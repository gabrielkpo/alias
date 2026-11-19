"""The bridge's second pass: a value aliased somewhere in a request gets the same alias
wherever else it is written, with other white space or case, without slowing down on long
conversations. Fictitious values only (tests/README.md)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from alias_pii.bridge import create_bridge
from alias_pii.entities import Entity, EntityType
from alias_pii.rules import RuleDetector

NAME = "Jean Dupont"
LOCAL = "http://127.0.0.1:8001"


class FakeMistral:
    def __init__(self):
        self.received = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        self.received.append(body)
        message = {"role": "assistant", "content": "ok"}
        return httpx.Response(200, json={"choices": [{"index": 0, "message": message}]})


class NameAfterTitle:
    """Finds NAME only after "M. ": a detector that misses it elsewhere, as a model can."""

    def detect(self, text):
        found = RuleDetector().detect(text)
        start = text.find(f"M. {NAME}")
        if start != -1:
            start += 3
            found.append(Entity(EntityType.PERSON, start, start + len(NAME), NAME, source="fake"))
        return sorted(found, key=lambda e: e.start)


def ask(client, *messages):
    return client.post(
        "/v1/chat/completions", json={"model": "mistral-small-latest", "messages": list(messages)}
    )


@pytest.mark.parametrize("written", ["Jean  Dupont", "Jean\nDupont", "Jean Dupont"])
def test_an_aliased_value_with_other_white_space_is_aliased_too(written):
    fake = FakeMistral()
    app = create_bridge(NameAfterTitle(), api_key="k", transport=httpx.MockTransport(fake))
    message = {"role": "user", "content": f"M. {NAME} écrit. Signé : {written}."}
    assert ask(TestClient(app, base_url=LOCAL), message).status_code == 200
    sent = fake.received[0]["messages"][0]["content"]
    assert sent == "M. [PERSON_1] écrit. Signé : [PERSON_1]."


def test_a_first_name_that_is_also_a_word_keeps_the_word():
    """Names are swept as found, in capitals or in title case only: "claire" the adjective and
    "pierre" the stone stay as they are, "CLAIRE" is the name."""
    fake = FakeMistral()

    class FirstNames:
        def detect(self, text):
            found = []
            for name in ("Claire", "Pierre"):
                start = text.find(name)
                if start == 0 or (start > 0 and text[start - 1] == " " and start < 12):
                    found.append(Entity(EntityType.PERSON, start, start + len(name), name))
            return sorted(found, key=lambda e: e.start)

    app = create_bridge(FirstNames(), api_key="k", transport=httpx.MockTransport(fake))
    text = "Claire et Pierre demandent une réponse claire sur la pierre. CLAIRE signe."
    assert (
        ask(TestClient(app, base_url=LOCAL), {"role": "user", "content": text}).status_code == 200
    )
    assert fake.received[0]["messages"][0]["content"] == (
        "[PERSON_1] et [PERSON_2] demandent une réponse claire sur la pierre. [PERSON_1] signe."
    )


def test_the_sweep_stays_fast_with_many_values():
    """500 aliased values over a 190,000-character conversation: one scan, not values x
    characters (it took seconds before)."""
    import time

    from alias_pii.bridge import Sweep

    values = [Entity(EntityType.EMAIL, 0, 0, f"user{i}@example.com") for i in range(500)]
    text = " ".join(f"mot{i} user{i % 500}@example.com" for i in range(9000))[:190_000]
    start = time.perf_counter()
    swept = Sweep(values).replace(text, lambda entity: "[EMAIL]")
    assert time.perf_counter() - start < 1.0
    assert "@example.com" not in swept.rsplit(" ", 1)[0]

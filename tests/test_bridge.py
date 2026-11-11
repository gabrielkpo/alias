import json

import httpx
from fastapi.testclient import TestClient

from alias_pii.bridge import create_bridge
from alias_pii.entities import Entity, EntityType
from alias_pii.rules import RuleDetector

# Fictitious values only (tests/README.md).
NAME = "Jean Dupont"
IBAN = "FR76 3000 6000 0112 3456 7890 189"
EMAIL = "jean.dupont@example.com"


class Names:
    """Stands in for the model: finds NAME, plus everything the rules find."""

    def detect(self, text):
        found = RuleDetector().detect(text)
        start = text.find(NAME)
        while start != -1:
            found.append(Entity(EntityType.PERSON, start, start + len(NAME), NAME, source="fake"))
            start = text.find(NAME, start + 1)
        return sorted(found, key=lambda e: e.start)


class FakeMistral:
    """Records what the provider receives; answers by echoing the aliases of the last message."""

    def __init__(self, reply=None, status=200):
        self.received = []
        self.headers = []
        self.reply, self.status = reply, status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.headers.append(dict(request.headers))
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "mistral-small-latest"}]})
        body = json.loads(request.content)
        self.received.append(body)
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "rate limited"})
        content = self.reply or f"Bien reçu : {body['messages'][-1]['content']}"
        return httpx.Response(
            200,
            json={"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]},
        )


def bridge(fake, api_key="test-key"):
    app = create_bridge(Names(), api_key=api_key, transport=httpx.MockTransport(fake))
    return TestClient(app)


def ask(client, *messages, **extra):
    return client.post(
        "/v1/chat/completions",
        json={"model": "mistral-small-latest", "messages": list(messages), **extra},
    )


def test_nothing_personal_reaches_the_provider_and_the_answer_is_restored():
    fake = FakeMistral()
    text = f"Écrire à {NAME} ({EMAIL}), virement sur {IBAN}."
    response = ask(bridge(fake), {"role": "user", "content": text})
    assert response.status_code == 200
    sent = json.dumps(fake.received, ensure_ascii=False)
    for value in (NAME, EMAIL, IBAN):
        assert value not in sent
    assert fake.received[0]["messages"][0]["content"] == (
        "Écrire à [PERSON_1] ([EMAIL_1]), virement sur [IBAN_1]."
    )
    assert fake.received[0]["model"] == "mistral-small-latest"  # other fields pass through
    answer = response.json()["choices"][0]["message"]["content"]
    assert answer == f"Bien reçu : {text}"
    assert response.headers["x-alias-masked"] == "3"
    assert response.headers["x-alias-restored"] == "3"


def test_a_value_keeps_its_alias_across_the_turns_of_a_conversation():
    fake = FakeMistral(reply="ok")
    first = {"role": "user", "content": f"Le client est {NAME}."}
    reply = {"role": "assistant", "content": f"Noté pour {NAME}."}  # restored by the bridge before
    second = {"role": "user", "content": f"Rappelle {NAME} au sujet de {IBAN}."}
    ask(bridge(fake), {"role": "system", "content": "Tu es un assistant."}, first, reply, second)
    contents = [m["content"] for m in fake.received[0]["messages"]]
    assert contents == [
        "Tu es un assistant.",
        "Le client est [PERSON_1].",
        "Noté pour [PERSON_1].",
        "Rappelle [PERSON_1] au sujet de [IBAN_1].",
    ]


def test_text_parts_are_masked_other_parts_passed_as_they_are():
    fake = FakeMistral(reply="ok")
    image = {"type": "image_url", "image_url": {"url": "https://example.com/x.png"}}
    content = [{"type": "text", "text": f"Qui est {NAME} ?"}, image]
    ask(bridge(fake), {"role": "user", "content": content})
    parts = fake.received[0]["messages"][0]["content"]
    assert parts == [{"type": "text", "text": "Qui est [PERSON_1] ?"}, image]


def test_an_alias_the_answer_invents_is_left_as_it_is():
    fake = FakeMistral(reply="Voir [PERSON_1] et [PERSON_9].")
    response = ask(bridge(fake), {"role": "user", "content": f"Contact : {NAME}."})
    assert response.json()["choices"][0]["message"]["content"] == f"Voir {NAME} et [PERSON_9]."


def test_a_checksummed_value_left_in_clear_stops_the_request():
    class Nothing:
        def detect(self, text):
            return []

    fake = FakeMistral()
    app = create_bridge(Nothing(), api_key="k", transport=httpx.MockTransport(fake))
    response = ask(TestClient(app), {"role": "user", "content": f"IBAN {IBAN}"})
    assert response.status_code == 422
    assert fake.received == []  # nothing was sent


def test_the_key_the_tool_sends_is_used_when_the_bridge_has_none():
    fake = FakeMistral(reply="ok")
    client = bridge(fake, api_key=None)
    assert ask(client, {"role": "user", "content": "Bonjour"}).status_code == 401
    response = client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "Bonjour"}]},
        headers={"Authorization": "Bearer from-the-tool"},
    )
    assert response.status_code == 200
    assert fake.headers[-1]["authorization"] == "Bearer from-the-tool"


def test_provider_errors_are_passed_through_and_streaming_is_refused_for_now():
    fake = FakeMistral(status=429)
    client = bridge(fake)
    assert ask(client, {"role": "user", "content": "Bonjour"}).status_code == 429
    assert ask(client, {"role": "user", "content": "Bonjour"}, stream=True).status_code == 501


def test_models_are_relayed():
    response = bridge(FakeMistral()).get("/v1/models")
    assert response.json()["data"][0]["id"] == "mistral-small-latest"


def test_the_openai_sdk_works_by_changing_only_its_base_url():
    """A tool written for the provider keeps its code: the official SDK pointed at the bridge."""
    import asyncio

    import pytest

    openai = pytest.importorskip("openai")
    fake = FakeMistral()
    app = create_bridge(Names(), api_key="k", transport=httpx.MockTransport(fake))

    async def call():
        sdk = openai.AsyncOpenAI(
            base_url="http://bridge/v1",
            api_key="unused",
            http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
        )
        return await sdk.chat.completions.create(
            model="mistral-small-latest", messages=[{"role": "user", "content": f"Salut {NAME}"}]
        )

    answer = asyncio.run(call())
    assert answer.choices[0].message.content == f"Bien reçu : Salut {NAME}"
    assert NAME not in json.dumps(fake.received)

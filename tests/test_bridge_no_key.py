"""A bridge holding no Mistral key passes on each tool's own key, but never the local token
tools were given: sent to Mistral it would be taken for a key. Fictitious values only."""

import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from alias_pii.bridge import create_bridge
from alias_pii.rules import RuleDetector

pytest.importorskip("keyring")

from alias_pii import cli  # noqa: E402

LOCAL = "http://127.0.0.1:8001"
TOKEN = "t" * 40
BODY = {"model": "m", "messages": [{"role": "user", "content": "Bonjour."}]}


def provider(seen):
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        message = {"role": "assistant", "content": "ok"}
        return httpx.Response(200, json={"choices": [{"index": 0, "message": message}]})

    return httpx.MockTransport(answer)


def test_the_local_token_is_refused_not_forwarded_when_the_bridge_holds_no_key():
    seen = []
    app = create_bridge(RuleDetector(), transport=provider(seen), idle_token=TOKEN)
    client = TestClient(app, base_url=LOCAL)
    refused = client.post(
        "/v1/chat/completions", json=BODY, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert refused.status_code == 401 and "no Mistral key" in refused.text
    own = client.post("/v1/chat/completions", json=BODY, headers={"Authorization": "Bearer own"})
    assert own.status_code == 200
    assert seen == ["Bearer own"]


def test_the_app_without_a_key_still_names_its_token(monkeypatch):
    class Model:
        def detect(self, text):
            return []

    served = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **options: served.update(app=app))
    monkeypatch.setattr(cli, "published_model", lambda: "folder")
    monkeypatch.setattr(cli, "model_detector", lambda folder: Model())
    monkeypatch.delenv("ALIAS_MODEL", raising=False)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps({"token": TOKEN}) + "\n"))
    assert cli.main(["serve", "--secrets-stdin"]) == 0
    client = TestClient(served["app"], base_url=LOCAL)
    answer = client.post(
        "/v1/chat/completions", json=BODY, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert answer.status_code == 401


def test_serve_without_a_key_refuses_the_token_left_in_the_keychain(monkeypatch):
    import keyring

    class Model:
        def detect(self, text):
            return []

    stored = {(cli.KEYCHAIN_SERVICE, cli.TOKEN_ACCOUNT): TOKEN}
    monkeypatch.setattr(keyring, "get_password", lambda s, a: stored.get((s, a)))
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("ALIAS_TOKEN", raising=False)
    monkeypatch.delenv("ALIAS_MODEL", raising=False)
    served = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **options: served.update(app=app))
    monkeypatch.setattr(cli, "published_model", lambda: "folder")
    monkeypatch.setattr(cli, "model_detector", lambda folder: Model())
    assert cli.main(["serve"]) == 0
    client = TestClient(served["app"], base_url=LOCAL)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert client.post("/v1/chat/completions", json=BODY, headers=headers).status_code == 401

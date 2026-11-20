"""The development entry point (`python -m alias_pii.bridge`) gets the same protection as
`alias-pii serve`: loopback only, and a local token when it holds MISTRAL_API_KEY."""

import pytest
from fastapi.testclient import TestClient

from alias_pii import bridge
from alias_pii.rules import RuleDetector

BODY = {"model": "m", "messages": [{"role": "user", "content": "Bonjour."}]}


def test_the_development_entry_point_listens_locally_and_asks_for_a_token(monkeypatch, capsys):
    pytest.importorskip("alias_pii.app")
    import alias_pii.app as app_module

    served = {}
    monkeypatch.setenv("MISTRAL_API_KEY", "not-a-real-key")
    monkeypatch.setattr("sys.argv", ["bridge", "--rules-only"])
    monkeypatch.setattr(app_module, "load_detector", lambda model: (RuleDetector(), "rules"))
    monkeypatch.setattr("uvicorn.run", lambda app, **options: served.update(app=app, **options))
    bridge.main()
    assert served["host"] == "127.0.0.1"
    token = capsys.readouterr().err.rsplit(": ", 1)[1].strip()
    client = TestClient(served["app"], base_url="http://127.0.0.1:8001")
    assert client.post("/v1/chat/completions", json=BODY).status_code == 401
    with pytest.raises(SystemExit):
        bridge.options(["--rules-only", "--host", "0.0.0.0"])
    headers = {"Authorization": f"Bearer {token}"}  # the token printed is the one to send
    assert client.post("/v1/chat/completions", json={}, headers=headers).status_code == 400

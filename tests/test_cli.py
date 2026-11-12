"""`alias-pii`: the keychain commands, model resolution and `serve` wiring, without a real model,
a real keychain or a network call (each is replaced)."""

import pytest

pytest.importorskip("keyring")
pytest.importorskip("fastapi")

import keyring  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from keyring.errors import PasswordDeleteError  # noqa: E402

from alias_pii import cli  # noqa: E402

SECRET = "sk-test-not-a-real-key"


@pytest.fixture
def keychain(monkeypatch):
    store = {}

    def delete(service, account):
        if (service, account) not in store:
            raise PasswordDeleteError("absent")
        del store[(service, account)]

    monkeypatch.setattr(keyring, "get_password", lambda s, a: store.get((s, a)))
    monkeypatch.setattr(keyring, "set_password", lambda s, a, v: store.__setitem__((s, a), v))
    monkeypatch.setattr(keyring, "delete_password", delete)
    return store


def test_the_key_is_stored_in_the_keychain_and_never_shown(keychain, monkeypatch, capsys):
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: f"  {SECRET}\n")
    assert cli.main(["key", "set"]) == 0
    assert keychain == {("alias-pii", "mistral"): SECRET}
    assert cli.main(["key", "status"]) == 0
    assert cli.main(["key", "delete"]) == 0
    assert cli.main(["key", "delete"]) == 0
    assert keychain == {}
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: " ")
    assert cli.main(["key", "set"]) == 1
    assert keychain == {}


def test_the_published_model_is_downloaded_once_at_a_pinned_revision(monkeypatch, tmp_path):
    pytest.importorskip("huggingface_hub")
    from huggingface_hub.errors import LocalEntryNotFoundError

    calls = []

    def snapshot_download(repo, **options):
        calls.append(options)
        if options.get("local_files_only"):
            raise LocalEntryNotFoundError("not cached")
        return str(tmp_path)

    monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot_download)
    assert cli.published_model() == tmp_path
    assert [c.get("local_files_only", False) for c in calls] == [True, False]
    assert all(c["revision"] == cli.MODEL_REVISION and len(c["revision"]) == 40 for c in calls)
    assert all(c["allow_patterns"] == cli.MODEL_FILES for c in calls)


def test_a_folder_without_an_onnx_model_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        cli.model_detector(tmp_path)


def test_serve_uses_the_keychain_key_and_listens_on_loopback(keychain, monkeypatch):
    served = {}

    def run(app, host, port, **options):
        served.update(app=app, host=host, port=port)

    class Model:
        def detect(self, text):
            return []

    monkeypatch.setattr("uvicorn.run", run)
    monkeypatch.setattr(cli, "published_model", lambda: "folder")
    monkeypatch.setattr(cli, "model_detector", lambda folder: Model())
    monkeypatch.setenv("MISTRAL_API_KEY", "from-the-environment")
    monkeypatch.delenv("ALIAS_MODEL", raising=False)
    keychain[("alias-pii", "mistral")] = SECRET
    assert cli.main(["serve"]) == 0
    assert (served["host"], served["port"]) == ("127.0.0.1", 8001)
    client = TestClient(served["app"], base_url="http://127.0.0.1:8001")
    assert client.get("/health").json()["detector"] == "rules+model"
    token = keychain[("alias-pii", "local-token")]
    assert len(token) >= 40 and token != SECRET
    assert client.get("/v1/models").status_code == 401  # the bridge holds a key: token needed
    assert cli.main(["serve", "--rules-only", "--port", "9000"]) == 0
    health = TestClient(served["app"], base_url="http://127.0.0.1:9000").get("/health").json()
    assert (health["detector"], served["port"]) == ("rules", 9000)
    with pytest.raises(SystemExit):
        cli.main(["serve", "--rules-only", "--model", "folder"])


def test_the_local_token_is_created_once_and_shown_on_request(keychain, capsys):
    assert cli.main(["key", "token"]) == 0
    first = capsys.readouterr().out.strip()
    assert cli.main(["key", "token"]) == 0
    assert capsys.readouterr().out.strip() == first == keychain[("alias-pii", "local-token")]


def test_without_a_stored_key_tools_send_their_own(keychain, monkeypatch):
    served = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **options: served.update(app=app))
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("ALIAS_MODEL", raising=False)
    assert cli.main(["serve", "--rules-only"]) == 0
    assert ("alias-pii", "local-token") not in keychain

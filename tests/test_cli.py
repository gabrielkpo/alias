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


def test_without_a_keychain_the_token_lives_for_one_run(monkeypatch, capsys):
    from keyring.errors import NoKeyringError

    def broken(*args):
        raise NoKeyringError("none")

    served = {}
    monkeypatch.setattr(keyring, "get_password", broken)
    monkeypatch.setattr("uvicorn.run", lambda app, **options: served.update(app=app))
    monkeypatch.setenv("MISTRAL_API_KEY", "from-the-environment")
    monkeypatch.delenv("ALIAS_MODEL", raising=False)
    assert cli.main(["key", "token"]) == 1
    assert cli.main(["serve", "--rules-only"]) == 0
    token = capsys.readouterr().err.split("API key): ")[1].split()[0]
    client = TestClient(served["app"], base_url="http://127.0.0.1:8001")
    assert client.post("/v1/chat/completions", json={}).status_code == 401
    headers = {"Authorization": f"Bearer {token}"}
    # Past the token check, an empty body is refused before anything is sent (no network).
    assert client.post("/v1/chat/completions", json={}, headers=headers).status_code == 400


def test_a_container_binds_everywhere_only_with_a_key_and_a_token(keychain, monkeypatch, capsys):
    served = {}
    monkeypatch.setattr(
        "uvicorn.run", lambda app, host, port, **o: served.update(app=app, host=host)
    )
    monkeypatch.delenv("ALIAS_MODEL", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(SystemExit):  # no key held: a bridge open to the network is refused
        cli.main(["serve", "--rules-only", "--host", "0.0.0.0"])
    monkeypatch.setenv("MISTRAL_API_KEY", "from-the-environment")
    monkeypatch.setenv("ALIAS_TOKEN", "short")
    with pytest.raises(SystemExit):
        cli.main(["serve", "--rules-only", "--host", "0.0.0.0"])
    token = "t" * 43
    monkeypatch.setenv("ALIAS_TOKEN", token)
    monkeypatch.setenv("ALIAS_ALLOWED_HOSTS", "alias-bridge, other")
    assert cli.main(["serve", "--rules-only", "--host", "0.0.0.0"]) == 0
    assert served["host"] == "0.0.0.0"
    assert ("alias-pii", "local-token") not in keychain  # the given token, not a stored one
    client = TestClient(served["app"], base_url="http://alias-bridge:8001")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/v1/chat/completions", json={}, headers=headers).status_code == 400
    stranger = TestClient(served["app"], base_url="http://evil.example:8001")
    assert stranger.post("/v1/chat/completions", json={}, headers=headers).status_code == 403
    assert token not in capsys.readouterr().err


def test_fetch_downloads_the_model_and_prints_where(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "published_model", lambda: tmp_path)
    assert cli.main(["fetch"]) == 0
    assert capsys.readouterr().out.strip() == str(tmp_path)


def test_an_app_passes_the_key_on_standard_input(keychain, monkeypatch, capsys):
    import io

    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(f"{SECRET}\n"))
    assert cli.main(["key", "set", "--stdin"]) == 0
    assert keychain[("alias-pii", "mistral")] == SECRET
    assert SECRET not in capsys.readouterr().out


def test_fetch_progress_prints_json_lines_then_ready(monkeypatch, tmp_path, capsys):
    import json
    import time

    pytest.importorskip("huggingface_hub")
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(tmp_path))
    blobs = tmp_path / f"models--{cli.MODEL_REPO.replace('/', '--')}" / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "left-by-an-old-download.incomplete").write_bytes(b"x" * 70)

    def download():
        for part in range(4):
            (blobs / f"part{part}").write_bytes(b"x" * 25)
            time.sleep(0.03)
        return tmp_path

    monkeypatch.setattr(cli, "cached_model", lambda: None)
    monkeypatch.setattr(cli, "_model_bytes", lambda: 100)
    monkeypatch.setattr(cli, "published_model", download)
    assert cli.fetch_with_progress(every=0.01) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[-1] == {"ready": True}
    progress = [line for line in lines if "done" in line]
    assert progress and all(line["total"] == 100 for line in progress)
    done = [line["done"] for line in progress]
    assert done == sorted(done) and 0 <= done[0] and done[-1] <= 100  # the old 70 bytes not counted


def test_fetch_progress_says_ready_at_once_when_the_model_is_cached(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "cached_model", lambda: tmp_path)
    assert cli.main(["fetch", "--progress"]) == 0
    assert capsys.readouterr().out.strip() == '{"ready": true}'


def test_fetch_progress_reports_a_failed_download(monkeypatch, tmp_path, capsys):
    import json

    pytest.importorskip("huggingface_hub")
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(tmp_path))

    def download():
        raise OSError("network is unreachable")

    monkeypatch.setattr(cli, "cached_model", lambda: None)
    monkeypatch.setattr(cli, "_model_bytes", lambda: None)
    monkeypatch.setattr(cli, "published_model", download)
    assert cli.fetch_with_progress(every=0.01) == 1
    last = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert last == {"error": "OSError: network is unreachable"}


def test_a_key_mistral_refuses_is_not_stored(keychain, monkeypatch, capsys):
    import io

    refused = "Mistral refused this key. Check it and paste it again."
    monkeypatch.setattr(cli, "key_refused", lambda value: refused if value == "bad" else None)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("bad\n"))
    assert cli.main(["key", "set", "--stdin", "--check"]) == 1
    assert keychain == {}
    assert refused in capsys.readouterr().err
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(f"{SECRET}\n"))
    assert cli.main(["key", "set", "--stdin", "--check"]) == 0
    assert keychain[("alias-pii", "mistral")] == SECRET


@pytest.mark.parametrize(
    ("status", "expected"),
    [(200, None), (401, "refused"), (403, "refused"), (503, "answered 503"), (None, "reached")],
)
def test_the_key_check_lists_mistral_models_with_the_key(monkeypatch, status, expected):
    import httpx

    seen = {}

    def get(url, headers, timeout):
        seen.update(url=url, auth=headers["Authorization"])
        if status is None:
            raise httpx.ConnectError("no route")
        return httpx.Response(status)

    monkeypatch.setattr(httpx, "get", get)
    answer = cli.key_refused(SECRET)
    assert seen == {"url": "https://api.mistral.ai/v1/models", "auth": f"Bearer {SECRET}"}
    assert answer is None if expected is None else expected in answer
    assert answer is None or SECRET not in answer


def test_the_app_gives_the_key_and_token_on_standard_input_never_the_keychain(monkeypatch):
    import io
    import json

    def no_keychain(*args):
        raise AssertionError("serve --secrets-stdin must not touch the keychain")

    monkeypatch.setattr(keyring, "get_password", no_keychain)
    monkeypatch.setattr(keyring, "set_password", no_keychain)

    class Model:
        def detect(self, text):
            return []

    served = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **options: served.update(app=app))
    monkeypatch.setattr(cli, "published_model", lambda: "folder")
    monkeypatch.setattr(cli, "model_detector", lambda folder: Model())
    monkeypatch.delenv("ALIAS_MODEL", raising=False)
    token = "t" * 40
    line = json.dumps({"key": SECRET, "token": token}) + "\n"
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(line))
    assert cli.main(["serve", "--secrets-stdin"]) == 0
    client = TestClient(served["app"], base_url="http://127.0.0.1:8001")
    assert client.post("/v1/chat/completions", json={}).status_code == 401
    ok = client.post("/v1/chat/completions", json={}, headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 400  # past the token check, refused before any call to Mistral

    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("{}\n"))
    assert cli.main(["serve", "--secrets-stdin"]) == 0  # no key: tools send their own
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps({"key": SECRET}) + "\n"))
    with pytest.raises(SystemExit):
        cli.main(["serve", "--secrets-stdin"])  # a key without a token is refused
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("null\n"))
    with pytest.raises(SystemExit):
        cli.main(["serve", "--secrets-stdin"])  # not an object: refused in one line


def test_key_check_asks_mistral_and_stores_nothing(keychain, monkeypatch, capsys):
    import io

    monkeypatch.setattr(cli, "key_refused", lambda v: None if v == SECRET else "Mistral refused")
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(f"{SECRET}\n"))
    assert cli.main(["key", "check", "--stdin"]) == 0
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("bad\n"))
    assert cli.main(["key", "check", "--stdin"]) == 1
    assert keychain == {}
    out = capsys.readouterr()
    assert "Mistral refused" in out.err and SECRET not in out.out + out.err

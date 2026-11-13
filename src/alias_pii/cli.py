"""`alias-pii`: run Alias Bridge on this machine, the Mistral key kept in the OS keychain.

    alias-pii key set      # asks for the Mistral key and stores it in the keychain
    alias-pii serve        # http://127.0.0.1:8001/v1 for tools written for Mistral
    alias-pii key token    # the local token tools send as their API key
    alias-pii key status   # whether a key is stored (it is never shown)
    alias-pii key delete
    alias-pii fetch        # download the model now (a container image does it at build time)
    alias-pii fetch --progress   # the same, with a JSON line of progress every half second (an app)

The detector is the published model run by ONNX Runtime, without PyTorch: it is downloaded once,
at a pinned revision (about 600 MB, into the Hugging Face cache), then read from the disk.
`--model` gives a local folder instead (an ONNX export with its tokenizer); `--rules-only` runs
the rules alone, which mask no names or addresses. The key comes from the keychain, else from
`MISTRAL_API_KEY`, else from the `Authorization` header each tool sends. When the bridge holds
the key, a tool must send the bridge's local token as its API key instead, so no other program or
account on the machine can spend the key.
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import secrets
import sys
import threading
from pathlib import Path

MODEL_REPO = "Gabrielkph/alias-mmbert-small"
MODEL_REVISION = "41638ca5485ab9b963e7e900914fe417bc314907"  # tag v1.0, pinned by commit
MODEL_FILES = [
    "onnx/model.onnx",
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
]
KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT = "alias-pii", "mistral"
TOKEN_ACCOUNT = "local-token"  # what tools send to the bridge when it holds the Mistral key
PORT = 8001
log = logging.getLogger("alias.cli")


def cached_model() -> Path | None:
    """The published model's folder if it is already on the disk, else None (no network)."""
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    options = {"revision": MODEL_REVISION, "allow_patterns": MODEL_FILES}
    try:
        return Path(snapshot_download(MODEL_REPO, local_files_only=True, **options))
    except LocalEntryNotFoundError:
        return None


def published_model() -> Path:
    """The published model's folder, downloaded on the first call only."""
    from huggingface_hub import snapshot_download

    cached = cached_model()
    if cached is not None:
        return cached
    print(f"Downloading the model {MODEL_REPO} once (about 600 MB)...", file=sys.stderr)
    return Path(snapshot_download(MODEL_REPO, revision=MODEL_REVISION, allow_patterns=MODEL_FILES))


def _folder_bytes(folder: Path) -> int:
    """Bytes of the regular files under `folder` (the cache's links are not counted twice)."""
    if not folder.is_dir():
        return 0
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file() and not p.is_symlink())


def _model_bytes() -> int | None:
    """Size of the model's files at the pinned revision, asked to the Hub; None if unknown."""
    from huggingface_hub import HfApi

    try:
        files = HfApi().get_paths_info(MODEL_REPO, MODEL_FILES, revision=MODEL_REVISION)
    except Exception:  # the size only draws a progress bar: the download reports real errors
        return None
    return sum(getattr(f, "size", 0) or 0 for f in files) or None


def fetch_with_progress(every: float = 0.5) -> int:
    """Downloads the model like `fetch`, printing one JSON line every `every` seconds:
    `{"done": bytes, "total": bytes or null}`, then `{"ready": true}` or `{"error": text}`.
    The desktop app reads them to draw its progress bar. `done` is what the model's cache folder
    gained since the start, so files left by an interrupted download are not counted."""

    def say(**fields: object) -> None:
        print(json.dumps(fields), flush=True)

    if cached_model() is not None:
        say(ready=True)
        return 0
    from huggingface_hub import constants

    cache = Path(constants.HF_HUB_CACHE) / f"models--{MODEL_REPO.replace('/', '--')}"
    total, start, outcome = _model_bytes(), _folder_bytes(cache), {}

    def download() -> None:
        try:
            published_model()
        except Exception as error:  # reported to the app as one line, then the exit code
            outcome["error"] = f"{type(error).__name__}: {error}"

    worker = threading.Thread(target=download, daemon=True)
    worker.start()
    while worker.is_alive():
        done = max(_folder_bytes(cache) - start, 0)
        say(done=min(done, total) if total else done, total=total)
        worker.join(every)
    if "error" in outcome:
        say(error=outcome["error"])
        return 1
    say(ready=True)
    return 0


def key_refused(value: str) -> str | None:
    """None when Mistral accepts the key (listing the models costs nothing), else why not."""
    import httpx

    from alias_pii.bridge import UPSTREAM

    try:
        answer = httpx.get(
            f"{UPSTREAM}/v1/models", headers={"Authorization": f"Bearer {value}"}, timeout=15
        )
    except httpx.HTTPError:
        return "Mistral could not be reached. Check the connection and try again."
    if answer.status_code in (401, 403):
        return "Mistral refused this key. Check it and paste it again."
    if answer.status_code >= 400:
        return f"Mistral answered {answer.status_code}. Try again in a moment."
    return None


def model_detector(folder: Path):
    """Rules plus the ONNX model found in `folder` (`onnx/model.onnx` or `model.onnx`)."""
    from alias_pii.detector import RulesAndModel
    from alias_pii.onnx_export import OnnxDetector

    model_file = "onnx/model.onnx" if (folder / "onnx" / "model.onnx").is_file() else "model.onnx"
    if not (folder / model_file).is_file():
        raise SystemExit(f"no ONNX model in {folder}: export one with alias_pii.onnx_export")
    return RulesAndModel(OnnxDetector(str(folder), model_file=model_file))


def stored_key() -> str | None:
    """The key in the OS keychain, or None (no key, or no keychain on this machine)."""
    import keyring
    from keyring.errors import KeyringError

    try:
        return keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    except KeyringError:
        return None


def local_token() -> tuple[str, bool]:
    """The bridge's local token, created and stored in the keychain on first use, and whether it
    is stored: ALIAS_TOKEN when set (a container), else with no usable keychain, a token for this
    run only."""
    given = os.environ.get("ALIAS_TOKEN")
    if given is not None:  # set by the user, for a container where no keychain exists
        if len(given) < 32:
            raise SystemExit("ALIAS_TOKEN must be at least 32 characters (secrets.token_urlsafe)")
        return given, True
    import keyring
    from keyring.errors import KeyringError

    try:
        token = keyring.get_password(KEYCHAIN_SERVICE, TOKEN_ACCOUNT)
        if not token:
            token = secrets.token_urlsafe(32)
            keyring.set_password(KEYCHAIN_SERVICE, TOKEN_ACCOUNT, token)
        return token, True
    except KeyringError:
        return secrets.token_urlsafe(32), False


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="alias-pii", description=__doc__.splitlines()[0])
    commands = root.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run Alias Bridge on 127.0.0.1")
    serve.add_argument(
        "--model",
        default=os.environ.get("ALIAS_MODEL"),
        help="a local ONNX model folder instead of the published model",
    )
    serve.add_argument(
        "--rules-only",
        action="store_true",
        help="no model: names and addresses reach Mistral in clear",
    )
    serve.add_argument(
        "--secrets-stdin",
        action="store_true",
        help='read {"key": ..., "token": ...} as one JSON line on standard input, not the '
        "keychain (the desktop app, which keeps them in its own keychain item)",
    )
    serve.add_argument("--port", type=int, default=PORT)
    serve.add_argument(
        "--host",
        default=os.environ.get("ALIAS_HOST", "127.0.0.1"),
        help="127.0.0.1 by default; 0.0.0.0 only inside a container published on 127.0.0.1",
    )
    serve.add_argument(
        "--allowed-host",
        action="append",
        default=[h for h in os.environ.get("ALIAS_ALLOWED_HOSTS", "").split(",") if h.strip()],
        help="a Host name tools may use besides localhost (another container's view of it)",
    )
    fetch = commands.add_parser("fetch", help="download the published model now (kept on disk)")
    fetch.add_argument(
        "--progress", action="store_true", help="print the progress as JSON lines (an app)"
    )
    key = commands.add_parser("key", help="the Mistral key in the OS keychain")
    key.add_argument("action", choices=["set", "status", "delete", "token", "check"])
    key.add_argument(
        "--stdin", action="store_true", help="set: read the key from standard input (an app)"
    )
    key.add_argument(
        "--check", action="store_true", help="set: store the key only if Mistral accepts it"
    )
    # `key check --stdin`: ask Mistral whether a key works, without storing it (the app stores it)
    return root


def key_command(action: str, from_stdin: bool = False, check: bool = False) -> int:
    if action == "check":  # no keychain: the key comes on standard input and is not stored
        value = sys.stdin.readline().strip() if from_stdin else getpass.getpass("Key: ").strip()
        refused = key_refused(value) if value else "No key given."
        if refused:
            print(refused, file=sys.stderr)
            return 1
        print("Mistral accepted the key.")
        return 0
    import keyring
    from keyring.errors import KeyringError, PasswordDeleteError

    try:
        if action == "token":  # the user asked for it, to give it to their tools
            token, stored = local_token()
            if not stored:
                print(
                    "No usable keychain: serve prints a new token at each start.", file=sys.stderr
                )
                return 1
            print(token)
        elif action == "set":
            if from_stdin:  # the desktop app passes it on a pipe, never on the command line
                value = sys.stdin.readline().strip()
            else:
                value = getpass.getpass("Mistral API key (not shown): ").strip()
            if not value:
                print("No key given: nothing stored.", file=sys.stderr)
                return 1
            refused = key_refused(value) if check else None
            if refused:
                print(refused, file=sys.stderr)
                return 1
            keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, value)
            print(f"Key stored in {keyring.get_keyring().name}.")
        elif action == "status":
            stored = stored_key() is not None
            print("A key is stored in the keychain." if stored else "No key in the keychain.")
        else:
            try:
                keyring.delete_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
            except PasswordDeleteError:
                print("No key in the keychain.")
                return 0
            print("Key deleted from the keychain.")
    except KeyringError as error:
        print(f"No usable keychain on this machine ({type(error).__name__}).", file=sys.stderr)
        return 1
    return 0


def serve_command(args: argparse.Namespace) -> int:
    import uvicorn

    from alias_pii.bridge import LOCAL_HOSTS, create_bridge
    from alias_pii.rules import RuleDetector

    if args.model and args.rules_only:
        raise SystemExit("--rules-only and a model (--model or ALIAS_MODEL) exclude each other")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if args.rules_only:
        detector, name = RuleDetector(), "rules"
        log.warning("rules only: names and addresses are NOT masked and reach Mistral in clear")
    else:
        folder = Path(args.model) if args.model else published_model()
        detector, name = model_detector(folder), "rules+model"
        log.info("detector: %s", name)
    token = None
    if args.secrets_stdin:
        # The desktop app owns the keychain item and passes its content on a pipe: this process
        # never touches the keychain, so macOS never asks the user about it.
        secrets_given = json.loads(sys.stdin.readline() or "{}")
        api_key = secrets_given.get("key") or None
        token = secrets_given.get("token") if api_key else None
        if api_key and (not token or len(token) < 32):
            raise SystemExit("--secrets-stdin: a key needs a local token of 32 characters or more")
        if api_key:
            log.info("key and local token given by the app")
        else:
            log.info("no key given by the app: each tool's own key is used")
    else:
        api_key = stored_key() or os.environ.get("MISTRAL_API_KEY")
    if api_key and token is None:
        # The bridge spends this key for whoever calls it: only a tool given the local token may.
        token, stored = local_token()
        if stored:
            log.info("tools send the local token as their API key: see alias-pii key token")
        else:  # no keychain: the token lives for this run only, so it is shown here
            print(f"Local token for this run (the tools' API key): {token}", file=sys.stderr)
    elif not api_key and not args.secrets_stdin:
        log.info("no stored key: each tool's own key is used (alias-pii key set to store one)")
    loopback = args.host in ("127.0.0.1", "::1", "localhost")
    if not loopback and not token:
        # Reachable from elsewhere (a container's network): a held key needs a token, and a
        # bridge without one would forward any caller's own key; both are refused.
        raise SystemExit(f"--host {args.host} needs the bridge's own key and a local token")
    hosts = (*LOCAL_HOSTS, *(h.strip() for h in args.allowed_host))
    app = create_bridge(
        detector, api_key=api_key, detector_name=name, local_token=token, allowed_hosts=hosts
    )
    print(f"Alias Bridge on http://{args.host}:{args.port}/v1", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "key":
        return key_command(args.action, args.stdin, args.check)
    if args.command == "fetch":
        if args.progress:
            return fetch_with_progress()
        print(published_model())
        return 0
    return serve_command(args)


if __name__ == "__main__":
    sys.exit(main())

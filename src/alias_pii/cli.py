"""`alias-pii`: run Alias Bridge on this machine, the Mistral key kept in the OS keychain.

    alias-pii key set      # asks for the Mistral key and stores it in the keychain
    alias-pii serve        # http://127.0.0.1:8001/v1 for tools written for Mistral
    alias-pii key status   # whether a key is stored (it is never shown)
    alias-pii key delete

The detector is the published model run by ONNX Runtime, without PyTorch: it is downloaded once,
at a pinned revision (about 600 MB, into the Hugging Face cache), then read from the disk.
`--model` gives a local folder instead (an ONNX export with its tokenizer); `--rules-only` runs
the rules alone, which mask no names or addresses. The key comes from the keychain, else from
`MISTRAL_API_KEY`, else from the `Authorization` header each tool sends.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
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
PORT = 8001
log = logging.getLogger("alias.cli")


def published_model() -> Path:
    """The published model's folder, downloaded on the first call only."""
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    options = {"revision": MODEL_REVISION, "allow_patterns": MODEL_FILES}
    try:
        return Path(snapshot_download(MODEL_REPO, local_files_only=True, **options))
    except LocalEntryNotFoundError:
        print(f"Downloading the model {MODEL_REPO} once (about 600 MB)...", file=sys.stderr)
        return Path(snapshot_download(MODEL_REPO, **options))


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
    serve.add_argument("--port", type=int, default=PORT)
    key = commands.add_parser("key", help="the Mistral key in the OS keychain")
    key.add_argument("action", choices=["set", "status", "delete"])
    return root


def key_command(action: str) -> int:
    import keyring
    from keyring.errors import KeyringError, PasswordDeleteError

    try:
        if action == "set":
            value = getpass.getpass("Mistral API key (not shown): ").strip()
            if not value:
                print("No key given: nothing stored.", file=sys.stderr)
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

    from alias_pii.bridge import create_bridge
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
    api_key = stored_key() or os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        log.info("no stored key: each tool's own key is used (alias-pii key set to store one)")
    app = create_bridge(detector, api_key=api_key, detector_name=name)
    print(f"Alias Bridge on http://127.0.0.1:{args.port}/v1", file=sys.stderr)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "key":
        return key_command(args.action)
    return serve_command(args)


if __name__ == "__main__":
    sys.exit(main())

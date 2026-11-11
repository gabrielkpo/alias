"""Alias Bridge: a local endpoint, compatible with Mistral's (and OpenAI's) chat API, that masks
every message before it leaves the machine and puts the real values back in the answer.

    uv run --extra app python -m alias_pii.bridge --model <checkpoint>

The user's tool keeps its code and only changes its base URL, from `https://api.mistral.ai/v1`
to `http://127.0.0.1:8001/v1`. For `POST /v1/chat/completions` the bridge:

1. masks the text of every message with **one alias table for the request**, aliases given in
   order of appearance: a client resends the whole history at each turn, so a value keeps its
   alias from one turn to the next without the bridge keeping any state;
2. checks the masked messages with the rules: a checksummed value still readable (an IBAN, a
   national ID) stops the request, since it would reach the provider in clear;
3. forwards the request to Mistral with the user's key (the bridge's own key, else the key the
   tool sent);
4. puts the values back in the answer, only for the aliases of this request (`masking.restore`),
   and returns it in the provider's format, with counts of what was masked in headers.

Nothing is logged but counts; no text is written to disk. `GET /v1/models` is relayed as is.
Streaming answers (`"stream": true`) come in the next version and are refused for now.
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
from collections import Counter

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from alias_pii import __version__
from alias_pii.entities import EntityType
from alias_pii.masking import AliasTable, Detector, MaskResult, mask, restore
from alias_pii.rules import RuleDetector

UPSTREAM = "https://api.mistral.ai"
# Values the rules prove by a checksum: if one is still readable after masking, the request stops.
CHECKED = frozenset({EntityType.IBAN, EntityType.NATIONAL_ID})
MAX_CHARS = 200_000  # the whole conversation of one request
log = logging.getLogger("alias.bridge")


class LeftInClear(Exception):
    """A checksummed value is still readable after masking."""


def mask_messages(
    messages: list[dict], detector: Detector
) -> tuple[list[dict], list[MaskResult], Counter]:
    """The messages with their text masked, the mask results (to restore the answer) and the
    count of values per type. Text is a message's `content` string, or the `text` of its
    `{"type": "text"}` parts; anything else (images, tool calls) is passed as it is."""
    table = AliasTable()
    results: list[MaskResult] = []
    counts: Counter = Counter()

    def masked(text: str) -> str:
        result = mask(text, detector, table)
        results.append(result)
        counts.update(e.type.value for e in result.entities)
        return result.text

    out = []
    for message in messages:
        message = dict(message)
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = masked(content)
        elif isinstance(content, list):
            message["content"] = [
                {**part, "text": masked(part["text"])}
                if isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
                else part
                for part in content
            ]
        out.append(message)
    return out, results, counts


def check_masked(results: list[MaskResult]) -> None:
    rules = RuleDetector()
    for result in results:
        if any(e.type in CHECKED for e in rules.detect(result.text)):
            raise LeftInClear


def restore_answer(data: dict, results: list[MaskResult]) -> tuple[dict, int]:
    """The provider's answer with the values back in each choice's message text; the number of
    aliases restored."""
    if not results:
        return data, 0
    restored = 0
    for choice in data.get("choices") or []:
        message = choice.get("message") if isinstance(choice, dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            back = restore(message["content"], *results)
            message["content"] = back.text
            restored += len(back.restored)
    return data, restored


def create_bridge(
    detector: Detector,
    api_key: str | None = None,
    upstream: str = UPSTREAM,
    transport: httpx.AsyncBaseTransport | None = None,
    max_chars: int = MAX_CHARS,
) -> FastAPI:
    """The bridge around one detector, loaded once by the caller. `api_key`: the Mistral key
    (else the one the client sends); `transport`: for tests, a fake provider."""
    app = FastAPI(title="Alias Bridge", version=__version__, docs_url=None, redoc_url=None)
    lock = threading.Lock()  # one detection at a time: CPU-bound, and the model is shared
    client = httpx.AsyncClient(base_url=upstream, transport=transport, timeout=120)

    def key(request: Request) -> str:
        if api_key:
            return api_key
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer ") and auth[7:].strip():
            return auth[7:].strip()
        raise HTTPException(401, "no Mistral API key: set one for the bridge or send it")

    def masked_request(body: dict) -> tuple[dict, list[MaskResult], Counter]:
        messages = body.get("messages")
        if not isinstance(messages, list):
            raise HTTPException(400, "'messages' must be a list")
        size = sum(len(str(m.get("content", ""))) for m in messages if isinstance(m, dict))
        if size > max_chars:
            raise HTTPException(413, f"conversation too long: at most {max_chars} characters")
        with lock:
            masked, results, counts = mask_messages(messages, detector)
        try:
            check_masked(results)
        except LeftInClear:
            raise HTTPException(
                422,
                "a checksummed value (IBAN, national ID) is still readable after masking: "
                "nothing was sent",
            ) from None
        return {**body, "messages": masked}, results, counts

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "upstream": upstream, "version": __version__}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Response:
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "the body must be JSON") from None
        if not isinstance(body, dict):
            raise HTTPException(400, "the body must be a JSON object")
        if body.get("stream"):
            raise HTTPException(501, "streaming answers are not supported yet: set stream false")
        token = key(request)
        outgoing, results, counts = await run_in_threadpool(masked_request, body)
        answer = await client.post(
            "/v1/chat/completions", json=outgoing, headers={"Authorization": f"Bearer {token}"}
        )
        if answer.status_code != 200:  # the provider's error, as it is (it only saw masked text)
            return Response(
                answer.content, answer.status_code, media_type=answer.headers.get("content-type")
            )
        data, restored = restore_answer(answer.json(), results)
        log.info("masked %s; restored %d", dict(counts), restored)
        return JSONResponse(
            data,
            headers={
                "X-Alias-Masked": str(sum(counts.values())),
                "X-Alias-Restored": str(restored),
            },
        )

    @app.get("/v1/models")
    async def models(request: Request) -> Response:
        answer = await client.get("/v1/models", headers={"Authorization": f"Bearer {key(request)}"})
        return Response(
            answer.content, answer.status_code, media_type=answer.headers.get("content-type")
        )

    return app


def main() -> None:
    from alias_pii.app import load_detector

    parser = argparse.ArgumentParser(description="Run the Alias Bridge in front of Mistral.")
    parser.add_argument("--model", default=os.environ.get("ALIAS_MODEL"), help="checkpoint")
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 only inside a container")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    detector, name = load_detector(args.model)
    log.info("detector: %s", name)
    app = create_bridge(detector, api_key=os.environ.get("MISTRAL_API_KEY"))
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

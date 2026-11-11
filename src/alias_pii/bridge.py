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
4. puts the values back in the answer, only for the aliases of this request (`masking.restore`)
   and never inside a link, and returns it in the provider's format, with counts in headers.

A request holding text the bridge does not mask (a field other than the settings, a message
`name`, a JSON schema, `prediction`...) is refused rather than forwarded with it.

Nothing is logged but counts; no text is written to disk. `GET /v1/models` is relayed as is.
Only local tools may call it: a request from a browser (an `Origin` header), with a non-local
`Host` (DNS rebinding) or a non-JSON body is refused, so a web page cannot spend the user's key.
Streaming answers (`"stream": true`) and tool calls come later and are refused for now.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import threading
from collections import Counter
from collections.abc import Awaitable, Callable

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
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
# What a request may hold besides `messages`: settings with no text of their own. Any other
# field (`prediction`, `user`, a JSON schema...) could carry personal data the bridge does not
# mask, so the request is refused rather than forwarded with it.
SETTINGS = frozenset(
    {
        "model",
        "temperature",
        "top_p",
        "max_tokens",
        "random_seed",
        "n",
        "presence_penalty",
        "frequency_penalty",
        "safe_prompt",
        "stream",
        "response_format",
        "stop",
    }
)
MESSAGE_KEYS = frozenset({"role", "content", "prefix"})
ROLES = frozenset({"system", "user", "assistant"})
# Where answer text may become a request of the client's own: a markdown link or image target
# (`](`), a reference definition (`]:`), an HTML tag or an autolink (`<`), a URL (`//`, `www.`).
# Markdown and HTML have too many forms (nested parentheses, escapes, targets on the next line,
# definitions in quotes) for a pattern to follow, so from such a mark to the end of the
# paragraph aliases stay masked: inline markdown never crosses a blank line.
# A `<` counts as a tag unless a space, `=` or digit follows (`a < b`, `<=`, `<3`): `<[PERSON_1]`
# becomes a tag once the name is put back, and `<a:b/title="...` is a tag to a browser even
# though it looks like an autolink.
# A backslash before a character counts too: a client that decodes the answer as JSON (or
# twice) turns `\u003c` into `<` and `\/\/` into `//`, marks the text here does not show.
TAG = r"<(?![\s=\d])|\\(?=\S)"
LINK_MARK = re.compile(rf"(?<=\])[(:]|{TAG}|//|www\.", re.IGNORECASE)
PARAGRAPH_END = re.compile(r"\n[ \t]*\n")
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


def unmaskable(body: dict) -> str | None:
    """Where the request holds text the bridge would forward without masking it, else None: a
    field that is not a setting, a message key other than role/content/prefix, a content that
    is neither text nor text and image parts, a JSON schema, a setting that is not a number."""
    for name in body:
        if name != "messages" and name not in SETTINGS:
            return f"'{name}'"
    if not isinstance(body.get("model", ""), str):
        return "'model'"
    for name in SETTINGS - {"model", "response_format", "stop"}:
        value = body.get(name)
        if value is not None and not isinstance(value, int | float | bool):
            return f"'{name}'"
    response_format = body.get("response_format")
    if response_format is not None and not (
        isinstance(response_format, dict)
        and set(response_format) <= {"type"}
        and response_format.get("type") in ("text", "json_object")
    ):
        return "'response_format' other than text or json_object (a schema's text is not masked)"
    stop = body.get("stop")
    if stop is not None and not (
        isinstance(stop, str) or (isinstance(stop, list) and all(isinstance(s, str) for s in stop))
    ):
        return "'stop'"
    messages = body.get("messages")
    for i, message in enumerate(messages if isinstance(messages, list) else []):
        where = f"messages[{i}]"
        if not isinstance(message, dict):
            return where
        for key in message:
            if key not in MESSAGE_KEYS:
                return f"{where}.{key}"
        if not isinstance(message.get("role"), str) or message["role"] not in ROLES:
            return f"{where}.role"
        if not isinstance(message.get("prefix", False), bool):
            return f"{where}.prefix"
        content = message.get("content")
        if content is None or isinstance(content, str):
            continue
        if not isinstance(content, list):
            return f"{where}.content"
        for j, part in enumerate(content):
            text = (
                isinstance(part, dict)
                and set(part) == {"type", "text"}
                and part["type"] == "text"
                and isinstance(part["text"], str)
            )
            image = isinstance(part, dict) and set(part) == {"type", "image_url"}
            if not (text or (image and part["type"] == "image_url")):
                return f"{where}.content[{j}]"
    return None


def stops(body: dict) -> list[str]:
    stop = body.get("stop")
    return [stop] if isinstance(stop, str) else list(stop or [])


def check_masked(results: list[MaskResult]) -> None:
    rules = RuleDetector()
    for result in results:
        if any(e.type in CHECKED for e in rules.detect(result.text)):
            raise LeftInClear


def link_spans(text: str, to_end: bool = False) -> list[tuple[int, int]]:
    """The parts of the text where aliases stay masked: from each link mark (`LINK_MARK`) to
    the end of its paragraph. From the first `<` or escape (`TAG`), or with `to_end`, to the end
    of the text: an HTML block can run across blank lines, a `>` in an attribute defeats
    counting, and an escape can hide any mark, a blank line included."""
    tag = re.search(TAG, text)
    first_tag = tag.start() if tag else len(text)
    spans: list[tuple[int, int]] = []
    position = 0
    while (mark := LINK_MARK.search(text, position)) and mark.start() < first_tag:
        end_of_paragraph = PARAGRAPH_END.search(text, mark.start())
        if to_end or not end_of_paragraph or end_of_paragraph.start() > first_tag:
            return [*spans, (mark.start(), len(text))]
        spans.append((mark.start(), end_of_paragraph.start()))
        position = end_of_paragraph.start()
    if first_tag < len(text):
        spans.append((first_tag, len(text)))
    return spans


def put_back(text: str, results: list[MaskResult], restored: set[str], to_end: bool = False) -> str:
    """The text with the values of this request's aliases put back, except in links and what
    follows them (`link_spans`): an alias there stays masked, so a client loading a link or an
    image sends no value."""

    def plain(segment: str) -> str:
        back = restore(segment, *results)
        restored.update(back.restored)
        return back.text

    parts: list[str] = []
    cursor = 0
    for start, end in link_spans(text, to_end):
        parts.append(plain(text[cursor:start]))
        parts.append(text[start:end])
        cursor = end
    parts.append(plain(text[cursor:]))
    return "".join(parts)


def _restore_json(text: str, results: list[MaskResult], restored: set[str]) -> str | None:
    """A JSON answer with the values put back inside each string, so the JSON stays valid
    whatever the values hold (quotes, backslashes); None if the text is not JSON. A client may
    show the JSON text as markdown, where an escaped blank line is no paragraph break and a
    link can start in one string and end in the next: from the first link mark on, in string
    order, nothing more is restored."""
    try:
        value = json.loads(text)
    except ValueError:
        return None
    marked = False

    def walk(node):
        nonlocal marked
        if isinstance(node, str):
            if marked:
                return node
            marked = LINK_MARK.search(node) is not None
            return put_back(node, results, restored, to_end=True)
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, dict):
            # Keys stay as they are: two keys that become equal once restored
            # (`[PERSON_1]`, `[PERSON_01]`) would merge and reorder the strings.
            out = {}
            for k, v in node.items():
                marked = marked or LINK_MARK.search(k) is not None
                out[k] = walk(v)
            return out
        return node

    return json.dumps(walk(value), ensure_ascii=False)


def restore_answer(
    data: dict, results: list[MaskResult], json_mode: bool = False
) -> tuple[dict, int]:
    """The provider's answer with the values back in each choice's message text; the number of
    aliases restored. In JSON mode (`response_format`), values go back inside the JSON string
    values, not in the keys."""
    if not results:
        return data, 0
    restored: set[str] = set()
    for choice in data.get("choices") or []:
        message = choice.get("message") if isinstance(choice, dict) else None
        if not (isinstance(message, dict) and isinstance(message.get("content"), str)):
            continue
        text = _restore_json(message["content"], results, restored) if json_mode else None
        if text is None:
            text = put_back(message["content"], results, restored)
        message["content"] = text
    return data, len(restored)


def create_bridge(
    detector: Detector,
    api_key: str | None = None,
    upstream: str = UPSTREAM,
    transport: httpx.AsyncBaseTransport | None = None,
    max_chars: int = MAX_CHARS,
    allowed_hosts: tuple[str, ...] = LOCAL_HOSTS,
) -> FastAPI:
    """The bridge around one detector, loaded once by the caller. `api_key`: the Mistral key
    (else the one the client sends); `transport`: for tests, a fake provider."""
    app = FastAPI(title="Alias Bridge", version=__version__, docs_url=None, redoc_url=None)
    hosts = set(allowed_hosts)

    @app.middleware("http")
    async def local_tools_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # The bridge spends the user's key: a web page must not be able to drive it. Browsers
        # send Origin on cross-site requests (SDKs and scripts do not), a DNS-rebinding page
        # arrives with its own host name, and a JSON content type forces a CORS preflight that
        # the bridge never answers.
        host = request.headers.get("host", "").rsplit(":", 1)[0].strip("[]")
        if "origin" in request.headers or host not in hosts:
            return JSONResponse({"detail": "only local tools may use the bridge"}, 403)
        if request.method == "POST" and not request.headers.get("content-type", "").startswith(
            "application/json"
        ):
            return JSONResponse({"detail": "the body must be application/json"}, 415)
        return await call_next(request)

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
            # A stop sequence cannot be masked without changing what it stops on.
            if any(detector.detect(stop) for stop in stops(body)):
                raise HTTPException(
                    422, "a stop sequence holds personal data, which cannot be masked: not sent"
                )
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
        messages = body.get("messages")
        if body.get("tools") or (
            isinstance(messages, list)
            and any(isinstance(m, dict) and m.get("tool_calls") for m in messages)
        ):
            # Tool definitions and call arguments are not masked yet: refuse rather than leak.
            raise HTTPException(501, "tool calls are not supported yet")
        where = unmaskable(body)
        if where:
            raise HTTPException(
                400, f"{where} is not supported: its text would reach Mistral unmasked"
            )
        token = key(request)
        outgoing, results, counts = await run_in_threadpool(masked_request, body)
        answer = await client.post(
            "/v1/chat/completions", json=outgoing, headers={"Authorization": f"Bearer {token}"}
        )
        if answer.status_code != 200:  # the provider's error, as it is (it only saw masked text)
            return Response(
                answer.content, answer.status_code, media_type=answer.headers.get("content-type")
            )
        response_format = body.get("response_format")
        json_mode = isinstance(response_format, dict) and str(
            response_format.get("type", "")
        ).startswith("json")
        data, restored = restore_answer(answer.json(), results, json_mode)
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

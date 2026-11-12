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
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from alias_pii import __version__
from alias_pii.entities import EntityType
from alias_pii.limits import BodyLimit
from alias_pii.masking import (
    AliasTable,
    Detector,
    MaskResult,
    find_leaks,
    mask,
    restore,
)
from alias_pii.rules import RuleDetector

UPSTREAM = "https://api.mistral.ai"
# Values the rules prove by a checksum: if one is still readable after masking, the request stops.
CHECKED = frozenset({EntityType.IBAN, EntityType.NATIONAL_ID})
# Values of the request looked for again, in any separator form, before sending.
COMPACT_CHECKED = frozenset({EntityType.IBAN, EntityType.NATIONAL_ID, EntityType.PHONE})
MAX_CHARS = 200_000  # the whole conversation of one request
MAX_BODY = 20_000_000  # bytes of one request, inline images included
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
# An image may only come inline: base64 data and nothing else, so no text rides in its URL.
IMAGE_DATA = re.compile(r"data:image/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]*")
# Where answer text may become a request of the client's own. A link (`](`) or a bare URL (`//`,
# `www.`) only works inside its paragraph (inline markdown never crosses a blank line) and needs
# a click, so from such a mark to the end of the paragraph aliases stay masked. From any of these
# to the end of the text, nothing more is restored (`FAR`):
# - an image (`![`): it is fetched as soon as it is shown;
# - a reference definition (`]:`), from the start of the text: an image anywhere in the answer
#   can use it, and its label may hold an alias, across a blank line a YAML decoder removes;
# - a `<` not followed by a space, `=` or digit (`a < b`, `<=`, `<3` are text): an HTML block can
#   run across blank lines, `<[PERSON_1]` becomes a tag once the name is back, and
#   `<a:b/title="...` is a tag to a browser even though it looks like an autolink;
# - a backslash: a client decoding the answer as JSON, JSON5 or YAML turns `\u003c` into `<`,
#   `\/\/` into `//`, and drops a backslash before a line break, all marks hidden here.
FAR = re.compile(r"!\[|(?<=\]):|<(?![\s=\d])|\\")
NEAR = re.compile(r"(?<=\])\(|//|www\.", re.IGNORECASE)
LINK_MARK = re.compile(f"{FAR.pattern}|{NEAR.pattern}", re.IGNORECASE)
DEFINITION = re.compile(r"(?<=\]):")
PARAGRAPH_END = re.compile(r"\n[ \t]*\n")
# A mark a client could form by joining two strings of a JSON document in any order: one string
# ends with its start, another starts with its end. An image also needs `](` or a definition
# (`]:`), so `![` split in two is caught through them; a split `<` is a string ending with `<`.
SPLIT_MARKS = ("](", "]:", "//", "www.")
OPENING = re.compile(r"[\[{]")
log = logging.getLogger("alias.bridge")


class LeftInClear(Exception):
    """A value is still readable after masking."""


def _each_text(messages: list[dict], change: Callable[[str], str]) -> list[dict]:
    """The messages with `change` applied to each text: a `content` string, or the `text` of a
    `{"type": "text"}` part. Other parts (inline images) are kept as they are."""
    out = []
    for message in messages:
        message = dict(message)
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = change(content)
        elif isinstance(content, list):
            message["content"] = [
                {**part, "text": change(part["text"])}
                if isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
                else part
                for part in content
            ]
        out.append(message)
    return out


def texts(messages: list[dict]) -> list[str]:
    found: list[str] = []
    _each_text(messages, lambda text: found.append(text) or text)
    return found


def mask_messages(
    messages: list[dict], detector: Detector
) -> tuple[list[dict], list[MaskResult], Counter]:
    """The messages with their text masked, the mask results (to restore the answer) and the
    count of values per type. Text is a message's `content` string, or the `text` of its
    `{"type": "text"}` parts; inline images (`inline_image`) are passed as they are.

    The detector may find a value in one message and miss it in another (a name in a sentence,
    then alone on a line): a second pass gives every whole-word occurrence of a value already
    aliased in this request the same alias."""
    table = AliasTable()
    results: list[MaskResult] = []
    counts: Counter = Counter()

    def masked(text: str) -> str:
        result = mask(text, detector, table)
        results.append(result)
        counts.update(e.type.value for e in result.entities)
        return result.text

    out = _each_text(messages, masked)
    known = list({e.text: e for result in results for e in result.entities}.values())
    if not known:
        return out, results, counts
    known.sort(key=lambda e: len(e.text), reverse=True)  # the longest value first
    pattern = re.compile(
        "|".join(rf"(?P<v{i}>(?<!\w){re.escape(e.text)}(?!\w))" for i, e in enumerate(known)),
        re.IGNORECASE,
    )

    def alias(match: re.Match[str]) -> str:
        entity = known[int(match.lastgroup[1:])]
        counts[entity.type.value] += 1
        return table.alias_for(entity)

    return _each_text(out, lambda text: pattern.sub(alias, text)), results, counts


def unmaskable(body: dict) -> str | None:
    """Where the request holds text the bridge would forward without masking it, else None: a
    field that is not a setting, a message key other than role/content/prefix, a content that
    is neither text nor text and inline image parts, a JSON schema, a setting that is not a
    number."""
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
            if not (text or inline_image(part)):
                return f"{where}.content[{j}]"
    return None


def inline_image(part) -> bool:
    """Whether a part is an image sent inline, as base64 data: a URL would be forwarded as it
    is, and its path or query can hold a name or an e-mail address."""
    if not (isinstance(part, dict) and set(part) == {"type", "image_url"}):
        return False
    image = part["image_url"]
    if isinstance(image, dict):
        detail = image.get("detail", "auto")
        if not (set(image) <= {"url", "detail"} and detail in ("auto", "low", "high")):
            return False
        image = image.get("url")
    return (
        part["type"] == "image_url"
        and isinstance(image, str)
        and IMAGE_DATA.fullmatch(image) is not None
    )


def stops(body: dict) -> list[str]:
    stop = body.get("stop")
    return [stop] if isinstance(stop, str) else list(stop or [])


def check_masked(masked: list[str], results: list[MaskResult]) -> None:
    """Raise `LeftInClear` when a text about to be sent still holds a checksummed value the
    rules find (IBAN, national ID), or an IBAN, national ID or phone number of this request
    written with other separators (`find_leaks`)."""
    rules = RuleDetector()
    entities = [e for result in results for e in result.entities if e.type in COMPACT_CHECKED]
    for text in masked:
        if any(e.type in CHECKED for e in rules.detect(text)) or find_leaks(text, entities):
            raise LeftInClear


def link_spans(text: str) -> list[tuple[int, int]]:
    """The parts of the text where aliases stay masked: from each link or URL mark (`NEAR`) to
    the end of its paragraph, and from the first image, tag or escape (`FAR`) to the end of the
    text, or all of it with a definition."""
    if DEFINITION.search(text):  # its label may hold an alias, even across a blank line a
        return [(0, len(text))]  # YAML decoder folds away: nothing is restored
    far = FAR.search(text)
    first_far = far.start() if far else len(text)
    spans: list[tuple[int, int]] = []
    position = 0
    while (mark := NEAR.search(text, position)) and mark.start() < first_far:
        end_of_paragraph = PARAGRAPH_END.search(text, mark.start())
        if not end_of_paragraph or end_of_paragraph.start() > first_far:
            return [*spans, (mark.start(), len(text))]
        spans.append((mark.start(), end_of_paragraph.start()))
        position = end_of_paragraph.start()
    if first_far < len(text):
        spans.append((first_far, len(text)))
    return spans


def put_back(text: str, results: list[MaskResult], restored: set[str]) -> str:
    """The text with the values of this request's aliases put back, except in links and what
    follows them (`link_spans`): an alias there stays masked, so a client loading a link or an
    image sends no value."""

    def plain(segment: str) -> str:
        back = restore(segment, *results)
        restored.update(back.restored)
        return back.text

    parts: list[str] = []
    cursor = 0
    for start, end in link_spans(text):
        parts.append(plain(text[cursor:start]))
        parts.append(text[start:end])
        cursor = end
    parts.append(plain(text[cursor:]))
    return "".join(parts)


def _document(text: str, strings: bool = False) -> dict | list | str | None:
    """The answer as a JSON object or array (or string, with `strings`), if it is one, read as
    leniently as a browser does (numbers of any length, kept as text). One too deeply nested to
    read counts as holding a link mark, so nothing is restored in it."""
    try:
        value = json.loads(text, parse_int=str, parse_float=str)
    except RecursionError:
        return ["<"]
    except ValueError:
        return None
    kinds = dict | list | str if strings else dict | list
    return value if isinstance(value, kinds) else None


def _documents(text: str) -> list:
    """The JSON objects and arrays in the answer, whole or within text (a ```json block,
    `Result: {...}`), read as leniently as `_document`. One too deeply nested to read counts as
    holding a link mark."""
    decoder = json.JSONDecoder(parse_int=str, parse_float=str)
    found: list = []
    position = 0
    while opening := OPENING.search(text, position):
        try:
            value, position = decoder.raw_decode(text, opening.start())
        except RecursionError:
            return [["<"]]
        except ValueError:
            position = opening.start() + 1
            continue
        found.append(value)
    return found


def _strings(node) -> list[str]:
    """Every string of a JSON document, keys included."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [s for item in node for s in _strings(item)]
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in (k, *_strings(v))]
    return []


def _linked(document: dict | list | str) -> bool:
    """Whether a client could form a link mark from a JSON document's strings, whatever it
    does with them: show them, join them with or without the keys, in any order (JavaScript
    puts integer keys first, a Go map sorts them). True when a string holds a mark or ends with
    `<`, or when one string ends with the start of a mark another one could finish
    (`SPLIT_MARKS`)."""
    try:
        strings = [s.lower() for s in _strings(document)]
    except RecursionError:
        return True
    if any(LINK_MARK.search(s) or s.endswith("<") for s in strings):
        return True
    return any(
        any(s.endswith(mark[:i]) for s in strings for i in range(1, len(mark)))
        and any(s.startswith(mark[i:]) for s in strings for i in range(1, len(mark)))
        for mark in SPLIT_MARKS
    )


def _restore_json(text: str, results: list[MaskResult], restored: set[str]) -> str | None:
    """A JSON answer with the values put back inside each string value, so the JSON stays valid
    whatever the values hold (quotes, backslashes); None if the text is not JSON. Keys keep their
    aliases (two keys equal once restored would merge), and a document holding a link mark
    anywhere (`_linked`) gets nothing back."""
    document = _document(text, strings=True)
    if document is None:
        return None
    if _linked(document):
        return text
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):  # an integer too long for Python: left as it is
        return text

    def walk(node):
        if isinstance(node, str):
            return put_back(node, results, restored)
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return node

    return json.dumps(walk(document), ensure_ascii=False)


def _text_part(part) -> bool:
    return (
        isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
    )


def _restore_parts(parts: list, results: list[MaskResult], restored: set[str]) -> list:
    """An answer given as a list of parts: a client may show every part's strings (text,
    thinking...) one after another, in any order, so the parts are judged as one JSON document
    (`_linked`), and their joined text for JSON within it; when no mark can be formed, each
    `text` part gets its values back. Other parts keep their aliases."""
    joined = "".join(part["text"] for part in parts if _text_part(part))
    if _linked(parts) or any(_linked(document) for document in _documents(joined)):
        return parts
    return [
        {**part, "text": put_back(part["text"], results, restored)} if _text_part(part) else part
        for part in parts
    ]


def restore_answer(
    data: dict, results: list[MaskResult], json_mode: bool = False
) -> tuple[dict, int]:
    """The provider's answer with the values back in each choice's message text; the number of
    aliases restored. In JSON mode (`response_format`), values go back inside the JSON string
    values, not in the keys. An answer holding a JSON document, whole or within the text, from
    whose strings a client could form a link mark gets nothing back (`_linked`)."""
    if not results:
        return data, 0
    restored: set[str] = set()
    for choice in data.get("choices") or []:
        message = choice.get("message") if isinstance(choice, dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), list):
            message["content"] = _restore_parts(message["content"], results, restored)
            continue
        if not (isinstance(message, dict) and isinstance(message.get("content"), str)):
            continue
        content = message["content"]
        text = _restore_json(content, results, restored) if json_mode else None
        if text is None:
            linked = any(_linked(document) for document in _documents(content))
            text = content if linked else put_back(content, results, restored)
        message["content"] = text
    return data, len(restored)


def create_bridge(
    detector: Detector,
    api_key: str | None = None,
    upstream: str = UPSTREAM,
    transport: httpx.AsyncBaseTransport | None = None,
    max_chars: int = MAX_CHARS,
    allowed_hosts: tuple[str, ...] = LOCAL_HOSTS,
    detector_name: str = "custom",
) -> FastAPI:
    """The bridge around one detector, loaded once by the caller. `api_key`: the Mistral key
    (else the one the client sends); `transport`: for tests, a fake provider; `detector_name`:
    shown in `/health` and in the `X-Alias-Detector` header, so a client can check what masks
    its text."""
    client = httpx.AsyncClient(base_url=upstream, transport=transport, timeout=120)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await client.aclose()

    app = FastAPI(
        title="Alias Bridge",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(BodyLimit, limit=MAX_BODY)
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

    async def upstream_call(method: str, path: str, **options) -> httpx.Response:
        try:
            return await client.request(method, path, **options)
        except httpx.TimeoutException:
            raise HTTPException(504, "Mistral did not answer in time") from None
        except httpx.HTTPError:
            raise HTTPException(502, "Mistral could not be reached") from None

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
            check_masked(texts(masked), results)
        except LeftInClear:
            raise HTTPException(
                422,
                "a value (IBAN, national ID, phone number) is still readable after masking: "
                "nothing was sent",
            ) from None
        return {**body, "messages": masked}, results, counts

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "upstream": upstream,
            "version": __version__,
            "detector": detector_name,
        }

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
        answer = await upstream_call(
            "POST",
            "/v1/chat/completions",
            json=outgoing,
            headers={"Authorization": f"Bearer {token}"},
        )
        if answer.status_code != 200:  # the provider's error, as it is (it only saw masked text)
            return Response(
                answer.content, answer.status_code, media_type=answer.headers.get("content-type")
            )
        response_format = body.get("response_format")
        json_mode = isinstance(response_format, dict) and str(
            response_format.get("type", "")
        ).startswith("json")
        try:
            data = answer.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise HTTPException(502, "Mistral's answer is not a JSON object")
        data, restored = restore_answer(data, results, json_mode)
        log.info("masked %s; restored %d", dict(counts), restored)
        return JSONResponse(
            data,
            headers={
                "X-Alias-Masked": str(sum(counts.values())),
                "X-Alias-Restored": str(restored),
                "X-Alias-Detector": detector_name,
            },
        )

    @app.get("/v1/models")
    async def models(request: Request) -> Response:
        answer = await upstream_call(
            "GET", "/v1/models", headers={"Authorization": f"Bearer {key(request)}"}
        )
        return Response(
            answer.content, answer.status_code, media_type=answer.headers.get("content-type")
        )

    return app


def options(argv: list[str] | None = None) -> argparse.Namespace:
    """The command line. Without a model the rules alone mask nothing but checksummed and
    formatted values (no names, no addresses), so that mode needs `--rules-only`."""
    parser = argparse.ArgumentParser(description="Run the Alias Bridge in front of Mistral.")
    parser.add_argument("--model", default=os.environ.get("ALIAS_MODEL"), help="checkpoint")
    parser.add_argument(
        "--rules-only",
        action="store_true",
        help="no model: names and addresses reach Mistral in clear",
    )
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 only inside a container")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(argv)
    if args.model and args.rules_only:
        parser.error("--rules-only and a model (--model or ALIAS_MODEL) exclude each other")
    if not args.model and not args.rules_only:
        parser.error(
            "no model: give a checkpoint (--model or ALIAS_MODEL), or pass --rules-only to "
            "mask only what the rules find; names and addresses would then reach Mistral in clear"
        )
    return args


def main() -> None:
    from alias_pii.app import load_detector

    args = options()
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    detector, name = load_detector(args.model)
    if args.rules_only:
        log.warning("rules only: names and addresses are NOT masked and reach Mistral in clear")
    else:
        log.info("detector: %s", name)
    app = create_bridge(detector, api_key=os.environ.get("MISTRAL_API_KEY"), detector_name=name)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

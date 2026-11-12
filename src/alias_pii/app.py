"""Local web API: paste a text, get it masked with stable aliases and a report without values.

    uv run --extra app python -m alias_pii.app --model models/mmbert-small/final

Nothing leaves the machine: the detector runs in this process, there is no outgoing call, no
text is logged or written to disk, and each request gets a fresh alias table that is dropped
with the response. Without `--model` (or `ALIAS_MODEL`) only the rules run: enough to develop
the page, not to mask names or addresses.

- `POST /api/mask` `{"text": "..."}` -> masked text, the spans found (type, position, alias)
  and a report counting values per type. The values themselves are never in the response: the
  caller already has the text, and positions are enough to highlight it. Positions count
  Unicode code points (Python string indices), not UTF-16 units as JavaScript strings do.
- `GET /health` -> which detector is loaded.
- `GET /` -> the page (`static/`: one HTML, one CSS, one JavaScript file, nothing from a CDN).
"""

from __future__ import annotations

import argparse
import os
import threading
from collections import Counter
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from alias_pii import __version__
from alias_pii.limits import BodyLimit
from alias_pii.masking import Detector, mask
from alias_pii.rules import RuleDetector

STATIC = Path(__file__).parent / "static"
MAX_CHARS = 100_000  # about 30 pages: a pasted text, not a corpus
SECURITY_HEADERS = {
    # The page ships its own CSS and JavaScript: nothing is loaded from elsewhere.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}


class MaskRequest(BaseModel):
    text: str


class Span(BaseModel):
    type: str
    start: int
    end: int
    alias: str


class MaskResponse(BaseModel):
    masked: str
    entities: list[Span]
    report: dict[str, int]  # values per type, plus "total"


def create_app(
    detector: Detector, name: str, max_chars: int = MAX_CHARS, demo: bool = False
) -> FastAPI:
    """The API and page around one detector, loaded once by the caller. `demo` shows a
    "fictitious data only" banner on the page (public demo)."""
    # The interactive docs load their scripts from a CDN: off, nothing is fetched from outside.
    app = FastAPI(title="Alias", version=__version__, docs_url=None, redoc_url=None)
    lock = threading.Lock()  # one detection at a time: CPU-bound, and the model is shared
    app.add_middleware(BodyLimit, limit=6 * max_chars + 1024)

    @app.middleware("http")
    async def limits_and_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # A JSON-escaped character takes at most 6 bytes (\uXXXX): refuse bigger bodies unread.
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > 6 * max_chars + 1024:
            response: Response = JSONResponse({"detail": "text too long"}, status_code=413)
        else:
            response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.get("/", include_in_schema=False)
    def page() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/health")
    def health() -> dict[str, str | bool]:
        return {"status": "ok", "detector": name, "version": __version__, "demo": demo}

    @app.post("/api/mask")
    def mask_text(body: MaskRequest) -> MaskResponse:
        if len(body.text) > max_chars:
            raise HTTPException(413, f"text too long: at most {max_chars} characters")
        with lock:
            result = mask(body.text, detector)
        # mask() writes one alias per entity, in order: pair them back for the positions.
        spans = [
            Span(type=e.type.value, start=e.start, end=e.end, alias=result.table.alias_for(e))
            for e in result.entities
        ]
        counts = Counter(s.type for s in spans)
        return MaskResponse(
            masked=result.text, entities=spans, report={**counts, "total": len(spans)}
        )

    return app


def load_detector(model: str | None) -> tuple[Detector, str]:
    """Rules + the fine-tuned model when a checkpoint is given, the rules alone otherwise."""
    if not model:
        return RuleDetector(), "rules"
    from alias_pii.detector import RulesAndModel

    return RulesAndModel.from_checkpoint(model), "rules+model"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Alias web API on this machine.")
    parser.add_argument("--model", default=os.environ.get("ALIAS_MODEL"), help="checkpoint")
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 only inside a container")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--max-chars", type=int, default=MAX_CHARS)
    parser.add_argument(
        "--demo",
        action="store_true",
        default=os.environ.get("ALIAS_DEMO") == "1",
        help="public demo: banner asking for fictitious data only",
    )
    args = parser.parse_args()

    import uvicorn

    detector, name = load_detector(args.model)
    app = create_app(detector, name, args.max_chars, args.demo)
    # Access logs hold the method and path only, never the body.
    uvicorn.run(app, host=args.host, port=args.port, server_header=False)


if __name__ == "__main__":
    main()

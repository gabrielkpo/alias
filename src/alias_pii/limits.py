"""A cap on request bodies that holds whether or not the client declares a Content-Length.

Starlette reads a chunked body to the end before a route sees it, and a size check on the
Content-Length header alone lets a chunked request through: `BodyLimit` counts the bytes as
they arrive and stops at the limit with 413, nothing more read.
"""

from __future__ import annotations

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyLimit:
    """ASGI middleware: a request whose body passes `limit` bytes gets 413."""

    def __init__(self, app: ASGIApp, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise HTTPException(413, f"body too large: at most {self.limit} bytes")
            return message

        await self.app(scope, counted, send)

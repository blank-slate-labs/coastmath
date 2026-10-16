"""Bound request bodies before any route reads, parses or rate-limits them.

FastAPI reads and validates a JSON body before SlowAPI counts the request, so
without this every body route, including unauthenticated ones, would parse
whatever arrives. Bytes are counted as they stream in: a missing or false
Content-Length cannot bypass the limit.
"""
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import api_error

MIB = 1024 * 1024
DEFAULT_LIMIT = 2 * MIB
# Ledger file imports carry a file of up to 10 MiB as base64 (4/3 of it) plus
# the mapping and category choices. Plug-ins add their own (app.plugins).
PATH_LIMITS = (("/api/ledger/imports", 15 * MIB),)


def too_large(limit: int) -> HTTPException:
    return api_error(413, "REQUEST_TOO_LARGE", f"This request is larger than {limit // MIB} MB.")


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, default: int = DEFAULT_LIMIT,
                 limits: tuple[tuple[str, int], ...] = PATH_LIMITS) -> None:
        self.app = app
        self.default = default
        self.limits = limits

    def limit_for(self, path: str) -> int:
        return next((size for prefix, size in self.limits
                     if path == prefix or path.startswith(prefix + "/")), self.default)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope["path"])
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await JSONResponse(too_large(limit).detail, status_code=413)(scope, receive, send)
            return
        received = 0

        async def bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # FastAPI re-raises HTTPException from body reading, so the
                    # shared error handler answers with the project envelope.
                    raise too_large(limit)
            return message

        await self.app(scope, bounded_receive, send)

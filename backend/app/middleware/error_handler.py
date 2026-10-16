import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException

from app.safe_logging import exception_summary

logger = logging.getLogger(__name__)

_HTTP_STATUS_TO_CODE = {
    401: "AUTH_REQUIRED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
}


def _error_response(status_code: int, code: str, message: str, details: list[dict], headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
        headers=headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = []
    for err in exc.errors():
        loc = err.get("loc", ())
        if loc and loc[0] in {"body", "query", "path", "header", "cookie"}:
            loc = loc[1:]
        field = ".".join(str(part) for part in loc) if loc else "unknown"
        details.append({"field": field, "reason": err.get("msg", "invalid")})
    return _error_response(422, "VALIDATION_ERROR", "Validation failed", details)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = _HTTP_STATUS_TO_CODE.get(exc.status_code, f"HTTP_{exc.status_code}")
    detail = exc.detail
    # Routers raise structured details in the project error shape; pass the
    # code, message and field-level details through instead of stringifying.
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        detail = detail["error"]
    if isinstance(detail, dict):
        message = str(detail.get("message", "Request failed"))
        details = detail.get("details") or []
        code = str(detail.get("code") or code)
        return _error_response(exc.status_code, code, message, details if isinstance(details, list) else [], exc.headers)
    return _error_response(exc.status_code, code, str(detail), [], exc.headers)


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception on %s %s: %s", request.scope.get("method", "-"),
                 request.scope.get("path", "-"), exception_summary(exc))
    return _error_response(500, "INTERNAL_ERROR", "Internal server error", [])


async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    response = _error_response(
        429, "RATE_LIMIT_EXCEEDED", f"Too many requests. Try again later ({exc.detail}).", []
    )
    # Preserve SlowAPI's configured rate-limit headers with our shared envelope.
    return request.app.state.limiter._inject_headers(response, request.state.view_rate_limit)

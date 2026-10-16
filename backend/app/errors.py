"""API errors in the project envelope: ``{"error": {"code", "message", "details"}}``.

Routers and services raise the exceptions built here, and
``app.middleware.error_handler.http_exception_handler`` renders them. The
module sits at the package root, not in ``app.routers`` or the middleware, so
routers, ledger services and scenario sync can all import it without an
import cycle. It depends on FastAPI only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

if TYPE_CHECKING:
    from coastmath.engine.household_lifecycle import UnsupportedLifecycleInput


def api_error(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    """An ``HTTPException`` whose detail is the project error envelope.

    ``details`` is a list of ``{"field", "reason"}`` items (ledger month refusals
    name ``{"month", "reasons"}`` instead), empty when omitted.
    """
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "details": list(details or [])}},
        headers=headers,
    )


def validation_error(message: str, field: str, reason: str | None = None) -> HTTPException:
    """A 422 ``VALIDATION_ERROR`` naming one field; the reason defaults to the message."""
    return api_error(422, "VALIDATION_ERROR", message, [{"field": field, "reason": message if reason is None else reason}])


def lifecycle_input_error(exc: UnsupportedLifecycleInput) -> HTTPException:
    """A 422 for household lifecycle input the engine cannot model."""
    return validation_error(str(exc), "estate_settings.household_lifecycle")

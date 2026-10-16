"""Readiness is separate from the process liveness endpoint."""
import os

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import api_error
from app.plugins import extensions

router = APIRouter(tags=["operations"])


@router.get("/ready")
def readiness(db: Session = Depends(get_db)) -> dict:
    result = {"status": "ready"}
    try:
        db.execute(text("SELECT 1"))
        # A deployment's own checks may refuse with 503 or add fields.
        for check in extensions.readiness_checks:
            result.update(check(db))
    except SQLAlchemyError:
        raise api_error(503, "DATABASE_NOT_READY", "Database is not ready.") from None
    result.setdefault("revision", os.getenv("APP_REVISION") or None)
    return result

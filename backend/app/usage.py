"""Feature-usage counting hooks.

Routes name the feature each request uses. Nothing is recorded unless a
plug-in installs a recorder (``app.plugins``); a recorder must never fail the
request.
"""
import uuid

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.models.user import User
from app.plugins import extensions


def record_usage(db: Session, user_id: uuid.UUID, feature: str) -> None:
    """Record one use of ``feature``."""
    if extensions.usage_recorder is not None:
        extensions.usage_recorder(db, user_id, feature)


def count_usage(feature: str):
    """Route dependency: record one use of ``feature`` before the route runs."""
    def dependency(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
        record_usage(db, current_user.id, feature)
    return dependency

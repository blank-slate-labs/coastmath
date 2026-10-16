import re
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, Request
from jwt.exceptions import PyJWTError
from sqlalchemy.orm import Session

from app.auth.config import SESSION_SECRET
from app.db import get_db
from app.errors import api_error
from app.models.user import User
from app.plugins import extensions


def decode_jwt(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token."""
    try:
        issuer = extensions.session_token_issuer
        return jwt.decode(token, SESSION_SECRET, algorithms=["HS256"], audience=issuer, issuer=issuer, options={"require": ["sub", "exp", "iss", "aud"]})
    except PyJWTError:
        raise api_error(401, "AUTH_REQUIRED", "Invalid or expired token") from None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Get the current authenticated user from the session cookie JWT."""
    token = request.cookies.get("session")
    if not token:
        raise api_error(401, "AUTH_REQUIRED", "Authentication required")

    payload = decode_jwt(token)
    user_id = payload.get("sub")
    if not user_id:
        raise api_error(401, "AUTH_REQUIRED", "Invalid token: missing subject")

    try:
        subject_id = UUID(user_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise api_error(401, "AUTH_REQUIRED", "Invalid token: malformed subject") from exc
    user = db.query(User).filter(User.id == subject_id).first()
    if not user or payload.get("ver", 0) != user.session_version:
        raise api_error(401, "AUTH_REQUIRED", "User not found")
    path = request.url.path
    read_only_calculation = request.method == "POST" and re.fullmatch(r"/api/plans/[0-9a-fA-F-]{36}/(simulate|compare|monte-carlo)", path)
    if user.is_demo and request.method not in ("GET", "HEAD", "OPTIONS") and not read_only_calculation and path not in ("/api/auth/session", "/api/auth/logout"):
        raise api_error(403, "DEMO_READ_ONLY", "The demo account is read-only.")
    # A plug-in's sign-in providers may refuse the session or add claims that a
    # refreshed cookie carries (request.state.session_claims).
    for check in extensions.session_checks:
        check(request, user, payload, db)
    request.state.user_id = user.id  # Rate-limit key; see app.rate_limit.session_user.
    return user

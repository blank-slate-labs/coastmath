import json as _json
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from limits import parse
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.auth.config import DEV_SESSION_SECRET, SESSION_SECRET
from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error
from app.models.user import User
from app.plugins import extensions
from app.rate_limit import client_address, limiter
from app.schemas.user import SessionCreate, SessionRead, UserProfileUpdate

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_MAX_AGE = 7 * 24 * 3600  # Authenticated sessions: 7 days
ANONYMOUS_COOKIE_MAX_AGE = 30 * 24 * 3600  # More time to return before native OAuth recovery exists.
#: New anonymous accounts per client address and worker. Each one is a stored
#: account that can hold plans, so this bounds how fast one address grows the
#: database; resuming a session is not counted.
ANONYMOUS_ACCOUNTS_PER_DAY = parse("100/day")


def _is_secure() -> bool:
    # SESSION_COOKIE_SECURE=false lets a self-hosted instance sign in over plain HTTP.
    if os.getenv("SESSION_COOKIE_SECURE", "").strip().lower() == "false":
        return False
    return SESSION_SECRET != DEV_SESSION_SECRET


def create_jwt(user_id: UUID, session_version: int = 0, *, anonymous: bool = False, claims: dict | None = None) -> str:
    """A signed session token. ``claims`` adds a sign-in provider's own claims."""
    issuer = extensions.session_token_issuer
    payload = {
        "sub": str(user_id),
        "ver": session_version,
        "exp": datetime.now(UTC) + timedelta(seconds=ANONYMOUS_COOKIE_MAX_AGE if anonymous else COOKIE_MAX_AGE),
        "iss": issuer,
        "aud": issuer,
    }
    payload.update({key: value for key, value in (claims or {}).items() if key not in payload})
    return jwt.encode(payload, SESSION_SECRET, algorithm="HS256")


def carried_claims(request: Request) -> dict:
    """Provider claims that a refreshed session cookie keeps (set by session checks)."""
    return getattr(request.state, "session_claims", None) or {}


def _set_session_cookie(response: Response, token: str, *, anonymous: bool = False) -> None:
    """Apply session cookie with consistent settings."""
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=_is_secure(),
        samesite="lax",
        max_age=ANONYMOUS_COOKIE_MAX_AGE if anonymous else COOKIE_MAX_AGE,
    )


def _user_dict(user: User) -> dict:
    return SessionRead.model_validate(user).model_dump(mode="json")


# Routes that read the database are synchronous so they run on the thread
# pool: a blocking query or provider call on the event loop stalls every request.
@router.post("/session", response_model=SessionRead)
@limiter.limit("30/minute")
def session(
    request: Request,
    body: SessionCreate | None = None,
    db: Session = Depends(get_db),
) -> Response:
    """Resume or create a session.

    - Valid session cookie → return existing user (200), refresh cookie.
    - No cookie / invalid → create an anonymous user and issue cookie (201).
      Sessions never create plans, accounts or workspaces. Older clients still send ``seed_demo`` and
      ``client_workspace``; both are accepted and ignored.
      Resuming never changes existing plans or accounts.
    """
    token = request.cookies.get("session")

    # --- Try to resume existing session ---
    if token:
        try:
            user = get_current_user(request, db)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
        else:
            response = Response(
                status_code=200,
                content=_json.dumps(_user_dict(user)),
                media_type="application/json",
            )
            _set_session_cookie(response, create_jwt(user.id, user.session_version, anonymous=user.is_anonymous, claims=carried_claims(request)), anonymous=user.is_anonymous)
            return response

    # --- Create anonymous session ---
    if limiter.enabled and not limiter.limiter.hit(ANONYMOUS_ACCOUNTS_PER_DAY, "anonymous_accounts", client_address(request)):
        raise api_error(429, "RATE_LIMIT_EXCEEDED", "Too many new sessions from this network today.",
                        headers={"Retry-After": "3600"})
    user = User(
        is_anonymous=True,
        is_demo=bool(body and body.read_only_demo),
        email=None,
        display_name="Anonymous",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    new_token = create_jwt(user.id, user.session_version, anonymous=user.is_anonymous)
    response = Response(
        status_code=201,
        content=_json.dumps(_user_dict(user)),
        media_type="application/json",
    )
    _set_session_cookie(response, new_token, anonymous=user.is_anonymous)
    return response


@router.get("/me", response_model=SessionRead, responses={204: {"description": "No session cookie (only with ``optional=true``)."}})
def me(
    request: Request,
    response: Response,
    optional: bool = False,
    db: Session = Depends(get_db),
) -> dict | Response:
    # A first visit has no cookie. With ``optional`` the web's startup probe gets 204 instead of a 401
    # the browser logs as an error; a present but invalid cookie is still a 401.
    if optional and not request.cookies.get("session"):
        return Response(status_code=204)
    current_user = get_current_user(request, db)
    # Resume safely without creating a new anonymous identity on expiry.
    _set_session_cookie(response, create_jwt(current_user.id, current_user.session_version, anonymous=current_user.is_anonymous, claims=carried_claims(request)), anonymous=current_user.is_anonymous)
    return _user_dict(current_user)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)) -> Response:
    try:
        user = get_current_user(request, db)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
    else:
        for hook in extensions.logout_hooks:
            hook(user)
        db.execute(update(User).where(User.id == user.id).values(session_version=User.session_version + 1))
        db.commit()
    response = Response(content='{"ok": true}', media_type="application/json")
    response.delete_cookie(
        key="session",
        httponly=True,
        secure=_is_secure(),
        samesite="lax",
    )
    return response


@router.put("/me", response_model=SessionRead)
def update_profile(
    body: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Edit presentation only; identity and authentication are unchanged."""
    current_user.display_name = body.display_name
    db.commit()
    db.refresh(current_user)
    return current_user

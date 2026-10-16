"""Tests for POST /api/auth/session endpoint and OAuth claim flow."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.config import SESSION_SECRET
from app.auth.router import create_jwt
from app.models.account import CurrentAccount
from app.models.plan import Plan
from app.models.planning_client import PlanningClient
from app.models.user import User
from app.plugins import extensions


@pytest.mark.anyio
async def test_session_no_cookie_creates_anonymous_user(client, db_session):
    """POST /api/auth/session with no cookie -> 201, anonymous user."""
    client.cookies.clear()
    response = await client.post("/api/auth/session")

    assert response.status_code == 201
    data = response.json()
    assert data["is_anonymous"] is True
    assert data["email"] is None
    assert data["display_name"] == "Anonymous"
    assert "id" in data

    # Cookie was set
    assert "session" in response.cookies

    # User exists in DB
    user = db_session.query(User).filter(User.id == uuid.UUID(data["id"])).first()
    assert user is not None
    assert user.is_anonymous is True


@pytest.mark.anyio
async def test_session_valid_cookie_returns_existing_user(client, db_session):
    """POST /api/auth/session with valid cookie -> 200, existing user data."""
    # Create a user and a valid JWT
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        display_name="Test User",
        is_anonymous=False,
        settings={},
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    db_session.commit()

    token = create_jwt(user.id)

    response = await client.post(
        "/api/auth/session",
        cookies={"session": token},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(user.id)
    assert data["email"] == "test@example.com"
    assert data["display_name"] == "Test User"
    assert data["is_anonymous"] is False

    # Cookie refreshed (sliding window)
    assert "session" in response.cookies


@pytest.mark.anyio
async def test_session_invalid_cookie_creates_new_anonymous(client, db_session):
    """POST /api/auth/session with invalid/expired cookie -> 201, new anonymous user."""
    # Create an expired JWT
    payload = {
        "sub": str(uuid.uuid4()),
        "exp": datetime.now(UTC) - timedelta(hours=1),
        "iss": extensions.session_token_issuer,
        "aud": extensions.session_token_issuer,
    }
    expired_token = jwt.encode(payload, SESSION_SECRET, algorithm="HS256")

    response = await client.post(
        "/api/auth/session",
        cookies={"session": expired_token},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["is_anonymous"] is True


@pytest.mark.anyio
async def test_session_cookie_for_deleted_user_creates_new(client, db_session):
    """POST /api/auth/session with valid JWT but user gone from DB -> 201."""
    # JWT for a user that doesn't exist
    token = create_jwt(uuid.uuid4())

    response = await client.post(
        "/api/auth/session",
        cookies={"session": token},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["is_anonymous"] is True


@pytest.mark.anyio
@pytest.mark.parametrize("body", [
    None,
    {},
    {"seed_demo": True},
    {"client_workspace": True},  # Web sample request before it became static
    {"seed_demo": True, "client_workspace": True, "read_only_demo": True},  # Shipped iOS demo
    {"seed_demo": False, "client_workspace": True, "read_only_demo": False},  # iOS personal onboarding
])
async def test_session_never_seeds_sample_data(client, db_session, body):
    """No session request creates a plan, account or workspace, whatever it asks for."""
    client.cookies.clear()
    response = await client.post("/api/auth/session", json=body) if body is not None else await client.post("/api/auth/session")
    assert response.status_code == 201
    user_id = uuid.UUID(response.json()["id"])

    assert db_session.query(Plan).filter(Plan.user_id == user_id).count() == 0
    assert db_session.query(CurrentAccount).filter(CurrentAccount.user_id == user_id).count() == 0
    assert db_session.query(PlanningClient).filter(PlanningClient.user_id == user_id).count() == 0
    plans = await client.get("/api/plans/summaries")  # As the new session
    assert plans.status_code == 200 and plans.json() == []

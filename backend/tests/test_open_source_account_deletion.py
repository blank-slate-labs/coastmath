"""The open-source ``DELETE /api/auth/me``: confirmed, then every owned row goes with the account."""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.account_deletion import router
from app.auth.router import create_jwt
from app.db import get_db
from app.models.user import User
from app.rate_limit import limiter

pytestmark = pytest.mark.anyio


async def test_deletion_needs_confirmation_then_removes_the_account(db_session, test_user):
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db_session
    user_id = test_user.id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           cookies={"session": create_jwt(user_id)}) as client:
        assert (await client.request("DELETE", "/api/auth/me", json={"confirmation": "delete"})).status_code == 422
        assert db_session.get(User, user_id) is not None
        deleted = await client.request("DELETE", "/api/auth/me", json={"confirmation": "DELETE"})
    assert deleted.status_code == 204
    assert 'session=""' in deleted.headers["set-cookie"]
    db_session.expire_all()
    assert db_session.get(User, user_id) is None

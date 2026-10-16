"""Cross-site state changes are refused on every API route, not only sign-in."""
import pytest
from fastapi.middleware.cors import CORSMiddleware

from app import main
from app.models.plan import Plan

pytestmark = pytest.mark.anyio


def plan_count(db_session, test_user):
    return db_session.query(Plan).filter_by(user_id=test_user.id).count()


@pytest.mark.parametrize("headers", [
    {"Origin": "https://attacker.test"},
    {"Origin": "null"},
    {"Sec-Fetch-Site": "cross-site"},  # A browser request that omitted Origin.
    {"Sec-Fetch-Site": "same-site"},
])
async def test_cross_site_body_less_post_changes_nothing(client, db_session, test_user, demo_plan, headers):
    before = plan_count(db_session, test_user)
    response = await client.post(f"/api/plans/{demo_plan.id}/duplicate", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_INVALID"
    assert response.headers["x-frame-options"] == "DENY"
    assert plan_count(db_session, test_user) == before


async def test_cross_site_delete_is_refused(client, db_session, test_user, demo_plan):
    response = await client.delete(f"/api/plans/{demo_plan.id}", headers={"Origin": "https://attacker.test"})
    assert response.status_code == 403
    assert db_session.get(Plan, demo_plan.id) is not None


@pytest.mark.parametrize("headers", [
    {},  # Native clients send neither Origin nor Sec-Fetch-Site.
    {"Origin": "http://test"},  # The API's own origin.
    {"Origin": "http://localhost:3000", "Sec-Fetch-Site": "same-site"},  # ALLOWED_ORIGINS default.
    {"Sec-Fetch-Site": "same-origin"},
])
async def test_same_origin_and_native_changes_still_work(client, db_session, test_user, demo_plan, headers):
    before = plan_count(db_session, test_user)
    response = await client.post(f"/api/plans/{demo_plan.id}/duplicate", headers=headers)
    assert response.status_code == 201
    assert plan_count(db_session, test_user) == before + 1


async def test_cross_site_reads_are_left_to_cors(client, demo_plan):
    response = await client.get(f"/api/plans/{demo_plan.id}", headers={"Origin": "https://attacker.test"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


async def test_signed_provider_webhook_is_not_origin_checked(client):
    response = await client.post("/api/ledger/webhooks/plaid", content=b"{}",
                                 headers={"Origin": "https://provider.test"})
    assert not (response.status_code == 403 and response.json()["error"]["code"] == "ORIGIN_INVALID")


async def test_sign_in_routes_keep_their_error_code(client):
    response = await client.post("/api/auth/logout", headers={"Origin": "https://attacker.test"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTH_ORIGIN_INVALID"


def test_allowed_origins_ignore_spaces_trailing_slashes_and_blanks():
    assert main.parse_allowed_origins(" https://a.test , https://b.test/,, ") == ["https://a.test", "https://b.test"]
    assert main.parse_allowed_origins("") == []


@pytest.mark.parametrize("value", ["*", "https://a.test, *", "null", "NULL", "null/"])
def test_allowed_origins_refuse_wildcards_and_null(value):
    # With allow_credentials, Starlette would echo any Origin for "*"; "null" is every sandboxed or file: page.
    with pytest.raises(ValueError, match="ALLOWED_ORIGINS"):
        main.parse_allowed_origins(value)


def test_cors_and_the_origin_check_share_one_list():
    (cors,) = [m for m in main.app.user_middleware if m.cls is CORSMiddleware]
    assert cors.kwargs["allow_origins"] is main.allowed_origins


async def test_spaced_allowed_origin_is_trusted(client, db_session, test_user, demo_plan, monkeypatch):
    monkeypatch.setattr(main, "allowed_origins", main.parse_allowed_origins("https://a.test, https://b.test"))
    response = await client.post(f"/api/plans/{demo_plan.id}/duplicate", headers={"Origin": "https://b.test"})
    assert response.status_code == 201

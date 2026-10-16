"""Plaid webhooks: verified wake-ups, rejected signatures, debounce, unknown Items and reconnect events."""
import json
from datetime import timedelta

import pytest

from app.ledger import connections as lifecycle
from app.ledger.balances import aware
from app.ledger.providers import plaid_webhooks
from app.models.financial_connection import FinancialConnection, utcnow
from tests.plaid_server import ACCESS_TOKEN, ITEM_ID

pytestmark = pytest.mark.anyio
URL = "/api/ledger/webhooks/plaid"


@pytest.fixture
def connection(plaid, db_session, test_user) -> FinancialConnection:
    row = lifecycle.create_connection(db_session, test_user.id, "plaid", ACCESS_TOKEN, provider_connection_id=ITEM_ID)
    row.status, row.next_check_at = lifecycle.ACTIVE, utcnow() + timedelta(hours=20)
    db_session.commit()
    return row


def event(kind="TRANSACTIONS", code="SYNC_UPDATES_AVAILABLE", item_id=ITEM_ID, **extra) -> bytes:
    return json.dumps({"webhook_type": kind, "webhook_code": code, "item_id": item_id, "environment": "sandbox",
                       **extra}).encode()


async def send(client, plaid, body: bytes, *, signature: str | None = None, headers=None):
    headers = {"Content-Type": "application/json", **(headers or {})}
    headers["Plaid-Verification"] = signature if signature is not None else plaid.sign(body)
    return await client.post(URL, content=body, headers=headers)


async def test_verified_webhook_wakes_the_connection(client, db_session, plaid, connection):
    before = utcnow()
    response = await send(client, plaid, event())
    assert response.status_code == 200 and response.json() == {"received": True}
    db_session.expire_all()
    due = aware(connection.next_check_at)
    assert before + plaid_webhooks.DEBOUNCE <= due <= utcnow() + plaid_webhooks.DEBOUNCE
    # A burst shares one sync: the next webhook never pushes the check later or earlier.
    assert (await send(client, plaid, event())).status_code == 200
    db_session.expire_all()
    assert aware(connection.next_check_at) == due
    # Nothing from the payload is stored.
    assert connection.status == "ACTIVE" and connection.error is None


async def test_rejected_signatures(client, db_session, plaid, connection):
    body = event()
    other = event(code="DEFAULT_UPDATE")
    for signature in ("", "not-a-jwt", plaid.sign(other), plaid.sign(body, iat=1)):
        refused = await send(client, plaid, body, signature=signature)
        assert refused.status_code == 401 and refused.json()["error"]["code"] == "WEBHOOK_UNVERIFIED"
    missing = await client.post(URL, content=body)
    assert missing.status_code == 401
    db_session.expire_all()
    assert aware(connection.next_check_at) > utcnow() + timedelta(hours=19)


async def test_unknown_items_and_malformed_events_are_ignored(client, db_session, plaid, connection):
    for body in (event(item_id="item-unknown"), b"[]", b"not json", event(code="")):
        assert (await send(client, plaid, body)).status_code == 200
    db_session.expire_all()
    assert aware(connection.next_check_at) > utcnow() + timedelta(hours=19)


async def test_item_events_mark_reconnection_and_repair(client, db_session, plaid, connection):
    error = {"error_type": "ITEM_ERROR", "error_code": "ITEM_LOGIN_REQUIRED"}
    assert (await send(client, plaid, event("ITEM", "ERROR", error=error))).status_code == 200
    db_session.expire_all()
    assert connection.status == "RECONNECT_REQUIRED" and connection.next_check_at is None
    assert connection.error == "This bank connection needs you to sign in again."
    # A reconnect-required connection is not woken by transaction updates.
    await send(client, plaid, event())
    db_session.expire_all()
    assert connection.next_check_at is None
    await send(client, plaid, event("ITEM", "LOGIN_REPAIRED"))
    db_session.expire_all()
    assert connection.status == "NEW" and connection.error is None and connection.next_check_at is not None
    await send(client, plaid, event("ITEM", "PENDING_EXPIRATION", consent_expiration_time="2026-10-18T00:00:00Z"))
    db_session.expire_all()
    assert connection.status == "RECONNECT_REQUIRED"


async def test_other_item_events(client, db_session, plaid, connection):
    await send(client, plaid, event("ITEM", "ERROR", error={"error_code": "INTERNAL_SERVER_ERROR"}))
    await send(client, plaid, event("ITEM", "ERROR", error="unexpected"))
    await send(client, plaid, event("ITEM", "LOGIN_REPAIRED"))
    await send(client, plaid, event("ITEM", "WEBHOOK_UPDATE_ACKNOWLEDGED"))
    db_session.expire_all()
    assert connection.status == "ACTIVE" and aware(connection.next_check_at) > utcnow() + timedelta(hours=19)
    await send(client, plaid, event("ITEM", "NEW_ACCOUNTS_AVAILABLE"))
    db_session.expire_all()
    assert aware(connection.next_check_at) < utcnow() + timedelta(minutes=1)


async def test_a_running_sync_is_left_alone(client, db_session, plaid, connection):
    lease = utcnow() + timedelta(minutes=10)
    connection.status, connection.next_check_at = lifecycle.SYNCING, lease
    db_session.commit()
    await send(client, plaid, event())
    db_session.expire_all()
    assert aware(connection.next_check_at) == aware(lease)


async def test_a_connection_without_a_schedule_is_woken(db_session, plaid, connection):
    connection.next_check_at = None
    db_session.commit()
    now = utcnow()
    assert plaid_webhooks.handle(db_session, event(), now) == "woken"
    assert aware(connection.next_check_at) == now + plaid_webhooks.DEBOUNCE


async def test_refused_while_plaid_is_not_offered(client, plaid, monkeypatch):
    monkeypatch.setenv("PLAID_ENABLED", "false")
    off = await send(client, plaid, event())
    assert off.status_code == 503 and off.json()["error"]["code"] == "INTEGRATION_UNAVAILABLE"
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "false")
    gated = await send(client, plaid, event())
    assert gated.status_code == 503 and gated.json()["error"]["code"] == "FEATURE_DISABLED"


async def test_webhook_skips_the_origin_check_and_csp_allows_link(client, plaid, connection):
    response = await send(client, plaid, event(), headers={"Origin": "https://provider.test",
                                                           "Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 200
    policy = response.headers["Content-Security-Policy-Report-Only"]
    script = next(part for part in policy.split("; ") if part.startswith("script-src"))
    frame = next(part for part in policy.split("; ") if part.startswith("frame-src"))
    assert "https://cdn.plaid.com" in script and "https://cdn.plaid.com" in frame

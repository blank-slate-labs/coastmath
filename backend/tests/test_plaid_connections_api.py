"""Plaid connection routes: offered states, Link tokens, exchange, update mode, disconnect and account deletion."""
import uuid

import pytest

from app.ledger import connections as lifecycle
from app.ledger import secrets, sync_worker
from app.ledger.providers import registry
from app.models.financial_connection import FinancialConnection, FinancialSource, utcnow
from app.models.user import User
from app.plugins import extensions
from tests.conftest import TestSession
from tests.ledger_fixture import other_user
from tests.plaid_server import (
    ACCESS_TOKEN,
    ITEM_ID,
    LINK_TOKEN,
    PUBLIC_TOKEN,
    Plaid,
    install,
    txn,
)

pytestmark = pytest.mark.anyio
KEY = "synthetic-ledger-key-0123456789-abcdef"


@pytest.fixture
def plaid(monkeypatch, test_user, db_session):
    for name, value in (("TRANSACTIONS_ENABLED", "true"), ("PLAID_ENABLED", "true"), ("LEDGER_ENCRYPTION_KEY", KEY)):
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("PLAID_REDIRECT_URI", raising=False)
    monkeypatch.delenv("PLAID_WEBHOOK_URL", raising=False)
    test_user.is_anonymous = False
    db_session.commit()
    server = Plaid()
    install(monkeypatch, server)
    return server


async def connect(client, db_session, **extra) -> FinancialConnection:
    created = await client.post("/api/ledger/connections/plaid", json={"public_token": PUBLIC_TOKEN, **extra})
    assert created.status_code == 201, created.text
    db_session.expire_all()
    return db_session.get(FinancialConnection, uuid.UUID(created.json()["id"]))


def removals(plaid) -> list[dict]:
    return [body for path, body in plaid.calls if path == "/item/remove"]


async def test_plaid_offered_states(client, monkeypatch, plaid):
    found = {p["key"]: p for p in (await client.get("/api/ledger/providers")).json()}
    item = found["plaid"]
    assert item["offered"] and item["link_flow"] == "widget" and item["history_days"] == 730
    assert {"webhooks", "balances", "pending"} <= set(item["capabilities"])
    assert "plaid" in registry.pull_providers()
    cases = [
        ("LEDGER_ENCRYPTION_KEY", None, "Plaid needs an encryption key on this server."),
        ("PLAID_SECRET", None, "Plaid needs PLAID_CLIENT_ID and PLAID_SECRET on this server."),
        ("PLAID_ENV", "development", "Plaid's configuration on this server is invalid."),
        ("PLAID_ENABLED", "false", "Plaid is not enabled on this server."),
        ("TRANSACTIONS_ENABLED", "false", "Transactions are unavailable in this release."),
    ]
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    for name, value, reason in cases:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
        descriptor = registry.descriptor("plaid")
        assert not descriptor.offered and descriptor.reason == reason, name


async def test_link_token_for_a_new_connection(client, plaid, test_user):
    response = await client.post("/api/ledger/connections/plaid/link-token", json={})
    assert response.status_code == 200, response.text
    assert response.json()["link_token"] == LINK_TOKEN and response.json()["expiration"]
    path, body = plaid.calls[-1]
    assert path == "/link/token/create" and body["products"] == ["transactions"]
    assert body["user"] == {"client_user_id": str(test_user.id)} and "access_token" not in body


async def test_exchange_creates_a_connection_and_syncs(client, db_session, test_user, plaid):
    plaid.page("", added=[txn("t1", day=utcnow().date().isoformat())], next_cursor="c1")
    connection = await connect(client, db_session, institution_name="Synthetic Bank")
    assert connection.provider == "plaid" and connection.environment == "sandbox"
    assert connection.provider_connection_id == ITEM_ID and connection.status == "NEW"
    assert connection.institution_name == "Synthetic Bank" and ACCESS_TOKEN not in connection.credentials_encrypted
    assert secrets.decrypt(connection.credentials_encrypted) == ACCESS_TOKEN
    assert plaid.paths() == ["/item/public_token/exchange"]
    assert sync_worker.sync_one_due(TestSession)
    db_session.expire_all()
    listed = (await client.get("/api/ledger/connections")).json()
    assert len(listed) == 1 and listed[0]["label"] == "Plaid" and listed[0]["status"] == "ACTIVE"
    card = next(a for a in listed[0]["accounts"] if a["name"] == "Synthetic card")
    assert card["type_confirmed"] and card["transaction_count"] == 1 and card["editable"] is False
    # Linking the same Item again keeps the connection.
    again = await client.post("/api/ledger/connections/plaid", json={"public_token": PUBLIC_TOKEN})
    assert again.status_code == 200 and again.json()["id"] == str(connection.id)


async def test_exchange_refusals(client, db_session, test_user, plaid, monkeypatch):
    both = await client.post("/api/ledger/connections/plaid",
                             json={"public_token": PUBLIC_TOKEN, "connection_id": str(uuid.uuid4())})
    assert both.status_code == 422
    assert (await client.post("/api/ledger/connections/plaid", json={})).status_code == 422
    plaid.failures["/item/public_token/exchange"] = (400, "INVALID_INPUT", "INVALID_PUBLIC_TOKEN")
    bad = await client.post("/api/ledger/connections/plaid", json={"public_token": PUBLIC_TOKEN})
    assert bad.status_code == 502 and bad.json()["error"]["code"] == "PROVIDER_ERROR"
    del plaid.failures["/item/public_token/exchange"]

    def no_key(secret):
        raise secrets.EncryptionUnavailable()

    monkeypatch.setattr(secrets, "encrypt", no_key)
    missing = await client.post("/api/ledger/connections/plaid", json={"public_token": PUBLIC_TOKEN})
    assert missing.status_code == 503 and missing.json()["error"]["code"] == "INTEGRATION_UNAVAILABLE"
    # The exchanged Item is removed rather than left billed and unreachable.
    assert removals(plaid) == [{"access_token": ACCESS_TOKEN}]
    plaid.failures["/item/remove"] = (500, "API_ERROR", "INTERNAL_SERVER_ERROR")
    still = await client.post("/api/ledger/connections/plaid", json={"public_token": PUBLIC_TOKEN})
    assert still.status_code == 503
    assert db_session.query(FinancialConnection).count() == 0


async def test_an_item_owned_by_someone_else_is_refused(client, db_session, test_user, plaid):
    stranger = other_user(db_session)
    lifecycle.create_connection(db_session, stranger.id, "plaid", ACCESS_TOKEN, provider_connection_id=ITEM_ID)
    db_session.commit()
    refused = await client.post("/api/ledger/connections/plaid", json={"public_token": PUBLIC_TOKEN})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "CONFLICT"
    assert removals(plaid) == [{"access_token": ACCESS_TOKEN}]


async def test_a_server_without_a_plug_in_links_an_anonymous_session(client, db_session, test_user, plaid, monkeypatch):
    monkeypatch.setattr(extensions, "access_policy", None)  # self-hosted: app.access.FULL_ACCESS
    test_user.is_anonymous = True
    db_session.commit()
    assert (await client.post("/api/ledger/connections/plaid/link-token", json={})).status_code == 200
    connection = await connect(client, db_session)
    assert connection.user_id == test_user.id


async def test_gating_and_not_offered(client, db_session, test_user, plaid, monkeypatch):
    monkeypatch.setenv("PLAID_ENABLED", "false")
    off = await client.post("/api/ledger/connections/plaid", json={"public_token": PUBLIC_TOKEN})
    assert off.status_code == 503 and off.json()["error"]["message"] == "Plaid is not enabled on this server."
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "false")
    gated = await client.post("/api/ledger/connections/plaid/link-token", json={})
    assert gated.status_code == 503 and gated.json()["error"]["code"] == "FEATURE_DISABLED"
    assert plaid.calls == []


async def test_link_token_failure_uses_the_error_envelope(client, plaid):
    plaid.failures["/link/token/create"] = (400, "INVALID_REQUEST", "INVALID_API_KEYS")
    failed = await client.post("/api/ledger/connections/plaid/link-token", json={})
    assert failed.status_code == 503 and failed.json()["error"]["code"] == "PROVIDER_CONFIGURATION"


async def test_update_mode_reconnects(client, db_session, test_user, plaid, monkeypatch):
    connection = await connect(client, db_session)
    connection.status, connection.error, connection.next_check_at = "RECONNECT_REQUIRED", "Sign in again.", None
    db_session.commit()
    token = await client.post("/api/ledger/connections/plaid/link-token", json={"connection_id": str(connection.id)})
    assert token.status_code == 200
    path, body = plaid.calls[-1]
    assert body["access_token"] == ACCESS_TOKEN and "products" not in body
    done = await client.post("/api/ledger/connections/plaid", json={"connection_id": str(connection.id)})
    assert done.status_code == 200 and done.json()["status"] == "NEW" and done.json()["error"] is None
    db_session.expire_all()
    assert connection.next_check_at is not None and secrets.decrypt(connection.credentials_encrypted) == ACCESS_TOKEN
    # Unknown, other-provider and unreadable connections are refused.
    missing = await client.post("/api/ledger/connections/plaid/link-token", json={"connection_id": str(uuid.uuid4())})
    assert missing.status_code == 404
    other = lifecycle.create_connection(db_session, test_user.id, "simplefin", "https://u:p@bridge.example/simplefin")
    db_session.commit()
    wrong = await client.post("/api/ledger/connections/plaid", json={"connection_id": str(other.id)})
    assert wrong.status_code == 404
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", "another-synthetic-ledger-key-0123456789")
    unreadable = await client.post("/api/ledger/connections/plaid/link-token",
                                   json={"connection_id": str(connection.id)})
    assert unreadable.status_code == 409 and unreadable.json()["error"]["code"] == "CREDENTIAL_UNAVAILABLE"


async def test_disconnect_removes_the_item(client, db_session, test_user, plaid):
    connection = await connect(client, db_session)
    assert sync_worker.sync_one_due(TestSession)
    db_session.expire_all()
    assert (await client.delete(f"/api/ledger/connections/{connection.id}")).status_code == 204
    db_session.expire_all()
    assert removals(plaid) == [{"access_token": ACCESS_TOKEN}]
    assert connection.disconnected and connection.credentials_encrypted is None and connection.sync_cursor is None
    assert {s.status for s in db_session.query(FinancialSource).filter_by(user_id=test_user.id)} == {"INACTIVE"}
    # Linking the same Item after a disconnect reuses its row and accounts.
    again = await client.post("/api/ledger/connections/plaid", json={"public_token": PUBLIC_TOKEN})
    assert again.status_code == 200 and again.json()["id"] == str(connection.id)


async def test_disconnect_with_a_failed_removal_stays_connected(client, db_session, test_user, plaid):
    connection = await connect(client, db_session)
    plaid.failures["/item/remove"] = (500, "API_ERROR", "INTERNAL_SERVER_ERROR")
    failed = await client.delete(f"/api/ledger/connections/{connection.id}")
    assert failed.status_code == 502 and failed.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert "Try again later" in failed.json()["error"]["message"]
    db_session.expire_all()
    assert not connection.disconnected and connection.credentials_encrypted


async def test_account_deletion_removes_plaid_items(client, db_session, test_user, plaid):
    await connect(client, db_session)
    user_id = test_user.id
    assert (await client.request("DELETE", "/api/auth/me", json={"confirmation": "DELETE"})).status_code == 204
    db_session.expire_all()
    assert db_session.get(User, user_id) is None and removals(plaid) == [{"access_token": ACCESS_TOKEN}]


async def test_account_deletion_waits_for_a_failed_item_removal(client, db_session, test_user, plaid):
    connection = await connect(client, db_session)
    plaid.failures["/item/remove"] = (500, "API_ERROR", "INTERNAL_SERVER_ERROR")
    failed = await client.request("DELETE", "/api/auth/me", json={"confirmation": "DELETE"})
    assert failed.status_code == 503 and failed.json()["error"]["code"] == "DELETION_CONNECTION_PENDING"
    db_session.expire_all()
    assert db_session.get(User, test_user.id) is not None and not connection.disconnected

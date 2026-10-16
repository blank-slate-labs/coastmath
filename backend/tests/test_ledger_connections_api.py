"""/api/ledger connection routes: providers, SimpleFIN link and reconnect, sync, disconnect, links, deletion."""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.ledger import connections as lifecycle
from app.ledger import secrets, sync_worker
from app.ledger.providers.errors import ProviderError
from app.ledger.providers.simplefin_adapter import SimpleFINAdapter
from app.models.account import CurrentAccount
from app.models.financial_connection import (
    FinancialBalanceLink,
    FinancialConnection,
    FinancialSource,
    FinancialTransaction,
    utcnow,
)
from app.models.liability import Liability
from app.models.user import User
from app.plugins import extensions
from app.routers.ledger_connections import require_linkable
from tests.conftest import TestSession
from tests.ledger_fixture import (
    make_source,
    other_user,
    plan_with_feed,
    plugin_provider,
)
from tests.simplefin_bridge import ACCESS_URL, SETUP_TOKEN, Bridge, install

pytestmark = pytest.mark.anyio
KEY = "synthetic-ledger-key-0123456789-abcdef"


@pytest.fixture
def env(monkeypatch, test_user, db_session):
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "true")
    monkeypatch.setenv("SIMPLEFIN_ENABLED", "true")
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", KEY)
    test_user.is_anonymous = False
    db_session.commit()


@pytest.fixture
def bridge(monkeypatch, env):
    bridge = Bridge(utcnow().date())
    bridge.add("ACT-card", "t1", 3, "-40.00")
    install(monkeypatch, bridge)
    return bridge


async def linked(client, db_session, test_user) -> FinancialConnection:
    created = await client.post("/api/ledger/connections/simplefin", json={"setup_token": SETUP_TOKEN})
    assert created.status_code == 201, created.text
    connection_id = uuid.UUID(created.json()["id"])
    assert sync_worker.sync_one_due(TestSession)
    db_session.expire_all()
    return db_session.get(FinancialConnection, connection_id)


def card_of(db_session, test_user) -> FinancialSource:
    return db_session.query(FinancialSource).filter_by(user_id=test_user.id, provider_account_id="ACT-card").one()


async def test_providers_list_offers_and_reasons(client, env, monkeypatch):
    found = {p["key"]: p for p in (await client.get("/api/ledger/providers")).json()}
    assert found["simplefin"]["offered"] and found["simplefin"]["link_flow"] == "token"
    assert found["simplefin"]["history_days"] == 365 and "balances" in found["simplefin"]["capabilities"]
    assert found["file"]["offered"]
    monkeypatch.setenv("SIMPLEFIN_ENABLED", "false")
    found = {p["key"]: p for p in (await client.get("/api/ledger/providers")).json()}
    assert found["simplefin"]["reason"] == "SimpleFIN is not enabled on this server."


async def test_connect_syncs_in_the_background(client, db_session, test_user, bridge):
    created = await client.post("/api/ledger/connections/simplefin", json={"setup_token": SETUP_TOKEN})
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "NEW" and body["provider"] == "simplefin" and body["label"] == "SimpleFIN"
    assert body["accounts"] == [] and bridge.claims == 1 and bridge.reads == []
    row = db_session.get(FinancialConnection, uuid.UUID(body["id"]))
    assert row.environment == "production" and ACCESS_URL not in row.credentials_encrypted
    assert secrets.decrypt(row.credentials_encrypted) == ACCESS_URL
    assert sync_worker.sync_one_due(TestSession)
    db_session.expire_all()
    listed = (await client.get("/api/ledger/connections")).json()
    assert len(listed) == 1 and listed[0]["status"] == "ACTIVE" and listed[0]["last_success_at"]
    accounts = {a["name"]: a for a in listed[0]["accounts"]}
    card = accounts["Synthetic card"]
    assert card["type_confirmed"] is False and card["counts_toward_spending"] is False
    assert card["blocked_reason"] == "Confirm this account's type before using its balance."
    assert card["balance"] == -250.0 and card["revision"] == 1 and card["links"] == []
    assert card["transaction_count"] == 1 and card["editable"] is True


async def test_connect_refusals(client, db_session, test_user, bridge, monkeypatch):
    bad = await client.post("/api/ledger/connections/simplefin", json={"setup_token": "not base64 !"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "PROVIDER_TOKEN_INVALID"
    bridge.claim_status = 403
    used = await client.post("/api/ledger/connections/simplefin", json={"setup_token": SETUP_TOKEN})
    assert used.status_code == 409 and used.json()["error"]["code"] == "PROVIDER_TOKEN_USED"
    bridge.claim_status = 200

    def no_key(secret):
        raise secrets.EncryptionUnavailable()

    monkeypatch.setattr(secrets, "encrypt", no_key)
    missing = await client.post("/api/ledger/connections/simplefin", json={"setup_token": SETUP_TOKEN})
    assert missing.status_code == 503 and missing.json()["error"]["code"] == "INTEGRATION_UNAVAILABLE"
    monkeypatch.undo()
    install(monkeypatch, bridge)
    for name, value in (("TRANSACTIONS_ENABLED", "true"), ("SIMPLEFIN_ENABLED", "true"), ("LEDGER_ENCRYPTION_KEY", KEY)):
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("SIMPLEFIN_ENABLED", "false")
    off = await client.post("/api/ledger/connections/simplefin", json={"setup_token": SETUP_TOKEN})
    assert off.status_code == 503 and off.json()["error"]["message"] == "SimpleFIN is not enabled on this server."
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "false")
    gated = await client.post("/api/ledger/connections/simplefin", json={"setup_token": SETUP_TOKEN})
    assert gated.status_code == 503 and gated.json()["error"]["code"] == "FEATURE_DISABLED"
    assert db_session.query(FinancialConnection).count() == 0


async def test_require_linkable_without_a_registered_provider():
    with pytest.raises(HTTPException) as error:
        require_linkable("unknown", User(is_anonymous=False))
    assert error.value.detail["error"]["message"] == "This provider is not offered on this server."


async def test_reconnect_replaces_the_credential(client, db_session, test_user, bridge):
    connection = await linked(client, db_session, test_user)
    connection.status, connection.next_check_at = "RECONNECT_REQUIRED", None
    db_session.commit()
    before = connection.credentials_encrypted
    again = await client.post("/api/ledger/connections/simplefin",
                              json={"setup_token": SETUP_TOKEN, "connection_id": str(connection.id)})
    assert again.status_code == 200 and again.json()["status"] == "NEW"
    db_session.expire_all()
    assert connection.credentials_encrypted != before and connection.error is None and connection.next_check_at
    assert db_session.query(FinancialConnection).count() == 1 and len(again.json()["accounts"]) == 2
    missing = await client.post("/api/ledger/connections/simplefin",
                                json={"setup_token": SETUP_TOKEN, "connection_id": str(uuid.uuid4())})
    assert missing.status_code == 404
    plaid = FinancialConnection(user_id=test_user.id, provider="plaid", environment="sandbox",
                                provider_connection_id="item-synthetic", status="ACTIVE")
    db_session.add(plaid)
    db_session.commit()
    wrong = await client.post("/api/ledger/connections/simplefin",
                              json={"setup_token": SETUP_TOKEN, "connection_id": str(plaid.id)})
    assert wrong.status_code == 404


async def test_manual_sync_rules(client, db_session, test_user, bridge, monkeypatch):
    connection = await linked(client, db_session, test_user)
    url = f"/api/ledger/connections/{connection.id}/sync"
    soon = await client.post(url)
    assert soon.status_code == 429 and soon.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    connection.last_checked_at = utcnow() - timedelta(hours=1)
    connection.next_check_at = utcnow() + timedelta(hours=11)
    db_session.commit()
    scheduled = await client.post(url)
    assert scheduled.status_code == 200
    db_session.expire_all()
    assert connection.next_check_at.replace(tzinfo=UTC) <= utcnow()
    # While a worker holds the lease, a request changes nothing.
    connection.status, connection.next_check_at = "SYNCING", utcnow() + timedelta(minutes=10)
    db_session.commit()
    assert (await client.post(url)).json()["status"] == "SYNCING"
    connection.status = "RECONNECT_REQUIRED"
    db_session.commit()
    blocked = await client.post(url)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "RECONNECT_REQUIRED"
    assert (await client.post(f"/api/ledger/connections/{uuid.uuid4()}/sync")).status_code == 404
    connection.disconnected = True
    db_session.commit()
    assert (await client.post(url)).status_code == 404
    monkeypatch.setenv("SIMPLEFIN_ENABLED", "false")
    assert (await client.post(url)).status_code == 503


async def test_sync_refuses_a_provider_without_pull_sync(client, db_session, test_user, env):
    plaid = FinancialConnection(user_id=test_user.id, provider="plaid", environment="sandbox",
                                provider_connection_id="item-synthetic", status="ACTIVE")
    files = FinancialConnection(user_id=test_user.id, provider="file", environment="production",
                                provider_connection_id="file-synthetic", status="ACTIVE")
    db_session.add_all([plaid, files])
    db_session.commit()
    refused = await client.post(f"/api/ledger/connections/{plaid.id}/sync")
    assert refused.status_code == 503 and refused.json()["error"]["message"] == "Plaid is not enabled on this server."
    refused = await client.post(f"/api/ledger/connections/{files.id}/sync")
    assert refused.status_code == 503 and refused.json()["error"]["message"] == "This provider cannot sync on this server."


async def test_disconnect_keeps_or_removes_data(client, db_session, test_user, bridge, monkeypatch):
    connection = await linked(client, db_session, test_user)
    card = card_of(db_session, test_user)
    plan, feed = plan_with_feed(db_session, test_user, [card.id])
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "false")
    kept = await client.delete(f"/api/ledger/connections/{connection.id}")
    assert kept.status_code == 204
    db_session.expire_all()
    assert connection.disconnected and connection.credentials_encrypted is None and connection.status == "DISCONNECTED"
    assert card.status == "INACTIVE" and card.connection_ids == [] and card.revision == 2
    assert db_session.query(FinancialTransaction).filter_by(source_id=card.id).count() == 1
    assert (await client.get("/api/ledger/connections")).json() == []
    removed = await client.delete(f"/api/ledger/connections/{connection.id}?remove_data=true")
    assert removed.status_code == 204
    db_session.expire_all()
    # Accounts already detached stay; a fresh connection's accounts go with remove_data.
    assert db_session.query(FinancialSource).filter_by(user_id=test_user.id).count() == 2
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "true")
    second = await linked(client, db_session, test_user)
    assert (await client.delete(f"/api/ledger/connections/{second.id}?remove_data=true")).status_code == 204
    db_session.expire_all()
    assert db_session.query(FinancialSource).filter_by(user_id=test_user.id).count() == 0
    assert db_session.query(FinancialTransaction).count() == 0
    assert (await client.delete(f"/api/ledger/connections/{uuid.uuid4()}")).status_code == 404


async def test_shared_accounts_stay_while_another_connection_refreshes_them(client, db_session, test_user, bridge):
    first = await linked(client, db_session, test_user)
    second = await linked(client, db_session, test_user)
    card = card_of(db_session, test_user)
    assert set(card.connection_ids) == {first.provider_connection_id, second.provider_connection_id}
    assert (await client.delete(f"/api/ledger/connections/{first.id}?remove_data=true")).status_code == 204
    db_session.expire_all()
    assert card.status == "ACTIVE" and card.connection_ids == [second.provider_connection_id]


async def test_failed_revocation_keeps_the_connection(client, db_session, test_user, bridge, monkeypatch):
    connection = await linked(client, db_session, test_user)

    def refuse(self, secret):
        raise ProviderError("PROVIDER_UNAVAILABLE", "The provider could not be reached. Try again later.", 502)

    monkeypatch.setattr(SimpleFINAdapter, "revoke", refuse)
    failed = await client.delete(f"/api/ledger/connections/{connection.id}")
    assert failed.status_code == 502 and failed.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"
    db_session.expire_all()
    assert not connection.disconnected and connection.credentials_encrypted
    # An unreadable credential has nothing to revoke.
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", "another-synthetic-ledger-key-0123456789")
    assert (await client.delete(f"/api/ledger/connections/{connection.id}")).status_code == 204


async def test_confirming_a_type_applies_the_amount_owed(client, db_session, test_user, bridge):
    await linked(client, db_session, test_user)
    card = card_of(db_session, test_user)
    confirmed = await client.patch(f"/api/ledger/accounts/{card.id}",
                                   json={"account_type": "CREDIT", "subtype": "CREDIT_CARD"})
    assert confirmed.status_code == 200 and confirmed.json()["counts_toward_spending"] is True
    db_session.expire_all()
    assert card.balance == Decimal("250.00") and card.revision == 2
    back = await client.patch(f"/api/ledger/accounts/{card.id}", json={"account_type": "DEPOSITORY"})
    assert back.status_code == 200
    db_session.expire_all()
    assert card.balance == Decimal("-250.00")
    await client.patch(f"/api/ledger/accounts/{card.id}", json={"account_type": "INVESTMENT"})
    db_session.expire_all()
    assert card.balance == Decimal("-250.00")


async def test_links_for_synced_accounts(client, db_session, test_user, bridge):
    connection = await linked(client, db_session, test_user)
    card = card_of(db_session, test_user)
    plan, _ = plan_with_feed(db_session, test_user, [])
    body = {"plan_id": str(plan.id), "source_revision": card.revision,
            "new_liability": {"name": "Synthetic card", "principal_balance": 1,
                              "interest_rate": 20, "monthly_payment": 25}}
    unconfirmed = await client.post(f"/api/ledger/accounts/{card.id}/link", json=body)
    assert unconfirmed.status_code == 422
    await client.patch(f"/api/ledger/accounts/{card.id}", json={"account_type": "CREDIT", "subtype": "CREDIT_CARD"})
    db_session.expire_all()
    body["source_revision"] = card.revision
    created = await client.post(f"/api/ledger/accounts/{card.id}/link", json=body)
    assert created.status_code == 201, created.text
    link = created.json()
    assert link["last_applied_balance"] == 250.0 and link["liability_id"]
    listed = (await client.get("/api/ledger/connections")).json()[0]
    assert [a for a in listed["accounts"] if a["id"] == str(card.id)][0]["links"][0]["id"] == link["id"]
    # The next sync pushes the new balance through the link.
    bridge.balances["ACT-card"] = "-275.00"
    connection.next_check_at = utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert sync_worker.sync_one_due(TestSession)
    db_session.expire_all()
    liability = db_session.get(Liability, uuid.UUID(link["liability_id"]))
    assert liability.principal_balance == Decimal("275.00")
    # A file account has no balance link; another user's link is not found.
    file_source = make_source(db_session, test_user)
    db_session.commit()
    assert (await client.post(f"/api/ledger/accounts/{file_source.id}/link", json=body)).status_code == 404
    stranger = other_user(db_session)
    foreign = make_source(db_session, stranger, provider="simplefin", external="ACT-foreign")
    db_session.commit()
    assert (await client.post(f"/api/ledger/accounts/{foreign.id}/link", json=body)).status_code == 404
    assert (await client.delete(f"/api/ledger/links/{link['id']}")).status_code == 204
    assert (await client.delete(f"/api/ledger/links/{link['id']}")).status_code == 404


async def test_links_need_a_live_connection_and_ignore_self_managed_providers(client, db_session, test_user, bridge,
                                                                              monkeypatch):
    connection = await linked(client, db_session, test_user)
    checking = db_session.query(FinancialSource).filter_by(provider_account_id="ACT-check").one()
    await client.patch(f"/api/ledger/accounts/{checking.id}", json={"account_type": "DEPOSITORY", "subtype": "CHECKING"})
    connection.status = "RECONNECT_REQUIRED"
    db_session.commit()
    db_session.expire_all()
    plan, _ = plan_with_feed(db_session, test_user, [])
    account = CurrentAccount(user_id=test_user.id, plan_id=plan.id, name="Synthetic checking",
                             account_type="checking", balance=100)
    db_session.add(account)
    db_session.commit()
    body = {"plan_id": str(plan.id), "source_revision": checking.revision, "account_id": str(account.id),
            "expected_balance": 100}
    refused = await client.post(f"/api/ledger/accounts/{checking.id}/link", json=body)
    assert refused.status_code == 409 and "Reconnect" in refused.json()["error"]["message"]
    connection.status = "ACTIVE"
    db_session.commit()
    created = await client.post(f"/api/ledger/accounts/{checking.id}/link", json=body)
    assert created.status_code == 201
    db_session.expire_all()
    assert account.balance == Decimal("1200.50")
    own = plugin_provider(monkeypatch, own_lifecycle=True)
    own_source = make_source(db_session, test_user, provider=own, environment="sandbox", external="own-1")
    other = CurrentAccount(user_id=test_user.id, plan_id=plan.id, name="Synthetic savings", account_type="savings",
                           balance=5)
    db_session.add(other)
    db_session.flush()
    own_link = FinancialBalanceLink(user_id=test_user.id, source_id=own_source.id, plan_id=plan.id,
                                     account_id=other.id, last_applied_balance=5, source_revision=1,
                                     source_type="DEPOSITORY")
    db_session.add(own_link)
    db_session.flush()
    assert (await client.delete(f"/api/ledger/links/{own_link.id}")).status_code == 404


async def test_account_deletion_drops_neutral_credentials(client, db_session, test_user, bridge, monkeypatch):
    connection = await linked(client, db_session, test_user)
    user_id, connection_id = test_user.id, connection.id
    dropped = []
    original = lifecycle.drop
    monkeypatch.setattr(lifecycle, "drop", lambda row: dropped.append(row.id) or original(row))
    assert (await client.request("DELETE", "/api/auth/me", json={"confirmation": "DELETE"})).status_code == 204
    db_session.expire_all()
    assert db_session.get(User, user_id) is None and dropped == [connection_id]


async def test_account_deletion_waits_for_a_failed_revocation(client, db_session, test_user, bridge, monkeypatch):
    connection = await linked(client, db_session, test_user)

    def refuse(self, secret):
        raise ProviderError("PROVIDER_UNAVAILABLE", "The provider could not be reached. Try again later.", 502)

    monkeypatch.setattr(SimpleFINAdapter, "revoke", refuse)
    failed = await client.request("DELETE", "/api/auth/me", json={"confirmation": "DELETE"})
    assert failed.status_code == 503 and failed.json()["error"]["code"] == "DELETION_CONNECTION_PENDING"
    db_session.expire_all()
    assert db_session.get(User, test_user.id) is not None and not connection.disconnected


async def test_unlinked_reads_cover_naive_timestamps(client, db_session, test_user, bridge):
    connection = await linked(client, db_session, test_user)
    connection.last_checked_at = datetime.now() - timedelta(hours=2)
    db_session.commit()
    assert (await client.post(f"/api/ledger/connections/{connection.id}/sync")).status_code == 200


async def test_a_server_without_a_plug_in_never_gates_linking(client, db_session, test_user, bridge, monkeypatch):
    monkeypatch.setattr(extensions, "access_policy", None)  # self-hosted: app.access.FULL_ACCESS
    # A self-hosted session is the only account there is; it never signs in.
    test_user.is_anonymous = True
    db_session.commit()
    connection = await linked(client, db_session, test_user)
    connection.last_checked_at = utcnow() - timedelta(hours=1)
    db_session.commit()
    synced = await client.post(f"/api/ledger/connections/{connection.id}/sync")
    assert synced.status_code == 200, synced.text

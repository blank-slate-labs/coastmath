"""Plaid adapter on the sync seam: pages, cursor persistence, removals, pending replacement, coverage, schedules."""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.ledger import connections as lifecycle
from app.ledger import sync_worker
from app.ledger.balances import aware
from app.ledger.providers import plaid_adapter
from app.ledger.providers.errors import ProviderError
from app.ledger.providers.plaid_client import DAYS_REQUESTED, PlaidClient
from app.models.financial_connection import (
    FinancialConnection,
    FinancialSource,
    FinancialTransaction,
    utcnow,
)
from tests.conftest import TestSession
from tests.plaid_server import ACCESS_TOKEN, ITEM_ID, txn


@pytest.fixture
def connection(plaid, db_session, test_user) -> FinancialConnection:
    row = lifecycle.create_connection(db_session, test_user.id, "plaid", ACCESS_TOKEN, provider_connection_id=ITEM_ID,
                                      institution_name="Synthetic Bank")
    db_session.commit()
    return row


def day(days_ago: int) -> str:
    return (utcnow().date() - timedelta(days=days_ago)).isoformat()


def sync(db_session, connection, now=None) -> bool:
    now = now or utcnow()
    claimed = sync_worker.claim_due(TestSession, now)
    assert claimed in (connection.id, None)
    if claimed is None:
        return False
    with TestSession() as db:
        result = sync_worker.run_connection(db, claimed, now)
    db_session.expire_all()
    return result


def sources(db_session, test_user) -> dict[str, FinancialSource]:
    return {row.provider_account_id: row for row in db_session.query(FinancialSource).filter_by(user_id=test_user.id)}


def stored(db_session) -> dict[str, FinancialTransaction]:
    return {row.provider_transaction_id: row for row in db_session.query(FinancialTransaction)}


def test_first_sync_follows_pages_and_saves_the_cursor(plaid, connection, db_session, test_user):
    plaid.page("", added=[txn("t1", day=day(40)), txn("t2", account_id="acc-check", amount=-900, day=day(20))],
               next_cursor="c1", has_more=True, status="INITIAL_UPDATE_COMPLETE")
    plaid.page("c1", added=[txn("p1", day=day(1), pending=True)], next_cursor="c2",
               status="INITIAL_UPDATE_COMPLETE")
    now = utcnow()
    assert sync(db_session, connection, now)
    assert connection.status == "ACTIVE" and connection.sync_cursor == "c2"
    assert connection.institution_name == "Synthetic Bank"
    assert aware(connection.next_check_at) == now + plaid_adapter.HISTORY_LOADING
    assert plaid.paths()[:3] == ["/transactions/sync", "/transactions/sync", "/accounts/get"]
    assert plaid.calls[1][1]["cursor"] == "c1" and "cursor" not in plaid.calls[0][1]
    found = sources(db_session, test_user)
    card, check = found["acc-card"], found["acc-check"]
    assert (card.account_type, card.subtype, card.mask) == ("CREDIT", "CREDIT_CARD", "4321")
    assert (check.account_type, check.subtype) == ("DEPOSITORY", "CHECKING")
    # Plaid reports the amount owed; the read time stands in for the missing balance time.
    assert card.balance == Decimal("250.00") and aware(card.balance_updated_at) == now
    assert card.institution_name == "Synthetic Bank" and card.connection_ids == [ITEM_ID]
    # Still loading history: each account covers from its own earliest transaction.
    assert card.transactions_coverage_start.isoformat() == day(40)
    assert check.transactions_coverage_start.isoformat() == day(20)
    assert not card.transactions_history_complete
    rows = stored(db_session)
    assert set(rows) == {"acc-card:t1", "acc-check:t2", "acc-card:p1"}
    assert rows["acc-card:p1"].status == "PENDING" and rows["acc-check:t2"].amount == Decimal("-900.00")


def test_later_pass_replaces_pending_removes_and_completes_history(plaid, connection, db_session, test_user):
    plaid.page("", added=[txn("t1", day=day(40)), txn("p1", day=day(2), pending=True),
                          txn("gone", account_id="acc-check", day=day(10))], next_cursor="c1",
               status="INITIAL_UPDATE_COMPLETE")
    assert sync(db_session, connection)
    pending = stored(db_session)["acc-card:p1"]
    pending.category_override, pending.one_time = "gifts_donations", True
    db_session.commit()
    plaid.page("c1", added=[txn("t9", day=day(1), pending_transaction_id="p1"),
                            txn("old", account_id="acc-check", day=day(300))],
               modified=[txn("t1", amount=99, day=day(40))],
               removed=[{"transaction_id": "p1"}, {"transaction_id": "gone", "account_id": "acc-check"}],
               next_cursor="c2")
    connection.next_check_at = utcnow()
    db_session.commit()
    assert sync(db_session, connection)
    rows = stored(db_session)
    assert set(rows) == {"acc-card:t1", "acc-card:t9", "acc-check:old"}
    posted = rows["acc-card:t9"]
    assert posted.status == "POSTED" and posted.category_override == "gifts_donations" and posted.one_time
    assert rows["acc-card:t1"].amount == Decimal("99.00")
    assert connection.sync_cursor == "c2"
    assert aware(connection.next_check_at) > utcnow() + timedelta(hours=23)
    found = sources(db_session, test_user)
    # History complete: every account covers from the Item's earliest transaction.
    assert found["acc-card"].transactions_coverage_start.isoformat() == day(300)
    assert found["acc-check"].transactions_coverage_start.isoformat() == day(300)
    assert found["acc-card"].transactions_history_complete


def test_history_complete_without_transactions_covers_the_requested_days(plaid, connection, db_session, test_user):
    plaid.page("", next_cursor="c1")
    assert sync(db_session, connection)
    start = sources(db_session, test_user)["acc-card"].transactions_coverage_start
    assert start == utcnow().date() - timedelta(days=DAYS_REQUESTED)


def test_a_failed_read_keeps_the_cursor(plaid, connection, db_session):
    plaid.page("", added=[txn("t1", day=day(3))], next_cursor="c1", has_more=True)
    plaid.failures["/accounts/get"] = (500, "API_ERROR", "INTERNAL_SERVER_ERROR")
    assert not sync(db_session, connection)
    assert connection.status == "RETRYING" and connection.sync_cursor is None
    assert db_session.query(FinancialTransaction).count() == 0


def test_a_failed_store_keeps_the_cursor_and_rows(plaid, connection, db_session, monkeypatch):
    plaid.page("", added=[txn("t1", day=day(3))], removed=[{"transaction_id": "x"}], next_cursor="c1")

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic store failure")

    monkeypatch.setattr(plaid_adapter, "remove_transactions", broken)
    assert not sync(db_session, connection)
    assert connection.sync_cursor is None and connection.status == "RETRYING"
    assert db_session.query(FinancialTransaction).count() == 0 and db_session.query(FinancialSource).count() == 0


def test_login_required_stops_retries(plaid, connection, db_session):
    plaid.failures["/transactions/sync"] = (400, "ITEM_ERROR", "ITEM_LOGIN_REQUIRED")
    assert not sync(db_session, connection)
    assert connection.status == "RECONNECT_REQUIRED" and connection.next_check_at is None
    assert connection.error == "This bank connection needs you to sign in again."
    assert sync_worker.claim_due(TestSession, utcnow() + timedelta(days=3)) is None


def test_accounts_for_another_item_are_refused(plaid, connection, db_session):
    plaid.item_id = "item-other"
    assert not sync(db_session, connection)
    assert connection.status == "RETRYING" and connection.error == "Plaid returned accounts for a different connection."


def test_unlisted_accounts_go_inactive_and_unknown_rows_are_dropped(plaid, connection, db_session, test_user):
    plaid.page("", added=[txn("t1", day=day(3))], next_cursor="c1")
    assert sync(db_session, connection)
    check = sources(db_session, test_user)["acc-check"]
    revision = check.revision
    plaid.accounts = plaid.accounts[:1]
    plaid.institution_name = None
    plaid.page("c1", added=[txn("t2", account_id="acc-check", day=day(2)), txn("t3", account_id="acc-new", day=day(2))],
               next_cursor="c2")
    connection.next_check_at = utcnow()
    db_session.commit()
    assert sync(db_session, connection)
    found = sources(db_session, test_user)
    assert found["acc-check"].status == "INACTIVE" and found["acc-check"].revision == revision + 1
    # Rows for a known but unlisted account are kept; rows for an unknown account are dropped.
    assert set(stored(db_session)) == {"acc-card:t1", "acc-check:t2"}
    assert connection.institution_name == "Synthetic Bank" and found["acc-card"].institution_name == "Synthetic Bank"


def test_an_older_balance_never_replaces_a_newer_one(plaid, connection, db_session, test_user):
    assert sync(db_session, connection)
    card = sources(db_session, test_user)["acc-card"]
    card.balance_updated_at = utcnow() + timedelta(days=1)
    db_session.commit()
    plaid.accounts[0]["balances"]["current"] = 999
    connection.next_check_at = utcnow()
    db_session.commit()
    assert sync(db_session, connection)
    assert sources(db_session, test_user)["acc-card"].balance == Decimal("250.00")


def test_revoke_removes_the_item(plaid):
    adapter = plaid_adapter.PlaidAdapter()
    adapter.revoke(ACCESS_TOKEN)
    assert plaid.calls[-1] == ("/item/remove", {"access_token": ACCESS_TOKEN})
    plaid.failures["/item/remove"] = (400, "ITEM_ERROR", "ITEM_NOT_FOUND")
    adapter.revoke(ACCESS_TOKEN)  # Already gone counts as removed.
    plaid.failures["/item/remove"] = (500, "API_ERROR", "INTERNAL_SERVER_ERROR")
    with pytest.raises(ProviderError) as error:
        adapter.revoke(ACCESS_TOKEN)
    assert error.value.code == "PROVIDER_UNAVAILABLE"


def test_default_client_uses_operator_settings(monkeypatch):
    monkeypatch.setenv("PLAID_CLIENT_ID", "demo-client-id")
    monkeypatch.setenv("PLAID_SECRET", "demo-secret-value")
    client = plaid_adapter.make_client()
    assert isinstance(client, PlaidClient) and client.settings.configured

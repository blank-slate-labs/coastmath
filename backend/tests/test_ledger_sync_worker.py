"""Ledger sync worker and SimpleFIN adapter: leases, schedules, windows, reconciliation and coverage."""
import asyncio
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.orm import object_session

from app.access import BANK_LINKING, AccessPolicy
from app.ledger import connections as lifecycle
from app.ledger import secrets, sync_worker
from app.ledger.balances import aware
from app.ledger.providers import simplefin_adapter
from app.ledger.providers.simplefin_adapter import SimpleFINAdapter
from app.models.financial_connection import (
    FinancialConnection,
    FinancialSource,
    FinancialTransaction,
    utcnow,
)
from app.plugins import extensions
from tests.conftest import TestSession
from tests.ledger_fixture import other_user
from tests.simplefin_bridge import ACCESS_URL, Bridge, install

KEY = "synthetic-ledger-key-0123456789-abcdef"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "true")
    monkeypatch.setenv("SIMPLEFIN_ENABLED", "true")
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", KEY)
    monkeypatch.delenv("LEDGER_ENCRYPTION_KEYS_PREVIOUS", raising=False)


@pytest.fixture
def now():
    return utcnow()


@pytest.fixture
def bridge(monkeypatch, env, now):
    bridge = Bridge(now.date())
    install(monkeypatch, bridge)
    return bridge


def connect(db, user, now, **values) -> FinancialConnection:
    connection = lifecycle.create_connection(db, user.id, "simplefin", ACCESS_URL, now=now - timedelta(seconds=1))
    for key, value in values.items():
        setattr(connection, key, value)
    db.commit()
    return connection


def run(db, connection, now) -> bool:
    connection_id = sync_worker.claim_due(TestSession, now)
    assert connection_id == connection.id
    with TestSession() as session:
        result = sync_worker.run_connection(session, connection_id, now)
    db.expire_all()
    return result


def sources(db, user) -> dict[str, FinancialSource]:
    return {s.provider_account_id: s for s in db.query(FinancialSource).filter_by(user_id=user.id, provider="simplefin")}


def txns(db, source) -> dict[str, FinancialTransaction]:
    return {t.provider_transaction_id.split(":", 1)[1]: t for t in db.query(FinancialTransaction).filter_by(source_id=source.id)}


def test_due_selection_and_lease(db_session, test_user, bridge, now):
    due = connect(db_session, test_user, now)
    connect(db_session, test_user, now, next_check_at=now + timedelta(hours=1))
    connect(db_session, test_user, now, disconnected=True)
    connect(db_session, test_user, now, credentials_encrypted=None)
    connect(db_session, test_user, now, next_check_at=None)
    unsynced = FinancialConnection(user_id=test_user.id, provider="other", environment="sandbox",
                                   provider_connection_id=str(uuid.uuid4()), next_check_at=now - timedelta(hours=1))
    db_session.add(unsynced)
    db_session.commit()
    assert sync_worker.claim_due(TestSession, now) == due.id
    db_session.expire_all()
    assert due.status == lifecycle.SYNCING and aware(due.next_check_at) == now + lifecycle.LEASE
    assert sync_worker.claim_due(TestSession, now) is None
    # A stopped worker's lease expires and the connection is claimed again.
    assert sync_worker.claim_due(TestSession, now + lifecycle.LEASE + timedelta(seconds=1)) == due.id


def test_nothing_claimed_when_no_pull_provider_is_offered(db_session, test_user, bridge, now, monkeypatch):
    connect(db_session, test_user, now)
    monkeypatch.setenv("SIMPLEFIN_ENABLED", "false")
    assert sync_worker.claim_due(TestSession, now) is None
    assert not sync_worker.sync_one_due(TestSession, now)
    assert not sync_worker.worker_wanted()


def test_first_sync_walks_back_and_stops_after_two_empty_windows(db_session, test_user, bridge, now):
    bridge.add("ACT-card", "t1", 5, "-45.10")
    bridge.add("ACT-card", "t2", 70, "-12.00")
    bridge.add("ACT-check", "t3", 3, "2000.00")
    connection = connect(db_session, test_user, now)
    assert run(db_session, connection, now)
    today = now.date()
    assert bridge.reads == [(today - timedelta(days=44), today), (today - timedelta(days=89), today - timedelta(days=45)),
                            (today - timedelta(days=134), today - timedelta(days=90)),
                            (today - timedelta(days=179), today - timedelta(days=135))]
    found = sources(db_session, test_user)
    card, checking = found["ACT-card"], found["ACT-check"]
    assert card.account_type == "UNCONFIRMED" and card.revision == 1 and card.name == "Synthetic card"
    assert card.balance == Decimal("-250.00") and card.institution_name == "Synthetic Bank"
    assert card.connection_ids == [connection.provider_connection_id]
    rows = txns(db_session, card)
    assert rows["t1"].amount == Decimal("45.10") and rows["t1"].merchant_name == "Synthetic Payee"
    assert txns(db_session, checking)["t3"].amount == Decimal("-2000.00")
    assert card.transactions_coverage_start == today - timedelta(days=70)
    assert checking.transactions_coverage_start == today - timedelta(days=3)
    assert aware(card.transactions_synced_at) == now
    assert connection.status == "ACTIVE" and connection.error is None
    assert aware(connection.last_checked_at) == now
    assert aware(connection.next_check_at) == now + timedelta(hours=12)
    assert connection.institution_name == "Synthetic Bank"


def test_first_sync_reads_at_most_a_year(db_session, test_user, bridge, now):
    for days in (10, 100, 160, 230, 290, 362):
        bridge.add("ACT-card", f"t{days}", days, "-1.00")
    bridge.add("ACT-card", "too-old", 400, "-1.00")
    connection = connect(db_session, test_user, now)
    assert run(db_session, connection, now)
    today = now.date()
    assert len(bridge.reads) == 9 and bridge.reads[-1] == (today - timedelta(days=364), today - timedelta(days=360))
    assert "too-old" not in txns(db_session, sources(db_session, test_user)["ACT-card"])


def test_account_without_transactions_is_covered_from_today(db_session, test_user, bridge, now):
    connection = connect(db_session, test_user, now)
    assert run(db_session, connection, now)
    assert len(bridge.reads) == 2
    assert sources(db_session, test_user)["ACT-check"].transactions_coverage_start == now.date()


def test_later_sync_reads_thirty_days_and_reconciles(db_session, test_user, bridge, now):
    bridge.add("ACT-card", "keep", 2, "-5.00")
    bridge.add("ACT-card", "gone", 12, "-7.00")
    bridge.add("ACT-card", "edge", 28, "-9.00")
    bridge.add("ACT-card", "old", 80, "-3.00")
    connection = connect(db_session, test_user, now)
    assert run(db_session, connection, now)
    card = sources(db_session, test_user)["ACT-card"]
    card.transactions_coverage_start = now.date() - timedelta(days=200)
    db_session.commit()
    later = now + timedelta(hours=13)
    bridge.rows = [row for row in bridge.rows if row[1] not in {"gone", "edge"}]
    bridge.reads.clear()
    assert run(db_session, connection, later)
    today = later.date()
    assert bridge.reads == [(today - timedelta(days=29), today)]
    rows = txns(db_session, card)
    # Removed inside the window; kept near its start edge and outside it.
    assert "gone" not in rows and {"keep", "edge", "old"} <= set(rows)
    assert card.transactions_coverage_start == now.date() - timedelta(days=200)


def test_bridge_errors_skip_reconciliation_and_surface_the_notice(db_session, test_user, bridge, now):
    bridge.add("ACT-card", "gone", 10, "-7.00")
    connection = connect(db_session, test_user, now)
    assert run(db_session, connection, now)
    bridge.rows.clear()
    bridge.errors = ["Synthetic Bank needs attention at your bridge."]
    assert run(db_session, connection, now + timedelta(hours=13))
    assert "gone" in txns(db_session, sources(db_session, test_user)["ACT-card"])
    assert connection.status == "ACTIVE" and connection.error == "Synthetic Bank needs attention at your bridge."


def test_sync_after_an_outage_reads_back_to_the_last_success(db_session, test_user, bridge, now):
    connection = connect(db_session, test_user, now, last_checked_at=now - timedelta(days=100))
    assert run(db_session, connection, now)
    today = now.date()
    assert bridge.reads[0][0] == today - timedelta(days=105) and bridge.reads[-1][1] == today
    assert len(bridge.reads) == 3


def test_confirmed_types_keep_the_amount_owed_and_user_edits(db_session, test_user, bridge, now):
    connection = connect(db_session, test_user, now)
    assert run(db_session, connection, now)
    card = sources(db_session, test_user)["ACT-card"]
    card.account_type, card.subtype, card.name = "CREDIT", "CREDIT_CARD", "My card"
    db_session.commit()
    bridge.balances["ACT-card"] = "-300.00"
    bridge.balance_day = now.date()
    assert run(db_session, connection, now + timedelta(hours=13))
    assert card.balance == Decimal("300.00") and card.name == "My card" and card.account_type == "CREDIT"
    assert card.revision == 2
    # A late read never regresses a newer balance.
    bridge.balances["ACT-card"] = "-999.00"
    bridge.balance_day = now.date() - timedelta(days=3)
    assert run(db_session, connection, now + timedelta(hours=26))
    assert card.balance == Decimal("300.00") and card.revision == 2


def test_rate_limit_payment_reconnect_and_backoff_schedules(db_session, test_user, bridge, now):
    connection = connect(db_session, test_user, now)
    bridge.status = 429
    assert not run(db_session, connection, now)
    assert connection.status == "RETRYING" and aware(connection.next_check_at) == now + timedelta(hours=6)
    bridge.status = 503
    later = now + timedelta(hours=6)
    assert not run(db_session, connection, later)
    # Backoff grows with the time since creation (no success yet), capped at 12 hours.
    assert aware(connection.next_check_at) == later + timedelta(hours=6, seconds=1)
    connection.last_checked_at = later - timedelta(minutes=1)
    connection.next_check_at = later
    db_session.commit()
    assert not run(db_session, connection, later)
    assert aware(connection.next_check_at) == later + timedelta(minutes=15)
    connection.last_checked_at = later - timedelta(days=3)
    connection.next_check_at = later
    db_session.commit()
    assert not run(db_session, connection, later)
    assert aware(connection.next_check_at) == later + timedelta(hours=12)
    bridge.status = 402
    connection.next_check_at = later
    db_session.commit()
    assert not run(db_session, connection, later)
    assert connection.status == "PAYMENT_REQUIRED" and aware(connection.next_check_at) == later + timedelta(hours=24)
    bridge.status = 403
    connection.next_check_at = later
    db_session.commit()
    assert not run(db_session, connection, later)
    assert connection.status == "RECONNECT_REQUIRED" and connection.next_check_at is None
    assert "Reconnect" in connection.error
    assert sync_worker.claim_due(TestSession, later + timedelta(days=30)) is None


def test_unreadable_credentials_and_rejected_hosts_require_reconnection(db_session, test_user, bridge, now, monkeypatch):
    connection = connect(db_session, test_user, now)
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", "another-synthetic-ledger-key-0123456789")
    assert not run(db_session, connection, now)
    assert connection.status == "RECONNECT_REQUIRED" and "Reconnect" in connection.error
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", KEY)
    monkeypatch.setenv("SIMPLEFIN_ALLOWED_HOSTS", "other.example")
    connection.next_check_at = now
    db_session.commit()
    assert not run(db_session, connection, now)
    assert connection.status == "RECONNECT_REQUIRED"


def test_unexpected_failures_reschedule(db_session, test_user, bridge, now, monkeypatch):
    connection = connect(db_session, test_user, now)

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    with monkeypatch.context() as patched:
        patched.setattr(SimpleFINAdapter, "read", broken)
        assert not run(db_session, connection, now)
    assert connection.status == "RETRYING" and connection.error == "Sync failed. It will retry automatically."
    monkeypatch.setattr(SimpleFINAdapter, "store", broken)
    connection.next_check_at = now
    db_session.commit()
    assert not run(db_session, connection, now)
    assert connection.status == "RETRYING" and not sources(db_session, test_user)


def test_a_read_made_stale_by_a_reconnect_is_discarded(db_session, test_user, bridge, now, monkeypatch):
    connection = connect(db_session, test_user, now)
    original = SimpleFINAdapter.read

    def reconnected_meanwhile(self, conn, secret, today):
        result = original(self, conn, secret, today)
        object_session(conn).execute(update(FinancialConnection).where(FinancialConnection.id == conn.id).values(
            credentials_encrypted=secrets.encrypt(ACCESS_URL)))
        return result

    monkeypatch.setattr(SimpleFINAdapter, "read", reconnected_meanwhile)
    assert not run(db_session, connection, now)
    assert not sources(db_session, test_user)


def test_rotated_keys_reencrypt_after_success(db_session, test_user, bridge, now, monkeypatch):
    old = "synthetic-old-ledger-key-0123456789-xyz"
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", old)
    connection = connect(db_session, test_user, now)
    before = connection.credentials_encrypted
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", KEY)
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEYS_PREVIOUS", old)
    assert run(db_session, connection, now)
    assert connection.credentials_encrypted != before
    monkeypatch.delenv("LEDGER_ENCRYPTION_KEYS_PREVIOUS")
    assert secrets.decrypt(connection.credentials_encrypted) == ACCESS_URL


def test_run_connection_ignores_missing_disconnected_and_unoffered(db_session, test_user, bridge, now, monkeypatch):
    connection = connect(db_session, test_user, now, disconnected=True)
    with TestSession() as session:
        assert not sync_worker.run_connection(session, uuid.uuid4(), now)
        assert not sync_worker.run_connection(session, connection.id, now)
        monkeypatch.setenv("SIMPLEFIN_ENABLED", "false")
        assert not sync_worker.run_connection(session, connection.id, now)
        # A failure recorded for a connection disconnected meanwhile changes nothing.
        assert not sync_worker.finish_failure(session, connection.id, RuntimeError(), now)


def test_sync_refreshes_feeds_and_one_due_runs(db_session, test_user, bridge, now, monkeypatch):
    seen = []
    monkeypatch.setattr(sync_worker, "refresh_feeds", lambda db, user_id, ids: seen.append(set(ids)) or 0)
    connect(db_session, test_user, now)
    assert sync_worker.sync_one_due(TestSession, now)
    assert seen and len(seen[0]) == 2


def test_worker_loop_runs_until_no_provider_is_offered(env, monkeypatch):
    calls = []

    def one(factory):
        calls.append(factory)
        if len(calls) == 2:
            raise RuntimeError("synthetic")
        return len(calls) == 1

    async def no_sleep(seconds):
        if len(calls) >= 3:
            monkeypatch.setenv("SIMPLEFIN_ENABLED", "false")

    monkeypatch.setattr(sync_worker, "sync_one_due", one)
    monkeypatch.setattr(sync_worker.asyncio, "sleep", no_sleep)
    asyncio.run(sync_worker.run_sync_worker(TestSession))
    assert len(calls) == 3


def test_adapter_revoke_is_a_no_op():
    assert SimpleFINAdapter().revoke(ACCESS_URL) is None
    assert simplefin_adapter.update_start(FinancialConnection(last_checked_at=None), utcnow().date())


class LinkingRefused(AccessPolicy):
    """A plug-in policy that lets nobody, or only ``allowed``, link providers."""

    def __init__(self, allowed=frozenset()):
        self.allowed = allowed

    def allows(self, user, action):
        return action != BANK_LINKING or user.id in self.allowed


def test_a_connection_the_account_may_not_link_waits_without_failing(db_session, test_user, bridge, now, monkeypatch):
    paused = connect(db_session, test_user, now, status="ACTIVE", error="Bridge notice")
    linked = other_user(db_session)
    allowed = connect(db_session, linked, now)
    allowed.next_check_at = now  # after the paused one, which is more overdue
    db_session.commit()
    monkeypatch.setattr(extensions, "access_policy", LinkingRefused({linked.id}))
    # The paused connection is passed over in the same claim; others still sync.
    assert sync_worker.claim_due(TestSession, now) == allowed.id
    db_session.expire_all()
    assert paused.status == "ACTIVE" and paused.error == "Bridge notice"
    assert aware(paused.next_check_at) == now + lifecycle.LINKING_PAUSED_RECHECK
    assert bridge.reads == [] and paused.credentials_encrypted
    allowed.disconnected = True  # out of the queue from here on
    db_session.commit()
    # Due again while still refused: nothing claimed, nothing failed.
    later = now + lifecycle.LINKING_PAUSED_RECHECK
    monkeypatch.setattr(extensions, "access_policy", LinkingRefused())
    assert sync_worker.claim_due(TestSession, later) is None
    db_session.expire_all()
    assert paused.status == "ACTIVE" and aware(paused.next_check_at) == later + lifecycle.LINKING_PAUSED_RECHECK
    # Access returns: the next check syncs it as usual.
    monkeypatch.setattr(extensions, "access_policy", None)
    resumed = later + lifecycle.LINKING_PAUSED_RECHECK
    assert sync_worker.claim_due(TestSession, resumed) == paused.id
    with TestSession() as session:
        assert sync_worker.run_connection(session, paused.id, resumed)
    db_session.expire_all()
    assert paused.status == "ACTIVE" and aware(paused.last_checked_at) == resumed

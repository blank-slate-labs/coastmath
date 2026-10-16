"""Suggestion job, background loop and /api/ledger/suggestions routes."""
import asyncio
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from app import main
from app.ledger import suggestions
from app.ledger.llm import LlmError
from app.ledger.suggestions import (
    Outcome,
    pending_rows,
    process_pending,
    run_for_user,
    users_with_candidates,
)
from app.models.financial_connection import FinancialTransaction, utcnow
from app.models.ledger import FinancialRule
from app.routers.ledger_suggestions import run_read
from tests.conftest import TestSession
from tests.ledger_fixture import make_source, make_txn, other_user, plan_with_feed

pytestmark = pytest.mark.anyio
DAY = utcnow().date() - timedelta(days=20)


class FakeClient:
    """Answers every item with a fixed category unless told otherwise."""

    def __init__(self, category="dining", fail_on=None, skip=()):
        self.category = category
        self.fail_on = fail_on
        self.skip = set(skip)
        self.batches: list[list[str]] = []

    def suggest(self, items):
        self.batches.append([item.key for item in items])
        if self.fail_on is not None and len(self.batches) == self.fail_on:
            raise LlmError("unavailable")
        return {item.key: self.category for item in items if item.key not in self.skip}


@pytest.fixture(autouse=True)
def clean_state():
    suggestions.reset_state()
    yield
    suggestions.reset_state()


@pytest.fixture
def offered(transactions_on, monkeypatch):
    monkeypatch.setenv("LEDGER_LLM_ENABLED", "true")
    monkeypatch.setenv("LEDGER_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("LEDGER_LLM_MODEL", "synthetic-model")


@pytest.fixture
def rows(db_session, test_user):
    card = make_source(db_session, test_user)
    made = {
        "blank": make_txn(db_session, test_user, card, 12, DAY, None, description="SYNTHETIC CAFE"),
        "other": make_txn(db_session, test_user, card, 30, DAY - timedelta(days=1), "Misc", description="CHECK 101"),
        "mapped": make_txn(db_session, test_user, card, 80, DAY, "Groceries", description="SYNTHETIC GROCER"),
        "override": make_txn(db_session, test_user, card, 9, DAY, None, description="SYNTHETIC KIOSK",
                             category_override="shopping"),
        "ruled": make_txn(db_session, test_user, card, 40, DAY, None, description="SYNTHETIC GYM"),
        "suggested": make_txn(db_session, test_user, card, 7, DAY, None, description="SYNTHETIC BAKERY",
                              llm_category="food_and_drink"),
        "pending": make_txn(db_session, test_user, card, 5, DAY, None, status="PENDING"),
        "excluded": make_txn(db_session, test_user, card, 6, DAY, None, excluded=True),
        "old": make_txn(db_session, test_user, card, 4, DAY - timedelta(days=900), None),
    }
    db_session.add(FinancialRule(user_id=test_user.id, match_field="description", match_type="contains",
                                 pattern="synthetic gym", direction="any", category="health"))
    db_session.commit()
    return card, made


def test_selection_skips_overrides_rules_suggestions_mapped_pending_excluded_and_old(db_session, test_user, rows):
    _, made = rows
    assert [row.id for row in pending_rows(db_session, test_user.id)] == [made["blank"].id, made["other"].id]
    assert users_with_candidates(db_session) == [test_user.id]


def test_run_stores_suggestions_without_touching_precedence(db_session, test_user, rows):
    _, made = rows
    client = FakeClient("dining")
    outcome = run_for_user(db_session, test_user.id, client)
    assert (outcome.status, outcome.suggested, outcome.sent) == ("suggested", 2, 2)
    db_session.expire_all()
    assert made["blank"].llm_category == "dining" and made["other"].llm_category == "dining"
    assert made["override"].llm_category is None and made["ruled"].llm_category is None
    assert made["override"].category_override == "shopping" and made["suggested"].llm_category == "food_and_drink"
    assert suggestions.last_outcome(test_user.id) == outcome
    assert run_for_user(db_session, test_user.id, client).status == "nothing_pending"


def test_runs_are_capped_and_batched(db_session, test_user, monkeypatch):
    card = make_source(db_session, test_user)
    for index in range(7):
        make_txn(db_session, test_user, card, 10 + index, DAY - timedelta(days=index), None)
    db_session.commit()
    monkeypatch.setattr(suggestions, "BATCH_SIZE", 2)
    client = FakeClient()
    assert run_for_user(db_session, test_user.id, client, limit=5).suggested == 5
    assert [len(batch) for batch in client.batches] == [2, 2, 1]
    assert len(pending_rows(db_session, test_user.id)) == 2


def test_provider_error_leaves_failed_batch_untouched(db_session, test_user, rows, monkeypatch):
    _, made = rows
    monkeypatch.setattr(suggestions, "BATCH_SIZE", 1)
    outcome = run_for_user(db_session, test_user.id, FakeClient(fail_on=2))
    assert (outcome.status, outcome.suggested, outcome.sent) == ("failed", 1, 1)
    assert outcome.message == "The suggestion service is unavailable."
    db_session.expire_all()
    assert made["blank"].llm_category == "dining" and made["other"].llm_category is None
    assert [row.id for row in pending_rows(db_session, test_user.id)] == [made["other"].id]


def test_unanswered_rows_are_not_resent_in_this_process(db_session, test_user, rows, monkeypatch):
    _, made = rows
    client = FakeClient(skip={str(made["other"].id)})
    assert run_for_user(db_session, test_user.id, client).suggested == 1
    assert pending_rows(db_session, test_user.id) == []
    monkeypatch.setattr(suggestions, "UNANSWERED_LIMIT", 1)
    suggestions.remember_unanswered(str(test_user.id), {"another"})
    assert [row.id for row in pending_rows(db_session, test_user.id)] == [made["other"].id]


def test_rows_claimed_during_a_run_keep_the_customer_choice(db_session, test_user, rows):
    _, made = rows

    class Racing(FakeClient):
        def suggest(self, items):
            with TestSession() as other:
                other.get(FinancialTransaction, made["blank"].id).category_override = "travel"
                other.commit()
            return super().suggest(items)

    assert run_for_user(db_session, test_user.id, Racing()).suggested == 1
    db_session.expire_all()
    assert made["blank"].llm_category is None and made["blank"].category_override == "travel"


def test_suggestions_reapply_feeds_reading_the_accounts(db_session, test_user, rows, monkeypatch):
    card, _ = rows
    plan_with_feed(db_session, test_user, [card.id])
    calls = []
    real = suggestions.refresh_feeds
    monkeypatch.setattr(suggestions, "refresh_feeds",
                        lambda db, user_id, ids: calls.append((user_id, set(ids))) or real(db, user_id, ids))
    run_for_user(db_session, test_user.id, FakeClient())
    assert calls == [(test_user.id, {str(card.id)})]
    assert suggestions.store_suggestions(db_session, test_user.id, {}) == 0
    assert suggestions.store_suggestions(db_session, test_user.id, {str(card.id): "dining"}) == 0
    assert pending_rows(db_session, other_user(db_session).id) == []


def test_not_offered_and_concurrent_runs(db_session, test_user, rows, offered, monkeypatch):
    monkeypatch.setenv("LEDGER_LLM_ENABLED", "false")
    assert run_for_user(db_session, test_user.id).status == "not_offered"
    monkeypatch.setenv("LEDGER_LLM_ENABLED", "true")
    sent = []
    monkeypatch.setattr(suggestions.LedgerLlmClient, "suggest", lambda self, items: sent.append(items) or {})
    assert run_for_user(db_session, test_user.id).status == "suggested" and len(sent) == 1
    suggestions._running.add(str(test_user.id))
    assert suggestions.is_running(test_user.id)
    assert run_for_user(db_session, test_user.id, FakeClient()) == Outcome("running")


def test_background_pass_backs_off_after_failures(db_session, test_user, rows):
    stranger = other_user(db_session)
    make_txn(db_session, stranger, make_source(db_session, stranger, external="acct-9"), 3, DAY, None)
    db_session.commit()
    first = users_with_candidates(db_session)[0]
    failing = FakeClient(fail_on=1)
    # The first user's only batch fails; the other user's rows are still served.
    assert process_pending(TestSession, failing) == (2 if first == stranger.id else 1)
    assert len(failing.batches) == 2
    again = FakeClient()
    assert process_pending(TestSession, again) == 0
    assert again.batches == []


async def test_worker_starts_only_when_offered(offered, monkeypatch):
    assert suggestions.start_suggestion_worker(None) is None
    passes = []

    def one_pass(factory, client):
        passes.append(client.settings.model)
        monkeypatch.setenv("LEDGER_LLM_ENABLED", "false")
        raise RuntimeError("controlled failure")

    monkeypatch.setattr(suggestions, "process_pending", one_pass)
    task = suggestions.start_suggestion_worker(TestSession)
    assert isinstance(task, asyncio.Task)
    task.cancel()
    await suggestions.run_suggestion_worker(TestSession, interval=0)
    assert passes == ["synthetic-model"]
    monkeypatch.setenv("LEDGER_LLM_ENABLED", "false")
    assert suggestions.start_suggestion_worker(TestSession) is None


async def test_lifespan_cancels_the_suggestion_worker(monkeypatch):
    monkeypatch.setattr(main, "engine", MagicMock())
    monkeypatch.setattr(main, "SESSION_SECRET", "controlled-test-secret-at-least-32-bytes")
    started = []

    async def forever():
        started.append(True)
        await asyncio.sleep(3600)

    monkeypatch.setattr(main, "start_suggestion_worker", lambda factory: asyncio.create_task(forever()))
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
    assert started == [True]


# --- routes -------------------------------------------------------------------

async def test_status_when_not_offered(client, transactions_on, rows):
    body = (await client.get("/api/ledger/suggestions/status")).json()
    assert body == {"offered": False, "running": False, "pending": None, "last_run": None}
    refused = await client.post("/api/ledger/suggestions/run")
    assert refused.status_code == 503 and refused.json()["error"]["code"] == "FEATURE_DISABLED"
    assert "not configured" in refused.json()["error"]["message"]


async def test_run_route_is_gated_by_the_release_flag(client, rows, monkeypatch):
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "false")
    refused = await client.post("/api/ledger/suggestions/run")
    assert refused.status_code == 503 and refused.json()["error"]["message"].startswith("Transactions")
    assert (await client.get("/api/ledger/suggestions/status")).status_code == 200


async def test_run_and_status_when_offered(client, offered, rows, test_user, monkeypatch):
    monkeypatch.setattr(suggestions.LedgerLlmClient, "suggest",
                        lambda self, items: {item.key: "dining" for item in items})
    before = (await client.get("/api/ledger/suggestions/status")).json()
    assert before["offered"] is True and before["pending"] == 2
    ran = await client.post("/api/ledger/suggestions/run")
    assert ran.status_code == 200
    body = ran.json()
    assert body["pending"] == 0 and body["last_run"]["status"] == "suggested" and body["last_run"]["suggested"] == 2
    listed = (await client.get("/api/ledger/transactions")).json()["transactions"]
    assert {t["category_source"] for t in listed if t["category"] == "dining"} == {"llm"}
    suggestions._running.add(str(test_user.id))
    busy = await client.post("/api/ledger/suggestions/run")
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "CONFLICT"
    assert (await client.get("/api/ledger/suggestions/status")).json()["running"] is True


async def test_run_route_reports_provider_failures(client, offered, rows, monkeypatch):
    def fail(self, items):
        raise LlmError("auth")

    monkeypatch.setattr(suggestions.LedgerLlmClient, "suggest", fail)
    body = (await client.post("/api/ledger/suggestions/run")).json()
    assert body["last_run"]["status"] == "failed" and body["pending"] == 2
    assert body["last_run"]["message"] == "The suggestion service refused the configured credentials."


async def test_run_route_is_rate_limited(client, offered, rows, monkeypatch):
    monkeypatch.setattr(suggestions.LedgerLlmClient, "suggest", lambda self, items: {})
    codes = [(await client.post("/api/ledger/suggestions/run")).status_code for _ in range(7)]
    assert codes[:6] == [200] * 6 and codes[6] == 429


def test_run_read_hides_internal_states():
    assert run_read(None) is None and run_read(Outcome("running")) is None
    assert run_read(Outcome("nothing_pending")).status == "nothing_pending"

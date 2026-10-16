"""Month variants for spending-model compare/apply, the feed's months basis and /api/ledger/spending-feeds.

Synthetic file accounts only: no real institutions, accounts or people.
"""
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.ledger.feeds import MONTHS_UNAVAILABLE, apply_feed, feed_for_plan
from app.ledger.month_models import average_by_category, months_label
from app.ledger.months import MonthSummary, month_key
from app.models.expense import Expense
from app.models.financial_connection import FinancialSpendingFeed, utcnow
from app.models.plan import Plan
from app.routers import ledger_feeds
from tests.ledger_fixture import make_import, make_source, make_txn, other_user
from tests.scenario_support import post

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("transactions_on")]
TODAY = utcnow().date()
THIS_MONTH = TODAY.replace(day=1)
M2_END = THIS_MONTH - timedelta(days=1)
M2 = M2_END.replace(day=1)
M1_END = M2 - timedelta(days=1)
M1 = M1_END.replace(day=1)
K1, K2, NOW_KEY = month_key(M1), month_key(M2), month_key(THIS_MONTH)


@pytest.fixture
def ledger(db_session, test_user):
    """A card and a checking account, both imported through today: last two months complete."""
    card = make_source(db_session, test_user, external="card-1")
    checking = make_source(db_session, test_user, external="chk-1", account_type="DEPOSITORY", subtype="CHECKING",
                           name="Synthetic checking")
    for source in (card, checking):
        make_import(db_session, test_user, source, M1, TODAY)
    for start, groceries, dining, pay in ((M1, 600, 200, 3000), (M2, 900, 100, 3200)):
        day = start + timedelta(days=9)
        make_txn(db_session, test_user, card, groceries, day, category_override="groceries")
        make_txn(db_session, test_user, card, dining, day, category_override="dining")
        make_txn(db_session, test_user, checking, -pay, day, category_override="income_wages")
    db_session.commit()
    return card, checking


async def _plan(client, *, expenses=True, **fields) -> str:
    pid = (await post(client, "/plans", {"name": "Plan", "birth_year": 1982, **fields}, 201))["id"]
    await post(client, f"/plans/{pid}/incomes", {"name": "Salary", "annual_amount": 110000, "withholding_percent": 20}, 201)
    await post(client, f"/plans/{pid}/accounts", {"name": "Cash", "account_type": "checking", "balance": 25000}, 201)
    if expenses:
        await post(client, f"/plans/{pid}/expenses", {"name": "Living", "annual_amount": 36000, "category": "essential"}, 201)
        await post(client, f"/plans/{pid}/expenses", {"name": "Fun", "annual_amount": 12000, "discretionary_percent": 75}, 201)
    return pid


def _months(*keys, **extra):
    return {"kind": "months", "months": list(keys), **extra}


async def _compare(client, pid, variants, status=200, **options):
    return await post(client, f"/plans/{pid}/spending-models/compare", {"variants": variants, **options}, status)


async def _apply(client, pid, variant, fingerprint, status=200):
    return await post(client, f"/plans/{pid}/spending-models/apply",
                      {"variant": variant, "expected_fingerprint": fingerprint}, status)


async def _feed(client, pid, source_ids, status=200, **body):
    response = await client.put(f"/api/ledger/spending-feeds/{pid}",
                                json={"source_ids": [str(value) for value in source_ids], **body})
    assert response.status_code == status, response.text
    return response.json()


# ── labels and category averages ─────────────────────────────────

def test_months_label_names_one_month_a_span_and_skipped_months():
    assert months_label(["2026-06"]) == "June 2026"
    assert months_label(["2026-08", "2026-06", "2026-07"]) == "Jun – Aug 2026"
    assert months_label(["2025-12", "2026-01"]) == "Dec 2025 – Jan 2026"
    assert months_label(["2026-06", "2026-08"]) == "Jun – Aug 2026 (2 months)"


def test_average_by_category_means_the_chosen_months():
    months = [MonthSummary("2026-06", True, [], by_category={"dining": Decimal("100"), "groceries": Decimal("50")}),
              MonthSummary("2026-07", True, [], by_category={"dining": Decimal("-20")}),
              MonthSummary("2026-08", True, [], by_category={"travel": Decimal("999")})]
    assert average_by_category(months, ["2026-06", "2026-07"]) == {"dining": Decimal("40.00"),
                                                                   "groceries": Decimal("25.00")}
    assert average_by_category(months, []) == {}


# ── compare ──────────────────────────────────────────────────────

async def test_single_and_combined_month_variants(client, ledger):
    card, checking = ledger
    pid = await _plan(client)
    body = await _compare(client, pid, [_months(K1), _months(K2, label="Latest"), _months(K1, K2)])
    june, latest, both = body["variants"]
    assert june["kind"] == "months" and june["label"] == months_label([K1])
    assert june["essential_annual"] == 12 * 600 and june["discretionary_annual"] == 12 * 200
    assert june["take_home_monthly"] == 3000
    assert june["months"] == [K1] and set(june["source_ids"]) == {str(card.id), str(checking.id)}
    assert june["by_category"] == {"dining": 200, "groceries": 600}
    assert latest["label"] == "Latest" and latest["essential_annual"] == 12 * 900
    assert both["label"] == months_label([K1, K2]) and both["essential_annual"] == 12 * 750
    assert both["discretionary_annual"] == 12 * 150 and both["take_home_monthly"] == 3100
    assert both["by_category"] == {"dining": 150, "groceries": 750}
    # Less spending than the plan's: every month variant ends wealthier.
    assert all(v["final_net_worth"] > body["plan"]["final_net_worth"] for v in body["variants"])
    assert body["plan"]["months"] is None and body["plan"]["by_category"] is None


async def test_amounts_and_months_variants_mix(client, ledger):
    pid = await _plan(client)
    body = await _compare(client, pid, [{"kind": "amounts", "essential_annual": 7200, "discretionary_annual": 2400},
                                        _months(K1)])
    amounts, month = body["variants"]
    assert amounts["kind"] == "amounts" and amounts["months"] is None
    assert amounts["final_net_worth"] == pytest.approx(month["final_net_worth"])


async def test_take_home_scales_income_when_asked(client, ledger):
    pid = await _plan(client)
    body = await _compare(client, pid, [_months(K2)], income="scale_to_take_home")
    variant = body["variants"][0]
    assert variant["income_ratio"] is not None
    assert variant["projected_take_home_monthly"] == pytest.approx(3200, abs=1)


async def test_explicit_sources_and_unknown_sources(client, db_session, test_user, ledger):
    card, _ = ledger
    pid = await _plan(client)
    variant = (await _compare(client, pid, [_months(K1, source_ids=[str(card.id)])]))["variants"][0]
    assert variant["source_ids"] == [str(card.id)] and variant["take_home_monthly"] is None
    foreign = make_source(db_session, other_user(db_session), external="card-x")
    db_session.commit()
    for source_id in (str(foreign.id), str(uuid.uuid4())):
        response = await client.post(f"/api/plans/{pid}/spending-models/compare",
                                     json={"variants": [_months(K1, source_ids=[source_id])]})
        assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"


async def test_feed_accounts_are_the_default(client, ledger):
    card, _ = ledger
    pid = await _plan(client, expenses=False)
    await _feed(client, pid, [card.id])
    variant = (await _compare(client, pid, [_months(K1)]))["variants"][0]
    assert variant["source_ids"] == [str(card.id)] and variant["take_home_monthly"] is None


async def test_incomplete_and_unknown_months_are_refused_with_reasons(client, ledger):
    pid = await _plan(client)
    response = await client.post(f"/api/plans/{pid}/spending-models/compare", json={"variants": [_months(K1, NOW_KEY)]})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "MONTH_INCOMPLETE"
    assert error["details"] == [{"month": NOW_KEY, "reasons": [{"code": "in_progress", "source_ids": []}]}]
    response = await client.post(f"/api/plans/{pid}/spending-models/compare", json={"variants": [_months("2001-01")]})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MONTH_UNKNOWN"
    assert response.json()["error"]["details"] == [{"month": "2001-01", "reasons": [{"code": "no_coverage", "source_ids": []}]}]


async def test_partial_coverage_names_the_account(client, db_session, test_user, ledger):
    pid = await _plan(client)
    late = make_source(db_session, test_user, external="card-late")
    make_import(db_session, test_user, late, M2, M2_END)
    db_session.commit()
    response = await client.post(f"/api/plans/{pid}/spending-models/compare", json={"variants": [_months(K1)]})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["reasons"] == [{"code": "partial_coverage", "source_ids": [str(late.id)]}]


async def test_months_use_the_plan_currency(client, ledger):
    pid = await _plan(client, currency="EUR")
    variant = (await _compare(client, pid, [_months(K1)]))["variants"][0]
    assert variant["essential_annual"] == 0 and variant["by_category"] == {} and variant["take_home_monthly"] is None


# ── apply without a feed ─────────────────────────────────────────

async def test_apply_months_scales_the_expenses_like_the_preview(client, ledger):
    pid = await _plan(client)
    preview = await _compare(client, pid, [_months(K1, K2)])
    applied = await _apply(client, pid, _months(K1, K2), preview["fingerprint"])
    assert applied["basis"] is None and len(applied["updated_expense_ids"]) == 2
    after = await _compare(client, pid, [_months(K1, K2)])
    assert after["plan"]["final_net_worth"] == pytest.approx(preview["variants"][0]["final_net_worth"], abs=0.01)
    assert after["plan"]["essential_annual"] == pytest.approx(12 * 750, abs=2)
    stale = await client.post(f"/api/plans/{pid}/spending-models/apply",
                              json={"variant": _months(K1), "expected_fingerprint": preview["fingerprint"]})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "CONFLICT"


async def test_apply_refuses_incomplete_months(client, ledger):
    pid = await _plan(client)
    preview = await _compare(client, pid, [_months(K1)])
    response = await client.post(f"/api/plans/{pid}/spending-models/apply",
                                 json={"variant": _months(NOW_KEY), "expected_fingerprint": preview["fingerprint"]})
    assert response.status_code == 422 and response.json()["error"]["code"] == "MONTH_INCOMPLETE"


# ── apply with a feed ────────────────────────────────────────────

async def test_apply_months_sets_the_feed_basis_and_matches_the_preview(client, db_session, ledger):
    card, checking = ledger
    pid = await _plan(client, expenses=False)
    trailing = await _feed(client, pid, [card.id, checking.id])
    assert trailing["basis"] == "trailing" and trailing["months_used"] == 2
    # File accounts count their import periods: both months, not "still loading".
    assert trailing["annual_essential"] == 12 * 750 and trailing["annual_discretionary"] == 12 * 150
    preview = await _compare(client, pid, [_months(K2)])
    assert preview["spending_feed"] is True
    refused = await client.post(f"/api/plans/{pid}/spending-models/apply", json={
        "variant": {"kind": "amounts", "essential_annual": 1, "discretionary_annual": 1},
        "expected_fingerprint": preview["fingerprint"]})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "SPENDING_FEED_ACTIVE"
    applied = await _apply(client, pid, _months(K2), preview["fingerprint"])
    assert applied["basis"] == "months" and len(applied["updated_expense_ids"]) == 2
    assert applied["created_expense_ids"] == []
    db_session.expire_all()
    feed = feed_for_plan(db_session, uuid.UUID(pid))
    assert feed.basis == "months" and feed.basis_months == [K2] and feed.months_used == 1
    assert float(feed.last_essential) == 12 * 900 and float(feed.last_discretionary) == 12 * 100
    after = await _compare(client, pid, [_months(K2)])
    assert after["plan"]["final_net_worth"] == pytest.approx(preview["variants"][0]["final_net_worth"], abs=0.01)
    # Back to recent months.
    reset = await _feed(client, pid, [card.id, checking.id], basis="trailing")
    assert reset["basis"] == "trailing" and reset["basis_months"] == [] and reset["annual_essential"] == 12 * 750


async def test_apply_to_a_feed_with_explicit_accounts(client, db_session, test_user, ledger):
    card, checking = ledger
    pid = await _plan(client, expenses=False)
    await _feed(client, pid, [card.id, checking.id])
    preview = await _compare(client, pid, [_months(K1, source_ids=[str(card.id)])])
    applied = await _apply(client, pid, _months(K1, source_ids=[str(card.id)]), preview["fingerprint"])
    assert applied["basis"] == "months"
    db_session.expire_all()
    assert feed_for_plan(db_session, uuid.UUID(pid)).source_ids == [str(card.id)]
    savings = make_source(db_session, test_user, external="sav-1", account_type="DEPOSITORY", subtype="SAVINGS")
    make_import(db_session, test_user, savings, M1, M2_END)
    db_session.commit()
    preview = await _compare(client, pid, [_months(K1, source_ids=[str(savings.id)])])
    response = await client.post(f"/api/plans/{pid}/spending-models/apply", json={
        "variant": _months(K1, source_ids=[str(savings.id)]), "expected_fingerprint": preview["fingerprint"]})
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_apply_to_a_paused_feed_saves_nothing(client, db_session, ledger):
    card, _ = ledger
    pid = await _plan(client, expenses=False)
    feed = await _feed(client, pid, [card.id])
    expense = db_session.get(Expense, uuid.UUID(feed["essential_expense_id"]))
    expense.annual_amount = 1234
    db_session.commit()
    preview = await _compare(client, pid, [_months(K1)])
    response = await client.post(f"/api/plans/{pid}/spending-models/apply",
                                 json={"variant": _months(K1), "expected_fingerprint": preview["fingerprint"]})
    assert response.status_code == 409 and response.json()["error"]["code"] == "SPENDING_FEED_PAUSED"
    db_session.expire_all()
    assert feed_for_plan(db_session, uuid.UUID(pid)).basis == "trailing"
    stale = await client.post(f"/api/plans/{pid}/spending-models/apply",
                              json={"variant": _months(K1), "expected_fingerprint": "0" * 64})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "CONFLICT"


# ── the feed's months basis ──────────────────────────────────────

async def test_a_chosen_month_that_stops_being_complete_keeps_the_last_amounts(client, db_session, test_user, ledger):
    card, _ = ledger
    pid = await _plan(client, expenses=False)
    await _feed(client, pid, [card.id], basis="months", months=[K1])
    db_session.expire_all()
    feed = feed_for_plan(db_session, uuid.UUID(pid))
    assert float(feed.last_essential) == 12 * 600
    feed.basis_months = [K1, NOW_KEY]
    assert apply_feed(db_session, feed) is False
    assert feed.error == MONTHS_UNAVAILABLE and float(feed.last_essential) == 12 * 600


def test_a_months_feed_without_months_reports_the_error(db_session, test_user):
    card = make_source(db_session, test_user, external="card-z")
    plan = Plan(user_id=test_user.id, name="Feed plan", birth_year=1985, life_expectancy=90, plan_type="NOW",
                currency="USD")
    db_session.add(plan)
    db_session.flush()
    feed = FinancialSpendingFeed(id=uuid.uuid4(), user_id=test_user.id, plan_id=plan.id, source_ids=[str(card.id)],
                                 basis="months", basis_months=None)
    db_session.add(feed)
    db_session.flush()
    assert apply_feed(db_session, feed, today=date.today()) is False and feed.error == MONTHS_UNAVAILABLE


# ── the user's calendar date ─────────────────────────────────────

def _server_clock(monkeypatch, day: date) -> None:
    """Pin the server's calendar to ``day``: the header's tolerance and the ledger's UTC fallbacks."""

    class ServerDate(date):
        @classmethod
        def today(cls):
            return cls(day.year, day.month, day.day)

    noon = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
    monkeypatch.setattr("app.routers.helpers.datetime", SimpleNamespace(date=ServerDate))
    for module in ("app.routers.ledger", "app.ledger.months", "app.ledger.feeds"):
        monkeypatch.setattr(f"{module}.utcnow", lambda: noon)


def _completeness(day: date) -> dict[str, bool]:
    """The fixture's months as seen on the last day of the previous month or the first of this one."""
    return {K1: True, K2: False} if day == M2_END else {K1: True, K2: True, NOW_KEY: False}


@pytest.mark.parametrize("server_day, user_day", [(THIS_MONTH, M2_END), (M2_END, THIS_MONTH)])
async def test_ledger_months_follow_the_client_date(client, monkeypatch, ledger, server_day, user_day):
    _server_clock(monkeypatch, server_day)

    async def completeness(headers):
        response = await client.get("/api/ledger/months", headers=headers)
        assert response.status_code == 200, response.text
        return {month["month"]: month["complete"] for month in response.json()["months"]}

    assert await completeness({"X-Client-Date": user_day.isoformat()}) == _completeness(user_day)
    assert await completeness({}) == _completeness(server_day)


async def test_a_month_still_running_for_the_user_is_refused(client, monkeypatch, ledger):
    # The server has reached the 1st; the user is still on the last day of the previous month.
    pid = await _plan(client)
    _server_clock(monkeypatch, THIS_MONTH)
    url = f"/api/plans/{pid}/spending-models/compare"
    local = await client.post(url, json={"variants": [_months(K2)]}, headers={"X-Client-Date": M2_END.isoformat()})
    assert local.status_code == 422 and local.json()["error"]["code"] == "MONTH_INCOMPLETE"
    assert local.json()["error"]["details"] == [{"month": K2, "reasons": [{"code": "in_progress", "source_ids": []}]}]
    assert (await client.post(url, json={"variants": [_months(K2)]})).status_code == 200


async def test_a_month_the_user_has_finished_previews_and_applies_to_the_feed(client, db_session, monkeypatch, ledger):
    # The user has reached the 1st; the server is still on the last day of the previous month.
    card, checking = ledger
    pid = await _plan(client, expenses=False)
    await _feed(client, pid, [card.id, checking.id])
    _server_clock(monkeypatch, M2_END)
    headers = {"X-Client-Date": THIS_MONTH.isoformat()}
    months = (await client.get("/api/ledger/months", params={"plan_id": pid}, headers=headers)).json()["months"]
    assert [month["month"] for month in months if month["complete"]] == [K1, K2]
    preview = await client.post(f"/api/plans/{pid}/spending-models/compare", json={"variants": [_months(K2)]},
                                headers=headers)
    assert preview.status_code == 200, preview.text
    applied = await client.post(f"/api/plans/{pid}/spending-models/apply", headers=headers, json={
        "variant": _months(K2), "expected_fingerprint": preview.json()["fingerprint"]})
    assert applied.status_code == 200, applied.text
    assert applied.json()["basis"] == "months"
    db_session.expire_all()
    feed = feed_for_plan(db_session, uuid.UUID(pid))
    assert feed.basis_months == [K2] and feed.months_used == 1 and feed.error is None
    assert float(feed.last_essential) == 12 * 900
    server = await client.post(f"/api/plans/{pid}/spending-models/compare", json={"variants": [_months(K2)]})
    assert server.status_code == 422 and server.json()["error"]["code"] == "MONTH_INCOMPLETE"


# ── /api/ledger/spending-feeds ───────────────────────────────────

async def test_feed_routes_read_create_validate_and_stop(client, db_session, test_user, ledger):
    card, checking = ledger
    pid = await _plan(client)
    url = f"/api/ledger/spending-feeds/{pid}"
    assert (await client.get(url)).json() == {
        "plan_id": pid, "active": False, "source_ids": [], "basis": "trailing", "basis_months": [],
        "essential_expense_id": None, "discretionary_expense_id": None, "annual_essential": None,
        "annual_discretionary": None, "months_used": 0, "error": None, "applied_at": None}
    # The plan has expenses: turning the feed on needs the acknowledgement.
    assert (await client.put(url, json={"source_ids": [str(card.id)]})).status_code == 409
    savings = make_source(db_session, test_user, external="sav-2", account_type="DEPOSITORY", subtype="SAVINGS")
    make_import(db_session, test_user, savings, M1, TODAY)
    db_session.commit()
    assert (await client.put(url, json={"source_ids": [str(savings.id)],
                                        "acknowledge_existing_expenses": True})).status_code == 422
    assert (await client.put(url, json={"source_ids": [str(uuid.uuid4())]})).status_code == 404
    for body in ({"source_ids": [str(card.id)], "basis": "months"},
                 {"source_ids": [str(card.id)], "months": [K1]},
                 {"source_ids": [str(card.id)], "basis": "months", "months": ["2026-00"]},
                 {"source_ids": []}):
        assert (await client.put(url, json=body)).status_code == 422
    incomplete = await client.put(url, json={"source_ids": [str(card.id)], "acknowledge_existing_expenses": True,
                                             "basis": "months", "months": [NOW_KEY]})
    assert incomplete.status_code == 422 and incomplete.json()["error"]["code"] == "MONTH_INCOMPLETE"
    # An account the customer included in spending is eligible.
    savings.include_in_spending = True
    db_session.commit()
    on = await _feed(client, pid, [card.id, savings.id], acknowledge_existing_expenses=True, basis="months",
                     months=[K1, K1])
    assert on["active"] is True and on["basis_months"] == [K1]
    assert on["source_ids"] == [str(card.id), str(savings.id)]
    assert (await client.get(url)).json()["basis"] == "months"
    assert (await client.delete(url)).status_code == 204
    assert (await client.delete(url)).status_code == 404


async def test_feed_routes_guard_ownership_plan_type_and_release(client, db_session, test_user, ledger, monkeypatch):
    card, _ = ledger
    stranger = other_user(db_session)
    foreign = Plan(user_id=stranger.id, name="Other", birth_year=1980, life_expectancy=90, plan_type="NOW",
                   currency="USD")
    db_session.add(foreign)
    db_session.commit()
    url = f"/api/ledger/spending-feeds/{foreign.id}"
    assert (await client.get(url)).status_code == 404
    assert (await client.put(url, json={"source_ids": [str(card.id)]})).status_code == 404
    assert (await client.delete(url)).status_code == 404
    fixed = await _plan(client, expenses=False, plan_type="FIXED_DATE", start_date="2030-01-01")
    response = await client.put(f"/api/ledger/spending-feeds/{fixed}", json={"source_ids": [str(card.id)]})
    assert response.status_code == 409
    pid = await _plan(client, expenses=False)
    await _feed(client, pid, [card.id])
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "false")
    response = await client.put(f"/api/ledger/spending-feeds/{pid}", json={"source_ids": [str(card.id)]})
    assert response.status_code == 503 and response.json()["error"]["code"] == "FEATURE_DISABLED"
    assert (await client.get(f"/api/ledger/spending-feeds/{pid}")).json()["active"] is True
    assert (await client.delete(f"/api/ledger/spending-feeds/{pid}")).status_code == 204


def test_feed_routes_refuse_a_deleted_account(db_session):
    with pytest.raises(HTTPException) as error:
        ledger_feeds._lock_user(db_session, uuid.uuid4())
    assert error.value.status_code == 401

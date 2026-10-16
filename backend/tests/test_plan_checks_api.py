"""POST /api/plans/{plan_id}/plan-checks."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.auth.router import create_jwt
from app.models.financial_connection import FinancialBalanceLink, FinancialSource
from app.models.user import User
from app.routers import plan_checks as route
from coastmath.engine.household_lifecycle import UnsupportedLifecycleInput
from coastmath.engine.types import AccountInfo, PlanData
from tests.api_support import create_plan

pytestmark = pytest.mark.anyio


async def _plan(client, **fields):
    body = {"name": "Checks", "birth_year": 1980, "life_expectancy": 90, "filing_status": "single", **fields}
    return (await create_plan(client, **body))["id"]


async def test_route_scores_the_plan_lists_gaps_and_counts_use(client, db_session, test_user, recorded_usage):
    pid = await _plan(client)
    brokerage = (await client.post("/api/accounts", json={"name": "Brokerage", "account_type": "taxable_brokerage",
                                                          "balance": 100_000})).json()
    salary = (await client.post(f"/api/plans/{pid}/incomes", json={"name": "Acme", "annual_amount": 120_000})).json()

    r = await client.post(f"/api/plans/{pid}/plan-checks")
    assert r.status_code == 200, r.text
    body = r.json()
    assert {c["key"]: c["passes"] for c in body["checks"]} == {
        "accounts_entered": True, "expenses_entered": False, "social_security_self": False,
        "earned_income_ends": False,
    }
    assert body["score"] == round(100 * 20 / 65)
    assert [(i["key"], i["kind"], i["section"], i["title"], i["target_id"]) for i in body["items"]] == [
        ("expenses_entered", "missing", "expenses", "No expenses", None),
        ("social_security_self", "missing", "income", "No Social Security for you", None),
        ("earned_income_ends", "missing", "income", "Salary never ends: Acme", salary["id"]),
        ("cost_basis_assumed", "review", "accounts", "Basis assumed equal to balance: Brokerage", brokerage["id"]),
    ]
    assert body["items"][1]["person"] == "self"

    assert recorded_usage.count("plan_checks") == 1


async def test_route_reports_connected_balance_freshness(client, db_session, test_user):
    pid = await _plan(client)
    cash = (await client.post("/api/accounts", json={"name": "Cash", "account_type": "checking", "balance": 5_000})).json()
    savings = (await client.post("/api/accounts", json={"name": "Savings", "account_type": "savings", "balance": 5_000})).json()
    now = datetime.now(UTC)
    for account, updated in ((cash, now - timedelta(days=1)), (savings, now - timedelta(days=30))):
        source = FinancialSource(user_id=test_user.id, provider="plaid", environment="sandbox", provider_account_id=account["id"],
                                 institution_name="Bank", name=account["name"], account_type="DEPOSITORY",
                                 status="ACTIVE", balance=Decimal("5000"), currency="USD", balance_updated_at=updated)
        db_session.add(source)
        db_session.flush()
        db_session.add(FinancialBalanceLink(user_id=test_user.id, source_id=source.id, plan_id=uuid.UUID(pid),
                                            account_id=uuid.UUID(account["id"]), last_applied_balance=Decimal("5000"),
                                            source_revision=1, source_type="DEPOSITORY"))
    db_session.commit()

    body = (await client.post(f"/api/plans/{pid}/plan-checks")).json()
    assert {c["key"]: c["passes"] for c in body["checks"]}["balances_current"] is False
    stale = [i for i in body["items"] if i["key"] == "balances_current"]
    assert [(i["title"], i["target_id"]) for i in stale] == [("Stale balance: Savings", savings["id"])]


def test_balance_currency_ignores_non_uuid_and_empty_account_maps(db_session):
    plan = PlanData(plan_id=str(uuid.uuid4()), birth_year=1980, filing_status="single", life_expectancy=90,
                    start_year=2026, accounts={"not-a-uuid": AccountInfo(1, "checking")})
    assert route._balance_currency(plan, uuid.uuid4(), db_session) == {}
    plan.accounts = {str(uuid.uuid4()): AccountInfo(1, "checking")}
    assert route._balance_currency(plan, uuid.uuid4(), db_session) == {}


async def test_route_404s_for_unknown_and_other_users_plans(client, db_session):
    r = await client.post(f"/api/plans/{uuid.uuid4()}/plan-checks")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"

    pid = await _plan(client)
    other = User(is_anonymous=True, display_name="Other", settings={})
    db_session.add(other)
    db_session.commit()
    client.cookies.set("session", create_jwt(other.id))
    r = await client.post(f"/api/plans/{pid}/plan-checks")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


async def test_route_maps_lifecycle_input_to_422_and_engine_crash_to_500(client, monkeypatch):
    pid = await _plan(client)

    def unsupported(plan_data):
        raise UnsupportedLifecycleInput("Not supported")

    monkeypatch.setattr(route, "run_simulation", unsupported)
    r = await client.post(f"/api/plans/{pid}/plan-checks")
    assert r.status_code == 422
    assert r.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Not supported", "details": [
        {"field": "estate_settings.household_lifecycle", "reason": "Not supported"}]}

    def crash(plan_data):
        raise RuntimeError("boom")

    monkeypatch.setattr(route, "run_simulation", crash)
    r = await client.post(f"/api/plans/{pid}/plan-checks")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "SIMULATION_FAILED"

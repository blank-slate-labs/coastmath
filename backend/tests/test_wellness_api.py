"""POST /api/plans/{plan_id}/wellness."""

import uuid
from datetime import UTC, datetime

import pytest

from app.models.plan import Plan
from app.models.user import User
from coastmath.engine.household_lifecycle import UnsupportedLifecycleInput

pytestmark = pytest.mark.anyio

KEYS = ["savings_rate", "emergency_fund", "debt_to_income", "savings_to_income", "withdrawal_rate",
        "guaranteed_income", "pre_tax_share", "funded_years", "fi_timing"]


async def _plan(client) -> str:
    plan = (await client.post("/api/plans", json={"name": "Wellness", "birth_year": 1980, "plan_type": "NOW",
                                                  "life_expectancy": 90, "filing_status": "single"})).json()
    pid = plan["id"]
    cash = (await client.post("/api/accounts", json={"name": "Cash", "account_type": "checking", "balance": 24_000})).json()
    assert (await client.post(f"/api/plans/{pid}/incomes", json={"name": "Salary", "annual_amount": 120_000})).status_code == 201
    assert (await client.post(f"/api/plans/{pid}/expenses", json={"name": "Living", "annual_amount": 48_000,
                                                                  "category": "essential"})).status_code == 201
    r = await client.put(f"/api/plans/{pid}/drawdown-order", json={"items": [{"rank": 1, "source_account_id": cash["id"]}]})
    assert r.status_code in (200, 201), r.text
    return pid


async def test_route_returns_every_metric_in_order_and_counts_use(client, db_session, test_user, recorded_usage):
    pid = await _plan(client)
    r = await client.post(f"/api/plans/{pid}/wellness")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["start_year"] >= 2026
    assert [m["key"] for m in body["metrics"]] == KEYS
    by_key = {m["key"]: m for m in body["metrics"]}
    fund = by_key["emergency_fund"]
    assert fund["unit"] == "months" and fund["section"] == "accounts" and fund["basis_year"] == body["start_year"]
    assert fund["bands"] == {"better": "higher", "fair_at": 3.0, "strong_at": 6.0}
    assert fund["value"] > 0 and fund["status"] in ("strong", "fair", "needs_attention")
    debt = by_key["debt_to_income"]
    assert debt == {"key": "debt_to_income", "label": "Debt payments to income", "value": None, "unit": "percent",
                    "status": "not_applicable", "bands": None, "basis_year": None, "section": "property_debt"}

    assert recorded_usage.count("wellness") == 1


async def test_unknown_and_other_users_plans_are_not_found(client, db_session):
    r = await client.post(f"/api/plans/{uuid.uuid4()}/wellness")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    other = User(id=uuid.uuid4(), email="other@example.com", display_name="Other", settings={},
                 created_at=datetime.now(UTC))
    db_session.add(other)
    db_session.flush()
    plan = Plan(id=uuid.uuid4(), user_id=other.id, name="Other plan", birth_year=1980, plan_type="NOW",
                created_at=datetime.now(UTC))
    db_session.add(plan)
    db_session.commit()
    r = await client.post(f"/api/plans/{plan.id}/wellness")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


async def test_route_requires_a_session(client):
    pid = await _plan(client)
    client.cookies.clear()
    assert (await client.post(f"/api/plans/{pid}/wellness")).status_code == 401


@pytest.mark.parametrize("error,status,code,field", [
    (UnsupportedLifecycleInput("Successor treatment is not modeled."), 422, "VALIDATION_ERROR", "estate_settings.household_lifecycle"),
    (ValueError("QCD source must be a traditional IRA in this plan."), 422, "VALIDATION_ERROR", "plan"),
    (RuntimeError("boom"), 500, "SIMULATION_FAILED", None),
])
async def test_engine_errors_use_the_shared_envelope(client, monkeypatch, error, status, code, field):
    pid = await _plan(client)

    def fail(plan_data):
        raise error

    monkeypatch.setattr("app.routers.wellness.run_simulation", fail)
    r = await client.post(f"/api/plans/{pid}/wellness")
    assert r.status_code == status
    envelope = r.json()["error"]
    assert envelope["code"] == code
    if field is None:
        assert envelope["details"] == [] and "boom" not in envelope["message"]
    else:
        assert envelope["details"] == [{"field": field, "reason": str(error)}]

"""Cash yield survives saved-plan conversion and uses the existing income ledger."""

import uuid

import pytest

from app.routers.helpers import load_plan_data
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    PlanData,
)


def cash_plan(*, rate=0.0, curves=(), fraction=1.0):
    return PlanData(
        plan_id="b494c84f-5f5d-44c1-bdfe-f97507845de6", birth_year=1984, birth_month=1,
        filing_status="single", life_expectancy=44, start_year=2026,
        first_year_fraction=fraction, milestones=[], income_streams=[],
        expenses=[], priorities=[], drawdown_order=[],
        assumptions=AssumptionData(inflation_rate=0, cash_yield_rate=rate),
        assumption_curves=list(curves),
        accounts={"savings": AccountInfo(30_000, "savings")},
    )


@pytest.mark.parametrize("fraction", [1.0, 0.5])
def test_fixed_cash_yield_matches_scalar_and_credits_income_once(fraction):
    scalar = run_simulation(cash_plan(rate=0.035, fraction=fraction))
    curve = run_simulation(cash_plan(curves=[
        AssumptionCurveData("cash_yield", fixed_rate=0.035),
    ], fraction=fraction))
    assert curve.model_dump() == scalar.model_dump()
    first = curve.yearly_snapshots[0]
    interest = 30_000 * 0.035 * fraction
    assert first.gross_income == pytest.approx(interest)
    assert first.net_worth == pytest.approx(30_000 + interest)
    assert sum(row.amount for row in first.cash_flow.income_sources
               if row.name == "Savings Yield") == pytest.approx(interest)


def test_age_based_cash_yield_changes_each_year_without_double_credit():
    result = run_simulation(cash_plan(curves=[AssumptionCurveData(
        "cash_yield", mode="curve",
        control_points=[{"x": 42, "y": 0.035}, {"x": 43, "y": 0.02}],
    )]))
    first, second = result.yearly_snapshots[:2]
    assert first.gross_income == pytest.approx(1_050)
    assert second.gross_income == pytest.approx(31_050 * 0.02)
    assert second.net_worth == pytest.approx(31_050 * 1.02)


def test_explicit_zero_curve_overrides_nonzero_scalar():
    result = run_simulation(cash_plan(rate=0.035, curves=[
        AssumptionCurveData("cash_yield", fixed_rate=0.0),
    ]))
    assert result.yearly_snapshots[0].gross_income == 0
    assert result.yearly_snapshots[0].net_worth == 30_000


@pytest.mark.anyio
async def test_saved_cash_yield_create_reload_update_delete(client, db_session, test_user):
    account_id = str(uuid.uuid4())
    response = await client.post("/api/plans", json={
        "name": "Cash yield persistence", "birth_year": 1984, "birth_month": 1,
        "life_expectancy": 50, "plan_type": "FIXED_DATE", "start_date": "2026-01-01",
        "snapshot_conditions": {account_id: {"balance": 30_000, "account_type": "savings"}},
    })
    assert response.status_code == 201, response.text
    plan_id = response.json()["id"]
    response = await client.post(f"/api/plans/{plan_id}/assumptions", json={
        "curve_type": "cash_yield", "mode": "fixed", "fixed_rate": 0.035,
    })
    assert response.status_code == 201, response.text
    curve_id = response.json()["id"]
    db_session.expire_all()
    saved = (await client.get(f"/api/plans/{plan_id}")).json()
    assert saved["assumption_curves"][0]["fixed_rate"] == 0.035
    data = load_plan_data(uuid.UUID(plan_id), test_user, db_session)
    assert data.assumptions.cash_yield_rate == 0.035
    first = run_simulation(data).yearly_snapshots[0]
    assert first.gross_income == pytest.approx(1_050)
    assert first.net_worth == pytest.approx(31_050)

    response = await client.put(f"/api/plans/{plan_id}/assumptions/{curve_id}", json={
        "fixed_rate": 0.0,
    })
    assert response.status_code == 200, response.text
    assert load_plan_data(uuid.UUID(plan_id), test_user, db_session).assumptions.cash_yield_rate == 0
    response = await client.delete(f"/api/plans/{plan_id}/assumptions/{curve_id}")
    assert response.status_code == 204
    restored = load_plan_data(uuid.UUID(plan_id), test_user, db_session)
    assert restored.assumptions.cash_yield_rate == 0
    assert restored.assumption_curves == []

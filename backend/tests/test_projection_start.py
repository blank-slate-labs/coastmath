"""Opening balances, dated first-year projections, and live account mutations."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.engine import plan_converter
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AssumptionData,
    ExpenseData,
    IncomeData,
    LiabilityData,
    RealAssetData,
)
from tests.api_support import make_account, make_plan


@pytest.mark.parametrize("as_of", [date(2026, 1, 1), date(2026, 9, 5), date(2026, 12, 31), date(2028, 2, 29)])
@pytest.mark.parametrize("plan_type", ["NOW", "FIXED_DATE"])
def test_opening_balances_and_remaining_year(as_of, plan_type, db_session, test_user, monkeypatch):
    class Today(date):
        @classmethod
        def today(cls):
            return as_of

    monkeypatch.setattr(plan_converter, "datetime", SimpleNamespace(date=Today))
    plan = make_plan(db_session, test_user)
    plan.plan_type = plan_type
    plan.start_date = as_of if plan_type == "FIXED_DATE" else None
    acct = make_account(db_session, test_user, balance=100_000, cost_basis=None)
    acct.account_type = "roth_ira"
    data = plan_converter.plan_to_engine_data(plan, [acct])
    data.assumptions = AssumptionData(stock_growth_rate=0.07, inflation_rate=0)
    data.income_streams = [IncomeData(id="income", name="Income", annual_amount=12_000, is_earned_income=False)]
    data.expenses = [ExpenseData(id="expense", name="Expense", annual_amount=6_000)]
    data.real_assets = [RealAssetData(id="home", name="Home", current_value=200_000, annual_appreciation_rate=0)]
    data.liabilities = [LiabilityData(id="loan", name="Loan", principal_balance=50_000, interest_rate=0, monthly_payment=0)]
    result = run_simulation(data)
    fraction = (date(as_of.year + 1, 1, 1) - as_of).days / (date(as_of.year + 1, 1, 1) - date(as_of.year, 1, 1)).days
    assert result.metadata.start_date == as_of
    assert result.metadata.first_year_fraction == pytest.approx(fraction)
    opening = result.initial_snapshot
    assert opening.as_of == as_of
    assert opening.accounts == {str(acct.id): 100_000}
    assert opening.net_worth == 250_000
    first = result.yearly_snapshots[0]
    assert first.accounts[str(acct.id)] == pytest.approx(100_000 * 1.07 ** fraction)
    assert first.gross_income == pytest.approx(12_000 * fraction)
    assert first.expenses == pytest.approx(6_000 * fraction)
    assert first.net_worth > opening.net_worth
    # The opening snapshot remains untouched by all subsequent annual loops.
    assert result.initial_snapshot.accounts[str(acct.id)] == 100_000


@pytest.mark.anyio
async def test_account_crud_changes_opening_and_projected_balances(client):
    created = await client.post("/api/plans", json={"name": "Refresh test", "birth_year": 1990, "filing_status": "single", "plan_type": "NOW"})
    assert created.status_code == 201
    pid = created.json()["id"]
    async def simulate():
        response = await client.post(f"/api/plans/{pid}/simulate")
        assert response.status_code == 200
        return response.json()

    before = await simulate()
    response = await client.post("/api/accounts", json={"name": "Roth", "account_type": "roth_ira", "balance": 100_000})
    assert response.status_code == 201
    aid = response.json()["id"]
    added = await simulate()
    assert added["initial_snapshot"]["accounts"][aid] == 100_000
    response = await client.put(f"/api/accounts/{aid}", json={"balance": 200_000})
    assert response.status_code == 200
    updated = await simulate()
    assert updated["initial_snapshot"]["accounts"][aid] == 200_000
    for low, high in zip(added["yearly_snapshots"], updated["yearly_snapshots"], strict=True):
        assert high["accounts"][aid] == pytest.approx(2 * low["accounts"][aid])
    response = await client.delete(f"/api/accounts/{aid}")
    assert response.status_code == 204
    deleted = await simulate()
    assert aid not in deleted["initial_snapshot"]["accounts"]
    assert deleted["yearly_snapshots"] == before["yearly_snapshots"]

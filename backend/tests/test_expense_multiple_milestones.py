"""FI milestones use completed spending annualized over the simulated year."""

import uuid
from dataclasses import asdict
from datetime import date

import pytest

from app.main import app
from app.routers.helpers import client_today
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    LiabilityData,
    MilestoneData,
    PlanData,
    PriorityData,
    RealAssetData,
)


def _plan(fraction=1.0, balance=1_000_000, metric="liquid_net_worth"):
    return PlanData(
        plan_id=str(uuid.uuid4()),
        birth_year=1980,
        life_expectancy=50,
        filing_status="single",
        start_year=2026,
        first_year_fraction=fraction,
        accounts={"cash": AccountInfo(balance=balance, account_type="checking")},
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0),
        tax_settings={
            "mode": "flat",
            "ordinary_income_tax_rate": 0,
            "capital_gains_tax_rate": 0,
        },
        milestones=[MilestoneData(
            id="fi", name="FI", trigger_type="expense_multiple",
            expense_multiple=25, metric=metric,
        )],
        income_streams=[IncomeData(id="salary", name="Salary", annual_amount=100_000)],
        expenses=[ExpenseData(id="living", name="Living", annual_amount=100_000)],
        priorities=[PriorityData(priority_rank=1, target_account_id="cash")],
        drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash")],
    )


@pytest.mark.parametrize("fraction", [1.0, 0.5, 115 / 365, 1 / 365, 0.0])
@pytest.mark.parametrize("balance", [1_000_000, 2_500_000, 2_500_001])
@pytest.mark.parametrize("metric", ["liquid_net_worth", "net_worth"])
def test_first_year_fraction_does_not_lower_fi_target(fraction, balance, metric):
    result = run_simulation(_plan(fraction, balance, metric))
    first = result.yearly_snapshots[0]
    # The cash ledger still covers only the remaining part of the opening year.
    assert first.expenses == pytest.approx(100_000 * fraction)
    assert first.gross_income == pytest.approx(100_000 * fraction)
    assert first.accounts["cash"] == pytest.approx(balance)
    # FI requires strictly more than 25 * $100,000, whatever the start date.
    # A zero-duration year supplies no expense basis; wait for the next year.
    # The completed year's spending is consumed at the next opening boundary;
    # report that activation year, including for linked relative milestones.
    expected_year = (2027 if fraction > 0 else 2028) if balance > 2_500_000 else None
    assert result.metadata.milestone_outcomes[0].year == expected_year


@pytest.mark.parametrize("fraction", [1.0, 0.25])
@pytest.mark.parametrize("metric", ["liquid_net_worth", "net_worth"])
def test_fi_counts_all_completed_expense_components(fraction, metric):
    plan = _plan(fraction, balance=1_200_000, metric=metric)
    plan.income_streams[0].annual_amount = 200_000
    plan.expenses = [
        ExpenseData(id="living", name="Living", annual_amount=36_000),
        ExpenseData(id="payroll", name="Payroll expense", annual_amount=6_000,
                    is_payroll_deduction=True),
        ExpenseData(id="funded", name="Funded expense", annual_amount=24_000,
                    specific_funding_source_id="cash"),
    ]
    plan.real_assets = [RealAssetData(
        id="home", name="Home", current_value=200_000,
        annual_appreciation_rate=0, annual_maintenance=12_000,
    )]
    plan.liabilities = [LiabilityData(
        id="loan", name="Loan", principal_balance=120_000,
        interest_rate=0, monthly_payment=1_000,
    )]

    result = run_simulation(plan)
    first = result.yearly_snapshots[0]
    # $36k living + $6k payroll + $24k funded + $12k upkeep + $12k loan.
    assert first.expenses == pytest.approx(90_000 * fraction)
    assert first.accounts["cash"] == pytest.approx(1_200_000 + 110_000 * fraction)
    assert first.liabilities_balance == pytest.approx(120_000 - 12_000 * fraction)
    assert result.metadata.milestone_outcomes[0].year is None


def test_fi_waits_for_full_annual_target_before_stopping_linked_income():
    plan = _plan(fraction=0.25, balance=250_000)
    plan.income_streams[0].annual_amount = 36_000
    plan.income_streams[0].end_milestone_id = "retire"
    plan.expenses[0].annual_amount = 12_000
    plan.milestones.append(MilestoneData(
        id="retire", name="Retirement", trigger_type="relative",
        relative_to_id="fi", offset_years=0,
    ))

    result = run_simulation(plan)
    # $300k target: $250k + $6k in the opening quarter, then $24k/year.
    assert [s.accounts["cash"] for s in result.yearly_snapshots] == pytest.approx(
        [256_000, 280_000, 304_000, 292_000],
    )
    assert [s.gross_income for s in result.yearly_snapshots] == [9_000, 36_000, 36_000, 0]
    assert {m.id: m.year for m in result.metadata.milestone_outcomes} == {
        "fi": 2029, "retire": 2029,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("plan_type", ["NOW", "FIXED_DATE"])
async def test_persisted_and_stateless_fi_use_annual_expenses(client, monkeypatch, plan_type):
    # Freeze the converter's date for a reproducible late-year Now plan.

    start = date(2026, 9, 8)
    fraction = (date(2027, 1, 1) - start).days / 365
    monkeypatch.setitem(app.dependency_overrides, client_today, lambda: start)
    plan = _plan(fraction)
    account_id = str(uuid.uuid4())
    created = await client.post("/api/plans", json={
        "name": "Annual expense FI regression", "plan_type": plan_type,
        "birth_year": 1980, "life_expectancy": 50,
        "start_date": start.isoformat() if plan_type == "FIXED_DATE" else None,
        "snapshot_conditions": {
            account_id: {"balance": 1_000_000, "account_type": "checking"},
        } if plan_type == "FIXED_DATE" else {},
        "tax_settings": plan.tax_settings,
    })
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    if plan_type == "NOW":
        account = await client.post("/api/accounts", json={
            "name": "Cash", "account_type": "checking", "balance": 1_000_000,
        })
        assert account.status_code == 201, account.text
    for endpoint, payload in [
        ("expenses", {"name": "Living", "annual_amount": 100_000, "inflation_linked": False}),
        ("incomes", {"name": "Salary", "annual_amount": 100_000, "growth_rate": 0}),
        ("milestones", {"name": "FI", "trigger_type": "expense_multiple",
                        "expense_multiple": 25, "metric": "liquid_net_worth"}),
    ]:
        response = await client.post(f"/api/plans/{pid}/{endpoint}", json=payload)
        assert response.status_code == 201, response.text

    # Re-read persisted inputs before requesting a fresh calculation.
    saved = await client.get(f"/api/plans/{pid}")
    assert saved.status_code == 200
    assert saved.json()["expenses"][0]["annual_amount"] == 100_000
    persisted = await client.post(f"/api/plans/{pid}/simulate")
    stateless = await client.post("/api/simulate/stateless", json=asdict(plan))
    for response in (persisted, stateless):
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["yearly_snapshots"][0]["expenses"] == pytest.approx(100_000 * fraction)
        assert data["metadata"]["first_year_fraction"] == pytest.approx(fraction)
        assert data["metadata"]["milestone_outcomes"][0]["year"] is None
        # Both paths return the FI estimate with the shared wire shape.
        assert data["metadata"]["fi_estimate"] == {
            "year": None, "basis_year": None, "target": None, "multiple": 25,
        }


# --- CoastMath FI estimate (metadata.fi_estimate) -------------------------------

@pytest.mark.parametrize("fraction", [1.0, 0.5, 115 / 365, 1 / 365, 0.0])
@pytest.mark.parametrize("balance", [1_000_000, 2_500_000, 2_500_001])
def test_fi_estimate_matches_a_25x_liquid_milestone(fraction, balance):
    result = run_simulation(_plan(fraction, balance))
    estimate = result.metadata.fi_estimate
    # The estimate is the user's 25x liquid-minus-debt milestone, so converting
    # it into one never moves its year, including after a partial opening year.
    assert estimate.year == result.metadata.milestone_outcomes[0].year
    assert estimate.multiple == 25
    if estimate.year is None:
        assert (estimate.basis_year, estimate.target) == (None, None)
        return
    assert estimate.basis_year == estimate.year - 1
    basis = next(s for s in result.yearly_snapshots if s.year == estimate.basis_year)
    basis_fraction = fraction if basis.year == 2026 else 1.0
    # Basis-year spending annualized: $100,000 a year, whatever the start date.
    assert estimate.target == pytest.approx(25 * basis.expenses / basis_fraction)
    assert estimate.target == pytest.approx(2_500_000)


def test_fi_estimate_never_reached_is_all_null():
    result = run_simulation(_plan(balance=100_000))
    assert result.metadata.fi_estimate.model_dump() == {
        "year": None, "basis_year": None, "target": None, "multiple": 25,
    }


def test_fi_estimate_subtracts_debt_and_ignores_property():
    # $88k living + $12k loan payments = $100k spending, so a $2.5M target.
    def plan_with(balance, loan=0.0, home=0.0):
        plan = _plan(balance=balance)
        plan.expenses[0].annual_amount = 88_000 if loan else 100_000
        if loan:
            plan.liabilities = [LiabilityData(
                id="loan", name="Loan", principal_balance=loan, interest_rate=0, monthly_payment=1_000,
            )]
        if home:
            plan.real_assets = [RealAssetData(
                id="home", name="Home", current_value=home, annual_appreciation_rate=0,
            )]
        return run_simulation(plan)

    no_debt = plan_with(2_600_000)
    assert no_debt.metadata.fi_estimate.year == 2027
    # $2.6M cash minus a $138k-and-falling loan stays under $2.5M through 2029.
    with_debt = plan_with(2_600_000, loan=150_000)
    assert with_debt.metadata.fi_estimate.year is None
    assert with_debt.metadata.milestone_outcomes[0].year is None
    # Property counts toward net worth, not toward the liquid estimate.
    with_home = plan_with(2_400_000, home=500_000)
    assert with_home.metadata.fi_estimate.year is None
    assert with_home.yearly_snapshots[0].net_worth > 2_500_000

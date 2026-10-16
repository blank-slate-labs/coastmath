"""Focused coverage for nullable per-account investment assumption overrides."""

import uuid

import numpy as np
import pytest

from coastmath.engine.monte_carlo import _run_single_trial, _TrialInputs
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PlanData,
    PriorityData,
    SimState,
)


def _plan(accounts, *, curves=None, tax_settings=None, expenses=None, priorities=None):
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000001",
        birth_year=1980,
        filing_status="single",
        life_expectancy=90,
        start_year=2026,
        assumptions=AssumptionData(
            inflation_rate=0.0,
            stock_growth_rate=0.10,
            bond_return_rate=0.04,
            stock_dividend_yield=0.0,
        ),
        assumption_curves=curves or [],
        accounts=accounts,
        drawdown_order=[DrawdownEntryData(rank=i + 1, source_account_id=aid)
                        for i, aid in enumerate(accounts)],
        tax_settings=tax_settings,
        expenses=expenses or [],
        priorities=priorities or [],
    )


def test_accounts_use_independent_fixed_blends_and_inherited_defaults():
    plan = _plan(
        {
            "custom": AccountInfo(
                100_000,
                "taxable_brokerage",
                cost_basis=100_000,
                investment_settings={
                    "stock_growth_rate": 0.0,
                    "bond_allocation": 0.5,
                },
            ),
            "inherited": AccountInfo(100_000, "taxable_brokerage", cost_basis=100_000),
        },
        curves=[AssumptionCurveData("bond_allocation", fixed_rate=0.2)],
    )

    result = run_simulation(plan)
    first = result.yearly_snapshots[0]

    # Custom: 50% × 4% bond return + 50% × 0% stock return.
    assert first.accounts["custom"] == pytest.approx(102_000.0)
    # Inherited: the plan's 20% bond mix blends 4% bonds and 10% stocks.
    assert first.accounts["inherited"] == pytest.approx(108_800.0)


def test_fixed_dividend_override_keeps_taxable_reinvested_basis_aligned():
    account = AccountInfo(
        100_000,
        "taxable_brokerage",
        cost_basis=50_000,
        investment_settings={"dividend_yield": 0.03},
    )
    state = SimState(year=2026, accounts={"brokerage": account})
    taxable_dividends, taxable_interest = state.apply_growth(
        0.0,
        0.04,
        0.0,
        stock_dividend_yield=0.0,
        account_rates={"brokerage": (0.0, 0.04, 0.0, 0.03)},
    )

    assert taxable_dividends == pytest.approx(3_000.0)
    assert taxable_interest == 0.0
    assert state.accounts["brokerage"].balance == pytest.approx(103_000.0)
    # Reinvested dividends are recognized and added to basis before later sales.
    assert state.accounts["brokerage"].cost_basis == pytest.approx(53_000.0)


def test_monthly_contribution_growth_uses_account_specific_blend():
    plan = _plan(
        {
            "custom": AccountInfo(
                0,
                "taxable_brokerage",
                cost_basis=0,
                investment_settings={"stock_growth_rate": 0.0},
            ),
            "inherited": AccountInfo(0, "taxable_brokerage", cost_basis=0),
            "cash": AccountInfo(0, "checking"),
        },
        tax_settings={"cash_flow_frequency": "monthly", "mode": "flat", "ordinary_income_tax_rate": 0},
        expenses=[ExpenseData("spend", "Spending", 0)],
        priorities=[
            PriorityData(1, "custom", max_annual_amount=6_000),
            PriorityData(2, "inherited"),
        ],
    )
    plan.income_streams = [IncomeData("salary", "Salary", 12_000, growth_rate=0.0)]

    first = run_simulation(plan).yearly_snapshots[0]

    # Six thousand is contributed to each account; the custom account's
    # contributions earn no stock return while the inherited account earns 10%.
    assert first.accounts["custom"] == pytest.approx(6_000.0)
    assert first.accounts["inherited"] > 6_000.0


def test_monte_carlo_trial_honors_fixed_stock_override():
    plan = _plan(
        {
            "custom": AccountInfo(
                100_000,
                "taxable_brokerage",
                cost_basis=100_000,
                investment_settings={"stock_growth_rate": 0.0},
            ),
            "sampled": AccountInfo(100_000, "taxable_brokerage", cost_basis=100_000),
        }
    )
    history = np.array([[0.25, 0.0, 0.0]], dtype=float)
    result = _run_single_trial(
        _TrialInputs(plan, history, plan_years=1, start_year=2026, block_size_range=(1, 1)),
        seed=1,
    )

    first = result.yearly_snapshots[0]
    assert first.accounts["custom"] == pytest.approx(100_000.0)
    assert first.accounts["sampled"] == pytest.approx(125_000.0)


@pytest.mark.anyio
async def test_account_settings_api_round_trip_and_stateless_parity(client):
    plan_response = await client.post(
        "/api/plans",
        json={"name": "Account returns", "birth_year": 1980, "plan_type": "NOW"},
    )
    assert plan_response.status_code == 201, plan_response.text
    plan = plan_response.json()
    settings = {
        "stock_growth_rate": 0.0,
        "dividend_yield": 0.02,
        "bond_allocation": 0.5,
    }
    account_response = await client.post(
        "/api/accounts",
        json={
            "name": "Custom brokerage",
            "account_type": "taxable_brokerage",
            "balance": 100_000,
            "cost_basis": 100_000,
            "investment_settings": settings,
        },
    )
    assert account_response.status_code == 201, account_response.text
    account = account_response.json()
    # Income-composition keys are additive and read back as null (legacy).
    read_back = {**settings, "qualified_dividend_ratio": None, "bond_income_yield": None,
                 "bond_income_mix": None, "municipal_state_exempt": None, "annual_fee_rate": None,
                 "annual_fee_amount": None, "fee_percent_of_earnings": None, "reinvest_income": None}
    assert account["investment_settings"] == read_back
    listed = await client.get("/api/accounts")
    assert listed.status_code == 200
    assert next(row for row in listed.json() if row["id"] == account["id"])["investment_settings"] == read_back

    persisted_response = await client.post(f"/api/plans/{plan['id']}/simulate")
    assert persisted_response.status_code == 200, persisted_response.text
    persisted = persisted_response.json()
    first_fraction = persisted["metadata"]["first_year_fraction"]
    stateless_body = {
        "plan_id": plan["id"],
        "birth_year": plan["birth_year"],
        "start_year": persisted["metadata"]["start_year"],
        "first_year_fraction": first_fraction,
        "life_expectancy": plan["life_expectancy"],
        "assumptions": {
            "inflation_rate": 0.03,
            "stock_growth_rate": 0.07,
            "bond_return_rate": 0.04,
            "stock_dividend_yield": 0.0,
            "cash_yield_rate": 0.0,
        },
        "accounts": {
            account["id"]: {
                "balance": 100_000,
                "account_type": "taxable_brokerage",
                "name": "Custom brokerage",
                "cost_basis": 100_000,
                "investment_settings": settings,
            },
        },
    }
    stateless_response = await client.post("/api/simulate/stateless", json=stateless_body)
    assert stateless_response.status_code == 200, stateless_response.text
    stateless = stateless_response.json()
    assert stateless["yearly_snapshots"][0]["accounts"][account["id"]] == pytest.approx(
        persisted["yearly_snapshots"][0]["accounts"][account["id"]],
    )


@pytest.mark.anyio
async def test_fixed_date_snapshot_carries_investment_settings_into_simulation(client):
    aid = str(uuid.uuid4())
    response = await client.post(
        "/api/plans",
        json={
            "name": "Snapshot account returns",
            "birth_year": 1980,
            "life_expectancy": 90,
            "plan_type": "FIXED_DATE",
            "start_date": "2026-01-01",
            "snapshot_conditions": {
                aid: {
                    "name": "Snapshot brokerage",
                    "account_type": "taxable_brokerage",
                    "balance": 100_000,
                    "cost_basis": 100_000,
                    "investment_settings": {
                        "stock_growth_rate": 0.0,
                        "dividend_yield": 0.0,
                        "bond_allocation": 0.5,
                    },
                },
            },
        },
    )
    assert response.status_code == 201, response.text
    simulation = await client.post(f"/api/plans/{response.json()['id']}/simulate")
    assert simulation.status_code == 200, simulation.text
    assert simulation.json()["yearly_snapshots"][0]["accounts"][aid] == pytest.approx(102_000.0)

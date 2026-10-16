"""Regression coverage for taxable and non-taxable retirement drawdowns."""

from __future__ import annotations

import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    PlanData,
)


def _one_year_drawdown_plan(account: AccountInfo) -> PlanData:
    return PlanData(
        plan_id=str(uuid.uuid4()),
        birth_year=1965,  # age 60 in 2025: no RMD and no 10% early penalty
        filing_status="single",
        life_expectancy=61,
        start_year=2025,
        expenses=[
            ExpenseData(
                id="living",
                name="Living expenses",
                annual_amount=80_000,
                inflation_linked=False,
            ),
        ],
        accounts={"source": account},
        drawdown_order=[DrawdownEntryData(rank=1, source_account_id="source")],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
    )


def test_traditional_401k_drawdown_increases_gross_income_and_taxes():
    plan = _one_year_drawdown_plan(
        AccountInfo(balance=500_000, account_type="traditional_401k"),
    )

    snap = run_simulation(plan).yearly_snapshots[0]

    assert sum(d.amount for d in snap.cash_flow.drawdowns) >= 80_000
    assert snap.gross_income >= 80_000
    assert snap.taxes > 0
    assert snap.effective_rate > 0


def test_taxable_brokerage_full_basis_drawdown_is_not_ordinary_income():
    plan = _one_year_drawdown_plan(
        AccountInfo(
            balance=500_000,
            account_type="taxable_brokerage",
            cost_basis=500_000,
        ),
    )

    snap = run_simulation(plan).yearly_snapshots[0]

    assert sum(d.amount for d in snap.cash_flow.drawdowns) == pytest.approx(80_000)
    assert snap.gross_income == 0
    assert snap.taxes == 0


def test_cryptocurrency_drawdown_realizes_same_gain_as_taxable_brokerage():
    taxable_plan = _one_year_drawdown_plan(
        AccountInfo(
            balance=500_000,
            account_type="taxable_brokerage",
            cost_basis=250_000,
        ),
    )
    crypto_plan = _one_year_drawdown_plan(
        AccountInfo(
            balance=500_000,
            account_type="cryptocurrency",
            cost_basis=250_000,
        ),
    )
    flat_tax = {
        "mode": "flat",
        "ordinary_income_tax_rate": 0.30,
        "capital_gains_tax_rate": 0.15,
    }
    taxable_plan.tax_settings = flat_tax
    crypto_plan.tax_settings = flat_tax

    taxable = run_simulation(taxable_plan).yearly_snapshots[0]
    crypto = run_simulation(crypto_plan).yearly_snapshots[0]

    assert crypto.taxes > 0
    assert crypto.taxes == pytest.approx(taxable.taxes)
    assert crypto.gross_income == pytest.approx(taxable.gross_income)
    assert crypto.accounts["source"] == pytest.approx(taxable.accounts["source"])
    assert sum(d.amount for d in crypto.cash_flow.drawdowns) == pytest.approx(
        sum(d.amount for d in taxable.cash_flow.drawdowns)
    )


def test_qualified_roth_ira_drawdown_is_not_taxable_income():
    plan = _one_year_drawdown_plan(
        AccountInfo(balance=500_000, account_type="roth_ira",
            roth_settings={"first_contribution_year":2010, "contribution_basis":0}),
    )

    snap = run_simulation(plan).yearly_snapshots[0]

    assert sum(d.amount for d in snap.cash_flow.drawdowns) == pytest.approx(80_000)
    assert snap.gross_income == 0
    assert snap.taxes == 0

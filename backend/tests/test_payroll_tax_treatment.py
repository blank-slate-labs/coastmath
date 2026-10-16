"""Regression coverage for pre-tax and after-tax payroll expenses."""

from __future__ import annotations

import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    ExpenseData,
    IncomeData,
    PlanData,
)
from coastmath.schemas.plan_data_request import (
    ExpenseRequest,
    PlanDataRequest,
    request_to_engine_data,
)


def _plan(treatment: str = "pre_tax", *, first_year_fraction: float = 1.0) -> PlanData:
    return PlanData(
        plan_id=str(uuid.uuid4()),
        birth_year=1980,
        filing_status="single",
        life_expectancy=90,
        start_year=2026,
        first_year_fraction=first_year_fraction,
        income_streams=[IncomeData(id="salary", name="Wages", annual_amount=100_000)],
        expenses=[
            ExpenseData(
                id="health",
                name="Health premium",
                annual_amount=12_000,
                inflation_linked=False,
                is_payroll_deduction=True,
                payroll_tax_treatment=treatment,
                tied_income_id="salary",
            )
        ],
        accounts={"cash": AccountInfo(balance=0, account_type="checking")},
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0),
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0.20},
    )


@pytest.mark.parametrize(
    ("treatment", "expected_tax", "expected_cash"),
    [("pre_tax", 17_600, 70_400), ("after_tax", 20_000, 68_000)],
)
def test_payroll_tax_treatment_changes_tax_but_charges_cash_once(
    treatment: str, expected_tax: float, expected_cash: float
) -> None:
    snapshot = run_simulation(_plan(treatment)).yearly_snapshots[0]

    assert snapshot.federal_tax == pytest.approx(expected_tax)
    assert snapshot.expenses == pytest.approx(12_000)
    assert snapshot.cash_flow is not None
    assert snapshot.cash_flow.payroll_deductions == pytest.approx(12_000)
    assert snapshot.cash_flow.net_pay == pytest.approx(88_000)
    assert snapshot.net_cash_flow == pytest.approx(expected_cash)
    # The paycheck expense is represented once in the payroll scalar and is
    # not also emitted as a general expense flow.
    assert sum(flow.amount for flow in snapshot.cash_flow.expenses) == pytest.approx(0)


def test_partial_year_payroll_expense_is_clamped_to_tied_salary() -> None:
    snapshot = run_simulation(_plan("after_tax", first_year_fraction=0.5)).yearly_snapshots[0]

    assert snapshot.gross_income == pytest.approx(50_000)
    assert snapshot.expenses == pytest.approx(6_000)
    assert snapshot.cash_flow is not None
    assert snapshot.cash_flow.payroll_deductions == pytest.approx(6_000)
    # Tax reports the full $100,000 calendar-year wages; only the post-start
    # share settles against this partial year's cash.
    assert snapshot.federal_tax == pytest.approx(20_000)
    assert snapshot.net_cash_flow == pytest.approx(34_000)


def test_stateless_request_defaults_and_preserves_payroll_tax_treatment() -> None:
    base = PlanDataRequest(
        plan_id=uuid.uuid4(),
        birth_year=1980,
        start_year=2026,
        life_expectancy=90,
        expenses=[
            ExpenseRequest(
                id="health",
                name="Health premium",
                annual_amount=12_000,
                is_payroll_deduction=True,
                tied_income_id="salary",
            )
        ],
    )
    assert request_to_engine_data(base).expenses[0].payroll_tax_treatment == "pre_tax"

    after_tax = base.model_copy(
        update={
            "expenses": [
                base.expenses[0].model_copy(update={"payroll_tax_treatment": "after_tax"})
            ]
        }
    )
    assert request_to_engine_data(after_tax).expenses[0].payroll_tax_treatment == "after_tax"


@pytest.mark.anyio
async def test_payroll_tax_treatment_save_read_and_stale_protection(client) -> None:
    plan = (await client.post("/api/plans", json={"name": "Payroll", "birth_year": 1980})).json()
    income = (
        await client.post(
            f"/api/plans/{plan['id']}/incomes",
            json={"name": "Wages", "annual_amount": 100_000},
        )
    ).json()
    base = f"/api/plans/{plan['id']}/expenses"
    expense = (
        await client.post(
            base,
            json={
                "name": "Health premium",
                "annual_amount": 12_000,
                "is_payroll_deduction": True,
                "tied_income_id": income["id"],
                "payroll_tax_treatment": "after_tax",
            },
        )
    ).json()
    assert expense["payroll_tax_treatment"] == "after_tax"
    assert (await client.get(base)).json()[0]["payroll_tax_treatment"] == "after_tax"
    copied = (await client.post(f"/api/plans/{plan['id']}/duplicate")).json()
    assert copied["expenses"][0]["payroll_tax_treatment"] == "after_tax"

    path = f"{base}/{expense['id']}"
    renamed = await client.put(path, json={"name": "Dental and health"})
    assert renamed.status_code == 200
    changed = await client.put(
        path,
        json={
            "payroll_tax_treatment": "pre_tax",
            "expected_values": {"payroll_tax_treatment": "after_tax"},
        },
    )
    assert changed.status_code == 200
    assert changed.json()["name"] == "Dental and health"
    assert changed.json()["payroll_tax_treatment"] == "pre_tax"

    stale = await client.put(
        path,
        json={
            "payroll_tax_treatment": "after_tax",
            "expected_values": {"payroll_tax_treatment": "after_tax"},
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CONFLICT"
    saved = (await client.get(base)).json()[0]
    assert saved["name"] == "Dental and health"
    assert saved["payroll_tax_treatment"] == "pre_tax"

"""ACA income counts Social Security exactly once, and cash is conserved.

Premium-tax-credit MAGI includes all Social Security benefits plus IRA
withdrawals and Roth conversions, with settlement lag, year-to-date income and
the prior-year estimate. Expected MAGI, credits and net worth are derived
independently from the IRS rules and Rev. Proc. 2025-25, not from engine
output.
"""

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PlanData,
    PriorityData,
)


def social_security_plan(**changes):
    fields = dict(
        plan_id="00000000-0000-4000-8000-000000000001",
        birth_year=1963, birth_month=1, filing_status="single",
        life_expectancy=65, start_year=2026, milestones=[],
        income_streams=[IncomeData(
            "ss", "Social Security", 24_000, is_social_security=True,
            is_earned_income=False, claiming_age=62, growth_rate=0,
        )],
        expenses=[ExpenseData("living", "Living", 45_000, inflation_linked=False)],
        priorities=[], drawdown_order=[DrawdownEntryData(1, "ira")],
        assumptions=AssumptionData(
            inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
            stock_dividend_yield=0, cash_yield_rate=0,
        ),
        accounts={"ira": AccountInfo(500_000, "traditional_ira")},
        healthcare_settings={
            "enabled": True, "aca_enabled": True,
            "aca_benchmark_premium_annual": 12_000,
            "aca_plan_premium_annual": 12_000, "aca_apply_age_curve": False,
            "medicare_enabled": False, "magi_prior_year": 45_000,
        },
    )
    fields.update(changes)
    return PlanData(**fields)


@pytest.mark.parametrize("settlement_lag", [0, 1])
def test_aca_counts_social_security_once_after_ira_withdrawals(settlement_lag):
    result = run_simulation(social_security_plan(
        tax_settings={"settlement_lag_years": settlement_lag},
    ))
    prior_magi = 45_000
    opening = 500_000
    for snap in result.yearly_snapshots:
        withdrawals = sum(flow.amount for flow in snap.cash_flow.drawdowns)
        # IRS PTC income includes all Social Security: taxable benefits in
        # AGI plus the remaining nontaxable benefits, not an earlier split.
        expected_magi = withdrawals + 24_000
        hc = snap.healthcare
        assert hc.aca_magi == pytest.approx(expected_magi)
        assert hc.aca_magi_estimate == pytest.approx(prior_magi)
        assert 3 * 15_650 < expected_magi < 4 * 15_650
        # Rev. Proc. 2025-25: 9.96% contribution at 300%-400% FPL.
        expected_credit = 12_000 - 0.0996 * expected_magi
        assert hc.aca_credit == pytest.approx(expected_credit)
        assert hc.aca_reconciliation == pytest.approx(
            expected_credit - hc.aca_credit_advanced,
        )
        # Net worth also includes any unsettled tax/PTC receivable or debt.
        assert snap.net_worth == pytest.approx(
            opening + 24_000 - 45_000 - snap.taxes - (12_000 - expected_credit),
            abs=0.02,
        )
        opening = snap.net_worth
        prior_magi = expected_magi


def test_next_aca_estimate_uses_prior_year_social_security_not_current_year():
    p = social_security_plan()
    p.income_streams[0].growth_rate = 0.10
    first, second = run_simulation(p).yearly_snapshots
    first_withdrawals = sum(flow.amount for flow in first.cash_flow.drawdowns)
    assert second.healthcare.aca_magi_estimate == pytest.approx(
        first_withdrawals + 24_000,
    )


def test_aca_final_income_includes_year_to_date_social_security_once():
    snap = run_simulation(social_security_plan(
        first_year_fraction=0.5,
        tax_settings={"year_to_date": {
            "tax_year": 2026, "gross_income": 20_000,
            "social_security_income": 12_000,
        }},
    )).yearly_snapshots[0]
    withdrawals = sum(flow.amount for flow in snap.cash_flow.drawdowns)
    assert snap.healthcare.aca_magi == pytest.approx(withdrawals + 20_000 + 24_000)


def test_aca_recomputes_social_security_split_after_roth_conversion():
    p = social_security_plan(
        accounts={
            "ira": AccountInfo(500_000, "traditional_ira"),
            "roth": AccountInfo(0, "roth_ira"),
            "cash": AccountInfo(100_000, "checking"),
        },
        drawdown_order=[DrawdownEntryData(1, "cash")],
        priorities=[PriorityData(
            1, target_account_id="roth", source_account_id="ira",
            priority_type="roth_conversion", max_annual_amount=30_000,
        )],
    )
    snap = run_simulation(p).yearly_snapshots[0]
    assert snap.accounts["roth"] == 30_000
    # Cash withdrawals are not taxable; conversion plus all SS is PTC MAGI.
    assert snap.healthcare.aca_magi == 54_000
    assert snap.healthcare.aca_credit == pytest.approx(12_000 - .0996 * 54_000)

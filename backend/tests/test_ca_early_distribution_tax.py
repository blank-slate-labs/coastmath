"""California's 2.5% additional tax on early distributions.

R&TC 17085(c); FTB 3805P line 4 ("Multiply line 3 by 2½% (.025)"): the part
of a pre-59½ qualified-plan or IRA distribution included in income, with the
federal IRC 72(t) exceptions, is taxed 2.5% on top of the federal 10%.
https://www.ftb.ca.gov/forms/2024/2024-3805p-instructions.html
"""
import uuid

import pytest

from coastmath.engine.roth import ledger
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    MilestoneData,
    PlanData,
    ResidencyPeriodData,
    SimState,
)
from coastmath.engine.waterfall import early_withdrawal_penalty_rate, execute_drawdown

CA_ALL_YEAR = ((0.0, 12.0, 0.025),)


def _first_year(state_code="CA", **overrides):
    values = dict(
        plan_id=str(uuid.uuid4()), birth_year=1976, birth_month=1, filing_status="single",
        life_expectancy=52, start_year=2026, state_code=state_code,
        expenses=[ExpenseData(id="e", name="Living", annual_amount=60_000, inflation_linked=False)],
        drawdown_order=[DrawdownEntryData(rank=1, source_account_id="ira")],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0,
                                   stock_dividend_yield=0.0, cash_yield_rate=0.0),
        accounts={"ira": AccountInfo(balance=1_000_000, account_type="traditional_ira")},
    )
    values.update(overrides)
    row = run_simulation(PlanData(**values)).yearly_snapshots[0]
    drawn = sum(d.amount for d in row.cash_flow.drawdowns)
    return row, drawn


@pytest.mark.parametrize(("state_code", "rate"), [("CA", 0.125), ("TX", 0.10)])
def test_age_50_ira_draw_pays_federal_10_plus_california_2_5(state_code, rate):
    row, drawn = _first_year(state_code)
    assert drawn > 0
    assert row.cash_flow.early_withdrawal_penalty == pytest.approx(rate * drawn, abs=0.01)


def test_california_draw_grosses_up_for_the_additional_tax():
    # Before the fix CA drew $80,200.98 with an $8,020.10 (10%) penalty.
    _, ca_drawn = _first_year("CA")
    assert ca_drawn > 80_200.98 + 2_005


def test_flat_mode_blended_rate_replaces_state_additional_tax():
    row, drawn = _first_year("CA", tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0.2})
    assert row.cash_flow.early_withdrawal_penalty == pytest.approx(0.10 * drawn, abs=0.01)


def test_move_out_of_california_charges_only_resident_months():
    # Resident January-March (move effective April 1): 3/12 of an all-early year.
    row, drawn = _first_year(
        "CA",
        milestones=[MilestoneData("move", "Move", "date", trigger_date="2026-04-01")],
        residency_periods=[ResidencyPeriodData("CA", end_milestone_id="move", rank=0),
                           ResidencyPeriodData("NV", start_milestone_id="move", rank=1)],
    )
    assert row.cash_flow.early_withdrawal_penalty == pytest.approx(
        (0.10 + 0.025 * 3 / 12) * drawn, abs=0.01)


def test_rate_counts_only_months_both_early_and_resident():
    # Born January 1967: 59 in 2026, reaches 59.5 in July, so January-June is
    # early. CA resident January-March: 10% x 6/12 + 2.5% x 3/12 = 5.625%.
    assert early_withdrawal_penalty_rate(59, 1, 1.0, ((0.0, 3.0, 0.025),)) == pytest.approx(0.05625)
    # Resident July-December: no early months overlap the residency.
    assert early_withdrawal_penalty_rate(59, 1, 1.0, ((6.0, 12.0, 0.025),)) == pytest.approx(0.05)
    assert early_withdrawal_penalty_rate(50, 1, 1.0, CA_ALL_YEAR) == pytest.approx(0.125)
    assert early_withdrawal_penalty_rate(60, 1, 1.0, CA_ALL_YEAR) == 0.0


def test_execute_drawdown_grosses_up_net_need_by_12_5_percent():
    state = SimState(2026, {"ira": AccountInfo(500_000, "traditional_ira")},
                     early_distribution_state_rates=CA_ALL_YEAR)
    withdrawals, penalty = execute_drawdown(
        87_500, [DrawdownEntryData(1, "ira")], state, age=50, birth_month=1)
    # 87,500 / (1 - 0.125) = 100,000; 12.5% of it is 12,500.
    assert withdrawals["ira"] == pytest.approx(100_000)
    assert penalty == pytest.approx(12_500)


def test_early_roth_earnings_pay_california_additional_tax():
    roth = AccountInfo(20_000, "roth_ira", roth_settings={
        "contribution_basis": 0, "first_contribution_year": 2010, "conversions": []})
    state = SimState(2026, {"roth": roth}, early_distribution_state_rates=CA_ALL_YEAR)
    withdrawals, penalty = execute_drawdown(
        8_750, [DrawdownEntryData(1, "roth")], state, age=46, birth_month=1)
    # All earnings: 8,750 / 0.875 = 10,000 includible, 12.5% = 1,250.
    assert withdrawals["roth"] == pytest.approx(10_000)
    assert penalty == pytest.approx(1_250)
    assert ledger(state).totals() == pytest.approx((10_000, 1_250))

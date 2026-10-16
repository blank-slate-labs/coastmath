"""Refunds use final conversion income, without provisional brokerage roundtrips.

Independent 2026 arithmetic: single standard deduction $16,100, ordinary
12% bracket tax .12*conversion - $2,180, and 400%-FPL ACA contribution
$62,600*.0996. Brokerage sales realize 40% with zero returns/dividends.
"""
from dataclasses import replace

import pytest

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
from tests.engine_support import roth_converted


def _plan(**changes):
    rule = PriorityData(1, priority_type="roth_conversion", source_account_id="ira",
        target_account_id="roth", conversion_mode="fill_bracket",
        bracket_ceiling_rate=.12, magi_cap=62_600)
    values = dict(plan_id="00000000-0000-0000-0000-000000000001",
        birth_year=1976, birth_month=2, start_year=2026, life_expectancy=51,
        filing_status="single", state_code="FL",
        accounts={"ira": AccountInfo(720_000, "traditional_ira"),
            "roth": AccountInfo(120_000, "roth_ira"),
            "broker": AccountInfo(360_000, "taxable_brokerage", cost_basis=216_000)},
        priorities=[rule, PriorityData(2, target_account_id="broker", allocation_mode="remaining")],
        drawdown_order=[DrawdownEntryData(1, "broker"), DrawdownEntryData(2, "roth"),
            DrawdownEntryData(3, "ira")],
        expenses=[ExpenseData("living", "Living", 60_000)],
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0,
            bond_return_rate=0, stock_dividend_yield=0),
        tax_settings={"cash_flow_frequency": "monthly"},
        healthcare_settings={"enabled": True, "aca_enabled": True,
            "medicare_enabled": False, "aca_benchmark_premium_annual": 11_460,
            "aca_plan_premium_annual": 11_460, "magi_prior_year": 40_000,
            "aca_advance_credit_fraction": 1, "aca_apply_age_curve": False})
    values.update(changes)
    return PlanData(**values)


def _assert_cash_identity(row, external_income=0):
    reconciliation = row.healthcare.aca_reconciliation if row.healthcare else 0
    assert row.net_worth == pytest.approx(1_200_000 + external_income
        + row.investment_growth - row.expenses - row.taxes + reconciliation, abs=.006)


@pytest.mark.parametrize("fraction", [1, .5])
def test_target_uses_final_aca_cash_cost_without_a_provisional_refund_or_bill(fraction):
    row = run_simulation(_plan(first_year_fraction=fraction)).yearly_snapshots[0]
    # C + .4*(fraction*(60000 + 11460 - 5225.04) + (.12*C - 2180)) = 62600.
    conversion = (62_600 - .4*(fraction*66_234.96 - 2_180)) / 1.048
    tax = .12*conversion - 2_180
    cash_cost = fraction*66_234.96 + tax
    assert roth_converted(row) == pytest.approx(conversion, abs=.002)
    assert row.healthcare.aca_magi == pytest.approx(62_600, abs=.002)
    assert row.healthcare.aca_credit == pytest.approx(fraction*5_225.04, abs=.002)
    assert row.federal_tax == pytest.approx(tax, abs=.002)
    assert sum(c.amount for c in row.cash_flow.contributions) == 0
    assert sum(d.amount for d in row.cash_flow.drawdowns) == pytest.approx(cash_cost, abs=.006)
    assert row.net_worth == pytest.approx(1_200_000 - cash_cost, abs=.006)
    _assert_cash_identity(row)


def test_ranked_targets_do_not_release_an_aca_refund_before_later_conversion():
    plan = _plan()
    first = replace(plan.priorities[0], conversion_mode="fixed", bracket_ceiling_rate=None,
        max_annual_amount=10_000, magi_cap=40_000)
    second = replace(plan.priorities[0], priority_rank=2)
    plan.priorities = [first, second, replace(plan.priorities[-1], priority_rank=3)]
    row = run_simulation(plan).yearly_snapshots[0]
    assert row.transfers[0].amount == 10_000
    assert roth_converted(row) == pytest.approx(36_978.016 / 1.048, abs=.002)
    assert sum(c.amount for c in row.cash_flow.contributions) == 0
    assert row.healthcare.aca_magi == pytest.approx(62_600, abs=.002)
    _assert_cash_identity(row)


def test_genuine_final_aca_refund_is_allocated_and_preserves_realized_sales():
    plan = _plan()
    plan.healthcare_settings["aca_advance_credit_fraction"] = 0
    row = run_simulation(plan).yearly_snapshots[0]
    # The full premium is paid before the final credit: sell $71,460,
    # realize $28,584, convert $34,016; tax $1,901.92, final refund $3,323.12.
    assert roth_converted(row) == pytest.approx(34_016, abs=.002)
    assert row.federal_tax == pytest.approx(1_901.92, abs=.002)
    assert row.healthcare.aca_credit == pytest.approx(5_225.04, abs=.002)
    assert sum(d.amount for d in row.cash_flow.drawdowns) == pytest.approx(71_460, abs=.006)
    assert sum(c.amount for c in row.cash_flow.contributions) == pytest.approx(3_323.12, abs=.006)
    assert row.net_worth == pytest.approx(1_131_863.12, abs=.006)
    _assert_cash_identity(row)


def test_initial_withholding_refund_waits_for_final_conversion_liability():
    plan = _plan(healthcare_settings=None, expenses=[],
        income_streams=[IncomeData("wage", "Wage", 50_000, growth_rate=0,
            withholding_percent=.2)])
    plan.priorities[0] = replace(plan.priorities[0], magi_cap=66_500)
    row = run_simulation(plan).yearly_snapshots[0]
    # $50k wage + $16.5k conversion - $16.1k deduction fills 12%.
    # Federal $5,800 + FICA $3,825; $10k withheld leaves a real $375 refund.
    assert roth_converted(row) == pytest.approx(16_500, abs=.002)
    assert row.federal_tax == pytest.approx(5_800, abs=.002)
    assert row.fica_tax == pytest.approx(3_825, abs=.002)
    assert row.cash_flow.tax_delta == pytest.approx(375, abs=.002)
    assert not row.cash_flow.drawdowns
    assert sum(c.amount for c in row.cash_flow.contributions) == pytest.approx(40_375, abs=.006)
    _assert_cash_identity(row, external_income=50_000)


def test_later_uncapped_fixed_rule_retains_its_explicit_override():
    plan = _plan()
    later = replace(plan.priorities[0], priority_rank=2, conversion_mode="fixed",
        bracket_ceiling_rate=None, magi_cap=None, max_annual_amount=5_000)
    plan.priorities = [plan.priorities[0], later, replace(plan.priorities[-1], priority_rank=3)]
    row = run_simulation(plan).yearly_snapshots[0]
    assert row.transfers[-1].amount == 5_000
    assert row.healthcare.aca_magi > 62_600
    _assert_cash_identity(row)


@pytest.mark.parametrize("inactive", ["milestone", "empty_source"])
def test_inactive_last_rule_does_not_hide_final_aca_cost_from_an_active_cap(inactive):
    plan = _plan()
    later = replace(plan.priorities[0], priority_rank=2)
    if inactive == "milestone":
        plan.milestones = [MilestoneData("later", "Later", "age", trigger_value=80)]
        later = replace(later, start_milestone_id="later")
    else:
        plan.accounts["empty"] = AccountInfo(0, "traditional_ira")
        later = replace(later, source_account_id="empty")
    plan.priorities = [plan.priorities[0], later, replace(plan.priorities[-1], priority_rank=3)]
    row = run_simulation(plan).yearly_snapshots[0]
    assert roth_converted(row) == pytest.approx(36_978.016 / 1.048, abs=.002)
    assert row.healthcare.aca_magi == pytest.approx(62_600, abs=.002)
    assert sum(c.amount for c in row.cash_flow.contributions) == 0
    _assert_cash_identity(row)


def test_unfunded_tax_estimate_refreshes_after_mortgage_itemization():
    plan = _plan(healthcare_settings=None,
        income_streams=[IncomeData("wage", "Wage", 50_000, growth_rate=0)],
        expenses=[ExpenseData("living", "Living", 30_000)],
        real_assets=[RealAssetData("home", "Home", 400_000,
            annual_appreciation_rate=0, is_primary_residence=True)],
        liabilities=[LiabilityData("loan", "Mortgage", 400_000,
            .10, monthly_payment=40_000/12, linked_asset_id="home")])
    plan.priorities[0] = replace(plan.priorities[0], magi_cap=60_000)
    row = run_simulation(plan).yearly_snapshots[0]
    # Mortgage itemization reduces ordinary tax to 1000 + .1*C. FICA is
    # 3825; the $40k interest-only payment leaves brokerage sale24825+.1*C.
    # C + .4*(24825 + .1*C) = 10000 => C =70/1.04.
    conversion = 70/1.04
    assert roth_converted(row) == pytest.approx(conversion, abs=.002)
    assert row.federal_tax == pytest.approx(1_000 + .1*conversion, abs=.002)
    assert row.fica_tax == 3_825
    assert row.capital_gains_tax == 0
    assert sum(d.amount for d in row.cash_flow.drawdowns) == pytest.approx(24_825 + .1*conversion, abs=.006)
    assert sum(c.amount for c in row.cash_flow.contributions) == 0
    assert row.net_worth == pytest.approx(1_175_168.26923077, abs=.006)
    _assert_cash_identity(row, external_income=50_000)

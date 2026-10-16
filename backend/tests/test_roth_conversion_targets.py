"""Conversion targets include deductions and the final cost of funding taxes.

The independent 2026 single-filer examples use IRS Rev. Proc. 2025-32:
$16,100 standard deduction and $50,400 top of the 12% ordinary bracket.
ACA MAGI includes nontaxable Social Security (IRS Form 8962 instructions).
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
    PlanData,
    PriorityData,
)
from coastmath.engine.waterfall import ConversionTaxContext, bracket_fill_headroom
from tests.engine_support import roth_converted


def _rule(**changes):
    return PriorityData(1, priority_type="roth_conversion", source_account_id="ira",
        target_account_id="roth", conversion_mode="fill_bracket",
        bracket_ceiling_rate=.12, **changes)


def _plan(**changes):
    options = dict(plan_id="00000000-0000-0000-0000-000000000001", birth_year=1966, start_year=2026,
        life_expectancy=61, filing_status="single", state_code="FL",
        accounts={"ira": AccountInfo(720_000, "traditional_ira"),
            "roth": AccountInfo(120_000, "roth_ira"),
            "broker": AccountInfo(360_000, "taxable_brokerage", cost_basis=216_000)},
        priorities=[_rule()], drawdown_order=[DrawdownEntryData(1, "broker"),
            DrawdownEntryData(2, "ira"), DrawdownEntryData(3, "roth")],
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0,
            bond_return_rate=0, stock_dividend_yield=0),
        tax_settings={"cash_flow_frequency": "annual"})
    options.update(changes)
    return PlanData(**options)


def test_fill_bracket_uses_unused_standard_deduction():
    p = _plan(accounts={"ira": AccountInfo(100_000, "traditional_ira"),
        "roth": AccountInfo(0, "roth_ira"), "broker": AccountInfo(100_000,
        "taxable_brokerage", cost_basis=100_000)})
    row = run_simulation(p).yearly_snapshots[0]
    assert roth_converted(row) == pytest.approx(66_500, abs=.01)
    assert row.federal_tax == pytest.approx(5_800, abs=.01)
    assert row.net_worth == pytest.approx(194_200, abs=.01)


def test_fill_bracket_reserves_ordinary_income_from_tax_funding():
    p = _plan(accounts={"ira": AccountInfo(100_000, "traditional_ira"),
        "roth": AccountInfo(0, "roth_ira")}, drawdown_order=[DrawdownEntryData(1, "ira")])
    row = run_simulation(p).yearly_snapshots[0]
    assert roth_converted(row) == pytest.approx(60_700, abs=.02)
    assert row.federal_tax == pytest.approx(5_800, abs=.01)
    assert row.net_worth == pytest.approx(94_200, abs=.01)


def test_magi_cap_includes_spending_gains_and_tax_funding():
    p = _plan(priorities=[_rule(magi_cap=62_000)],
        expenses=[ExpenseData("living", "Living", 60_000)])
    row = run_simulation(p).yearly_snapshots[0]
    # Gains are 40% of cash sold: x + .4*(60000 + (.12*x-2180)) = 62000.
    conversion = (62_000 - 23_128) / 1.048
    expected_tax = .12 * conversion - 2_180
    assert roth_converted(row) == pytest.approx(conversion, abs=.02)
    assert row.federal_tax == pytest.approx(expected_tax, abs=.01)
    assert row.capital_gains_tax == 0
    assert row.net_worth == pytest.approx(1_200_000 - 60_000 - expected_tax, abs=.02)
    assert row.unfunded_expenses == 0


def test_magi_cap_includes_qualified_dividends():
    p = _plan(priorities=[_rule(magi_cap=50_000)],
        accounts={"ira": AccountInfo(720_000, "traditional_ira"),
            "roth": AccountInfo(0, "roth_ira"), "cash": AccountInfo(100_000, "checking"),
            "broker": AccountInfo(360_000, "taxable_brokerage", cost_basis=360_000)},
        drawdown_order=[DrawdownEntryData(1, "cash")],
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0,
            bond_return_rate=0, stock_dividend_yield=.02))
    row = run_simulation(p).yearly_snapshots[0]
    assert roth_converted(row) == pytest.approx(42_800, abs=.01)
    assert row.federal_tax == pytest.approx(2_956, abs=.01)


def test_aca_cap_adds_back_nontaxable_social_security():
    p = _plan(birth_year=1964, life_expectancy=63,
        accounts={"ira": AccountInfo(100_000, "traditional_ira"),
            "roth": AccountInfo(0, "roth_ira"), "cash": AccountInfo(100_000, "checking")},
        drawdown_order=[DrawdownEntryData(1, "cash")], priorities=[_rule(magi_cap=30_000)],
        income_streams=[IncomeData("ss", "Social Security", 10_000,
            is_social_security=True, growth_rate=0)], healthcare_settings={
                "enabled": True, "aca_enabled": True, "medicare_enabled": False,
                "aca_benchmark_premium_annual": 9_000, "aca_plan_premium_annual": 9_000,
                "magi_prior_year": 30_000, "aca_apply_age_curve": False})
    row = run_simulation(p).yearly_snapshots[0]
    assert roth_converted(row) == pytest.approx(20_000, abs=.01)
    assert row.healthcare.aca_magi == pytest.approx(30_000, abs=.01)
    assert row.healthcare.aca_eligible


def test_aca_cap_survives_credit_clawback_and_cap_inflation():
    p = _plan(birth_year=1976, life_expectancy=52, priorities=[_rule(magi_cap=62_000)],
        expenses=[ExpenseData("living", "Living", 60_000)], healthcare_settings={
            "enabled": True, "aca_enabled": True, "medicare_enabled": False,
            "aca_benchmark_premium_annual": 11_454, "aca_plan_premium_annual": 11_454,
            "magi_prior_year": 40_000, "aca_apply_age_curve": False},
        assumptions=AssumptionData(inflation_rate=.03, stock_growth_rate=0,
            bond_return_rate=0, stock_dividend_yield=0))
    result = run_simulation(p)
    for row in result.yearly_snapshots:
        assert row.healthcare.aca_magi == pytest.approx(62_000 * row.inflation_factor, abs=.03)
        assert row.healthcare.aca_eligible
        assert row.healthcare.aca_credit > 0
    row = result.yearly_snapshots[0]
    assert row.healthcare.aca_credit == pytest.approx(11_454 - 62_000 * .0996, abs=.01)
    assert row.net_worth == pytest.approx(1_200_000 - 60_000
        - row.healthcare.aca_net_premium - row.taxes, abs=.03)


def test_ranked_rules_share_final_magi_room_and_keep_fixed_conversion():
    first = replace(_rule(), conversion_mode="fixed", bracket_ceiling_rate=None,
        max_annual_amount=20_000)
    second = replace(_rule(magi_cap=62_000), priority_rank=2)
    p = _plan(priorities=[first, second], expenses=[ExpenseData("living", "Living", 60_000)])
    row = run_simulation(p).yearly_snapshots[0]
    assert row.transfers[0].amount == 20_000
    assert roth_converted(row) == pytest.approx((62_000 - 23_128) / 1.048, abs=.02)


def test_unavoidable_income_above_cap_does_not_convert_or_lose_cash():
    p = _plan(priorities=[_rule(magi_cap=10_000)],
        expenses=[ExpenseData("living", "Living", 60_000)])
    row = run_simulation(p).yearly_snapshots[0]
    assert not row.transfers
    assert row.net_worth == pytest.approx(1_140_000)


def test_fixed_only_conversion_preserves_amount_and_cash_conservation():
    fixed = replace(_rule(), conversion_mode="fixed", bracket_ceiling_rate=None,
        max_annual_amount=50_000)
    p = _plan(priorities=[fixed], expenses=[ExpenseData("living", "Living", 60_000)])
    row = run_simulation(p).yearly_snapshots[0]
    assert roth_converted(row) == 50_000
    assert row.net_worth == pytest.approx(1_200_000 - 60_000 - row.taxes, abs=.01)


def test_two_ranked_target_rules_share_the_same_final_cap():
    first = _rule(magi_cap=62_000, max_annual_amount=20_000)
    second = replace(_rule(magi_cap=62_000), priority_rank=2)
    p = _plan(priorities=[first, second], expenses=[ExpenseData("living", "Living", 60_000)])
    row = run_simulation(p).yearly_snapshots[0]
    assert row.transfers[0].amount == 20_000
    assert roth_converted(row) == pytest.approx((62_000 - 23_128) / 1.048, abs=.02)
    assert row.net_worth == pytest.approx(1_200_000 - 60_000 - row.taxes, abs=.02)


def test_delayed_settlement_preserves_liability_and_does_not_prefund_future_tax():
    p = _plan(accounts={"ira": AccountInfo(100_000, "traditional_ira"),
        "roth": AccountInfo(0, "roth_ira"), "broker": AccountInfo(100_000,
        "taxable_brokerage", cost_basis=100_000)},
        tax_settings={"settlement_lag_years": 1, "cash_flow_frequency": "annual"})
    row = run_simulation(p).yearly_snapshots[0]
    assert roth_converted(row) == pytest.approx(66_500, abs=.01)
    assert row.federal_tax == pytest.approx(5_800, abs=.01)
    assert row.tax_balance == pytest.approx(5_800, abs=.01)
    assert row.accounts["broker"] == 100_000
    assert row.net_worth == pytest.approx(194_200, abs=.01)


def test_fill_bracket_includes_qbi_deduction_that_grows_with_conversion():
    p = _plan(accounts={"ira": AccountInfo(100_000, "traditional_ira"),
        "roth": AccountInfo(0, "roth_ira"), "cash": AccountInfo(100_000, "checking")},
        drawdown_order=[DrawdownEntryData(1, "cash")],
        income_streams=[IncomeData("business", "Business", 50_000,
            tax_category="self_employment", growth_rate=0)])
    row = run_simulation(p).yearly_snapshots[0]
    # SE deduction = 50000*.9235*.153/2 = 3532.3875.
    # Final QBI deduction = (50000-3532.3875)*.2 = 9293.5225,
    # versus a taxable-income-limited 6073.5225 before conversion.
    conversion = 50_400 - (50_000 - 3_532.3875 - 16_100 - 9_293.5225)
    assert roth_converted(row) == pytest.approx(conversion, abs=.01)
    assert row.federal_tax == pytest.approx(5_800, abs=.01)
    assert row.fica_tax == pytest.approx(7_064.775, abs=.01)
    assert row.net_worth == pytest.approx(250_000 - row.taxes, abs=.01)


def test_waterfall_bracket_room_retains_unused_deduction():
    context = ConversionTaxContext(ordinary_taxable_income=0, modified_agi=0,
        brackets=[(50_400, .12)], unused_deduction=16_100)
    assert bracket_fill_headroom(context, .12) == 66_500

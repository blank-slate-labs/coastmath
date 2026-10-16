"""Integrated examples: the tax engine with the statutory state deduction rules.

Statutory amounts are the rules module's versioned data (its own tests check
them against the published forms). These examples check the engine's side:
each result component reaches the state base in the right place, using the
engine's own bracket tables for the remaining arithmetic.
"""
import pytest

from coastmath.engine import state_deduction_rules as rules
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import _state_tax_details, calculate
from coastmath.engine.types import AccountInfo, AssumptionData, IncomeData, PlanData

ON = {"state_deduction_rules": True}


def wages(amount, **changes):
    return dict(gross_income=amount, deductions=0.0, filing_status="single", tax_year=2026,
                earned_income=amount, holder_age=45, **changes)


def bracket_tax(state, taxable, legacy_deduction):
    """The engine's bracket tax on ``taxable`` (legacy path adds its deduction back)."""
    return _state_tax_details(taxable + legacy_deduction, state, tax_year=2026).tax


def test_connecticut_personal_exemption_phases_out_on_agi():
    # 2025 CT single exemption $15,000, reduced $1,000 per $1,000 above $30,000.
    # CT AGI $40,000 is below the add-back and recapture tables; Table E
    # gives a .10 personal credit on the tax.
    off = calculate(**wages(40_000.0), state_code="CT")
    on = calculate(**wages(40_000.0), state_code="CT", settings=ON)
    assert off.state == pytest.approx(bracket_tax("CT", 40_000, 0))
    assert bracket_tax("CT", 35_000, 0) == pytest.approx(1_325)  # 2% x 10,000 + 4.5% x 25,000
    assert on.state == pytest.approx(1_325 * .90)
    assert on.state_deduction_coverage == "supported"


def test_alabama_subtracts_federal_income_tax_liability_and_phases_its_standard_deduction():
    on = calculate(**wages(80_000.0), state_code="AL", settings=ON)
    liability = on.federal + on.capital_gains_tax
    assert on.state_federal_tax_subtraction == pytest.approx(liability, abs=1)
    # The standard deduction phases to its $2,500 floor at this income
    # ($3,000 less $25 per $500 above $26,000). Alabama itemized deductions
    # include employee Social Security and Medicare tax, which is larger
    # here, so the household itemizes. $1,500 personal exemption.
    deduction = max(2_500, on.fica_tax)
    expected = bracket_tax("AL", 80_000 - deduction - 1_500 - on.state_federal_tax_subtraction, 3_000)
    assert on.state == pytest.approx(expected, abs=.05)


def test_missouri_federal_tax_deduction_uses_its_income_percentage():
    on = calculate(**wages(60_000.0), state_code="MO", settings=ON)
    liability = on.federal + on.capital_gains_tax
    # MO AGI of $50,001-$100,000 deducts 15% of federal liability, capped at $5,000.
    assert on.state_federal_tax_subtraction == pytest.approx(min(.15 * liability, 5_000), abs=1)
    off = calculate(**wages(60_000.0), state_code="MO")
    assert on.state < off.state


@pytest.mark.parametrize("state", ["OR", "WI"])
def test_supported_states_report_coverage_and_keep_tax_nonnegative(state):
    for amount in (15_000.0, 70_000.0, 400_000.0):
        on = calculate(**wages(amount), state_code=state, settings=ON)
        assert on.state_deduction_coverage == "supported"
        assert on.state >= 0
        assert on.state_federal_tax_subtraction <= on.federal + on.capital_gains_tax + on.niit + 1


@pytest.mark.parametrize("state", ["CA", "OH", "IA", "LA", "SC", "TX"])
def test_legacy_unverified_and_repealed_states_are_unchanged(state):
    off = calculate(**wages(90_000.0), state_code=state)
    on = calculate(**wages(90_000.0), state_code=state, settings=ON)
    assert on.state == off.state and on.state_federal_tax_subtraction == 0
    assert on.state_deduction_coverage == rules.state_rule_coverage(state) != "supported"


@pytest.mark.parametrize("state", ["AL", "MO", "OR", "CT", "WI"])
def test_supported_states_without_the_flag_keep_the_existing_calculation(state):
    assert calculate(**wages(90_000.0), state_code=state) == calculate(
        **wages(90_000.0), state_code=state, settings={"state_deduction_rules": False})


def test_projection_converges_the_federal_and_state_deduction_feedback():
    plan = dict(plan_id="00000000-0000-0000-0000-0000000000c1", birth_year=1970, start_year=2026,
                life_expectancy=58, filing_status="single", state_code="AL",
                income_streams=[IncomeData("w", "Wages", 250_000, growth_rate=0.0, withholding_percent=.3)],
                accounts={"cash": AccountInfo(10_000, "checking")},
                assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
                                           stock_dividend_yield=0))
    off = run_simulation(PlanData(**plan, tax_settings={"cash_flow_frequency": "annual"})).yearly_snapshots[0]
    on_result = run_simulation(PlanData(**plan, tax_settings={"cash_flow_frequency": "annual", **ON}))
    on = on_result.yearly_snapshots[0]
    assert on.state_tax < off.state_tax
    # The federal return then deducts less state tax: federal tax rises
    # by less than the state saving (both itemized and standard cases).
    assert on.federal_tax >= off.federal_tax - .01
    assert on.taxes < off.taxes

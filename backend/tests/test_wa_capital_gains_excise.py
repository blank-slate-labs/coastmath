"""Washington capital gains excise (RCW 82.87).

7% of Washington capital gains above the standard deduction ($278,000, the
latest published amount, used for 2026), plus 2.9% of the part above
$1,000,000. Spouses share one deduction. Real estate is excluded.
"""

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import calculate, state_capital_gains_excise
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    PlanData,
    RealAssetData,
)


@pytest.mark.parametrize(("gains", "expected"), [
    (0, 0.0),
    (278_000, 0.0),
    (500_000, 0.07 * 222_000),
    # $1,500,000 - $278,000 = $1,222,000: 7% of all of it plus 2.9% of $222,000.
    (1_500_000, 0.07 * 1_222_000 + 0.029 * 222_000),
])
def test_excise_tiers(gains, expected):
    assert state_capital_gains_excise("WA", gains) == pytest.approx(expected)


def test_no_excise_outside_washington():
    assert state_capital_gains_excise("OR", 2_000_000) == 0.0
    assert state_capital_gains_excise(None, 2_000_000) == 0.0


def test_deduction_is_indexed_but_the_million_dollar_tier_is_not():
    assert state_capital_gains_excise("WA", 556_000, inflation_factor=2.0) == 0.0
    # Deduction $556,000: taxable $1,444,000; the 2.9% tier starts at $1,000,000.
    assert state_capital_gains_excise("WA", 2_000_000, inflation_factor=2.0) == pytest.approx(
        0.07 * 1_444_000 + 0.029 * 444_000)


@pytest.mark.parametrize("status", ["single", "married_filing_jointly", "married_filing_separately"])
def test_excise_is_part_of_state_tax_with_one_shared_deduction(status):
    result = calculate(gross_income=50_000, deductions=0, filing_status=status,
                       state_code="WA", capital_gains=500_000)
    assert result.state_capital_gains_excise == pytest.approx(15_540)
    assert result.state == pytest.approx(15_540)
    assert result.total_tax == pytest.approx(result.federal + result.capital_gains_tax + result.state
                                             + result.fica_tax + result.niit + result.local)


def test_real_estate_gains_are_excluded():
    result = calculate(gross_income=0, deductions=0, filing_status="single", state_code="WA",
                       capital_gains=900_000, real_estate_capital_gains=600_000)
    assert result.state_capital_gains_excise == pytest.approx(0.07 * 22_000)
    # A real estate loss is excluded too, so it cannot offset stock gains.
    loss = calculate(gross_income=0, deductions=0, filing_status="single", state_code="WA",
                     capital_gains=300_000, real_estate_capital_gains=-200_000)
    assert loss.state_capital_gains_excise == pytest.approx(0.07 * 222_000)


def test_custom_state_brackets_skip_the_excise():
    result = calculate(gross_income=0, deductions=0, filing_status="single", state_code="WA",
                       capital_gains=900_000, settings={"state_brackets": [[999_999_999, 0.0]]})
    assert result.state_capital_gains_excise == 0.0


def _plan(**kwargs):
    return PlanData(
        plan_id="00000000-0000-0000-0000-0000000000a1", birth_year=1970, birth_month=1,
        filing_status="single", life_expectancy=57, start_year=2026, state_code="WA",
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        drawdown_order=[DrawdownEntryData(1, "brk")], **kwargs)


def test_simulated_property_sale_owes_no_excise():
    plan = _plan(
        accounts={"brk": AccountInfo(balance=10_000, account_type="taxable_brokerage", cost_basis=10_000)},
        real_assets=[RealAssetData(id="rental", name="Rental", current_value=1_000_000, sale_year=2026,
                                   annual_appreciation_rate=0.0, adjusted_basis=200_000,
                                   tax_treatment="investment")],
    )
    snapshot = run_simulation(plan).yearly_snapshots[0]
    assert snapshot.capital_gains_tax > 0
    assert snapshot.state_capital_gains_excise == 0.0


def test_simulated_brokerage_sale_owes_excise():
    plan = _plan(accounts={"brk": AccountInfo(balance=2_000_000, account_type="taxable_brokerage",
                                              cost_basis=0)})
    plan.expenses = [ExpenseData(id="e", name="Big purchase", annual_amount=600_000, inflation_linked=False)]
    snapshot = run_simulation(plan).yearly_snapshots[0]
    assert snapshot.state_capital_gains_excise > 0
    assert snapshot.state_tax == pytest.approx(snapshot.state_capital_gains_excise)

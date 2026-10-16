"""New Jersey NJ-1040 Tax Rate Schedules, "2020 and after".

https://www.nj.gov/treasury/taxation/pdf/current/njtaxratesch.pdf
Table A: single and married filing separately. Table B: married filing
jointly, head of household and qualifying widow(er). Table B is its own
schedule, not Table A doubled. Expected values use the published
"multiply and subtract" form; NJ has no standard deduction in the data.
"""

import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    ExpenseData,
    IncomeData,
    PlanData,
)


@pytest.mark.parametrize("status,income,expected", [
    # Table B
    ("married_filing_jointly", 60_000, 60_000 * .0245 - 420),           # 1,050.00
    ("married_filing_jointly", 300_000, 300_000 * .0637 - 4_042.50),    # 15,067.50
    ("married_filing_jointly", 1_000_000, 1_000_000 * .0897 - 17_042.50),  # 72,657.50
    ("married_filing_jointly", 1_500_000, 1_500_000 * .1075 - 34_842.50),  # 126,407.50
    ("head_of_household", 100_000, 100_000 * .05525 - 2_775),           # 2,750.00
    # Table A
    ("single", 100_000, 100_000 * .0637 - 2_126.25),                    # 4,243.75
    ("married_filing_separately", 600_000, 600_000 * .0897 - 15_126.25),  # 38,693.75
])
def test_nj_rate_schedule_by_filing_status(status, income, expected):
    result = calculate(gross_income=income, deductions=0, filing_status=status,
                       state_code="NJ", tax_year=2026)
    assert result.state == pytest.approx(expected)


def test_custom_brackets_keep_joint_doubling_convention():
    custom = [{"min": 0, "max": 10_000, "rate": .01}, {"min": 10_000, "max": 999_999_999, "rate": .05}]
    tax, _ = _state_tax_and_taxable_income(
        30_000, "NJ", custom_brackets=custom, filing_status="married_filing_jointly")
    assert tax == pytest.approx(20_000 * .01 + 10_000 * .05)


def test_simulation_applies_nj_joint_schedule():
    plan = PlanData(
        plan_id=str(uuid.uuid4()), birth_year=1966, filing_status="married_filing_jointly",
        life_expectancy=90, start_year=2026, spouse_birth_year=1966, spouse_life_expectancy=90,
        state_code="NJ",
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        income_streams=[IncomeData(id="i", name="Pension", annual_amount=1_000_000,
                                   is_earned_income=False, tax_category="qualified_pension",
                                   growth_rate=0.0)],
        expenses=[ExpenseData(id="e", name="Living", annual_amount=100_000, inflation_linked=False)],
        accounts={"chk": AccountInfo(balance=0, account_type="checking")},
    )
    snapshot = run_simulation(plan).yearly_snapshots[0]
    assert snapshot.state_tax == pytest.approx(1_000_000 * .0897 - 17_042.50)

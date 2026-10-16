"""Minnesota 2026 income tax schedules by filing status.

MN DOR press release 2025-12-16 (Minn. Stat. 290.06 subd. 2c indexing):
https://www.revenue.state.mn.us/press-release/2025-12-16/minnesota-income-tax-brackets-standard-deduction-and-dependent-exemption
Rates 5.35% / 6.80% / 7.85% / 9.85% with separately published thresholds:
  single  33,310 / 109,430 / 203,150   standard deduction 15,300
  MFJ     48,700 / 193,480 / 337,930   standard deduction 30,600
  MFS     24,350 /  96,740 / 168,965   standard deduction 15,300
  HoH     41,010 / 164,800 / 270,060   standard deduction 23,000
The joint and head-of-household schedules are not the single one doubled.
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


@pytest.mark.parametrize("status,gross,expected_taxable,expected", [
    # MFJ taxable 150,000: 48,700 x .0535 + 101,300 x .068
    ("married_filing_jointly", 180_600, 150_000, 2_605.45 + 6_888.40),
    # MFJ taxable 400,000: + 144,780 x .068 + 144,450 x .0785 + 62,070 x .0985
    ("married_filing_jointly", 430_600, 400_000, 2_605.45 + 9_845.04 + 11_339.325 + 6_113.895),
    # HoH taxable 100,000 (23,000 deduction): 41,010 x .0535 + 58,990 x .068
    ("head_of_household", 123_000, 100_000, 2_194.035 + 4_011.32),
    # MFS taxable 100,000: 24,350 x .0535 + 72,390 x .068 + 3,260 x .0785
    ("married_filing_separately", 115_300, 100_000, 1_302.725 + 4_922.52 + 255.91),
    # Single unchanged, taxable 100,000: 33,310 x .0535 + 66,690 x .068
    ("single", 115_300, 100_000, 1_782.085 + 4_534.92),
])
def test_mn_schedule_by_filing_status(status, gross, expected_taxable, expected):
    tax, taxable = _state_tax_and_taxable_income(gross, "MN", filing_status=status)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected)
    result = calculate(gross_income=gross, deductions=0, filing_status=status,
                       state_code="MN", tax_year=2026)
    assert result.state == pytest.approx(expected)


def test_mn_schedule_scales_with_inflation_factor():
    # Every threshold and the HoH deduction scale by 1.1: deduction 25,300,
    # taxable 110,000 = 45,111 x .0535 + 64,889 x .068
    tax, taxable = _state_tax_and_taxable_income(
        135_300, "MN", filing_status="head_of_household", inflation_factor=1.1)
    assert taxable == pytest.approx(110_000)
    assert tax == pytest.approx(45_111 * .0535 + 64_889 * .068)


def test_custom_brackets_ignore_mn_status_schedules():
    custom = [{"min": 0, "max": 10_000, "rate": .01}, {"min": 10_000, "max": 999_999_999, "rate": .05}]
    tax, taxable = _state_tax_and_taxable_income(
        70_600, "MN", custom_brackets=custom, filing_status="married_filing_jointly")
    assert taxable == pytest.approx(40_000)
    assert tax == pytest.approx(20_000 * .01 + 20_000 * .05)


def test_simulation_applies_mn_joint_schedule():
    plan = PlanData(
        plan_id=str(uuid.uuid4()), birth_year=1966, filing_status="married_filing_jointly",
        life_expectancy=90, start_year=2026, spouse_birth_year=1966, spouse_life_expectancy=90,
        state_code="MN",
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        income_streams=[IncomeData(id="i", name="Pension", annual_amount=430_600,
                                   is_earned_income=False, tax_category="qualified_pension",
                                   growth_rate=0.0)],
        expenses=[ExpenseData(id="e", name="Living", annual_amount=100_000, inflation_linked=False)],
        accounts={"chk": AccountInfo(balance=0, account_type="checking")},
    )
    snapshot = run_simulation(plan).yearly_snapshots[0]
    assert snapshot.state_tax == pytest.approx(29_903.71, abs=0.01)

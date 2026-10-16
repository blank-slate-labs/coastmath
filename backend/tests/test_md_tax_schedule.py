"""Maryland income tax schedules by filing status.

2025 Maryland Resident Tax Booklet, "Maryland Tax Computation Worksheet
Schedules" (brackets unchanged for 2026):
https://www.marylandcomptroller.gov/content/dam/mdcomp/tax/instructions/2025/resident-booklet.pdf
Schedule I (single, MFS, dependent): 2% to 1K, 3% to 2K, 4% to 3K, 4.75% to
100K, 5% to 125K, 5.25% to 150K, 5.5% to 250K, 5.75% to 500K, 6.25% to 1M,
6.5% above.
Schedule II (MFJ, head of household, qualifying surviving spouse): the same
low tiers, then 4.75% to 150K, 5% to 175K, 5.25% to 225K, 5.5% to 300K,
5.75% to 600K, 6.25% to 1.2M, 6.5% above. Published base amounts:
150K 7,072.50; 300K 15,072.50; 600K 32,322.50; 1.2M 69,822.50.
Instruction 16 gives MFJ, head of household and qualifying surviving spouse
twice the single standard deduction (6,700 vs 3,350 for 2025; the data
indexes single to 3,400 for 2026, so the joint amount is 6,800).
Schedule II is not Schedule I doubled.
"""

import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate
from coastmath.engine.types import AccountInfo, AssumptionData, IncomeData, PlanData


@pytest.mark.parametrize("status,gross,expected_taxable,expected", [
    # MFJ taxable 150,000: 20 + 30 + 40 + 147,000 x .0475
    ("married_filing_jointly", 156_800, 150_000, 90 + 6_982.50),
    # MFJ taxable 300,000: + 25,000 x .05 + 50,000 x .0525 + 75,000 x .055
    ("married_filing_jointly", 306_800, 300_000, 7_072.50 + 1_250 + 2_625 + 4_125),
    # MFJ taxable 1,200,000: + 300,000 x .0575 + 600,000 x .0625
    ("married_filing_jointly", 1_206_800, 1_200_000, 15_072.50 + 17_250 + 37_500),
    # MFJ taxable 2,000,000: + 800,000 x .065
    ("married_filing_jointly", 2_006_800, 2_000_000, 69_822.50 + 52_000),
    # HoH takes the joint deduction (6,800), taxable 496,600: + 196,600 x .0575
    ("head_of_household", 503_400, 496_600, 15_072.50 + 11_304.50),
    # Single and MFS stay on Schedule I, taxable 500,000:
    # 90 + 97,000 x .0475 + 25,000 x .05 + 25,000 x .0525 + 100,000 x .055
    # + 250,000 x .0575
    ("single", 503_400, 500_000, 90 + 4_607.50 + 1_250 + 1_312.50 + 5_500 + 14_375),
    ("married_filing_separately", 503_400, 500_000, 27_135),
])
def test_md_schedule_by_filing_status(status, gross, expected_taxable, expected):
    tax, taxable = _state_tax_and_taxable_income(gross, "MD", filing_status=status)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected)
    result = calculate(gross_income=gross, deductions=0, filing_status=status,
                       state_code="MD", tax_year=2026)
    assert result.state == pytest.approx(expected)


def test_md_joint_schedule_scales_with_inflation_factor():
    # Thresholds and deduction scale by 1.1: deduction 7,480, low tiers end at
    # 1,100 / 2,200 / 3,300, 4.75% runs to 165,000; taxable 165,000
    tax, taxable = _state_tax_and_taxable_income(
        172_480, "MD", filing_status="married_filing_jointly", inflation_factor=1.1)
    assert taxable == pytest.approx(165_000)
    assert tax == pytest.approx(22 + 33 + 44 + 161_700 * .0475)


def test_simulation_applies_md_joint_schedule():
    plan = PlanData(
        plan_id=str(uuid.uuid4()), birth_year=1960, birth_month=6,
        filing_status="married_filing_jointly", life_expectancy=70, start_year=2026,
        spouse_birth_year=1960, spouse_birth_month=6, spouse_life_expectancy=95,
        state_code="MD",
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        # The holder is 66: Maryland's $41,200 pension exclusion (Tax-General
        # 10-209) applies to their pension, so 1,248,000 - 41,200 - 6,800
        # standard deduction keeps taxable income at the 1.2M base amount.
        income_streams=[IncomeData(id="pen", name="Pension", annual_amount=1_248_000,
                                   growth_rate=0.0, tax_category="qualified_pension")],
        accounts={"chk": AccountInfo(balance=0, account_type="checking")},
    )
    snapshot = run_simulation(plan).yearly_snapshots[0]
    assert snapshot.state_tax == pytest.approx(69_822.50, abs=0.01)

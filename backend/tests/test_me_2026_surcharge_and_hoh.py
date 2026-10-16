"""Maine 2026 uses the revised schedules, deductions and the 2% income tax surcharge.

Maine Revenue Services, *2026 Individual Income Tax Rates*, revised May 20, 2026,
https://www.maine.gov/revenue/sites/maine.gov.revenue/files/2026-05/ind_tax_rate_sched_2026_rev.pdf:
single/MFS 5.8% below $27,400, 6.75% to $64,850, 7.15% above; head of household
$41,100 / $97,300; joint $54,850 / $129,750. Note (1): "the tax calculated above is
increased by a surcharge of 2% on the portion of the taxpayer's Maine taxable income
greater than $1,000,000 if filing single, $750,000 if married filing separate; or
$1,500,000 if married filing jointly or head of household." Standard deduction:
single and MFS $15,700, joint $31,400, head of household $23,550. The $5,300
personal exemption and the deduction/exemption phaseouts remain omitted.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate

# Single/MFS through $64,850: 27,400 x 5.8% (1,589.20) + 37,450 x 6.75% (2,527.875)
_SINGLE_TO_64_850 = 4_117.075
# Joint through $129,750: 54,850 x 5.8% (3,181.30) + 74,900 x 6.75% (5,055.75)
_JOINT_TO_129_750 = 8_237.05
# Head of household through $97,300: 41,100 x 5.8% (2,383.80) + 56,200 x 6.75% (3,793.50)
_HOH_TO_97_300 = 6_177.30


@pytest.mark.parametrize("filing_status, agi, expected_taxable, expected_tax", [
    # 100,000 - 15,700 = 84,300: 4,117.075 + 19,450 x 7.15% (1,390.675) = 5,507.75
    ("single", 100_000, 84_300, _SINGLE_TO_64_850 + 1_390.675),
    # 100,000 - 23,550 = 76,450: 2,383.80 + 35,350 x 6.75% (2,386.125) = 4,769.925
    ("head_of_household", 100_000, 76_450, 2_383.80 + 2_386.125),
    # 2,015,700 - 15,700 = 2,000,000: 4,117.075 + 1,935,150 x 7.15% (138,363.225)
    # + surcharge 2% x 1,000,000 (20,000) = 162,480.30
    ("single", 2_015_700, 2_000_000, _SINGLE_TO_64_850 + 138_363.225 + 20_000),
    # 1,015,700 - 15,700 = 1,000,000: no surcharge at the threshold.
    # 4,117.075 + 935,150 x 7.15% (66,863.225) = 70,980.30
    ("single", 1_015_700, 1_000_000, _SINGLE_TO_64_850 + 66_863.225),
    # 3,031,400 - 31,400 = 3,000,000: 8,237.05 + 2,870,250 x 7.15% (205,222.875)
    # + 2% x 1,500,000 (30,000) = 243,459.925
    ("married_filing_jointly", 3_031_400, 3_000_000, _JOINT_TO_129_750 + 205_222.875 + 30_000),
    # 2,023,550 - 23,550 = 2,000,000: 6,177.30 + 1,902,700 x 7.15% (136,043.05)
    # + 2% x 500,000 (10,000) = 152,220.35
    ("head_of_household", 2_023_550, 2_000_000, _HOH_TO_97_300 + 136_043.05 + 10_000),
    # 1,015,700 - 15,700 = 1,000,000: 4,117.075 + 935,150 x 7.15% (66,863.225)
    # + 2% x 250,000 (5,000) = 75,980.30
    ("married_filing_separately", 1_015_700, 1_000_000, _SINGLE_TO_64_850 + 66_863.225 + 5_000),
])
def test_me_2026_schedules_deductions_and_surcharge(filing_status, agi, expected_taxable,
                                                    expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "ME", filing_status=filing_status,
                                                 tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


def test_me_surcharge_through_calculate():
    result = calculate(2_015_700, 0, "single", state_code="ME", tax_year=2026,
                       earned_income=2_015_700, w2_income=2_015_700, holder_age=50)
    assert result.state == pytest.approx(162_480.30, abs=0.01)

"""New York heads of household use the $11,200 deduction and the HoH schedule.

IT-2105-I (2026), https://www.tax.ny.gov/pdf/2026/inc/it2105i_2026.pdf:
p. 3 standard deduction table: single $8,000, head of household $11,200.
p. 10 head-of-household schedule: 3.90% to $12,800; 4.40% to $17,650; 5.15% to
$20,900; 5.40% to $107,650; 5.90% to $269,300; 6.85% to $1,616,450; 9.65% to
$5,000,000; 10.3% to $25,000,000; 10.9% above. NY taxable income = NYAGI -
standard deduction. NYC's resident tax uses NY taxable income as its base.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate

# Tax through the top of the 5.15% band: 12,800 x 3.9% + 4,850 x 4.4%
# + 3,250 x 5.15% = 499.20 + 213.40 + 167.375 = 879.975
_HOH_TO_20_900 = 879.975


@pytest.mark.parametrize("filing_status, agi, expected_taxable, expected_tax", [
    # 40,000 - 11,200 = 28,800: 879.975 + 7,900 x 5.4% (426.60) = 1,306.575
    ("head_of_household", 40_000, 28_800, 1_306.575),
    # 70,000 - 11,200 = 58,800: 879.975 + 37,900 x 5.4% (2,046.60) = 2,926.575
    ("head_of_household", 70_000, 58_800, 2_926.575),
    # 100,000 - 11,200 = 88,800: 879.975 + 67,900 x 5.4% (3,666.60) = 4,546.575
    ("head_of_household", 100_000, 88_800, 4_546.575),
    # 130,000 - 11,200 = 118,800: + 86,750 x 5.4% (4,684.50)
    # + 11,150 x 5.9% (657.85) = 6,222.325 (recapture not modeled)
    ("head_of_household", 130_000, 118_800, _HOH_TO_20_900 + 4_684.50 + 657.85),
    # Control, single schedule: 70,000 - 8,000 = 62,000: 8,500 x 3.9% (331.50)
    # + 3,200 x 4.4% (140.80) + 2,200 x 5.15% (113.30) + 48,100 x 5.4% (2,597.40)
    ("single", 70_000, 62_000, 3_183.00),
])
def test_ny_2026_head_of_household_schedule(filing_status, agi, expected_taxable, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "NY", filing_status=filing_status,
                                                 tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


def test_ny_head_of_household_through_calculate_with_nyc():
    result = calculate(70_000, 0, "head_of_household", state_code="NY", earned_income=70_000,
                       w2_income=70_000, tax_year=2026, holder_age=40,
                       local_tax={"jurisdiction": "ny_new_york_city"})
    assert result.state == pytest.approx(2_926.575, abs=0.01)
    # NYC HoH schedule on 58,800: 14,400 x 3.078% (443.232) + 15,600 x 3.762%
    # (586.872) + 28,800 x 3.819% (1,099.872) = 2,129.976. School credit rate
    # reduction: 14,400 x 0.171% (24.624) + 44,400 x 0.228% (101.232) = 125.856;
    # fixed school credit 63. 2,129.976 - 125.856 - 63 = 1,941.12
    assert result.local == pytest.approx(1_941.12, abs=0.01)

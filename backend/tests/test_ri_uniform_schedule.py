"""Rhode Island uses one rate schedule for every filing status.

RI Division of Taxation ADV 2025-22
(https://tax.ri.gov/sites/g/files/xkgbur541/files/2025-11/ADV_2025_22_Inflation_Adjustments.pdf),
p. 2: the "uniform tax rate schedule, which is used by all filers". 2026:
3.75% to $82,050; $3,076.88 + 4.75% to $186,450; $8,035.88 + 5.99% above.
P. 1 sets the 2026 standard deduction at $11,200 single/MFS, $22,400 MFJ and
$16,800 head of household. Personal exemptions and the phaseout are not modeled.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income


@pytest.mark.parametrize("filing_status, agi, expected_taxable, expected_tax", [
    # 100,000 - 22,400 = 77,600; 0.0375 x 77,600
    ("married_filing_jointly", 100_000, 77_600, 2_910.00),
    # 177,600: 3,076.88 + 0.0475 x 95,550
    ("married_filing_jointly", 200_000, 177_600, 7_615.505),
    # 277,600: 8,035.88 + 0.0599 x 91,150
    ("married_filing_jointly", 300_000, 277_600, 13_495.765),
    # 100,000 - 11,200 = 88,800: 3,076.88 + 0.0475 x 6,750
    ("single", 100_000, 88_800, 3_397.505),
    ("married_filing_separately", 100_000, 88_800, 3_397.505),
    # 100,000 - 16,800 = 83,200: 3,076.88 + 0.0475 x 1,150
    ("head_of_household", 100_000, 83_200, 3_131.505),
])
def test_ri_2026_uniform_schedule(filing_status, agi, expected_taxable, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "RI", filing_status=filing_status,
                                                 tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    # The published base amounts are rounded to the cent.
    assert tax == pytest.approx(expected_tax, abs=0.01)


def test_ri_future_year_indexing_scales_shared_schedule_once():
    # Deduction 2 x 22,400 = 44,800; taxable 355,200; bounds 164,100 / 372,900:
    # 0.0375 x 164,100 + 0.0475 x 191,100 = 6,153.75 + 9,077.25
    tax, taxable = _state_tax_and_taxable_income(400_000, "RI", filing_status="married_filing_jointly",
                                                 inflation_factor=2, tax_year=2027)
    assert taxable == pytest.approx(355_200)
    assert tax == pytest.approx(15_231.0)

"""Wisconsin taxes joint and separate filers on their own published schedules.

WI DOR "Tax rates" FAQ, https://www.revenue.wi.gov/Pages/FAQS/pcs-taxrates.aspx
(2025, Wis. Stat. 71.06(1q) indexed under 71.06(2e)):
- Single/HoH: 3.5% to $14,680; 4.4% to $50,480; 5.3% to $323,290; 7.65% above.
- MFJ: 3.5% to $19,580; 4.4% to $67,300 ($685.30 base); 5.3% to $431,060
  ($2,784.98 base); 7.65% above ($22,064.26 base).
- MFS: 3.5% to $9,790; 4.4% to $33,650 ($342.65 base); 5.3% to $215,530
  ($1,392.49 base); 7.65% above ($11,032.13 base).
Maximum standard deductions (2025 Form 1 instructions, filing requirement):
$13,560 single, $25,110 MFJ, $11,930 MFS. The sliding-scale phase-down
(Wis. Stat. 71.05(22)) is not modelled; 2026 retains the 2025 values.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate


@pytest.mark.parametrize("tax_year", [2025, 2026])
@pytest.mark.parametrize("filing_status, agi, expected_taxable, expected_tax", [
    # TI 124,890: 2,784.98 + (124,890 - 67,300) x 5.3% (3,052.27) = 5,837.25
    ("married_filing_jointly", 150_000, 124_890.0, 5_837.25),
    # TI 674,890: 22,064.26 + (674,890 - 431,060) x 7.65% (18,653.00) = 40,717.26
    ("married_filing_jointly", 700_000, 674_890.0, 40_717.255),
    # TI 44,890: 685.30 + (44,890 - 19,580) x 4.4% (1,113.64) = 1,798.94
    ("married_filing_jointly", 70_000, 44_890.0, 1_798.94),
    # TI 238,070: 11,032.13 + (238,070 - 215,530) x 7.65% (1,724.31) = 12,756.44
    ("married_filing_separately", 250_000, 238_070.0, 12_756.44),
    # TI 28,070: 342.65 + (28,070 - 9,790) x 4.4% (804.32) = 1,146.97
    ("married_filing_separately", 40_000, 28_070.0, 1_146.97),
    # Unchanged: TI 46,440: 513.80 + (46,440 - 14,680) x 4.4% (1,397.44) = 1,911.24
    ("single", 60_000, 46_440.0, 1_911.24),
    ("head_of_household", 60_000, 46_440.0, 1_911.24),
])
def test_wi_schedule(tax_year, filing_status, agi, expected_taxable, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "WI", filing_status=filing_status,
                                                 tax_year=tax_year)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


def test_wi_joint_through_calculate():
    result = calculate(gross_income=700_000, deductions=0, filing_status="married_filing_jointly",
                       state_code="WI", tax_year=2025)
    assert result.state == pytest.approx(40_717.255, abs=0.01)

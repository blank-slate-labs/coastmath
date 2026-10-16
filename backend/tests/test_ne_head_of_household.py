"""Nebraska taxes heads of household on their own schedule and deduction.

NE DOR 2025 Tax Calculation Schedule 8-460-2025
(https://revenue.nebraska.gov/sites/default/files/doc/tax-forms/2025/2025_Tax_Calculation_Schedule.pdf),
Head of Household: 2.46% to $7,510; 3.51% to $38,590 ($184.75 base); 5.01% to
$57,630; 5.20% above. Single: 4,030 / 24,120 / 38,870. Form 1040N (2025) line 6
standard deduction: $8,600 single/MFS, $17,200 MFJ, $12,600 head of household.
For 2026, Neb. Rev. Stat. 77-2715.03(2)(b)-(c) sets both upper rates at 4.55%;
the data keeps the 2025 thresholds, so HoH is 2.46% to $7,510, 3.51% to
$38,590 and 4.55% above. The state layer reads the 2026 table for every year.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate


@pytest.mark.parametrize("filing_status, agi, expected_taxable, expected_tax", [
    # TI 17,400: 7,510 x 2.46% (184.746) + 9,890 x 3.51% (347.139) = 531.885
    ("head_of_household", 30_000, 17_400.0, 531.885),
    # TI 47,400: 184.746 + 31,080 x 3.51% (1,090.908) + 8,810 x 4.55% (400.855) = 1,676.509
    ("head_of_household", 60_000, 47_400.0, 1_676.509),
    # TI 4,000 (below the first threshold): 4,000 x 2.46% = 98.40
    ("head_of_household", 16_600, 4_000.0, 98.40),
    # Unchanged single: TI 51,400: 4,030 x 2.46% (99.138) + 20,090 x 3.51% (705.159)
    # + 27,280 x 4.55% (1,241.24) = 2,045.537
    ("single", 60_000, 51_400.0, 2_045.537),
])
def test_ne_schedule(filing_status, agi, expected_taxable, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "NE", filing_status=filing_status,
                                                 tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


def test_ne_hoh_through_calculate():
    result = calculate(gross_income=60_000, deductions=0, filing_status="head_of_household",
                       state_code="NE", tax_year=2026)
    assert result.state == pytest.approx(1_676.509, abs=0.01)

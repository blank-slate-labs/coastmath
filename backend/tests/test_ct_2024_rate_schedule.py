"""Connecticut 2025/2026 tax uses the CGS 12-700(a)(10) schedule (PA 23-204).

CGS 12-700(a)(10), "For taxable years commencing on or after January 1, 2024",
https://www.cga.ct.gov/current/pub/chap_229.htm: the bottom two rates are 2.0% and
4.5% (the 3.0%/5.0% schedule in (a)(9) ended with 2023 taxable years).
- (A) unmarried and (D) married filing separately: 2.0% to $10,000, 4.5% to $50,000.
- (B) head of household: 2.0% to $16,000, 4.5% to $80,000, 5.5% to $160,000, 6.0% to
  $320,000, 6.5% to $400,000, 6.9% to $800,000, 6.99% above.
- (C) joint / surviving spouse: 2.0% to $20,000, 4.5% to $100,000, then twice the
  unmarried thresholds.
Cases stay at or below each status's (ii) 2%-band phase-out start ($56,500 single,
$50,250 MFS, $78,500 HoH, $100,500 joint) and above the 12-702 personal exemption
phase-out, which the bracket engine does not model.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate


@pytest.mark.parametrize("tax_year", [2025, 2026])
@pytest.mark.parametrize("filing_status, agi, expected_tax", [
    # 10,000 x 2% (200) + 40,000 x 4.5% (1,800) = 2,000
    ("single", 50_000, 2_000.0),
    # (D) matches (A): 200 + 40,000 x 4.5% = 2,000
    ("married_filing_separately", 50_000, 2_000.0),
    # 20,000 x 2% (400) + 80,000 x 4.5% (3,600) = 4,000
    ("married_filing_jointly", 100_000, 4_000.0),
    # 16,000 x 2% (320) + 62,000 x 4.5% (2,790) = 3,110
    ("head_of_household", 78_000, 3_110.0),
])
def test_ct_bottom_rates(tax_year, filing_status, agi, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "CT", filing_status=filing_status,
                                                 tax_year=tax_year)
    assert taxable == pytest.approx(agi)
    assert tax == pytest.approx(expected_tax, abs=0.01)


@pytest.mark.parametrize("tax_year", [2025, 2026])
def test_ct_head_of_household_upper_bands(tax_year):
    # Schedule amount at $900,000: (B)(i) $50,000 at $800,000 + 100,000 x 6.99%
    # (6,990) = 56,990. Cumulative check: 320 + 64,000 x 4.5% (2,880) + 80,000 x 5.5%
    # (4,400) + 160,000 x 6% (9,600) + 80,000 x 6.5% (5,200) + 400,000 x 6.9%
    # (27,600) = 50,000. The (ii)-(v) phase-out and recapture remain omitted.
    tax, _ = _state_tax_and_taxable_income(900_000, "CT", filing_status="head_of_household",
                                           tax_year=tax_year)
    assert tax == pytest.approx(56_990.0, abs=0.01)


def test_ct_through_calculate():
    result = calculate(gross_income=50_000, deductions=0, filing_status="single",
                       state_code="CT", tax_year=2026)
    assert result.state == pytest.approx(2_000.0, abs=0.01)

"""Oklahoma tax uses the 68 O.S. 2355 schedules as amended by HB 2764 (2025).

Enrolled HB 2764, https://www.oklegislature.gov/cf_pdf/2025-26%20ENR/hB/HB2764%20ENR.PDF:
- 2355(D), "For tax year 2026 and for subsequent tax years": (1) single and married
  filing separately: 0% on the first $3,750, 2.5% on the next $1,150, 3.5% on the
  next $2,300, 4.5% on the remainder; (2) joint, surviving spouse "and heads of
  households": 0% on the first $7,500, 2.5% on the next $2,300, 3.5% on the next
  $4,600, 4.5% on the remainder.
Oklahoma standard deduction (OTC Form 511 instructions, 2024 packet): $6,350 single
and MFS, $12,700 MFJ, $9,350 head of household. Subsection E's trigger-based rate
cuts and the $1,000 personal exemptions are not modelled.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate


@pytest.mark.parametrize("filing_status, agi, expected_taxable, expected_tax", [
    # TI 53,650: 1,150 x 2.5% (28.75) + 2,300 x 3.5% (80.50) + 46,450 x 4.5%
    # (2,090.25) = 2,199.50
    ("single", 60_000, 53_650.0, 2_199.50),
    ("married_filing_separately", 60_000, 53_650.0, 2_199.50),
    # TI 47,300: 2,300 x 2.5% (57.50) + 4,600 x 3.5% (161.00) + 32,900 x 4.5%
    # (1,480.50) = 1,699.00
    ("married_filing_jointly", 60_000, 47_300.0, 1_699.00),
    # TI 50,650: 218.50 + 36,250 x 4.5% (1,631.25) = 1,849.75
    ("head_of_household", 60_000, 50_650.0, 1_849.75),
    # TI 5,650 (inside the 3.5% band): 1,150 x 2.5% (28.75) + 750 x 3.5% (26.25) = 55.00
    ("single", 12_000, 5_650.0, 55.00),
    # TI 3,650 (inside the 0% band) = 0
    ("single", 10_000, 3_650.0, 0.0),
])
def test_ok_2026_schedule(filing_status, agi, expected_taxable, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "OK", filing_status=filing_status,
                                                 tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


def test_ok_through_calculate():
    result = calculate(gross_income=60_000, deductions=0, filing_status="single",
                       state_code="OK", tax_year=2026)
    assert result.state == pytest.approx(2_199.50, abs=0.01)

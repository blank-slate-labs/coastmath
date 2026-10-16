"""North Carolina's head-of-household standard deduction is $19,125.

G.S. 105-153.5(a)(1),
https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_105/GS_105-153.5.html:
MFJ/surviving spouse $25,500, head of household $19,125, single $12,750, MFS
$12,750. NCDOR publishes the same table and no additional amount for age 65+
or blind. G.S. 105-153.7 sets one flat rate for every filing status, 3.99% for
2026. NC taxable income = AGI - standard deduction.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate


@pytest.mark.parametrize("tax_year, filing_status, agi, expected_taxable, expected_tax", [
    # 60,000 - 19,125 = 40,875 x 3.99% = 1,630.9125
    (2026, "head_of_household", 60_000, 40_875, 1_630.91),
    # 100,000 - 19,125 = 80,875 x 3.99% = 3,226.9125
    (2026, "head_of_household", 100_000, 80_875, 3_226.91),
    # Controls: 60,000 - 12,750 = 47,250 x 3.99% = 1,885.275
    (2026, "single", 60_000, 47_250, 1_885.28),
    # 100,000 - 25,500 = 74,500 x 3.99% = 2,972.55
    (2026, "married_filing_jointly", 100_000, 74_500, 2_972.55),
    # 60,000 - 12,750 = 47,250 x 3.99%
    (2026, "married_filing_separately", 60_000, 47_250, 1_885.28),
])
def test_nc_standard_deduction_by_filing_status(tax_year, filing_status, agi,
                                                expected_taxable, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "NC", filing_status=filing_status,
                                                 tax_year=tax_year)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


def test_nc_head_of_household_through_calculate():
    # 3.99% x (60,000 - 19,125) = 1,630.91; no NC amount for age 65+
    result = calculate(gross_income=60_000, deductions=0, filing_status="head_of_household",
                       state_code="NC", tax_year=2026, holder_age=70)
    assert result.state == pytest.approx(1_630.91, abs=0.01)

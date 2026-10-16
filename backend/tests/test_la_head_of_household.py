"""Louisiana heads of household get the doubled standard deduction.

La. R.S. 47:294(A), https://legis.la.gov/Legis/Law.aspx?d=101761: single and
married-separate $12,500; married-joint, qualified surviving spouse and head of
household 200% of the single amount ($25,000). Rate is a flat 3% for all filers
(LDR FAQ, https://revenue.louisiana.gov/tax-education-and-faqs/faqs/income-tax-reform/
what-are-the-individual-income-tax-rates-and-brackets/).
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate


@pytest.mark.parametrize("tax_year", [2025, 2026])
@pytest.mark.parametrize("filing_status, agi, expected_taxable, expected_tax", [
    # 80,000 - 25,000 = 55,000 x 3% = 1,650
    ("head_of_household", 80_000, 55_000, 1_650.00),
    # 30,000 - 25,000 = 5,000 x 3% = 150
    ("head_of_household", 30_000, 5_000, 150.00),
    # 20,000 - 25,000 floors at 0
    ("head_of_household", 20_000, 0, 0.00),
    # Controls: single 80,000 - 12,500 = 67,500 x 3% = 2,025; MFJ as HoH
    ("single", 80_000, 67_500, 2_025.00),
    ("married_filing_jointly", 80_000, 55_000, 1_650.00),
])
def test_la_head_of_household_deduction(tax_year, filing_status, agi, expected_taxable,
                                        expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "LA", filing_status=filing_status,
                                                 tax_year=tax_year)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


def test_la_head_of_household_through_calculate():
    result = calculate(gross_income=80_000, deductions=0.0, filing_status="head_of_household",
                       state_code="LA", tax_year=2026)
    assert result.state == pytest.approx(1_650.00, abs=0.01)

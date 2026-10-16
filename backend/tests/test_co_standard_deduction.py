"""Colorado taxes federal taxable income, so it inherits the IRC 63 standard deduction.

C.R.S. 39-22-104(1.7) and the CDOR Individual Income Tax Guide
(https://tax.colorado.gov/individual-income-tax-guide): Colorado income tax
is 4.4% of "modified federal taxable income", so the deduction is IRC 63(c)
for the filing status plus the 63(f) amount per individual aged 65+.

2026 federal amounts (Rev. Proc. 2025-32): $16,100 single, $32,200 MFJ,
$24,150 HoH; 63(f) $2,050 unmarried, $1,650 married per aged individual.
"""

import pytest

from coastmath.engine.tax_engine import calculate


@pytest.mark.parametrize("filing_status, holder_age, spouse_age, expected", [
    # Control: 4.4% x (100,000 - 16,100) = 4.4% x 83,900 = 3,691.60
    ("single", 45, None, 3_691.60),
    # 4.4% x (100,000 - 24,150) = 4.4% x 75,850 = 3,337.40
    ("head_of_household", 45, None, 3_337.40),
    # 4.4% x (100,000 - 16,100 - 2,050) = 4.4% x 81,850 = 3,601.40
    ("single", 70, None, 3_601.40),
    # 4.4% x (100,000 - 32,200 - 2 x 1,650) = 4.4% x 64,500 = 2,838.00
    ("married_filing_jointly", 70, 70, 2_838.00),
    # 4.4% x (100,000 - 32,200 - 1,650) = 4.4% x 66,150 = 2,910.60
    ("married_filing_jointly", 70, 60, 2_910.60),
])
def test_co_uses_federal_standard_deduction(filing_status, holder_age, spouse_age, expected):
    result = calculate(gross_income=100_000, deductions=0, filing_status=filing_status,
                       state_code="CO", tax_year=2026, holder_age=holder_age, spouse_age=spouse_age)
    assert result.state == pytest.approx(expected, abs=0.01)

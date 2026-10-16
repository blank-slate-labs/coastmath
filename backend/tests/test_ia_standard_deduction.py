"""Iowa taxes federal taxable income, so it inherits the federal deductions.

Iowa Code 422.7 (https://www.legis.iowa.gov/docs/code/422.7.pdf): "net
income" is taxable income as computed under IRC section 63, and Iowa Code
422.3(5)(b) (https://www.legis.iowa.gov/docs/code/422.3.pdf) conforms to the
IRC as amended. So the deduction is IRC 63(c) for the filing status plus the
63(f) amount per individual aged 65+, plus the IRC 151(d)(5) senior deduction,
which Iowa adopts (IDR, https://revenue.iowa.gov/taxes/tax-guidance/
individual-income-tax/1040-expanded-instructions/whats-new: "the deduction is
already included in your federal taxable income").

2026 federal amounts (Rev. Proc. 2025-32): $16,100 single, $32,200 MFJ,
$24,150 HoH; 63(f) $2,050 unmarried, $1,650 married per aged individual.
Senior deduction: $6,000 per individual 65+, less 6% of MAGI above $75,000
($150,000 joint). Iowa rate 3.8%.
"""

import pytest

from coastmath.engine.tax_engine import calculate


@pytest.mark.parametrize("wages, filing_status, holder_age, spouse_age, expected", [
    # Control: 3.8% x (80,000 - 16,100) = 3.8% x 63,900 = 2,428.20
    (80_000, "single", 45, None, 2_428.20),
    # Control: 3.8% x (80,000 - 32,200) = 3.8% x 47,800 = 1,816.40
    (80_000, "married_filing_jointly", 45, 45, 1_816.40),
    # 3.8% x (80,000 - 24,150) = 3.8% x 55,850 = 2,122.30
    (80_000, "head_of_household", 45, None, 2_122.30),
    # Senior: 6,000 - 6% x (80,000 - 75,000) = 5,700
    # 3.8% x (80,000 - 16,100 - 2,050 - 5,700) = 3.8% x 56,150 = 2,133.70
    (80_000, "single", 67, None, 2_133.70),
    # Senior: 2 x 6,000 (MAGI under 150,000)
    # 3.8% x (80,000 - 32,200 - 2 x 1,650 - 12,000) = 3.8% x 32,500 = 1,235.00
    (80_000, "married_filing_jointly", 67, 67, 1_235.00),
    # Senior fully phased out: 6,000 - 6% x (200,000 - 75,000) < 0
    # 3.8% x (200,000 - 16,100 - 2,050) = 3.8% x 181,850 = 6,910.30
    (200_000, "single", 67, None, 6_910.30),
])
def test_ia_uses_federal_taxable_income_deductions(wages, filing_status, holder_age,
                                                   spouse_age, expected):
    result = calculate(wages, 0, filing_status, state_code="IA", earned_income=wages,
                       tax_year=2026, holder_age=holder_age, spouse_age=spouse_age)
    assert result.state == pytest.approx(expected, abs=0.01)

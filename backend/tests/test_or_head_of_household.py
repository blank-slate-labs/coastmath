"""Oregon heads of household use Chart J and the $4,560 standard deduction.

2025 Form OR-40 Instructions (150-101-040-1, Rev. 01-29-26),
https://www.oregon.gov/dor/forms/FormsPubs/form-or-40-inst_101-040-1_2025.pdf:
line 17 standard deduction: single $2,835, MFJ $5,670, head of household $4,560.
Line 20: "Use Chart J if your filing status is married filing jointly, head of
household, or qualifying surviving spouse." Chart J: $3,756 plus 8.75% of the
excess over $50,000 up to $250,000; $21,256 plus 9.9% over $250,000. The engine
carries Chart J as doubled single bands (4.75% to $8,800, 6.75% to $22,200, 8.75%
to $250,000, 9.9% above), which is $3,755 at $50,000 against the chart's $3,756.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate

# Doubled bands through $22,200: 8,800 x 4.75% (418) + 13,400 x 6.75% (904.50)
_J_TO_22_200 = 1_322.50


@pytest.mark.parametrize("filing_status, agi, expected_taxable, expected_tax", [
    # 100,000 - 4,560 = 95,440: 1,322.50 + 73,240 x 8.75% (6,408.50) = 7,731.00
    # (Chart J: 3,756 + 45,440 x 8.75% = 7,732.00)
    ("head_of_household", 100_000, 95_440, 7_731.00),
    # 300,000 - 4,560 = 295,440: 1,322.50 + 227,800 x 8.75% (19,932.50)
    # + 45,440 x 9.9% (4,498.56) = 25,753.56 (Chart J: 25,754.56)
    ("head_of_household", 300_000, 295_440, 25_753.56),
    # Control, Chart S: 100,000 - 2,835 = 97,165: 4,400 x 4.75% (209)
    # + 6,700 x 6.75% (452.25) + 86,065 x 8.75% (7,530.6875) = 8,191.9375
    ("single", 100_000, 97_165, 8_191.9375),
])
def test_or_2026_head_of_household_chart_j(filing_status, agi, expected_taxable, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "OR", filing_status=filing_status,
                                                 tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


def test_or_head_of_household_through_calculate():
    result = calculate(100_000, 0, "head_of_household", state_code="OR", tax_year=2026,
                       holder_age=45)
    assert result.state == pytest.approx(7_731.00, abs=0.01)

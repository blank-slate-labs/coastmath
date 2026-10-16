"""Missouri adopts the allowable federal standard deduction.

RSMo 143.131.2 (https://revisor.mo.gov/main/OneSection.aspx?section=143.131):
"The Missouri standard deduction shall be the allowable federal standard
deduction", i.e. IRC 63(c) for the filing status plus the 63(f) amount per
individual aged 65+ (2025 Form MO-1040 instructions, line 14). RSMo 143.161.2
and MO-1040 line 15 add a fixed $1,400 head-of-household exemption.

2026 federal amounts (Rev. Proc. 2025-32): $16,100 single/MFS, $32,200 MFJ,
$24,150 HoH; 63(f) $2,050 unmarried, $1,650 married per aged individual.
MO rate chart: 0% to $1,313, then 2/2.5/3/3.5/4/4.5% per $1,313 band to
$9,191 ($256.035 cumulative), 4.7% above.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate


@pytest.mark.parametrize("filing_status, holder_age, agi, expected_taxable, expected_tax", [
    # 60,000 - (16,100 + 2,050) = 41,850; 256.035 + 4.7% x 32,659 = 1,791.008
    ("single", 67, 60_000, 41_850, 1_791.01),
    # Under 65: 60,000 - 16,100 = 43,900; 256.035 + 4.7% x 34,709 = 1,887.358
    ("single", 64, 60_000, 43_900, 1_887.36),
    # 80,000 - 24,150 - 1,400 = 54,450; 256.035 + 4.7% x 45,259 = 2,383.208
    ("head_of_household", 40, 80_000, 54_450, 2_383.21),
    # 80,000 - (24,150 + 2,050) - 1,400 = 52,400; 256.035 + 4.7% x 43,209 = 2,286.858
    ("head_of_household", 70, 80_000, 52_400, 2_286.86),
    # 60,000 - (16,100 + 1,650) = 42,250; 256.035 + 4.7% x 33,059 = 1,809.808
    ("married_filing_separately", 66, 60_000, 42_250, 1_809.81),
])
def test_mo_federal_standard_deduction(filing_status, holder_age, agi, expected_taxable, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(
        agi, "MO", filing_status=filing_status, holder_age=holder_age, tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


@pytest.mark.parametrize("holder_age, spouse_age, extra", [
    (67, 66, 2 * 1_650),
    (67, 60, 1_650),
    (60, 67, 1_650),
])
def test_mo_joint_aged_additions(holder_age, spouse_age, extra):
    # Taxable income stays in the 4.7% band, so each aged spouse lowers MO tax
    # by 4.7% x 1,650 = 77.55 relative to a couple under 65 (32,200 deduction).
    def mo(h, s):
        return calculate(gross_income=100_000, deductions=0, filing_status="married_filing_jointly",
                         state_code="MO", tax_year=2026, holder_age=h, spouse_age=s)
    assert mo(60, 60).state - mo(holder_age, spouse_age).state == pytest.approx(0.047 * extra, abs=0.01)
    _, taxable = _state_tax_and_taxable_income(
        100_000, "MO", filing_status="married_filing_jointly",
        holder_age=holder_age, spouse_age=spouse_age, tax_year=2026)
    assert taxable == pytest.approx(100_000 - 32_200 - extra)

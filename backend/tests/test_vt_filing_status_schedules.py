"""Vermont taxes each filing status on its own schedule after personal exemptions.

2026 Form IN-114 instructions, "2026 Preliminary Vermont Tax Rates"
(https://tax.vermont.gov/sites/tax/files/documents/IN-114-Instr-2026.pdf), rates
3.35/6.6/7.6/8.75%: Schedule X (single) $50,750 / $122,850 / $256,300; Y-1
(joint) $84,700 / $204,750 / $312,050; Y-2 (married filing separately) $42,350 /
$102,375 / $156,025; Z (head of household) $68,000 / $175,500 / $284,150.
2025 Form IN-111 instructions
(https://tax.vermont.gov/sites/tax/files/documents/IN-111-Instr-2025.pdf),
lines 4-8: standard deduction $7,650 single and MFS, $15,300 joint, $11,450 head
of household, plus $1,250 per individual 65 or older; a $5,300 personal
exemption for the filer and a joint spouse. 32 V.S.A. 5822(a)(6): above $150,000
federal AGI the tax is at least 3% of federal AGI.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate


@pytest.mark.parametrize("filing_status, agi, expected_taxable, expected_tax", [
    # 100,000 - 7,650 - 5,300 = 87,050
    # X: 50,750 x 3.35% (1,700.125) + 36,300 x 6.6% (2,395.80) = 4,095.925
    ("single", 100_000, 87_050, 4_095.925),
    # 500,000 - 15,300 - 2 x 5,300 = 474,100
    # Y-1: 2,837.45 + 120,050 x 6.6% (7,923.30) + 107,300 x 7.6% (8,154.80)
    #      + 162,050 x 8.75% (14,179.375) = 33,094.925; 3% minimum 15,000
    ("married_filing_jointly", 500_000, 474_100, 33_094.925),
    # 120,000 - 11,450 - 5,300 = 103,250
    # Z: 68,000 x 3.35% (2,278.00) + 35,250 x 6.6% (2,326.50) = 4,604.50
    ("head_of_household", 120_000, 103_250, 4_604.50),
    # 250,000 - 7,650 - 5,300 = 237,050
    # Y-2: 1,418.725 + 60,025 x 6.6% (3,961.65) + 53,650 x 7.6% (4,077.40)
    #      + 81,025 x 8.75% (7,089.6875) = 16,547.4625; 3% minimum 7,500
    ("married_filing_separately", 250_000, 237_050, 16_547.4625),
])
def test_vt_schedule(filing_status, agi, expected_taxable, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "VT", filing_status=filing_status,
                                                 tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


@pytest.mark.parametrize("filing_status, agi, expected_taxable", [
    # 60,000 - (7,650 + 1,250) - 5,300 = 45,800
    ("single", 60_000, 45_800),
    # 100,000 - (15,300 + 2 x 1,250) - 2 x 5,300 = 71,600
    ("married_filing_jointly", 100_000, 71_600),
])
def test_vt_aged_addition(filing_status, agi, expected_taxable):
    tax, taxable = _state_tax_and_taxable_income(agi, "VT", filing_status=filing_status,
                                                 holder_age=70, spouse_age=70, tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_taxable * 0.0335, abs=0.01)


def test_vt_minimum_tax_uses_federal_agi():
    # State AGI 100,000 -> TI 74,100 x 3.35% = 2,482.35 < 3% x 200,000 = 6,000
    tax, taxable = _state_tax_and_taxable_income(
        200_000, "VT", filing_status="married_filing_jointly", tax_year=2026,
        state_income_adjustment=-100_000)
    assert taxable == pytest.approx(74_100)
    assert tax == pytest.approx(6_000.00)


def test_vt_minimum_tax_threshold_is_not_indexed():
    # Deduction and exemption are indexed: 51,000 - 2 x (15,300 + 10,600) = -800
    # -> TI 0, but federal AGI 151,000 > 150,000, so 3% x 151,000 = 4,530
    tax, _ = _state_tax_and_taxable_income(
        151_000, "VT", filing_status="married_filing_jointly", inflation_factor=2.0,
        tax_year=2026, state_income_adjustment=-100_000)
    assert tax == pytest.approx(4_530.00)


def test_vt_indexed_exemption_and_brackets():
    # factor 1.1: TI = 100,000 - 8,415 - 5,830 = 85,755
    # 55,825 x 3.35% (1,870.1375) + 29,930 x 6.6% (1,975.38) = 3,845.5175
    tax, taxable = _state_tax_and_taxable_income(100_000, "VT", filing_status="single",
                                                 inflation_factor=1.1, tax_year=2026)
    assert taxable == pytest.approx(85_755)
    assert tax == pytest.approx(3_845.5175, abs=0.01)


def test_vt_joint_through_calculate():
    result = calculate(gross_income=500_000, deductions=0, filing_status="married_filing_jointly",
                       state_code="VT", tax_year=2026)
    assert result.state == pytest.approx(33_094.925, abs=0.01)

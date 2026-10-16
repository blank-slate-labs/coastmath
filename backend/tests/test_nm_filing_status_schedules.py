"""New Mexico publishes a separate rate schedule per filing status.

NMSA 1978 Section 7-2-7 as amended by HB 252 (Laws 2024, ch. 67, Section 5),
https://www.nmlegis.gov/Sessions/24%20Regular/final/HB0252.pdf, for taxable
years beginning on or after January 1, 2025 (not indexed). Rates 1.5% / 3.2% /
4.3% / 4.7% / 4.9% / 5.9%:
(A) married filing jointly, heads of household and surviving spouses: tops
$8,000 / $25,000 / $50,000 / $100,000 / $315,000 ($4,089 at $100,000, $14,624
at $315,000);
(B) single: $5,500 / $16,500 / $33,500 / $66,500 / $210,000 ($2,716.50 at
$66,500);
(C) married filing separately: $4,000 / $12,500 / $25,000 / $50,000 / $157,500
($869.50 at $25,000, $7,312 at $157,500).
NM taxable income starts from federal AGI less the federal standard deduction
for the filing status (2026: $16,100 single/MFS, $32,200 MFJ, $24,150 HoH).
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate


@pytest.mark.parametrize("filing_status, agi, expected_taxable, expected_tax", [
    # 132,200 - 32,200 = 100,000: 4,089 (statutory amount at $100,000)
    ("married_filing_jointly", 132_200, 100_000, 4_089.00),
    # 532,200 - 32,200 = 500,000: 14,624 + 5.9% x 185,000 = 14,624 + 10,915
    ("married_filing_jointly", 532_200, 500_000, 25_539.00),
    # 132,200 - 24,150 = 108,050: 4,089 + 4.9% x 8,050 = 4,089 + 394.45
    ("head_of_household", 132_200, 108_050, 4_483.45),
    # 44,150 - 24,150 = 20,000: 120 + 3.2% x 12,000 = 120 + 384
    ("head_of_household", 44_150, 20_000, 504.00),
    # 216,100 - 16,100 = 200,000: 7,312 + 5.9% x 42,500 = 7,312 + 2,507.50
    ("married_filing_separately", 216_100, 200_000, 9_819.50),
    # 46,100 - 16,100 = 30,000: 869.50 + 4.7% x 5,000 = 869.50 + 235
    ("married_filing_separately", 46_100, 30_000, 1_104.50),
    # single unchanged: 116,100 - 16,100 = 100,000: 2,716.50 + 4.9% x 33,500 = 2,716.50 + 1,641.50
    ("single", 116_100, 100_000, 4_358.00),
])
def test_nm_2026_filing_status_schedules(filing_status, agi, expected_taxable, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "NM", filing_status=filing_status,
                                                 tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


def test_nm_mfj_through_calculate():
    # 532,200 - 32,200 = 500,000: 14,624 + 10,915
    result = calculate(gross_income=532_200, deductions=0, filing_status="married_filing_jointly",
                       state_code="NM", tax_year=2026)
    assert result.state == pytest.approx(25_539.00, abs=0.01)

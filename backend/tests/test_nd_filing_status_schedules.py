"""North Dakota publishes a separate rate schedule per filing status.

ND Office of State Tax Commissioner, https://www.tax.nd.gov/individual-income-tax
(2025 tax year; the 2026 data keeps the same thresholds):
single 0% to $48,475, 1.95% to $244,825, 2.5% above; MFJ 0% to $80,975,
1.95% to $298,075; MFS 0% to $40,475, 1.95% to $149,025; head of household
0% to $64,950, 1.95% to $271,450. ND-1 starts from federal taxable income, so
the deduction is the federal standard deduction for the filing status
(2026: $16,100 single/MFS, $32,200 MFJ, $24,150 HoH).
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate


@pytest.mark.parametrize("filing_status, agi, expected_taxable, expected_tax", [
    # 97,800 - 80,975 = 16,825 x 1.95%
    ("married_filing_jointly", 130_000, 97_800, 328.09),
    # 217,800 - 80,975 = 136,825 x 1.95%
    ("married_filing_jointly", 250_000, 217_800, 2_668.09),
    # 217,100 x 1.95% = 4,233.45; (517,800 - 298,075) x 2.5% = 5,493.125
    ("married_filing_jointly", 550_000, 517_800, 9_726.58),
    # 130,000 - 24,150 = 105,850; (105,850 - 64,950) x 1.95% = 797.55
    ("head_of_household", 130_000, 105_850, 797.55),
    # 320,000 - 24,150 = 295,850: 206,500 x 1.95% = 4,026.75; 24,400 x 2.5% = 610
    ("head_of_household", 320_000, 295_850, 4_636.75),
    # 200,000 - 16,100 = 183,900: (149,025 - 40,475) x 1.95% = 2,116.725; (183,900 - 149,025) x 2.5% = 871.875
    ("married_filing_separately", 200_000, 183_900, 2_988.60),
    # single unchanged: (113,900 - 48,475) x 1.95% = 1,275.79
    ("single", 130_000, 113_900, 1_275.79),
])
def test_nd_2026_filing_status_schedules(filing_status, agi, expected_taxable, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "ND", filing_status=filing_status,
                                                 tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


def test_nd_mfj_through_calculate():
    # 550,000 - 32,200 = 517,800: 4,233.45 + 5,493.125
    result = calculate(gross_income=550_000, deductions=0, filing_status="married_filing_jointly",
                       state_code="ND", tax_year=2026)
    assert result.state == pytest.approx(9_726.58, abs=0.01)

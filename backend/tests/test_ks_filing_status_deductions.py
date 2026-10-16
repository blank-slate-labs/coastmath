"""Kansas standard deductions per filing status and for filers 65 or older.

2025 Kansas Individual Income Tax booklet IP25, https://www.ksrevenue.gov/pdf/ip25.pdf
(unindexed amounts, the same on the 2026 K-40ES, https://www.ksrevenue.gov/pdf/k-40es26.pdf):
p.6 line 4, standard deduction $3,605 single, $8,240 married filing joint,
$6,180 head of household, $4,120 married filing separate; the worksheet for
people 65 or older adds $850 per box for single/head of household and $700
for married filers. p.34 tax computation: 5.2% to $46,000 joint ($23,000
single, head of household and married filing separate), 5.58% above. The
exemption allowance is a documented omission of the default state path.
"""

import pytest

from coastmath.engine.tax_engine import calculate


def _ks_tax(filing_status, wages, age=40):
    married = filing_status.startswith("married")
    return calculate(gross_income=wages, deductions=0, filing_status=filing_status, state_code="KS",
                     w2_income=wages, earned_income=wages, holder_age=age,
                     spouse_age=age if married else None, tax_year=2026).state


@pytest.mark.parametrize("filing_status, wages, age, expected", [
    # 60,000 - 3,605 = 56,395: 23,000 x 5.2% = 1,196; 33,395 x 5.58% = 1,863.44
    ("single", 60_000, 40, 3_059.44),
    # 60,000 - 8,240 = 51,760: 46,000 x 5.2% = 2,392; 5,760 x 5.58% = 321.41
    ("married_filing_jointly", 60_000, 40, 2_713.41),
    # 100,000 - 8,240 = 91,760: 2,392 + 45,760 x 5.58% = 2,553.41
    ("married_filing_jointly", 100_000, 40, 4_945.41),
    # 60,000 - 6,180 = 53,820: 1,196 + 30,820 x 5.58% = 1,719.76
    ("head_of_household", 60_000, 40, 2_915.76),
    # 60,000 - 4,120 = 55,880: 1,196 + 32,880 x 5.58% = 1,834.70
    ("married_filing_separately", 60_000, 40, 3_030.70),
    # 60,000 - 4,455 (worksheet, one box): 1,196 + 32,545 x 5.58% = 1,816.01
    ("single", 60_000, 67, 3_012.01),
    # 60,000 - 7,030 (worksheet, one box): 1,196 + 29,970 x 5.58% = 1,672.33
    ("head_of_household", 60_000, 67, 2_868.33),
    # 100,000 - 9,640 (worksheet, two boxes): 2,392 + 44,360 x 5.58% = 2,475.29
    ("married_filing_jointly", 100_000, 67, 4_867.29),
    # 60,000 - 4,820 (worksheet, one box; spouse not modeled): 1,196 + 32,180 x 5.58% = 1,795.64
    ("married_filing_separately", 60_000, 67, 2_991.64),
])
def test_ks_2026_standard_deduction_by_status_and_age(filing_status, wages, age, expected):
    assert _ks_tax(filing_status, wages, age) == pytest.approx(expected, abs=0.01)

"""Idaho adopts the IRC 63 standard deduction and taxes heads of household jointly.

Idaho Code 63-3022(j)(1) (https://legislature.idaho.gov/statutesrules/idstat/Title63/T63CH30/SECT63-3022/):
individuals deduct "the standard deduction as defined in section 63 of the
Internal Revenue Code", i.e. 63(c) for the filing status plus the 63(f) amount
per individual aged 65+. Idaho Code 63-3024(2)(b)
(https://legislature.idaho.gov/statutesrules/idstat/Title63/T63CH30/SECT63-3024/):
a head-of-household return "shall be treated as a joint return", so it uses the
joint 0% band (twice the single band).

2026 federal amounts (Rev. Proc. 2025-32): $16,100 single, $32,200 MFJ,
$24,150 HoH; 63(f) $2,050 unmarried, $1,650 married per aged individual.
Idaho bands carried by the data: 0% to $4,811 single, $9,622 joint; 5.3% above.
"""

import pytest

from coastmath.engine.tax_engine import calculate


@pytest.mark.parametrize("filing_status, holder_age, spouse_age, gross, expected", [
    # Control: 60,000 - 16,100 = 43,900; 5.3% x (43,900 - 4,811) = 2,071.717
    ("single", 40, None, 60_000, 2_071.72),
    # 60,000 - (16,100 + 2,050) = 41,850; 5.3% x 37,039 = 1,963.067
    ("single", 67, None, 60_000, 1_963.07),
    # 100,000 - (32,200 + 2 x 1,650) = 64,500; 5.3% x (64,500 - 9,622) = 2,908.534
    ("married_filing_jointly", 67, 66, 100_000, 2_908.53),
    # 100,000 - (32,200 + 1,650) = 66,150; 5.3% x 56,528 = 2,995.984
    ("married_filing_jointly", 67, 60, 100_000, 2_995.98),
    # 60,000 - 24,150 = 35,850; 5.3% x (35,850 - 9,622) = 1,390.084
    ("head_of_household", 40, None, 60_000, 1_390.08),
    # 60,000 - (24,150 + 2,050) = 33,800; 5.3% x 24,178 = 1,281.434
    ("head_of_household", 68, None, 60_000, 1_281.43),
])
def test_id_federal_deduction_and_hoh_joint_band(filing_status, holder_age, spouse_age, gross, expected):
    result = calculate(gross_income=gross, deductions=0, filing_status=filing_status,
                       state_code="ID", tax_year=2026, holder_age=holder_age, spouse_age=spouse_age)
    assert result.state == pytest.approx(expected, abs=0.01)

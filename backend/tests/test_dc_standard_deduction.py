"""District of Columbia standard deduction by filing status and age.

D.C. Code 47-1801.04(44)(A)-(C)(iv),
https://code.dccouncil.gov/us/dc/council/code/sections/47-1801.04: for taxable
years after 2017 the DC standard deduction for single, head-of-household and
joint returns is "the standard deduction as prescribed in section 63(c)". IRC
63(c)(1) adds the 63(c)(3)/63(f) additional amount for each individual 65 or
older. DC keeps the Rev. Proc. 2024-40 sec. 3.15 table for 2025 and 2026:
$15,000 single/MFS, $22,500 head of household, $30,000 joint, plus $2,000 per
aged unmarried filer or $1,600 per aged spouse.

One rate schedule for every filer (D.C. Code 47-1806.03): 4% to $10,000, 6%
to $40,000, 6.5% to $60,000, 8.5% to $250,000, then 9.25% / 9.75% / 10.75%.
Cumulative tax: $400 at $10,000, $2,200 at $40,000, $3,500 at $60,000.
"""

import pytest

from coastmath.engine.tax_engine import calculate


@pytest.mark.parametrize("tax_year", [2025, 2026])
@pytest.mark.parametrize("filing_status, income, holder_age, spouse_age, expected", [
    # 80,000 - 22,500 = 57,500: 2,200 + 6.5% x 17,500 = 2,200 + 1,137.50
    ("head_of_household", 80_000, 40, None, 3_337.50),
    # 30,000 - 22,500 = 7,500: 4% x 7,500
    ("head_of_household", 30_000, 40, None, 300.00),
    # 80,000 - (22,500 + 2,000) = 55,500: 2,200 + 6.5% x 15,500 = 2,200 + 1,007.50
    ("head_of_household", 80_000, 70, None, 3_207.50),
    # 80,000 - (15,000 + 2,000) = 63,000: 3,500 + 8.5% x 3,000 = 3,500 + 255
    ("single", 80_000, 70, None, 3_755.00),
    # under 65 unchanged: 80,000 - 15,000 = 65,000: 3,500 + 8.5% x 5,000
    ("single", 80_000, 40, None, 3_925.00),
    # 100,000 - (30,000 + 2 x 1,600) = 66,800: 3,500 + 8.5% x 6,800 = 3,500 + 578
    ("married_filing_jointly", 100_000, 70, 68, 4_078.00),
    # one spouse 65+: 100,000 - 31,600 = 68,400: 3,500 + 8.5% x 8,400 = 3,500 + 714
    ("married_filing_jointly", 100_000, 70, 60, 4_214.00),
    # 80,000 - (15,000 + 1,600) = 63,400: 3,500 + 8.5% x 3,400 = 3,500 + 289
    ("married_filing_separately", 80_000, 70, None, 3_789.00),
])
def test_dc_standard_deduction_follows_irc_63c(tax_year, filing_status, income, holder_age,
                                               spouse_age, expected):
    result = calculate(income, 0, filing_status, state_code="DC", tax_year=tax_year,
                       holder_age=holder_age, spouse_age=spouse_age)
    assert result.state == pytest.approx(expected, abs=0.01)

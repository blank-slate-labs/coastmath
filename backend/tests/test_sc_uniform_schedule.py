"""South Carolina uses one rate schedule for every filing status.

SC Code 12-6-510 as amended by H.4216
(https://www.scstatehouse.gov/sess126_2025-2026/bills/4216.htm) and SCDOR
"Information about H. 4216" (https://dor.sc.gov/news/information-about-h-4216),
tax years after 2025: 1.99% of SC taxable income under $30,000; 5.21% of the
amount minus $966 at $30,000 and above, for all individuals. The SC Income
Adjusted Deduction (12-6-1140(15)) is $15,000 single/MFS, $22,500 head of
household and $30,000 MFJ. Its AGI phasedown is not modeled.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income


@pytest.mark.parametrize("filing_status, agi, expected_taxable, expected_tax", [
    # 50,000 - 30,000 = 20,000 < 30,000: 0.0199 x 20,000
    ("married_filing_jointly", 50_000, 20_000, 398.00),
    # 75,000 - 30,000 = 45,000, inside the old doubled band: 0.0521 x 45,000 - 966
    ("married_filing_jointly", 75_000, 45_000, 1_378.50),
    # 70,000: 0.0521 x 70,000 - 966 = 3,647 - 966
    ("married_filing_jointly", 100_000, 70_000, 2_681.00),
    # 120,000: 6,252 - 966
    ("married_filing_jointly", 150_000, 120_000, 5_286.00),
    # 100,000 - 15,000 = 85,000: 4,428.50 - 966
    ("single", 100_000, 85_000, 3_462.50),
    ("married_filing_separately", 100_000, 85_000, 3_462.50),
    # 100,000 - 22,500 = 77,500: 4,037.75 - 966
    ("head_of_household", 100_000, 77_500, 3_071.75),
])
def test_sc_2026_uniform_schedule(filing_status, agi, expected_taxable, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "SC", filing_status=filing_status,
                                                 tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)

"""South Carolina deducts 44% of net capital gain.

S.C. Code 12-6-1150 (https://www.scstatehouse.gov/code/t12c006.php): "(A)
Individuals, estates, and trusts are allowed a deduction from South Carolina
taxable income equal to forty-four percent of net capital gain ... (B)(2) Net
capital gain is as defined in Internal Revenue Code, Section 1222". H.4216 (Act
R117, 2026) does not amend it. Qualified dividends are not IRC 1222 net capital
gain, so they get no deduction.

SC 2026 data: 1.99% to $30,000 and 5.21% above for every filing status; SCIAD
$15,000 single / $30,000 MFJ (phase-down not modelled).
"""

import pytest

from coastmath.engine.tax_engine import calculate


def _sc(gross_income=60_000, **kw):
    return calculate(gross_income=gross_income, earned_income=60_000, w2_income=60_000,
                     deductions=0, state_code="SC", tax_year=2026, **kw).state


@pytest.mark.parametrize("kw, expected", [
    # TI 160,000 - 15,000 = 145,000; less 44,000 = 101,000
    # 30,000 x 1.99% (597) + 71,000 x 5.21% (3,699.10)
    (dict(capital_gains=100_000, filing_status="single"), 4_296.10),
    # TI 360,000 - 30,000 = 330,000; less 132,000 = 198,000
    # 597 + 168,000 x 5.21% (8,752.80)
    (dict(capital_gains=300_000, filing_status="married_filing_jointly"), 9_349.80),
    # Qualified dividends only, no deduction: TI 95,000
    # 597 + 65,000 x 5.21% (3,386.50)
    (dict(qualified_dividends=50_000, filing_status="single"), 3_983.50),
    # Netted first: 60,000 - 20,000 carryforward = 40,000 net gain;
    # AGI 100,000, TI 85,000; less 17,600 = 67,400
    # 597 + 37,400 x 5.21% (1,948.54)
    (dict(capital_gains=60_000, capital_loss_carryforward=20_000,
          filing_status="single"), 2_545.54),
])
def test_sc_net_capital_gain_deduction_2026(kw, expected):
    assert _sc(**kw) == pytest.approx(expected, abs=0.01)


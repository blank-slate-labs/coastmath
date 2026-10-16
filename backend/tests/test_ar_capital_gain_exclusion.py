"""Arkansas exempts 50% of net capital gain and all of it above $10M.

Ark. Code Ann. 26-51-815(b) and Form AR1000D (2025, R 4/25/2025,
https://www.dfa.arkansas.gov/wp-content/uploads/2025_AR1000D_CapitalGains.pdf):
line 7a net capital gain = long-term gain less net short-term loss; "7b. If the
amount on line 7a is over $10,000,000, only enter $10,000,000"; "8. ... If a
gain multiply line 7b by 50 percent (.50)". Act 1488 of 2013 exempts the excess
over $10,000,000.

AR data: standard deduction $2,470 (doubled for joint); single bands
0% / 2% / 3% / 3.4% / 3.7% at 5,599 / 11,199 / 15,999 / 26,399. Below the top band a single filer owes
5,600 x 2% + 4,800 x 3% + 10,400 x 3.4% = 112 + 144 + 353.60 = 609.60; a joint
filer (bands doubled, top at 52,798) owes 224 + 288 + 707.20 = 1,219.20.
"""

import pytest

from coastmath.engine.tax_engine import calculate


def _ar(**kw):
    return calculate(gross_income=60_000, earned_income=60_000, w2_income=60_000,
                     deductions=0, state_code="AR", tax_year=2026, **kw).state


@pytest.mark.parametrize("kw, expected", [
    # 60,000 + 100,000 - 50,000 = 110,000; TI 107,530
    # 609.60 + 81,131 x 3.7% (3,001.847) = 3,611.447
    (dict(capital_gains=100_000, filing_status="single"), 3_611.447),
    # 60,000 + 200,000 - 100,000 = 160,000; TI 155,060
    # 1,219.20 + 102,262 x 3.7% (3,783.694) = 5,002.894
    (dict(capital_gains=200_000, filing_status="married_filing_jointly"), 5_002.894),
    # Netted first: 60,000 - 20,000 carryforward = 40,000; exempt 20,000
    # 60,000 + 40,000 - 20,000 = 80,000; TI 77,530
    # 609.60 + 51,131 x 3.7% (1,891.847) = 2,501.447
    (dict(capital_gains=60_000, capital_loss_carryforward=20_000, filing_status="single"),
     2_501.447),
    # Exactly $10M: exempt 5,000,000; AGI 5,060,000; TI 5,057,530
    # 609.60 + 5,031,131 x 3.7% (186,151.847) = 186,761.447
    (dict(capital_gains=10_000_000, filing_status="single"), 186_761.447),
    # $12M: exempt 50% x 10,000,000 + 2,000,000 = 7,000,000; same AGI and tax
    (dict(capital_gains=12_000_000, filing_status="single"), 186_761.447),
])
def test_ar_net_capital_gain_exclusion(kw, expected):
    assert _ar(**kw) == pytest.approx(expected, abs=0.01)

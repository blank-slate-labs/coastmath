"""North Dakota excludes 40% of net long-term gain and qualified dividends.

N.D.C.C. 57-38-30.3(2)(d) (https://ndlegis.gov/cencode/t57c38.pdf): North
Dakota taxable income is federal taxable income "reduced by forty percent of:
(1) The excess of the taxpayer's net long-term capital gain ... over the net
short-term capital loss ... (2) Qualified dividends as defined under Internal
Revenue Code section 1(h)(11) ... but only if taxed at a federal income tax rate
that is lower than the regular federal income tax rates".

ND 2026 data: federal standard deduction $16,100 single / $32,200 MFJ; single
bands 0% / 1.95% / 2.5% at 48,475 / 244,825; MFJ 0% / 1.95% at 80,975 / 298,075.
"""

import pytest

from coastmath.engine.tax_engine import calculate


def _state(state_code, gross_income=60_000, **kw):
    return calculate(gross_income=gross_income, earned_income=60_000, w2_income=60_000,
                     deductions=0, state_code=state_code, tax_year=2026, **kw).state


@pytest.mark.parametrize("kw, expected", [
    # TI 160,000 - 16,100 = 143,900; less 40,000 = 103,900
    # 55,425 x 1.95% = 1,080.7875
    (dict(capital_gains=100_000, filing_status="single"), 1_080.7875),
    # TI 360,000 - 32,200 = 327,800; less 120,000 = 207,800
    # 126,825 x 1.95% = 2,473.0875
    (dict(capital_gains=300_000, filing_status="married_filing_jointly"), 2_473.0875),
    # Qualified dividends only: TI 93,900; less 20,000 = 73,900
    # 25,425 x 1.95% = 495.7875
    (dict(qualified_dividends=50_000, filing_status="single"), 495.7875),
    # Netted first: 60,000 - 20,000 carryforward = 40,000 gain, plus 10,000
    # dividends; AGI 110,000, TI 93,900; less 16,000 + 4,000 = 73,900
    (dict(capital_gains=60_000, capital_loss_carryforward=20_000,
          qualified_dividends=10_000, filing_status="single"), 495.7875),
    # Top band: TI 543,900; less 200,000 = 343,900
    # 196,350 x 1.95% (3,828.825) + 99,075 x 2.5% (2,476.875) = 6,305.70
    (dict(capital_gains=500_000, filing_status="single"), 6_305.70),
])
def test_nd_long_term_gain_and_dividend_exclusion(kw, expected):
    assert _state("ND", **kw) == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize("state_code", ["WI", "AR"])
def test_gain_only_exclusions_do_not_exclude_dividends(state_code):
    # Wis. Stat. 71.05(6)(b)9 and Ark. Code Ann. 26-51-815(b) exclude net
    # capital gain only: $50,000 of qualified dividends is taxed like $50,000
    # of other income in the same state AGI.
    with_dividends = _state(state_code, qualified_dividends=50_000, filing_status="single")
    ordinary = _state(state_code, gross_income=110_000, filing_status="single")
    assert with_dividends == pytest.approx(ordinary, abs=0.01)
    assert with_dividends > _state(state_code, capital_gains=50_000, filing_status="single")

"""Hawaii caps the rate on net capital gain at 7.25%.

HRS 235-51(f)
(https://data.capitol.hawaii.gov/hrscurrent/Vol04_Ch0201-0257/HRS0235/HRS_0235-0051.htm):
with a net capital gain, tax may not exceed the ordinary tax on the greater of
(A) taxable income less net capital gain or (B) taxable income taxed below
7.25%, plus 7.25% of the rest. Qualified dividends are not capital gain.

2026 HI data: single deduction $8,000, rates below 7.25% end at $48,000;
tax to 48,000 = 134.40 + 153.60 + 264.00 + 307.20 + 816.00 + 864.00 =
2,539.20. Above: 7.6% to 125,000, 7.9% to 175,000, 8.25% to 225,000, 9% to
275,000. Joint doubles the bands and deduction; head of household uses
1.5x bands and a $12,000 deduction.
"""

import pytest

from coastmath.engine.tax_engine import calculate


def _hi(**kw):
    return calculate(state_code="HI", tax_year=2026, holder_age=60, deductions=0, **kw).state


@pytest.mark.parametrize("kw, expected", [
    # TI 232,000; base max(32,000, 48,000) = 48,000
    # 2,539.20 + 184,000 x 7.25% (13,340) = 15,879.20 (ordinary 17,096.20)
    (dict(gross_income=40_000, capital_gains=200_000, filing_status="single"), 15_879.20),
    # TI 484,000; base max(84,000, 96,000) = 96,000
    # 5,078.40 + 388,000 x 7.25% (28,130) = 33,208.40 (ordinary 35,992.40)
    (dict(gross_income=100_000, capital_gains=400_000,
          filing_status="married_filing_jointly", spouse_age=60), 33_208.40),
    # TI 228,000; base 72,000; 3,808.80 + 156,000 x 7.25% (11,310) = 15,118.80
    (dict(gross_income=40_000, capital_gains=200_000, filing_status="head_of_household"), 15_118.80),
    # (A) governs: TI 192,000, base 142,000
    # 2,539.20 + 77,000 x 7.6% (5,852) + 17,000 x 7.9% (1,343) = 9,734.20
    # + 50,000 x 7.25% (3,625) = 13,359.20 (ordinary 13,743.70)
    (dict(gross_income=150_000, capital_gains=50_000, filing_status="single"), 13_359.20),
    # Netted first: 200,000 - 50,000 carryforward = 150,000; TI 182,000
    # 2,539.20 + 134,000 x 7.25% (9,715) = 12,254.20 (ordinary 12,918.70)
    (dict(gross_income=40_000, capital_gains=200_000, capital_loss_carryforward=50_000,
          filing_status="single"), 12_254.20),
    # Qualified dividends stay ordinary: TI 232,000, 2,539.20 + 5,852 + 3,950
    # + 50,000 x 8.25% (4,125) + 7,000 x 9% (630) = 17,096.20
    (dict(gross_income=40_000, qualified_dividends=200_000, filing_status="single"), 17_096.20),
    # Gains entirely below the 7.25% band: TI 40,000 ordinary, no cap effect
    # 1,675.20 + 4,000 x 7.2% (288) = 1,963.20
    (dict(gross_income=18_000, capital_gains=30_000, filing_status="single"), 1_963.20),
])
def test_hi_capital_gain_rate_cap(kw, expected):
    assert _hi(**kw) == pytest.approx(expected, abs=0.01)

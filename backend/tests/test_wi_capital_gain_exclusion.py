"""Wisconsin subtracts 30% of net long-term capital gain.

Wis. Stat. 71.05(6)(b)9
(https://docs.legis.wisconsin.gov/statutes/statutes/71/i/05/6/b/9): subtract
from federal AGI, "On assets held more than one year ... 30 percent of the
capital gain as computed under the internal revenue code", with gains and
losses netted first. Qualified dividends are not capital gain.

2026 WI data (2025 schedules, maximum standard deduction): single $13,560 and
3.5% / 4.4% / 5.3% breaks at 14,680 / 50,480; joint $25,110 and breaks at
19,580 / 67,300. 14,680 x 3.5% = 513.80; 35,800 x 4.4% = 1,575.20;
19,580 x 3.5% = 685.30; 47,720 x 4.4% = 2,099.68.
"""

import pytest

from coastmath.engine.tax_engine import calculate


def _wi(**kw):
    return calculate(state_code="WI", tax_year=2026, holder_age=60, deductions=0, **kw).state


@pytest.mark.parametrize("kw, expected", [
    # 40,000 + 60,000 - 30% x 60,000 = 82,000; TI 82,000 - 13,560 = 68,440
    # 513.80 + 1,575.20 + 17,960 x 5.3% (951.88) = 3,040.88
    (dict(gross_income=40_000, capital_gains=60_000, filing_status="single"), 3_040.88),
    # 80,000 + 200,000 - 60,000 = 220,000; TI 220,000 - 25,110 = 194,890
    # 685.30 + 2,099.68 + 127,590 x 5.3% (6,762.27) = 9,547.25
    (dict(gross_income=80_000, capital_gains=200_000,
          filing_status="married_filing_jointly", spouse_age=60), 9_547.25),
    # Netted first: 60,000 - 20,000 carryforward = 40,000 net gain; exclusion 12,000
    # 40,000 + 40,000 - 12,000 = 68,000; TI 54,440
    # 513.80 + 1,575.20 + 3,960 x 5.3% (209.88) = 2,298.88
    (dict(gross_income=40_000, capital_gains=60_000, capital_loss_carryforward=20_000,
          filing_status="single"), 2_298.88),
    # Qualified dividends are not capital gain: TI 100,000 - 13,560 = 86,440
    # 513.80 + 1,575.20 + 35,960 x 5.3% (1,905.88) = 3,994.88
    (dict(gross_income=40_000, qualified_dividends=60_000, filing_status="single"), 3_994.88),
])
def test_wi_long_term_capital_gain_exclusion(kw, expected):
    assert _wi(**kw) == pytest.approx(expected, abs=0.01)

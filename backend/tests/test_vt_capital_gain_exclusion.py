"""Vermont excludes the first $5,000 of net capital gain.

32 V.S.A. 5811(21)(B)(ii)
(https://legislature.vermont.gov/statutes/section/32/151/05811) decreases
Vermont taxable income by "the first $5,000.00" of adjusted net capital gain
income (IRC 1(h)) reduced by qualified dividends, or by 40% of gains on assets
held more than three years other than publicly traded securities; the decrease
"shall not exceed 40 percent of federal taxable income". 2025 Schedule IN-153:
line 9 is the smaller of net capital gain and $5,000, line 21 the smaller of
that and 40% of federal taxable income. The $5,000 is not indexed.

VT 2026 data: 3.35% to 50,750 then 6.6% (single); 3.35% to 84,700 then 6.6%
(MFJ); deduction 7,650 / 15,300; exemption 5,300 per filer.
"""

import pytest

from coastmath.engine.tax_engine import calculate


def _vt(wages, filing_status="single", tax_year=2026, **kw):
    return calculate(gross_income=wages, earned_income=wages, w2_income=wages, deductions=0,
                     filing_status=filing_status, state_code="VT", tax_year=tax_year,
                     holder_age=45, spouse_age=45 if filing_status == "married_filing_jointly" else None,
                     **kw).state


@pytest.mark.parametrize("wages, kw, expected", [
    # AGI 80,000 - 7,650 - 5,300 = 67,050; less 5,000 = 62,050
    # 50,750 x 3.35% (1,700.125) + 11,300 x 6.6% (745.80)
    (60_000, dict(capital_gains=20_000), 2_445.925),
    # AGI 200,000 - 15,300 - 10,600 = 174,100; less 5,000 = 169,100
    # 84,700 x 3.35% (2,837.45) + 84,400 x 6.6% (5,570.40)
    (150_000, dict(capital_gains=50_000, filing_status="married_filing_jointly"), 8_407.85),
    # Gain below $5,000 is fully excluded: AGI 63,000 -> taxable 50,050
    # less 3,000 = 47,050 x 3.35%
    (60_000, dict(capital_gains=3_000), 47_050 * 0.0335),
    # Qualified dividends get no exclusion: taxable 67,050
    # 1,700.125 + 16,300 x 6.6% (1,075.80)
    (60_000, dict(qualified_dividends=20_000), 2_775.925),
    # Netted first: 8,000 gain - 6,000 carryforward = 2,000 excluded
    # AGI 62,000 (3,000 loss limit not reached) -> taxable 49,050; less 2,000
    # = 47,050 x 3.35%
    (60_000, dict(capital_gains=8_000, capital_loss_carryforward=6_000), 47_050 * 0.0335),
])
def test_vt_flat_capital_gain_exclusion(wages, kw, expected):
    assert _vt(wages, **kw) == pytest.approx(expected, abs=0.01)


def test_vt_flat_capital_gain_exclusion_2025():
    # The exclusion predates 2025: a 20,000 gain leaves the same Vermont
    # taxable income as 15,000 of (unexcluded) qualified dividends.
    assert _vt(60_000, tax_year=2025, capital_gains=20_000) == pytest.approx(
        _vt(60_000, tax_year=2025, qualified_dividends=15_000), abs=0.01)
    assert _vt(60_000, tax_year=2025, capital_gains=20_000) < _vt(
        60_000, tax_year=2025, qualified_dividends=20_000)


def test_vt_exclusion_capped_at_40_percent_of_federal_taxable_income():
    # Wages 10,000 + gain 5,000: federal TI = 15,000 - 16,100 (2026 single
    # standard deduction) = 0, so the cap is 0 and no gain is excluded.
    # VT taxable 15,000 - 7,650 - 5,300 = 2,050 x 3.35% = 68.675
    assert _vt(10_000, capital_gains=5_000) == pytest.approx(68.675, abs=0.01)
    # Wages 15,000 + gain 5,000: federal TI 3,900; cap 1,560.
    # VT taxable 7,050 - 1,560 = 5,490 x 3.35% = 183.915
    assert _vt(15_000, capital_gains=5_000) == pytest.approx(183.915, abs=0.01)

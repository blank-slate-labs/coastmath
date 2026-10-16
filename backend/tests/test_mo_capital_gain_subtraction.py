"""Missouri subtracts all federal capital gain from Missouri AGI (2025 on).

RSMo 143.121.3(14)(a) (https://revisor.mo.gov/main/OneSection.aspx?section=143.121):
for tax years beginning on or after January 1, 2025, Missouri AGI excludes
"one hundred percent of all income reported as a capital gain for federal
income tax purposes". Qualified dividends are not capital gain. The private
pension exemption phase-out (RSMo 143.124.3-4) and the federal-tax deduction
percentage (RSMo 143.171) are measured on Missouri AGI, so the gain is out of
those bases too.

MO rate chart: 0% to $1,313, then 2/2.5/3/3.5/4/4.5% per $1,313 band to
$9,191 ($256.035 cumulative), 4.7% above. 2026 federal standard deduction
$16,100 single, $32,200 joint, +$1,650 per aged joint filer (RSMo 143.131).
"""

import pytest

from coastmath.engine.state_retirement_exclusion import RetirementIncome
from coastmath.engine.tax_engine import calculate


def mo_schedule(taxable):
    """MO single schedule; the engine applies it as-is to every filer here."""
    tax, lower = 0.0, 0.0
    for upper, rate in ((1_313, 0.0), (2_626, .02), (3_939, .025), (5_252, .03),
                        (6_565, .035), (7_878, .04), (9_191, .045), (float("inf"), .047)):
        tax += rate * max(0.0, min(taxable, upper) - lower)
        lower = upper
    return tax


def mo(**kw):
    return calculate(state_code="MO", tax_year=2026, deductions=0, **kw)


def test_schedule_matches_hand_arithmetic():
    # 26.26 + 32.825 + 39.39 + 45.955 + 52.52 + 59.085 + 4.7% x 14,709 = 947.358
    assert mo_schedule(23_900) == pytest.approx(947.358)


@pytest.mark.parametrize("gain", [0, 100_000])
def test_single_gain_is_not_taxed(gain):
    # MO AGI = 40,000 + gain - gain; TI = 40,000 - 16,100 = 23,900 -> $947.36.
    result = mo(gross_income=40_000, capital_gains=gain, filing_status="single", holder_age=60)
    assert result.state == pytest.approx(947.36, abs=.01)


@pytest.mark.parametrize("gain", [0, 200_000])
def test_joint_gain_is_not_taxed(gain):
    # TI = 60,000 - (32,200 + 2 x 1,650) = 24,500. On the engine's doubled
    # joint schedule (each band $2,626): 52.52 + 65.65 + 78.78 + 91.91
    # + 105.04 + 118.17 + 4.7% x (24,500 - 18,382) = 799.616.
    result = mo(gross_income=60_000, capital_gains=gain, filing_status="married_filing_jointly",
                holder_age=67, spouse_age=67)
    assert result.state == pytest.approx(799.62, abs=.01)


def test_qualified_dividends_stay_taxable():
    # $10,000 qualified dividends are not capital gain: TI 33,900,
    # 947.358 + 4.7% x 10,000 = 1,417.358, with or without a $100,000 gain.
    for gain in (0, 100_000):
        result = mo(gross_income=40_000, capital_gains=gain, qualified_dividends=10_000,
                    filing_status="single", holder_age=60)
        assert result.state == pytest.approx(1_417.36, abs=.01)


def test_private_pension_phase_out_excludes_the_gain():
    # $24,000 IRA income and a $50,000 gain. MO AGI = 24,000 < $25,000, so
    # the full $6,000 private-pension exemption applies (no phase-out):
    # TI = 24,000 - 6,000 - 16,100 = 1,900; tax = 2% x 587 = 11.74.
    # Measuring the phase-out on federal AGI (74,000) would remove the
    # exemption and give TI 7,900 (tax 197.94).
    result = mo(gross_income=24_000, capital_gains=50_000, filing_status="single", holder_age=60,
                retirement_income=[RetirementIncome(age=60, amounts={"ira": 24_000})])
    assert mo_schedule(1_900) == pytest.approx(11.74)
    assert result.state == pytest.approx(11.74, abs=.01)


def test_federal_tax_deduction_tier_excludes_the_gain():
    # Statutory rules: MO AGI 40,000 is in the $25,001-$50,000 tier (25% of
    # federal liability, capped at $5,000), not the 0% tier above $125,000
    # that the federal AGI of 140,000 would select.
    result = mo(gross_income=40_000, earned_income=40_000, capital_gains=100_000,
                filing_status="single", holder_age=45, settings={"state_deduction_rules": True})
    liability = result.federal + result.capital_gains_tax
    deduction = min(.25 * liability, 5_000)
    assert deduction > 0
    assert result.state_federal_tax_subtraction == pytest.approx(deduction, abs=1)
    assert result.state == pytest.approx(mo_schedule(23_900 - deduction), abs=.05)

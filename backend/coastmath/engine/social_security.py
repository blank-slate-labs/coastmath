"""Social Security benefit estimation.

The income-based estimator is retained for backward compatibility.  The PIA
path accepts a user-provided monthly Primary Insurance Amount (PIA), then
applies the existing birth-year FRA and monthly claiming factors.  It does not
derive AIME, reconstruct covered earnings, or model household benefits.
"""

import math

# 2026 SSA: wage base $184,500; max monthly retired-worker benefit at FRA $4,152.
# https://www.ssa.gov/oact/cola/cbb.html  (contribution and benefit base)
# https://www.ssa.gov/oact/cola/examplemax.html  (maximum-taxable benefit examples)
_SS_MAX_BENEFIT_MONTHLY = 4_152  # at FRA
_SS_WAGE_BASE = 184_500  # max taxable earnings

def full_retirement_age(birth_year: int = 1960) -> float:
    """SSA retired-worker FRA; inputs have month precision, not birth day.

    https://www.ssa.gov/benefits/retirement/planner/agereduction.html
    """
    if birth_year <= 1937:
        return 65.0
    if birth_year <= 1942:
        return 65.0 + (birth_year - 1937) / 6
    if birth_year <= 1954:
        return 66.0
    return min(67.0, 66.0 + (birth_year - 1954) / 6)


def claiming_factor(claiming_age: float, birth_year: int = 1960) -> float:
    """Monthly actuarial reduction and cohort delayed credits through age 70.

    https://www.ssa.gov/OACT/quickcalc/early_late.html
    """
    months = round((min(70, max(62, claiming_age)) - full_retirement_age(birth_year)) * 12)
    if months < 0:
        return 1 - min(-months, 36) * (5 / 900) - max(0, -months - 36) * (5 / 1200)
    if birth_year <= 1924:
        annual_credit = .03
    elif birth_year <= 1942:
        annual_credit = .035 + ((birth_year - 1925) // 2) * .005
    else:
        annual_credit = .08
    return 1 + months * annual_credit / 12


def estimate_ss_benefit(
    current_annual_income: float,
    claiming_age: float = 67,
    birth_year: int = 1960,
) -> float:
    """Estimate annual Social Security benefit.

    Uses simplified replacement rate model:
    - First $15k: 90% replacement
    - $15k-$90k: 32% replacement
    - Above $90k: 15% replacement

    Returns annual benefit in dollars.
    """
    capped = min(current_annual_income, _SS_WAGE_BASE)

    if capped <= 15_000:
        base = capped * 0.90
    elif capped <= 90_000:
        base = 15_000 * 0.90 + (capped - 15_000) * 0.32
    else:
        base = 15_000 * 0.90 + 75_000 * 0.32 + (capped - 90_000) * 0.15

    factor = claiming_factor(claiming_age, birth_year)
    adjusted = base * factor

    max_annual = _SS_MAX_BENEFIT_MONTHLY * 12 * factor
    return min(adjusted, max_annual)


def expected_benefit_fraction(expected_benefit_percentage: float = 100.0) -> float:
    """Convert an expected-benefit percentage to a validated fraction.

    The percentage is a planning assumption applied after the PIA and claiming
    adjustment.  SSA's PIA calculation and claiming rules remain separate
    inputs; this control does not imply an earnings-record calculation.
    """
    if not math.isfinite(expected_benefit_percentage) or not 0 <= expected_benefit_percentage <= 100:
        raise ValueError("expected_benefit_percentage must be between 0 and 100")
    return expected_benefit_percentage / 100.0


def estimate_ss_benefit_from_pia(
    monthly_pia: float,
    claiming_age: float = 67,
    birth_year: int = 1960,
    expected_benefit_percentage: float = 100.0,
) -> float:
    """Estimate a retired-worker annual benefit from a monthly PIA.

    ``monthly_pia`` is the worker's benefit at full retirement age.  The
    existing SSA claiming factor is applied once, and the resulting annual
    amount is the final claimed benefit suitable for ``IncomeStream.annual_amount``.
    The expected percentage is an explicit planning haircut or confidence
    assumption, expressed in percent.

    This bounded path intentionally does not calculate AIME from one salary,
    recreate a 35-year covered-earnings record, or add spousal/survivor or
    earnings-test behavior.

    SSA references:
    - https://www.ssa.gov/OACT/COLA/piaformula.html
    - https://www.ssa.gov/OACT/quickcalc/early_late.html
    """
    if not math.isfinite(monthly_pia) or monthly_pia < 0:
        raise ValueError("monthly_pia must be a finite nonnegative amount")
    fraction = expected_benefit_fraction(expected_benefit_percentage)
    return monthly_pia * 12.0 * claiming_factor(claiming_age, birth_year) * fraction

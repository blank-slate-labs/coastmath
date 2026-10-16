"""SEPP 72(t) calculator — three IRS-approved distribution methods.

Substantially Equal Periodic Payments allow penalty-free early withdrawals
from retirement accounts before age 59.5.  Once started, distributions must
continue for 5 years or until age 59.5, whichever is LATER.

IRS divisor data loaded from coastmath/data/irs_uniform_lifetime_table.json.
Primary SEPP source: IRS Notice 2022-6.
https://www.irs.gov/pub/irs-drop/n-22-06.pdf

Mortality data: IRS 2022 unisex mortality table from Treas. Reg. §1.401(a)(9)-9(e),
used for the fixed annuitization method per IRS Notice 2022-6.
XXX The current mortality table is a coarse internal approximation, not a
verbatim transcription of every official q_x value.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

# IRS Single Life Expectancy Table (Treas. Reg. §1.401(a)(9)-9, 2022 update),
# used for the fixed amortization method loan term.
from coastmath.engine.single_life import SINGLE_LIFE_TABLE as _SINGLE_LIFE_TABLE

# ---------------------------------------------------------------------------
# Load IRS divisor table once at module level
# ---------------------------------------------------------------------------

_DATA_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "irs_uniform_lifetime_table.json"
)

with open(_DATA_FILE) as _f:
    _IRS_DATA = json.load(_f)

_DIVISORS: dict[int, float] = {int(k): float(v) for k, v in _IRS_DATA["divisors"].items()}

_VALID_METHODS = frozenset({"rmd_method", "fixed_amortization", "fixed_annuitization"})

# ---------------------------------------------------------------------------
# IRS 2022 unisex mortality rates (q_x) — Treas. Reg. §1.401(a)(9)-9(e)
# Rev. Rul. 2023-2, gender-neutral annuity mortality table.
# q_x = probability of dying within the year for a person of age x.
# Used for computing annuity factors in the fixed annuitization method.
# ---------------------------------------------------------------------------

_IRS_MORTALITY_QX_ANCHORS: dict[int, float] = {
    50: 0.003, 51: 0.003, 52: 0.004, 53: 0.004, 54: 0.005,
    55: 0.005, 56: 0.006, 57: 0.007, 58: 0.008, 59: 0.009,
    60: 0.010, 61: 0.011, 62: 0.012, 63: 0.013, 64: 0.015,
    65: 0.016, 66: 0.018, 67: 0.020, 68: 0.022, 69: 0.024,
    70: 0.027, 71: 0.030, 72: 0.033, 73: 0.037, 74: 0.042,
    75: 0.047, 76: 0.053, 77: 0.060, 78: 0.068, 79: 0.077,
    80: 0.088, 81: 0.100, 82: 0.113, 83: 0.128, 84: 0.145,
    85: 0.165, 86: 0.187, 87: 0.211, 88: 0.238, 89: 0.268,
    90: 0.300, 95: 0.450, 100: 0.600,
}


def _get_qx(age: int) -> float:
    """Get mortality rate q_x for a given age, interpolating if needed."""
    if age > 105:
        return 1.0
    if age in _IRS_MORTALITY_QX_ANCHORS:
        return _IRS_MORTALITY_QX_ANCHORS[age]
    # Linear interpolation between anchor ages
    anchors = sorted(_IRS_MORTALITY_QX_ANCHORS.keys())
    if age < anchors[0]:
        return _IRS_MORTALITY_QX_ANCHORS[anchors[0]]
    for i in range(len(anchors) - 1):
        lo, hi = anchors[i], anchors[i + 1]
        if lo < age < hi:
            frac = (age - lo) / (hi - lo)
            return _IRS_MORTALITY_QX_ANCHORS[lo] + frac * (
                _IRS_MORTALITY_QX_ANCHORS[hi] - _IRS_MORTALITY_QX_ANCHORS[lo]
            )
    return _IRS_MORTALITY_QX_ANCHORS[anchors[-1]]


def _compute_annuity_factor(age: int, rate: float) -> float:
    """Compute mortality-based annuity factor per IRS Notice 2022-6.

    Uses annuity-immediate convention (first payment discounted one period):

    AF(age, rate) = sum over k from 1 to (110 - age) of:
        survival_prob[age + k] * (1 / (1 + rate))^k

    Where survival_prob[age] = 1.0 and for subsequent ages:
        survival_prob[age + k] = product of (1 - q_x) for x from age to age+k-1

    Note: IRS Notice 2022-6 prescribes annuity-immediate (k starts at 1),
    NOT annuity-due (k starts at 0).  The k=0 term (discount^0 = 1.0)
    is excluded because the first payment is discounted one full period.
    """
    max_age = 110
    if age >= max_age:
        return 1.0

    af = 0.0
    survival = 1.0
    discount = 1.0 / (1.0 + rate) if rate > 0 else 1.0

    for k in range(1, max_age - age + 1):
        survival *= (1.0 - _get_qx(age + k - 1))
        af += survival * (discount ** k)

    return af


def single_life_expectancy(age: int) -> float:
    """Look up the Single Life Expectancy Table value for the given age.

    Reads the IRS 2022 Single Life Table (Pub. 590-B Appendix B, Table I, via
    ``coastmath.engine.single_life``), which covers ages 0 to 120. Any integer
    age is accepted: below 0 uses the age-0 entry and above 120 the age-120
    entry. Interpolates linearly between the two nearest ages if exact age is
    not present.
    """
    if age in _SINGLE_LIFE_TABLE:
        return _SINGLE_LIFE_TABLE[age]
    ages = sorted(_SINGLE_LIFE_TABLE.keys())
    if age < ages[0]:
        return _SINGLE_LIFE_TABLE[ages[0]]
    if age > ages[-1]:
        return _SINGLE_LIFE_TABLE[ages[-1]]
    for i in range(len(ages) - 1):
        lo, hi = ages[i], ages[i + 1]
        if lo < age < hi:
            frac = (age - lo) / (hi - lo)
            return _SINGLE_LIFE_TABLE[lo] + frac * (_SINGLE_LIFE_TABLE[hi] - _SINGLE_LIFE_TABLE[lo])
    return _SINGLE_LIFE_TABLE[ages[-1]]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def calculate_sepp(
    account_balance: float,
    owner_age: int,
    method: str,
    interest_rate: float = 0.05,
    life_expectancy_divisor: float | None = None,
) -> float:
    """Calculate the annual SEPP distribution amount.

    Args:
        account_balance: Current balance of the retirement account.
        owner_age: Owner's current age (integer).
        method: One of 'rmd_method', 'fixed_amortization', 'fixed_annuitization'.
        interest_rate: Reasonable interest rate for amortization/annuitization.
        life_expectancy_divisor: Override for the IRS table divisor. If None,
            looked up from the Uniform Lifetime Table by owner_age.

    Returns:
        Annual SEPP distribution amount.

    Raises:
        ValueError: If method is invalid or age is outside the IRS table range
            and no override divisor is provided.
    """
    if method not in _VALID_METHODS:
        raise ValueError(
            f"Invalid SEPP method: {method!r}. Must be one of {sorted(_VALID_METHODS)}"
        )

    if life_expectancy_divisor is not None:
        divisor = life_expectancy_divisor
    elif owner_age in _DIVISORS:
        divisor = _DIVISORS[owner_age]
    else:
        # SEPP typically applies to ages < 72 where Uniform Lifetime Table
        # has no entry — use Single Life Expectancy Table per IRS guidance
        divisor = single_life_expectancy(owner_age)

    if divisor <= 0:
        raise ValueError(f"Life expectancy divisor must be positive, got {divisor}")

    if account_balance <= 0:
        return 0.0

    if method == "rmd_method":
        return account_balance / divisor

    r = interest_rate

    if method == "fixed_amortization":
        # Use IRS Single Life Expectancy Table for the loan term n,
        # unless an explicit override divisor was provided
        n = (
            life_expectancy_divisor
            if life_expectancy_divisor is not None
            else single_life_expectancy(owner_age)
        )
        if r == 0:
            return account_balance / n
        return account_balance * (r / (1 - math.pow(1 + r, -n)))

    # fixed_annuitization — IRS mortality-based annuity factor per Notice 2022-6
    annuity_factor = _compute_annuity_factor(owner_age, r)

    return account_balance / annuity_factor


# Notice 2022-6 sec. 2.02(c): the interest rate may be as high as the greater
# of 5% or 120% of the federal mid-term rate for either of the two months
# before the first distribution. Monthly rates: data/sepp_mid_term_rates.json
# (citations in its ``_sources``). Months not in the file fall back
# to the 5% floor.
_MID_TERM = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "sepp_mid_term_rates.json").read_text()
)
SEPP_VALIDATED_RATE_CEILING = float(_MID_TERM["floor_rate"])
_MID_TERM_120 = {key: float(value) for key, value in _MID_TERM["rates_120_percent_mid_term"].items()}


def first_distribution_month(birth_year: int, birth_month: int | None, start_age: float) -> tuple[int, int]:
    """(year, month) of the series' first planning installment, as in sepp_year_fraction."""
    index = birth_year * 12 + (birth_month or 1) - 1 + math.ceil(start_age * 12 - 1e-9)
    return index // 12, index % 12 + 1


def sepp_rate_ceiling(first_year: int | None, first_month: int | None) -> float:
    """Highest interest rate Notice 2022-6 allows for a series starting then.

    The greater of 5% and 120% of the federal mid-term rate for either of the
    two months before the first distribution; 5% when those months are unknown.
    """
    ceiling = SEPP_VALIDATED_RATE_CEILING
    if first_year is None or first_month is None:
        return ceiling
    index = first_year * 12 + first_month - 1
    for prior in (index - 1, index - 2):
        rate = _MID_TERM_120.get(f"{prior // 12:04d}-{prior % 12 + 1:02d}")
        if rate is not None:
            ceiling = max(ceiling, rate)
    return ceiling
# A payment is a whole-dollar figure; one dollar of rounding is not a different series.
SEPP_AMOUNT_TOLERANCE = 1.0


def custom_amount_qualifies(
    annual_amount: float,
    balance: float,
    owner_age: int,
    method: str,
    interest_rate: float,
    rate_ceiling: float = SEPP_VALIDATED_RATE_CEILING,
) -> bool:
    """Whether a custom yearly amount equals what an approved method yields.

    Evidence is a recomputation: the amount must match the fixed amortization
    payment for the entered balance, age and rate, and the rate must not exceed
    ``rate_ceiling`` (``sepp_rate_ceiling``; 5% when the start month is unknown).
    The RMD method changes every year and the annuitization factor rests on an
    approximate table, so neither can vouch for a fixed custom amount. An amount
    that does not match is an ordinary early withdrawal.
    """
    if method != "fixed_amortization" or interest_rate > rate_ceiling + 1e-12:
        return False
    approved = calculate_sepp(balance, owner_age, method, interest_rate)
    return approved > 0 and abs(annual_amount - approved) <= SEPP_AMOUNT_TOLERANCE


def get_sepp_end_age(start_age: float) -> float:
    """Return the age at which SEPP distributions can stop.

    IRS rule: 5 years or age 59.5, whichever is LATER.
    """
    return max(start_age + 5, 59.5)


def is_sepp_active(current_age: float, start_age: float) -> bool:
    """The series is required up to, but excluding, its modification date."""
    return start_age <= current_age < get_sepp_end_age(start_age)


def sepp_year_fraction(age: int, start_age: float, birth_month: int | None = None,
                       simulation_fraction: float = 1.0, active_until: float = 1.0) -> float:
    """Monthly planning installments from start age to the later anniversary.

    ``age`` and ``birth_month`` are the IRA owner's. Month precision matches
    plan birth and start-age inputs. The last required month precedes the
    five-year anniversary / age 59.5 modification month. ``active_until`` is
    the share of the year the owner is alive; the requirement ends at death.
    """
    birthday = (birth_month or 1) - 1
    start = birthday + math.ceil(start_age * 12 - 1e-9)
    end = birthday + math.ceil(get_sepp_end_age(start_age) * 12 - 1e-9)
    year_start = age * 12
    active_start = max(start, year_start + 12 * (1 - simulation_fraction))
    active_end = min(end, year_start + 12 * max(0.0, min(1.0, active_until)))
    return max(0.0, active_end - active_start) / 12

"""RMD calculator — Required Minimum Distributions per SECURE Act 2.0.

Uses IRS Uniform Lifetime Table divisors loaded from
coastmath/data/irs_uniform_lifetime_table.json.
Sources: IRS Pub. 590-B and 26 CFR 1.401(a)(9)-9.
https://www.irs.gov/publications/p590b
https://www.ecfr.gov/current/title-26/section-1.401(a)(9)-9
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

# The IRS Single Life Expectancy Table (2022) gives inherited IRA divisors.
from coastmath.engine.single_life import single_life_divisor

# ---------------------------------------------------------------------------
# Load IRS data once at module level
# ---------------------------------------------------------------------------

_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "irs_uniform_lifetime_table.json"

with open(_DATA_FILE) as _f:
    _IRS_DATA = json.load(_f)

# The printed Uniform Lifetime Table (ages 72+). SEPP and the RMD-table
# withdrawal strategy read it too and fall back to Single Life below 72.
_DIVISORS: dict[int, float] = {int(k): v for k, v in _IRS_DATA["divisors"].items()}
_MIN_DIVISOR: float = min(_DIVISORS.values())
_MAX_TABLE_AGE: int = max(_DIVISORS.keys())
# Lifetime RMD divisors, extended below the printed table with the derived
# values for the earliest start ages a plan may assume (70 and 71).
_RMD_DIVISORS: dict[int, float] = {
    **{int(k): v for k, v in _IRS_DATA["derived_divisors"].items()},
    **_DIVISORS,
}
_INHERITED_MAX_YEARS: int = _IRS_DATA["inherited_ira"]["max_years"]

# Joint Life and Last Survivor Expectancy (Treas. Reg. 1.401(a)(9)-9(d), Table 3),
# owner ages 70+.
_JOINT_FILE = _DATA_FILE.with_name("irs_joint_life_table.json")
with open(_JOINT_FILE) as _jf:
    _JOINT_TABLE: dict[int, list[float]] = {int(k): v for k, v in json.load(_jf)["table"].items()}
_JOINT_MIN_OWNER_AGE: int = min(_JOINT_TABLE)
_JOINT_MAX_OWNER_AGE: int = max(_JOINT_TABLE)

# ---------------------------------------------------------------------------
# SECURE Act 2.0 RMD start age — birth-year dependent.
# IRS Pub. 590-B reflects age 73 for 1951-1959 and age 75 for 1960+.
# XXX Taxpayers who reached RMD age under pre-2020 age-70.5 rules need
# first-RMD-year history; birth year alone is not enough to model every legacy case.
# ---------------------------------------------------------------------------


def get_rmd_start_age(birth_year: int) -> int:
    """Return the RMD start age based on birth year per SECURE Act 2.0.

    - Born 1950 or earlier -> 72
    - Born 1951-1959 -> 73
    - Born 1960 or later -> 75
    """
    if birth_year <= 1950:
        return 72
    if birth_year <= 1959:
        return 73
    return 75


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rmd_start_age_override(tax_settings: Mapping | None, owner: str) -> int | None:
    """The owner's assumed RMD start age from ``tax_settings.rmd_start_ages``.

    None means the SECURE 2.0 schedule applies. Plans use it to model a
    possible change in law; it never changes inherited-account rules.
    """
    value = ((tax_settings or {}).get("rmd_start_ages") or {}).get(owner)
    return None if value is None else int(value)


def is_rmd_required(owner_age: int, birth_year: int, start_age: int | None = None) -> bool:
    """Return True if the owner must take RMDs based on age and birth year.

    ``start_age`` replaces the SECURE 2.0 start age for a plan that models a
    different law (``tax_settings.rmd_start_ages``); None keeps the statute.
    """
    return owner_age >= (get_rmd_start_age(birth_year) if start_age is None else start_age)


def joint_life_divisor(owner_age: int, spouse_age: int) -> float:
    """Table 3 divisor for an owner and a spouse, both at year-end age.

    Owner ages below the first row (70, the earliest assumable start age)
    cannot owe a lifetime RMD and use that row; ages past the last row and spouse ages past 120 use the final
    printed value.
    """
    row = _JOINT_TABLE[min(max(owner_age, _JOINT_MIN_OWNER_AGE), _JOINT_MAX_OWNER_AGE)]
    return row[min(max(spouse_age, 0), len(row) - 1)]


def spouse_more_than_ten_years_younger(
    owner_birth_year: int,
    spouse_birth_year: int,
    owner_birth_month: int | None = None,
    spouse_birth_month: int | None = None,
) -> bool:
    """Whether the spouse is *more than* ten years younger (Reg. 1.401(a)(9)-9(c)(2)).

    Uses birth months when both are known, so exactly ten years apart is not
    enough. Without both months, only a gap of more than ten calendar years
    counts; an ambiguous ten-year gap keeps the Uniform Lifetime Table.
    """
    if owner_birth_month and spouse_birth_month:
        return (spouse_birth_year * 12 + spouse_birth_month) - (owner_birth_year * 12 + owner_birth_month) > 120
    return spouse_birth_year - owner_birth_year > 10


def calculate_rmd(
    account_balance: float,
    owner_age: int,
    birth_year: int,
    prior_year_balance: float | None = None,
    spouse_age: int | None = None,
    start_age: int | None = None,
) -> float:
    """Calculate the Required Minimum Distribution for a given year.

    Args:
        account_balance: Current balance (used only for the zero-check).
        owner_age: Owner's age in the distribution year.
        birth_year: Owner's birth year (determines RMD start age).
        prior_year_balance: Prior-year Dec 31 balance for the RMD divisor
            calculation (IRS requirement). Falls back to account_balance
            if not provided.
        spouse_age: Spouse's year-end age when the caller has established
            that the spouse is the sole beneficiary and more than ten years
            younger; the Joint Life and Last Survivor divisor then applies.
        start_age: The owner's RMD start age in place of the SECURE 2.0
            schedule; None keeps the statute.

    Returns:
        The RMD amount, or 0.0 if not yet required or balance is zero.
    """
    if account_balance <= 0 or not is_rmd_required(owner_age, birth_year, start_age):
        return 0.0

    basis = prior_year_balance if prior_year_balance is not None else account_balance

    if spouse_age is not None:
        divisor = joint_life_divisor(owner_age, spouse_age)
    elif owner_age > _MAX_TABLE_AGE:
        divisor = _MIN_DIVISOR
    else:
        divisor = _RMD_DIVISORS[owner_age]

    return basis / divisor


def calculate_inherited_ira_rmd(
    account_balance: float,
    inherited_year: int,
    current_year: int,
    beneficiary_age: int | None = None,
    beneficiary_type: str = "non_edb",
    prior_year_balance: float | None = None,
    *,
    distribution_method: str = "automatic",
    decedent_birth_year: int | None = None,
    decedent_died_after_rbd: bool | None = None,
    beneficiary_is_minor_child: bool = False,
    year_of_death_rmd_remaining: float = 0.0,
    is_roth: bool = False,
) -> float:
    """Pub.590-B beneficiary distributions, including the 2025 final rules.

    A spouse can elect own-account treatment or remain a beneficiary; EDBs
    use life expectancy unless they elect an eligible ten-year distribution.
    Non-EDBs after the RBD take annual distributions plus the year10 balance.
    Pre-2020 individual beneficiaries retain life expectancy treatment.
    Missing legacy RBD metadata preserves the previous before-RBD assumption;
    the simulation warns explicitly until the user supplies that history.
    """
    if account_balance <= 0 or current_year < inherited_year:
        return 0.0
    elapsed = current_year - inherited_year
    after_rbd = bool(decedent_died_after_rbd) and not is_roth
    if elapsed == 0:
        return min(account_balance, max(0.0, year_of_death_rmd_remaining)) if not is_roth else 0.0
    basis = account_balance if prior_year_balance is None else prior_year_balance
    if distribution_method == "spousal_rollover":
        if beneficiary_type != "spouse" or beneficiary_age is None:
            raise ValueError("Own-account treatment requires a spouse beneficiary with a known age")
        return 0.0 if is_roth else min(account_balance, calculate_rmd(account_balance,beneficiary_age,
            current_year-beneficiary_age,prior_year_balance=basis))
    ten_year = distribution_method == "ten_year" or (beneficiary_type == "non_edb" and inherited_year >= 2020)
    if distribution_method == "life_expectancy" and beneficiary_type == "non_edb" and inherited_year >= 2020:
        raise ValueError("A non-eligible beneficiary remains subject to the ten-year deadline")
    if distribution_method == "ten_year" and beneficiary_type != "non_edb" and after_rbd:
        raise ValueError("Eligible beneficiaries cannot elect the ten-year rule after the owner's required beginning date")
    if ten_year and elapsed >= 10:
        return account_balance
    if beneficiary_is_minor_child and beneficiary_age is not None and inherited_year >= 2020:
        majority_year = current_year - beneficiary_age + 21
        if current_year >= majority_year + 10:
            return account_balance
    if ten_year and not after_rbd:
        return 0.0
    # IRS Notices2022-53/2023-54/2024-35 waive specified annual RMDs through
    # 2024 for post-2019 deaths under the ten-year rule; the deadline remains.
    if ten_year and current_year < 2025:
        return 0.0
    if beneficiary_age is None:
        raise ValueError("Beneficiary age is required for life expectancy distributions")
    if beneficiary_type == "spouse":
        if not after_rbd and decedent_birth_year is not None:
            first_year = max(inherited_year + 1,decedent_birth_year + get_rmd_start_age(decedent_birth_year))
            if current_year < first_year:
                return 0.0
        divisor = single_life_divisor(beneficiary_age)
    else:
        first_year_age = beneficiary_age - (elapsed - 1)
        divisor = max(1.0,single_life_divisor(first_year_age) - (elapsed - 1))
    if after_rbd and decedent_birth_year is not None:
        owner_divisor = max(1.0,single_life_divisor(inherited_year-decedent_birth_year) - elapsed)
        divisor = max(divisor,owner_divisor)
    return min(account_balance,max(0.0,basis) / divisor)

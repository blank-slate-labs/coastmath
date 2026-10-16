"""State retirement-income exclusions (pensions, IRAs and employer plans).

Each income-tax state's rule lives under ``retirement_income_exclusion`` in
``coastmath/data/tax_brackets_2026.json`` and is sourced, state by state, in the
"State retirement-income exclusions" section of
``_sources`` in ``tax_brackets_2026.json``. A rule is a list of
``components``; each component is evaluated per person and then per return:

- ``sources``: the income it covers, from :data:`SOURCES`. ``employer_plan``
  expands to the 401(k), 403(b), 457(b) and 401(a) sources. ``any_income``
  instead makes it an age deduction against any income (Virginia, the South
  Carolina age-65 deduction), limited only by state AGI in the tax engine.
- ``minimum_age`` / ``maximum_age``: the person qualifies when their age at
  the end of the tax year is at least ``ceil(minimum_age)`` and below
  ``maximum_age``. A half-year minimum such as 59.5 is therefore met in the
  year the person turns 60 (annual granularity: the year someone turns 59 1/2
  is not split at that date). ``source_minimum_age`` gates single sources the
  same way (for example IRA distributions that a state covers only when no
  early-distribution penalty applies).
- ``cap`` (per person, ``null`` for unlimited) or ``age_caps``
  (``[[minimum_age, amount], ...]``, the highest band reached applies);
  ``return_cap`` is a per-return cap keyed by filing status.
- ``indexed``: dollar caps and income thresholds scale with the state
  inflation factor (calendar anchor 2026 = 1.0); an ``income_limit`` may set
  its own ``indexed``. Unindexed amounts are statutory constants.
- ``social_security``: ``"reduces_cap"`` lowers each person's cap by their own
  gross Social Security benefits (Maryland, Maine). ``"colorado"`` adds the
  Colorado subtraction of the person's federally taxable benefits and lowers
  the person's pension cap by it (C.R.S. 39-22-104(4)(f)).
- ``income_limit``: ``dollar_phaseout`` reduces each person's cap by every
  dollar of the base above a filing-status threshold (Virginia, Missouri);
  ``schedule`` keeps a share of the household exclusion by income band
  (Connecticut, New Jersey); ``cliff`` removes it above a threshold (Rhode
  Island); ``fraction`` removes the share (base - threshold) / denominator
  (Maine). ``base`` is ``federal_agi`` or
  ``federal_agi_less_taxable_social_security``.
- ``reduced_by_components``: a person's cap is reduced by what they claimed
  under the listed earlier components (South Carolina 12-6-1170(B)).

Amounts are the federally taxable income in each category. Roth conversions
are their own source and are covered only where a state's guidance says so.
Rules apply to the state the simulator resolves for the whole tax year, the
same way the state's capital-gain exclusion applies (``coastmath.engine.residency``
resolves one state per calendar year; there is no part-year proration).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

#: Income sources a rule can cover. Account sources are the taxable
#: distributions (withdrawals, RMDs net of QCDs, SEPP) from traditional
#: accounts of that type, inherited accounts included.
SOURCES = frozenset({
    "pension",          # qualified_pension income streams
    "annuity",          # nonqualified_annuity income streams (taxable part)
    "ira",              # traditional IRA distributions
    "401k", "403b", "457b", "401a",
    "roth_conversion",  # taxable traditional-to-Roth conversions
})
EMPLOYER_PLAN_SOURCES = ("401k", "403b", "457b", "401a")

#: Traditional account type -> exclusion source.
ACCOUNT_TYPE_SOURCES = {
    "traditional_ira": "ira",
    "traditional_401k": "401k",
    "traditional_403b": "403b",
    "traditional_457b": "457b",
    "traditional_401a": "401a",
}
#: Income stream tax category -> exclusion source.
STREAM_CATEGORY_SOURCES = {
    "qualified_pension": "pension",
    "nonqualified_annuity": "annuity",
}


@dataclass(frozen=True)
class RetirementIncome:
    """One person's calendar-year retirement income for state exclusions."""

    age: int | None
    amounts: Mapping[str, float] = field(default_factory=dict)
    #: Gross Social Security benefits received by this person.
    social_security: float = 0.0


def _expand(sources: Sequence[str]) -> tuple[str, ...]:
    expanded: list[str] = []
    for source in sources:
        expanded.extend(EMPLOYER_PLAN_SOURCES if source == "employer_plan" else (source,))
    return tuple(expanded)


def _age_met(age: int | None, minimum: float | None) -> bool:
    return minimum is None or (age is not None and age >= math.ceil(float(minimum)))


def _by_status(value, filing_status: str):
    if isinstance(value, Mapping):
        return value.get(filing_status, value.get("default", value.get("single")))
    return value


def _person_cap(component: Mapping, age: int | None, factor: float) -> float | None:
    if "age_caps" in component:
        amount = None
        for minimum, band_amount in component["age_caps"]:
            if _age_met(age, minimum):
                amount = float(band_amount)
        cap = amount if amount is not None else 0.0
    elif component.get("cap") is None:
        return None
    else:
        cap = float(component["cap"])
    return cap * factor


def _income_share(limit: Mapping, filing_status: str, base: float, factor: float) -> float:
    """Household share of the exclusion kept under a return-level income limit."""
    kind = limit["type"]
    if kind == "cliff":
        threshold = float(_by_status(limit["threshold"], filing_status)) * factor
        return 1.0 if base <= threshold else 0.0
    if kind == "fraction":
        threshold = float(_by_status(limit["threshold"], filing_status)) * factor
        denominator = float(_by_status(limit["denominator"], filing_status))
        return 1.0 - min(1.0, max(0.0, base - threshold) / denominator)
    if kind == "schedule":
        # Bands are [upper bound exclusive, share]; income at or above the
        # last bound keeps nothing.
        for upper, share in limit["bands"][filing_status if filing_status in limit["bands"] else "single"]:
            if base < float(upper) * factor:
                return float(share)
        return 0.0
    raise ValueError(f"Unknown retirement exclusion income limit type: {kind!r}")


def state_retirement_exclusion(
    rule: Mapping | None,
    persons: Sequence[RetirementIncome],
    filing_status: str,
    federal_agi: float,
    taxable_social_security: float = 0.0,
    social_security_income: float = 0.0,
    inflation_factor: float = 1.0,
) -> float:
    """Return the state subtraction for retirement income on one return.

    *federal_agi* includes capital gains, less any capital-gain subtraction
    that the state's AGI excludes (Missouri). *taxable_social_security* is the
    return's federally taxable benefits, attributed to each person in
    proportion to their share of *social_security_income* (the return's gross
    benefits). The tax engine caps the result at state AGI.
    """
    if not rule or not persons:
        return 0.0
    afagi = federal_agi - max(0.0, taxable_social_security)
    taxable_share = (max(0.0, taxable_social_security) / social_security_income
                     if social_security_income > 0 else 0.0)
    claimed: list[list[float]] = []
    total = 0.0
    for component in rule["components"]:
        factor = inflation_factor if component.get("indexed") else 1.0
        limit = component.get("income_limit")
        # Income thresholds follow the component unless the limit says
        # otherwise (Rhode Island indexes its threshold, not its cap).
        limit_factor = (inflation_factor if limit and limit.get("indexed", component.get("indexed"))
                        else 1.0)
        base = (afagi if limit and limit.get("base") == "federal_agi_less_taxable_social_security"
                else federal_agi)
        sources = _expand(component.get("sources", ()))
        source_ages = {expanded: age for source, age in component.get("source_minimum_age", {}).items()
                       for expanded in _expand((source,))}
        per_person: list[float] = []
        for index, person in enumerate(persons):
            age = person.age
            if not _age_met(age, component.get("minimum_age")) or (
                    component.get("maximum_age") is not None
                    and (age is None or age >= float(component["maximum_age"]))):
                per_person.append(0.0)
                continue
            covered = (math.inf if component.get("any_income") else sum(
                max(0.0, float(person.amounts.get(source, 0.0))) for source in sources
                if _age_met(age, source_ages.get(source))))
            cap = _person_cap(component, age, factor)
            if component.get("social_security") == "reduces_cap" and cap is not None:
                cap -= max(0.0, person.social_security)
            if limit and limit["type"] == "dollar_phaseout" and cap is not None:
                threshold = float(_by_status(limit["threshold"], filing_status)) * limit_factor
                cap -= max(0.0, base - threshold)
            for earlier in component.get("reduced_by_components", ()):
                if cap is not None:
                    cap -= claimed[earlier][index]
            social_security = 0.0
            if component.get("social_security") == "colorado":
                # C.R.S. 39-22-104(4)(f): taxable benefits are subtracted in
                # full at 65+, or at 55-64 under the AGI limit; otherwise they
                # share the pension cap. Either way the subtraction reduces
                # the cap left for other pension and annuity income.
                taxable = max(0.0, person.social_security) * taxable_share
                full = component["social_security_full"]
                if (_age_met(age, full["minimum_age"])
                        or federal_agi <= float(_by_status(full["federal_agi_limit"], filing_status))):
                    social_security = taxable
                else:
                    social_security = min(taxable, max(0.0, cap or 0.0))
                cap = (cap or 0.0) - social_security
            amount = covered if cap is None else min(covered, max(0.0, cap))
            per_person.append(social_security + max(0.0, amount))
        claimed.append(per_person)
        excluded = sum(per_person)
        if component.get("any_income"):
            total += excluded
            continue
        share = (_income_share(limit, filing_status, base, limit_factor)
                 if limit and limit["type"] != "dollar_phaseout" else 1.0)
        return_cap = component.get("return_cap")
        if return_cap is not None and (share >= 1.0 or not component.get("return_cap_full_share_only")):
            excluded = min(excluded, float(_by_status(return_cap, filing_status)) * factor)
        total += excluded * share
    return total

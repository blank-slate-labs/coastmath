"""Plan-level tax target: how much taxable income a year should carry.

A plan can name one target (stay within a federal bracket, a taxable-income
or MAGI amount, below an IRMAA tier, or below a percentage of the poverty
line while on marketplace coverage) plus optional extra ceilings (the NIIT
threshold, the first IRMAA tier, a poverty-line percentage in ACA years).
The year's limit on each measured quantity is the smallest that applies.

Strategies that opt in (tax-aware drawdown blending, Roth conversions and
gain harvests with ``use_plan_tax_target``) size their income by solving the
simulator's own tax calculation against :meth:`YearTaxTarget.fits`; this
module only turns settings into limits and a tax result into measures.

Statutory thresholds come from the existing data: federal brackets
(``tax_brackets_*.json``), IRMAA ranges and poverty guidelines
(``healthcare_2026.json``) and the IRC 1411(b) NIIT thresholds.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from coastmath.engine.healthcare import irmaa_threshold
from coastmath.engine.tax_engine import get_federal_brackets, niit_threshold
from coastmath.engine.types import TaxResult

TARGET_KINDS = frozenset({"federal_bracket", "taxable_income", "magi", "irmaa_tier", "aca_fpl_percent"})

#: IRMAA in year t is set by MAGI from year t - 2 (42 U.S.C. 1395r(i)(4)).
IRMAA_LOOKBACK_YEARS = 2
#: Medicare eligibility by age (42 U.S.C. 426(a)).
MEDICARE_AGE = 65
#: A measure fits its limit up to this much above it, absorbing float noise
#: between the sizing trial and the final tax calculation.
FIT_TOLERANCE = 0.005

# Measures a limit can bound. "taxable_income" is total taxable income:
# ordinary taxable income plus the gains and qualified dividends that stack
# on it (IRC 1(h)), so realized gains use the same room as ordinary income.
TAXABLE_INCOME = "taxable_income"
MAGI = "magi"
IRMAA_MAGI = "irmaa_magi"
NIIT_MAGI = "niit_magi"
ACA_MAGI = "aca_magi"


@dataclass(frozen=True)
class TaxTargetSettings:
    kind: str
    bracket_rate: float | None = None
    amount: float | None = None  # today's dollars; indexed with plan inflation
    irmaa_tier: int | None = None
    aca_fpl_percent: float | None = None
    avoid_niit: bool = False
    avoid_irmaa: bool = False
    aca_cap_fpl_percent: float | None = None


def parse_tax_target(tax_settings: dict | None) -> TaxTargetSettings | None:
    """The plan's tax target from ``tax_settings.tax_target``, or None."""
    raw = (tax_settings or {}).get("tax_target")
    if not raw or raw.get("kind") not in TARGET_KINDS:
        return None

    def number(key):
        value = raw.get(key)
        return None if value is None else float(value)

    tier = raw.get("irmaa_tier")
    return TaxTargetSettings(
        kind=raw["kind"],
        bracket_rate=number("bracket_rate"),
        amount=number("amount"),
        irmaa_tier=None if tier is None else int(tier),
        aca_fpl_percent=number("aca_fpl_percent"),
        avoid_niit=bool(raw.get("avoid_niit", False)),
        avoid_irmaa=bool(raw.get("avoid_irmaa", False)),
        aca_cap_fpl_percent=number("aca_cap_fpl_percent"),
    )


@dataclass(frozen=True)
class YearTaxTarget:
    """The limits in force for one year, keyed by the measure each bounds."""
    limits: dict[str, float]

    def fits(self, measures: dict[str, float]) -> bool:
        return all(measures[name] <= limit + FIT_TOLERANCE for name, limit in self.limits.items())

    def room(self, measures: dict[str, float]) -> float:
        """Additional income (first order) before the tightest limit binds."""
        return max(0.0, min(limit - measures[name] for name, limit in self.limits.items()))


def plan_bracket_rates(tax_settings: Mapping | None, filing_status: str = "single") -> list[float]:
    """Federal bracket rates a bracket target can name in this plan, ascending.

    The rates of the plan's own schedule (custom ``federal_brackets``, else
    the built-in brackets) and of every schedule a scheduled change installs
    (an empty one restores the built-in brackets). The schedule in force can
    differ by year; years whose schedule lacks the target's rate get a plan
    warning (:func:`missing_bracket_target_warning`).
    """
    settings = tax_settings or {}
    built_in = [rate for _, rate in get_federal_brackets(filing_status)]

    def schedule_rates(brackets) -> list[float]:
        return [float(bracket[1]) for bracket in brackets] if brackets else built_in

    rates = list(schedule_rates(settings.get("federal_brackets")))
    for change in settings.get("scheduled_changes") or []:
        brackets = (change.get("settings") or {}).get("federal_brackets")
        if brackets is not None:
            rates.extend(schedule_rates(brackets))
    unique: list[float] = []
    for rate in sorted(rates):
        if not unique or abs(rate - unique[-1]) >= 1e-9:
            unique.append(rate)
    return unique


def bracket_rate_in_schedule(federal_brackets: list[tuple[float, float]], rate: float) -> bool:
    """Whether ``rate`` is one of the schedule's bracket rates."""
    return any(abs(bracket_rate - rate) < 1e-9 for _, bracket_rate in federal_brackets)


def bracket_target_top(federal_brackets: list[tuple[float, float]], rate: float) -> float | None:
    """Top of the taxable income a federal bracket target allows, or None for no cap.

    A rate in the schedule allows income through the top of its bracket. A
    rate the schedule lacks (a saved target after the plan's brackets changed)
    allows income only while every bracket it fills is taxed at or below the
    saved rate: the top of the highest such bracket, or no taxable income when
    the first bracket's rate is already higher. An unbounded top bracket is no
    cap.
    """
    top = None
    if bracket_rate_in_schedule(federal_brackets, rate):
        for upper, bracket_rate in federal_brackets:
            if abs(bracket_rate - rate) < 1e-9:
                top = upper
    else:
        top = 0.0
        for upper, bracket_rate in federal_brackets:
            if bracket_rate > rate + 1e-9:
                break
            top = upper
    return top if top is not None and math.isfinite(top) else None


def _year_ranges(years: list[int]) -> str:
    spans: list[list[int]] = []
    for year in sorted(set(years)):
        if spans and year == spans[-1][1] + 1:
            spans[-1][1] = year
        else:
            spans.append([year, year])
    return ", ".join(str(a) if a == b else f"{a}\u2013{b}" for a, b in spans)


def missing_bracket_target_warning(rate: float, years: list[int], subject: str = "The tax target's") -> str:
    """The plan warning for years whose federal brackets lack a bracket ceiling's rate.

    ``subject`` names whose ceiling it is: the plan's tax target by default,
    or an allocation rule with its own ``bracket_ceiling_rate``.
    """
    percent = f"{rate * 100:g}%"
    return (f"{subject} {percent} federal bracket is not in the bracket schedule for "
            f"{_year_ranges(years)}; those years fill only brackets taxed at or below {percent}.")


def year_tax_target(
    target: TaxTargetSettings | None,
    *,
    filing_status: str,
    year: int,
    flat_tax: bool,
    federal_brackets: list[tuple[float, float]],
    inflation_factor: float,
    irmaa_inflation_factor: float,
    irmaa_applies: bool,
    mfs_lived_apart_all_year: bool = False,
    aca_poverty_line: float | None = None,
) -> YearTaxTarget | None:
    """Limits for ``year``, or None when no part of the target applies.

    ``federal_brackets`` are already scaled to the year. IRMAA limits use the
    ranges of ``year + 2``, the premium year this income sets, indexed by
    ``irmaa_inflation_factor``; they apply only when ``irmaa_applies`` (someone
    reaches Medicare age by then). Poverty-line limits apply only when
    ``aca_poverty_line`` is given, i.e. in years with marketplace coverage.
    """
    if target is None:
        return None
    limits: dict[str, float] = {}

    def cap(measure: str, value: float) -> None:
        limits[measure] = min(limits.get(measure, math.inf), value)

    def aca_cap(percent: float) -> None:
        # Premium tax credit eligibility ends above 400% of the poverty line
        # (26 U.S.C. 36B(c)(1)(A): household income that "does not exceed 400
        # percent"), a cliff in 2026. Cap at the largest whole dollar the
        # credit calculation keeps at or below the percentage (a return may
        # round to whole dollars), with the fit tolerance inside it.
        ratio = percent / 100.0
        dollars = math.floor(aca_poverty_line * ratio)
        while dollars / aca_poverty_line > ratio:
            dollars -= 1
        cap(ACA_MAGI, dollars - FIT_TOLERANCE)

    def irmaa_cap(tier: int) -> None:
        if irmaa_applies:
            # The tier is a cliff: keep the fit tolerance inside the range so
            # the largest fitting MAGI is the highest whole dollar below it.
            cap(IRMAA_MAGI, irmaa_threshold(tier, filing_status, year + IRMAA_LOOKBACK_YEARS,
                                            irmaa_inflation_factor, mfs_lived_apart_all_year) - FIT_TOLERANCE)

    if target.kind == "federal_bracket" and target.bracket_rate is not None and not flat_tax:
        top = bracket_target_top(federal_brackets, target.bracket_rate)
        if top is not None:
            cap(TAXABLE_INCOME, top)
    elif target.kind == "taxable_income" and target.amount is not None:
        cap(TAXABLE_INCOME, target.amount * inflation_factor)
    elif target.kind == "magi" and target.amount is not None:
        cap(MAGI, target.amount * inflation_factor)
    elif target.kind == "irmaa_tier" and target.irmaa_tier is not None:
        irmaa_cap(target.irmaa_tier)
    elif target.kind == "aca_fpl_percent" and target.aca_fpl_percent is not None and aca_poverty_line is not None:
        aca_cap(target.aca_fpl_percent)
    if target.avoid_niit:
        # Not a cliff: NIIT taxes only MAGI in excess of the whole-dollar
        # threshold (26 U.S.C. 1411(a)(1)(B), (b)), so MAGI at it owes none.
        cap(NIIT_MAGI, niit_threshold(filing_status))
    if target.avoid_irmaa:
        irmaa_cap(1)
    if target.aca_cap_fpl_percent is not None and aca_poverty_line is not None:
        aca_cap(target.aca_cap_fpl_percent)
    return YearTaxTarget(limits) if limits else None


def tax_measures(result: TaxResult, *, aca_magi: float, aca_active: bool) -> dict[str, float]:
    """The quantities a tax target bounds, from one tax calculation.

    ``magi`` matches the conversion rules' MAGI cap: the premium tax credit
    MAGI while marketplace coverage applies, otherwise AGI including gains.
    IRMAA MAGI adds tax-exempt interest (42 U.S.C. 1395r(i)(4)(A)); NIIT MAGI
    is AGI including gains (IRC 1411(d), no foreign exclusion modeled).
    """
    # Preferential income stacks on ordinary taxable income after any
    # deduction ordinary income could not absorb (IRC 1(h)).
    taxable_gains = max(0.0, (result.modified_agi - result.agi)
                        - max(0.0, result.deduction_amount - result.agi))
    taxable_total = result.taxable_income + taxable_gains
    if taxable_total <= 0:
        # Deductions income cannot absorb are room too: report the shortfall
        # as negative taxable income instead of clipping it at zero.
        taxable_total = min(0.0, result.modified_agi - result.deduction_amount)
    return {
        TAXABLE_INCOME: taxable_total,
        MAGI: aca_magi if aca_active else result.modified_agi,
        IRMAA_MAGI: result.modified_agi + result.tax_exempt_interest,
        NIIT_MAGI: result.modified_agi,
        ACA_MAGI: aca_magi,
    }


def largest_fitting(fits: Callable[[float], bool], upper: float, tolerance: float = 0.01) -> float:
    """Largest amount in [0, upper] for which the monotone ``fits`` holds."""
    if upper <= 0:
        return 0.0
    if fits(upper):
        return upper
    if not fits(0.0):
        return 0.0
    lower = 0.0
    for _ in range(60):
        if upper - lower <= tolerance:
            break
        middle = (lower + upper) / 2
        if fits(middle):
            lower = middle
        else:
            upper = middle
    return lower

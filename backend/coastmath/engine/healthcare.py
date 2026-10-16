"""Health coverage costs: ACA marketplace premium tax credits and Medicare
premiums with income-related monthly adjustment amounts (IRMAA).

All statutory figures are loaded from ``coastmath/data/healthcare_2026.json``
(sources listed there). The module is pure: the simulator supplies incomes,
ages and inflation factors and adds the resulting premiums to expenses once.

Simplifications:
- The premium tax credit is computed annually from full-year MAGI; the IRS
  computes it monthly and reconciles advance payments.
- Household income below 100% of the poverty line receives no credit; Medicaid
  and CHIP eligibility are not modeled.
- Benchmark and plan premiums are age-rated with the federal default age curve
  from the household's premiums at their current ages; state-specific curves
  and family tiers for children are not modeled.
- IRMAA thresholds index with plan inflation (the top tier is frozen through
  2027); premium dollar amounts grow with the medical inflation rate.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from coastmath.schemas.healthcare_settings import HealthcareSettings

_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "healthcare_2026.json"
BASE_YEAR = 2026


@lru_cache(maxsize=1)
def _data() -> dict:
    with _DATA_PATH.open() as fh:
        return json.load(fh)


@dataclass
class HealthcareSettingsData:
    enabled: bool = False
    medical_inflation_rate: float | None = None  # None -> plan inflation
    # ACA marketplace coverage (pre-Medicare adults)
    aca_enabled: bool = False
    aca_start_milestone_id: str | None = None
    aca_end_milestone_id: str | None = None
    aca_benchmark_premium_annual: float = 0.0  # SLCSP for covered adults at current ages, today's dollars
    aca_plan_premium_annual: float = 0.0  # chosen plan's gross premium, same basis
    aca_advance_credit_fraction: float = 1.0  # fraction of the estimated credit advanced during coverage
    aca_cover_spouse: bool = True
    aca_dependents: int = 0  # additional household members (children) for the poverty-line size
    aca_apply_age_curve: bool = True
    aca_state_group: str = "contiguous"  # contiguous | alaska | hawaii
    # Medicare (age 65+)
    medicare_enabled: bool = True
    medicare_part_b: bool = True
    medicare_part_d: bool = True
    medicare_part_d_plan_premium_monthly: float = 0.0  # per person, today's dollars
    medicare_supplement_premium_monthly: float = 0.0  # Medigap/Advantage per person, today's dollars
    medicare_apply_irmaa: bool = True
    magi_prior_year: float | None = None  # IRMAA lookback seeds for the first two years
    magi_two_years_prior: float | None = None
    magi_prior_year_filing_status: str | None = None
    magi_two_years_prior_filing_status: str | None = None
    persons: list[dict] = field(default_factory=list)


@dataclass
class ACAResult:
    covered_adults: int = 0
    household_size: int = 0
    magi: float = 0.0
    poverty_line: float = 0.0
    fpl_ratio: float = 0.0
    applicable_percentage: float = 0.0
    expected_contribution: float = 0.0
    benchmark_premium: float = 0.0
    gross_premium: float = 0.0
    credit: float = 0.0
    net_premium: float = 0.0
    eligible: bool = False
    reason: str | None = None


@dataclass
class MedicareResult:
    enrolled_persons: int = 0
    magi_used: float = 0.0
    lookback_year: int | None = None
    lookback_source: str = "none"  # history | seed | proxy
    tier_index: int = 0
    part_b_standard: float = 0.0
    part_b_irmaa: float = 0.0
    part_d_irmaa: float = 0.0
    part_d_plan: float = 0.0
    supplement: float = 0.0

    @property
    def total(self) -> float:
        return self.part_b_standard + self.part_b_irmaa + self.part_d_irmaa + self.part_d_plan + self.supplement


@dataclass
class HealthcareYearResult:
    aca: ACAResult | None = None
    medicare: MedicareResult | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return (self.aca.net_premium if self.aca else 0.0) + (self.medicare.total if self.medicare else 0.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_healthcare_settings(raw: dict | None) -> HealthcareSettingsData:
    """Build settings from the JSONB dict, ignoring unknown keys."""
    if not isinstance(raw, dict) or not raw:
        return HealthcareSettingsData()
    allowed = HealthcareSettingsData.__dataclass_fields__
    values = {k: v for k, v in raw.items() if k in allowed}
    if values.get("persons"):
        validated = HealthcareSettings.model_validate(raw)
        values["persons"] = [person.model_dump(mode="json") for person in validated.persons]
    for key in ("aca_benchmark_premium_annual", "aca_plan_premium_annual",
                "medicare_part_d_plan_premium_monthly", "medicare_supplement_premium_monthly"):
        if key in values and values[key] is not None:
            values[key] = float(values[key])
    if "aca_advance_credit_fraction" in values:
        fraction = float(values["aca_advance_credit_fraction"])
        if not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
            raise ValueError("aca_advance_credit_fraction must be between 0 and 1")
        values["aca_advance_credit_fraction"] = fraction
    for key in ("medical_inflation_rate", "magi_prior_year", "magi_two_years_prior"):
        if key in values and values[key] is not None:
            values[key] = float(values[key])
    if "aca_dependents" in values and values["aca_dependents"] is not None:
        values["aca_dependents"] = int(values["aca_dependents"])
    return HealthcareSettingsData(**values)


def age_curve_factor(age: int) -> float:
    """Federal default standard age curve factor (3:1 adult ratio)."""
    factors = _data()["age_curve"]["factors"]
    if age <= 14:
        return float(factors["0"])
    if age >= 64:
        return float(factors["64"])
    return float(factors[str(age)])


def poverty_line(household_size: int, state_group: str = "contiguous", inflation_factor: float = 1.0) -> float:
    table = _data()["poverty_guidelines_2025"]
    row = table.get(state_group, table["contiguous"])
    size = max(1, int(household_size))
    return (float(row["first_person"]) + float(row["each_additional"]) * (size - 1)) * inflation_factor


def applicable_percentage(fpl_ratio: float) -> float | None:
    """Rev. Proc. 2025-25 table; None when no credit is available."""
    data = _data()
    if fpl_ratio < data["ptc_minimum_fpl_ratio"] or fpl_ratio > data["ptc_maximum_fpl_ratio"]:
        return None
    for band in data["applicable_percentage_bands"]:
        lower, upper = band["lower"], band["upper"]
        if lower <= fpl_ratio < upper or (fpl_ratio == upper and upper == data["ptc_maximum_fpl_ratio"]):
            if band["final"] == band["initial"] or upper == lower:
                return float(band["initial"])
            share = (fpl_ratio - lower) / (upper - lower)
            return float(band["initial"] + share * (band["final"] - band["initial"]))
    return None


def calculate_premium_tax_credit(
    magi: float,
    household_size: int,
    benchmark_premium: float,
    gross_premium: float,
    *,
    covered_adults: int,
    state_group: str = "contiguous",
    inflation_factor: float = 1.0,
    coverage_periods: list[tuple[float, float, float]] | None = None,
    filing_status: str | None = None,
) -> ACAResult:
    """Annual premium tax credit under IRC 36B for the covered adults."""
    result = ACAResult(
        covered_adults=covered_adults, household_size=household_size, magi=magi,
        benchmark_premium=benchmark_premium, gross_premium=gross_premium,
        net_premium=gross_premium,
    )
    if filing_status == "married_filing_separately":
        # IRC 36B(c)(1)(C), Treas. Reg. 1.36B-2(b)(2)(i): a married taxpayer
        # is an applicable taxpayer only on a joint return. The domestic
        # abuse/abandonment relief in 1.36B-2(b)(2)(ii) is not modeled.
        if coverage_periods is not None:
            result.benchmark_premium = sum(b * f for b, _, f in coverage_periods)
            result.gross_premium = result.net_premium = sum(g * f for _, g, f in coverage_periods)
        result.reason = "married filing separately: IRC 36B(c)(1)(C) requires a joint return"
        return result
    if coverage_periods is not None:
        # Each period supplies annualized premiums and its fraction of a year.
        # Apply the contribution and credit cap within each coverage month,
        # then aggregate (IRC 36B(b)(2)); enrollment can change midyear.
        result.benchmark_premium = result.gross_premium = result.net_premium = 0.0
        for benchmark, premium, fraction in coverage_periods:
            part = calculate_premium_tax_credit(
                magi, household_size, benchmark, premium,
                covered_adults=covered_adults, state_group=state_group,
                inflation_factor=inflation_factor,
            )
            for name in ("benchmark_premium", "gross_premium", "net_premium", "credit", "expected_contribution"):
                setattr(result, name, getattr(result, name) + getattr(part, name) * fraction)
            for name in ("poverty_line", "fpl_ratio", "applicable_percentage", "eligible", "reason"):
                setattr(result, name, getattr(part, name))
        return result
    if covered_adults <= 0 or gross_premium <= 0:
        result.reason = "no covered adults"
        return result
    fpl = poverty_line(household_size, state_group, inflation_factor)
    result.poverty_line = fpl
    result.fpl_ratio = magi / fpl if fpl > 0 else 0.0
    pct = applicable_percentage(result.fpl_ratio)
    if pct is None:
        result.reason = (
            "income below 100% of the poverty line; Medicaid is not modeled"
            if result.fpl_ratio < _data()["ptc_minimum_fpl_ratio"]
            else "income above 400% of the poverty line"
        )
        return result
    result.applicable_percentage = pct
    result.expected_contribution = pct * max(0.0, magi)
    credit = max(0.0, benchmark_premium - result.expected_contribution)
    result.credit = min(credit, gross_premium)
    result.net_premium = gross_premium - result.credit
    result.eligible = True
    return result


def _irmaa_tier(
    magi: float, filing_status: str, year: int, inflation_factor: float,
    mfs_lived_apart_all_year: bool = False,
) -> tuple[int, float, float]:
    """Return (tier index, part B add, part D add) in base-year dollars.

    Separate filers who lived apart from their spouse all year use the
    individual ranges; only those who lived together use the married-separate
    ranges (20 CFR 418.1115(b), (d); 418.2115).

    Every tier but the top one includes its upper bound. The top tier starts
    at the boundary itself: MAGI of at least $500,000 single, $750,000 joint
    or $391,000 separate (20 CFR 418.1115(c)-(d); CMS 2026 Part B premiums).
    """
    med = _data()["medicare_2026"]
    freeze_top = year <= int(med["top_tier_frozen_through"])
    if filing_status == "married_filing_separately" and not mfs_lived_apart_all_year:
        tiers = med["separate_tiers"]
        for idx, tier in enumerate(tiers):
            upper = tier["upper"]
            if upper is None:
                return idx, float(tier["part_b_add"]), float(tier["part_d_add"])
            is_top_boundary = idx == len(tiers) - 2
            threshold = float(upper) * (1.0 if (is_top_boundary and freeze_top) else inflation_factor)
            if magi < threshold or (magi == threshold and not is_top_boundary):
                return idx, float(tier["part_b_add"]), float(tier["part_d_add"])
    tiers = med["irmaa_tiers"]
    key = "joint_upper" if filing_status == "married_filing_jointly" else "single_upper"
    for idx, tier in enumerate(tiers):
        upper = tier[key]
        if upper is None:
            return idx, float(tier["part_b_add"]), float(tier["part_d_add"])
        is_top_boundary = idx == len(tiers) - 2
        threshold = float(upper) * (1.0 if (is_top_boundary and freeze_top) else inflation_factor)
        if magi < threshold or (magi == threshold and not is_top_boundary):
            return idx, float(tier["part_b_add"]), float(tier["part_d_add"])
    last = tiers[-1]
    return len(tiers) - 1, float(last["part_b_add"]), float(last["part_d_add"])


def irmaa_threshold(
    tier: int, filing_status: str, year: int, inflation_factor: float,
    mfs_lived_apart_all_year: bool = False,
) -> float:
    """Highest whole-dollar MAGI that stays below IRMAA surcharge ``tier`` in ``year``.

    Tier 1 is the first surcharge, so ``irmaa_threshold(1, ...)`` is the most
    MAGI that avoids any surcharge. Uses the same ranges, indexing and frozen
    top boundary as the premium calculation (:func:`_irmaa_tier`). A tier past
    the schedule's last boundary uses that boundary.

    Whole dollars, because a return may round its figures to whole dollars
    (Form 1040 instructions, "Rounding Off to Whole Dollars"): $499,999.99
    can be reported as $500,000, which is in the top tier.

    Lower boundaries include their bound (MAGI at or below it stays in the
    lower tier; 20 CFR 418.1115(c)-(d)): the answer is the largest whole
    dollar :func:`_irmaa_tier` keeps in the lower tier. MAGI at the top
    boundary already enters the top tier: the answer is the largest whole
    dollar strictly below the bound, read to the cent so that float noise in
    an indexed bound (540800.0000000001 for 500,000 x 1.04 ** 2) cannot admit
    the bound itself.
    """
    med = _data()["medicare_2026"]
    freeze_top = year <= int(med["top_tier_frozen_through"])
    if filing_status == "married_filing_separately" and not mfs_lived_apart_all_year:
        tiers, key = med["separate_tiers"], "upper"
    else:
        tiers = med["irmaa_tiers"]
        key = "joint_upper" if filing_status == "married_filing_jointly" else "single_upper"
    index = max(0, min(int(tier) - 1, len(tiers) - 2))
    is_top_boundary = index == len(tiers) - 2
    bound = float(tiers[index][key]) * (1.0 if (is_top_boundary and freeze_top) else inflation_factor)
    if not is_top_boundary:
        return float(math.floor(bound))
    dollars = math.ceil(round(bound, 2)) - 1
    while dollars >= bound:  # cannot trigger after reading to the cent; guards the float bound
        dollars -= 1
    return float(dollars)


def medicare_cost_factor(year: int, medical_rate: float | None, calendar_factor: float) -> float:
    """Index published Medicare dollars from their data year, not plan start."""
    base_year = int(_data()["medicare_2026"]["base_year"])
    return (1.0 + medical_rate) ** max(0, year - base_year) if medical_rate is not None else calendar_factor


def part_a_premium_monthly(quarters: int | None) -> float:
    """The published monthly Part A premium for Medicare-covered ``quarters``.

    42 USC 1395i-2: people with 40 or more quarters (their own or a
    qualifying spouse's) pay none; 30-39 quarters pay the reduced premium;
    fewer pay the full premium. None means no premium is modeled.
    """
    if quarters is None:
        return 0.0
    med = _data()["medicare_2026"]
    limits, premiums = med["part_a_quarters"], med["part_a_premium_monthly"]
    if quarters >= int(limits["premium_free"]):
        return 0.0
    return float(premiums["reduced"] if quarters >= int(limits["reduced"]) else premiums["full"])


def calculate_medicare_premiums(
    magi_lookback: float,
    filing_status: str,
    persons: float,
    settings: HealthcareSettingsData,
    *,
    year: int,
    inflation_factor: float,
    medical_factor: float,
    statutory_medical_factor: float | None = None,
    mfs_lived_apart_all_year: bool = False,
) -> MedicareResult:
    """Annual Medicare premiums for ``persons`` enrolled person-years.

    ``persons`` may be fractional to prorate the enrollment year. Published
    Part B/IRMAA use the calendar-based statutory factor; entered premiums
    retain the plan-relative medical factor. Omitting the new factor preserves
    direct callers that already supply a calendar-indexed medical factor.
    """
    med = _data()["medicare_2026"]
    result = MedicareResult(enrolled_persons=int(round(persons)) if persons >= 1 else (1 if persons > 0 else 0), magi_used=magi_lookback)
    if persons <= 0:
        return result
    months = 12.0 * persons
    statutory_factor = medical_factor if statutory_medical_factor is None else statutory_medical_factor
    if settings.medicare_part_b:
        result.part_b_standard = float(med["part_b_standard_monthly"]) * statutory_factor * months
    tier, b_add, d_add = (0, 0.0, 0.0)
    if settings.medicare_apply_irmaa:
        tier, b_add, d_add = _irmaa_tier(
            magi_lookback, filing_status, year, inflation_factor, mfs_lived_apart_all_year)
    result.tier_index = tier
    if settings.medicare_part_b:
        result.part_b_irmaa = b_add * statutory_factor * months
    if settings.medicare_part_d:
        result.part_d_irmaa = d_add * statutory_factor * months
        result.part_d_plan = settings.medicare_part_d_plan_premium_monthly * medical_factor * months
    result.supplement = settings.medicare_supplement_premium_monthly * medical_factor * months
    return result

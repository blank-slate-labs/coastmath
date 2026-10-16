"""Tax engine — progressive federal + state brackets, capital gains.

Federal tables select the applicable published year (2025 or 2026).
Other tax layers retain their separately documented 2026 assumptions.
Formula/data sources are tracked in ``_sources`` in ``tax_brackets_2026.json``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from coastmath.engine import state_rules_bridge
from coastmath.engine.ca_exemption_credits import ca_exemption_credit
from coastmath.engine.local_tax import (
    LocalIncome,
    LocalTaxContext,
    LocalTaxResult,
    calculate_local_tax,
)
from coastmath.engine.real_estate import UNRECAPTURED_1250_RATE
from coastmath.engine.state_enacted_changes import (
    calendar_factor_for,
    state_data_for_year,
)
from coastmath.engine.state_retirement_exclusion import (
    RetirementIncome,
    state_retirement_exclusion,
)
from coastmath.engine.state_social_security import (
    SocialSecurityContext,
    state_social_security_subtraction,
)
from coastmath.engine.state_tax_allocation import (
    CAPartYearTaxAllocation,
    CAPartYearWageContext,
    allocate_ca_part_year_tax,
)
from coastmath.engine.tax_adjustments import (
    YearAdjustments,
    apply_credits,
    surcharge_amount,
)
from coastmath.engine.types import TaxResult

# ---------------------------------------------------------------------------
# Load tax data once at module level
# ---------------------------------------------------------------------------

_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "tax_brackets_2026.json"
_CA_HOUSEHOLD_DATA = json.loads(_DATA_FILE.with_name("ca_household_tax_2025.json").read_text())

with open(_DATA_FILE) as _f:
    _TAX_DATA = json.load(_f)
with open(_DATA_FILE.with_name("tax_brackets_2025.json")) as _f:
    _TAX_DATA_2025 = json.load(_f)


def _federal_data(tax_year: int) -> dict:
    """Select published federal data; pre-2025 years retain the legacy fallback.

    Years before 2025 are not historically supported. Future years use the
    latest published table with the caller's projected inflation multiplier.
    """
    return _TAX_DATA_2025 if tax_year == 2025 else _TAX_DATA

# 26 USC 164(b)(6)-(7), as amended by Public Law 119-21 (OBBBA):
# https://uscode.house.gov/view.xhtml?req=(title:26%20section:164%20edition:prelim)
_SALT_MIN_CAP = 10_000.0


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_standard_deduction(filing_status: str, tax_year: int = 2026) -> float:
    """Return the standard deduction for the given filing status."""
    deductions = _federal_data(tax_year)["standard_deductions"]
    if filing_status not in deductions:
        raise ValueError(f"Unknown filing status: {filing_status!r}")
    return float(deductions[filing_status])


def get_federal_brackets(filing_status: str, tax_year: int = 2026) -> list[tuple[float, float]]:
    """Return federal brackets as (upper_bound, rate) pairs."""
    brackets = _federal_data(tax_year)["brackets"]
    if filing_status not in brackets:
        raise ValueError(f"Unknown filing status: {filing_status!r}")
    return [(float(upper), float(rate)) for upper, rate in brackets[filing_status]]


def custom_federal_factor(settings: Mapping | None, inflation_factor: float) -> float:
    """The factor for custom federal amounts: plan inflation when indexed."""
    return inflation_factor if (settings or {}).get("federal_overrides_indexed", True) else 1.0


def federal_ordinary_brackets(
    settings: Mapping | None,
    filing_status: str,
    tax_year: int,
    federal_factor: float,
    inflation_factor: float,
) -> list[tuple[float, float]]:
    """This year's federal ordinary-income brackets, scaled to the year.

    ``settings["federal_brackets"]`` replaces the built-in brackets for every
    filing status. Custom bounds are plan inputs: indexed ones are plan-start
    dollars grown with the plan-relative *inflation_factor*, unindexed ones
    are nominal. Built-in bounds use the calendar *federal_factor*.
    """
    custom = (settings or {}).get("federal_brackets")
    if custom:
        factor = custom_federal_factor(settings, inflation_factor)
        return [(float(upper) * factor, float(rate)) for upper, rate in _convert_state_brackets(custom)]
    return [(upper * federal_factor, rate) for upper, rate in get_federal_brackets(filing_status, tax_year)]


def apply_progressive_brackets(taxable_income: float, brackets: list[tuple[float, float]]) -> float:
    """Compute tax using progressive brackets. Reused for federal, state, and LTCG."""
    if taxable_income <= 0:
        return 0.0

    tax = 0.0
    prev_bound = 0.0
    for upper_bound, rate in brackets:
        if taxable_income <= prev_bound:
            break
        slice_top = min(taxable_income, upper_bound)
        tax += (slice_top - prev_bound) * rate
        prev_bound = upper_bound

    return tax


def get_marginal_rate(taxable_income: float, brackets: list[tuple[float, float]]) -> float:
    """Return the marginal tax rate for the given taxable income."""
    if taxable_income <= 0:
        return 0.0

    rate = 0.0
    for upper_bound, bracket_rate in brackets:
        rate = bracket_rate
        if taxable_income <= upper_bound:
            break
    return rate


def get_ltcg_brackets(filing_status: str, tax_year: int = 2026) -> list[tuple[float, float]]:
    """Return LTCG brackets as (upper_bound, rate) pairs for the filing status."""
    brackets = _federal_data(tax_year)["long_term_capital_gains"]
    if filing_status not in brackets:
        raise ValueError(f"Unknown filing status: {filing_status!r}")
    return [(float(upper), float(rate)) for upper, rate in brackets[filing_status]]


def _salt_cap_for_year(
    tax_year: int,
    filing_status: str,
    modified_agi: float,
) -> float:
    """Return the federal SALT itemized-deduction cap for a tax year.

    OBBBA raised the cap for 2025-2029, with a MAGI phasedown that cannot
    reduce the cap below the legacy $10k floor ($5k for MFS).
    Source: 26 USC 164(b)(6)-(7), preliminary House code:
    https://uscode.house.gov/view.xhtml?req=(title:26%20section:164%20edition:prelim)

    NOTE: _salt_cap_for_year already models the statutory year schedule;
    left untouched by inflation_factor (29.1.1).
    """
    mfs = filing_status == "married_filing_separately"
    floor = _SALT_MIN_CAP / 2 if mfs else _SALT_MIN_CAP

    if tax_year < 2025 or tax_year > 2029:
        return floor

    if tax_year == 2025:
        cap = 40_000.0
        threshold = 500_000.0
    else:
        cap = 40_400.0
        threshold = 505_000.0
        for _ in range(2027, tax_year + 1):
            cap *= 1.01
            threshold *= 1.01

    if mfs:
        cap /= 2
        threshold /= 2

    phasedown = max(0.0, modified_agi - threshold) * 0.30
    return max(floor, cap - phasedown)


def _calculate_capital_gains_tax(
    capital_gains: float,
    taxable_income: float,
    filing_status: str,
    ltcg_brackets: list[tuple[float, float]] | None = None,
) -> float:
    """Compute LTCG tax with brackets stacked on top of ordinary taxable income.

    LTCG brackets apply starting from the ordinary taxable_income level.
    For example, if taxable_income is $40k and LTCG is $20k, the LTCG
    is taxed as if it occupies the $40k-$60k range in the LTCG bracket table.

    If *ltcg_brackets* is provided (e.g. pre-scaled for inflation), those
    brackets are used directly; otherwise the base-year brackets are loaded.
    """
    if capital_gains <= 0:
        return 0.0

    if ltcg_brackets is None:
        ltcg_brackets = get_ltcg_brackets(filing_status)
    tax = 0.0
    remaining = capital_gains
    prev_bound = 0.0

    for upper_bound, rate in ltcg_brackets:
        if remaining <= 0:
            break
        # Skip bracket space already covered by ordinary income
        effective_start = max(prev_bound, taxable_income)
        if effective_start >= upper_bound:
            prev_bound = upper_bound
            continue
        # Portion of this bracket available for capital gains
        bracket_space = upper_bound - effective_start
        taxable_in_bracket = min(remaining, bracket_space)
        tax += taxable_in_bracket * rate
        remaining -= taxable_in_bracket
        prev_bound = upper_bound

    return tax


def _capital_gains_tax_with_unrecaptured_1250(
    net_capital_gain: float,
    unrecaptured_1250: float,
    ordinary_taxable_income: float,
    ordinary_brackets: list[tuple[float, float]],
    ltcg_brackets: list[tuple[float, float]],
) -> float:
    """Tax on the net capital gain when part of it is unrecaptured 1250 gain.

    IRC 1(h)(1): the unrecaptured gain is stacked directly on ordinary
    income. The part of it in ordinary brackets taxed below 25% (through the
    24% bracket) is taxed at ordinary rates (1(h)(1)(A)(ii)(I); Schedule D Tax
    Worksheet line 19); the rest at 25% (1(h)(1)(E)). The adjusted net
    capital gain is stacked above the ordinary-rate amount at the 0/15/20%
    rates (1(h)(1)(B)-(D)). The total never exceeds the regular tax on all
    taxable income. Returns the tax above the ordinary tax on
    *ordinary_taxable_income*.
    """
    below_25_top = max((upper for upper, rate in ordinary_brackets if rate < UNRECAPTURED_1250_RATE),
                       default=0.0)
    ordinary_base = max(ordinary_taxable_income,
                        min(below_25_top, ordinary_taxable_income + unrecaptured_1250))
    at_ordinary_rates = ordinary_base - ordinary_taxable_income
    at_25 = unrecaptured_1250 - at_ordinary_rates
    adjusted_net_capital_gain = net_capital_gain - unrecaptured_1250
    ordinary_tax = apply_progressive_brackets(ordinary_taxable_income, ordinary_brackets)
    tax = (apply_progressive_brackets(ordinary_base, ordinary_brackets) - ordinary_tax
           + _calculate_capital_gains_tax(adjusted_net_capital_gain, ordinary_base, "",
                                          ltcg_brackets=ltcg_brackets)
           + UNRECAPTURED_1250_RATE * at_25)
    regular = (apply_progressive_brackets(ordinary_taxable_income + net_capital_gain, ordinary_brackets)
               - ordinary_tax)
    return min(tax, regular)


# ---------------------------------------------------------------------------
# State tax
# ---------------------------------------------------------------------------


def _convert_state_brackets(raw_brackets: list[dict | Sequence[float]]) -> list[tuple[float, float]]:
    """Convert state brackets to (upper_bound, rate) tuples.

    The data files store {min, max, rate} dicts. Plan tax settings store
    ``TaxSettings.state_brackets`` as (upper_bound, rate) pairs, which JSON
    returns as two-item lists.
    """
    return [
        (float(b["max"]), float(b["rate"])) if isinstance(b, dict) else (float(b[0]), float(b[1]))
        for b in raw_brackets
    ]


def _state_data_for(
    state_code: str | None,
    tax_year: int,
    inflation_factor: float = 1.0,
    calendar_inflation: Mapping[int, float] | None = None,
) -> dict | None:
    """The built-in state entry in force for ``tax_year``.

    The 2026 table with the state's enacted later changes applied
    (``coastmath.engine.state_enacted_changes``). *inflation_factor* is the
    calendar factor the state layer scales built-in amounts by;
    *calendar_inflation* gives earlier years' factors when known.
    """
    return state_data_for_year(
        _TAX_DATA.get("state", {}).get(state_code or ""), state_code, tax_year,
        calendar_factor_for(inflation_factor, tax_year, calendar_inflation))


def _calculate_taxable_social_security(
    ss_income: float,
    other_income: float,
    filing_status: str,
    mfs_lived_apart_all_year: bool = False,
) -> float:
    """Determine taxable portion of Social Security per IRS Pub. 915 worksheet.

    Uses a layered calculation (not a cliff):
      Provisional income = other_income (AGI without SS) + 0.5 * SS.
      Tier 1 (50%): min(0.5 * SS, 0.5 * (provisional - t1))
      Tier 2 (85%): min(0.85 * SS, tier2_base + 0.85 * (provisional - t2))
    Single: t1=$25k, t2=$34k, tier2_base=$4,500
    MFJ:   t1=$32k, t2=$44k, tier2_base=$6,000

    NOTE: SS provisional-income thresholds are statutorily unindexed
    (unchanged since 1984/1993). Do NOT scale by inflation_factor.
    """
    if ss_income <= 0:
        return 0.0

    provisional = other_income + 0.5 * ss_income
    if filing_status == "married_filing_separately" and not mfs_lived_apart_all_year:
        # Pub. 915 Worksheet 1: skip to 85% of provisional income, capped
        # at 85% of benefits. All-year separation uses the single thresholds.
        return .85 * min(ss_income, max(0.0, provisional))

    if filing_status == "married_filing_jointly":
        t1, t2, tier2_base = 32_000.0, 44_000.0, 6_000.0
    else:
        t1, t2, tier2_base = 25_000.0, 34_000.0, 4_500.0

    if provisional <= t1:
        return 0.0
    if provisional <= t2:
        return min(0.5 * ss_income, 0.5 * (provisional - t1))
    return min(0.85 * ss_income, min(0.5 * ss_income, tier2_base) + 0.85 * (provisional - t2))


def _social_security_excess(
    ss_income: float,
    modified_agi: float,
    filing_status: str,
    mfs_lived_apart_all_year: bool = False,
) -> float:
    """IRC 86(b)(1) excess of modified AGI plus half the benefits over the
    86(c)(1) base amount ($25,000; $32,000 joint; $0 married filing separately
    without living apart all year). Statutorily unindexed."""
    if ss_income <= 0:
        return 0.0
    if filing_status == "married_filing_jointly":
        base = 32_000.0
    elif filing_status == "married_filing_separately" and not mfs_lived_apart_all_year:
        base = 0.0
    else:
        base = 25_000.0
    return max(0.0, modified_agi + 0.5 * ss_income - base)


def cash_charitable_limit(agi: float) -> float:
    """Cash contributions to public charities: IRC 170(b)(1)(G)."""
    return float(_TAX_DATA["charitable"]["cash_agi_limit"]) * max(0.0, agi)


def capital_gain_property_charitable_limit(amount: float, agi: float) -> float:
    """Allowed deduction for capital gain property given to public charities.

    IRC 170(b)(1)(C)(i): 30% of the contribution base, within the 50% limit
    of 170(b)(1)(A).
    """
    rules = _TAX_DATA["charitable"]
    base = max(0.0, agi)
    return min(max(0.0, amount), float(rules["capital_gain_property_agi_limit"]) * base,
               float(rules["public_charity_agi_limit"]) * base)


def _calculate_state_tax(*args, **kwargs) -> float:
    """Compute state income tax; see ``_state_tax_and_taxable_income``."""
    return _state_tax_and_taxable_income(*args, **kwargs)[0]


@dataclass(frozen=True)
class _StateTaxDetails:
    tax: float
    taxable: float
    rule: object | None = None            # StateDeductionResult when the rules ran
    credits_applied: float = 0.0          # user state credits, including the refund
    refund: float = 0.0                   # refundable state credit excess
    surcharge: float = 0.0


def _state_tax_and_taxable_income(*args, **kwargs) -> tuple[float, float]:
    """Compute state income tax and the state taxable income it taxes.

    See ``_state_tax_details``, which also reports the user adjustments and
    statutory deduction rules it applied.
    """
    details = _state_tax_details(*args, **kwargs)
    return details.tax, details.taxable


def _state_tax_details(
    agi: float,
    state_code: str | None,
    custom_brackets: list[dict | Sequence[float]] | None = None,
    filing_status: str = "single",
    inflation_factor: float = 1.0,
    ca_exemption_eligible_owners: list[str] | None = None,
    holder_age: int | None = None,
    spouse_age: int | None = None,
    tax_year: int = 2026,
    state_income_adjustment: float = 0.0,
    ca_dependent_count: int = 0,
    taxable_social_security: float = 0.0,
    oh_exemption_eligible_owners: list[str] | None = None,
    oh_dependent_count: int = 0,
    net_long_term_capital_gains: float = 0.0,
    qualified_dividends: float = 0.0,
    federal_taxable_income: float = 0.0,
    retirement_exclusion: float = 0.0,
    social_security_subtraction: float | None = None,
    contribution_basis_recovery: float = 0.0,
    deduction_rule: Callable[[float, float], object] | None = None,
    adjustments: YearAdjustments | None = None,
    calendar_inflation: Mapping[int, float] | None = None,
) -> _StateTaxDetails:
    """Compute state income tax and the state taxable income it taxes.

    The taxable income is the base for local taxes levied on it (for
    example New York City and Maryland counties).

    Uses AGI as the starting point, then applies the state's own standard
    deduction and progressive brackets. Returns 0 for states with no
    income tax or when state_code is None.

    Bracket upper bounds and the state standard deduction are scaled by
    *inflation_factor* so that real tax burden stays constant in the
    nominal-dollar simulation.  This is an approximation -- most states
    index their brackets annually, but each uses a different CPI variant.

    Limitation: this intentionally simple bracket engine cannot
    exactly represent every state worksheet, credit, recapture rule, or
    federal-taxable-income starting point. See
    ``_sources`` in ``tax_brackets_2026.json`` for state-by-state limits.
    Local taxes are computed separately (coastmath.engine.local_tax).

    For MFJ filers, a state's published ``joint_brackets`` schedule is used
    when present (NJ Table B, MD Schedule II, ME). Otherwise thresholds use the
    state's joint multiplier: two by default, one for states with a single
    schedule for every filing status (OH, DC, VA, MA, RI, SC). States whose
    ``head_of_household_schedule`` is ``"joint"`` tax heads of household on
    the joint schedule and deduction. The standard deduction is doubled. A
    ``filing_status_schedules`` entry (Minnesota, New Mexico, North Dakota, Vermont; Wisconsin
    married filing jointly and separately; Rhode Island,
    South Carolina, North Carolina, New York, Oregon, Hawaii, Maine, Connecticut, Oklahoma, Nebraska, Montana, Arizona and District of Columbia head of household;
    Maine and West Virginia married filing separately; New York married filing jointly) replaces both the brackets and the standard deduction for its
    filing status.

    *net_long_term_capital_gains* is the IRC 1222 net long-term capital gain
    included in *agi*. Only states with a ``net_long_term_capital_gains``
    schedule (Montana) tax it separately; states with a
    ``long_term_capital_gain_exclusion`` (Wisconsin, Arkansas, North Dakota,
    South Carolina, Missouri) subtract a share of it, or a ``flat_amount`` of it capped
    at a share of *federal_taxable_income* (Vermont), and of *qualified_dividends* where the exclusion
    ``includes_qualified_dividends`` (North Dakota); a ``capital_gain_max_rate``
    (Hawaii) caps the rate on it.

    *retirement_exclusion* is the state's retirement-income subtraction from
    ``coastmath.engine.state_retirement_exclusion``. It is subtracted next to the
    Social Security subtraction, limited to the state AGI left after it, and
    ignored with custom brackets like the capital-gain exclusion.

    *social_security_subtraction* is the state's subtraction of federally
    taxable Social Security (``coastmath.engine.state_social_security``). When it is
    omitted, the state's rule is evaluated from *taxable_social_security* and
    *agi* alone (rules needing gross benefits or ages then subtract nothing).

    *contribution_basis_recovery* is the previously state-taxed retirement
    contribution basis recovered from this year's distributions; it is
    subtracted after the retirement exclusion, with or without custom
    brackets, mirroring the contribution add-back in
    *state_income_adjustment*.

    *deduction_rule* (statutory state deduction rules, opt-in) receives the
    state AGI after every subtraction above, and before the Social Security
    subtraction, retirement exclusion and basis recovery, and returns the state's
    standard-or-itemized deduction, exemptions after phaseout, federal income
    tax subtraction and nonrefundable credit. A supported result replaces the
    built-in standard deduction and exemptions; Ohio's exemption tiers and
    California's exemption credits stay with their own rules. Its
    ``tax_addition`` is added to the bracket tax and its ``tax_credit_rate``
    taken from that total (Connecticut) before every other credit.

    *adjustments* are the user's state surcharges and credits for the year
    (``coastmath.engine.tax_adjustments``): surcharges are added to the bracket tax,
    then nonrefundable credits, then refundable credits, whose excess is
    returned as ``refund``. California's behavioral health tax is added after
    all credits.

    The state table is the 2026 one with the state's enacted changes for
    *tax_year* applied (``coastmath.engine.state_enacted_changes``);
    *calendar_inflation* maps earlier calendar years to their inflation
    factors, which place amounts a statute sets for a later year.
    """
    if state_code is None:
        return _StateTaxDetails(0.0, 0.0)

    builtin = custom_brackets is None
    # Custom brackets replace built-in law, including its enacted changes.
    state_data = (_TAX_DATA.get("state", {}).get(state_code) if not builtin
                  else _state_data_for(state_code, tax_year, inflation_factor, calendar_inflation))
    if state_data is None:
        return _StateTaxDetails(0.0, 0.0)
    schedule = _state_schedule(state_code, state_data, custom_brackets, filing_status, tax_year,
                               inflation_factor, holder_age, spouse_age, agi)
    if schedule is None:
        return _StateTaxDetails(0.0, 0.0)
    brackets, state_deduction = schedule

    # State Social Security subtractions start from the federally taxable
    # benefits, never gross benefits (for example Schedule CA (540) line 6b
    # and Ohio Schedule of Adjustments line 16). Custom brackets keep their
    # federal-AGI semantics except where the rule says otherwise (California).
    if social_security_subtraction is None:
        social_security_subtraction = state_social_security_subtraction_for(
            state_code, not builtin, SocialSecurityContext(
                filing_status=filing_status, taxable_social_security=taxable_social_security,
                social_security_income=0.0, federal_agi=agi, modified_agi_86=0.0,
                provisional_excess=0.0, inflation_factor=inflation_factor,
                state_rate=_flat_state_rate(state_data)))
    gain_exclusion = state_data.get("long_term_capital_gain_exclusion") if builtin else None
    gain_excluded = (_capital_gain_exclusion(gain_exclusion, net_long_term_capital_gains,
                                             qualified_dividends, federal_taxable_income)
                     if gain_exclusion else 0.0)
    state_agi_before_exclusions = agi + state_income_adjustment
    if gain_exclusion and gain_exclusion.get("reduces_state_agi_for_income_limits"):
        # RSMo 143.121.3(14)(a): the RSMo 143.171 federal-tax deduction tiers
        # are measured on Missouri AGI, which excludes capital gains.
        state_agi_before_exclusions -= min(gain_excluded, max(0.0, state_agi_before_exclusions))
    state_agi = agi + state_income_adjustment - social_security_subtraction
    if builtin and retirement_exclusion > 0:
        state_agi -= min(retirement_exclusion, max(0.0, state_agi))
    if contribution_basis_recovery > 0:
        state_agi -= min(contribution_basis_recovery, max(0.0, state_agi))
    if gain_excluded:
        state_agi -= min(gain_excluded, max(0.0, state_agi))

    # Ohio's own exemption tiers stay in place under statutory deduction rules.
    rule_kept_exemption = (
        _ohio_personal_exemptions(state_data["personal_exemptions"], state_agi, filing_status, tax_year,
                                  inflation_factor, oh_exemption_eligible_owners, oh_dependent_count)
        if state_code == "OH" and builtin and tax_year >= 2026 else 0.0)
    exemption_deduction = (
        _state_exemptions(rule_kept_exemption, state_data, filing_status, inflation_factor,
                          _aged_individuals(filing_status, holder_age, spouse_age))
        if builtin else rule_kept_exemption)
    rule_result = None
    federal_tax_subtraction = 0.0
    if deduction_rule is not None:
        rule_result = deduction_rule(max(0.0, state_agi), state_agi_before_exclusions)
        if getattr(rule_result, "supported", False):
            state_deduction = max(0.0, float(rule_result.deduction))
            exemption_deduction = rule_kept_exemption + max(0.0, float(rule_result.exemption_deduction))
            federal_tax_subtraction = max(0.0, float(rule_result.federal_tax_subtraction))
        else:
            rule_result = None
    state_taxable = max(0.0, state_agi - state_deduction - exemption_deduction - federal_tax_subtraction)

    state_tax = _state_bracket_tax(state_data, builtin, brackets, state_taxable, filing_status,
                                   inflation_factor, agi, net_long_term_capital_gains)
    is_ca = state_code == "CA" and builtin
    ca_credit = (ca_exemption_credit(
        agi, filing_status, ca_exemption_eligible_owners,
        holder_age, spouse_age, tax_year, inflation_factor,
        dependent_count=ca_dependent_count,
    ) if is_ca else 0.0)
    return _state_tax_after_credits(state_tax, state_taxable, rule_result, adjustments, is_ca, ca_credit,
                                    net_long_term_capital_gains, qualified_dividends)


def _state_schedule(
    state_code: str,
    state_data: dict,
    custom_brackets: list[dict | Sequence[float]] | None,
    filing_status: str,
    tax_year: int,
    inflation_factor: float,
    holder_age: int | None,
    spouse_age: int | None,
    agi: float,
) -> tuple[list[tuple[float, float]], float] | None:
    """The state brackets and standard deduction for the filing status, scaled
    by *inflation_factor*; None when a built-in table has no brackets.

    See ``_state_tax_details`` for the joint, head-of-household and
    per-filing-status schedule conventions.
    """
    builtin = custom_brackets is None
    if not builtin:
        brackets = _convert_state_brackets(custom_brackets)
    else:
        raw = state_data.get("brackets", [])
        if not raw:
            return None
        brackets = _convert_state_brackets(raw)

    state_deduction = float(state_data.get("standard_deduction", 0))

    # States that publish a full schedule and standard deduction per filing
    # status (Minnesota) list them under ``filing_status_schedules``.
    status_schedule = (state_data.get("filing_status_schedules", {}).get(filing_status)
                       if builtin else None)
    # Published joint schedules are not always twice the single one. Custom
    # brackets retain the existing joint-threshold convention.
    joint_schedule = filing_status == "married_filing_jointly" or (
        filing_status == "head_of_household" and builtin
        and state_data.get("head_of_household_schedule") == "joint"
    )
    if status_schedule:
        brackets = _convert_state_brackets(status_schedule["brackets"])
        state_deduction = float(status_schedule["standard_deduction"])
    elif joint_schedule:
        if builtin and state_data.get("joint_brackets"):
            brackets = _convert_state_brackets(state_data["joint_brackets"])
        else:
            joint_multiplier = (float(state_data.get("joint_bracket_multiplier", 2))
                                if builtin else 2)
            brackets = [(upper * joint_multiplier, rate) for upper, rate in brackets]
        state_deduction *= 2

    if state_code == "CA" and builtin and tax_year >= 2025 and filing_status == "head_of_household":
        rules = _CA_HOUSEHOLD_DATA
        brackets = [(upper if upper is not None else float("inf"), rate)
                    for upper, rate in rules["head_of_household_brackets"]]
        state_deduction = rules["standard_deduction"]

    if builtin and state_data.get("standard_deduction_source") == "federal":
        # RSMo 143.131 (Missouri), Idaho Code 63-3022(j)(1), C.R.S.
        # 39-22-104(1.7) (Colorado taxes federal taxable income), MCA
        # 15-30-2101(22) (Montana taxes federal taxable income) and Iowa Code
        # 422.7 (Iowa taxes federal taxable income under IRC 63): the state
        # standard deduction is the federal one, i.e. IRC 63(c) for the filing
        # status plus the 63(f) amount per aged individual. This replaces the
        # doubled table amount for joint schedules. Built-in state tables
        # share the federal inflation anchor, so this tracks the federal one.
        aged_extra = _federal_data(tax_year).get("additional_standard_deduction_65", {})
        state_deduction = (get_standard_deduction(filing_status, tax_year)
                           + _aged_individuals(filing_status, holder_age, spouse_age)
                           * float(aged_extra.get(filing_status, 0.0)))

    # [29.1.1] Scale state bracket bounds and deduction by inflation_factor
    brackets = [(upper * inflation_factor, rate) for upper, rate in brackets]
    state_deduction *= inflation_factor
    if builtin and state_data.get("includes_federal_senior_deduction"):
        # States whose base is federal taxable income without decoupling
        # (Iowa) also allow the IRC 151(d)(5) senior deduction, which IRC
        # 63(b)(4) and (d)(4) subtract. It is statutory and not indexed, so
        # it is added after the inflation scaling.
        state_deduction += _senior_deduction(
            _aged_individuals(filing_status, holder_age, spouse_age), filing_status, tax_year, agi)
    return brackets, state_deduction


def _ohio_personal_exemptions(
    rule: Mapping,
    state_agi: float,
    filing_status: str,
    tax_year: int,
    inflation_factor: float,
    eligible_owners: list[str] | None,
    dependent_count: int,
) -> float:
    """Ohio's personal and dependent exemptions (2026 on).

    ORC 5747.025 and HB96 section 757.120(A): published 2025 amounts remain
    frozen for 2026; MAGI cutoffs are not indexed. No Ohio business-income
    deduction is currently modeled, so its MAGI addback does not change this
    state AGI. Future amounts use the caller's inflation forecast, not a
    published future table.
    """
    if state_agi < rule["maximum_magi"]:
        amount = next(tier["amount"] for tier in rule["tiers"]
                      if tier["maximum_magi"] is None or state_agi <= tier["maximum_magi"])
        if tax_year > rule["base_year"]:
            increment = rule["rounding_increment"]
            amount = math.ceil(amount * max(1.0, inflation_factor) / increment) * increment
        owners = set(eligible_owners or []) & {"self", "spouse"}
        if filing_status != "married_filing_jointly":
            owners.discard("spouse")
        return amount * (len(owners) + max(0, dependent_count))
    return 0.0


def _state_exemptions(
    exemption_deduction: float,
    state_data: dict,
    filing_status: str,
    inflation_factor: float,
    aged_count: int,
) -> float:
    """Add a built-in table's head-of-household, personal and aged exemptions
    to *exemption_deduction*."""
    if filing_status == "head_of_household":
        # RSMo 143.161 and Form MO-1040 line 15: a fixed, unindexed
        # head-of-household exemption.
        exemption_deduction += float(state_data.get("head_of_household_exemption", 0))
    if state_data.get("personal_exemption"):
        # Vermont Form IN-111 lines 4-5e: an indexed exemption for the filer
        # and a joint spouse. Dependent exemptions and blindness are not
        # modeled.
        filers = 2 if filing_status == "married_filing_jointly" else 1
        exemption_deduction += inflation_factor * float(state_data["personal_exemption"]) * filers
    if state_data.get("aged_additional_deduction"):
        # Vermont Form IN-111 line 5 and MCA 15-30-2120(3)(g) (Montana): an
        # indexed amount for each individual 65 or older. D.C. Code
        # 47-1801.04(44) (District of Columbia) adopts the IRC 63(c)
        # standard deduction, whose 63(f) aged amount differs for married
        # and unmarried filers, so it is keyed by filing status.
        aged_amount = state_data["aged_additional_deduction"]
        if isinstance(aged_amount, dict):
            aged_amount = aged_amount.get(filing_status, 0)
        exemption_deduction += inflation_factor * float(aged_amount) * aged_count
    if state_data.get("aged_exemption"):
        # ARS 43-1023(E) (Arizona): a fixed, unindexed exemption for each
        # individual 65 or older.
        exemption_deduction += float(state_data["aged_exemption"]) * aged_count
    return exemption_deduction


def _state_bracket_tax(
    state_data: dict,
    builtin: bool,
    brackets: list[tuple[float, float]],
    state_taxable: float,
    filing_status: str,
    inflation_factor: float,
    agi: float,
    net_long_term_capital_gains: float,
) -> float:
    """State tax on *state_taxable* before credits, with a built-in table's
    capital gain schedules, base tax, minimum tax and surtax."""
    ltcg_rule = state_data.get("net_long_term_capital_gains") if builtin else None
    if ltcg_rule:
        # MCA 15-30-2103(2) (Montana): net long-term capital gains are the top
        # layer of taxable income. They are taxed at the lower rate on the
        # filing-status band less nonqualified taxable income, and at the
        # upper rate above it. Ordinary brackets apply to the rest.
        gains = min(max(0.0, net_long_term_capital_gains), state_taxable)
        nonqualified = state_taxable - gains
        room = max(0.0, float(ltcg_rule["band"][filing_status]) * inflation_factor - nonqualified)
        state_tax = (apply_progressive_brackets(nonqualified, brackets)
                     + min(gains, room) * float(ltcg_rule["lower_rate"])
                     + max(0.0, gains - room) * float(ltcg_rule["upper_rate"]))
    else:
        state_tax = apply_progressive_brackets(state_taxable, brackets)
    gain_cap = state_data.get("capital_gain_max_rate") if builtin else None
    if gain_cap:
        # HRS 235-51(f) (Hawaii): with a net capital gain, tax is at most the
        # ordinary tax on the greater of taxable income less the gain or the
        # income taxed below the cap rate, plus the cap rate on the rest.
        cap_rate = float(gain_cap["rate"])
        gains = min(max(0.0, net_long_term_capital_gains), state_taxable)
        below_cap = max((upper for upper, rate in brackets if rate < cap_rate), default=0.0)
        base = max(state_taxable - gains, min(below_cap, state_taxable))
        state_tax = min(state_tax, apply_progressive_brackets(base, brackets)
                        + cap_rate * (state_taxable - base))
    # ORC 5747.02(A)(3)(c): Ohio's 2026 nonbusiness schedule adds $332
    # only when taxable income exceeds $26,050. Keep the amount and threshold
    # in versioned data and follow the existing future-year indexing convention.
    base_rule = state_data.get("base_tax_above_threshold") if builtin else None
    if base_rule and state_taxable > float(base_rule["threshold"]) * inflation_factor:
        state_tax += float(base_rule["amount"]) * inflation_factor
    # 32 V.S.A. 5822(a)(6): above an unindexed federal AGI threshold, Vermont
    # tax is at least 3% of federal AGI. The U.S.-obligation interest
    # subtraction is not modeled.
    minimum_tax = state_data.get("minimum_tax") if builtin else None
    if minimum_tax and agi > float(minimum_tax["agi_threshold"]):
        state_tax = max(state_tax, float(minimum_tax["rate"]) * agi)
    # TG 10-105(a)(3)(i) (Maryland, from 2025; Technical Bulletin No. 58):
    # with federal AGI above an unindexed $350,000 for every filing status,
    # an additional 2% of the whole IRC 1222(11) net capital gain. Excluded
    # gains (a residence under $1.5M, section 179 property) are not modeled.
    surtax = state_data.get("capital_gain_surtax") if builtin else None
    if surtax and agi > float(surtax["federal_agi_threshold"]):
        state_tax += float(surtax["rate"]) * max(0.0, net_long_term_capital_gains)
    return state_tax


def _state_tax_after_credits(
    state_tax: float,
    state_taxable: float,
    rule_result: object | None,
    adjustments: YearAdjustments | None,
    is_ca: bool,
    ca_credit: float,
    net_long_term_capital_gains: float,
    qualified_dividends: float,
) -> _StateTaxDetails:
    """Apply the statutory rules' tax items, user surcharges and every credit.

    *ca_credit* is California's exemption credit; with *is_ca* California's
    behavioral health tax is added after all credits.
    """
    if rule_result is not None:
        # Tax schedule items of the statutory rules (Connecticut CGS
        # 12-700(a)(10) add-back and recapture, then the 12-703 personal
        # credit as a decimal of that total), before every other credit.
        state_tax += max(0.0, float(getattr(rule_result, "tax_addition", 0.0)))
        state_tax *= 1.0 - min(1.0, max(0.0, float(getattr(rule_result, "tax_credit_rate", 0.0))))
    rule_credit = max(0.0, float(rule_result.nonrefundable_credit)) if rule_result is not None else 0.0
    if adjustments is None and rule_credit == 0.0:
        if is_ca:
            state_tax -= ca_credit
            state_tax = max(0.0, state_tax) + ca_behavioral_health_tax(state_taxable)
        return _StateTaxDetails(max(0.0, state_tax), state_taxable, rule=rule_result)
    # User surcharges, then every nonrefundable credit (the rules' credit,
    # California's exemption credits, the user's), then refundable credits.
    surcharges = adjustments.surcharges("state") if adjustments is not None else ()
    taxable_gains = min(max(0.0, net_long_term_capital_gains) + max(0.0, qualified_dividends), state_taxable)
    surcharge = surcharge_amount(surcharges, {
        "ordinary_taxable_income": state_taxable - taxable_gains, "taxable_income": state_taxable,
        "capital_gains": taxable_gains, "income_tax": max(0.0, state_tax)})
    state_tax = max(0.0, state_tax) + surcharge
    state_tax = max(0.0, state_tax - rule_credit - ca_credit)
    credits = apply_credits(state_tax, adjustments.credits("state") if adjustments is not None else ())
    state_tax = credits.tax_after
    if is_ca:
        state_tax += ca_behavioral_health_tax(state_taxable)
    return _StateTaxDetails(state_tax, state_taxable, rule=rule_result, credits_applied=credits.applied,
                            refund=credits.refund, surcharge=surcharge)


def _capital_gain_exclusion(gain_exclusion: Mapping, net_long_term_capital_gains: float,
                            qualified_dividends: float, federal_taxable_income: float) -> float:
    """Return a state's ``long_term_capital_gain_exclusion`` subtraction."""
    # Wis. Stat. 71.05(6)(b)9 (Wisconsin): subtract 30% of the net
    # capital gain on assets held more than one year. Gains and losses
    # are netted first, so only a positive net long-term gain qualifies.
    # Ark. Code Ann. 26-51-815(b) and Form AR1000D lines 7a-8 (Arkansas):
    # 50% of net capital gain is exempt, and all of it above a fixed,
    # unindexed $10,000,000. The cap applies to the household gain.
    # S.C. Code 12-6-1150 (South Carolina): deduct 44% of IRC 1222 net
    # capital gain from South Carolina taxable income. RSMo 143.121.3(14)(a)
    # (Missouri, 2025 on): subtract all income reported as a federal
    # capital gain; qualified dividends are not capital gain.
    gain = max(0.0, net_long_term_capital_gains)
    cap = gain_exclusion.get("full_exemption_above")
    if "flat_amount" in gain_exclusion:
        # 32 V.S.A. 5811(21)(B)(ii) and Schedule IN-153 lines 9 and 20-21
        # (Vermont): the first $5,000 (unindexed) of net capital gain,
        # at most 40% of federal taxable income. The alternative 40%
        # exclusion excludes publicly traded securities, so it is unmodeled.
        excluded = min(gain, float(gain_exclusion["flat_amount"]),
                       float(gain_exclusion["federal_taxable_income_share_cap"])
                       * max(0.0, federal_taxable_income))
    elif cap is None:
        excluded = float(gain_exclusion["rate"]) * gain
    else:
        excluded = (float(gain_exclusion["rate"]) * min(gain, float(cap))
                    + max(0.0, gain - float(cap)))
    if gain_exclusion.get("includes_qualified_dividends"):
        # N.D.C.C. 57-38-30.3(2)(d) (North Dakota): 40% of the net
        # long-term gain over net short-term loss and 40% of IRC 1(h)(11)
        # qualified dividends taxed at the preferential federal rate.
        excluded += float(gain_exclusion["rate"]) * max(0.0, qualified_dividends)
    return excluded


def _flat_state_rate(state_data: dict) -> float:
    """The rate of a single-rate state schedule; 0 for graduated ones."""
    rates = {float(b["rate"]) for b in state_data.get("brackets", [])}
    return rates.pop() if len(rates) == 1 else 0.0


def state_social_security_subtraction_for(
    state_code: str | None,
    custom_brackets: bool,
    context: SocialSecurityContext,
) -> float:
    """The state's subtraction of federally taxable Social Security.

    Rules live in versioned data (``social_security_subtraction``); see
    ``coastmath.engine.state_social_security``. Custom brackets apply only rules
    marked ``applies_with_custom_brackets``.
    """
    rule = _TAX_DATA.get("state", {}).get(state_code or "", {}).get("social_security_subtraction")
    if not rule or (custom_brackets and not rule.get("applies_with_custom_brackets")):
        return 0.0
    return state_social_security_subtraction(rule, context)


def state_capital_gains_excise(
    state_code: str | None,
    long_term_capital_gains: float,
    inflation_factor: float = 1.0,
) -> float:
    """A state's separate excise on long-term capital gains (Washington).

    RCW 82.87.040 and 82.87.060: 7% of Washington capital gains (federal net
    long-term gain less excluded real estate and retirement-account gains,
    less the standard deduction), plus 2.9% of the part above $1,000,000.
    Spouses and domestic partners share one standard deduction whether they
    file jointly or separately. The deduction is indexed to the Seattle CPI
    (RCW 82.87.150); the $1,000,000 threshold is not. The charitable
    deduction and the qualified small business deduction are not modeled.
    """
    rule = _TAX_DATA.get("state", {}).get(state_code or "", {}).get("capital_gains_excise")
    if not rule or long_term_capital_gains <= 0:
        return 0.0
    deduction = float(rule["standard_deduction"]) * (
        inflation_factor if rule.get("standard_deduction_indexed") else 1.0)
    taxable = max(0.0, long_term_capital_gains - deduction)
    return (float(rule["rate"]) * taxable
            + float(rule["additional_rate"]) * max(0.0, taxable - float(rule["additional_threshold"])))


def ca_behavioral_health_tax(ca_taxable_income: float) -> float:
    """California Behavioral Health Services Tax (R&TC 17043; Form 540 line 62).

    1% of taxable income above $1,000,000 for every filing status. The
    threshold is statutory: neither doubled for joint returns nor indexed.
    Exemption credits do not reduce it.
    """
    rule = _TAX_DATA["state"]["CA"]["behavioral_health_services_tax"]
    return max(0.0, ca_taxable_income - float(rule["threshold"])) * float(rule["rate"])


def state_early_distribution_rate(state_code: str | None) -> float:
    """A state's additional tax rate on early retirement distributions.

    California adds 2.5% (R&TC 17085(c); FTB 3805P line 4) to the federal
    10% IRC 72(t) tax, on the same includible amount and with the same
    exceptions. States without such a tax return 0.
    """
    rule = _TAX_DATA["state"].get(state_code or "", {}).get("early_distribution_additional_tax")
    return float(rule["rate"]) if rule else 0.0


# ---------------------------------------------------------------------------
# FICA / payroll taxes  [13.1.1]
# ---------------------------------------------------------------------------


def calculate_fica_tax(
    earned_income: float,
    filing_status: str,
    is_self_employed: bool = False,
    inflation_factor: float = 1.0,
    tax_year: int = 2026,
) -> dict[str, float]:
    """Compute FICA payroll taxes (Social Security + Medicare).

    Self-employed individuals pay both employee and employer shares.
    Additional Medicare Tax (0.9%) applies above filing-status thresholds.

    The SS wage base is scaled by *inflation_factor*; Additional Medicare
    thresholds are statutorily unindexed (IRS Topic 560) and stay fixed.
    """
    result = calculate_mixed_fica_tax(
        0.0 if is_self_employed else earned_income,
        earned_income if is_self_employed else 0.0,
        filing_status, inflation_factor, tax_year,
    )
    return {key: result[key] for key in (
        "social_security_tax", "medicare_tax", "additional_medicare_tax", "total_fica",
    )}


def _se_taxable_earnings(net_profit: float) -> float:
    """Ordinary Schedule SE method; input is profit after business expenses."""
    rules = _TAX_DATA["payroll_tax"]
    earnings = max(0.0, net_profit) * rules["se_earnings_factor"]
    return earnings if earnings >= rules["se_minimum_earnings"] else 0.0


def _additional_medicare_tax(earnings: float, filing_status: str) -> float:
    rules = _TAX_DATA["payroll_tax"]
    threshold = rules["additional_medicare_thresholds"][filing_status]
    return max(0.0, earnings - threshold) * rules["additional_medicare_rate"]


def calculate_mixed_fica_tax(
    w2_income: float,
    self_employment_income: float,
    filing_status: str,
    inflation_factor: float = 1.0,
    tax_year: int = 2026,
) -> dict[str, float]:
    """Compute payroll taxes when W-2 and self-employment income coexist.

    W-2 wages use employee FICA rates; self-employment income uses both
    employee and employer shares. The Social Security wage base is shared,
    with W-2 wages consuming the base first.

    The SS wage base is scaled by *inflation_factor*; Additional Medicare
    thresholds are statutorily unindexed (IRS Topic 560) and stay fixed.

    SE input is business net profit. Ordinary Schedule SE applies the 92.35%
    earnings adjustment and $400 floor before payroll tax, per worker.
    Optional methods and special occupations are not modeled.
    Sources: IRS Topic 554, Schedule SE, SSA contribution base and Topic 560.
    https://www.irs.gov/taxtopics/tc554
    https://www.ssa.gov/oact/cola/cbb.html
    https://www.irs.gov/taxtopics/tc560
    """
    w2 = max(0.0, w2_income)
    se = _se_taxable_earnings(self_employment_income)
    if w2 <= 0 and se <= 0:
        return {
            "social_security_tax": 0.0,
            "medicare_tax": 0.0,
            "additional_medicare_tax": 0.0,
            "total_fica": 0.0,
            "se_employer_half": 0.0,
        }

    rules = _TAX_DATA["payroll_tax"]
    # Published SSA 2025 base; future assumptions index the 2026 base.
    ss_wage_base = (176_100 if tax_year == 2025 else rules["social_security_wage_base"]) * inflation_factor
    ss_rate = rules["employee_social_security_rate"]
    medicare_rate = rules["employee_medicare_rate"]
    w2_ss_tax = min(w2, ss_wage_base) * ss_rate
    se_ss_room = max(0.0, ss_wage_base - w2)
    se_ss_tax = min(se, se_ss_room) * ss_rate * 2
    medicare_tax = w2 * medicare_rate + se * medicare_rate * 2
    additional_medicare = _additional_medicare_tax(w2 + se, filing_status)

    social_security_tax = w2_ss_tax + se_ss_tax
    total = social_security_tax + medicare_tax + additional_medicare
    # [31.1.3] SE employer-equivalent half for AGI deduction (shared wage base).
    # Only the SE portion's SS + Medicare is deductible; Additional Medicare is not.
    se_employer_half = se_ss_tax / 2.0 + se * medicare_rate
    return {
        "social_security_tax": social_security_tax,
        "medicare_tax": medicare_tax,
        "additional_medicare_tax": additional_medicare,
        "total_fica": total,
        "se_employer_half": se_employer_half,
    }


def calculate_household_fica_tax(
    w2_by_owner: dict[str, float], se_by_owner: dict[str, float],
    filing_status: str, inflation_factor: float = 1.0,
    tax_year: int = 2026,
) -> dict[str, float]:
    """Apply the SS base per worker, but Additional Medicare per tax return."""
    result = dict.fromkeys(("social_security_tax", "medicare_tax",
                           "additional_medicare_tax", "total_fica", "se_employer_half"), 0.0)
    for owner in w2_by_owner.keys() | se_by_owner.keys():
        worker = calculate_mixed_fica_tax(w2_by_owner.get(owner, 0.0),
                                        se_by_owner.get(owner, 0.0), filing_status,
                                        inflation_factor, tax_year)
        for key in ("social_security_tax", "medicare_tax", "se_employer_half"):
            result[key] += worker[key]
    # Apply the SE floor per worker before combining earnings for Form 8959.
    household_earnings = (sum(max(0.0, wages) for wages in w2_by_owner.values())
                          + sum(_se_taxable_earnings(profit) for profit in se_by_owner.values()))
    result["additional_medicare_tax"] = _additional_medicare_tax(household_earnings, filing_status)
    result["total_fica"] = sum(result[k] for k in
                               ("social_security_tax", "medicare_tax", "additional_medicare_tax"))
    return result


# ---------------------------------------------------------------------------
# Net Investment Income Tax (NIIT)  [13.1.2]
# ---------------------------------------------------------------------------


# IRC 1411(b) MAGI thresholds; statutorily unindexed.
NIIT_THRESHOLDS = {
    "single": 200_000.0,
    "married_filing_jointly": 250_000.0,
    "married_filing_separately": 125_000.0,
    "head_of_household": 200_000.0,
}


def niit_threshold(filing_status: str) -> float:
    """MAGI above which the 3.8% Net Investment Income Tax applies."""
    return NIIT_THRESHOLDS.get(filing_status, 200_000.0)


def calculate_niit(
    net_investment_income: float,
    magi: float,
    filing_status: str,
) -> float:
    """Compute the 3.8% Net Investment Income Tax.

    Applies to the lesser of net investment income or MAGI excess
    over the filing-status threshold.

    NOTE: NIIT thresholds are statutorily unindexed (ACA Sec. 1411).
    Do NOT scale by inflation_factor.
    """
    if net_investment_income <= 0:
        return 0.0

    threshold = niit_threshold(filing_status)
    excess_magi = max(0, magi - threshold)
    return min(net_investment_income, excess_magi) * 0.038


# ---------------------------------------------------------------------------
# Alternative Minimum Tax (AMT)  [13.3.1]
# ---------------------------------------------------------------------------


def calculate_amt(
    regular_taxable_income: float,
    deduction_addback: float = 0.0,
    filing_status: str = "single",
    inflation_factor: float = 1.0,
    tax_year: int = 2026,
    preferential_income: float = 0.0,
    qualified_gains: float | None = None,
    unrecaptured_section_1250_gain: float = 0.0,
) -> float:
    """Compute tentative minimum tax under the applicable published AMT rules.

    AMTI = regular taxable income + deduction_addback.

    The AMT disallows certain deductions that reduce regular taxable income
    (IRC §56(b)):
      - Standard deduction: disallowed entirely — add back the full amount.
      - Itemized SALT: disallowed — add back the capped SALT component.
      - QBI deduction (§199A): allowed under AMT — do NOT add back.
        The caller passes post-QBI taxable_income as regular_taxable_income,
        which is correct.

    Capital gains and qualified dividends participate in AMTI and exemption
    phaseout and retain preferential rates under Form 6251 Part III. The
    unrecaptured section 1250 part of *preferential_income* is taxed at 25%
    (IRC 55(b)(3)(D)), the rest at the 0/15/20% rates.
    *preferential_income* is the part of regular taxable income that is
    preferential; *qualified_gains* is the full qualified dividends plus net
    capital gain (Form 6251 line 13, the Qualified Dividends and Capital Gain
    Tax Worksheet line 4), which a deduction larger than ordinary income does
    not reduce. It defaults to *preferential_income*.
    ISO and depreciation preference items are not modeled.

    OBBBA (Public Law 119-21, §70107) changes effective 2026:
      - Phaseout thresholds reset to $500k single / $1M MFJ (from 2018 levels).
      - Phaseout rate doubled to 50 cents per dollar (from 25 cents).
      - Exemption amounts and 28% threshold continue annual inflation indexing.
      - Phaseout thresholds are NOT indexed for 2026 (IRC §55(d)(4)(B):
        "not adjusted … for any taxable year beginning before January 1, 2027").
        From 2027 onward they ARE inflation-indexed.  Since inflation_factor
        starts at 1.0 in the base year (2026), scaling by inflation_factor
        correctly yields the exact statutory value in 2026 and approximates
        post-2026 indexing in later projection years.

    Dollar thresholds (exemption_base, phaseout_start, amt_28_threshold)
    are scaled by *inflation_factor* -- the IRS indexes these annually.

    Returns the tentative minimum tax (caller compares with regular tax).
    """
    rules = _federal_data(tax_year)["amt"]
    status = filing_status if filing_status in rules["exemption"] else "single"
    exemption_base = float(rules["exemption"][status])
    phaseout_start = float(rules["phaseout_start"][status])
    amt_28_threshold = float(rules["rate_28_threshold"][status])

    # [29.1.1] Scale AMT dollar thresholds by inflation_factor
    exemption_base *= inflation_factor
    phaseout_start *= inflation_factor
    amt_28_threshold *= inflation_factor

    # AMTI: add back the deduction that was taken on the regular return
    amti = regular_taxable_income + deduction_addback + preferential_income

    if amti <= 0:
        return 0.0

    # [29.4.2] OBBBA phaseout rate: 50% (doubled from prior 25%)
    phaseout_reduction = max(0.0, (amti - phaseout_start) * float(rules["phaseout_rate"]))
    exemption = max(0.0, exemption_base - phaseout_reduction)

    amt_base = max(0.0, amti - exemption)

    def ordinary_amt(base):
        return min(base, amt_28_threshold) * .26 + max(0.0, base - amt_28_threshold) * .28
    # Form 6251 lines 13 and 16: the preferential part of the AMT base is the
    # full qualified dividends and net capital gain, capped at the base.
    line_13 = preferential_income if qualified_gains is None else qualified_gains
    gains = min(max(0.0, line_13), amt_base)
    ordinary_base = amt_base - gains
    brackets = [(upper * inflation_factor, rate) for upper, rate in get_ltcg_brackets(filing_status, tax_year)]
    # Form 6251 lines 20/27 use regular-tax ordinary income for the 0/15%
    # room, even when the AMT exemption changes the ordinary AMT base.
    unrecaptured = min(max(0.0, unrecaptured_section_1250_gain), gains)
    preferential_tax = _calculate_capital_gains_tax(gains - unrecaptured, regular_taxable_income + unrecaptured,
                                                    filing_status, ltcg_brackets=brackets)
    preferential_tax += UNRECAPTURED_1250_RATE * unrecaptured
    return min(ordinary_amt(amt_base), ordinary_amt(ordinary_base) + preferential_tax)


# ---------------------------------------------------------------------------
# Qualified Business Income (QBI) deduction  [13.3.2]
# ---------------------------------------------------------------------------


def calculate_qbi_deduction(
    qualified_business_income: float = 0.0,
    taxable_income_before_qbi: float = 0.0,
    filing_status: str = "single",
) -> float:
    """Compute the Section 199A QBI deduction (simplified).

    20% of QBI, capped at 20% of taxable income (before QBI deduction).
    Skips W-2 wage limitation, UBIA, and SSTB phase-outs.
    """
    if qualified_business_income <= 0 or taxable_income_before_qbi <= 0:
        return 0.0

    return min(0.20 * qualified_business_income, 0.20 * taxable_income_before_qbi)


# ---------------------------------------------------------------------------
# Age-based deductions
# ---------------------------------------------------------------------------


def _aged_individuals(
    filing_status: str,
    holder_age: int | None,
    spouse_age: int | None,
) -> int:
    """Count the individuals on the return who are 65 or older.

    Unknown ages count as under 65. A spouse counts only on a joint return;
    the married-filing-separately rule that allows a spouse with no income
    is not modeled.
    """
    count = 1 if holder_age is not None and holder_age >= 65 else 0
    if (
        filing_status == "married_filing_jointly"
        and spouse_age is not None
        and spouse_age >= 65
    ):
        count += 1
    return count


def _senior_deduction(
    aged_count: int,
    filing_status: str,
    tax_year: int,
    modified_agi: float,
) -> float:
    """IRC 151(d)(5) senior deduction (Pub. L. 119-21 sec. 70103).

    $6,000 per individual 65 or older for tax years 2025-2028. Each
    individual's $6,000 is reduced by 6% of MAGI above $75,000 ($150,000
    joint), so a joint deduction is gone at $250,000 whether one or both
    spouses qualify (2025 Schedule 1-A, Part V, lines 34-37). Married
    taxpayers must file jointly. Amounts are statutory and not indexed.
    """
    rules = _TAX_DATA.get("senior_deduction")
    if not rules or aged_count <= 0 or filing_status == "married_filing_separately":
        return 0.0
    if not int(rules["first_year"]) <= tax_year <= int(rules["last_year"]):
        return 0.0
    thresholds = rules["phaseout_threshold"]
    threshold = float(thresholds.get(filing_status, thresholds["single"]))
    phasedown = float(rules["phaseout_rate"]) * max(0.0, modified_agi - threshold)
    return max(0.0, float(rules["amount"]) - phasedown) * aged_count


def _child_tax_credit(
    birth_years: list[int] | None,
    filing_status: str,
    tax_year: int,
    modified_agi: float,
    federal_factor: float,
) -> float:
    """IRC 24 child tax credit before the tax-liability limit.

    Counts each child under 17 at the end of ``tax_year`` (born in or before
    it). After 2026 the per-child amount is indexed from IRC 24(i)(2)'s 2024
    base, not from the rounded 2026 $2,200: the unrounded 2026 adjustment
    carries forward before rounding down to $100. The $50-per-$1,000 MAGI
    phaseout thresholds are statutory and unindexed.
    The $500 credit for other dependents is not modeled.
    """
    rules = _TAX_DATA.get("child_tax_credit")
    if not rules or not birth_years:
        return 0.0
    children = sum(1 for year in birth_years if 0 <= tax_year - int(year) <= int(rules["max_age"]))
    if children == 0:
        return 0.0
    amount = float(rules["amount"])
    if tax_year > 2026:
        step = float(rules["index_rounding"])
        cola = float(rules["index_base_cola_2026"]) * federal_factor
        amount = math.floor(amount * cola / step + 1e-9) * step
    thresholds = rules["phaseout_threshold"]
    excess = max(0.0, modified_agi - float(thresholds.get(filing_status, thresholds["single"])))
    reduction = math.ceil(excess / float(rules["phaseout_step"]) - 1e-9) * float(rules["phaseout_per_step"])
    return max(0.0, children * amount - reduction)


def _fallback_local_income(
    w2_income: float | None,
    self_employment_income: float | None,
    w2_by_owner: dict[str, float] | None,
    se_by_owner: dict[str, float] | None,
    earned_income: float,
    is_self_employed: bool,
    net_investment_income: float,
    dividends: float,
    retirement_distributions: float,
) -> LocalIncome:
    """Local income categories inferred from aggregate ``calculate`` inputs.

    Wages and business profit use the most specific inputs supplied; other
    gross income is unclassified and treated as neither pension nor annuity.
    """
    if w2_by_owner is not None or se_by_owner is not None:
        wages = sum((w2_by_owner or {}).values())
        business = sum((se_by_owner or {}).values())
    elif w2_income is not None or self_employment_income is not None:
        wages, business = w2_income or 0.0, self_employment_income or 0.0
    else:
        wages, business = (0.0, earned_income) if is_self_employed else (earned_income, 0.0)
    return LocalIncome(
        wages=wages, self_employment=business, dividends=max(0.0, dividends),
        investment_income=max(0.0, net_investment_income),
        retirement_distributions=retirement_distributions,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def calculate(
    gross_income: float,
    deductions: float,
    filing_status: str,
    settings: dict | None = None,
    capital_gains: float = 0,
    state_code: str | None = None,
    itemized_deductions: dict | None = None,
    roth_conversions: float = 0,
    rmd_income: float = 0,
    qcd_offset: float = 0,
    charitable_deduction: float = 0,
    social_security_income: float = 0.0,
    earned_income: float = 0.0,
    is_self_employed: bool = False,
    net_investment_income: float = 0.0,
    qualified_business_income: float = 0.0,
    tax_year: int = 2026,
    w2_income: float | None = None,
    self_employment_income: float | None = None,
    inflation_factor: float = 1.0,
    w2_income_by_owner: dict[str, float] | None = None,
    self_employment_income_by_owner: dict[str, float] | None = None,
    qualified_dividends: float = 0.0,
    capital_loss_carryforward: float = 0.0,
    charitable_direct_cash: float = 0.0,
    holder_age: int | None = None,
    spouse_age: int | None = None,
    federal_inflation_factor: float | None = None,
    ca_part_year_context: CAPartYearWageContext | None = None,
    state_income_adjustment: float = 0.0,
    local_tax: dict | None = None,
    local_income: LocalIncome | None = None,
    tax_exempt_interest: float = 0.0,
    in_state_municipal_interest: float = 0.0,
    us_obligation_interest: float = 0.0,
    retirement_income: Sequence[RetirementIncome] | None = None,
    real_estate_capital_gains: float = 0.0,
    state_contribution_basis_recovery: float = 0.0,
    state_contribution_basis_distributions: float = 0.0,
    unrecaptured_section_1250_gain: float = 0.0,
    charitable_capital_gain_property: float = 0.0,
    medical_expenses: float = 0.0,
    adjustments: YearAdjustments | None = None,
    calendar_inflation: Mapping[int, float] | None = None,
) -> TaxResult:
    """Compute federal, state, local and payroll tax liability for one year.

    [29.1.1] When *inflation_factor* > 1.0, all IRS-indexed dollar
    thresholds (bracket bounds, standard deduction, LTCG brackets, AMT
    exemption/phaseout, FICA SS wage base, state brackets/deduction)
    are scaled so that real tax burden stays constant in the nominal-dollar
    simulation.  Statutorily unindexed thresholds (NIIT, Additional
    Medicare, SS provisional income) are intentionally left fixed.

    Args:
        gross_income: Total gross income for the year (excluding SS income).
        deductions: Additional deductions beyond the standard deduction.
        filing_status: One of single, married_filing_jointly,
            married_filing_separately, head_of_household.
        settings: Optional calculation settings. ``{"mode": "flat", ...}``
            applies fixed ordinary-income and capital-gains rates without
            federal/state/payroll-tax layers or a standard deduction.  This is
            useful for plans whose tax assumption is an explicit blended rate.
        capital_gains: Long-term capital gains (taxed at separate LTCG rates).
        state_code: 2-letter state code. If None, no state tax.
        itemized_deductions: Dict with property_tax, salt, charitable,
            mortgage_interest. If None, standard deduction is used.
        roth_conversions: Traditional-to-Roth conversion amount; added to
            ordinary income.
        rmd_income: RMD withdrawal amount; added to ordinary income.
        qcd_offset: Qualified charitable distribution; reduces RMD taxable
            amount.
        charitable_deduction: DAF/direct charitable deduction (AGI-limited).
            Added to itemized deductions; triggers itemizing if total exceeds
            the standard deduction.
        social_security_income: Total Social Security benefit. Only the
            taxable fraction (determined by IRS provisional income test)
            is included in AGI.
        earned_income: Portion of gross_income that is earned (W-2 or SE).
        is_self_employed: Whether any earned income is self-employment income.
        net_investment_income: Investment income subject to NIIT (capital
            gains + non-earned income).
        qualified_business_income: Business profit eligible for the IRC 199A
            deduction, before the deductible half of SE tax.
        tax_year: The calendar year taxed; selects the federal tables and
            the state law in force.
        w2_income: Wages, when known apart from self-employment profit.
            This or *self_employment_income* selects the payroll computation
            that shares one Social Security wage base.
        self_employment_income: Self-employment net profit (see *w2_income*).
        inflation_factor: Cumulative inflation multiplier (1.0 = base year).
            Scales IRS-indexed thresholds so bracket creep matches the
            nominal-dollar simulation.
        w2_income_by_owner: Wages per worker. With
            *self_employment_income_by_owner* it takes precedence over the
            aggregate payroll inputs: the Social Security wage base applies
            per worker and the Additional Medicare Tax per return.
        self_employment_income_by_owner: Self-employment net profit per worker.
        qualified_dividends: IRC 1(h)(11) dividends, taxed with
            *capital_gains* at the preferential rates.
        capital_loss_carryforward: Capital loss carried in from earlier years,
            netted against *capital_gains* (IRC 1211 and 1212). The loss left
            unused is returned as ``TaxResult.capital_loss_carryforward``.
        charitable_direct_cash: Cash gifts to public charities (not
            donor-advised funds), which non-itemizers deduct up to the IRC
            170(p) cap from 2026.
        holder_age: Taxpayer's age in the tax year. At 65 or older the
            IRC 63(f) additional standard deduction and, for 2025-2028, the
            IRC 151(d)(5) senior deduction apply. ``None`` means unknown and
            no age-based deduction is taken.
        spouse_age: Spouse's age in the tax year; counted only on a joint
            return.
        federal_inflation_factor: The calendar inflation factor for statutory
            indexing (federal, payroll and built-in state and local tables);
            None uses *inflation_factor*.
        ca_part_year_context: Optional internal timed-wage attribution for a
            CA/counterpart move. Unsupported inputs retain the legacy annual
            state estimate with diagnostics; no-context behavior is unchanged.
        state_income_adjustment: State additions less state subtractions,
            added to federal AGI for the state base.
        local_tax: The residence's local income tax selection (a catalog
            jurisdiction or custom rates); None means no local tax. Flat mode
            ignores it with the other automatic tax layers.
        local_income: Income by the categories local bases distinguish. When
            omitted, it is estimated from the aggregate arguments.
        tax_exempt_interest: IRC 103 municipal bond interest. It is not in
            *gross_income* or NII, but it enters Social Security provisional
            income (IRC 86(b)(2)(B)) and state income, and is returned for
            the ACA and IRMAA MAGI add-backs.
        in_state_municipal_interest: The part of *tax_exempt_interest* the
            state also exempts (in-state bonds).
        us_obligation_interest: U.S. Treasury interest included in
            *gross_income* (federal ordinary income and NII). States cannot
            tax it (31 U.S.C. 3124(a)), so it is subtracted from state income.
        retirement_income: Each person's pension, annuity, retirement-account
            and Social Security income with their age, for the state's
            retirement-income exclusion (``coastmath.engine.state_retirement_exclusion``).
            None or a state without a rule means no exclusion.
        real_estate_capital_gains: The part of *capital_gains* from real
            property sales, which a state capital gains excise (Washington)
            excludes.
        state_contribution_basis_recovery: Retirement contributions the
            resident state taxed when made and recovers from this year's
            distributions (``coastmath.engine.state_taxed_basis``).
        state_contribution_basis_distributions: The taxable distributions
            from the accounts carrying that basis. The recovery is limited to
            the part of them the state retirement exclusion leaves taxable.
        unrecaptured_section_1250_gain: The part of *capital_gains* that is
            depreciation on real property sold (IRC 1(h)(6)). It is taxed at
            ordinary rates capped at 25% (IRC 1(h)(1)(E)) instead of the
            0/15/20% rates; zero leaves the computation unchanged.
        charitable_capital_gain_property: Fair market value of appreciated
            shares given to public charities or donor-advised funds this
            year plus usable carryovers. Limited to 30% of AGI (IRC
            170(b)(1)(C)) and figured before cash gifts, which are then
            limited to 60% of AGI less this deduction (IRS Pub. 526).
        medical_expenses: Qualified medical expenses paid this year (IRC
            213), itemized to the extent they exceed 7.5% of AGI.
        adjustments: The user's deductions, credits and surcharges active
            this year, in nominal dollars. None (no adjustments) leaves every
            figure unchanged. ``settings["state_deduction_rules"]`` opts into
            the statutory state deduction rules for supported states.
        calendar_inflation: The calendar inflation factor of each earlier
            projection year (2026 = 1.0). Built-in state tables apply the
            state's enacted changes for *tax_year*; an amount a statute sets
            for a later year is stated in that year's dollars, and this
            places it. None assumes constant inflation since 2026.
    """
    inputs = _TaxInputs(
        gross_income=gross_income, deductions=deductions, filing_status=filing_status, settings=settings,
        capital_gains=capital_gains, state_code=state_code, itemized_deductions=itemized_deductions,
        roth_conversions=roth_conversions, rmd_income=rmd_income, qcd_offset=qcd_offset,
        charitable_deduction=charitable_deduction, social_security_income=social_security_income,
        earned_income=earned_income, is_self_employed=is_self_employed,
        net_investment_income=net_investment_income, qualified_business_income=qualified_business_income,
        tax_year=tax_year, w2_income=w2_income, self_employment_income=self_employment_income,
        inflation_factor=inflation_factor, w2_income_by_owner=w2_income_by_owner,
        self_employment_income_by_owner=self_employment_income_by_owner,
        qualified_dividends=qualified_dividends, capital_loss_carryforward=capital_loss_carryforward,
        charitable_direct_cash=charitable_direct_cash, holder_age=holder_age, spouse_age=spouse_age,
        federal_inflation_factor=federal_inflation_factor, ca_part_year_context=ca_part_year_context,
        state_income_adjustment=state_income_adjustment, local_tax=local_tax, local_income=local_income,
        tax_exempt_interest=tax_exempt_interest, in_state_municipal_interest=in_state_municipal_interest,
        us_obligation_interest=us_obligation_interest, retirement_income=retirement_income,
        real_estate_capital_gains=real_estate_capital_gains,
        state_contribution_basis_recovery=state_contribution_basis_recovery,
        state_contribution_basis_distributions=state_contribution_basis_distributions,
        unrecaptured_section_1250_gain=unrecaptured_section_1250_gain,
        charitable_capital_gain_property=charitable_capital_gain_property,
        medical_expenses=medical_expenses, adjustments=adjustments, calendar_inflation=calendar_inflation,
    )
    base = _income_base(inputs)
    # Explicit blended-rate mode replaces every automatic tax layer below.
    if settings and settings.get("mode") == "flat":
        return _flat_tax_result(inputs, base)

    # Statutory indexing is separate from economic exposure:
    # a projection crossing 2025 -> 2026 must use the published 2026 table
    # without applying a second assumed increase on top of it.
    federal_factor = inflation_factor if federal_inflation_factor is None else federal_inflation_factor
    mixed_fica, se_fica_deduction = _self_employment_tax_deduction(inputs, federal_factor)
    income = _federal_income(inputs, base, se_fica_deduction)
    deduction = _federal_deduction(inputs, income, federal_factor)
    federal = _federal_income_tax(inputs, base, income, deduction, se_fica_deduction, federal_factor)
    payroll = _payroll_tax(inputs, mixed_fica, federal_factor)

    # [13.1.2] Net Investment Income Tax
    # NIIT thresholds are statutorily unindexed -- no inflation_factor scaling.
    # MAGI ~ AGI; NII includes capital gains. Form 8960 line 5a nets a capital
    # loss up to the IRC 1211(b) amount deducted this year (at most $3,000).
    total_nii = net_investment_income + base.capital_gains - base.loss_deduction
    niit_amount = calculate_niit(total_nii, income.agi + base.capital_gains, filing_status)

    # [10.1.2] State income tax — include capital gains in state tax base
    state = _state_inputs(inputs, base, income, federal, federal_factor)
    state_rule_coverage, deduction_rule, adjustment_diagnostics = _state_deduction_rules(
        inputs, income, deduction, federal, state, payroll, niit_amount)
    state_details = _resident_state_tax(inputs, base, income, federal, state, deduction_rule)
    state_tax, state_taxable_income = state_details.tax, state_details.taxable
    state_rule_result = state_details.rule
    if state_rule_result is not None:
        adjustment_diagnostics.extend(state_rule_result.diagnostics)

    state_allocation_diagnostics: tuple[str, ...] = ()
    if ca_part_year_context is not None:
        allocation = _ca_part_year_allocation(
            inputs, base, income, state, state_rule_result, se_fica_deduction, federal_factor)
        state_allocation_diagnostics = allocation.diagnostics
        if allocation.state_tax is not None:
            state_tax = allocation.state_tax

    capital_gains_excise, state_tax = _with_capital_gains_excise(
        inputs, base, state, state_tax, state_taxable_income)
    local_result = _resident_local_tax(
        inputs, base, income, state_taxable_income, state_tax, deduction.aged_count, federal_factor)
    local_tax_amount = local_result.amount

    # Refundable credit excess is a payment: it lowers the net tax settled.
    total_tax = (federal.tax + federal.capital_gains_tax + state_tax + local_tax_amount + payroll.total
                 + niit_amount - federal.refund - state_details.refund)

    # [10.1.3] Effective rate denominator uses taxable_rmd, not gross rmd_income
    total_gross = (gross_income + social_security_income + roth_conversions + base.taxable_rmd
                   + base.capital_gains)
    effective_rate = total_tax / total_gross if total_gross > 0 else 0.0
    marginal = get_marginal_rate(federal.taxable_income, federal.brackets)

    return TaxResult(
        federal=federal.tax,
        state=state_tax,
        local=local_tax_amount,
        capital_gains_tax=federal.capital_gains_tax,
        total_tax=total_tax,
        effective_rate=effective_rate,
        marginal_rate=marginal,
        agi=income.agi,
        taxable_social_security=income.taxable_ss,
        modified_agi=income.modified_agi,
        taxable_income=federal.taxable_income,
        deduction_used=deduction.used,
        deduction_amount=deduction.amount,
        standard_deduction=deduction.standard_deduction,
        fica_tax=payroll.total,
        niit=niit_amount,
        amt=federal.amt,
        amt_excess=federal.amt_excess,
        qbi_deduction=federal.qbi_deduction,
        capital_loss_carryforward=max(0.0, base.net_loss - min(base.loss_deduction,
            max(0.0, income.agi + base.loss_deduction + base.capital_gains - deduction.amount))),
        senior_deduction=deduction.senior_deduction,
        child_tax_credit=federal.child_tax_credit,
        self_employment_tax=payroll.self_employment_tax,
        additional_medicare_tax=payroll.fica["additional_medicare_tax"],
        tax_exempt_interest=base.tax_exempt_interest,
        state_allocation_diagnostics=state_allocation_diagnostics,
        local_tax_diagnostics=local_result.diagnostics,
        state_retirement_exclusion=state.retirement_exclusion,
        state_social_security_subtraction=state.ss_subtraction,
        state_capital_gains_excise=capital_gains_excise,
        state_contribution_basis_recovery=state.basis_recovery,
        unrecaptured_section_1250_gain=federal.unrecaptured_1250,
        tax_adjustment_deductions=income.federal_adjustment_deduction
            + (deduction.user_itemized if deduction.used == "itemized" else 0.0),
        tax_adjustment_credits=federal.credits_applied + state_details.credits_applied,
        tax_adjustment_refund=federal.refund + state_details.refund,
        tax_adjustment_surcharge=federal.surcharge + state_details.surcharge,
        state_deduction_coverage=state_rule_coverage,
        state_federal_tax_subtraction=(float(state_rule_result.federal_tax_subtraction)
                                       if state_rule_result is not None else 0.0),
        tax_adjustment_diagnostics=tuple(adjustment_diagnostics),
    )


# ---------------------------------------------------------------------------
# Steps of ``calculate``
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TaxInputs:
    """The arguments of one ``calculate`` call, as given."""

    gross_income: float
    deductions: float
    filing_status: str
    settings: dict | None
    capital_gains: float
    state_code: str | None
    itemized_deductions: dict | None
    roth_conversions: float
    rmd_income: float
    qcd_offset: float
    charitable_deduction: float
    social_security_income: float
    earned_income: float
    is_self_employed: bool
    net_investment_income: float
    qualified_business_income: float
    tax_year: int
    w2_income: float | None
    self_employment_income: float | None
    inflation_factor: float
    w2_income_by_owner: dict[str, float] | None
    self_employment_income_by_owner: dict[str, float] | None
    qualified_dividends: float
    capital_loss_carryforward: float
    charitable_direct_cash: float
    holder_age: int | None
    spouse_age: int | None
    federal_inflation_factor: float | None
    ca_part_year_context: CAPartYearWageContext | None
    state_income_adjustment: float
    local_tax: dict | None
    local_income: LocalIncome | None
    tax_exempt_interest: float
    in_state_municipal_interest: float
    us_obligation_interest: float
    retirement_income: Sequence[RetirementIncome] | None
    real_estate_capital_gains: float
    state_contribution_basis_recovery: float
    state_contribution_basis_distributions: float
    unrecaptured_section_1250_gain: float
    charitable_capital_gain_property: float
    medical_expenses: float
    adjustments: YearAdjustments | None
    calendar_inflation: Mapping[int, float] | None

    def setting(self, key: str, default: object = None):
        """A calculation setting, or *default* when it or the settings are absent."""
        return (self.settings or {}).get(key, default)

    def dependents_for_year(self, key: str) -> int:
        """The tax year's count in a by-year dependents setting keyed by year."""
        by_year = self.setting(key) or {}
        return by_year.get(str(self.tax_year), by_year.get(self.tax_year, 0))


@dataclass(frozen=True)
class _IncomeBase:
    """Income netted the same way on the flat and detailed paths."""

    taxable_rmd: float          # RMDs less the QCD offsetting them
    net_sales: float            # realized sales gains less the carried capital loss
    net_loss: float
    loss_deduction: float       # IRC 1211(b) ordinary deduction of the net loss
    deductions: float           # the input deductions plus loss_deduction
    capital_gains: float        # positive net sales gains plus qualified dividends
    tax_exempt_interest: float


def _income_base(inputs: _TaxInputs) -> _IncomeBase:
    # QCD reduces the taxable portion of RMD income (capped so offset <= rmd_income)
    taxable_rmd = inputs.rmd_income - min(inputs.qcd_offset, inputs.rmd_income)
    # IRC 1211/1212: net realized sales against carried losses first.
    # Qualified dividends keep their preferential rate but are not sales gains.
    net_sales = inputs.capital_gains - max(0.0, inputs.capital_loss_carryforward)
    net_loss = max(0.0, -net_sales)
    loss_limits = _TAX_DATA["capital_loss_ordinary_deduction_limit"]
    loss_limit = float(loss_limits.get(inputs.filing_status, loss_limits["default"]))
    loss_deduction = min(net_loss, loss_limit)
    return _IncomeBase(
        taxable_rmd=taxable_rmd,
        net_sales=net_sales,
        net_loss=net_loss,
        loss_deduction=loss_deduction,
        deductions=inputs.deductions + loss_deduction,
        capital_gains=max(0.0, net_sales) + max(0.0, inputs.qualified_dividends),
        tax_exempt_interest=max(0.0, inputs.tax_exempt_interest),
    )


@dataclass(frozen=True)
class _AdjustedIncomeTax:
    ordinary_tax: float
    capital_gains_tax: float
    surcharge: float
    credits_applied: float
    refund: float


def _apply_federal_adjustments(
    adjustments: YearAdjustments,
    ordinary_tax: float,
    capital_gains_tax: float,
    ordinary_taxable_income: float,
    taxable_capital_gains: float,
) -> _AdjustedIncomeTax:
    """The user's federal surcharges, then credits, on income tax.

    A surcharge is added to the ordinary tax; credits reduce the ordinary
    tax first, then the capital gains tax.
    """
    surcharge = surcharge_amount(adjustments.surcharges("federal"), {
        "ordinary_taxable_income": ordinary_taxable_income,
        "taxable_income": ordinary_taxable_income + taxable_capital_gains,
        "capital_gains": taxable_capital_gains,
        "income_tax": ordinary_tax + capital_gains_tax})
    ordinary_tax += surcharge
    credits = apply_credits(ordinary_tax + capital_gains_tax, adjustments.credits("federal"))
    reduction = ordinary_tax + capital_gains_tax - credits.tax_after
    ordinary_reduction = min(reduction, ordinary_tax)
    ordinary_tax -= ordinary_reduction
    capital_gains_tax -= reduction - ordinary_reduction
    return _AdjustedIncomeTax(ordinary_tax, capital_gains_tax, surcharge, credits.applied, credits.refund)


def _flat_tax_result(inputs: _TaxInputs, base: _IncomeBase) -> TaxResult:
    """Explicit blended-rate mode (``settings["mode"] == "flat"``).

    This intentionally bypasses the automatic US federal/state/FICA/AMT/NIIT
    stack: the configured ordinary rate is the complete tax assumption.
    Payroll/pre-tax deductions still reduce the ordinary base, and capital
    gains retain their separately configured rate.
    """
    settings = inputs.settings
    ordinary_rate = float(settings.get("ordinary_income_tax_rate") or 0.0)
    capital_gains_rate = float(settings["capital_gains_tax_rate"] if settings.get("capital_gains_tax_rate") is not None else ordinary_rate)
    if not 0.0 <= ordinary_rate <= 1.0:
        raise ValueError("ordinary_income_tax_rate must be between 0 and 1")
    if not 0.0 <= capital_gains_rate <= 1.0:
        raise ValueError("capital_gains_tax_rate must be between 0 and 1")

    # User adjustments: the blended rate has no federal/state split or
    # itemizing, so only federal above-the-line deductions and federal
    # surcharges and credits apply.
    adjustments = inputs.adjustments
    flat_deductions = adjustments.federal_above_the_line if adjustments is not None else 0.0
    agi_without_ss = (inputs.gross_income + inputs.roth_conversions + base.taxable_rmd
                      - base.deductions - flat_deductions)
    taxable_ss = _calculate_taxable_social_security(
        inputs.social_security_income,
        agi_without_ss + base.capital_gains + base.tax_exempt_interest,
        inputs.filing_status,
        inputs.setting("mfs_lived_apart_all_year", False),
    )
    agi = agi_without_ss + taxable_ss
    ordinary_taxable_income = max(0.0, agi)
    taxable_capital_gains = max(0.0, base.capital_gains)
    ordinary_tax = ordinary_taxable_income * ordinary_rate
    capital_gains_tax = taxable_capital_gains * capital_gains_rate
    surcharge = credits_applied = refund = 0.0
    diagnostics: tuple[str, ...] = ()
    if adjustments is not None:
        adjusted = _apply_federal_adjustments(
            adjustments, ordinary_tax, capital_gains_tax, ordinary_taxable_income, taxable_capital_gains)
        ordinary_tax, capital_gains_tax = adjusted.ordinary_tax, adjusted.capital_gains_tax
        surcharge, credits_applied, refund = adjusted.surcharge, adjusted.credits_applied, adjusted.refund
        if any(item.kind == "deduction" and item.deduction_type == "itemized" or item.scope == "state"
               for item in adjustments.items):
            diagnostics = ("Flat tax mode applies only federal above-the-line deductions and "
                           "federal credits and surcharges; itemized and state adjustments are not applied.",)
    total_tax = ordinary_tax + capital_gains_tax - refund
    total_gross = (
        inputs.gross_income
        + inputs.social_security_income
        + inputs.roth_conversions
        + base.taxable_rmd
        + base.capital_gains
    )
    return TaxResult(
        federal=ordinary_tax,
        capital_gains_tax=capital_gains_tax,
        total_tax=total_tax,
        effective_rate=total_tax / total_gross if total_gross > 0 else 0.0,
        marginal_rate=ordinary_rate,
        agi=agi,
        taxable_social_security=taxable_ss,
        modified_agi=agi + base.capital_gains,
        taxable_income=ordinary_taxable_income,
        deduction_used="custom_flat",
        deduction_amount=max(0.0, base.deductions + flat_deductions),
        standard_deduction=0.0,
        capital_loss_carryforward=max(0.0, base.net_loss - min(base.loss_deduction,
            max(0.0, agi + base.loss_deduction + base.capital_gains))),
        tax_exempt_interest=base.tax_exempt_interest,
        state_allocation_diagnostics=(
            ("California part-year wage allocation unsupported in flat tax mode; "
             "retained the configured blended-rate estimate.",)
            if inputs.ca_part_year_context is not None else ()
        ),
        tax_adjustment_deductions=flat_deductions,
        tax_adjustment_credits=credits_applied,
        tax_adjustment_refund=refund,
        tax_adjustment_surcharge=surcharge,
        tax_adjustment_diagnostics=diagnostics,
    )


def _self_employment_tax_deduction(
    inputs: _TaxInputs, federal_factor: float,
) -> tuple[dict[str, float] | None, float]:
    """[13.1.1] The employer-equivalent half of SE FICA, which reduces AGI.

    [31.1.3] When W-2 and SE income are given separately, the mixed-FICA
    computation (shared SS wage base) makes the deduction reflect that W-2
    wages consume the Social Security base first. Its result is returned
    for reuse as the FICA liability; it is None for the aggregate inputs.
    """
    filing_status, tax_year = inputs.filing_status, inputs.tax_year
    if inputs.w2_income_by_owner is not None or inputs.self_employment_income_by_owner is not None:
        mixed_fica = calculate_household_fica_tax(
            inputs.w2_income_by_owner or {}, inputs.self_employment_income_by_owner or {},
            filing_status, federal_factor, tax_year)
        return mixed_fica, mixed_fica["se_employer_half"]
    if inputs.w2_income is not None or inputs.self_employment_income is not None:
        mixed_fica = calculate_mixed_fica_tax(
            inputs.w2_income or 0.0, inputs.self_employment_income or 0.0, filing_status,
            inflation_factor=federal_factor, tax_year=tax_year,
        )
        return mixed_fica, mixed_fica["se_employer_half"]
    if inputs.is_self_employed and inputs.earned_income > 0:
        fica = calculate_fica_tax(
            inputs.earned_income, filing_status, is_self_employed=True,
            inflation_factor=federal_factor, tax_year=tax_year,
        )
        # IRC 164(f) excludes the Additional Medicare Tax, which
        # calculate_fica_tax reports apart from medicare_tax.
        return None, (fica["social_security_tax"] + fica["medicare_tax"]) / 2.0
    return None, 0.0


@dataclass(frozen=True)
class _FederalIncome:
    agi_without_ss: float
    taxable_ss: float
    agi: float                          # federal AGI before capital gains
    modified_agi: float                 # agi plus capital gains
    federal_adjustment_deduction: float  # the user's federal above-the-line deductions
    state_income_adjustment: float      # the input adjustment net of the user's deductions


def _federal_income(inputs: _TaxInputs, base: _IncomeBase, se_fica_deduction: float) -> _FederalIncome:
    # User above-the-line deductions lower federal AGI; the state base adds
    # back federal-only ones and subtracts state-only ones.
    deductions = base.deductions
    state_income_adjustment = inputs.state_income_adjustment
    federal_adjustment_deduction = 0.0
    if inputs.adjustments is not None:
        federal_adjustment_deduction = inputs.adjustments.federal_above_the_line
        deductions += federal_adjustment_deduction
        state_income_adjustment += federal_adjustment_deduction - inputs.adjustments.state_above_the_line

    # Compute AGI without SS first (needed for provisional income test)
    agi_without_ss = (inputs.gross_income + inputs.roth_conversions + base.taxable_rmd
                      - deductions - se_fica_deduction)

    # [10.1.1] IRS provisional income test determines taxable SS fraction.
    # Capital gains are part of MAGI for this worksheet, even though they are
    # taxed separately below. IRC 86(b)(2)(B) adds tax-exempt interest.
    taxable_ss = _calculate_taxable_social_security(
        inputs.social_security_income, agi_without_ss + base.capital_gains + base.tax_exempt_interest,
        inputs.filing_status, inputs.setting("mfs_lived_apart_all_year", False),
    )
    agi = agi_without_ss + taxable_ss
    return _FederalIncome(
        agi_without_ss=agi_without_ss,
        taxable_ss=taxable_ss,
        agi=agi,
        modified_agi=agi + base.capital_gains,
        federal_adjustment_deduction=federal_adjustment_deduction,
        state_income_adjustment=state_income_adjustment,
    )


@dataclass(frozen=True)
class _FederalDeduction:
    standard_deduction: float       # basic plus the IRC 63(f) aged amounts
    aged_count: int
    user_itemized: float
    total_itemized: float           # 0 when nothing itemizable was given
    capped_salt: float
    used: str                       # "standard" or "itemized"
    non_itemizer_charitable: float  # the IRC 170(p) deduction; 0 when itemizing
    senior_deduction: float
    amount: float                   # the deduction taken, with the senior deduction


def _federal_deduction(inputs: _TaxInputs, income: _FederalIncome, federal_factor: float) -> _FederalDeduction:
    """The standard or itemized deduction, whichever is larger, plus the senior deduction."""
    filing_status, tax_year, settings = inputs.filing_status, inputs.tax_year, inputs.settings
    # [29.1.1] Scale standard deduction by inflation_factor
    standard_deduction = get_standard_deduction(filing_status, tax_year) * federal_factor
    if settings and settings.get("federal_standard_deduction") is not None:
        # A custom basic standard deduction; the IRC 63(f) additional amount
        # and the senior deduction below still follow current law.
        standard_deduction = float(settings["federal_standard_deduction"]) * custom_federal_factor(
            settings, inputs.inflation_factor)
    # IRC 63(f): an additional standard deduction for each individual who is
    # 65 or older. The spouse counts on a joint return only; unmarried filers
    # get the larger amount. Indexed with the basic standard deduction.
    aged_count = _aged_individuals(filing_status, inputs.holder_age, inputs.spouse_age)
    aged_extra = _federal_data(tax_year).get("additional_standard_deduction_65", {})
    standard_deduction += aged_count * float(aged_extra.get(filing_status, 0.0)) * federal_factor

    adjustments = inputs.adjustments
    user_itemized = adjustments.federal_itemized if adjustments is not None else 0.0
    charitable_rules = _TAX_DATA.get("charitable", {}) if tax_year >= 2026 else {}
    # 26 USC 170(p): non-itemizers deduct cash gifts to public charities
    # (not donor-advised funds) up to a fixed, unindexed cap. Itemizing
    # forfeits it, so it belongs in the itemize-or-not comparison.
    non_itemizer_caps = charitable_rules.get("non_itemizer_cash_deduction", {})
    non_itemizer_charitable = min(max(0.0, inputs.charitable_direct_cash),
                                  float(non_itemizer_caps.get(filing_status, 0.0)))
    # [31.1.1] Zero on the standard path so the AMT addback can read it.
    capped_salt = total_itemized = 0.0
    itemize = False
    if inputs.itemized_deductions is not None or inputs.charitable_deduction > 0 \
            or inputs.charitable_capital_gain_property > 0 or inputs.medical_expenses > 0 or user_itemized > 0:
        capped_salt, total_itemized = _itemized_deductions(
            inputs, income.modified_agi, user_itemized, charitable_rules)
        itemize = total_itemized > standard_deduction + non_itemizer_charitable
    if itemize:
        used, amount, non_itemizer_charitable = "itemized", total_itemized, 0.0
    else:
        used, amount = "standard", standard_deduction + non_itemizer_charitable

    # IRC 151(d)(5) (Pub. L. 119-21): $6,000 senior deduction per individual
    # 65 or older for 2025-2028, allowed whether or not the taxpayer itemizes,
    # phased down by 6% of MAGI above the threshold.
    senior_deduction = _senior_deduction(aged_count, filing_status, tax_year, income.modified_agi)
    amount += senior_deduction
    return _FederalDeduction(
        standard_deduction=standard_deduction,
        aged_count=aged_count,
        user_itemized=user_itemized,
        total_itemized=total_itemized,
        capped_salt=capped_salt,
        used=used,
        non_itemizer_charitable=non_itemizer_charitable,
        senior_deduction=senior_deduction,
        amount=amount,
    )


def _itemized_deductions(
    inputs: _TaxInputs, modified_agi: float, user_itemized: float, charitable_rules: Mapping,
) -> tuple[float, float]:
    """The capped SALT deduction and the total itemized deductions."""
    existing = inputs.itemized_deductions or {}
    salt_total = existing.get("salt", 0) + existing.get("property_tax", 0)
    capped_salt = min(
        salt_total,
        _salt_cap_for_year(inputs.tax_year, inputs.filing_status, modified_agi),
    )
    # Pub. 526: use the contribution base after all income, conversions,
    # capital gains, QCD exclusions and above-the-line deductions.
    # Pub. 526 ordering: capital gain property first (30% and 50% limits),
    # then cash within 60% of AGI less the other contributions allowed.
    property_gifts = capital_gain_property_charitable_limit(
        inputs.charitable_capital_gain_property, modified_agi)
    itemized_charitable = property_gifts + min(
        max(0.0, existing.get("charitable", 0) + inputs.charitable_deduction),
        max(0.0, cash_charitable_limit(modified_agi) - property_gifts),
    )
    # 26 USC 170(b)(1)(I): itemized charitable deductions are allowed only
    # to the extent they exceed 0.5% of the contribution base (AGI).
    floor = float(charitable_rules.get("itemized_floor_rate", 0.0)) * max(0.0, modified_agi)
    itemized_charitable = max(0.0, itemized_charitable - floor)
    total_itemized = (
        capped_salt
        + itemized_charitable
        # The acquisition-debt cap needs debt history the plan model does
        # not hold; affected simulations warn.
        # Mortgage interest is supplied as deductible interest. The plan
        # model lacks debt origination/use history; simulator estimates
        # using raw interest must surface that limitation to the caller.
        + existing.get("mortgage_interest", 0)
        # IRC 213(a): medical expenses above 7.5% of AGI.
        + max(0.0, max(0.0, inputs.medical_expenses)
              - float(_TAX_DATA["medical"]["agi_floor_rate"]) * max(0.0, modified_agi))
        # User itemized deductions (IRC 63(d)); never an AGI reduction.
        + user_itemized
    )
    return capped_salt, total_itemized


@dataclass(frozen=True)
class _FederalTax:
    taxable_income: float           # ordinary taxable income after the QBI deduction
    taxable_capital_gains: float
    qbi_deduction: float
    brackets: list[tuple[float, float]]
    unrecaptured_1250: float
    amt: float                      # tentative minimum tax
    amt_excess: float
    child_tax_credit: float
    tax: float                      # regular tax plus AMT excess, after credits and surcharges
    capital_gains_tax: float
    surcharge: float
    credits_applied: float
    refund: float

    @property
    def income_tax_liability(self) -> float:
        """Federal income tax after nonrefundable credits: no payroll, SE tax or NIIT."""
        return self.tax + self.capital_gains_tax


def _federal_income_tax(
    inputs: _TaxInputs,
    base: _IncomeBase,
    income: _FederalIncome,
    deduction: _FederalDeduction,
    se_fica_deduction: float,
    federal_factor: float,
) -> _FederalTax:
    """Regular, capital gains and alternative minimum tax, less credits."""
    filing_status, tax_year = inputs.filing_status, inputs.tax_year
    ordinary_taxable_income = max(0.0, income.agi - deduction.amount)
    deduction_remaining_for_gains = max(0.0, deduction.amount - income.agi)
    taxable_capital_gains = max(0.0, base.capital_gains - deduction_remaining_for_gains)

    # [13.3.2 / 31.1.2] QBI deduction — applied before federal brackets.
    # QBI is business profit net of the deductible half of SE tax (se_fica_deduction).
    qbi_net = max(0.0, inputs.qualified_business_income - se_fica_deduction)
    qbi_deduction = calculate_qbi_deduction(
        qbi_net, ordinary_taxable_income, filing_status,
    )
    taxable_income = max(0.0, ordinary_taxable_income - qbi_deduction)

    # [29.1.1] Scale federal bracket bounds by inflation_factor
    brackets = federal_ordinary_brackets(inputs.settings, filing_status, tax_year, federal_factor,
                                         inputs.inflation_factor)
    regular_tax = apply_progressive_brackets(taxable_income, brackets)

    # [29.1.1] Scale LTCG bracket bounds by inflation_factor
    ltcg_brackets = [(upper * federal_factor, rate) for upper, rate in get_ltcg_brackets(filing_status, tax_year)]

    # Capital gains tax (stacked on top of ordinary income)
    # IRC 1(h)(1)(E): unrecaptured section 1250 gain, limited to the net
    # capital gain without qualified dividends and to what is taxable.
    unrecaptured_1250 = min(max(0.0, inputs.unrecaptured_section_1250_gain), max(0.0, base.net_sales),
                            taxable_capital_gains)
    if unrecaptured_1250 > 0:
        cg_tax = _capital_gains_tax_with_unrecaptured_1250(
            taxable_capital_gains, unrecaptured_1250, taxable_income, brackets, ltcg_brackets,
        )
    else:
        cg_tax = _calculate_capital_gains_tax(
            taxable_capital_gains, taxable_income, filing_status,
            ltcg_brackets=ltcg_brackets,
        )

    # [31.1.1] AMT add-back: what was actually deducted on the regular return.
    # Standard deduction is entirely disallowed under AMT (IRC §56(b)(1)(E));
    # for itemizers, only the SALT component is disallowed (IRC §56(b)(1)(A)).
    # The deduction amount is already inflation-scaled (29.1.1).
    # The senior deduction sits with the personal-exemption deduction in IRC
    # 151, which AMT also disallows (IRC 56(b)(1)(E)), so it is added back
    # on both paths (the standard path already includes it in the amount).
    # The 170(p) gift deduction is a section 170 deduction AMT allows.
    if deduction.used == "standard":
        amt_addback = deduction.amount - deduction.non_itemizer_charitable
    else:
        amt_addback = deduction.capped_salt + deduction.senior_deduction

    # [13.3.1] AMT — federal tax is the greater of regular tax or tentative AMT
    amt_amount = calculate_amt(
        taxable_income, amt_addback, filing_status,
        inflation_factor=federal_factor, tax_year=tax_year,
        preferential_income=taxable_capital_gains,
        qualified_gains=base.capital_gains,
        unrecaptured_section_1250_gain=unrecaptured_1250,
    )
    amt_excess = max(0.0, amt_amount - regular_tax - cg_tax)
    federal_tax = regular_tax + amt_excess

    # IRC 24 child tax credit, limited to income tax (Schedule 8812 Credit
    # Limit Worksheet A). The refundable ACTC portion is not modeled.
    child_tax_credit = min(
        _child_tax_credit(inputs.setting("dependent_birth_years"), filing_status,
                          tax_year, income.modified_agi, federal_factor),
        federal_tax + cg_tax,
    )
    federal_credit = min(child_tax_credit, federal_tax)
    federal_tax -= federal_credit
    cg_tax -= child_tax_credit - federal_credit

    # User surcharges, then credits, on federal income tax only (regular
    # tax, AMT and capital gains tax; never payroll, SE tax or NIIT).
    surcharge = credits_applied = refund = 0.0
    if inputs.adjustments is not None:
        adjusted = _apply_federal_adjustments(
            inputs.adjustments, federal_tax, cg_tax, taxable_income, taxable_capital_gains)
        federal_tax, cg_tax = adjusted.ordinary_tax, adjusted.capital_gains_tax
        surcharge, credits_applied, refund = adjusted.surcharge, adjusted.credits_applied, adjusted.refund
    return _FederalTax(
        taxable_income=taxable_income,
        taxable_capital_gains=taxable_capital_gains,
        qbi_deduction=qbi_deduction,
        brackets=brackets,
        unrecaptured_1250=unrecaptured_1250,
        amt=amt_amount,
        amt_excess=amt_excess,
        child_tax_credit=child_tax_credit,
        tax=federal_tax,
        capital_gains_tax=cg_tax,
        surcharge=surcharge,
        credits_applied=credits_applied,
        refund=refund,
    )


@dataclass(frozen=True)
class _PayrollTax:
    fica: dict[str, float]
    total: float
    self_employment_tax: float      # Schedule SE tax, both halves


def _payroll_tax(inputs: _TaxInputs, mixed_fica: dict[str, float] | None, federal_factor: float) -> _PayrollTax:
    # [13.1.1] FICA / payroll taxes
    # [31.1.3] Reuse the mixed-FICA result computed for the deduction;
    # fall back to the standalone helper for legacy callers.
    if mixed_fica is not None:
        fica = mixed_fica
    else:
        fica = calculate_fica_tax(
            inputs.earned_income, inputs.filing_status, inputs.is_self_employed,
            inflation_factor=federal_factor, tax_year=inputs.tax_year,
        )
    # Schedule SE tax (both halves) for IRC 6654; the legacy helper is all-SE
    # or all-W-2 and omits the employer-half key.
    self_employment_tax = (2.0 * fica["se_employer_half"] if "se_employer_half" in fica
                           else fica["social_security_tax"] + fica["medicare_tax"] if inputs.is_self_employed
                           else 0.0)
    return _PayrollTax(fica=fica, total=fica["total_fica"], self_employment_tax=self_employment_tax)


@dataclass(frozen=True)
class _StateInputs:
    custom_brackets: list | None
    factor: float                   # inflation factor for the state's thresholds
    data: dict                      # the state's table for the year; {} without one
    interest_adjustment: float      # taxable municipal less exempt U.S. obligation interest
    ss_subtraction: float
    retirement_exclusion: float
    basis_recovery: float
    real_estate_gain_exclusion: float


def _state_inputs(
    inputs: _TaxInputs,
    base: _IncomeBase,
    income: _FederalIncome,
    federal: _FederalTax,
    federal_factor: float,
) -> _StateInputs:
    """The state table and the subtractions from federal income on the state return."""
    state_code, tax_year, filing_status = inputs.state_code, inputs.tax_year, inputs.filing_status
    custom_state = None
    if inputs.settings and "state_brackets" in inputs.settings:
        custom_state = inputs.settings["state_brackets"]
    # Built-in state tables share the calendar anchor. Custom thresholds are
    # plan inputs, so their stated dollars retain the plan-relative factor.
    state_factor = inputs.inflation_factor if custom_state is not None else federal_factor
    if state_code == "CA" and custom_state is None and tax_year >= 2025:
        # Form 540-ES prescribes the published 2025 table for 2026 estimates.
        # Subsequent projected thresholds and credits follow calendar years,
        # not the projection's partial-year economic exposure or start date.
        state_factor = 1.0 if tax_year <= 2026 else federal_factor
    # States tax municipal interest from other states' bonds (in-state bonds
    # only when the plan does not mark them exempt) and cannot tax U.S.
    # obligation interest (31 U.S.C. 3124(a)). Only the nonqualified part of
    # dividends reaches state ordinary income; qualified_dividends below stays
    # the IRC 1(h)(11) amount that state dividend rules key on.
    state_interest_adjustment = (
        max(0.0, base.tax_exempt_interest - max(0.0, inputs.in_state_municipal_interest))
        - max(0.0, inputs.us_obligation_interest)
    )
    # The built-in table for this year, with enacted later changes; custom
    # brackets keep the 2026 entry (they replace built-in law).
    state_data = ((_TAX_DATA["state"].get(state_code or "") if custom_state is not None
                   else _state_data_for(state_code, tax_year, state_factor, inputs.calendar_inflation)) or {})
    persons = tuple(inputs.retirement_income or ())
    mfs_apart = inputs.setting("mfs_lived_apart_all_year", False)
    modified_agi_86 = income.agi_without_ss + base.capital_gains + base.tax_exempt_interest
    ss_subtraction = state_social_security_subtraction_for(
        state_code, custom_state is not None, SocialSecurityContext(
            filing_status=filing_status, taxable_social_security=income.taxable_ss,
            social_security_income=inputs.social_security_income,
            federal_agi=income.modified_agi, modified_agi_86=modified_agi_86,
            provisional_excess=_social_security_excess(
                inputs.social_security_income, modified_agi_86, filing_status, mfs_apart),
            tax_exempt_interest=base.tax_exempt_interest, persons=persons,
            inflation_factor=state_factor, state_rate=_flat_state_rate(state_data),
        ))
    # RSMo 143.121.3(14)(a): Missouri AGI excludes capital gains, so the
    # limits keyed to it (the RSMo 143.124 private-pension phase-out and the
    # RSMo 143.171 federal-tax deduction tiers) exclude them too.
    gain_rule = state_data.get("long_term_capital_gain_exclusion") if custom_state is None else None
    state_agi_gain_subtraction = (
        _capital_gain_exclusion(gain_rule, max(0.0, base.net_sales), max(0.0, inputs.qualified_dividends),
                                federal.taxable_income + federal.taxable_capital_gains)
        if gain_rule and gain_rule.get("reduces_state_agi_for_income_limits") else 0.0)
    state_agi_before_exclusions = max(0.0, income.modified_agi + income.state_income_adjustment
                                      + state_interest_adjustment - ss_subtraction
                                      - state_agi_gain_subtraction)
    retirement_exclusion = 0.0
    retirement_rule = state_data.get("retirement_income_exclusion") if custom_state is None else None
    if retirement_rule and inputs.retirement_income:
        retirement_exclusion = state_retirement_exclusion(
            retirement_rule, inputs.retirement_income, filing_status,
            federal_agi=income.modified_agi - state_agi_gain_subtraction,
            taxable_social_security=income.taxable_ss,
            social_security_income=inputs.social_security_income,
            inflation_factor=state_factor,
        )
        # The amount subtracted, at most the state AGI left after the Social
        # Security subtraction. Colorado's Social Security subtraction is
        # inside its retirement rule, so its data rule subtracts nothing.
        retirement_exclusion = min(retirement_exclusion, state_agi_before_exclusions)
    basis_recovery = _contribution_basis_recovery(
        inputs.state_contribution_basis_recovery, inputs.state_contribution_basis_distributions,
        persons, retirement_exclusion, state_agi_before_exclusions)
    # Washington's income tax (from 2028) excludes long-term capital gains
    # except those its capital gains excise taxes, so real property gains
    # leave its base; the excise paid on included gains is credited later.
    if custom_state is None and state_data.get("excludes_real_estate_capital_gains"):
        real_estate_gain_exclusion = min(max(0.0, inputs.real_estate_capital_gains), max(0.0, base.net_sales))
    else:
        real_estate_gain_exclusion = 0.0
    return _StateInputs(
        custom_brackets=custom_state,
        factor=state_factor,
        data=state_data,
        interest_adjustment=state_interest_adjustment,
        ss_subtraction=ss_subtraction,
        retirement_exclusion=retirement_exclusion,
        basis_recovery=basis_recovery,
        real_estate_gain_exclusion=real_estate_gain_exclusion,
    )


def _contribution_basis_recovery(
    recovery: float,
    distributions: float,
    persons: Sequence[RetirementIncome],
    retirement_exclusion: float,
    state_agi_before_exclusions: float,
) -> float:
    """State-taxed contribution basis recovered from this year's distributions.

    Only the part of the basis accounts' distributions the retirement
    exclusion left taxable can be recovered. The exclusion is attributed to
    them by their share of covered income.
    """
    basis_distributions = max(0.0, distributions)
    if recovery > 0 and basis_distributions > 0:
        covered = sum(max(0.0, amount) for person in persons for amount in person.amounts.values())
        excluded = (retirement_exclusion * min(1.0, basis_distributions / covered)
                    if covered > 0 else 0.0)
        return min(recovery, max(0.0, basis_distributions - excluded),
                   max(0.0, state_agi_before_exclusions - retirement_exclusion))
    return 0.0


def _state_deduction_rules(
    inputs: _TaxInputs,
    income: _FederalIncome,
    deduction: _FederalDeduction,
    federal: _FederalTax,
    state: _StateInputs,
    payroll: _PayrollTax,
    niit_amount: float,
) -> tuple[str, Callable[[float, float], object] | None, list[str]]:
    """Statutory state deduction rules (opt-in, supported states only).

    Returns the rules' coverage of the state, the rule for
    ``_state_tax_details`` (None when they do not run) and diagnostics.
    The context separates raw itemized categories (before the federal SALT
    cap and AGI floors) from the federal itemized result and election.
    Federal income tax paid is not tracked apart from all withholding, so
    the paid basis is unknown here and the evaluator says how it falls back.
    """
    state_code, tax_year, adjustments = inputs.state_code, inputs.tax_year, inputs.adjustments
    custom_state = state.custom_brackets
    adjustment_diagnostics: list[str] = []
    state_rule_coverage = ""
    deduction_rule = None
    if inputs.setting("state_deduction_rules") and state_code:
        state_rule_coverage = state_rules_bridge.coverage(state_code) if custom_state is None else "legacy"
        if state_rule_coverage == "supported":
            rules = state_rules_bridge.evaluator()
            existing_itemized = inputs.itemized_deductions or {}
            categories = rules.ItemizedCategories(
                state_local_income_tax=max(0.0, float(existing_itemized.get("salt", 0.0))),
                real_estate_tax=max(0.0, float(existing_itemized.get("property_tax", 0.0))),
                mortgage_interest=max(0.0, float(existing_itemized.get("mortgage_interest", 0.0))),
                charitable_cash=max(0.0, float(existing_itemized.get("charitable", 0.0))
                                    + inputs.charitable_deduction),
                charitable_property=max(0.0, inputs.charitable_capital_gain_property),
                medical_expenses=max(0.0, inputs.medical_expenses),
                other=adjustments.state_itemized if adjustments is not None else 0.0,
                **({"local_income_tax": max(0.0, float(existing_itemized.get("local_income_tax", 0.0)))}
                   if "local_income_tax" in getattr(rules.ItemizedCategories, "__dataclass_fields__", {}) else {}),
            )
            # Qualifying children by the IRC 152(c)(3) age test (under 19 at
            # year end); students and other dependents are not identified.
            birth_years = inputs.setting("dependent_birth_years") or []
            dependents = sum(1 for born in birth_years if 0 <= tax_year - int(born) < 19)

            def optional_context(rules, state_agi_before_exclusions: float) -> dict:
                """Fields later added to the rules context, when the module has them."""
                names = getattr(rules.StateDeductionContext, "__dataclass_fields__", {})
                values = {
                    # Employee Social Security and Medicare (with Additional
                    # Medicare) withheld from wages; SE tax is separate.
                    "payroll_taxes_withheld": max(0.0, payroll.total - payroll.self_employment_tax),
                    "self_employment_tax": payroll.self_employment_tax,
                    "state_agi_before_retirement_exclusions": state_agi_before_exclusions,
                    # IRC 24(c)(1) age test (under 17 at year end) for rules
                    # keyed to the federal child tax credit.
                    "children_under_17": sum(1 for born in birth_years if 0 <= tax_year - int(born) < 17),
                }
                if hasattr(rules, "FederalTaxComponents"):
                    # The 72(t) additional tax and premium tax credit figures
                    # are settled outside this calculation and are not passed.
                    values["federal_components"] = rules.FederalTaxComponents(
                        net_investment_income_tax=niit_amount)
                return {key: value for key, value in values.items() if key in names}

            def deduction_rule(state_agi: float, state_agi_before_exclusions: float):
                return rules.evaluate_state_deductions(rules.StateDeductionContext(
                    state_code=state_code.upper(), tax_year=tax_year, inflation_factor=state.factor,
                    filing_status=inputs.filing_status, holder_age=inputs.holder_age,
                    spouse_age=inputs.spouse_age, dependent_count=dependents,
                    federal_agi=income.modified_agi, state_agi=state_agi, itemized=categories,
                    federal_itemized_elected=deduction.used == "itemized",
                    federal_itemized_total=deduction.total_itemized,
                    federal_standard_deduction=deduction.standard_deduction,
                    federal_income_tax_liability=federal.income_tax_liability,
                    **optional_context(rules, state_agi_before_exclusions),
                ))
        else:
            adjustment_diagnostics.append(
                f"State deduction rules for {state_code} are {state_rule_coverage.replace('_', ' ')}"
                + ("" if custom_state is None else " with custom state brackets")
                + "; the existing state standard deduction and exemption estimate is used.")
    if (adjustments is not None and adjustments.state_itemized > 0 and deduction_rule is None
            and state_code):
        adjustment_diagnostics.append(
            "State itemized adjustments apply only with supported state deduction rules; "
            "they are not deducted on this state return.")
    return state_rule_coverage, deduction_rule, adjustment_diagnostics


def _resident_state_tax(
    inputs: _TaxInputs,
    base: _IncomeBase,
    income: _FederalIncome,
    federal: _FederalTax,
    state: _StateInputs,
    deduction_rule: Callable[[float, float], object] | None,
) -> _StateTaxDetails:
    state_income_adjustment = income.state_income_adjustment
    return _state_tax_details(
        income.modified_agi, inputs.state_code, state.custom_brackets, inputs.filing_status,
        calendar_inflation=inputs.calendar_inflation,
        inflation_factor=state.factor,
        ca_exemption_eligible_owners=inputs.setting("ca_exemption_eligible_owners"),
        holder_age=inputs.holder_age, spouse_age=inputs.spouse_age, tax_year=inputs.tax_year,
        state_income_adjustment=(state_income_adjustment + state.interest_adjustment
                                 if state.interest_adjustment else state_income_adjustment)
                                - state.real_estate_gain_exclusion,
        taxable_social_security=income.taxable_ss,
        ca_dependent_count=inputs.dependents_for_year("ca_dependents_by_year"),
        oh_exemption_eligible_owners=inputs.setting("oh_exemption_eligible_owners"),
        oh_dependent_count=inputs.dependents_for_year("oh_dependents_by_year"),
        # Sales gains are treated as long-term (coastmath.engine.cost_basis); qualified
        # dividends are not IRC 1222 capital gains.
        net_long_term_capital_gains=max(0.0, base.net_sales),
        qualified_dividends=max(0.0, inputs.qualified_dividends),
        federal_taxable_income=federal.taxable_income + federal.taxable_capital_gains,
        retirement_exclusion=state.retirement_exclusion,
        social_security_subtraction=state.ss_subtraction,
        contribution_basis_recovery=state.basis_recovery,
        deduction_rule=deduction_rule,
        adjustments=inputs.adjustments,
    )


def _ca_part_year_unsupported(
    inputs: _TaxInputs,
    income: _FederalIncome,
    state: _StateInputs,
    state_rule_result: object | None,
    se_fica_deduction: float,
) -> tuple[str, ...]:
    """Inputs the bounded Form 540NR wage-only allocator cannot source."""
    context = inputs.ca_part_year_context
    state_code, tax_year = inputs.state_code, inputs.tax_year
    unsupported: list[str] = []
    # Full-year household/HSA controls do not establish their sourcing or
    # credit proration under the bounded 540NR wage-only allocator.
    if income.state_income_adjustment != 0:
        unsupported.append("California income adjustments require separate part-year sourcing")
    if state.interest_adjustment != 0:
        unsupported.append("municipal or U.S. obligation interest adjustments require separate part-year sourcing")
    if inputs.filing_status == "head_of_household":
        unsupported.append("head-of-household part-year schedule is not established")
    if inputs.dependents_for_year("ca_dependents_by_year"):
        unsupported.append("dependent-credit part-year allocation is not established")
    if state.custom_brackets is not None:
        unsupported.append("custom state brackets")
    if inputs.adjustments is not None and any(item.applies_to("state") for item in inputs.adjustments.items):
        unsupported.append("user state tax adjustments require separate part-year sourcing")
    if state_rule_result is not None:
        unsupported.append("statutory state deduction rules are not part-year allocated")
    if tax_year < 2025:
        unsupported.append("California table year before the supported 2025 anchor")
    if (state_code not in context.residency_state_codes
            or context.legacy_residual_in_ca != (state_code == "CA")):
        unsupported.append("legacy selected state conflicts with residency/allocation context")
    # Check separate components before netting: positive RMD/gains cannot
    # conceal unclassified deductions, losses or negative gross income.
    if abs(inputs.deductions - context.conforming_wage_deductions) > 1e-6:
        unsupported.append(
            "unallocated or nonconforming deductions "
            f"${inputs.deductions - context.conforming_wage_deductions:,.2f}"
        )
    if (inputs.capital_gains < 0 or inputs.qualified_dividends < 0
            or inputs.capital_loss_carryforward != 0):
        unsupported.append("capital losses or loss carryforwards require separate CA treatment")
    if inputs.rmd_income < 0 or inputs.qcd_offset < 0 or inputs.social_security_income < 0:
        unsupported.append("negative RMD, QCD or Social Security input")
    if (inputs.is_self_employed or se_fica_deduction != 0
            or (inputs.self_employment_income or 0) != 0 or inputs.qualified_business_income != 0
            or any(value != 0 for value in (inputs.self_employment_income_by_owner or {}).values())):
        unsupported.append("self-employment/business income or associated deductions")
    return tuple(unsupported)


def _ca_part_year_allocation(
    inputs: _TaxInputs,
    base: _IncomeBase,
    income: _FederalIncome,
    state: _StateInputs,
    state_rule_result: object | None,
    se_fica_deduction: float,
    federal_factor: float,
) -> CAPartYearTaxAllocation:
    """California tax on a part-year move, allocated by timed wages."""
    context = inputs.ca_part_year_context
    filing_status, tax_year = inputs.filing_status, inputs.tax_year
    unsupported = _ca_part_year_unsupported(inputs, income, state, state_rule_result, se_fica_deduction)

    # CA's table anchor applies even when the legacy destination is NV.
    ca_factor = 1.0 if 2025 <= tax_year <= 2026 else federal_factor
    ca_data = _TAX_DATA["state"]["CA"]
    filing_factor = 2 if filing_status == "married_filing_jointly" else 1
    ca_deduction = float(ca_data["standard_deduction"]) * filing_factor * ca_factor
    ca_brackets = [
        (upper * filing_factor * ca_factor, rate)
        for upper, rate in _convert_state_brackets(ca_data["brackets"])
    ]
    # Schedule CA removes federally taxable SS from CA-law all-source AGI.
    # Form 540NR's credit phaseout still uses the FEDERAL AGI (line 13).
    ca_all_source_agi = income.modified_agi - income.taxable_ss
    ca_total_taxable = max(0.0, ca_all_source_agi - ca_deduction)
    return allocate_ca_part_year_tax(
        context,
        all_source_agi=ca_all_source_agi,
        standard_deduction=ca_deduction,
        gross_tax_on_total_taxable=(apply_progressive_brackets(ca_total_taxable, ca_brackets)
                                    + ca_behavioral_health_tax(ca_total_taxable)),
        all_source_exemption_credit=ca_exemption_credit(
            income.modified_agi, filing_status,
            inputs.setting("ca_exemption_eligible_owners"),
            inputs.holder_age, inputs.spouse_age, tax_year, ca_factor,
        ),
        residual_components=(
            ("gross non-W2 income", inputs.gross_income - context.total_w2_wages),
            ("taxable RMD", base.taxable_rmd),
            ("Roth conversion", inputs.roth_conversions),
            ("capital gains", max(0.0, base.net_sales)),
            ("qualified dividends", max(0.0, inputs.qualified_dividends)),
        ),
        # The separate levy is not prorated by the wage allocation; keep
        # its statutory threshold (never MFJ-doubled or indexed) as a guard.
        surcharge_threshold=float(ca_data["behavioral_health_services_tax"]["threshold"]),
        unsupported_reasons=unsupported,
    )


def _with_capital_gains_excise(
    inputs: _TaxInputs,
    base: _IncomeBase,
    state: _StateInputs,
    state_tax: float,
    state_taxable_income: float,
) -> tuple[float, float]:
    """A separate state excise on long-term capital gains (Washington) and
    the state tax including it.

    Real property gains are excluded; retirement accounts realize no gains.
    """
    builtin = state.custom_brackets is None
    capital_gains_excise = (state_capital_gains_excise(
        inputs.state_code, max(0.0, base.net_sales) - inputs.real_estate_capital_gains, state.factor)
        if builtin else 0.0)
    if capital_gains_excise > 0 and state.data.get("capital_gains_excise_credit") and builtin:
        # ESSB 6346 (2026), Washington: a credit for capital gains excise
        # paid on gains the income tax also taxes, at most the income tax on
        # those gains, taken as the top layer of taxable income.
        gains_in_base = max(0.0, base.net_sales) - state.real_estate_gain_exclusion
        top_rate = max((float(b["rate"]) for b in state.data.get("brackets", [])), default=0.0)
        state_tax -= min(capital_gains_excise, max(0.0, state_tax),
                         top_rate * min(gains_in_base, state_taxable_income))
    return capital_gains_excise, state_tax + capital_gains_excise


def _resident_local_tax(
    inputs: _TaxInputs,
    base: _IncomeBase,
    income: _FederalIncome,
    state_taxable_income: float,
    state_tax: float,
    aged_count: int,
    federal_factor: float,
) -> LocalTaxResult:
    """Resident local income tax, after the final state tax it may surcharge.

    Catalog thresholds share the built-in state tables' calendar anchor.
    """
    if not inputs.local_tax:
        return LocalTaxResult()
    filing_status = inputs.filing_status
    return calculate_local_tax(
        inputs.local_tax,
        inputs.local_income or _fallback_local_income(
            inputs.w2_income, inputs.self_employment_income, inputs.w2_income_by_owner,
            inputs.self_employment_income_by_owner, inputs.earned_income, inputs.is_self_employed,
            inputs.net_investment_income, inputs.qualified_dividends, base.taxable_rmd + inputs.roth_conversions,
        ),
        LocalTaxContext(
            state_code=inputs.state_code, filing_status=filing_status, tax_year=inputs.tax_year,
            state_taxable_income=state_taxable_income, state_income_tax=state_tax,
            federal_agi=income.modified_agi, taxable_social_security=income.taxable_ss,
            persons=2 if filing_status == "married_filing_jointly" else 1,
            aged_persons=aged_count, index_factor=federal_factor,
        ),
    )

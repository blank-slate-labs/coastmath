"""Waterfall engine — surplus allocation and drawdown logic.

Allocates surplus cash to accounts by priority, and draws down from
accounts in rank order to cover deficits.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from coastmath.engine.account_types import (
    ANNUAL_ADDITIONS_415C_TYPES,
    EARLY_WITHDRAWAL_PENALTY_TYPES,
    ELECTIVE_DEFERRAL_402G_TYPES,
    ELECTIVE_DEFERRAL_TYPES,
    EMPLOYER_ONLY_PLAN_TYPES,
    EMPLOYER_PLAN_TYPES,
    ROTH_EMPLOYER_PLAN_TYPES,
    ROTH_PLAN_COUNTERPART,
    ROTH_TYPES,
    RULE_OF_55_TYPES,
    SECTION_457B_TYPES,
    TRADITIONAL_EMPLOYER_PLAN_TYPES,
    TRADITIONAL_RETIREMENT_TYPES,
    annual_additions_group,
)
from coastmath.engine.cash_reserve import reserve_floors
from coastmath.engine.coverage_rules import active_coverage, hsa_contribution_room
from coastmath.engine.education_savings import (
    EDUCATION_ACCOUNT_TYPE,
    earnings_fraction,
    nonqualified_additional_tax_rate,
)
from coastmath.engine.intl_accounts import after_contribution
from coastmath.engine.intl_accounts import contribution_room as country_room
from coastmath.engine.intl_cost_base import record_sale
from coastmath.engine.milestones import is_event_active
from coastmath.engine.plan_validation import (
    validate_roth_conversion_rules,
    validate_transfer_rules,
)
from coastmath.engine.roth import ledger
from coastmath.engine.state_retirement_exclusion import ACCOUNT_TYPE_SOURCES
from coastmath.engine.tax_target import bracket_target_top
from coastmath.engine.types import (
    _TAXABLE_TYPES,
    AccountInfo,
    DrawdownEntryData,
    EmployerMatchData,
    MatchTierData,
    NamedAmount,
    PayrollContribution,
    PriorityData,
    SimState,
)

# ---------------------------------------------------------------------------
# IRS 2026 annual contribution limits.
# Retirement plan / IRA limits: IRS Notice 2025-67.
# HSA limits: Rev. Proc. 2025-19.
# https://www.irs.gov/pub/irs-drop/n-25-67.pdf
# https://www.irs.gov/newsroom/401k-limit-increases-to-24500-for-2026-ira-limit-increases-to-7500
# https://www.irs.gov/pub/irs-drop/rp-25-19.pdf
# ---------------------------------------------------------------------------

_CONTRIBUTION_DATA = json.loads((Path(__file__).resolve().parents[1] / "data" / "contribution_limits_2026.json").read_text())

_IRS_LIMITS = _CONTRIBUTION_DATA["_IRS_LIMITS"]

_CATCHUP_50 = _CONTRIBUTION_DATA["_CATCHUP_50"]

# HSA catch-up starts at 55, not 50 (statutorily fixed — not indexed)
_HSA_CATCHUP_55 = _CONTRIBUTION_DATA["_HSA_CATCHUP_55"]

# 2026 Roth IRA modified-AGI phaseout ranges.  IRS Notice 2025-67 / IR-2025-111:
# https://www.irs.gov/newsroom/401k-limit-increases-to-24500-for-2026-ira-limit-increases-to-7500
_ROTH_IRA_PHASEOUTS = _CONTRIBUTION_DATA["_ROTH_IRA_PHASEOUTS"]

# 2026 traditional IRA deduction phase-out ranges for workplace-plan
# participants ("covered") and for someone whose spouse is one
# ("spouse_covered"). IR-2025-111; IRC 219(g).
_IRA_DEDUCTION_PHASEOUTS = _CONTRIBUTION_DATA["_TRADITIONAL_IRA_DEDUCTION_PHASEOUTS"]

# ---------------------------------------------------------------------------
# IRS 10% early withdrawal penalty (IRC §72(t)). A governmental 457(b) is
# not a 4974(c) plan, so it carries none (see coastmath.engine.account_types).
# https://www.irs.gov/taxtopics/tc558
# ---------------------------------------------------------------------------

_EARLY_WITHDRAWAL_TYPES = EARLY_WITHDRAWAL_PENALTY_TYPES
_EARLY_WITHDRAWAL_PENALTY = 0.10
_EARLY_WITHDRAWAL_END_AGE = 59.5
_TAXABLE_DRAWDOWN_TYPES = frozenset({"brokerage", "taxable_brokerage", "cryptocurrency"})


def is_subject_to_early_withdrawal_penalty(
    age: int,
    birth_month: int | None,
) -> bool:
    """Return True when most of the year falls before age 59.5 (IRC 72(t)).

    :func:`execute_drawdown` prorates the 10% penalty by month; this yes/no
    form is for statuses that hold for a whole year, such as Roth ordering.
    Someone born in January reaches 59.5 in July, so half of that year is
    early; someone born in June is early for eleven months. An unknown
    birth month counts as December.
    """
    return share_of_year_before_age(age, birth_month, _EARLY_WITHDRAWAL_END_AGE) > 0.5


def share_of_year_before_age(
    age: int,
    birth_month: int | None,
    threshold_age: float,
    year_fraction: float = 1.0,
) -> float:
    """Share of this year's modeled months before the owner reaches an age.

    ``age`` is the age attained during the calendar year. As with SEPP and
    milestones, an age is reached at the start of its month. Withdrawals
    are assumed evenly spread over the modeled (trailing) part of the year.
    An unknown birth month counts as July, mid-year: for 59.5 it keeps the
    earlier whole-year convention (all of the age-59 year early, none of
    the age-60 year).
    """
    start, before_end, active = _months_before_age(age, birth_month, threshold_age, year_fraction)
    return (before_end - start) / active if active > 0.0 else 0.0


def _months_before_age(
    age: int,
    birth_month: int | None,
    threshold_age: float,
    year_fraction: float,
) -> tuple[float, float, float]:
    """Return (modeled start, end of months before the age, modeled months)."""
    active = 12.0 * max(0.0, min(1.0, year_fraction))
    start = 12.0 - active
    reached = (birth_month or 7) - 1 + math.ceil(threshold_age * 12 - 1e-9) - age * 12
    return start, max(start, min(12.0, reached)), active


def state_early_distribution_rate_share(
    state_rates: tuple[tuple[float, float, float], ...],
    start: float,
    end: float,
    active: float,
) -> float:
    """Rate-weighted share of ``active`` modeled months in ``[start, end)``.

    ``state_rates`` holds residency months with a state additional tax on
    early distributions (CA 2.5%, FTB 3805P), so a part-year resident pays
    it only on the evenly spread withdrawals made while resident.
    """
    if active <= 0.0:
        return 0.0
    return sum(rate * max(0.0, min(end, span_end) - max(start, span_start))
               for span_start, span_end, rate in state_rates) / active


#: IRC 72(t)(2)(A)(v): separation from service in or after the calendar year
#: the employee reaches this age.
RULE_OF_55_AGE = 55


def penalty_free_by_separation(
    account_type: str,
    inherited_year: int | None,
    distribution_settings: dict | None,
    owner_age: int,
    year: int,
) -> bool:
    """Whether the Rule of 55 lifts the 10% tax on this account this year.

    ``owner_age`` is the age the owner attains in ``year`` (calendar-year
    basis), so the age at the end of the separation year is
    ``owner_age - (year - separation_year)``. The separation year is modeled
    as separation on January 1, so every distribution that year and after
    is covered. Only the owner's own workplace plan qualifies: never an
    IRA, an inherited account or a 457(b).
    """
    separation_year = (distribution_settings or {}).get("separation_year")
    if separation_year is None or separation_year > year:
        return False
    if account_type not in RULE_OF_55_TYPES or inherited_year is not None:
        return False
    return owner_age - (year - separation_year) >= RULE_OF_55_AGE


def early_withdrawal_penalty_rate(
    age: int,
    birth_month: int | None,
    year_fraction: float = 1.0,
    state_rates: tuple[tuple[float, float, float], ...] = (),
) -> float:
    """Federal 10% (IRC 72(t)) plus state additional tax, prorated by month.

    Withdrawals are evenly spread over the modeled months; only months both
    before 59.5 and within a taxing state's residency carry the state rate.
    """
    start, early_end, active = _months_before_age(
        age, birth_month, _EARLY_WITHDRAWAL_END_AGE, year_fraction)
    if active <= 0.0:
        return 0.0
    return (_EARLY_WITHDRAWAL_PENALTY * (early_end - start) / active
            + state_early_distribution_rate_share(state_rates, start, early_end, active))


# IRC 223(f)(2), (f)(4): HSA distributions not used for qualified medical
# expenses are income, plus a 20% additional tax before age 65.
_HSA_ADDITIONAL_TAX = 0.20
_HSA_ADDITIONAL_TAX_END_AGE = 65


# SECURE 2.0: ages 60-63 get enhanced catch-up (replaces normal catch-up)
_SUPER_CATCHUP_60_63 = _CONTRIBUTION_DATA["_SUPER_CATCHUP_60_63"]


def _irs_contribution_room(
    account_type: str,
    age: int,
    ytd: float,
    inflation_factor: float = 1.0,
    filing_status: str | None = None,
    modified_agi: float | None = None,
) -> float:
    """Return remaining IRS contribution room for an account type.

    Returns ``float('inf')`` for account types with no IRS limit
    (checking, savings, taxable brokerage, etc.).

    When *inflation_factor* > 1.0 the 2026-base limits are scaled up to
    approximate IRS cost-of-living adjustments over longer simulations.
    """
    base = _IRS_LIMITS.get(account_type)
    if base is None:
        return float("inf")

    limit = base

    # SECURE 2.0 super catch-up for ages 60-63 (401(k), 403(b), governmental 457(b))
    if 60 <= age <= 63 and account_type in _SUPER_CATCHUP_60_63:
        limit += _SUPER_CATCHUP_60_63[account_type]
    elif age >= 50 and account_type in _CATCHUP_50:
        limit += _CATCHUP_50[account_type]

    # Apply inflation indexing (mirrors QCD cap logic in simulator.py)
    limit *= inflation_factor
    # HSA catch-up is statutorily fixed, unlike the indexed base limit.
    if account_type == "hsa" and age >= 55:
        limit += _HSA_CATCHUP_55

    if (
        account_type == "roth_ira"
        and filing_status is not None
        and modified_agi is not None
        and filing_status in _ROTH_IRA_PHASEOUTS
    ):
        # IRC 408A(c)(3): only the starting amount is indexed, and not for a
        # separate return; the $15,000/$10,000 range widths stay fixed.
        limit = _phased_out_limit(limit, modified_agi, _ROTH_IRA_PHASEOUTS[filing_status],
                                  filing_status, inflation_factor)

    return max(0.0, limit - ytd)


def _phased_out_limit(
    limit: float, modified_agi: float, bounds: list[float], filing_status: str, inflation_factor: float,
) -> float:
    """An IRA dollar limit reduced over a modified-AGI phase-out range.

    The starting amount is indexed except for a separate return; the range
    width stays fixed. Publication 590-A Worksheets 1-2 and 2-2 round the
    remaining limit up to the next $10, with a $200 minimum inside the range.
    """
    lower, upper = bounds
    width = upper - lower
    if filing_status != "married_filing_separately":
        lower *= inflation_factor
    upper = lower + width
    if modified_agi >= upper:
        return 0.0
    if modified_agi <= lower:
        return limit
    reduction = limit * (modified_agi - lower) / width
    reduced = max(0.0, -(-(limit - reduction) // 10) * 10)
    return 200.0 if 0 < reduced < 200 else reduced


def traditional_ira_deduction_limit(
    owner_age: int,
    filing_status: str,
    modified_agi: float,
    *,
    covered: bool,
    spouse_covered: bool,
    inflation_factor: float = 1.0,
    lived_apart: bool = False,
) -> float:
    """The most of one owner's traditional IRA contributions that is deductible.

    IRC 219(g) and Publication 590-A Worksheet 1-2: an active participant in
    a workplace plan (``covered``) loses the deduction over the filing
    status's range. Someone not covered whose spouse is gets the wider
    married range on a joint return; spouses filing separately share the
    $0-$10,000 range unless they lived apart all year, which makes them
    unmarried for this purpose (219(g)(4)). Otherwise the whole IRA limit,
    catch-up included, is deductible. ``modified_agi`` is AGI figured without
    the IRA deduction (Worksheet 1-1).
    """
    limit = _irs_contribution_room("traditional_ira", owner_age, 0, inflation_factor)
    married = filing_status in ("married_filing_jointly", "married_filing_separately") and not (
        filing_status == "married_filing_separately" and lived_apart)
    status = "single" if filing_status == "married_filing_separately" and lived_apart else filing_status
    if covered:
        bounds = _IRA_DEDUCTION_PHASEOUTS["covered"].get(status)
    elif spouse_covered and married:
        bounds = _IRA_DEDUCTION_PHASEOUTS["spouse_covered"].get(status)
    else:
        return limit
    if bounds is None:
        return limit
    return _phased_out_limit(limit, modified_agi, bounds, status, inflation_factor)


def contribution_limit_group(account_type: str) -> frozenset[str]:
    """Account types sharing one owner's annual contribution limit.

    401(k) and 403(b) deferrals share the 402(g) limit, traditional and Roth
    IRAs share the IRA limit and 457(b) has its own; any other type is its
    own group.
    """
    for group in (frozenset({"traditional_ira", "roth_ira"}), ELECTIVE_DEFERRAL_402G_TYPES, SECTION_457B_TYPES):
        if account_type in group:
            return frozenset(group)
    return frozenset({account_type})


def contribution_room(
    account_id: str, state: SimState, age: int,
    filing_status: str | None = None, modified_agi: float | None = None,
    reasons: list[str] | None = None, backdoor: bool = False,
) -> float:
    """Owner-level statutory limits, shared across accounts and tax treatments.

    ``backdoor`` marks a Roth IRA funded through a nondeductible traditional IRA
    contribution converted at once: the income phaseout no longer applies, but
    the compensation test and the shared IRA limit still do.
    """
    reasons = reasons if reasons is not None else []
    account = state.accounts[account_id]
    if account_id in state.closed_employer_account_ids:
        reasons.append("ownership")
        return 0.0
    if account_id in state.intl_kinds:
        # A country account kind's own limits replace the US ones.
        room = country_room(account_id, state)
        if room <= 0:
            reasons.append("contribution_limit")
        return room
    if backdoor and account.account_type == "roth_ira":
        modified_agi = None
    if (account.account_type in _IRS_LIMITS or account.account_type in EMPLOYER_PLAN_TYPES) and (account.inherited_year is not None or account.owner == "joint"):
        reasons.append("ownership")
        return 0.0
    group = contribution_limit_group(account.account_type)
    ytd = sum(amount for aid, amount in state.ytd_contributions.items()
              if aid in state.accounts and state.accounts[aid].owner == account.owner
              and state.accounts[aid].account_type in group)
    owner_age = state.owner_ages.get(account.owner, age)
    if account.owner == "spouse" and "spouse" not in state.owner_ages:
        # Unknown age preserves the base allowance but cannot establish a
        # spouse's catch-up (IRC 414(v), 219(b)(5)(B), 223(b)(3)) from the
        # primary person's birth year.
        owner_age = 0
    room = _irs_contribution_room(account.account_type, owner_age, ytd,
                                  state.coverage_inflation_factor)
    if account.account_type == "hsa":
        explicit_room = hsa_contribution_room(account_id, state, owner_age)
        if explicit_room is not None:
            room = explicit_room
        elif account.owner in state.hsa_medicare_start:
            # IRC 223(b)(2), (b)(7): without entered coverage, the legacy
            # limit is prorated to the months before modeled Medicare.
            eligible_share = state.hsa_medicare_start[account.owner]
            room = max(0.0, _irs_contribution_room("hsa", owner_age, 0, state.coverage_inflation_factor)
                       * eligible_share - ytd)
    if account.account_type in EMPLOYER_ONLY_PLAN_TYPES:
        # A 401(a) takes no employee elective deferrals; only payroll
        # employer contributions fund it.
        room = 0.0
    if room <= 0:
        reasons.append("contribution_limit")
    if account.account_type == "roth_ira":
        roth_ytd = sum(amount for aid, amount in state.ytd_contributions.items()
                       if aid in state.accounts and state.accounts[aid].owner == account.owner
                       and state.accounts[aid].account_type == "roth_ira")
        # Worksheet 2-2 takes the smaller of the phaseout limit and the
        # combined IRA room; traditional contributions do not reduce both.
        roth_room = _irs_contribution_room("roth_ira", owner_age, roth_ytd,
                   state.coverage_inflation_factor, filing_status, modified_agi)
        if roth_room <= 0:
            reasons.append("income_eligibility" if _irs_contribution_room("roth_ira", owner_age, 0,
                state.coverage_inflation_factor, filing_status, modified_agi) <= 0 else "contribution_limit")
        room = min(room, roth_room)
    if account.account_type in {"traditional_ira", "roth_ira"} and state.compensation_by_owner is not None:
        compensation = state.compensation_by_owner.get(account.owner, 0.0)
        used = ytd
        if filing_status == "married_filing_jointly":
            compensation = sum(state.compensation_by_owner.values())
            used = sum(amount for aid, amount in state.ytd_contributions.items()
                       if aid in state.accounts and state.accounts[aid].account_type in group)
        if compensation - used <= 0:
            reasons.append("compensation")
        room = min(room, max(0.0, compensation - used))
    # 457(b)(2)(B) also caps 457(b) deferrals, employer ones included, at
    # includible compensation.
    if account.account_type in ELECTIVE_DEFERRAL_TYPES and state.compensation_by_owner is not None:
        if state.compensation_by_owner.get(account.owner, 0.0) - ytd <= 0:
            reasons.append("compensation")
        room = min(room, max(0.0, state.compensation_by_owner.get(account.owner, 0.0) - ytd))
    if account.account_type in ELECTIVE_DEFERRAL_TYPES:
        regular_limit = _IRS_LIMITS[account.account_type] * state.coverage_inflation_factor
        if account.account_type in ANNUAL_ADDITIONS_415C_TYPES:
            # Section 415(c) counts this plan group's regular deferrals and
            # employer money; a 457(b) is not a 415(c) plan.
            deferrals, employer_used = _annual_additions(account.owner, annual_additions_group(account.account_type),
                                                         state, account_id)
            full_limit = _irs_contribution_room(account.account_type, owner_age, 0, state.coverage_inflation_factor)
            total = _CONTRIBUTION_DATA["defined_contribution_total"] * state.coverage_inflation_factor
            if state.compensation_by_owner is not None:
                total = min(total, state.compensation_by_owner.get(account.owner, 0.0))
            room = min(room, max(0.0, total + full_limit - regular_limit - employer_used - deferrals))
        # SECURE 2.0 s.603 (IRC 414(v)(7)): a high earner's catch-up must be
        # Roth in 401(k), 403(b) and governmental 457(b) plans alike.
        if account.account_type in TRADITIONAL_EMPLOYER_PLAN_TYPES and account.owner in state.roth_catchup_owners:
            room = min(room, max(0.0, regular_limit - ytd))
    if room <= 0 and not reasons:
        reasons.append("contribution_limit")
    return room


def custom_limit_room(priority: PriorityData, account_id: str, state: SimState) -> float | None:
    """Room left under a rule's custom annual limit, or None for IRS limits.

    A plan may set a lower limit than the IRS one. The custom amount is in
    today's dollars, indexed like the IRS limits, and counts the year's
    contributions to the rule's account on the same basis as that account's
    IRS limit (employer money too for an HSA or 457(b)). Callers take the
    smaller of this and :func:`contribution_room`, so it can only lower the
    ceiling.
    """
    if priority.limit_mode != "custom" or priority.custom_annual_limit is None:
        return None
    limit = max(0.0, priority.custom_annual_limit) * state.coverage_inflation_factor
    return max(0.0, limit - state.ytd_contributions.get(account_id, 0.0))


def _tiered_match_share(deferral_share: float, tiers: list[MatchTierData]) -> float:
    """Matched share of pay for deferrals of ``deferral_share`` of pay."""
    matched = 0.0
    floor = 0.0
    for tier in tiers:
        band = max(0.0, tier.up_to_percent_of_pay)
        matched += max(0.0, tier.match_percent) * max(0.0, min(deferral_share - floor, band))
        floor += band
    return matched


def employer_match_amount(
    match: EmployerMatchData,
    compensation: float,
    deferral: float,
    elected_rate: float,
    pay_months: int = 12,
    cap: float | None = None,
) -> float:
    """Employer money for one year under a matching formula.

    ``compensation`` is the year's plan compensation, ``deferral`` the
    employee's actual deferral after every limit and ``elected_rate`` the
    deferral rate elected (decimals). With ``true_up`` the tiers apply to the
    year's deferral as a share of compensation, as a plan that trues up the
    match at year end does.

    Without it the match is figured each pay period. The engine is annual, so
    pay periods are approximated by ``pay_months`` equal months: deferrals run
    at the elected rate from the first month until the year's actual deferral
    is used up (for example when the 402(g) limit stops them in September),
    and each month is matched on that month's deferral alone. Months after
    deferrals stop get no match, which is what a true-up would restore.

    ``nonelective_percent`` of compensation is added regardless of deferrals,
    then ``cap`` limits the total.
    """
    if compensation <= 0:
        return 0.0
    deferral = max(0.0, deferral)
    if match.true_up or elected_rate <= 0 or deferral <= 0:
        matched = compensation * _tiered_match_share(deferral / compensation, match.tiers)
    else:
        months = max(1, pay_months)
        monthly_pay = compensation / months
        monthly_deferral = elected_rate * monthly_pay
        full_months = min(months, int(deferral / monthly_deferral + 1e-9))
        matched = full_months * monthly_pay * _tiered_match_share(elected_rate, match.tiers)
        rest = deferral - full_months * monthly_deferral
        if full_months < months and rest > 1e-9:
            matched += monthly_pay * _tiered_match_share(rest / monthly_pay, match.tiers)
    total = matched + compensation * max(0.0, match.nonelective_percent)
    if cap is not None:
        total = min(total, max(0.0, cap))
    return max(0.0, total)


def roth_employer_account(account_id: str, state: SimState) -> str | None:
    """The owner's designated Roth account in the same plan type, if any.

    A Roth account is its own answer. Otherwise the first open, non-inherited
    Roth 401(k)/403(b)/457(b) of the same owner and plan type in account
    order; None when there is none (a 401(a) has no Roth counterpart).
    """
    account = state.accounts[account_id]
    if account.account_type in ROTH_EMPLOYER_PLAN_TYPES:
        return account_id
    roth_type = ROTH_PLAN_COUNTERPART.get(account.account_type)
    for aid, acct in state.accounts.items():
        if (acct.account_type == roth_type and acct.owner == account.owner
                and acct.inherited_year is None and aid not in state.closed_employer_account_ids):
            return aid
    return None


def _annual_additions(owner: str, group: frozenset[str], state: SimState,
                      account_id: str | None = None) -> tuple[float, float]:
    """An owner's employee deferrals and employer plus after-tax money this
    year across the accounts of one section 415(c) aggregation group.

    Section 415(c) applies per employer (Treas. Reg. 1.415(f)-1): with
    ``account_id``, only plans of that account's employer count. A plan funded
    from self-employment profit (``state.self_employment_plan_ids``) belongs
    to the owner's business, unrelated to their W-2 employers, whose plans
    stay pooled because the engine cannot tell those employers apart.
    """
    side = None if account_id is None else account_id in state.self_employment_plan_ids
    ids = [aid for aid, acct in state.accounts.items() if acct.owner == owner and acct.account_type in group
           and (side is None or (aid in state.self_employment_plan_ids) == side)]
    return (sum(state.ytd_contributions.get(aid, 0.0) for aid in ids),
            sum(state.ytd_employer_contributions.get(aid, 0.0)
                + state.ytd_after_tax_contributions.get(aid, 0.0) for aid in ids))


def after_tax_401k_room(owner: str, state: SimState, account_id: str | None = None) -> tuple[float, bool]:
    """Section 415(c) room left for an owner's after-tax 401(k) contributions.

    Annual additions are regular employee deferrals, employer contributions
    and after-tax contributions across the owner's 401(k)s and 401(a)s;
    catch-up deferrals are excluded (IRC 414(v)(3)(A)). The total is indexed
    like the other limits and capped at compensation (IRC 415(c)(1)(B)).
    Returns the room and whether compensation, not the dollar limit, set the
    total.
    """
    deferrals, others = _annual_additions(owner, annual_additions_group("roth_401k"), state, account_id)
    regular = min(deferrals, _IRS_LIMITS["traditional_401k"] * state.coverage_inflation_factor)
    total = _CONTRIBUTION_DATA["defined_contribution_total"] * state.coverage_inflation_factor
    compensation_bound = False
    if state.compensation_by_owner is not None:
        compensation = state.compensation_by_owner.get(owner, 0.0)
        compensation_bound = compensation < total
        total = min(total, compensation)
    return max(0.0, total - regular - others), compensation_bound


def _allocate_after_tax_401k(
    priority: PriorityData,
    account: AccountInfo,
    state: SimState,
    remaining_by_income: dict[str, float],
    available_pay: float,
    contribution_fraction: float,
) -> PayrollContribution | None:
    """Fund a mega backdoor Roth: after-tax 401(k) money converted at once.

    Paid from the owner's wages after tax, so it neither reduces taxable or
    FICA wages nor uses the 402(g) deferral limit. The in-plan Roth rollover
    is immediate, so there are no earnings to tax; the Roth ledger records a
    rollover with no taxable portion (Notice 2010-84). Rules run in list
    order, so the room reflects deferrals and employer money already made.
    """
    source = priority.source_income_id or ""
    pay = min(remaining_by_income.get(source, 0.0), available_pay)
    if pay <= 0:
        return None
    reasons: list[str] = []
    room, compensation_bound = after_tax_401k_room(account.owner, state, priority.target_account_id)
    if room <= 0:
        reasons.append("compensation" if compensation_bound else "contribution_limit")
    limits = {"contribution eligibility / annual limit": room}
    if priority.max_annual_amount is not None:
        # Like other explicit dollar amounts, the cap prorates in a partial year.
        limits["annual maximum"] = max(0.0, priority.max_annual_amount) * max(0.0, min(1.0, contribution_fraction))
        if priority.max_annual_amount == 0:
            reasons.append("annual_maximum")
    active = is_event_active(priority.start_milestone_id, priority.end_milestone_id, state.triggered_milestones)
    amount = max(0.0, min(pay, *limits.values())) if active else 0.0
    if amount > 0:
        state.deposit_to(priority.target_account_id, amount, conversion_taxable=0.0)
        state.ytd_after_tax_contributions[priority.target_account_id] = (
            state.ytd_after_tax_contributions.get(priority.target_account_id, 0.0) + amount)
    return PayrollContribution(
        target_account_id=priority.target_account_id,
        employee_amount=amount,
        source_income_id=priority.source_income_id,
        priority_rank=priority.priority_rank,
        requested_amount=pay,
        limited_by=[label for label, limit in limits.items() if limit < pay - 0.005],
        funding_reasons=list(dict.fromkeys(reasons)) if active else ["inactive_rule"],
    )


def allocate_payroll_contributions(
    priorities: list[PriorityData],
    income_by_id: dict[str, float],
    state: SimState,
    age: int,
    contribution_fraction: float = 1.0,
    income_owners: dict[str, str] | None = None,
    w2_income_ids: set[str] | None = None,
    self_employment_income_ids: set[str] | None = None,
    self_employed_employer_room: dict[str, float] | None = None,
    prior_compensation_by_income: dict[str, float] | None = None,
    pay_months_by_income: dict[str, int] | None = None,
) -> list[PayrollContribution]:
    """Fund income-linked and other pre-tax contribution priorities.

    ``income_percent`` priorities calculate employee deferrals and employer
    matches from one named income stream.  Employee amounts consume the
    account's IRS employee limit and reduce spendable/taxable pay; employer
    match amounts are deposited directly and do not consume that employee
    limit.  ``pre_tax_contribution`` priorities (for example an HSA funded
    through payroll) contribute up to their user/IRS cap. ``after_tax_401k``
    priorities fund a Roth 401(k) with after-tax money up to the remaining
    section 415(c) room (see :func:`_allocate_after_tax_401k`); they are
    returned even when unfunded so their funding reasons reach the client.

    A self-employed person has no separate employer: an "employer" amount
    from ``self_employment_income_ids`` is paid out of that business profit,
    so it consumes the source income. ``self_employed_employer_room`` holds
    each owner's remaining 401(k) profit-sharing room and is reduced here;
    omit it to skip that limit.

    A rule's ``employer_match`` formula replaces ``employer_match_rate``
    with a match on the employee's actual deferral (see
    :func:`employer_match_amount`; ``pay_months_by_income`` holds each
    stream's paid months this year for per-period matching). With ``roth``
    the employer money is returned as a separate contribution to the owner's
    Roth account of the same plan type (:func:`roth_employer_account`), or
    stays in the rule's account when there is none. A ``custom`` limit mode
    lowers the account's ceiling (:func:`custom_limit_room`).

    A 401(k) percentage applies to at most the section 401(a)(17)
    compensation limit for the year. ``prior_compensation_by_income`` holds
    each stream's pay already earned this year before the projection starts;
    it uses up that limit first.

    The caller is responsible for subtracting the returned employee amounts,
    and self-employed employer amounts, from cash and taxable income.
    Deposits are applied here so the account state and year-to-date
    contribution room stay authoritative.
    Periodic fixed-dollar pre-tax contributions are prorated by
    ``contribution_fraction`` in a partial first simulation year.
    """
    results: list[PayrollContribution] = []
    available_pay = sum(max(0.0, amount) for amount in income_by_id.values())
    remaining_by_income = {key: max(0.0, value) for key, value in income_by_id.items()}

    for priority in sorted(priorities, key=lambda item: item.priority_rank):
        if priority.priority_type not in ("income_percent", "pre_tax_contribution", "after_tax_401k"):
            continue
        account_id = priority.target_account_id
        if account_id is None:
            continue
        account = state.accounts.get(account_id)
        if account is None or account_id in state.closed_employer_account_ids:
            continue
        cafeteria_ids = None
        if (account.account_type == "hsa" and active_coverage(state.year, state.hsa_coverage)
                .get(account.owner, {}).get("payroll_funding") == "cafeteria"):
            # A spouse's wages, SE earnings or opening YTD wages cannot fund
            # a current employee salary reduction for this account owner.
            cafeteria_ids = {key for key in (w2_income_ids or set())
                             if (income_owners or {}).get(key) == account.owner}
            if priority.source_income_id is not None:
                cafeteria_ids &= {priority.source_income_id}
            if not cafeteria_ids:
                continue
        if income_owners is not None and priority.source_income_id is not None:
            if income_owners.get(priority.source_income_id) != account.owner:
                continue
        if priority.priority_type == "after_tax_401k":
            # W-2 wages fund an in-plan conversion to the owner's Roth 401(k).
            if (account.account_type != "roth_401k" or account.inherited_year is not None
                    or priority.source_income_id is None
                    or (w2_income_ids is not None and priority.source_income_id not in w2_income_ids)):
                continue
            contribution = _allocate_after_tax_401k(
                priority, account, state, remaining_by_income, available_pay, contribution_fraction)
            if contribution is not None:
                available_pay -= contribution.employee_amount
                remaining_by_income[priority.source_income_id] -= contribution.employee_amount
                results.append(contribution)
            continue
        # Saved milestone bounds use the same annual activation as surplus rules.
        if not is_event_active(priority.start_milestone_id, priority.end_milestone_id, state.triggered_milestones):
            continue

        ytd = state.ytd_contributions.get(account_id, 0.0)
        room = contribution_room(account_id, state, age)
        plan_room = custom_limit_room(priority, account_id, state)
        if plan_room is not None:
            room = min(room, plan_room)

        if priority.priority_type == "income_percent":
            source_income = max(0.0, income_by_id.get(priority.source_income_id or "", 0.0))
            if account.account_type in ANNUAL_ADDITIONS_415C_TYPES:
                # IRC 401(a)(17): the plan may not take into account pay above
                # the annual compensation limit, for deferrals or employer money.
                compensation_limit = _CONTRIBUTION_DATA["annual_compensation_limit"] * state.coverage_inflation_factor
                prior = (prior_compensation_by_income or {}).get(priority.source_income_id or "", 0.0)
                source_income = min(source_income, max(0.0, compensation_limit - max(0.0, prior)))
            requested_employee = source_income * max(0.0, priority.employee_rate)
        else:
            # Remaining legal room is a calendar-year ceiling, not an
            # annual dollar request. Only explicit dollar amounts prorate.
            requested_employee = room

        if priority.max_annual_amount is not None:
            requested_employee = min(requested_employee, priority.max_annual_amount)
        if priority.priority_type == "pre_tax_contribution" and priority.max_annual_amount is not None:
            requested_employee = priority.max_annual_amount * max(0.0, min(1.0, contribution_fraction))
        employee_amount = min(requested_employee, room, available_pay)
        if cafeteria_ids is not None:
            employee_amount = min(employee_amount, sum(remaining_by_income.get(key, 0.0) for key in cafeteria_ids))
        if priority.source_income_id is not None:
            employee_amount = min(employee_amount, remaining_by_income.get(priority.source_income_id, 0.0))
        employee_amount = max(0.0, employee_amount)

        employer_amount = 0.0
        self_employed = priority.source_income_id in (self_employment_income_ids or set())
        employer_account_id = account_id
        if priority.priority_type == "income_percent":
            match = priority.employer_match
            if match is None:
                employer_amount = source_income * max(0.0, priority.employer_match_rate)
                # A flat rate of pay ignores the deferral. With the option,
                # cut it by the share of the elected deferral that pay could
                # not fund; contribution limits are not a cut. A tiered
                # formula already matches the actual deferral.
                elected = min(requested_employee, room)
                if priority.reduce_employer_contribution and elected > 0.005:
                    employer_amount *= max(0.0, min(1.0, employee_amount / elected))
            else:
                cap = None
                if match.cap_amount is not None:
                    # Like other annual dollar amounts, the cap prorates in a
                    # partial first simulation year.
                    cap = (max(0.0, match.cap_amount) * state.inflation_factor
                           * max(0.0, min(1.0, contribution_fraction)))
                employer_amount = employer_match_amount(
                    match, source_income, employee_amount, max(0.0, priority.employee_rate),
                    (pay_months_by_income or {}).get(priority.source_income_id or "", 12), cap)
                if match.roth:
                    employer_account_id = roth_employer_account(account_id, state) or account_id
            if self_employed:
                employer_amount = min(employer_amount, remaining_by_income.get(priority.source_income_id, 0.0) - employee_amount)
                if (self_employed_employer_room is not None
                        and account.account_type in EMPLOYER_PLAN_TYPES):
                    employer_amount = min(employer_amount, self_employed_employer_room.get(account.owner, 0.0))
            if account.account_type in ANNUAL_ADDITIONS_415C_TYPES:
                employee_ytd, employer_ytd = _annual_additions(
                    account.owner, annual_additions_group(account.account_type), state, account_id)
                # Catch-up deferrals are excluded from the section 415(c) total;
                # 401(k) and 403(b) share one regular 402(g) amount.
                regular_employee = min(employee_ytd + employee_amount, _IRS_LIMITS["traditional_401k"] * state.coverage_inflation_factor)
                total_limit = _CONTRIBUTION_DATA["defined_contribution_total"] * state.coverage_inflation_factor
                if state.compensation_by_owner is not None:
                    total_limit = min(total_limit, state.compensation_by_owner.get(account.owner, 0.0))
                employer_amount = min(employer_amount, max(0.0, total_limit - regular_employee - employer_ytd))
            elif account.account_type in _IRS_LIMITS:
                # HSA employer funding uses the same limit as employee funding,
                # as do 457(b) employer deferrals (IRC 457(b)(2)).
                employer_amount = min(employer_amount, max(0.0, room - employee_amount))
                if account.account_type in SECTION_457B_TYPES:
                    # The 414(v) catch-up is for elective deferrals only, so
                    # employer money must fit within the base 457(e)(15) limit.
                    base_used = sum(state.ytd_contributions.get(aid, 0.0) for aid, acct in state.accounts.items()
                                    if acct.owner == account.owner and acct.account_type in SECTION_457B_TYPES)
                    employer_amount = min(employer_amount, max(0.0, _IRS_LIMITS[account.account_type]
                                                               * state.coverage_inflation_factor - base_used - employee_amount))
            employer_amount = max(0.0, employer_amount)
            if account_id in state.intl_kinds:
                if not state.intl_kinds[account_id].employer_match_allowed:
                    employer_amount = 0.0  # the country account kind takes no employer money
                else:
                    # Employer money uses the kind's room left after the
                    # employee's; the rest is not deposited, as for an HSA.
                    employer_room = country_room(account_id, state, employer=True)
                    if plan_room is not None:
                        employer_room = min(employer_room, plan_room)
                    employer_amount = min(employer_amount, max(0.0, employer_room - employee_amount))

        if employee_amount > 0:
            state.deposit_to(account_id, employee_amount)
            state.ytd_contributions[account_id] = ytd + employee_amount
            available_pay -= employee_amount
            if priority.source_income_id is not None:
                remaining_by_income[priority.source_income_id] -= employee_amount
            elif cafeteria_ids is not None:
                left = employee_amount
                for key in sorted(cafeteria_ids):
                    used = min(left, remaining_by_income.get(key, 0.0))
                    remaining_by_income[key] -= used
                    left -= used
        if employer_amount > 0:
            # A Roth match lands in a same-plan Roth account, which shares
            # every limit group used above with the rule's account.
            state.deposit_to(employer_account_id, employer_amount)
            state.ytd_employer_contributions[employer_account_id] = (
                state.ytd_employer_contributions.get(employer_account_id, 0.0) + employer_amount)
            if account.account_type not in ANNUAL_ADDITIONS_415C_TYPES:
                state.ytd_contributions[employer_account_id] = (
                    state.ytd_contributions.get(employer_account_id, 0.0) + employer_amount)
            if self_employed:
                available_pay -= employer_amount
                remaining_by_income[priority.source_income_id] -= employer_amount
                if (self_employed_employer_room is not None
                        and account.account_type in EMPLOYER_PLAN_TYPES):
                    self_employed_employer_room[account.owner] = max(
                        0.0, self_employed_employer_room.get(account.owner, 0.0) - employer_amount)
        if account_id in state.intl_kinds and employee_amount + employer_amount > 0:
            after_contribution(state, account_id, employee_amount + employer_amount)

        same_account_employer = employer_amount if employer_account_id == account_id else 0.0
        if employee_amount > 0 or same_account_employer > 0:
            results.append(PayrollContribution(
                target_account_id=account_id,
                employee_amount=employee_amount,
                employer_amount=same_account_employer,
                source_income_id=priority.source_income_id,
            ))
        if employer_amount > 0 and employer_account_id != account_id:
            results.append(PayrollContribution(
                target_account_id=employer_account_id,
                employer_amount=employer_amount,
                source_income_id=priority.source_income_id,
            ))

    return results


@dataclass
class ConversionTaxContext:
    """Pre-conversion tax picture used by bracket-fill conversions.

    ``ordinary_taxable_income`` is taxable income after deductions but before
    any conversion; ``brackets`` are (upper bound, rate) pairs already scaled
    to the projection year; ``modified_agi`` is AGI including gains.
    """
    ordinary_taxable_income: float
    modified_agi: float
    brackets: list[tuple[float, float]]
    inflation_factor: float = 1.0
    flat_tax: bool = False
    # Long-term capital gains brackets (upper bound, rate), scaled to the year.
    # Gains stack on top of ordinary taxable income.
    ltcg_brackets: list[tuple[float, float]] | None = None
    # Gains and qualified dividends already recognised this year.
    capital_gains_so_far: float = 0.0
    # Deductions still available to ordinary income must not disappear when
    # the tax engine clips pre-conversion taxable income at zero.
    unused_deduction: float = 0.0


def bracket_fill_headroom(context: ConversionTaxContext, ceiling_rate: float) -> float:
    """Ordinary-income room below the top of the bracket taxed at ``ceiling_rate``.

    A rate the year's schedule lacks fills only the brackets taxed at or below
    it, the same rule as the plan's bracket target (``bracket_target_top``).
    """
    if context.flat_tax:
        return 0.0
    top = bracket_target_top(context.brackets, ceiling_rate)
    if top is None:
        return math.inf
    return max(0.0, top - context.ordinary_taxable_income + context.unused_deduction)


_HARVEST_TYPES = frozenset({"taxable_brokerage"})


def gain_harvest_headroom(context: ConversionTaxContext, ceiling_rate: float, ordinary_added: float = 0.0) -> float:
    """Capital-gain room below the top of the LTCG bracket taxed at ``ceiling_rate``.

    Long-term gains stack on ordinary taxable income (IRC 1(h)), so the room
    is the bracket top minus ordinary taxable income (including any conversion
    added this year) minus gains already recognised.
    """
    if context.flat_tax or not context.ltcg_brackets:
        return 0.0
    top = None
    for upper, rate in context.ltcg_brackets:
        if abs(rate - ceiling_rate) < 1e-9:
            top = upper
    if top is None:
        return 0.0
    return max(0.0, top - context.ordinary_taxable_income - ordinary_added - context.capital_gains_so_far)


def execute_gain_harvests(
    priorities: list[PriorityData],
    state: SimState,
    *,
    tax_context: ConversionTaxContext | None,
    triggered_milestones: set[str] | None = None,
    amount_limit: Callable[[PriorityData, float], float] | None = None,
) -> dict[str, float]:
    """Realise gains in taxable accounts up to a capital-gains bracket ceiling.

    Tax-gain harvesting sells and immediately repurchases appreciated
    holdings: the balance is unchanged, the cost basis rises by the realised
    gain, and the gain is recognised for tax (and MAGI) this year. There is
    no wash-sale rule for gains. Only ``taxable_brokerage`` accounts with
    tracked basis are eligible. Returns account_id -> gain realised.

    The simulator supplies ``amount_limit`` to solve the band and MAGI limits
    on the post-harvest tax: the gain itself can raise ordinary taxable income
    (IRC 86 Social Security inclusion, IRC 151(d)(5) senior-deduction
    phase-out). It only lowers the pre-harvest room, which leaves deductions
    that ordinary income cannot absorb for the year's later sales.
    """
    result: dict[str, float] = {}
    if tax_context is None:
        return result
    room_used = 0.0
    for p in sorted(priorities, key=lambda x: x.priority_rank):
        if p.priority_type != "gain_harvest" or p.source_account_id is None:
            continue
        if p.bracket_ceiling_rate is None and not p.use_plan_tax_target:
            continue
        if p.use_plan_tax_target and amount_limit is None:
            # Only the simulator can solve the plan target on the final tax.
            continue
        if triggered_milestones is not None and (p.start_milestone_id or p.end_milestone_id):
            if not is_event_active(p.start_milestone_id, p.end_milestone_id, triggered_milestones):
                continue
        acct = state.accounts.get(p.source_account_id)
        if acct is None or acct.account_type not in _HARVEST_TYPES or acct.cost_basis is None:
            continue
        if p.source_account_id in state.locked_account_ids:
            continue
        unrealised = max(0.0, acct.balance - acct.cost_basis)
        if unrealised <= 0:
            continue
        if p.use_plan_tax_target:
            # The plan target's room is solved by amount_limit on the tax that
            # already includes earlier rules' gains.
            amount = unrealised
        else:
            room = gain_harvest_headroom(tax_context, p.bracket_ceiling_rate, state.roth_conversions_this_year) - room_used
            amount = min(unrealised, max(0.0, room))
        if p.max_annual_amount is not None:
            amount = min(amount, p.max_annual_amount)
        if p.magi_cap is not None and not p.use_plan_tax_target:
            cap_room = p.magi_cap * tax_context.inflation_factor - tax_context.modified_agi - state.roth_conversions_this_year - room_used
            amount = min(amount, max(0.0, cap_room))
        if amount_limit is not None and amount > 0:
            amount = min(amount, max(0.0, amount_limit(p, amount)))
        if amount <= 0:
            continue
        room_used += amount
        if state.indexed_cost_bases is not None:
            # A harvest sells this share of the holding and buys it back.
            record_sale(state, p.source_account_id, amount / unrealised, amount)
        acct.cost_basis += amount
        state.capital_gains_this_year += amount
        state.harvested_gains_this_year += amount
        result[p.source_account_id] = result.get(p.source_account_id, 0.0) + amount
    return result


def execute_roth_conversions(
    priorities: list[PriorityData],
    state: SimState,
    *,
    tax_context: ConversionTaxContext | None = None,
    triggered_milestones: set[str] | None = None,
    amount_limit: Callable[[PriorityData, float], float] | None = None,
) -> dict[str, float]:
    """Execute Roth conversions as account-to-account transfers.

    Unlike surplus allocation, Roth conversions are NOT gated on cash
    surplus — the source pre-tax account funds the conversion directly.
    The taxable income from the conversion is tracked via
    ``state.roth_conversions_this_year`` for the tax engine.

    ``fill_bracket`` rules convert only the headroom below the chosen
    federal bracket (and below ``magi_cap`` when set), so several rules in
    one year share the same headroom in rank order. Milestone bounds are
    honoured when ``triggered_milestones`` is supplied. The simulator supplies
    ``amount_limit`` to solve final bracket/MAGI limits, including deductions,
    income and ACA changes from funding the tax. Its upper bound is the source
    balance/annual dollar limit; pre-conversion headroom can grow (e.g. QBI).

    Returns a dict of target_account_id → amount converted.
    """

    validate_roth_conversion_rules(priorities, state.accounts)
    result: dict[str, float] = {}
    headroom_used = 0.0
    for p in sorted(priorities, key=lambda x: x.priority_rank):
        if p.priority_type != "roth_conversion":
            continue
        if p.target_account_id is None or p.source_account_id is None:
            continue
        if p.source_account_id in state.locked_account_ids:
            continue
        if triggered_milestones is not None and (p.start_milestone_id or p.end_milestone_id):
            if not is_event_active(p.start_milestone_id, p.end_milestone_id, triggered_milestones):
                continue
        source_balance = state.get_balance(p.source_account_id)
        if source_balance <= 0:
            continue
        amount = source_balance
        if p.max_annual_amount is not None:
            amount = min(amount, p.max_annual_amount)
        if p.use_plan_tax_target:
            # Sized only by the simulator's solve against the plan target.
            if tax_context is None or tax_context.flat_tax or amount_limit is None:
                continue
        elif p.conversion_mode == "fill_bracket":
            if tax_context is None or p.bracket_ceiling_rate is None:
                continue
            if tax_context.flat_tax:
                continue
            if amount_limit is None:
                room = bracket_fill_headroom(tax_context, p.bracket_ceiling_rate) - headroom_used
                amount = min(amount, max(0.0, room))
        if p.magi_cap is not None and tax_context is not None and amount_limit is None:
            cap_room = p.magi_cap * tax_context.inflation_factor - tax_context.modified_agi - headroom_used
            amount = min(amount, max(0.0, cap_room))
        if amount_limit is not None and amount > 0:
            amount = min(amount, max(0.0, amount_limit(p, amount)))
        if amount <= 0:
            continue
        headroom_used += amount
        state.withdraw_from(p.source_account_id, amount)
        state.deposit_to(p.target_account_id, amount, conversion_taxable=amount)
        state.roth_conversions_this_year += amount
        source_account = state.accounts.get(p.source_account_id)
        if source_account is not None:
            state.record_retirement_income(source_account.owner, "roth_conversion", amount)
        state.record_transfer(p.source_account_id, p.target_account_id, amount)
        result[p.target_account_id] = result.get(p.target_account_id, 0.0) + amount
    return result


def execute_transfers(
    priorities: list[PriorityData],
    state: SimState,
    *,
    age: int = 100,
    birth_month: int | None = None,
    withholding_rates: dict[str, float] | None = None,
    sepp_account_ids: set[str] | None = None,
    active_months: Callable[[PriorityData], list[int]] | None = None,
    month_growth: Callable[[str, list[int]], float] | None = None,
) -> dict[str, float]:
    """Execute account-to-account transfers independent of surplus.

    Like Roth conversions, transfers are NOT gated on cash surplus —
    the source account funds the transfer directly.  This fixes the
    previous bug where transfers consumed surplus cash (evaporating
    the source-funded amount from total net worth).

    Saved milestone bounds use the same annual activation semantics as
    surplus priorities: the start must be reached and the end unreached.

    What a transfer is depends on the accounts (``plan_validation.transfer_error``
    rejects everything else before any money moves):

    - cash or brokerage into cash or brokerage: a sale realizes gain on the
      shares sold (``state.withdraw_from``); the proceeds arrive in full less
      any configured withholding on that gain.
    - a retirement account into cash or brokerage: a distribution. A
      traditional distribution is ordinary income, a Roth distribution follows
      the Roth ordering rules, and either carries the 10% additional tax
      unless an exception applies. The target receives the amount net of that
      tax and of withholding; both are settled with the year's other taxes.
    - one traditional retirement account into another of the same owner: a
      direct rollover, which is neither income nor a contribution.

    A ``monthly`` rule (``transfer_frequency``) runs only in the calendar
    months ``active_months(rule)`` returns: the milestone window prorated to
    the month, within the simulated part of the year. A capped rule moves
    1/12 of ``max_annual_amount`` at the end of each active month; an
    uncapped rule moves the whole balance at the end of the first active
    month. Balances already include the year's growth, so the source gives
    up, and the target takes on, the growth or loss after each move:
    ``month_growth(account_id, months)`` is the average growth from the end
    of those months to the year's end. Without the callables (direct engine
    callers) every rule runs annually.

    Returns a dict of target_account_id -> amount delivered to the target.
    """

    # Validate before any movement so invalid legacy or direct-engine inputs
    # cannot become an untaxed distribution or a partial transfer sequence.
    validate_transfer_rules(priorities, state.accounts)
    result: dict[str, float] = {}
    for p in sorted(priorities, key=lambda x: x.priority_rank):
        if p.priority_type != "transfer":
            continue
        monthly = (p.transfer_frequency == "monthly" and active_months is not None
                   and month_growth is not None)
        if monthly:
            months = active_months(p)
            if not months:
                continue
        elif not is_event_active(
            p.start_milestone_id, p.end_milestone_id, state.triggered_milestones,
        ):
            continue
        if p.source_account_id is None or p.target_account_id is None:
            continue
        if p.source_account_id == p.target_account_id:
            continue
        if p.source_account_id in state.locked_account_ids:
            continue
        if p.source_account_id in (sepp_account_ids or ()):
            # Any extra withdrawal would modify an active 72(t) series.
            continue
        source_balance = state.get_balance(p.source_account_id)
        if source_balance <= 0:
            continue
        source = state.accounts[p.source_account_id]
        target = state.accounts[p.target_account_id]
        if monthly:
            moves = months if p.max_annual_amount is not None else months[:1]
            # Gains and losses after each move both belong to the target. A
            # source that lost everything after the moves (factor -1) cannot
            # be traced back to its balance at the move, so it moves as is.
            source_factor = month_growth(p.source_account_id, moves)
            if 1.0 + source_factor <= 1e-9:
                source_factor = 0.0
            target_factor = month_growth(p.target_account_id, moves)
            amount = source_balance / (1.0 + source_factor)
            if p.max_annual_amount is not None:
                amount = min(amount, p.max_annual_amount / 12.0 * len(months))
            if amount <= 0:
                continue
            # The moved money did not grow in the source after each move.
            drag = amount * source_factor
            source.balance -= drag
            state.withdrawal_growth_adjustment -= drag
        else:
            amount = source_balance
            if p.max_annual_amount is not None:
                amount = min(amount, p.max_annual_amount)
        delivered = _move_transfer(
            p, source, target, amount, state,
            age=age, birth_month=birth_month, withholding_rates=withholding_rates or {})
        if monthly and delivered > 0 and target_factor:
            # It grows in the target from each move to the year's end.
            gain = delivered * target_factor
            target.balance += gain
            state.withdrawal_growth_adjustment += gain
        state.record_transfer(p.source_account_id, p.target_account_id, amount)
        result[p.target_account_id] = result.get(p.target_account_id, 0.0) + delivered
    return result


def _move_transfer(
    p: PriorityData,
    source,
    target,
    amount: float,
    state: SimState,
    *,
    age: int,
    birth_month: int | None,
    withholding_rates: dict[str, float],
) -> float:
    """Move ``amount`` out of ``source`` with its tax; return what the target gets."""

    withholding_rate = max(0.0, min(0.99, withholding_rates.get(source.account_type, 0.0)))
    if source.account_type in TRADITIONAL_RETIREMENT_TYPES and target.account_type in TRADITIONAL_RETIREMENT_TYPES:
        # Direct rollover: nothing is distributed to the owner.
        state.withdraw_from(p.source_account_id, amount)
        state.deposit_to(p.target_account_id, amount)
        return amount

    withholding = 0.0
    penalty = 0.0
    if source.account_type in _TAXABLE_DRAWDOWN_TYPES:
        basis = source.cost_basis if source.cost_basis is not None else source.balance
        gain_fraction = max(0.0, min(1.0, 1.0 - basis / source.balance)) if source.balance > 0 else 0.0
        # Withholding applies to the realized-gain share of a sale, not to returned basis.
        withholding = amount * gain_fraction * withholding_rate
        state.withdraw_from(p.source_account_id, amount)
    elif source.account_type in TRADITIONAL_RETIREMENT_TYPES or source.account_type in ROTH_TYPES:
        owner_age = state.owner_ages.get(source.owner, age)
        owner_month = state.owner_birth_months.get(source.owner, birth_month)
        exempt = penalty_free_by_separation(
            source.account_type, source.inherited_year, source.distribution_settings, owner_age, state.year)
        penalized = (source.account_type in _EARLY_WITHDRAWAL_TYPES and source.inherited_year is None
                     and not exempt)
        if source.account_type in ROTH_TYPES:
            early_share = share_of_year_before_age(
                owner_age, owner_month, _EARLY_WITHDRAWAL_END_AGE, state.year_fraction)
            taxable, penalty = ledger(state).distribution(
                p.source_account_id, amount, source.balance, source.account_type,
                early_share > 0.5, source.inherited_year is not None, commit=True,
                penalty_exempt=exempt)
            state.roth_penalty_charged += penalty
            withholding = taxable * withholding_rate
        else:
            if penalized:
                penalty = amount * early_withdrawal_penalty_rate(
                    owner_age, owner_month, state.year_fraction, state.early_distribution_state_rates)
            withholding = amount * withholding_rate
            state.record_retirement_income(
                source.owner, ACCOUNT_TYPE_SOURCES[source.account_type], amount, account_id=p.source_account_id)
            state.transfer_income_this_year += amount
        state.withdraw_from(p.source_account_id, amount)
        state.transfer_penalty_this_year += penalty
    else:
        # Cash: nothing is realized.
        state.withdraw_from(p.source_account_id, amount)
    state.drawdown_tax_withheld_this_year += withholding
    delivered = max(0.0, amount - penalty - withholding)
    state.deposit_to(p.target_account_id, delivered)
    return delivered


@dataclass
class ShortfallRequest:
    """Part of a withdraw-if-short rule's amount the year's surplus did not cover.

    ``amount`` already respects every statutory and rule limit at the time
    the surplus ran out; :func:`fund_rule_shortfalls` rechecks them
    before depositing what the withdrawal order raises. ``flow`` is the
    rule's reported allocation, updated in place.
    """

    priority: PriorityData
    amount: float
    flow: NamedAmount
    age: int = 0
    filing_status: str | None = None
    modified_agi: float | None = None


def _rule_request(p: PriorityData, surplus: float, remaining: float, fraction: float,
                  limits: dict[str, float], deferred: bool) -> float:
    """The amount a rule asks for before its limits apply.

    A withdraw-if-short rule taking the "remaining" surplus asks for its tightest
    finite limit (annual maximum, contribution room, target balance or loan
    principal) instead, since a deficit year has no surplus to measure it
    by. With no finite limit it can only take what surplus remains.
    """
    if p.allocation_mode == "percentage":
        return surplus * max(0.0, min(100.0, p.allocation_value or 0.0)) / 100.0
    if p.allocation_mode == "amount":
        return max(0.0, p.allocation_value or 0.0) * fraction
    if deferred:
        finite = [limit for limit in limits.values() if math.isfinite(limit)]
        return max(0.0, min(finite)) if finite else max(0.0, remaining)
    return remaining


def _allocate_debt_payment(
    p: PriorityData,
    surplus: float,
    remaining: float,
    state: SimState,
    fraction: float,
    shortfall_pending: list[ShortfallRequest] | None = None,
) -> float:
    """Apply surplus to a loan's principal; return the cash it consumed.

    The payment is capped by the surplus left after earlier rules, the rule's
    own amount/percent/annual limit and the loan's remaining principal, so it
    can neither overpay the loan nor spend cash that is not there. It is made
    after the year's scheduled payment, so the year's interest is unchanged and
    the lower balance reduces interest from the next year on. A withdraw-if-short
    rule (with ``shortfall_pending``) is not capped by the surplus; the part
    the surplus cannot pay is queued for the withdrawal order.
    """
    loan = state.liability_states.get(p.target_liability_id) if p.target_liability_id else None
    if loan is None:
        return 0.0
    deferred = p.withdraw_if_short and shortfall_pending is not None
    active = is_event_active(p.start_milestone_id, p.end_milestone_id, state.triggered_milestones)
    principal = max(0.0, loan.remaining_balance)
    limits = {} if deferred else {"available surplus": remaining}
    limits["remaining principal"] = principal
    if p.max_annual_amount is not None:
        limits["annual maximum"] = max(0.0, p.max_annual_amount)
    requested = _rule_request(p, surplus, remaining, fraction, limits, deferred)
    reasons: list[str] = []
    if remaining <= 0 and not deferred:
        reasons.append("insufficient_surplus" if surplus <= 0 else "earlier_rules")
    if principal <= 0.005:
        reasons.append("loan_paid_off")
    if p.max_annual_amount == 0:
        reasons.append("annual_maximum")
    desired = max(0.0, min(requested, *limits.values())) if active else 0.0
    payment = min(desired, max(0.0, remaining)) if deferred else desired
    if payment < 0.005:
        payment = 0.0
    flow = NamedAmount(
        name=f"Pay down {loan.name or 'loan'}", amount=payment,
        source="priority", priority_rank=p.priority_rank, requested_amount=requested,
        funding_reasons=list(dict.fromkeys(reasons)) if active else ["inactive_rule"],
        limited_by=[label for label, limit in limits.items() if limit < requested - 0.005],
    )
    state.allocation_flows.append(flow)
    if deferred and desired - payment > 0.005:
        shortfall_pending.append(ShortfallRequest(p, desired - payment, flow))
    if payment <= 0:
        return 0.0
    _pay_down_loan(p, loan, payment, state)
    return payment


def _pay_down_loan(p: PriorityData, loan, payment: float, state: SimState) -> None:
    loan.remaining_balance = max(0.0, loan.remaining_balance - payment)
    state.debt_prepayments[p.target_liability_id] = state.debt_prepayments.get(p.target_liability_id, 0.0) + payment


def _deposit_contribution(p: PriorityData, acct: AccountInfo, deposit: float, state: SimState) -> None:
    """Deposit a surplus contribution and count it toward the year's limits."""
    backdoor_taxable = (backdoor_prorata_taxable(deposit, acct.owner, state)
                        if p.backdoor_roth and acct.account_type == "roth_ira" else None)
    state.deposit_to(p.target_account_id, deposit, conversion_taxable=backdoor_taxable)
    state.ytd_contributions[p.target_account_id] = (
        state.ytd_contributions.get(p.target_account_id, 0.0) + deposit
    )
    if p.target_account_id in state.intl_kinds:
        after_contribution(state, p.target_account_id, deposit)
    if backdoor_taxable:
        state.roth_conversions_this_year += backdoor_taxable
        state.record_retirement_income(acct.owner, "roth_conversion", backdoor_taxable)
        state.backdoor_prorata_taxable += backdoor_taxable


def _contribution_limits(p: PriorityData, acct: AccountInfo, state: SimState, age: int,
                         filing_status: str | None, modified_agi: float | None,
                         reasons: list[str], funded: float = 0.0) -> dict[str, float]:
    """Every ceiling on a contribution rule except the available surplus.

    ``funded`` is what the rule already deposited this year, which counts
    against its annual maximum.
    """
    limits: dict[str, float] = {}
    if p.max_annual_amount is not None:
        limits["annual maximum"] = max(0.0, p.max_annual_amount - funded)
    limits["contribution eligibility / annual limit"] = contribution_room(
        p.target_account_id, state, age, filing_status, modified_agi, reasons,
        backdoor=p.backdoor_roth)
    plan_room = custom_limit_room(p, p.target_account_id, state)
    if plan_room is not None:
        limits["plan contribution limit"] = plan_room
        if plan_room <= 0:
            reasons.append("contribution_limit")
    if p.target_balance is not None:
        limits["target balance"] = max(0.0, p.target_balance - acct.balance)
    return limits


def allocate_surplus(
    surplus: float,
    priorities: list[PriorityData],
    state: SimState,
    age: int = 0,
    filing_status: str | None = None,
    modified_agi: float | None = None,
    target_balance_fraction: float = 1.0,
    shortfall_pending: list[ShortfallRequest] | None = None,
) -> dict[str, float]:
    """Allocate surplus cash to accounts in priority_rank order.

    Respects both user ``max_annual_amount`` caps and IRS contribution
    limits (when *age* > 0).  Mutates *state* via ``state.deposit_to()``
    and updates ``state.ytd_contributions``.

    Withdraw-if-short rules run first, in rank order among themselves. When the
    caller passes ``shortfall_pending``, the part of such a rule's amount
    the surplus cannot cover (within every other limit) is appended there
    for :func:`fund_rule_shortfalls`; without it they take surplus
    only, like other rules.

    Returns a dict of account_id → amount deposited.
    """
    result: dict[str, float] = {}
    if not priorities:
        return result

    surplus = max(0.0, surplus)
    remaining = surplus
    fraction = max(0.0, min(1.0, target_balance_fraction))
    for p in sorted(priorities, key=lambda x: (not x.withdraw_if_short, x.priority_rank)):
        if p.priority_type == "debt_payment":
            remaining -= _allocate_debt_payment(p, surplus, remaining, state, fraction, shortfall_pending)
            continue
        if p.target_account_id is None:
            continue
        active = is_event_active(p.start_milestone_id, p.end_milestone_id, state.triggered_milestones)

        if p.priority_type in (
            "roth_conversion",
            "transfer",
            "income_percent",
            "pre_tax_contribution",
            "after_tax_401k",
            "gain_harvest",
        ):
            # Handled separately by execute_roth_conversions() / execute_transfers()
            continue
        acct = state.accounts.get(p.target_account_id)
        if acct is None:
            continue
        deferred = p.withdraw_if_short and shortfall_pending is not None
        reasons: list[str] = []
        limits = {} if deferred else {"available surplus": remaining}
        limits.update(_contribution_limits(p, acct, state, age, filing_status, modified_agi, reasons))
        requested = _rule_request(p, surplus, remaining, fraction, limits, deferred)
        if remaining <= 0 and not deferred:
            reasons.append("insufficient_surplus" if surplus <= 0 else "earlier_rules")
        if p.max_annual_amount == 0:
            reasons.append("annual_maximum")
        if p.target_balance is not None and acct.balance >= p.target_balance:
            reasons.append("target_balance")
        if p.allocation_mode != "remaining" and requested <= 0 and surplus > 0:
            reasons.append("zero_request")
        desired = max(0.0, min(requested, *limits.values())) if active else 0.0
        deposit = min(desired, max(0.0, remaining)) if deferred else desired
        flow = NamedAmount(
            name=acct.name or p.target_account_id, amount=deposit,
            account_id=p.target_account_id, account_name=acct.name or p.target_account_id,
            source="priority", priority_rank=p.priority_rank,
            requested_amount=requested,
            funding_reasons=list(dict.fromkeys(reasons)) if active else ["inactive_rule"],
            limited_by=[label for label, limit in limits.items() if limit < requested - 0.005],
        )
        state.allocation_flows.append(flow)
        if deferred and desired - deposit > 0.005:
            shortfall_pending.append(ShortfallRequest(
                p, desired - deposit, flow, age, filing_status, modified_agi))

        if deposit <= 0:
            continue

        _deposit_contribution(p, acct, deposit, state)
        result[p.target_account_id] = result.get(p.target_account_id, 0.0) + deposit
        remaining -= deposit

    return result


def shortfall_excluded_sources(p: PriorityData, state: SimState) -> frozenset[str]:
    """Accounts a withdraw-if-short rule may not draw from.

    A rule never draws from its own destination. For a destination with an
    annual contribution limit (IRA, workplace plan, HSA and the like) it also
    skips the same owner's accounts sharing that limit, so it cannot withdraw
    from one traditional or Roth account only to redeposit the money in its
    sibling. Debt payment rules have no destination account.
    """
    acct = state.accounts.get(p.target_account_id) if p.target_account_id else None
    if acct is None:
        return frozenset()
    excluded = {p.target_account_id}
    if acct.account_type in _IRS_LIMITS or acct.account_type in EMPLOYER_PLAN_TYPES:
        group = contribution_limit_group(acct.account_type)
        excluded.update(aid for aid, other in state.accounts.items()
                        if other.owner == acct.owner and other.account_type in group)
    return frozenset(excluded)


def fund_rule_shortfalls(
    pending: list[ShortfallRequest],
    state: SimState,
    draw: Callable[[float, frozenset[str]], float],
    current_magi: Callable[[], float] | None = None,
    keep_cash: Callable[[float], None] | None = None,
) -> dict[str, float]:
    """Fund what the surplus could not cover for withdraw-if-short rules.

    Runs after the year's spending deficit has been drawn, so goals never
    take money the plan's spending needs. In rank order, each request is
    rechecked against its limits (earlier requests may have used shared
    room), then ``draw(amount, excluded_account_ids)`` withdraws through the
    plan's withdrawal order and returns the net cash raised. What cannot be
    raised is added to ``state.rule_funding_shortfall``; it does not count as
    an unfunded expense or a plan failure.

    Roth IRA income test: withdrawals can raise modified AGI and so lower
    the Roth IRA phase-out limit. With ``current_magi`` (the year's modified
    AGI as of now, for the Roth IRA limit), a Roth IRA request is rechecked
    at the higher of its queued MAGI and the current one, before and again
    after its own withdrawal. This is a single fixed-point pass: when the
    withdrawal itself lowers the limit, only the eligible part is deposited
    and the rest of the cash raised goes to ``keep_cash`` (the plan's cash
    account) instead of being withdrawn again. The pass does not iterate
    toward the larger amount a smaller withdrawal might have allowed.

    Returns a dict of account_id → amount deposited.
    """
    result: dict[str, float] = {}
    for request in pending:
        p = request.priority
        loan = None
        acct = None
        roth_income_test = False
        magi = request.modified_agi
        if p.priority_type == "debt_payment":
            loan = state.liability_states.get(p.target_liability_id)
            if loan is None:
                continue
            need = min(request.amount, max(0.0, loan.remaining_balance))
        else:
            acct = state.accounts.get(p.target_account_id)
            if acct is None:
                continue
            roth_income_test = (acct.account_type == "roth_ira" and current_magi is not None
                                and keep_cash is not None and magi is not None)
            if roth_income_test:
                magi = max(magi, current_magi())
            limits = _contribution_limits(p, acct, state, request.age, request.filing_status,
                                          magi, [], funded=request.flow.amount)
            need = max(0.0, min(request.amount, *limits.values()))
        if need <= 0.005:
            continue
        raised = max(0.0, min(need, draw(need, shortfall_excluded_sources(p, state))))
        if raised < 0.005:
            raised = 0.0
        shortfall = need - raised
        if roth_income_test and raised > 0:
            after = _contribution_limits(p, acct, state, request.age, request.filing_status,
                                         max(magi, current_magi()), [], funded=request.flow.amount)
            eligible = max(0.0, min(raised, *after.values()))
            if raised - eligible > 0.005:
                keep_cash(raised - eligible)
                for label, limit in after.items():
                    if limit < raised - 0.005 and label not in request.flow.limited_by:
                        request.flow.limited_by.append(label)
                # The lower limit, not missing cash, is why the rest is unfunded.
                shortfall = 0.0
                raised = eligible
        if raised > 0:
            if loan is not None:
                _pay_down_loan(p, loan, raised, state)
            else:
                _deposit_contribution(p, acct, raised, state)
                result[p.target_account_id] = result.get(p.target_account_id, 0.0) + raised
            request.flow.amount += raised
        if shortfall > 0.005:
            state.rule_funding_shortfall += shortfall
            request.flow.funding_reasons = list(dict.fromkeys(
                [*request.flow.funding_reasons, "withdrawal_shortfall"]))
            if "available withdrawals" not in request.flow.limited_by:
                request.flow.limited_by.append("available withdrawals")
    return result


def backdoor_prorata_taxable(contribution: float, owner: str, state: SimState) -> float:
    """Taxable share of a backdoor Roth contribution under the IRA pro-rata rule.

    Converting a fresh nondeductible contribution while the same person holds
    pre-tax traditional IRA money taxes the conversion in proportion to the
    pre-tax share of all their IRAs (IRS Form 8606). Inherited IRAs and
    workplace plans are outside that pool. The after-tax basis that stays in
    the traditional IRA is not tracked; the app says so in a warning.
    """
    pretax = sum(
        a.balance for a in state.accounts.values()
        if a.account_type == "traditional_ira" and a.owner == owner and a.inherited_year is None
    )
    if contribution <= 0 or pretax <= 0:
        return 0.0
    return contribution * pretax / (pretax + contribution)


def blend_source_eligible(
    account_id: str,
    state: SimState,
    *,
    age: int,
    birth_month: int | None,
    sepp_account_ids: set[str] | None = None,
) -> bool:
    """Whether a tax-target blending pass may draw from this account.

    Only withdrawals that create taxable income qualify: tax-deferred
    accounts (ordinary income) and taxable accounts holding an unrealized
    gain (the realized share of each sale). Cash, Roth and HSA accounts, withdrawal-locked and
    active-SEPP accounts, and accounts that would carry an early-withdrawal
    penalty this year are skipped.
    """
    if account_id in (sepp_account_ids or ()) or account_id in state.locked_account_ids:
        return False
    acct = state.accounts.get(account_id)
    if acct is None or state.get_balance(account_id) <= 0:
        return False
    if acct.account_type in _TAXABLE_TYPES:
        # A sale realizes income only from unrealized gain; untracked basis is
        # treated as all basis (calculate_gain_on_withdrawal).
        return acct.cost_basis is not None and acct.balance > acct.cost_basis
    if acct.account_type not in TRADITIONAL_RETIREMENT_TYPES:
        return False
    if acct.account_type in _EARLY_WITHDRAWAL_TYPES and acct.inherited_year is None:
        owner_age = state.owner_ages.get(acct.owner, age)
        rate = 0.0 if penalty_free_by_separation(
            acct.account_type, acct.inherited_year, acct.distribution_settings, owner_age, state.year,
        ) else early_withdrawal_penalty_rate(
            owner_age, state.owner_birth_months.get(acct.owner, birth_month),
            state.year_fraction, state.early_distribution_state_rates)
        if rate > 0:
            return False
    return True


def execute_drawdown(
    deficit: float,
    drawdown_order: list[DrawdownEntryData],
    state: SimState,
    age: int = 100,
    sepp_account_ids: set[str] | None = None,
    birth_month: int | None = None,
    withholding_rates: dict[str, float] | None = None,
    hsa_qualified: bool = False,
    gross_limits: dict[str, float] | None = None,
    education_qualified: bool = False,
    reserve_fallback: bool = True,
) -> tuple[dict[str, float], float]:
    """Draw to cover *deficit*, protecting an opt-in cash reserve.

    Without a reserve (``state.cash_reserve_accounts`` empty) this is exactly
    :func:`_drawdown_pass`. With one, the first pass leaves the reserve
    dollars untouched in the saved order; only when the other accounts cannot
    cover the deficit does a second pass spend the reserve accounts in their
    listed order. Locks, 72(t) series and exhaustion apply to both passes.
    ``reserve_fallback=False`` skips the second pass (partial passes such as
    tax-target blending leave the remainder to the full pass).
    """
    if deficit > 0 and not drawdown_order:
        # No accounts to draw from: immediate failure.
        state.failure_year = state.failure_year or state.year
        state.unfunded_expenses += deficit
        return {}, 0.0
    reserve_ids = state.cash_reserve_accounts
    floors = reserve_floors(
        {aid: state.get_balance(aid) for aid in reserve_ids if aid in state.accounts},
        reserve_ids, state.cash_reserve_target) if reserve_ids and deficit > 0 else {}
    if not floors:
        result, penalty, remaining = _drawdown_pass(
            deficit, drawdown_order, state, age, sepp_account_ids, birth_month,
            withholding_rates, hsa_qualified, gross_limits, education_qualified)
        _record_unfunded(state, remaining)
        return result, penalty
    limits = dict(gross_limits or {})
    for aid, floor in floors.items():
        cap = max(0.0, state.get_balance(aid) - floor)
        limits[aid] = min(limits[aid], cap) if aid in limits else cap
    result, penalty, remaining = _drawdown_pass(
        deficit, drawdown_order, state, age, sepp_account_ids, birth_month,
        withholding_rates, hsa_qualified, limits, education_qualified)
    if remaining > 0.01 and reserve_fallback:
        fallback = [DrawdownEntryData(index + 1, aid) for index, aid in enumerate(reserve_ids)]
        more, more_penalty, remaining = _drawdown_pass(
            remaining, fallback, state, age, sepp_account_ids, birth_month,
            withholding_rates, hsa_qualified, gross_limits, education_qualified)
        for aid, value in more.items():
            result[aid] = result.get(aid, 0.0) + value
        penalty += more_penalty
    _record_unfunded(state, remaining)
    return result, penalty


def _record_unfunded(state: SimState, remaining: float) -> None:
    if remaining > 0.01:
        state.failure_year = state.failure_year or state.year
        state.unfunded_expenses += remaining


def _drawdown_pass(
    deficit: float,
    drawdown_order: list[DrawdownEntryData],
    state: SimState,
    age: int = 100,
    sepp_account_ids: set[str] | None = None,
    birth_month: int | None = None,
    withholding_rates: dict[str, float] | None = None,
    hsa_qualified: bool = False,
    gross_limits: dict[str, float] | None = None,
    education_qualified: bool = False,
) -> tuple[dict[str, float], float, float]:
    """Draw from accounts in rank order to cover *deficit*.

    Clamps each withdrawal to the account's available balance.
    Applies a 10% IRS early-withdrawal penalty for retirement accounts
    when the taxpayer is under 59.5 (see
    :func:`is_subject_to_early_withdrawal_penalty`), plus any state
    additional tax for resident months (``state.early_distribution_state_rates``),
    unless the account is SEPP 72(t)-exempt.
    Sets ``state.failure_year`` if all accounts are exhausted and a
    shortfall remains.

    HSA withdrawals are untaxed up to ``state.hsa_medical_allowance`` (the
    year's remaining modeled qualified medical costs); the rest is taxable
    income plus a 20% additional tax before 65, accumulated on ``state``.
    The Medicare-premium part (``state.hsa_medicare_premium_allowance``)
    counts only for the owner's months at 65 or older and is used first.
    ``hsa_qualified`` marks spending the user funded from the HSA directly,
    and a ``None`` allowance keeps the untaxed treatment for direct callers.

    529 withdrawals work the same way with ``state.education_allowance``
    (the year's remaining qualified education expenses) and
    ``education_qualified``: the earnings share of the rest is income
    (``state.education_taxable_earnings_this_year``) plus a 10% additional
    tax (coastmath.engine.education_savings).

    Optional account-type ``withholding_rates`` are treated as cash withheld
    from the distribution, so each withdrawal is grossed up to cover the net
    deficit.  Withholding is accumulated on ``state`` for the simulator's tax
    settlement calculation.

    ``gross_limits`` caps the gross amount taken from listed accounts (the
    tax-target blending pass); other accounts are unaffected.

    Returns ``(drawdown_amounts, total_penalty, unmet)`` — a dict of
    account_id → gross amount withdrawn, the total penalty incurred and the
    deficit left unfunded (recorded by the caller).
    """
    result: dict[str, float] = {}
    total_penalty = 0.0
    if deficit <= 0 or not drawdown_order:
        # No accounts to draw from when deficit > 0: the caller records failure.
        return result, total_penalty, max(0.0, deficit)

    _sepp_ids = sepp_account_ids or set()
    remaining = deficit
    for entry in sorted(drawdown_order, key=lambda x: x.rank):
        if remaining <= 0:
            break
        if entry.source_account_id is None:
            continue
        if entry.source_account_id in _sepp_ids:
            # An active 72(t) series must not be modified: any withdrawal
            # beyond the scheduled payment busts the series and applies the
            # 10% penalty retroactively (IRC 72(t)(4)). The scheduled payment
            # is taken separately by the simulator, so skip this account here.
            continue
        if entry.source_account_id in state.locked_account_ids:
            # Withdrawal-locked (coastmath.engine.withdrawal_locks): not available.
            continue

        growth_factor = state.withdrawal_growth_factors.get(entry.source_account_id, 0.0)
        available = max(0.0, state.get_balance(entry.source_account_id)) / (1 + growth_factor)
        if gross_limits is not None and entry.source_account_id in gross_limits:
            available = min(available, max(0.0, gross_limits[entry.source_account_id]))

        # Check if this account incurs the 10% early withdrawal penalty
        acct = state.accounts.get(entry.source_account_id)
        if acct is None:
            continue
        owner_age = state.owner_ages.get(acct.owner, age)
        owner_month = state.owner_birth_months.get(acct.owner, birth_month)
        # Evenly spread withdrawals: the share made before 59.5 is penalized.
        # Roth ordering holds one early/qualified status per year, so it uses
        # the status covering most of the year.
        early_share = share_of_year_before_age(
            owner_age, owner_month, _EARLY_WITHDRAWAL_END_AGE, state.year_fraction)
        age_penalty_applies = early_share > 0.5
        is_roth = acct.account_type in ROTH_TYPES
        # Rule of 55: the 10% (and a state's matching additional tax) does not
        # apply, but a designated Roth distribution before 59 1/2 stays
        # non-qualified, so its earnings remain income.
        penalty_exempt = penalty_free_by_separation(
            acct.account_type, acct.inherited_year, acct.distribution_settings, owner_age, state.year)
        penalized = (
            acct is not None
            and acct.account_type in _EARLY_WITHDRAWAL_TYPES
            and acct.inherited_year is None
            and not is_roth
            and not penalty_exempt
        )
        penalty_rate = early_withdrawal_penalty_rate(
            owner_age, owner_month, state.year_fraction,
            state.early_distribution_state_rates) if penalized else 0.0
        # A country account kind before its access age (coastmath.engine.intl_accounts).
        penalty_rate = state.intl_penalty_rates.get(entry.source_account_id, penalty_rate)
        withholding_rate = 0.0
        if acct is not None and withholding_rates is not None:
            withholding_rate = max(
                0.0,
                min(0.99, withholding_rates.get(acct.account_type, 0.0)),
            )
            if acct.account_type in _TAXABLE_DRAWDOWN_TYPES:
                basis = acct.cost_basis if acct.cost_basis is not None else acct.balance
                gain_fraction = (
                    max(0.0, min(1.0, 1.0 - basis / acct.balance))
                    if acct.balance > 0
                    else 0.0
                )
                # Taxable-account withholding applies to the realized-gain
                # portion of a sale, not to returned cost basis.
                withholding_rate *= gain_fraction
        total_deduction_rate = penalty_rate + withholding_rate
        if total_deduction_rate >= 1.0:
            total_deduction_rate = 0.99
        hsa_taxable = 0.0
        hsa_allowance_applies = (acct.account_type == "hsa" and not hsa_qualified
                                 and state.hsa_medical_allowance is not None)
        education_applies = (acct.account_type == EDUCATION_ACCOUNT_TYPE
                             and state.education_allowance is not None)
        education_earnings = 0.0
        education_qualified_amount = 0.0

        # Called only within this iteration, so it sees this entry's values.
        def roth_cost(amount, *, commit=False):
            # Designated Roth proportions use the value remaining after the
            # foregone growth on this particular withdrawal is removed.
            taxable, penalty = ledger(state).distribution(entry.source_account_id, amount,  # noqa: B023
                max(0.0, acct.balance - amount * growth_factor), acct.account_type,  # noqa: B023
                age_penalty_applies, acct.inherited_year is not None, commit=commit,  # noqa: B023
                penalty_exempt=penalty_exempt)  # noqa: B023
            return penalty, taxable * withholding_rate  # noqa: B023

        if is_roth:
            # Contribution/conversion thresholds make a flat gross-up wrong.
            # Solve the monotone net-cash function within the affordable balance.
            withdrawal = min(remaining, available)
            p, w = roth_cost(withdrawal)
            if p + w > .000001:
                low, high = withdrawal, available
                for _ in range(40):
                    midpoint = (low + high) / 2
                    p, w = roth_cost(midpoint)
                    if midpoint - p - w < remaining:
                        low = midpoint
                    else:
                        high = midpoint
                withdrawal = high
            penalty, withholding = roth_cost(withdrawal, commit=True)
            state.roth_penalty_charged += penalty
        elif hsa_allowance_applies:
            # Reimbursing this year's qualified medical costs comes first and
            # is untaxed; the additional tax on the rest is paid from it.
            hsa_rate = _HSA_ADDITIONAL_TAX * share_of_year_before_age(
                owner_age, owner_month, _HSA_ADDITIONAL_TAX_END_AGE, state.year_fraction)
            # Insurance premiums qualify only once the account beneficiary
            # is 65 (IRC 223(d)(2)(C)(iv); Pub. 969), so an owner under 65
            # cannot reimburse a spouse's Medicare premiums.
            allowance = max(0.0, state.hsa_medical_allowance)
            premium_pool = min(allowance, max(0.0, state.hsa_medicare_premium_allowance))
            premium_cap = premium_pool * (1.0 - share_of_year_before_age(
                owner_age, owner_month, _HSA_ADDITIONAL_TAX_END_AGE, state.year_fraction))
            qualified = min(remaining, allowance - premium_pool + premium_cap, available)
            hsa_premium_used = min(qualified, premium_cap)
            withdrawal = min(qualified + (remaining - qualified) / (1.0 - hsa_rate), available)
            hsa_taxable = withdrawal - qualified
            penalty = hsa_taxable * hsa_rate
            withholding = 0.0
        elif education_applies:
            # Qualified expenses first, untaxed; the earnings share of the
            # rest is income plus the additional tax, paid from the withdrawal.
            # Earnings are measured on the value left after foregone growth.
            fraction = earnings_fraction(max(0.0, acct.balance - available * growth_factor), acct.cost_basis)
            education_rate = nonqualified_additional_tax_rate() * fraction
            qualified = (min(remaining, available) if education_qualified
                         else min(remaining, max(0.0, state.education_allowance), available))
            withdrawal = min(qualified + (remaining - qualified) / (1.0 - education_rate), available)
            education_qualified_amount = qualified
            education_earnings = (withdrawal - qualified) * fraction
            penalty = (withdrawal - qualified) * education_rate
            withholding = 0.0
        else:
            gross_needed = remaining / (1.0 - total_deduction_rate)
            withdrawal = min(gross_needed, available)
            penalty = withdrawal * penalty_rate
            withholding = withdrawal * withholding_rate

        if withdrawal > 0:
            if hsa_allowance_applies:
                state.hsa_medical_allowance -= withdrawal - hsa_taxable
                state.hsa_medicare_premium_allowance -= hsa_premium_used
                state.hsa_taxable_distributions_this_year += hsa_taxable
            if education_applies:
                state.education_allowance = max(0.0, state.education_allowance - education_qualified_amount)
                state.education_qualified_withdrawals_this_year += education_qualified_amount
                state.education_taxable_earnings_this_year += education_earnings
            # End-of-year balances include growth on money spent earlier.
            # Reserve that foregone growth BEFORE computing affordable cash;
            # capping a correction after withdrawal would hide insolvency.
            drag = withdrawal * growth_factor
            acct.balance -= drag
            state.withdrawal_growth_adjustment -= drag
            dividend_drag = withdrawal * state.withdrawal_dividend_factors.get(entry.source_account_id, 0.0)
            if acct.account_type in _TAXABLE_DRAWDOWN_TYPES and dividend_drag > 0:
                # Unearned income leaves each tax character (qualified and
                # ordinary dividends, bond interest) in its recognized share.
                state.reverse_yield_income(entry.source_account_id, dividend_drag)
                if acct.cost_basis is not None:
                    acct.cost_basis = max(0.0, acct.cost_basis - dividend_drag)
            # Realize basis against the value actually available for sale,
            # after removing the growth/dividends that were never earned.
            # Otherwise full depletion leaves basis behind in an empty account.
            state.withdraw_from(entry.source_account_id, withdrawal)
            result[entry.source_account_id] = (
                result.get(entry.source_account_id, 0.0) + withdrawal
            )
            total_penalty += penalty
            state.drawdown_tax_withheld_this_year += withholding
            # Net amount that covers the deficit after penalty and withholding.
            remaining -= (withdrawal - penalty - withholding)

    return result, total_penalty, remaining

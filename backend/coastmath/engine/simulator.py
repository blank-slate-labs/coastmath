"""Main simulation loop — 12-step yearly projection engine.

Orchestrates milestones, income, expenses, taxes, waterfall allocation,
and drawdown into a year-by-year financial projection.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from functools import partial
from typing import Any, NamedTuple

from coastmath.engine import (
    estimated_tax,
    intl_accounts,
    intl_bridge,
    intl_cost_base,
    intl_regime,
    real_estate,
)
from coastmath.engine import household_lifecycle as lifecycle
from coastmath.engine.account_types import (
    ANNUAL_ADDITIONS_415C_TYPES,
    EARLY_WITHDRAWAL_PENALTY_TYPES,
    ELECTIVE_DEFERRAL_TYPES,
    EMPLOYER_PLAN_FAMILY,
    IRA_ACTIVE_PARTICIPANT_PLAN_TYPES,
    PRE_TAX_CONTRIBUTION_TYPES,
    RETIREMENT_ACCOUNT_TYPES,
    RMD_TYPES,
    ROTH_EMPLOYER_PLAN_TYPES,
    ROTH_TYPES,
    SECTION_457B_TYPES,
    TRADITIONAL_EMPLOYER_PLAN_TYPES,
    TRADITIONAL_RETIREMENT_TYPES,
)
from coastmath.engine.amortization import calculate_year as amortize_year
from coastmath.engine.amortization import resolve_monthly_payment
from coastmath.engine.assumption_curves import (
    DEFAULT_BOND_ALLOCATION,
    resolve_assumption,
)
from coastmath.engine.bond_location import (
    parse_asset_location,
    resolve_bond_allocations,
)
from coastmath.engine.cash_reserve import reserve_floors
from coastmath.engine.coverage_rules import active_coverage, state_payroll_obligations
from coastmath.engine.debt_relief import (
    apply_forgiveness,
    forgiven_amounts,
    forgiveness_due,
)
from coastmath.engine.education_savings import (
    EDUCATION_ACCOUNT_TYPE,
    state_contribution_deduction,
    state_deduction_supported,
)
from coastmath.engine.estate_tax import calculate_net_legacy, step_up_joint_accounts
from coastmath.engine.flex_spending import (
    apply_flex_rules,
    discretionary_share,
    flex_multiplier,
    flex_strategy_spending,
    scope_multiplier,
    spends_leftover,
)
from coastmath.engine.healthcare import (
    age_curve_factor,
    calculate_medicare_premiums,
    calculate_premium_tax_credit,
    medicare_cost_factor,
    parse_healthcare_settings,
    poverty_line,
)
from coastmath.engine.historical_data import DIVIDEND_YIELD_PROVENANCE
from coastmath.engine.income_events import PensionAccrual, payment_share
from coastmath.engine.income_growth_schedule import next_amount, opening_amount
from coastmath.engine.local_tax import LocalIncome
from coastmath.engine.milestones import (
    FI_ESTIMATE_METRIC,
    FI_ESTIMATE_MULTIPLE,
    evaluate_milestones,
    expense_multiple_reached,
    is_event_active,
    never_active_windows,
    prorate_for_year,
    resolve_deterministic_milestones,
    resolve_trigger_month,
    with_social_security_claiming,
)
from coastmath.engine.payroll_elections import payroll_wage_reductions
from coastmath.engine.person_healthcare import (
    aca_participates,
    add_person_costs,
    lookback_filing_status,
    medical_total,
    medicare_enrollment_start,
    person_profiles,
    validate_person_healthcare_plan,
)
from coastmath.engine.plan_validation import (
    validate_account_history,
    validate_roth_conversion_rules,
)
from coastmath.engine.residency import (
    resolve_country_for_year,
    resolve_local_tax_for_year,
    resolve_residency_spans,
    resolve_state_for_year,
)
from coastmath.engine.return_validation import validate_override_returns
from coastmath.engine.rmd import (
    calculate_inherited_ira_rmd,
    calculate_rmd,
    get_rmd_start_age,
    is_rmd_required,
    rmd_start_age_override,
    spouse_more_than_ten_years_younger,
)
from coastmath.engine.roth import ledger
from coastmath.engine.sepp import (
    calculate_sepp,
    custom_amount_qualifies,
    first_distribution_month,
    sepp_rate_ceiling,
    sepp_year_fraction,
)
from coastmath.engine.ss_divorced import apply_household_benefits
from coastmath.engine.ss_earnings import RULES as SS_EARNINGS_RULES
from coastmath.engine.ss_earnings import (
    CoveredRecords,
    arf_factor,
    earnings_test_due,
    fully_withheld_months,
    spousal_arf_factor,
)
from coastmath.engine.ss_household import month_index, owner_birth, retirement_fra_index
from coastmath.engine.state_retirement_exclusion import (
    ACCOUNT_TYPE_SOURCES,
    STREAM_CATEGORY_SOURCES,
    RetirementIncome,
)
from coastmath.engine.state_tax_allocation import CAPartYearWageContext
from coastmath.engine.state_taxed_basis import (
    basis_distributions,
    basis_recovery_by_account,
)
from coastmath.engine.state_taxed_basis import commit_year as commit_state_taxed_basis
from coastmath.engine.survivor_social_security import (
    grown_benefit,
    prepare_survivor_policy,
    survivor_arf_annual,
    survivor_fra_months,
    survivor_top_up,
)
from coastmath.engine.tax_adjustments import resolve_year_adjustments
from coastmath.engine.tax_engine import (
    calculate as calculate_tax,
)
from coastmath.engine.tax_engine import (
    calculate_mixed_fica_tax,
    capital_gain_property_charitable_limit,
    cash_charitable_limit,
    federal_ordinary_brackets,
    get_ltcg_brackets,
    state_early_distribution_rate,
)
from coastmath.engine.tax_schedule import effective_tax_settings
from coastmath.engine.tax_target import (
    IRMAA_LOOKBACK_YEARS,
    MEDICARE_AGE,
    TaxTargetSettings,
    YearTaxTarget,
    bracket_rate_in_schedule,
    bracket_target_top,
    largest_fitting,
    missing_bracket_target_warning,
    parse_tax_target,
    tax_measures,
    year_tax_target,
)
from coastmath.engine.types import (
    _TAXABLE_TYPES,
    _ZERO_GROWTH_TYPES,
    AccountInfo,
    CashFlowBreakdown,
    CharityData,
    DrawdownEntryData,
    EstateSettingsData,
    ExpenseData,
    HealthcareYear,
    IncomeComposition,
    IncomeData,
    LiabilityData,
    LiabilityState,
    NamedAmount,
    PlanData,
    PriorityData,
    RealAssetData,
    SimState,
    TaxResult,
    YearSnapshot,
    account_income_composition,
    account_investment_rates,
    reinvests_income,
)
from coastmath.engine.waterfall import (
    _CONTRIBUTION_DATA,
    ConversionTaxContext,
    ShortfallRequest,
    allocate_payroll_contributions,
    allocate_surplus,
    blend_source_eligible,
    early_withdrawal_penalty_rate,
    execute_drawdown,
    execute_gain_harvests,
    execute_roth_conversions,
    execute_transfers,
    fund_rule_shortfalls,
    penalty_free_by_separation,
    traditional_ira_deduction_limit,
)
from coastmath.engine.withdrawal_locks import (
    unresolved_lock_warnings,
    update_locked_accounts,
)
from coastmath.engine.withdrawal_strategy import (
    WithdrawalStrategySpec,
    WithdrawalStrategyState,
    strategy_spending,
)
from coastmath.schemas.simulation import (
    CashFlowBreakdownSchema,
    FiEstimate,
    HealthcareYearSchema,
    MilestoneOutcome,
    NamedAmountSchema,
    OpeningSnapshot,
    SimMetadata,
    SimulationResult,
    TransferFlowSchema,
)
from coastmath.schemas.simulation import (
    YearSnapshot as YearSnapshotSchema,
)

# Export/adoption capability marker, covered by calendar-step regression tests.
EXPENSE_INFLATION_CONVENTION = "expense_fixed_january_after_capture_year"


def get_assumption_rate(assumptions, key: str) -> float:
    """Return a fixed rate from AssumptionData by attribute name.

    Fixed rates apply when the plan defines no assumption curve.
    """
    return getattr(assumptions, key, 0.0)


def _rate_for_fraction(annual_rate: float, fraction: float) -> float:
    """Convert an effective annual rate to an effective partial-year rate."""
    fraction = max(0.0, min(1.0, fraction))
    if annual_rate <= -1.0:
        return annual_rate if fraction == 1.0 else -1.0 + (1.0 - fraction)
    return (1.0 + annual_rate) ** fraction - 1.0


def _withdrawal_factors(account: AccountInfo, price_rate: float, income_rate: float,
                        factor: Callable[[float], float]) -> tuple[float, float]:
    """Growth and income factors that money withdrawn during the year never earned.

    Opening-balance growth credits a full year on the whole balance, so each
    withdrawal removes ``amount * growth`` from the balance and reverses
    ``amount * income`` of recognized income. Reinvested income compounds
    with the price change. Paid-out income was credited to household cash
    instead; the share the withdrawn money never earned comes back out of
    the balance at cost (without compounding), so both settings follow one
    convention and the household keeps only the income its money earned.
    """
    income = factor(income_rate)
    if reinvests_income(account):
        return factor(price_rate + income_rate), income
    return factor(price_rate) + income, income


def _average_monthly_deposit_growth_factor(
    annual_rate: float,
    active_months: int,
) -> float:
    """Return growth on equal end-of-month deposits as a share of deposits.

    A yearly engine normally deposits the whole year's savings after market
    growth, which understates ending balances versus a monthly planner. This
    factor gives the exact future-value uplift for ``active_months`` equal
    deposits using the effective monthly rate implied by ``annual_rate``.
    """
    active_months = max(1, min(12, active_months))
    if annual_rate == 0.0 or active_months == 1:
        return 0.0
    monthly_rate = (1.0 + annual_rate) ** (1.0 / 12.0) - 1.0
    future_value_factor = sum(
        (1.0 + monthly_rate) ** months_remaining
        for months_remaining in range(active_months)
    ) / active_months
    return future_value_factor - 1.0


def _end_of_month_growth_factor(annual_rate: float, months: list[int]) -> float:
    """Average growth to the year's end on equal deposits at the end of ``months``.

    Month 12's deposit earns nothing this year; month 1's earns 11 months.
    """
    if not months or annual_rate == 0.0:
        return 0.0
    growth = max(0.0, 1.0 + annual_rate)
    return sum(growth ** ((12 - month) / 12) - 1.0 for month in months) / len(months)


def _active_months(start_ms, end_ms, triggered: set[str], newly_triggered: list[str], year: int,
                   birth_month: int | None, year_fraction: float) -> list[int]:
    """Calendar months (1-12) in which a milestone-bounded event is active.

    Same rules as ``prorate_for_year``, month by month, within the simulated
    part of the year.
    """
    def overlap(fraction: float) -> float:
        return prorate_for_year(start_ms, end_ms, None, None, triggered, newly_triggered,
                                year, birth_month, min(year_fraction, fraction))
    return [month for month in range(1, 13)
            if overlap((13 - month) / 12) - overlap((12 - month) / 12) > 1e-9]


def _price_and_income_rates(
    rates: tuple[float, float, float, float],
    composition: IncomeComposition,
    account_type: str,
) -> tuple[float, float, float]:
    """Annual price, stock dividend and bond income rates for one account.

    Bond income is carved out of the bond total return, so price plus both
    income rates always equals the account's total return.
    """
    stock_rate, bond_rate, allocation, dividend_rate = rates
    bond_income = composition.bond_income_rate(bond_rate)
    price_rate = allocation * (bond_rate - bond_income) + (1 - allocation) * stock_rate
    if account_type == "cryptocurrency":
        return price_rate, 0.0, 0.0
    return price_rate, (1 - allocation) * dividend_rate, allocation * bond_income


def _scheduled_growth_factor(annual_rate: float, event, milestone_map: dict,
                             triggered: set[str], newly_triggered: list[str],
                             year: int, birth_month: int | None,
                             year_fraction: float) -> float:
    """Weight end-of-month growth by an event's actual active months.

    Differences of trailing-year overlaps preserve the same milestone and
    partial-month convention used for the event's dollar amount.
    """
    def overlap(fraction):
        return prorate_for_year(
            milestone_map.get(event.start_milestone_id),
            milestone_map.get(event.end_milestone_id),
            event.start_month, event.end_month, triggered, newly_triggered,
            year, birth_month, min(year_fraction, fraction))

    total = overlap(1.0)
    if total <= 0:
        return 0.0
    return sum((overlap((13 - month) / 12) - overlap((12 - month) / 12))
               * (max(0.0, 1 + annual_rate) ** ((12 - month) / 12) - 1)
               for month in range(1, 13)) / total


def _fill_rules(priorities: list[PriorityData], funded_by_rank: dict[int, float],
                year_fraction: float, excluded_targets: frozenset[str] = frozenset()) -> list[PriorityData]:
    """Surplus contribution rules limited to what they still lack this year.

    Fixed-amount and remaining rules keep their rank; annual caps and fixed
    amounts are reduced by ``funded_by_rank``. Percentage rules, which refer
    to the year's surplus, are left out.
    """
    rules = []
    for priority in priorities:
        if priority.priority_type not in (None, "contribution") or priority.allocation_mode not in ("amount", "remaining"):
            continue
        if priority.target_account_id in excluded_targets:
            continue
        funded = funded_by_rank.get(priority.priority_rank, 0.0)
        cap = None if priority.max_annual_amount is None else max(0.0, priority.max_annual_amount - funded)
        value = priority.allocation_value
        if priority.allocation_mode == "amount":
            unfilled = max(0.0, (value or 0.0) * year_fraction - funded)
            value = unfilled / year_fraction if year_fraction > 0 else 0.0
        rules.append(replace(priority, max_annual_amount=cap, allocation_value=value, withdraw_if_short=False))
    return rules


def _sweep_excess_reserve_cash(plan_data: PlanData, state: SimState, cf_contributions: list[NamedAmount],
                               year_fraction: float, allocate) -> dict[int, float]:
    """Move reserve-account cash above the cash reserve into unmet allocation rules.

    Runs after the year's surplus, spending and withdraw-if-short draws. Cash in
    the reserve accounts beyond the protected amount (listed order, as for
    withdrawals) funds the surplus contribution rules in rank order, within
    their annual caps, fixed amounts and contribution limits, through
    ``allocate(amount, rules)``. Withdrawal-locked reserve accounts are not
    drawn, and a rule never pays into a reserve account. Moving cash is not
    a taxable event. The moves are recorded as transfers and stored in
    ``state.swept_reserve_cash`` (target -> amount). Returns rank -> amount.
    """
    state.swept_reserve_cash = {}
    reserve_ids = state.cash_reserve_accounts
    if not reserve_ids:
        return {}
    floors = reserve_floors({aid: state.get_balance(aid) for aid in reserve_ids},
                            reserve_ids, state.cash_reserve_target)
    excess = {aid: max(0.0, state.get_balance(aid) - floors.get(aid, 0.0))
              for aid in reserve_ids if aid not in state.locked_account_ids}
    available = sum(excess.values())
    if available <= 0.005:
        return {}
    funded: dict[int, float] = {}
    for flow in cf_contributions:
        if flow.source == "priority" and flow.priority_rank is not None:
            funded[flow.priority_rank] = funded.get(flow.priority_rank, 0.0) + flow.amount
    rules = _fill_rules(plan_data.priorities, funded, year_fraction, frozenset(reserve_ids))
    if not rules:
        return {}
    offset = len(state.allocation_flows)
    deposits = allocate(available, rules)
    swept_by_rank: dict[int, float] = {}
    for flow in state.allocation_flows[offset:]:
        if flow.amount > 0 and flow.priority_rank is not None:
            swept_by_rank[flow.priority_rank] = swept_by_rank.get(flow.priority_rank, 0.0) + flow.amount
    # These flows are reported as transfers, not as surplus allocations.
    del state.allocation_flows[offset:]
    sources = [[aid, amount] for aid, amount in excess.items() if amount > 0]
    for target_id, deposited in deposits.items():
        left = deposited
        for source in sources:
            if left <= 0:
                break
            take = min(left, source[1])
            if take <= 0:
                continue
            state.withdraw_from(source[0], take)
            state.record_transfer(source[0], target_id, take,
                                  state.accounts[source[0]].name or None,
                                  state.accounts[target_id].name or None)
            source[1] -= take
            left -= take
        state.swept_reserve_cash[target_id] = state.swept_reserve_cash.get(target_id, 0.0) + deposited
    return swept_by_rank


def _loan_occurrence(liab: LiabilityData, year: int, start_year: int, milestone_map: dict,
                     state: SimState, newly_triggered: list[str], birth_month: int | None) -> int | None:
    """The repeat number of a loan taken again in January of ``year``, if any.

    A loan with ``recurrence_years`` N is taken again every N years after the
    plan start (occurrence 1 in start + N, 2 in start + 2N, ...) on its
    original terms. No occurrence starts after ``recurrence_end_year`` or
    once the end milestone has been reached; a milestone reached later in
    January's year still allows that year's occurrence.
    """
    every = liab.recurrence_years
    elapsed = year - start_year
    if not every or every <= 0 or elapsed <= 0 or elapsed % every:
        return None
    if liab.recurrence_end_year is not None and year > liab.recurrence_end_year:
        return None
    end_id = liab.recurrence_end_milestone_id
    if end_id is not None and end_id in state.triggered_milestones:
        milestone = milestone_map.get(end_id)
        if end_id not in newly_triggered or milestone is None:
            return None
        if resolve_trigger_month(milestone, birth_month, year) <= 1:
            return None
    return elapsed // every


def _expense_amount_for_year(
    expense: ExpenseData,
    year: int,
    activation_year: int,
    inflation_factor: float,
    start_year: int | None = None,
) -> float:
    """Return an expense's full-year amount before intra-year proration.

    Amounts are stated in plan-start-year dollars. A custom growth rate
    compounds from the plan's start year (like inflation linking), so an
    expense that begins later is first carried forward to its start. The
    recurrence cadence still counts from the year the expense activates.
    """
    years_elapsed = max(0, year - activation_year)
    growth_years = max(0, year - (start_year if start_year is not None else activation_year))
    occurrence = 0
    if expense.recurrence_years is not None:
        if expense.recurrence_years <= 0:
            return 0.0
        if years_elapsed % expense.recurrence_years != 0:
            return 0.0
        occurrence = years_elapsed // expense.recurrence_years

    amount = expense.annual_amount
    if expense.growth_rate is not None:
        amount *= (1.0 + expense.growth_rate) ** growth_years
        if expense.growth_cap is not None:
            cap = expense.growth_cap
            if expense.growth_cap_inflation_linked:
                cap *= inflation_factor
            amount = min(amount, cap)
    elif expense.inflation_linked:
        amount *= inflation_factor

    if occurrence > 0 and expense.recurrence_growth_rate != 0.0:
        amount *= (1.0 + expense.recurrence_growth_rate) ** occurrence
    return amount


_RMD_ACCOUNT_TYPES = RMD_TYPES
# Contributions to these accounts are excluded from taxable income whether
# they arrive through payroll or from after-tax cash in the savings
# waterfall (deductible IRA, solo/self-directed 401(k), HSA), and 403(b),
# 457(b) and 401(a) deferrals likewise (IRC 402(a), 403(b)(1), 457(a)).
# A traditional IRA contribution is then limited to its deductible part by
# the workplace-plan phase-out in ``_compute_tax`` (IRC 219(g)).
_PRE_TAX_CONTRIBUTION_TYPES = PRE_TAX_CONTRIBUTION_TYPES
# PA DOR Personal Income Tax Guide, Gross Compensation: employee contributions
# to any retirement plan, including IRC 401 deferrals, are always taxable
# compensation; PA-40 has no IRA deduction, and self-employed retirement
# contributions are not a business expense. 403(b) and 457 deferrals are
# employee contributions too. Pennsylvania adds the federally
# excluded retirement contributions back. HSA and section 125 health amounts
# remain excluded, as they are federally.
_RETIREMENT_CONTRIBUTION_TYPES = TRADITIONAL_RETIREMENT_TYPES
_STATES_TAXING_RETIREMENT_CONTRIBUTIONS = frozenset({"PA"})
# NJ GIT-2 (IRA Withdrawals): the Gross Income Tax Act has no IRA deduction,
# so IRA contributions are taxed in the year made. NJ still excludes 401(k)
# deferrals (N.J.S.A. 54A:6-21). M.G.L. c.62 s.2(d)(1)(F) likewise disallows
# the IRC 219 deduction for Massachusetts; MA gross income follows federal
# gross income (s.2(a)), so 401(k) deferrals stay excluded there too. The
# taxed contributions are recovered on withdrawal (coastmath.engine.state_taxed_basis).
_STATES_TAXING_IRA_CONTRIBUTIONS = frozenset({"NJ", "MA"})
# NJ has no deferral provision for 403(b) or 457 plans: employee and employer
# 403(b) contributions and 457 deferrals are taxed in the year made (NJ
# Division of Taxation, "Treatment of Employer Post-Retirement Contributions
# to a Section 403(b) Plan", https://www.nj.gov/treasury/taxation/section403.shtml;
# "Retiring in New Jersey" guide). MA follows the federal exclusion for both.
# Employer 457(b) contributions keep the federal treatment (not confirmed).
_NJ_TAXED_DEFERRAL_TYPES = frozenset({"traditional_403b", "traditional_457b"})
_ORDINARY_DRAWDOWN_ACCOUNT_TYPES = TRADITIONAL_RETIREMENT_TYPES
# State a non-Roth, non-HSA drawdown can change; a tax-target trial
# withdrawal saves and restores these around its tax calculation.
_DRAWDOWN_TRIAL_FIELDS = (
    "capital_gains_this_year", "qualified_dividends_this_year", "ordinary_dividends_this_year",
    "treasury_interest_this_year", "municipal_interest_this_year",
    "state_exempt_municipal_interest_this_year", "other_bond_interest_this_year",
    "withdrawal_growth_adjustment", "drawdown_tax_withheld_this_year",
    "failure_year", "unfunded_expenses",
    # Indexed cost bases (coastmath.engine.intl_cost_base).
    "indexed_cost_bases", "capital_gain_split_this_year",
)
_QCD_ELIGIBLE_TYPES = frozenset({"traditional_ira"})
# States whose residents nearly all owe a local income tax: without a
# selection the projection omits it.
_LOCAL_TAX_STATE_PROMPTS = {
    "IN": "Indiana county income tax is not included. Select a county.",
    "MD": "Maryland county income tax is not included. Select a county or Baltimore City.",
    "PA": "Pennsylvania local earned income tax is not included. Select a locality or enter its rate.",
}
# 2026 QCD annual exclusion limit: $111,000 (SECURE 2.0 §307 inflation
# adjustment, indexed annually via CPI-U rounded to nearest $1,000).
# Rev. Proc. 2025-32; confirmed by IRS Pub. 590-B (2025 ed., 2026 worksheet).
_QCD_ANNUAL_CAP = 111_000.0

# Primary residence capital gains exclusion amounts
# IRC 121 / IRS Pub. 523: $250k single, $500k MFJ if ownership/use tests apply.
# https://www.irs.gov/publications/p523
_PRIMARY_EXCLUSION_SINGLE = 250_000.0
_PRIMARY_EXCLUSION_MARRIED = 500_000.0

# When selected accounts span types, the configured drawdown order supplies
# the type hierarchy by first occurrence. Types absent from that order use
# this deterministic fallback, followed by any unknown type names sorted
# lexicographically. Selection order remains authoritative within a type.
_SPECIFIC_FUNDING_TYPE_FALLBACK = (
    "checking", "savings", "taxable_brokerage", "cryptocurrency", "hsa",
    "traditional_ira", "traditional_401k", "traditional_403b", "traditional_457b", "traditional_401a",
    "roth_ira", "roth_401k", "roth_403b", "roth_457b",
    "five_twenty_nine", "other",
)


def _discretionary_amount(expense: ExpenseData, planned: float, paid: float) -> float | None:
    """The discretionary part of an expense's paid amount, for spending outputs.

    Only expenses with an explicit percent report a split; category-only
    expenses leave it None so their output stays as it was. ``planned`` is
    the amount before any flex cut and ``paid`` after it. The cut falls only
    on the discretionary part, so the essential part is ``planned * (1 - share)``.
    """
    if expense.discretionary_fraction is None:
        return None
    share = discretionary_share(expense) or 0.0
    return min(paid, max(0.0, paid - planned * (1.0 - share)))


def _expense_funding_ids(expense: ExpenseData) -> list[str]:
    """Return the ordered funding selection, preserving legacy scalar data."""
    if expense.specific_funding_source_ids is not None:
        return list(expense.specific_funding_source_ids)
    if expense.specific_funding_source_id is not None:
        return [expense.specific_funding_source_id]
    return []


def _ordered_specific_funding_ids(
    selected_ids: list[str], plan_data: PlanData,
) -> list[str]:
    """Apply global type precedence while keeping selected same-type order."""
    if len(selected_ids) < 2:
        return list(selected_ids)
    configured_types: list[str] = []
    for entry in sorted(plan_data.drawdown_order, key=lambda item: item.rank):
        account = plan_data.accounts.get(entry.source_account_id or "")
        if account is not None and account.account_type not in configured_types:
            configured_types.append(account.account_type)

    selected_types = {
        plan_data.accounts[account_id].account_type
        for account_id in selected_ids
        if account_id in plan_data.accounts
    }
    fallback_rank = {kind: index for index, kind in enumerate(_SPECIFIC_FUNDING_TYPE_FALLBACK)}
    missing_types = sorted(
        selected_types.difference(configured_types),
        key=lambda kind: (fallback_rank.get(kind, len(fallback_rank)), kind),
    )
    type_rank = {kind: index for index, kind in enumerate(configured_types + missing_types)}
    return [
        account_id
        for _, account_id in sorted(
            enumerate(selected_ids),
            key=lambda item: (
                type_rank.get(
                    plan_data.accounts[item[1]].account_type,
                    len(type_rank),
                ),
                item[0],
            ),
        )
    ]


def _stream_owner_shares(owner: str, plan_data: PlanData) -> tuple[tuple[str, float], ...]:
    """Split an income stream between people for per-person state exclusions.

    A joint stream is shared equally when the plan has a spouse; the data
    model records no other split.
    """
    if owner == "joint":
        return (("self", .5), ("spouse", .5)) if plan_data.spouse_birth_year is not None else (("self", 1.0),)
    return ((owner, 1.0),)


def _retirement_income(state: SimState, plan_data: PlanData, year: int) -> list[RetirementIncome]:
    """Each person's retirement income this year, with their year-end age.

    Accounts re-owned by a survivor count as the survivor's; opening
    year-to-date income has no category and is not included.
    """
    birth_years = {"self": plan_data.birth_year, "spouse": plan_data.spouse_birth_year}
    return [
        RetirementIncome(
            age=year - birth_years[owner] if birth_years.get(owner) is not None else None,
            amounts={source: amount for source, amount in by_source.items() if source != "social_security"},
            social_security=by_source.get("social_security", 0.0),
        )
        for owner, by_source in sorted(state.retirement_income_this_year.items())
    ]


def _record_waterfall_retirement_contribution(state: SimState, account_id: str, amount: float) -> None:
    """Note a surplus deposit into a traditional retirement account this year."""
    if amount:
        contributions = state.waterfall_retirement_contributions_this_year
        contributions[account_id] = contributions.get(account_id, 0.0) + amount


def _state_taxed_contributions_by_account(
    state_code: str | None,
    state: SimState,
    payroll_by_account: dict[str, float],
    nj_employer_403b_by_account: dict[str, float],
    ira_nondeductible: float,
) -> dict[str, float]:
    """This year's state contribution add-back, split by account.

    Mirrors the ``state_income_adjustment`` built in ``_compute_tax``: the
    totals by account sum to it. The federally nondeductible IRA part, which
    is not added back, is taken from the IRA accounts in proportion.
    """
    if state_code in _STATES_TAXING_RETIREMENT_CONTRIBUTIONS:
        payroll_types = waterfall_types = _RETIREMENT_CONTRIBUTION_TYPES
    elif state_code in _STATES_TAXING_IRA_CONTRIBUTIONS:
        waterfall_types = frozenset({"traditional_ira"})
        payroll_types = waterfall_types | (_NJ_TAXED_DEFERRAL_TYPES if state_code == "NJ" else frozenset())
    else:
        return {}
    added: dict[str, float] = {}
    for sources, types in ((payroll_by_account, payroll_types),
                           (state.waterfall_retirement_contributions_this_year, waterfall_types)):
        for account_id, amount in sources.items():
            account = state.accounts.get(account_id)
            if account is not None and account.account_type in types and amount > 0:
                added[account_id] = added.get(account_id, 0.0) + amount
    if state_code == "NJ":
        for account_id, amount in nj_employer_403b_by_account.items():
            if amount > 0:
                added[account_id] = added.get(account_id, 0.0) + amount
    ira_ids = [aid for aid in added if state.accounts[aid].account_type == "traditional_ira"]
    ira_total = sum(added[aid] for aid in ira_ids)
    if ira_nondeductible > 0 and ira_total > 0:
        scale = max(0.0, ira_total - ira_nondeductible) / ira_total
        for aid in ira_ids:
            added[aid] *= scale
    return added


def _ordinary_income_from_drawdowns(
    drawdowns: dict[str, float],
    state: SimState,
) -> float:
    """Return the taxable ordinary income created by account drawdowns.

    Pre-tax IRA/401(k) withdrawals are ordinary income under IRS Publication
    590-B, "Distributions from Individual Retirement Arrangements (IRAs)",
    and IRS Publication 575, "Pension and Annuity Income":
    https://www.irs.gov/publications/p590b
    https://www.irs.gov/publications/p575
    """
    total = 0.0
    for account_id, amount in drawdowns.items():
        acct = state.accounts.get(account_id)
        if acct is None or acct.account_type not in _ORDINARY_DRAWDOWN_ACCOUNT_TYPES:
            continue
        total += amount
        state.record_retirement_income(acct.owner, ACCOUNT_TYPE_SOURCES[acct.account_type], amount,
                                       account_id=account_id)
    return total


def _hsa_qualified_medical_costs(healthcare: HealthcareYear | None) -> tuple[float, float]:
    """Modeled costs an HSA can reimburse untaxed (IRC 223(d)(2); Pub. 969).

    Returns (all qualified costs, the Medicare premiums among them).
    Medicare premiums, out-of-pocket, itemized medical and net long-term care
    qualify. Marketplace premiums and Medigap premiums do not. Medicare
    premiums qualify only from an HSA whose owner is 65 or older, whoever is
    covered (223(d)(2)(C)(iv); Pub. 969, "Insurance premiums").
    """
    if healthcare is None:
        return 0.0, 0.0
    premiums = max(0.0, healthcare.medicare_part_a + healthcare.medicare_part_b
                   + healthcare.medicare_irmaa_part_b + healthcare.medicare_irmaa_part_d
                   + healthcare.medicare_part_d_plan)
    other = max(0.0, healthcare.out_of_pocket + healthcare.itemized_medical + healthcare.long_term_care)
    return premiums + other, premiums


def qcd_eligible(age: int | None, birth_month: int | None) -> bool:
    """IRC 408(d)(8)(B)(i): the IRA owner must have attained age 70 1/2 when
    the distribution is made. With annual granularity, a holder born in
    January-June reaches 70 1/2 during the year they turn 70; later births
    qualify the following year. Unknown age or month is treated conservatively.
    """
    if age is None:
        return True  # legacy callers without age information
    threshold = 70 if (birth_month or 7) <= 6 else 71
    return age >= threshold


def _qcd_eligible_owner_ids(
    state: SimState,
    age: int | None,
    birth_month: int | None,
    owners: set[str] | None = None,
) -> set[str]:
    """Return IRA owners who can make a QCD in the current year.

    The annual exclusion is an individual limit.  The simulation populates
    ``owner_ages`` and ``owner_birth_months`` for the holder and spouse; use
    those values rather than applying the tax return holder's age to every
    account.  Direct helper callers from older code may not populate these
    maps, so retain the historical holder-based fallback in that case.
    """
    if owners is None:
        owners = {
            acct.owner
            for acct in state.accounts.values()
            if acct.account_type in _QCD_ELIGIBLE_TYPES and acct.balance > 0
        }
    if not state.owner_ages:
        return owners if qcd_eligible(age, birth_month) else set()
    return {
        owner
        for owner in owners
        if owner in state.owner_ages
        if qcd_eligible(
            state.owner_ages[owner],
            state.owner_birth_months.get(owner),
        )
    }


def _process_qcds(
    state: SimState,
    charity_entities: list[CharityData],
    rmd_amount: float,
    triggered_milestones: set[str],
    qcd_cap: float = _QCD_ANNUAL_CAP,
    *,
    age: int | None = None,
    birth_month: int | None = None,
    rmd_by_owner: dict[str, float] | None = None,
    rmd_by_account: dict[str, float] | None = None,
) -> float:
    """Process Qualified Charitable Distributions from traditional IRAs.

    QCDs count toward the RMD but are NOT taxed as income.
    Capped at the inflation-adjusted annual limit and available IRA funds.
    Eligibility and the annual cap are applied per IRA owner.  The household
    charity request is allocated across eligible owners, using that owner's
    RMD first and then that owner's remaining traditional IRA balance.

    Returns the total QCD amount distributed.
    """
    # Filter to active QCD entities
    qcd_entities = [
        e for e in charity_entities
        if e.entity_type == "qcd"
        and is_event_active(e.start_milestone_id, e.end_milestone_id, triggered_milestones)
    ]
    if not qcd_entities:
        return 0.0

    bound_entities = [e for e in qcd_entities if e.source_account_id is not None]
    legacy_owner_mode = not state.owner_ages and rmd_by_owner is None
    if legacy_owner_mode and not qcd_eligible(age, birth_month):
        return 0.0

    eligible_owners = _qcd_eligible_owner_ids(
        state,
        age,
        birth_month,
        owners=(
            {
                acct.owner
                for acct in state.accounts.values()
                if acct.account_type in _QCD_ELIGIBLE_TYPES and acct.balance > 0
            }
            | set(rmd_by_owner or {})
        ),
    )
    if not eligible_owners and legacy_owner_mode and qcd_eligible(age, birth_month):
        # The legacy API may report an RMD that has already depleted the
        # account, leaving no positive balance from which to infer an owner.
        eligible_owners = {"self"}
    if not eligible_owners:
        return 0.0

    # Sum requested QCD amounts.  The cap is per eligible IRA owner, while
    # the charity request is a household amount with no owner assignment.
    total_requested = sum(e.annual_amount for e in qcd_entities)
    qcd_total = min(total_requested, qcd_cap * len(eligible_owners))

    # Preserve the old pooled-RMD behavior for direct callers that predate the
    # owner-aware simulation maps.  The simulation passes owner totals below.
    if legacy_owner_mode and not bound_entities:
        available_ira = sum(
            acct.balance for aid, acct in state.accounts.items()
            if acct.account_type in _QCD_ELIGIBLE_TYPES and acct.balance > 0
            and aid not in state.locked_account_ids
        )
        rmd_portion = min(qcd_total, max(0.0, rmd_amount))
        direct_portion = min(max(0.0, qcd_total - rmd_portion), available_ira)
        remaining = direct_portion
        for aid, acct in state.accounts.items():
            if remaining <= 0:
                break
            if acct.account_type not in _QCD_ELIGIBLE_TYPES or acct.balance <= 0 or aid in state.locked_account_ids:
                continue
            withdrawal = min(remaining, acct.balance)
            state.withdraw_from(aid, withdrawal)
            remaining -= withdrawal
        return rmd_portion + direct_portion - remaining

    # Allocate the household request in stable account order, enforcing each
    # eligible owner's annual limit and using only that owner's IRA balances.
    remaining_rmd = dict(rmd_by_owner or {})
    remaining_account_rmd = dict(rmd_by_account or {})
    owner_used: dict[str, float] = {}
    actual = 0.0
    # Explicit payers consume only their own account's RMD. In particular,
    # an own-IRA gift cannot exclude a separate inherited IRA distribution.
    for gift in bound_entities:
        aid = gift.source_account_id
        acct = state.accounts.get(aid)
        if acct is None or acct.account_type not in _QCD_ELIGIBLE_TYPES or acct.owner not in {"self", "spouse"}:
            raise ValueError("QCD source must be a traditional IRA in this plan.")
        if acct.owner not in eligible_owners:
            continue
        requested = min(max(0.0, gift.annual_amount), max(0.0, qcd_cap - owner_used.get(acct.owner, 0.0)))
        rmd_part = min(requested, max(0.0, remaining_account_rmd.get(aid, 0.0)))
        # A withdrawal-locked IRA gives only from its RMD.
        direct = 0.0 if aid in state.locked_account_ids else min(requested - rmd_part, max(0.0, acct.balance))
        state.withdraw_from(aid, direct)
        given = rmd_part + direct
        owner_used[acct.owner] = owner_used.get(acct.owner, 0.0) + given
        remaining_account_rmd[aid] = remaining_account_rmd.get(aid, 0.0) - rmd_part
        remaining_rmd[acct.owner] = max(0.0, remaining_rmd.get(acct.owner, 0.0) - rmd_part)
        actual += given

    remaining_request = sum(e.annual_amount for e in qcd_entities if e.source_account_id is None)
    owner_order: list[str] = []
    for acct in state.accounts.values():
        if acct.owner in eligible_owners and acct.owner not in owner_order:
            owner_order.append(acct.owner)
    for owner in (rmd_by_owner or {}):
        if owner in eligible_owners and owner not in owner_order:
            owner_order.append(owner)
    for owner in owner_order:
        if remaining_request <= 0:
            break
        owner_request = min(remaining_request, max(0.0, qcd_cap - owner_used.get(owner, 0.0)))
        rmd_portion = min(owner_request, max(0.0, remaining_rmd.get(owner, 0.0)))
        direct_remaining = owner_request - rmd_portion
        owner_actual = rmd_portion
        if direct_remaining > 0:
            for aid, acct in state.accounts.items():
                if direct_remaining <= 0:
                    break
                if (
                    acct.owner != owner
                    or acct.account_type not in _QCD_ELIGIBLE_TYPES
                    or acct.balance <= 0
                    or aid in state.locked_account_ids
                ):
                    continue
                direct = min(direct_remaining, acct.balance)
                state.withdraw_from(aid, direct)
                direct_remaining -= direct
                owner_actual += direct
        remaining_request -= owner_actual
        actual += owner_actual
    return actual


def _sell_real_asset(
    state: SimState,
    plan_data: PlanData,
    asset: RealAssetData,
    sale_month: int = 12,
) -> None:
    """Recognize the sale, repay secured debt, and conserve the cash proceeds.

    Selling costs reduce the amount realized and the cash received. A rental
    property's gain is first unrecaptured section 1250 gain up to the
    depreciation taken; a net loss on it is an ordinary section 1231 loss.
    """
    sale_price = state.get_real_asset_value(asset.id)
    selling_costs = sale_price * min(1.0, max(0.0, asset.selling_cost_rate))
    amount_realized = sale_price - selling_costs
    basis = state.real_asset_basis.get(asset.id)
    if basis is None:
        basis = asset.adjusted_basis if asset.adjusted_basis is not None else asset.current_value
    depreciation = state.real_estate_depreciation.get(asset.id, 0.0)
    gain = amount_realized - (basis - depreciation)

    def home_sale_exclusion() -> float:
        status = state.current_filing_status or plan_data.filing_status
        purchase = state.real_asset_purchase_dates.get(asset.id)
        test = real_estate.section_121_test(asset, state.year, sale_month, purchase)
        if test is None:
            state.real_estate_warnings.add(
                f"{asset.name}: the home sale exclusion assumes the 2-of-5-year ownership and use test "
                "is met. Enter when you bought and moved into the home to check it.")
        if test is not False:
            return real_estate.home_sale_exclusion_amount(status)
        state.real_estate_warnings.add(
            f"{state.year}: {asset.name} was owned or used as the main home for less than 2 of the "
            "5 years before the sale, so no home sale exclusion applies. Reduced exclusions for "
            "work, health or unforeseen moves are not modeled.")
        return 0.0

    if real_estate.is_rental(asset):
        # A mixed-use property splits the gain by its average rental share
        # over the ownership period (IRC 121(b)(5) use-ratio approximation).
        rental_share = 1.0
        if real_estate.is_mixed_use(asset):
            owned_from = ((asset.owned_since_year, asset.owned_since_month or 1)
                          if asset.owned_since_year is not None
                          else state.real_asset_purchase_dates.get(asset.id)
                          or (plan_data.start_year, round(12 * (1.0 - plan_data.first_year_fraction)) + 1))
            rental_share = real_estate.sale_rental_share(asset, state.year, sale_month, owned_from)
        if gain >= 0:
            prior = 0.0 if asset.id in state.real_asset_purchase_dates else max(0.0, asset.prior_depreciation)
            # Gain up to the depreciation taken is always taxed, even on a
            # home (IRC 121(d)(6)).
            recapture = min(gain, prior + depreciation)
            state.unrecaptured_1250_this_year += recapture
            if asset.is_primary_residence and rental_share < 1.0:
                personal_gain = (gain - recapture) * (1.0 - rental_share)
                gain -= min(personal_gain, home_sale_exclusion())
        else:
            # IRC 1231(a)(2): a net loss on rental real property is ordinary.
            # The personal-use share of a loss is not deductible.
            state.real_estate_ordinary_loss_this_year -= gain * rental_share
            gain = 0.0
        state.disposed_rentals_this_year.add(asset.id)
    elif asset.is_primary_residence:
        # Losses on a personal residence are not deductible.
        gain = max(0.0, gain - home_sale_exclusion())
    elif asset.tax_treatment != "investment":
        # IRS Publication 550: personal-use sale gains are taxable, losses
        # are not deductible. Legacy unclassified assets use this conservative
        # treatment with a review warning, never an assumed investment loss.
        gain = max(0.0, gain)
    state.capital_gains_this_year += gain
    state.real_estate_gains_this_year += gain
    intl_cost_base.record_real_asset_sale(state, asset.id, gain, asset.is_primary_residence)
    proceeds = amount_realized
    for liab in plan_data.liabilities:
        if liab.linked_asset_id == asset.id:
            liability = state.liability_states.get(liab.id)
            if liability is not None:
                payoff = min(proceeds, liability.remaining_balance + liability.accrued_interest)
                # Unpaid simple interest is settled before principal.
                interest_part = min(payoff, liability.accrued_interest)
                liability.accrued_interest -= interest_part
                liability.remaining_balance -= payoff - interest_part
                proceeds -= payoff
    destination = asset.liquidation_target_account_id
    if destination not in state.accounts:
        destination = state.cash_account()
    state.deposit_to(destination, proceeds)
    state.remove_real_asset(asset.id)


# IRS Pub. 526: cash contributions to qualifying public charities are generally
# deductible up to 60% of AGI, with 5-year carryforward for excess amounts.
# https://www.irs.gov/publications/p526
_DAF_CARRYFORWARD_YEARS = 5


@dataclass
class CharitableResult:
    """Result of charitable contribution processing.

    Carryovers follow contribution limits regardless of the deduction election.
    """
    allowable_deduction: float = 0.0
    committed_carryforward: list[tuple[int, float]] = field(default_factory=list)
    preserved_carryforward: list[tuple[int, float]] = field(default_factory=list)  # legacy alias
    direct_cash_contributions: float = 0.0  # eligible for the non-itemizer deduction
    # Per-entity outflows: (entity_name, amount_withdrawn) for cash-flow reporting.
    entity_outflows: list[tuple[str, float]] = field(default_factory=list)
    account_withdrawals: dict[str, float] = field(default_factory=dict)
    # Brokerage shares reserved for gifts but not sold yet (``defer_sales``):
    # the year's surplus pays them first; only a deficit sells the shares.
    deferred_sales: dict[str, float] = field(default_factory=dict)
    total_contributions: float = 0.0
    daf_contributions: float = 0.0
    prior_carryforward: list[tuple[int, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Gifts of appreciated shares (capital gain property, 30% limit): this
    # year's market value given, unexpired carryovers, and the carryovers
    # left after this year's limit.
    property_contributions: float = 0.0
    prior_property_carryforward: list[tuple[int, float]] = field(default_factory=list)
    committed_property_carryforward: list[tuple[int, float]] = field(default_factory=list)


def _process_charitable_contributions(
    state: SimState,
    plan_data: PlanData,
    gross_income: float,
    newly_triggered: set[str],
    ss_income: float = 0.0,
    rmd_total: float = 0.0,
    defer_sales: bool = False,
) -> CharitableResult:
    """Process DAF and direct charitable contributions for the current year.

    - Deducts contribution amounts from checking, savings, then brokerage.
      With ``defer_sales`` the brokerage part is only reserved
      (``deferred_sales``), so a year whose income covers the gift realizes
      no gain; the simulator sells the shares only to fund a deficit.
    - Gifts funded with appreciated shares leave their taxable account at
      market value with a pro-rata share of its basis, so the gain is never
      realized. The engine tracks one average basis per account, so this
      stands in for choosing the highest-gain lots. A shortfall is paid in
      cash like other gifts.
    - Computes the allowable charitable deduction (capped at 60% of AGI;
      shares at 30%).
    - For DAFs, computes the excess remaining after contribution limits.
    - Does NOT mutate ``state.daf_carryforward``; the caller commits.
    """
    # --- Expire old carry-forward entries (older than 5 years) ---
    unexpired: list[tuple[int, float]] = [
        (yr, amt) for yr, amt in state.daf_carryforward
        if state.year - yr <= _DAF_CARRYFORWARD_YEARS
    ]
    unexpired_property: list[tuple[int, float]] = [
        (yr, amt) for yr, amt in state.capital_gain_gift_carryforward
        if state.year - yr <= _DAF_CARRYFORWARD_YEARS
    ]
    property_contributions = 0.0

    # --- Collect active DAF/direct charity entities ---
    total_contributions = 0.0
    direct_contributions = 0.0
    daf_contributions = 0.0
    entity_outflows: list[tuple[str, float]] = []
    account_withdrawals: dict[str, float] = {}
    deferred_sales: dict[str, float] = {}
    warnings: list[str] = []
    funding_rank = {"checking": 0, "savings": 1, "taxable_brokerage": 2}
    funding_accounts = sorted(state.accounts.items(), key=lambda item: funding_rank.get(item[1].account_type, 3))
    for ce in plan_data.charity_entities:
        if ce.entity_type not in ("daf", "direct"):
            continue
        if not is_event_active(
            ce.start_milestone_id, ce.end_milestone_id, state.triggered_milestones,
        ):
            continue

        amount = ce.annual_amount
        deducted = 0.0
        if ce.funding == "appreciated_shares":
            source = state.accounts.get(ce.source_account_id or "")
            if (source is not None and source.account_type in _TAXABLE_TYPES
                    and ce.source_account_id not in state.locked_account_ids and source.balance > 0):
                shares = min(amount, source.balance)
                basis = source.cost_basis if source.cost_basis is not None else source.balance
                source.cost_basis = max(0.0, basis * (1.0 - shares / source.balance))
                intl_cost_base.record_disposal(state, ce.source_account_id, shares / source.balance)
                source.balance -= shares
                account_withdrawals[ce.source_account_id] = (
                    account_withdrawals.get(ce.source_account_id, 0.0) + shares)
                property_contributions += shares
                deducted = shares
            if deducted < amount:
                warnings.append(f"{state.year}: Charitable gift '{ce.name}' gave ${deducted:,.2f} of shares; "
                                "the rest is paid in cash because the source account was short or unavailable.")
        shares_given = deducted

        # Use cash before selling investments, independent of account insertion order.
        for aid, acct in funding_accounts:
            if acct.account_type in funding_rank and aid not in state.locked_account_ids:
                available = max(0.0, acct.balance) - deferred_sales.get(aid, 0.0)
                take = min(amount - deducted, available)
                if take > 0:
                    if defer_sales and acct.account_type == "taxable_brokerage":
                        deferred_sales[aid] = deferred_sales.get(aid, 0.0) + take
                    else:
                        state.withdraw_from(aid, take)
                        account_withdrawals[aid] = account_withdrawals.get(aid, 0.0) + take
                    deducted += take
                if deducted >= amount:
                    break

        if deducted < amount:
            warnings.append(f"{state.year}: Charitable gift '{ce.name}' funded ${deducted:,.2f} of ${amount:,.2f}; insufficient checking, savings and brokerage balances.")
        cash_given = deducted - shares_given
        total_contributions += cash_given
        if ce.entity_type == "direct":
            direct_contributions += cash_given
        elif ce.entity_type == "daf":
            daf_contributions += cash_given
        if deducted > 0:
            entity_outflows.append((ce.name, deducted))

    result = CharitableResult(
        total_contributions=total_contributions,
        daf_contributions=daf_contributions,
        prior_carryforward=sorted(unexpired),
        entity_outflows=entity_outflows,
        account_withdrawals=account_withdrawals,
        deferred_sales=deferred_sales,
        direct_cash_contributions=direct_contributions,
        warnings=warnings,
        property_contributions=property_contributions,
        prior_property_carryforward=sorted(unexpired_property),
    )
    # Legacy helper callers may supply an estimate. The simulator recomputes
    # this limit from final tax AGI, after all withdrawals and conversions.
    return _limit_charitable_deduction(result, gross_income + ss_income + rmd_total, state.year)


def _limit_charitable_deduction(result: CharitableResult, agi: float, year: int) -> CharitableResult:
    """Apply the cash-gift limit without re-funding gifts or mutating history.

    Pub. 526: current gifts use the limit first; prior carryovers then use
    remaining room, oldest first, retaining their original expiration dates.
    The existing DAF-only carryforward contract is retained.
    """
    # Pub. 526: appreciated shares (30% limit) first, current year before
    # carryovers; cash then uses 60% of AGI less the shares allowed.
    property_room = capital_gain_property_charitable_limit(float("inf"), agi)
    property_current = min(result.property_contributions, property_room)
    property_room -= property_current
    property_used = property_current
    committed_property = []
    for yr, amount in sorted(result.prior_property_carryforward):
        used = min(amount, property_room)
        property_room -= used
        property_used += used
        if amount > used:
            committed_property.append((yr, amount - used))
    if result.property_contributions > property_current:
        committed_property.append((year, result.property_contributions - property_current))
    limit = max(0.0, cash_charitable_limit(agi) - property_used)
    current_used = min(result.total_contributions, limit)
    room = limit - current_used
    committed = []
    carry_used = 0.0
    for yr, amount in sorted(result.prior_carryforward):
        used = min(amount, room)
        room -= used
        carry_used += used
        if amount > used:
            committed.append((yr, amount - used))
    if result.total_contributions > 0:
        daf_excess = (result.total_contributions - current_used) * result.daf_contributions / result.total_contributions
        if daf_excess > 0:
            committed.append((year, daf_excess))
    # IRS IRM 4.19.15.21.4.2: a standard-deduction year still consumes
    # carryover room. The election never banks the full current-year gift.
    return replace(result, allowable_deduction=current_used + carry_used + property_used,
        committed_carryforward=committed, preserved_carryforward=list(committed),
        committed_property_carryforward=committed_property)


def _compute_healthcare_year(
    state: SimState,
    plan_data: PlanData,
    *,
    year: int,
    start_year: int,
    age: int,
    year_fraction: float,
    filing_status: str,
    agi: float,
    nontaxable_ss: float,
    aca_active: bool,
    aca_magi_estimate: float | None = None,
    aca_months: frozenset[int] | None = None,
) -> tuple[HealthcareYear | None, list[str]]:
    """Return the year's health coverage costs and any warnings.

    ACA premiums apply to adults under 65 in the months (1-12) of
    ``aca_months`` inside the ACA period; ``None`` means every month while
    ``aca_active``. Medicare applies from 65 (prorated by the holder's birth
    month in the enrolment year). MAGI for the credit is AGI plus non-taxable
    Social Security; IRMAA uses MAGI from two years earlier.
    """
    settings = parse_healthcare_settings(plan_data.healthcare_settings)
    if not settings.enabled:
        return None, []
    warnings: list[str] = []
    years_elapsed = year - start_year
    if settings.medical_inflation_rate is not None:
        medical_factor = (1.0 + settings.medical_inflation_rate) ** years_elapsed
    else:
        medical_factor = state.inflation_factor
    hc = HealthcareYear()
    profiles = person_profiles(plan_data, state, year)
    by_owner = {profile["owner"]: profile for profile in profiles}
    spouse_alive = "spouse" in by_owner and by_owner["spouse"]["alive_until"] > 0

    # ---- ACA marketplace coverage ----
    if settings.aca_enabled and aca_active and settings.aca_plan_premium_annual > 0:
        cover_self = aca_participates(settings, "self")
        cover_spouse = settings.aca_cover_spouse and aca_participates(settings, "spouse")
        covered = {"self": cover_self, "spouse": cover_spouse}
        # The entered premiums price the covered adults still under 65 when
        # the plan starts. Someone already on Medicare then is not in them.
        first_fraction = max(0.0, min(1.0, plan_data.first_year_fraction))
        start_month = next((m for m in range(1, 13) if m / 12 > 1 - first_fraction), 1)
        adults_at_start = [profile["age"] - (year - start_year) for profile in profiles
            if covered[profile["owner"]] and (not lifecycle.enabled(plan_data)
                or lifecycle.owner_alive_until(plan_data, state, profile["owner"], start_year) > 0)
            and (profile["age"] - (year - start_year) < 65
                 or profile["age"] - (year - start_year) == 65 and start_month < profile["birth_month"])]
        candidates = [(profile["age"], profile["birth_month"], profile["alive_until"])
            for profile in profiles if covered[profile["owner"]]]
        covered_ages = []
        periods = []
        for month in range(1, 13):
            if aca_months is not None and month not in aca_months:
                continue
            duration = max(0.0, month / 12 - max((month - 1) / 12, 1 - year_fraction))
            active_ages = [min(a, 64) for a, birthday, alive_until in candidates
                if (a < 65 or (a == 65 and month < birthday)) and month / 12 <= alive_until]
            if not active_ages or duration <= 0:
                continue
            if len(active_ages) > len(covered_ages):
                covered_ages = active_ages
            if settings.aca_apply_age_curve:
                base = sum(age_curve_factor(a) for a in adults_at_start) or 1.0
                scale = sum(age_curve_factor(a) for a in active_ages) / base
            else:
                scale = len(active_ages) / max(1, len(adults_at_start))
            periods.append((settings.aca_benchmark_premium_annual * scale * medical_factor,
                settings.aca_plan_premium_annual * scale * medical_factor, duration))
        if covered_ages:
            hc.aca_coverage_periods = periods
            benchmark = sum(b * f for b, _, f in periods)
            gross = sum(g * f for _, g, f in periods)
            # Form 8962 uses the annual tax family even when coverage ends
            # during the year. A deceased spouse remains on the joint return
            # for the death year; coverage above still stops by month.
            spouse_in_tax_family = spouse_alive or (
                state.partner_death_year == year and filing_status == "married_filing_jointly"
            )
            primary_in_tax_family = by_owner["self"]["alive_until"] > 0 or (
                lifecycle.enabled(plan_data) and lifecycle.death_year(plan_data, "self") == year
                and filing_status == "married_filing_jointly")
            household = int(primary_in_tax_family) + int(spouse_in_tax_family) + max(0, settings.aca_dependents)
            # Advance credit: like the marketplace, estimate income before the
            # year's withdrawals are known; the final credit is reconciled with
            # the tax settlement once post-withdrawal MAGI is available.
            magi = aca_magi_estimate if aca_magi_estimate is not None else agi + nontaxable_ss
            aca = calculate_premium_tax_credit(
                magi, household, benchmark, gross, covered_adults=len(covered_ages),
                state_group=settings.aca_state_group, inflation_factor=state.coverage_inflation_factor,
                coverage_periods=hc.aca_coverage_periods, filing_status=filing_status,
            )
            hc.aca_covered_adults = aca.covered_adults
            hc.aca_household_size = aca.household_size
            hc.aca_magi = aca.magi
            hc.aca_fpl_ratio = aca.fpl_ratio
            hc.aca_applicable_percentage = aca.applicable_percentage
            hc.aca_benchmark_premium = aca.benchmark_premium
            hc.aca_gross_premium = aca.gross_premium
            hc.aca_credit = aca.credit
            # Keep the coverage-year cash premium separate from the final
            # tax-return net premium. The marketplace advances only the
            # configured fraction of the estimated credit; the remaining
            # allowed credit is reconciled after final MAGI is known.
            hc.aca_credit_advanced = settings.aca_advance_credit_fraction * aca.credit
            hc.aca_cash_premium = hc.aca_gross_premium - hc.aca_credit_advanced
            hc.aca_net_premium = hc.aca_cash_premium
            hc.aca_eligible = aca.eligible
            hc.aca_reason = aca.reason
            hc.aca_magi_estimate = magi

    # ---- Medicare ----
    lived_apart = bool((plan_data.tax_settings or {}).get("mfs_lived_apart_all_year", False))
    if settings.persons:
        lookback_year = year - 2
        source = "history"
        if lookback_year in state.magi_history:
            magi_lb = state.magi_history[lookback_year]
        elif lookback_year == start_year - 1 and settings.magi_prior_year is not None:
            magi_lb, source = settings.magi_prior_year, "seed"
        elif lookback_year == start_year - 2 and settings.magi_two_years_prior is not None:
            magi_lb, source = settings.magi_two_years_prior, "seed"
        else:
            magi_lb, source = agi, "proxy"
        filing_lb = lookback_filing_status(settings, state, lookback_year, start_year, filing_status)
        warnings.extend(add_person_costs(hc, settings,
            profiles, year=year, start_year=start_year,
            year_fraction=year_fraction, filing_status=filing_lb, magi=magi_lb,
            inflation_factor=state.coverage_inflation_factor, medical_factor=medical_factor,
            mfs_lived_apart_all_year=lived_apart))
        if hc.medicare_persons:
            hc.medicare_magi_used = magi_lb
            hc.medicare_lookback_year = lookback_year
            hc.medicare_lookback_source = source
            hc.medicare_lookback_filing_status = filing_lb
            if source == "proxy":
                warnings.append("IRMAA for the first projection years uses current income because prior-year MAGI was not provided; enter it under Health coverage for accuracy.")
    elif settings.medicare_enabled:
        persons = 0.0
        enrollments = [(profile["age"], profile["birth_month"], profile["alive_until"])
            for profile in profiles]
        for person_age, birthday, alive_until in enrollments:
            if person_age >= 65:
                start = (birthday - 1) / 12 if person_age == 65 else 0.0
                persons += max(0.0, alive_until - max(start, 1 - year_fraction))
        if persons > 0:
            lookback_year = year - 2
            source = "history"
            if lookback_year in state.magi_history:
                magi_lb = state.magi_history[lookback_year]
            elif lookback_year == start_year - 1 and settings.magi_prior_year is not None:
                magi_lb, source = settings.magi_prior_year, "seed"
            elif lookback_year == start_year - 2 and settings.magi_two_years_prior is not None:
                magi_lb, source = settings.magi_two_years_prior, "seed"
            else:
                magi_lb, source = agi, "proxy"
                warnings.append("IRMAA for the first projection years uses current income because prior-year MAGI was not provided; enter it under Health coverage for accuracy.")
            filing_lb = lookback_filing_status(settings, state, lookback_year, start_year, filing_status)
            med = calculate_medicare_premiums(
                magi_lb, filing_lb, persons, settings,
                year=year, inflation_factor=state.coverage_inflation_factor, medical_factor=medical_factor,
                statutory_medical_factor=medicare_cost_factor(
                    year, settings.medical_inflation_rate, state.coverage_inflation_factor),
                mfs_lived_apart_all_year=lived_apart,
            )
            hc.medicare_persons = persons
            hc.medicare_magi_used = magi_lb
            hc.medicare_lookback_year = lookback_year
            hc.medicare_lookback_source = source
            hc.medicare_lookback_filing_status = filing_lb
            hc.medicare_tier = med.tier_index
            hc.medicare_part_b = med.part_b_standard
            hc.medicare_irmaa_part_b = med.part_b_irmaa
            hc.medicare_irmaa_part_d = med.part_d_irmaa
            hc.medicare_part_d_plan = med.part_d_plan
            hc.medicare_supplement = med.supplement

    hc.total = medical_total(hc)
    return hc, warnings


# Account types where step-up in basis applies (taxable accounts only)
_STEP_UP_TYPES = _TAXABLE_TYPES


def _handle_partner_death(
    state: SimState,
    plan_data: PlanData,
    year: int | None = None,
) -> None:
    """Handle partner death: filing status change, step-up in basis, account inheritance.

    Called once in the year the partner's life expectancy is reached.
    """
    estate = plan_data.estate_settings or EstateSettingsData()

    # Filing status changes in the following tax year. A final joint return
    # remains eligible in the death year; this model has no remarriage event.
    # IRS Publication 501, "Death of spouse": https://www.irs.gov/publications/p501

    # 2. Step-up in basis on inherited accounts
    if estate.step_up_basis_on_death:
        for acct in state.accounts.values():
            if acct.owner == "spouse" and acct.account_type in _STEP_UP_TYPES:
                acct.cost_basis = acct.balance

    # Joint taxable accounts (opt-in): the decedent's half, or both halves in
    # a community property state.
    step_up_joint_accounts(state, estate, resolve_state_for_year(
        year if year is not None else state.year, state.triggered_milestones, plan_data))

    # 3. Account inheritance — spouse-owned accounts transfer to survivor
    for aid, acct in state.accounts.items():
        if acct.owner == "spouse":
            acct.owner = "self"
            state.partner_reowned_account_ids.add(aid)
    # Joint accounts remain as-is (owner stays "joint")

    state.partner_deceased = True
    state.partner_death_year = year

    # Legacy mode does not elect survivor Social Security. The separate opt-in
    # policy validates claimed-benefit/owner/eligibility evidence.


def _impute_pro_rata_year_to_date(
    plan_data: PlanData,
    milestone_map: dict,
    triggered: set[str],
    newly_triggered: list[str],
    year: int,
    year_fraction: float,
    stream_active_until: dict[str, float],
) -> dict:
    """Pre-start share of the opening year's income streams as year-to-date history.

    A mid-year start without ``tax_settings.year_to_date`` is
    taxed on the full calendar year. Each stream's share of the months before
    the start date (its active window less the simulated window, so a job that
    begins or ends mid-year is not overstated) is imputed in start-year
    dollars; the opening year's growth factors are 1.0. Contributions,
    withdrawals and deductions before the start are not imputed. Returns ``{}``
    when nothing was earned before the start.
    """
    by_owner: dict[str, dict[str, float]] = {"w2_income_by_owner": {}, "self_employment_income_by_owner": {}}
    by_income_id: dict[str, float] = {}
    gross = social_security = investment = 0.0
    for inc in plan_data.income_streams:
        if inc.tax_category == "nontaxable" or inc.pension_formula:
            continue
        def share(
            simulation_fraction: float,
            active_from: float = 0.0,
            active_to: float = 1.0,
            inc=inc,
        ) -> float:
            return prorate_for_year(
                start_ms=milestone_map.get(inc.start_milestone_id) if inc.start_milestone_id else None,
                end_ms=milestone_map.get(inc.end_milestone_id) if inc.end_milestone_id else None,
                start_month=inc.start_month,
                end_month=inc.end_month,
                triggered=triggered,
                newly_triggered=newly_triggered,
                year=year,
                birth_month=plan_data.birth_month,
                simulation_fraction=simulation_fraction,
                active_until=min(active_to, stream_active_until.get(inc.id, 1.0)),
                active_from=active_from,
            )
        if inc.pay_interruption is None:
            pre_start = share(1.0) - share(year_fraction)
        else:
            pause_start, resume_at, multiplier = inc.pay_interruption

            def paid_share(simulation_fraction: float, pause_start=pause_start, resume_at=resume_at,
                           multiplier=multiplier) -> float:
                return (
                    share(simulation_fraction, active_to=pause_start - year)
                    + multiplier * share(simulation_fraction, active_from=resume_at - year)
                )

            pre_start = paid_share(1.0) - paid_share(year_fraction)
        if inc.frequency == "once":
            first_year = plan_data.start_year
            if inc.start_milestone_id:
                ms = milestone_map.get(inc.start_milestone_id)
                first_year = (int(ms.trigger_date[:4]) if ms and ms.trigger_type == "date" and ms.trigger_date
                              else year if inc.start_milestone_id in newly_triggered else None)
            payment_month = inc.start_month or (
                resolve_trigger_month(milestone_map[inc.start_milestone_id], plan_data.birth_month, year)
                if inc.start_milestone_id in milestone_map else 1)
            pre_start = float(first_year == year and inc.is_active and
                              (payment_month - 1) / 12 < 1 - year_fraction and share(1.0) > 0)
        if pre_start <= 1e-9:
            continue
        annual = inc.annual_amount if inc.growth_cap is None else min(inc.annual_amount, inc.growth_cap)
        if inc.frequency == "once" and inc.pay_interruption is not None:
            pause_start, resume_at, multiplier = inc.pay_interruption
            position = year + (payment_month - 1) / 12
            annual *= 0.0 if pause_start <= position < resume_at else multiplier if position >= resume_at else 1.0
        amount = annual * pre_start
        by_income_id[inc.id] = amount
        if inc.is_social_security:
            social_security += amount
            continue
        gross += amount
        if inc.is_earned_income:
            key = "self_employment_income_by_owner" if inc.is_self_employed else "w2_income_by_owner"
            by_owner[key][inc.owner] = by_owner[key].get(inc.owner, 0.0) + amount
        elif inc.tax_category not in {"qualified_pension", "other_ordinary"}:
            investment += amount
    if gross <= 0 and social_security <= 0:
        return {}
    return {
        "tax_year": year,
        "gross_income": gross,
        "social_security_income": social_security,
        "net_investment_income": investment,
        "_pre_start_income_by_id": by_income_id,
        **{key: owners for key, owners in by_owner.items() if owners},
    }


def inherited_history_note(name: str, settings: Mapping[str, Any]) -> str:
    """One sentence naming the assumptions an inherited traditional account's missing history forces."""
    assumed = []
    if settings.get("decedent_died_after_rbd") is None:
        assumed.append("death before the required beginning date")
    if settings.get("decedent_birth_year") is None:
        assumed.append("no original-owner birth year")
    return f"{name}: inherited RMDs assume {' and '.join(assumed)}."


def property_sale_note(asset: Any, *, purchased: bool) -> str | None:
    """One sentence per sold property: a missing basis and an unspecified tax treatment together."""
    if asset.sale_year is None and not asset.auto_liquidate_on_depletion:
        return None
    missing_basis = asset.adjusted_basis is None and not purchased
    no_loss = asset.tax_treatment == "unspecified" and not asset.is_primary_residence
    if missing_basis and no_loss:
        return f"{asset.name} sale: basis is today's value; a loss isn't deducted without investment treatment."
    if missing_basis:
        return f"{asset.name} sale: basis is today's value."
    if no_loss:
        return f"{asset.name} sale: a loss isn't deducted without investment treatment."
    return None


# ---------------------------------------------------------------------------
# Steps of run_simulation's year loop, in the order the loop runs them, then
# the end-of-plan result assembly.
# ---------------------------------------------------------------------------


def _opening_state(plan_data: PlanData, start_year: int, purchase_positions: Mapping[str, Any]) -> SimState:
    """Mutable simulation state built from the plan's opening accounts, assets and loans."""
    return SimState(
        year=start_year,
        accounts={
            aid: AccountInfo(
                balance=acct.balance,
                account_type=acct.account_type,
                name=acct.name,
                cost_basis=acct.cost_basis if acct.cost_basis is not None else acct.balance,
                inherited_year=acct.inherited_year,
                inheritance_settings=acct.inheritance_settings,
                roth_settings=({**(acct.roth_settings or {}),
                    "first_contribution_year": (acct.roth_settings or {}).get("first_contribution_year") or min(
                        (c["year"] for c in (acct.roth_settings or {}).get("conversions", [])),
                        default=start_year if acct.balance > 0 else None)}
                    if acct.account_type in ROTH_TYPES else None),
                investment_settings=acct.investment_settings,
                withdrawal_lock=acct.withdrawal_lock,
                distribution_settings=acct.distribution_settings,
                owner=acct.owner,
                beneficiary_type=acct.beneficiary_type,
                intl_account_kind=acct.intl_account_kind,
                include_in_liquid=acct.include_in_liquid,
            )
            for aid, acct in plan_data.accounts.items()
        },
        real_asset_values={
            asset.id: asset.current_value
            for asset in plan_data.real_assets
            if asset.id not in purchase_positions
        },
        pending_purchase_values={
            asset.id: max(0.0, asset.purchase_price or asset.current_value)
            for asset in plan_data.real_assets
            if asset.id in purchase_positions
        },
        suspended_passive_losses={
            asset.id: asset.suspended_passive_loss
            for asset in plan_data.real_assets
            if real_estate.is_rental(asset) and asset.suspended_passive_loss > 0
        },
        liability_states={
            liab.id: LiabilityState(remaining_balance=liab.principal_balance, name=liab.name)
            for liab in plan_data.liabilities
        },
    )


def _begin_year_state(
    state: SimState, plan_data: PlanData, year: int, *, tax_settings: Mapping[str, Any],
    federal_inflation_factor: float, calendar_inflation: dict[int, float], ytd: Mapping[str, Any],
    coverage_warnings: set[str],
) -> dict:
    """Reset the per-year accumulators and seed them from opening year-to-date entries.

    Returns the year's entered HSA coverage by owner.
    """
    state.year = year
    state.hsa_coverage = tax_settings.get("hsa_coverage", [])
    state.coverage_inflation_factor = federal_inflation_factor
    calendar_inflation[year] = federal_inflation_factor
    known_hsa = active_coverage(year, state.hsa_coverage)
    # IRC 223(b)(7): no HSA contributions from the month of Medicare
    # enrollment. Entered coverage rows take precedence.
    state.hsa_medicare_start = {}
    hsa_hc_settings = parse_healthcare_settings(plan_data.healthcare_settings)
    for hsa_owner, owner_birth_year, owner_birth_month in (
            ("self", plan_data.birth_year, plan_data.birth_month),
            ("spouse", plan_data.spouse_birth_year, plan_data.spouse_birth_month)):
        if owner_birth_year is None or hsa_owner in known_hsa:
            continue
        enrollment = medicare_enrollment_start(hsa_hc_settings, hsa_owner, year - owner_birth_year,
                                               owner_birth_month)
        if enrollment is not None:
            state.hsa_medicare_start[hsa_owner] = enrollment
    if any(a.account_type == "hsa" and a.owner not in known_hsa for a in state.accounts.values()):
        coverage_warnings.add("HSA eligibility is unspecified for some years. Legacy self-only limits apply unless explicit family coverage requires confirmation of the other owner's eligibility. Enter covered months, including Medicare and other coverage restrictions.")
    state.roth_conversions_this_year = 0.0
    state.retirement_income_this_year = {}
    state.retirement_distributions_this_year = {}
    state.waterfall_retirement_contributions_this_year = {}
    state.real_estate_gains_this_year = 0.0
    state.unrecaptured_1250_this_year = 0.0
    state.real_estate_ordinary_loss_this_year = 0.0
    state.disposed_rentals_this_year = set()
    state.roth_ledger = None
    state.roth_penalty_charged = 0.0
    state.owner_birth_months = {"self": plan_data.birth_month, "spouse": plan_data.spouse_birth_month}
    state.capital_gains_this_year = 0.0
    state.harvested_gains_this_year = 0.0
    state.reset_investment_income()
    state.deposits_this_year = {}
    state.withdrawals_this_year = {}
    state.intl_bonus_this_year = {}
    state.intl_account_tax_this_year = 0.0
    state.investment_fees_this_year = 0.0
    state.paid_out_dividends_this_year = 0.0
    state.paid_out_bond_interest_this_year = 0.0
    state.withdrawal_growth_adjustment = 0.0
    state.withdrawal_growth_factors = {}
    state.withdrawal_dividend_factors = {}
    state.income_character = {}
    state.owner_ages = {"self": year - plan_data.birth_year}
    if plan_data.spouse_birth_year is not None:
        state.owner_ages["spouse"] = year - plan_data.spouse_birth_year
    elif any(a.account_type == "hsa" and a.owner == "spouse" for a in state.accounts.values()):
        coverage_warnings.add("Partner age is missing; an HSA catch-up contribution cannot be established for that partner.")
    state.drawdown_tax_withheld_this_year = 0.0
    state.hsa_medical_allowance = None
    state.hsa_medicare_premium_allowance = 0.0
    state.hsa_taxable_distributions_this_year = 0.0
    state.education_allowance = None
    state.education_taxable_earnings_this_year = 0.0
    state.education_qualified_withdrawals_this_year = 0.0
    state.transfers = []
    state.ytd_contributions = dict(ytd.get("contributions_by_account", {}))
    # Opening year-to-date 529 contributions count for a state deduction.
    state.education_contributions_this_year = sum(
        float(amount) for account_id, amount in state.ytd_contributions.items()
        if account_id in state.accounts and state.accounts[account_id].account_type == EDUCATION_ACCOUNT_TYPE)
    state.allocation_flows = []
    state.debt_prepayments = {}
    state.rule_funding_shortfall = 0.0
    state.debt_forgiven_this_year = 0.0
    state.cod_income_this_year = 0.0
    state.transfer_income_this_year = 0.0
    state.transfer_penalty_this_year = 0.0
    if plan_data.cash_reserve is not None:
        state.cash_reserve_accounts = tuple(
            aid for aid in plan_data.cash_reserve.account_ids if aid in state.accounts)
        state.cash_reserve_target = plan_data.cash_reserve.amount * state.inflation_factor
    state.ytd_employer_contributions = dict(ytd.get("employer_contributions_by_account", {}))
    state.ytd_after_tax_contributions = {}
    # HSA and 457(b) employer money shares the employee limit (IRC 457(b)(2)).
    for account_id, amount in state.ytd_employer_contributions.items():
        if account_id in state.accounts and state.accounts[account_id].account_type in SECTION_457B_TYPES | {"hsa"}:
            state.ytd_contributions[account_id] = state.ytd_contributions.get(account_id, 0.0) + amount
    return known_hsa


def _apply_loan_forgiveness(
    state: SimState, plan_data: PlanData, year: int, newly_triggered: list[str], coverage_warnings: set[str],
) -> None:
    """Step 1a: forgive loans whose one-time forgiveness falls in this year."""
    for liab in plan_data.liabilities:
        event = liab.forgiveness
        loan = state.liability_states.get(liab.id)
        if event is None or loan is None or liab.id in state.forgiven_liability_ids:
            continue
        if not forgiveness_due(event, year, newly_triggered):
            if (year == plan_data.start_year and event.milestone_id in state.triggered_milestones
                    and event.milestone_id not in newly_triggered):
                state.forgiven_liability_ids.add(liab.id)
                coverage_warnings.add(
                    f"{liab.name}: the forgiveness milestone was reached before the plan starts, "
                    "so the forgiveness is not applied. Start the plan with the balance after forgiveness.")
            continue
        state.forgiven_liability_ids.add(liab.id)
        forgiven, taxable_forgiven = forgiven_amounts(
            event, loan.remaining_balance + loan.accrued_interest)
        if forgiven <= 0:
            continue
        apply_forgiveness(loan, forgiven)
        state.debt_forgiven_this_year += forgiven
        state.cod_income_this_year += taxable_forgiven


def _take_repeating_loans(
    state: SimState, plan_data: PlanData, year: int, *, start_year: int,
    repeating_loans: list[LiabilityData], milestone_map: Mapping[str, Any], newly_triggered: list[str],
) -> None:
    """Step 1b: add this year's occurrence of each repeating loan, inflated."""
    for liab in repeating_loans:
        occurrence = _loan_occurrence(liab, year, start_year, milestone_map, state,
                                      newly_triggered, plan_data.birth_month)
        if occurrence is None:
            continue
        loan_id = f"{liab.id}:repeat:{occurrence}"
        principal = liab.principal_balance * state.inflation_factor
        plan_data.liabilities.append(replace(
            liab, id=loan_id, principal_balance=principal,
            monthly_payment=(liab.monthly_payment if liab.payment_type == "percent_of_balance"
                             or liab.monthly_payment is None
                             else liab.monthly_payment * state.inflation_factor),
            extra_payment=liab.extra_payment * state.inflation_factor,
            linked_asset_id=None, payoff_milestone_id=None, forgiveness=None,
            recurrence_years=None, recurrence_end_year=None, recurrence_end_milestone_id=None,
        ))
        state.liability_states[loan_id] = LiabilityState(remaining_balance=principal, name=liab.name)


def _apply_filing_status_and_deaths(
    state: SimState, plan_data: PlanData, year: int, coverage_warnings: set[str],
) -> None:
    """Step 1b: scheduled filing-status changes, deaths and the survivor's filing status."""
    applicable_statuses = [
        (change.get("year") if change.get("year") is not None else
         state.triggered_milestone_years.get(change.get("milestone_id")), index, change["filing_status"])
        for index, change in enumerate(plan_data.filing_status_changes)
    ]
    applicable_statuses = [item for item in applicable_statuses if item[0] is not None and item[0] <= year]
    if applicable_statuses:
        state.current_filing_status = max(applicable_statuses)[2]
    lifecycle.apply_transitions(plan_data, state, year)
    if (
        not lifecycle.enabled(plan_data)
        and not state.partner_deceased
        and plan_data.spouse_birth_year is not None
        and plan_data.spouse_life_expectancy is not None
        and year >= plan_data.spouse_birth_year + plan_data.spouse_life_expectancy
    ):
        _handle_partner_death(
            state, plan_data,
            plan_data.spouse_birth_year + plan_data.spouse_life_expectancy,
        )
    if state.partner_death_year is not None and year > state.partner_death_year:
        estate = plan_data.estate_settings or EstateSettingsData()
        state.current_filing_status = estate.filing_status_after_death
        if (estate.filing_status_after_death == "married_filing_jointly"
                and year > state.partner_death_year + 2):
            # IRC 2(a)(1): joint rates as a qualifying surviving spouse
            # last at most the two years after the death year (and need
            # a dependent child, which the plan cannot confirm).
            state.current_filing_status = "single"
            coverage_warnings.add(
                "Joint filing after a partner's death is limited to the two years after the death "
                "year (qualifying surviving spouse, which also requires a dependent child); later years "
                "are taxed as single. Choose head of household if it applies.")


class _MarketYear(NamedTuple):
    """Step 2 results the rest of the year reads."""

    annual_account_rates: dict[str, tuple]
    annual_income_composition: dict[str, IncomeComposition]
    bond_allocation: float
    bond_allocation_by_account: dict[str, float]
    # Prior December 31 balances (RMD, SEPP and strategy bases).
    prior_year_balances: dict[str, float]
    # Opening balances, real assets and loans for a country year.
    regime_opening: tuple[dict, dict, dict]
    taxable_dividends: float
    taxable_cash_interest: float
    taxable_bond_interest: float
    total_start: float
    total_end: float
    used_historical_yields: bool
    used_assumed_yield_fallback: bool


def _apply_market_growth(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, *,
    override_returns: dict[int, tuple] | None, curves: Any, tax_settings: Mapping[str, Any],
    asset_location: Any, country_accounts: bool, coverage_warnings: set[str],
    default_stock_growth: float, default_bond_return: float, default_dividend_yield: float,
    default_cash_yield: float,
) -> _MarketYear:
    """Step 2: resolve the year's returns and grow every account.

    Also sets the withdrawal growth factors that required distributions
    and later withdrawals use, and records the year's portfolio return.
    """
    used_historical_yields = used_assumed_yield_fallback = False
    crypto_return = None
    if override_returns is not None and year in override_returns:
        override_row = override_returns[year]
        stock_growth_rate, bond_growth_rate, _override_inflation = override_row[0], override_row[1], override_row[2]
        historical_yield = override_row[3] if len(override_row) > 3 else None
        # Monte Carlo crypto distribution: total return for crypto accounts.
        crypto_return = override_row[4] if len(override_row) > 4 else None
        if historical_yield is not None:
            # Observed start-of-year dividend yield for the replayed year;
            # the total return is preserved and split into price + income.
            dividend_yield = float(historical_yield)
            used_historical_yields = True
        else:
            # Fallback: split using the plan's assumed distribution yield.
            dividend_yield = resolve_assumption(curves, "dividend_yield", year,
                                                plan_data.birth_year, default_dividend_yield)
            # An unknown distribution is only an assumption. Bound it by
            # the supplied total return so price cannot fall below zero;
            # a complete loss has no remaining value to distribute.
            dividend_yield = min(dividend_yield, 1.0 + stock_growth_rate)
            used_assumed_yield_fallback = True
        stock_growth_rate -= dividend_yield
    else:
        stock_growth_rate = resolve_assumption(
            curves, "market_return", year, plan_data.birth_year, default_stock_growth,
        )
        bond_growth_rate = resolve_assumption(
            curves, "bond_return", year, plan_data.birth_year, default_bond_return,
        )
        dividend_yield = resolve_assumption(
            curves,
            "dividend_yield",
            year,
            plan_data.birth_year,
            default_dividend_yield,
        )
    bond_allocation = resolve_assumption(
        curves, "bond_allocation", year, plan_data.birth_year, DEFAULT_BOND_ALLOCATION,
    )
    # Catmull-Rom splines can overshoot between control points; clamp so
    # apply_growth never gets a nonsensical stock/bond blend.
    bond_allocation = min(1.0, max(0.0, bond_allocation))
    annual_stock_growth_rate = stock_growth_rate
    annual_bond_growth_rate = bond_growth_rate
    annual_dividend_yield = dividend_yield
    if override_returns is not None and year in override_returns:
        # Compound the total return for the active period, then separate
        # its distribution component so partial years also conserve it.
        total_stock_rate = _rate_for_fraction(stock_growth_rate + dividend_yield, year_fraction)
        stock_growth_rate = total_stock_rate - dividend_yield * year_fraction
    else:
        stock_growth_rate = _rate_for_fraction(stock_growth_rate, year_fraction)
    bond_growth_rate = _rate_for_fraction(bond_growth_rate, year_fraction)
    dividend_yield *= year_fraction
    cash_yield_rate = resolve_assumption(
        curves, "cash_yield", year, plan_data.birth_year, default_cash_yield,
    ) * year_fraction
    # Glide paths and the household asset location, from opening balances.
    resolved_bond_allocations, bond_allocation_by_account = resolve_bond_allocations(
        state.accounts, bond_allocation, asset_location, year, state.owner_ages,
    )
    annual_account_rates = {
        aid: account_investment_rates(
            account,
            annual_stock_growth_rate,
            annual_bond_growth_rate,
            bond_allocation,
            annual_dividend_yield,
            resolved_bond_allocations.get(aid),
        )
        for aid, account in state.accounts.items()
    }
    if crypto_return is not None:
        # A sampled crypto return replaces the crypto account's growth,
        # including a fixed account rate; crypto pays no income.
        for aid, account in state.accounts.items():
            if account.account_type == "cryptocurrency":
                _stock, bond_rate, allocation, dividend_rate = annual_account_rates[aid]
                annual_account_rates[aid] = (float(crypto_return), bond_rate, allocation, dividend_rate)
    # Dividend character and bond income (account investment_settings).
    # The character splits income on mid-year contributions and on
    # withdrawals in the same shares as income on opening balances.
    annual_income_composition = {
        aid: account_income_composition(account)
        for aid, account in state.accounts.items()
    }
    for aid, account in state.accounts.items():
        if account.account_type in _ZERO_GROWTH_TYPES:
            continue
        _price_rate, stock_income_rate, bond_income_rate = _price_and_income_rates(
            annual_account_rates[aid], annual_income_composition[aid], account.account_type)
        state.income_character[aid] = annual_income_composition[aid].character(
            stock_income_rate, bond_income_rate)
    if any(account.account_type == "taxable_brokerage" and account.balance > 0
           and annual_account_rates[aid][2] > 0
           and (account.investment_settings or {}).get("bond_income_yield") is None
           for aid, account in state.accounts.items()):
        coverage_warnings.add("Taxable bond interest is not modeled separately from bond price returns. Taxable bond holdings may understate annual ordinary-income tax and overstate later capital gains; a coupon-yield assumption is required to separate them.")
    # Required distributions and discretionary withdrawals share the same
    # end-of-month convention. Establish factors before either can occur.
    frequency = tax_settings.get("withdrawal_cash_flow_frequency") or tax_settings.get("cash_flow_frequency", "monthly")
    if frequency == "monthly":
        active_months = max(1, min(12, round(12 * year_fraction)))
        for aid, account in state.accounts.items():
            if account.account_type in _ZERO_GROWTH_TYPES:
                continue
            rate, stock_income_rate, bond_income_rate = _price_and_income_rates(
                annual_account_rates[aid], annual_income_composition[aid], account.account_type)
            state.withdrawal_growth_factors[aid], state.withdrawal_dividend_factors[aid] = _withdrawal_factors(
                account, rate, stock_income_rate + bond_income_rate,
                lambda r: _average_monthly_deposit_growth_factor(r, active_months))
    period_income_composition = {
        aid: composition.for_period(year_fraction)
        for aid, composition in annual_income_composition.items()
    }
    fractional_account_rates = {}
    for aid, account in state.accounts.items():
        stock_rate, _bond_rate, allocation, dividend_rate = annual_account_rates[aid]
        settings = account.investment_settings or {}
        fractional_account_rates[aid] = (
            _rate_for_fraction(stock_rate, year_fraction)
            if settings.get("stock_growth_rate") is not None
            or (crypto_return is not None and account.account_type == "cryptocurrency")
            else stock_growth_rate,
            bond_growth_rate,
            allocation,
            dividend_rate * year_fraction
            if settings.get("dividend_yield") is not None
            else dividend_yield,
        )
    # Snapshot prior-year-end balances for RMD calculation (IRS requires
    # RMDs to be based on the prior December 31 balance, before growth).
    prior_year_balances = {aid: acct.balance for aid, acct in state.accounts.items()}
    # Opening balances for a country year's wealth tax and estate rules.
    regime_opening = (dict(prior_year_balances), dict(state.real_asset_values),
                      {lid: loan.remaining_balance + loan.accrued_interest
                       for lid, loan in state.liability_states.items()})

    total_start = sum(
        a.balance for a in state.accounts.values()
        if a.account_type not in _ZERO_GROWTH_TYPES
    )
    taxable_dividends, taxable_cash_interest = state.apply_growth(
        stock_growth_rate,
        bond_growth_rate,
        bond_allocation,
        stock_dividend_yield=dividend_yield,
        cash_yield_rate=cash_yield_rate,
        account_rates=fractional_account_rates,
        income_composition=period_income_composition,
        fee_year_fraction=year_fraction,
    )
    # Accumulators were reset this year, so this is income on opening balances.
    taxable_bond_interest = state.bond_interest_this_year
    if country_accounts:
        # Tax inside country accounts on the year's growth, netted from it.
        intl_accounts.apply_earnings_tax(state, prior_year_balances)
    total_end = sum(
        a.balance for a in state.accounts.values()
        if a.account_type not in _ZERO_GROWTH_TYPES
    )
    year_return = (total_end - total_start) / total_start if total_start > 0 else 0.0
    state.return_history.append(year_return)
    return _MarketYear(
        annual_account_rates=annual_account_rates,
        annual_income_composition=annual_income_composition,
        bond_allocation=bond_allocation,
        bond_allocation_by_account=bond_allocation_by_account,
        prior_year_balances=prior_year_balances,
        regime_opening=regime_opening,
        taxable_dividends=taxable_dividends,
        taxable_cash_interest=taxable_cash_interest,
        taxable_bond_interest=taxable_bond_interest,
        total_start=total_start,
        total_end=total_end,
        used_historical_yields=used_historical_yields,
        used_assumed_yield_fallback=used_assumed_yield_fallback,
    )


class _RealAssetYear(NamedTuple):
    """Step 2b results the rest of the year reads."""

    # Values at the start of the year (a purchase: its price).
    real_asset_start_values: dict[str, float]
    # Share of the modeled year each asset is owned.
    asset_fractions: dict[str, float]
    # Calendar-year month positions (0-12) each asset is owned.
    asset_windows: dict[str, tuple[float, float]]
    scheduled_sales: list[RealAssetData]
    purchases_this_year: list[tuple[RealAssetData, real_estate.PurchaseTerms]]


def _appreciate_real_assets(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, *,
    purchase_positions: Mapping[str, float], rental_building_basis: dict[str, float | None],
) -> _RealAssetYear:
    """Step 2b: complete planned purchases, appreciate owned assets, queue sales.

    A purchase loan joins ``plan_data.liabilities`` in the purchase year.
    """
    real_asset_start_values = dict(state.real_asset_values)
    asset_fractions = {}
    # Calendar-year month positions (0-12) a property is owned this year.
    asset_windows: dict[str, tuple[float, float]] = {}
    scheduled_sales = []
    purchases_this_year: list[tuple[RealAssetData, real_estate.PurchaseTerms]] = []
    for asset in plan_data.real_assets:
        start_fraction = 1 - year_fraction
        if asset.id in state.pending_purchase_values:
            position = purchase_positions[asset.id]
            buy_fraction = max(0.0, min(1.0, position - year))
            # The planned price follows the asset's appreciation until
            # the purchase month.
            state.pending_purchase_values[asset.id] *= 1 + _rate_for_fraction(
                asset.annual_appreciation_rate, max(0.0, min(1.0, buy_fraction) - start_fraction))
            if position >= year + 1:
                continue
            terms = real_estate.purchase_terms(asset, state.pending_purchase_values.pop(asset.id))
            state.set_real_asset_value(asset.id, terms.price)
            state.real_asset_basis[asset.id] = terms.basis
            state.real_asset_purchase_dates[asset.id] = (asset.purchase_year, asset.purchase_month)
            real_asset_start_values[asset.id] = terms.price
            purchases_this_year.append((asset, terms))
            start_fraction = max(start_fraction, buy_fraction)
        elif asset.id not in state.real_asset_values:
            continue
        end_fraction = 1.0
        if asset.sale_year is not None and year >= asset.sale_year:
            # Sale is at the start of the selected month. Only the
            # overlap with the modeled portion of this year is owned.
            end_fraction = (asset.sale_month - 1) / 12 if year == asset.sale_year else 0.0
            scheduled_sales.append(asset)
        owned_fraction = max(0.0, end_fraction - start_fraction)
        asset_fractions[asset.id] = owned_fraction
        asset_windows[asset.id] = (12 * start_fraction, 12 * max(start_fraction, end_fraction))
        value = state.get_real_asset_value(asset.id)
        state.set_real_asset_value(asset.id, value * (1 + _rate_for_fraction(
            asset.annual_appreciation_rate, owned_fraction)))
    # A purchase loan starts in the purchase month and amortizes with the
    # months the property is owned, like any loan linked to it.
    for asset, terms in purchases_this_year:
        if real_estate.is_rental(asset):
            rental_building_basis[asset.id] = terms.building_basis
        if terms.loan_principal <= 0.005 or not asset.purchase_loan_term_months:
            continue
        loan_id = f"{asset.id}:purchase_loan"
        loan_rate = asset.purchase_loan_rate or 0.0
        plan_data.liabilities.append(LiabilityData(
            id=loan_id, name=f"{asset.name} purchase loan",
            principal_balance=terms.loan_principal, interest_rate=loan_rate,
            term_months=asset.purchase_loan_term_months,
            monthly_payment=resolve_monthly_payment(
                terms.loan_principal, loan_rate, asset.purchase_loan_term_months, None, "fixed"),
            payment_type="fixed", linked_asset_id=asset.id,
        ))
        state.liability_states[loan_id] = LiabilityState(remaining_balance=terms.loan_principal)
    return _RealAssetYear(real_asset_start_values, asset_fractions, asset_windows,
                          scheduled_sales, purchases_this_year)


class _RmdYear(NamedTuple):
    """Step 2c totals: all RMDs, the taxable ones and the IRA ones QCDs can offset."""

    rmd_total: float
    taxable_rmd_total: float
    # The taxable part of inherited Roth RMDs.
    roth_rmd_income: float
    ira_rmd_total: float
    ira_rmd_by_owner: dict[str, float]
    ira_rmd_by_account: dict[str, float]


def _required_minimum_distributions(
    state: SimState, plan_data: PlanData, year: int, age: int, *,
    prior_year_balances: Mapping[str, float], ytd: Mapping[str, Any],
) -> _RmdYear:
    """Step 2c: take each account's required minimum distribution for the year."""
    rmd_total = 0.0
    taxable_rmd_total = 0.0
    roth_rmd_income = 0.0
    ira_rmd_total = 0.0
    ira_rmd_by_owner: dict[str, float] = {}
    ira_rmd_by_account: dict[str, float] = {}
    for aid, acct in state.accounts.items():
        if acct.balance <= 0:
            continue

        if acct.inherited_year is not None and year > acct.inherited_year and (acct.inheritance_settings or {}).get('distribution_method') == 'spousal_rollover':
            if acct.beneficiary_type != 'spouse':
                raise ValueError('Own-account treatment requires a spouse beneficiary')
            acct.inherited_year = None
            acct.inheritance_settings = None

        # Resolve owner's age/birth_year for RMD trigger and divisor.
        # Spouse-owned accounts use the spouse's age so a spouse 5 years
        # older starts RMDs 5 years earlier (and gets their own divisor).
        # Joint-owned accounts use the plan holder's age — joint RMD
        # attribution is not owner-split in this engine (see 31.3.3).
        # In the legacy death year, an account re-owned from the deceased
        # spouse still owes the decedent's RMD, figured as if they lived
        # the whole year, and none if they died before the required
        # beginning date (April 1 after the start-age year). The survivor
        # owes no RMD as owner until the next year. IRS Pub. 590-B, "Year
        # of owner's death"; Treas. Reg. §1.408-8(c)(3).
        decedent_death_year = (
            year == state.partner_death_year
            and aid in state.partner_reowned_account_ids
            and plan_data.spouse_birth_year is not None
        )
        if (
            acct.owner == "spouse"
            and plan_data.spouse_birth_year is not None
            and not state.partner_deceased
        ) or decedent_death_year:
            owner_age = year - plan_data.spouse_birth_year
            owner_birth_year = plan_data.spouse_birth_year
            rmd_owner = "spouse"
        else:
            owner_age = age
            owner_birth_year = plan_data.birth_year
            rmd_owner = "self"
        # An assumed start age replaces SECURE 2.0 for the owner's own
        # accounts only; inherited-account rules keep the statute.
        owner_start_age = rmd_start_age_override(plan_data.tax_settings, rmd_owner)

        prior_bal = prior_year_balances.get(aid, acct.balance)
        # Opening year: withdrawals taken before the plan start count
        # toward this year's minimum. Adding them back and removing this
        # year's contributions rebuilds the prior December 31 balance;
        # market movement since then is unknown and ignored.
        already_distributed = float(ytd.get("distributions_by_account", {}).get(aid, 0.0))
        if ytd:
            prior_bal = max(0.0, prior_bal + already_distributed
                            - float(ytd.get("contributions_by_account", {}).get(aid, 0.0))
                            - float(ytd.get("employer_contributions_by_account", {}).get(aid, 0.0)))
        growth_factor = state.withdrawal_growth_factors.get(aid, 0.0)
        available = max(0.0, acct.balance) / (1 + growth_factor)
        if acct.inherited_year is not None and acct.account_type in RETIREMENT_ACCOUNT_TYPES:
            rmd_amount = calculate_inherited_ira_rmd(
                available, acct.inherited_year, year,
                beneficiary_age=owner_age,
                beneficiary_type=acct.beneficiary_type,
                prior_year_balance=prior_bal,
                is_roth=acct.account_type.startswith('roth'),
                **(acct.inheritance_settings or {}),
            )
        elif acct.account_type in _RMD_ACCOUNT_TYPES and is_rmd_required(owner_age, owner_birth_year,
                                                                          owner_start_age):
            if decedent_death_year:
                # Legacy death is at the start of the spouse's birth month.
                death_month = year * 12 + (plan_data.spouse_birth_month or 1) - 1
                start_age_used = (get_rmd_start_age(owner_birth_year) if owner_start_age is None
                                  else owner_start_age)
                rbd_month = (owner_birth_year + start_age_used + 1) * 12 + 3
                if death_month < rbd_month:
                    continue
            # Opt-in: a spouse who is the account's sole beneficiary and more
            # than ten years younger moves the divisor to Table 3
            # (Treas. Reg. 1.401(a)(9)-9(c)(2)). No living spouse, no switch.
            joint_spouse_age = None
            if ((acct.distribution_settings or {}).get("spouse_sole_beneficiary")
                    and acct.owner in ("self", "spouse") and plan_data.spouse_birth_year is not None
                    and not state.partner_deceased and not decedent_death_year):
                holder_is_owner = acct.owner == "self"
                other_birth_year = plan_data.spouse_birth_year if holder_is_owner else plan_data.birth_year
                if spouse_more_than_ten_years_younger(
                        owner_birth_year, other_birth_year,
                        plan_data.birth_month if holder_is_owner else plan_data.spouse_birth_month,
                        plan_data.spouse_birth_month if holder_is_owner else plan_data.birth_month):
                    joint_spouse_age = year - other_birth_year
            rmd_amount = calculate_rmd(acct.balance, owner_age, owner_birth_year, prior_year_balance=prior_bal,
                                       spouse_age=joint_spouse_age, start_age=owner_start_age)
        else:
            continue
        if rmd_amount > 0:
            rmd_amount = min(rmd_amount, available)
            if already_distributed > 0 and rmd_amount < available:
                # An annual minimum, not a required full payout.
                rmd_amount = max(0.0, rmd_amount - already_distributed)
        if rmd_amount > 0:
            # Reserve foregone growth before withdrawal, including a final
            # inherited-account distribution that empties the account.
            drag = rmd_amount * growth_factor
            acct.balance -= drag
            state.withdrawal_growth_adjustment -= drag
            if acct.account_type in ROTH_TYPES:
                roth_taxable, _ = ledger(state).distribution(aid, rmd_amount, acct.balance, acct.account_type,
                    False, True, commit=True)
                roth_rmd_income += roth_taxable
            state.withdraw_from(aid, rmd_amount)
            rmd_total += rmd_amount
            if acct.account_type in _RMD_ACCOUNT_TYPES:
                taxable_rmd_total += rmd_amount
                state.record_retirement_income(
                    acct.owner, ACCOUNT_TYPE_SOURCES[acct.account_type], rmd_amount, account_id=aid)
                if acct.account_type in _QCD_ELIGIBLE_TYPES:
                    ira_rmd_total += rmd_amount
                    ira_rmd_by_account[aid] = rmd_amount
                    ira_rmd_by_owner[acct.owner] = (
                        ira_rmd_by_owner.get(acct.owner, 0.0) + rmd_amount
                    )
    return _RmdYear(rmd_total, taxable_rmd_total, roth_rmd_income, ira_rmd_total,
                    ira_rmd_by_owner, ira_rmd_by_account)


def _qualified_charitable_distributions(
    state: SimState, plan_data: PlanData, *, tax_holder_age: int | None, ira_rmd_total: float,
    ira_rmd_by_owner: Mapping[str, float], ira_rmd_by_account: Mapping[str, float],
    taxable_rmd_total: float, tax_deferred_withholding_rate: float,
) -> tuple[float, dict[str, float], float, float]:
    """Step 2d: make the year's QCDs and withhold tax on the taxable RMD left.

    Returns (QCD total, direct IRA withdrawals by account, RMD amount the
    QCDs exclude from income, tax withheld from RMDs).
    """
    adjusted_qcd_cap = _QCD_ANNUAL_CAP * state.coverage_inflation_factor
    before_qcd = {aid: acct.balance for aid, acct in state.accounts.items()}
    qcd_total = _process_qcds(
        state, plan_data.charity_entities, ira_rmd_total, state.triggered_milestones,
        qcd_cap=adjusted_qcd_cap, age=tax_holder_age,
        birth_month=plan_data.spouse_birth_month if lifecycle.enabled(plan_data) and state.primary_deceased else plan_data.birth_month,
        rmd_by_owner=ira_rmd_by_owner,
        rmd_by_account=ira_rmd_by_account,
    )
    # RMD-funded QCDs are already represented by the RMD income source.
    # Only additional IRA withdrawals need another cash-flow source.
    qcd_withdrawals = {aid: balance - state.accounts[aid].balance
                       for aid, balance in before_qcd.items()
                       if balance > state.accounts[aid].balance}
    # The QCD helper allocates each request to an owner and consumes that
    # owner's RMD before direct IRA funds.  Derive the excluded amount from
    # the resulting direct withdrawals, so a direct gift by one owner
    # cannot erase another owner's taxable RMD.
    qcd_rmd_offset = min(
        ira_rmd_total,
        max(0.0, qcd_total - sum(qcd_withdrawals.values())),
    )
    taxable_rmd_after_qcd = max(
        0.0,
        taxable_rmd_total - qcd_rmd_offset,
    )
    # QCDs exclude IRA RMDs from income. The helper does not report the
    # owner split, so the offset is shared by each owner's IRA RMD.
    for owner, owner_rmd in ira_rmd_by_owner.items():
        if ira_rmd_total > 0:
            state.record_retirement_income(owner, "ira", -qcd_rmd_offset * owner_rmd / ira_rmd_total)
    rmd_tax_withheld = (
        taxable_rmd_after_qcd * tax_deferred_withholding_rate
    )
    state.drawdown_tax_withheld_this_year += rmd_tax_withheld
    return qcd_total, qcd_withdrawals, qcd_rmd_offset, rmd_tax_withheld


def _pension_salary_share(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, start_year: int,
    milestone_map: Mapping[str, Any], newly_triggered: list[str], income_active_until: Mapping[str, float],
    salary: IncomeData, until: float,
) -> float:
    """The share of the year a pension's salary stream pays, up to ``until``."""
    share = prorate_for_year(
        milestone_map.get(salary.start_milestone_id), milestone_map.get(salary.end_milestone_id),
        salary.start_month, salary.end_month, state.triggered_milestones, newly_triggered,
        year, plan_data.birth_month, year_fraction,
        active_until=min(until, income_active_until[salary.id]),
    )
    return payment_share(salary, year, start_year, state.triggered_milestone_years,
                         share, year_fraction, min(until, income_active_until[salary.id]))


def _spousal_arf(ss_aux_withheld_months: Mapping[Any, int], income: IncomeData) -> float:
    """A spousal-type benefit's adjustment for months the earnings test withheld."""
    pool = income.ss_spousal_reduction[0]
    return spousal_arf_factor(income.ss_spousal_reduction, ss_aux_withheld_months.get(pool, 0))


class _IncomeYear(NamedTuple):
    """Step 3: the year's income streams, by tax treatment and owner."""

    gross_income: float
    nontaxable_income: float
    ss_income: float
    earned_income: float
    w2_income: float
    ca_w2_income: float
    non_earned_income: float
    has_self_employment: bool
    w2_by_owner: dict[str, float]
    se_by_owner: dict[str, float]
    state_ytd_wages: dict[str, float]
    state_wages_by_owner: dict[str, float]
    covered_income_by_id: dict[str, float]
    nonresident_payroll_wages: bool
    local_stream_income: dict[str | None, float]
    income_details: list[tuple[float, float]]
    income_by_id: dict[str, float]
    income_grown_by_id: dict[str, float]
    income_active_share: dict[str, float]
    cf_income_sources: list[NamedAmount]


def _income_streams(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, *, start_year: int,
    ytd: Mapping[str, Any], milestone_map: Mapping[str, Any], newly_triggered: list[str],
    income_active_until: Mapping[str, float], income_growth_factors: Mapping[str, float],
    income_scheduled_amounts: Mapping[str, float], pension_amounts: Mapping[str, float],
    social_security_inflation_factor: float, ss_adjustments: Mapping[str, float],
    known_payroll: Mapping[str, Any], residency_spans: list, ca_move_year: bool,
    taxable_dividends: float, taxable_bond_interest: float, taxable_cash_interest: float,
) -> _IncomeYear:
    """Step 3: each income stream's amount for the year and where it is taxed.

    Prorates each stream for its active months, applies growth, caps, pay
    interruptions and Social Security claiming adjustments, and sorts the
    result into wages, self-employment, Social Security and other income,
    with state payroll coverage and California move-year wages. Records
    retirement income by owner for state exclusions.
    """
    ca_w2_income = 0.0
    gross_income = taxable_cash_interest
    nontaxable_income = 0.0
    ss_income = 0.0  # Social Security income tracked separately for tax
    earned_income = 0.0  # [13.1.1] earned income for FICA
    w2_income = 0.0
    w2_by_owner = dict(ytd.get("w2_income_by_owner", {}))
    state_ytd_wages = {
        owner: amount for owner, amount in w2_by_owner.items()
        if owner in known_payroll and (
            known_payroll[owner]['start_year'] < year
            or known_payroll[owner].get('start_month', 1) == 1
            or (known_payroll[owner].get('start_month', 1)-1)/12 < 1-year_fraction
        )
    }
    state_wages_by_owner = dict(state_ytd_wages)
    covered_income_by_id: dict[str, float] = {}
    nonresident_payroll_wages = False
    se_by_owner = dict(ytd.get("self_employment_income_by_owner", {}))
    non_earned_income = taxable_cash_interest  # [13.1.2] ordinary investment income
    # Non-wage income streams by tax category, for local income tax bases.
    local_stream_income: dict[str | None, float] = {}
    has_self_employment = False  # [13.1.1] any SE income stream active
    income_details: list[tuple[float, float]] = []  # (prorated_amount, withholding_pct)
    income_by_id: dict[str, float] = {}
    income_grown_by_id: dict[str, float] = {}
    # Share of the calendar year each stream pays, for per-period matches.
    income_active_share: dict[str, float] = {}
    cf_income_sources: list[NamedAmount] = []
    if taxable_dividends > 0:
        cf_income_sources.append(NamedAmount(
            name="Taxable Stock Dividends",
            amount=taxable_dividends,
        ))
    if taxable_bond_interest > 0:
        cf_income_sources.append(NamedAmount(
            name="Taxable-Account Bond Interest",
            amount=taxable_bond_interest,
        ))
    if taxable_cash_interest > 0:
        cf_income_sources.append(NamedAmount(
            name="Savings Yield",
            amount=taxable_cash_interest,
        ))

    for inc in plan_data.income_streams:
        active_until = income_active_until[inc.id]
        prorate = prorate_for_year(
            start_ms=milestone_map.get(inc.start_milestone_id) if inc.start_milestone_id else None,
            end_ms=milestone_map.get(inc.end_milestone_id) if inc.end_milestone_id else None,
            start_month=inc.start_month,
            end_month=inc.end_month,
            triggered=state.triggered_milestones,
            newly_triggered=newly_triggered,
            year=year,
            birth_month=plan_data.birth_month,
            simulation_fraction=year_fraction,
            active_until=active_until,
        )
        payment_position = ((inc.start_month or (
            resolve_trigger_month(milestone_map[inc.start_milestone_id], plan_data.birth_month, year)
            if inc.start_milestone_id in milestone_map else 1)) - 1) / 12
        prorate = payment_share(inc, year, start_year, state.triggered_milestone_years,
                                prorate, year_fraction, active_until,
                                resolve_trigger_month(milestone_map[inc.start_milestone_id], plan_data.birth_month, year)
                                if inc.start_milestone_id in milestone_map else 1)
        if prorate == 0.0:
            income_details.append((0.0, inc.withholding_percent))
            income_by_id[inc.id] = 0.0
            continue

        # Amounts are in plan-start-year dollars: growth compounds from
        # the start year even when the stream begins later, so a future
        # pension or job is carried forward to its start date just as
        # inflation-linked expenses and Social Security are.
        grown_amount = (pension_amounts[inc.id] if inc.pension_formula else
                        income_scheduled_amounts[inc.id] if inc.id in income_scheduled_amounts else
                        inc.annual_amount * income_growth_factors[inc.id])
        if inc.growth_cap is not None and not inc.pension_formula:
            cap = inc.growth_cap
            if inc.growth_cap_inflation_linked:
                cap *= social_security_inflation_factor if inc.is_social_security else state.inflation_factor
            grown_amount = min(grown_amount, cap)
        if inc.pay_interruption is not None:
            # Scenario stress overlay: unpaid months and the resumed rate
            # scale the year's grown amount, so every consumer of
            # ``grown_amount`` (contributions, state wages) follows it.
            pause_start, resume_at, multiplier = inc.pay_interruption

            def active_share(active_from, until, inc=inc, active_until=active_until):
                return prorate_for_year(
                    milestone_map.get(inc.start_milestone_id) if inc.start_milestone_id else None,
                    milestone_map.get(inc.end_milestone_id) if inc.end_milestone_id else None,
                    inc.start_month, inc.end_month, state.triggered_milestones, newly_triggered,
                    year, plan_data.birth_month, year_fraction,
                    active_from=min(1.0, max(0.0, active_from)),
                    active_until=min(active_until, max(0.0, until)),
                )
            if inc.frequency == "once":
                position = year + payment_position
                grown_amount *= 0.0 if pause_start <= position < resume_at else multiplier if position >= resume_at else 1.0
            else:
                paid = active_share(0.0, pause_start - year) + multiplier * active_share(resume_at - year, 1.0)
                grown_amount *= paid / prorate
        income_grown_by_id[inc.id] = grown_amount
        prorated_amount = grown_amount * prorate
        if inc.id in ss_adjustments and ss_adjustments[inc.id] != 1:
            birth, birth_month = owner_birth(plan_data, inc.owner)
            fra = retirement_fra_index(birth, month_index(birth, birth_month))
            post_share = prorate_for_year(milestone_map.get(inc.start_milestone_id), milestone_map.get(inc.end_milestone_id), inc.start_month, inc.end_month, state.triggered_milestones, newly_triggered, year, plan_data.birth_month, year_fraction, active_from=max(0.0, min(1.0, (fra - month_index(year, 1))/12)), active_until=active_until)
            prorated_amount += grown_amount * (ss_adjustments[inc.id] - 1) * post_share
        income_by_id[inc.id] = prorated_amount
        income_active_share[inc.id] = prorate

        for owner, owner_share in _stream_owner_shares(inc.owner, plan_data):
            source = ("social_security" if inc.is_social_security
                      else STREAM_CATEGORY_SOURCES.get(inc.tax_category))
            if source:
                state.record_retirement_income(owner, source, prorated_amount * owner_share)
        if inc.tax_category == "nontaxable":
            nontaxable_income += prorated_amount
        elif inc.is_social_security:
            ss_income += prorated_amount
        else:
            gross_income += prorated_amount
            # [13.1.1] Track earned vs non-earned income
            if inc.is_earned_income:
                earned_income += prorated_amount
                if inc.is_self_employed:
                    se_by_owner[inc.owner] = se_by_owner.get(inc.owner, 0.0) + prorated_amount
                    has_self_employment = True
                else:
                    w2_income += prorated_amount
                    w2_by_owner[inc.owner] = w2_by_owner.get(inc.owner, 0.0) + prorated_amount
                    coverage = known_payroll.get(inc.owner)
                    if coverage is not None:
                        coverage_start = ((coverage.get("start_month", 1) - 1) / 12
                                          if year == coverage["start_year"] else 0.0)
                        def covered_fraction(start, end, inc=inc, coverage_start=coverage_start,
                                             payment_position=payment_position, active_until=active_until):
                            if inc.frequency == "once":
                                return float(max(coverage_start, start) <= payment_position < min(active_until, end))
                            return prorate_for_year(
                                milestone_map.get(inc.start_milestone_id),
                                milestone_map.get(inc.end_milestone_id),
                                inc.start_month, inc.end_month,
                                state.triggered_milestones, newly_triggered,
                                year, plan_data.birth_month, year_fraction,
                                active_from=max(coverage_start, start),
                                active_until=min(active_until, end),
                            )
                        covered = grown_amount * covered_fraction(0.0, 1.0)
                        covered_income_by_id[inc.id] = covered
                        state_wages_by_owner[inc.owner] = state_wages_by_owner.get(inc.owner, 0.0) + covered
                        resident_covered = grown_amount * sum(
                            covered_fraction(span.start_fraction, span.end_fraction)
                            for span in residency_spans if span.state_code == coverage["state_code"]
                        )
                        nonresident_payroll_wages |= covered - resident_covered > .005
                    if ca_move_year:
                        # Intersect actual wage and residency windows. A
                        # June move cannot reassign wages paid only in May.
                        ca_w2_income += grown_amount * sum(
                            prorate_for_year(
                                milestone_map.get(inc.start_milestone_id),
                                milestone_map.get(inc.end_milestone_id),
                                inc.start_month, inc.end_month,
                                state.triggered_milestones, newly_triggered,
                                year, plan_data.birth_month, year_fraction,
                                active_from=span.start_fraction,
                                active_until=min(active_until, span.end_fraction),
                            ) if inc.frequency != "once" else float(span.start_fraction <= payment_position < min(active_until, span.end_fraction))
                            for span in residency_spans if span.state_code == "CA"
                        )
            else:
                local_stream_income[inc.tax_category] = (
                    local_stream_income.get(inc.tax_category, 0.0) + prorated_amount
                )
                if inc.tax_category not in {"qualified_pension", "other_ordinary"}:
                    non_earned_income += prorated_amount
        income_details.append((prorated_amount, 0.0 if inc.tax_category == "nontaxable" else inc.withholding_percent))
        if prorated_amount > 0:
            cf_income_sources.append(NamedAmount(name=inc.name, amount=prorated_amount))
    return _IncomeYear(
        gross_income=gross_income, nontaxable_income=nontaxable_income, ss_income=ss_income,
        earned_income=earned_income, w2_income=w2_income, ca_w2_income=ca_w2_income,
        non_earned_income=non_earned_income, has_self_employment=has_self_employment,
        w2_by_owner=w2_by_owner, se_by_owner=se_by_owner, state_ytd_wages=state_ytd_wages,
        state_wages_by_owner=state_wages_by_owner, covered_income_by_id=covered_income_by_id,
        nonresident_payroll_wages=nonresident_payroll_wages, local_stream_income=local_stream_income,
        income_details=income_details, income_by_id=income_by_id, income_grown_by_id=income_grown_by_id,
        income_active_share=income_active_share, cf_income_sources=cf_income_sources,
    )


def _social_security_survivor_and_earnings_test(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, *, start_year: int,
    ytd: dict[str, Any], ytd_imputed: bool, has_provided_ytd: bool, milestone_map: Mapping[str, Any],
    newly_triggered: list[str], survivor_context: Any, income_by_id: dict[str, float],
    income_details: list[tuple[float, float]], income_grown_by_id: Mapping[str, float],
    income_active_share: Mapping[str, float], income_active_until: Mapping[str, float],
    income_growth_factors: Mapping[str, float], social_security_inflation_factor: float,
    ss_adjustments: Mapping[str, float], ss_claims: Mapping[str, int],
    ss_withheld_months: dict[str, int], ss_aux_withheld_months: dict, ss_survivor_withheld_months: int,
    ss_grace_used: set, ss_wage_index: Callable[[int], float], spousal_arf: Callable[[Any], float],
    ss_income: float, cf_income_sources: list[NamedAmount],
) -> tuple[float, float, int, dict[str, float]]:
    """Step 3: the survivor top-up and the annual earnings test on Social Security.

    Adjusts the year's benefit amounts in place and accumulates fully withheld
    months for the benefit recomputation at full retirement age. Returns
    (Social Security income, earnings-test withholding, survivor withheld months,
    withholding by the owner whose earnings the test counted). The last is
    before any auxiliary top-up offsets it, so it can exceed the household net.
    """
    # Source-backed survivor election adds only the amount above own SS.
    def own_survivor_overlap(income, active_from, active_until):
        return prorate_for_year(
            milestone_map.get(income.start_milestone_id), milestone_map.get(income.end_milestone_id),
            income.start_month, income.end_month, state.triggered_milestones, newly_triggered,
            year, plan_data.birth_month, year_fraction,
            min(active_until, income_active_until[income.id]), active_from,
        )
    def survivor_own_adjustment(income, beginning, ending):
        birth, birth_month = owner_birth(plan_data, income.owner)
        fra = retirement_fra_index(birth, month_index(birth, birth_month))
        multiplier = arf_factor(plan_data, income, ss_claims[income.id], ss_withheld_months.get(income.id, 0))
        post = own_survivor_overlap(income, max(beginning, (fra - month_index(year, 1))/12), ending)
        return grown_benefit(income, income_growth_factors, social_security_inflation_factor) * (multiplier - 1) * post
    survivor_arf = survivor_arf_annual(plan_data, survivor_context, ss_survivor_withheld_months)
    survivor_retirement_fra = None
    if survivor_context:
        birth, birth_month = owner_birth(plan_data, survivor_context.recipient)
        survivor_retirement_fra = retirement_fra_index(birth, month_index(birth, birth_month))
    def calculate_survivor_top_up(active_until=1.0, fraction=None):
        return survivor_top_up(survivor_context, year=year, year_fraction=year_fraction if fraction is None else fraction,
            growth_factors=income_growth_factors, inflation_factor=social_security_inflation_factor,
            own_overlap=own_survivor_overlap, own_adjustment=survivor_own_adjustment,
            adjusted_pia_annual=survivor_arf[1] if survivor_arf else None,
            adjustment_month_index=survivor_arf[0] if survivor_arf else None,
            own_adjustment_month_index=survivor_retirement_fra,
            active_until=active_until)
    survivor_amount = calculate_survivor_top_up()
    survivor_pre_retirement_gross = calculate_survivor_top_up(
        max(0.0, min(1.0, (survivor_retirement_fra - month_index(year, 1)) / 12))
    ) if survivor_retirement_fra is not None else 0.0
    survivor_gross_amount = survivor_amount
    if survivor_amount:
        state.record_retirement_income("spouse" if state.primary_deceased else "self",
                                       "social_security", survivor_amount)
        ss_income += survivor_amount
        income_details.append((survivor_amount, 0.0))
        cf_income_sources.append(NamedAmount(name="Social Security survivor top-up", amount=survivor_amount))

    # The annual test is owner-specific. Worker deductions are shared
    # proportionally with auxiliary spouse payments on that record.
    ss_earnings_test_withheld = 0.0
    reductions = {}
    ss_owner_test_due = {}
    withheld_by_earner: dict[str, float] = {}
    def record_withheld(owner, amount):
        if amount:
            withheld_by_earner[owner] = withheld_by_earner.get(owner, 0.0) + amount
    # Imputed history is a scheduled calendar-year estimate. Apply the
    # annual earnings test once, then allocate its deduction between
    # history and projected cash using the eligible benefit windows.
    ss_calendar_amounts = (_impute_pro_rata_year_to_date(
        plan_data, milestone_map, state.triggered_milestones,
        newly_triggered, year, 0.0, income_active_until,
    ).get("_pre_start_income_by_id", {}) if ytd_imputed else {})
    def ss_calendar_window(income, until=1.0):
        end = min(until, income_active_until[income.id])
        share = prorate_for_year(milestone_map.get(income.start_milestone_id), milestone_map.get(income.end_milestone_id), income.start_month, income.end_month, state.triggered_milestones, newly_triggered, year, plan_data.birth_month, 1.0, active_until=end)
        return payment_share(income, year, start_year, state.triggered_milestone_years,
            share, 1.0, end,
            resolve_trigger_month(milestone_map.get(income.start_milestone_id), plan_data.birth_month, year))
    def ss_calendar_before(income, until):
        share = ss_calendar_window(income)
        return ss_calendar_amounts.get(income.id, 0.0) * ss_calendar_window(income, until) / share if share else 0.0
    def survivor_before_fra(fra):
        return calculate_survivor_top_up(max(0.0, min(1.0, (fra - month_index(year, 1)) / 12)))
    def earnings_share_before(job, before_fraction):
        until = min(before_fraction, income_active_until[job.id])
        share = prorate_for_year(
            milestone_map.get(job.start_milestone_id), milestone_map.get(job.end_milestone_id),
            job.start_month, job.end_month, state.triggered_milestones, newly_triggered,
            year, plan_data.birth_month, year_fraction, active_until=until,
        )
        return payment_share(job, year, start_year, state.triggered_milestone_years,
            share, year_fraction, until,
            resolve_trigger_month(milestone_map.get(job.start_milestone_id), plan_data.birth_month, year))
    def active_in_month(income, month):
        return prorate_for_year(
            milestone_map.get(income.start_milestone_id), milestone_map.get(income.end_milestone_id),
            income.start_month, income.end_month, state.triggered_milestones, newly_triggered,
            year, plan_data.birth_month, 1.0, active_until=min(month / 12, income_active_until[income.id]),
            active_from=(month - 1) / 12,
        ) > 0
    def service_months(owner):
        """Calendar months in which the owner works for earned income.

        Every working month counts as a service month; the monthly exempt
        amount and the substantial-services test are not modeled.
        """
        months = set()
        for job in plan_data.income_streams:
            if job.owner != owner or not job.is_earned_income or job.is_social_security:
                continue
            if not (ss_calendar_amounts.get(job.id, 0.0) if ytd_imputed else income_by_id.get(job.id, 0.0)):
                continue
            if job.frequency == "once":
                months.add(job.start_month or resolve_trigger_month(
                    milestone_map.get(job.start_milestone_id), plan_data.birth_month, year))
            else:
                months.update(m for m in range(1, 13) if active_in_month(job, m))
        return months
    def grace_year_share(key, owner, entitlement, benefit_months):
        """Share of withholdable benefit months under the grace-year rule.

        20 CFR 404.435: in the first year with a non-service month at or
        after entitlement, only benefits for service months can be
        withheld. Other years return 1.0 (the annual test applies to every
        month). Entitlement before the plan's start year is assumed to have
        had its grace year already, since earlier service is unknown.
        Projected-only cash excludes months before the plan starts.
        """
        service = service_months(owner)
        if (key in ss_grace_used or entitlement < month_index(start_year, 1)
                or all(m in service for m in benefit_months)):
            return 1.0
        ss_grace_used.add(key)
        opening = 0 if ytd_imputed or year != start_year else round(12 * (1 - year_fraction))
        window = [m for m in benefit_months if m > opening]
        return sum(m in service for m in window) / len(window) if window else 0.0
    for inc in plan_data.income_streams:
        if not inc.is_social_security or inc.ss_worker_income_id:
            continue
        birth, birth_month = owner_birth(plan_data, inc.owner)
        fra = retirement_fra_index(birth, month_index(birth, birth_month))
        pre_fra = max(0.0, min(1.0, (fra - month_index(year, 1)) / 12))
        if not pre_fra:
            continue
        earnings = 0.0
        for job in plan_data.income_streams:
            if job.owner != inc.owner or not job.is_earned_income or job.is_social_security:
                continue
            amount = income_by_id.get(job.id, 0.0)
            share = income_active_share.get(job.id, 0.0)
            if ytd_imputed:
                amount = ss_calendar_amounts.get(job.id, 0.0)
                share = ss_calendar_window(job)
            if not amount or not share:
                continue
            before = earnings_share_before(job, pre_fra)
            if ytd_imputed:
                before = ss_calendar_window(job, pre_fra)
            earnings += amount * before / share
        if has_provided_ytd and year == start_year:
            history_share = max(0.0, 1 - year_fraction)
            before_share = min(pre_fra, history_share)
            history_earned = sum(float(ytd.get(key, {}).get(inc.owner, 0.0)) for key in ("w2_income_by_owner", "self_employment_income_by_owner"))
            earnings += history_earned * before_share / history_share if history_share else 0.0
        linked = [i for i in plan_data.income_streams if i.ss_worker_income_id == inc.id]
        survivor_owner = "spouse" if state.primary_deceased else "self"
        # Grace year: benefits for non-service months are protected.
        claim = ss_claims[inc.id]
        cap_share = grace_year_share(inc.id, inc.owner, claim, [
            m for m in range(1, 13)
            if claim <= month_index(year, m) < fra and active_in_month(inc, m)])
        eligible_amounts = {}
        post_start_eligible = {}
        for benefit in [inc, *linked]:
            share = income_active_share.get(benefit.id, 0.0)
            before = prorate_for_year(milestone_map.get(benefit.start_milestone_id), milestone_map.get(benefit.end_milestone_id), benefit.start_month, benefit.end_month, state.triggered_milestones, newly_triggered, year, plan_data.birth_month, year_fraction, active_until=min(pre_fra, income_active_until[benefit.id]))
            eligible_amounts[benefit.id] = income_grown_by_id.get(benefit.id, 0.0) * before if share else 0.0
            post_start_eligible[benefit.id] = eligible_amounts[benefit.id]
            if ytd_imputed:
                eligible_amounts[benefit.id] = ss_calendar_before(benefit, pre_fra)
        if survivor_amount and inc.owner == survivor_owner:
            eligible_amounts['survivor'] = survivor_before_fra(fra)
        available = sum(eligible_amounts.values()) * cap_share
        ss_owner_test_due[inc.owner] = earnings_test_due(year, fra, earnings, ss_wage_index)
        due = min(available, ss_owner_test_due[inc.owner])
        total = sum(eligible_amounts.values())
        if due and total:
            for identity, amount in eligible_amounts.items():
                deduction = due * amount / total
                if ytd_imputed and identity != 'survivor':
                    post_deduction = deduction * post_start_eligible.get(identity, 0.0) / amount if amount else 0.0
                    history_deduction = deduction - post_deduction
                    past = ytd.get("_pre_start_income_by_id", {})
                    history_deduction = min(history_deduction, past.get(identity, 0.0))
                    past[identity] = max(0.0, past.get(identity, 0.0) - history_deduction)
                    ytd["social_security_income"] = max(0.0, ytd.get("social_security_income", 0.0) - history_deduction)
                    deduction = post_deduction
                reductions[identity] = reductions.get(identity, 0.0) + deduction
                record_withheld(inc.owner, deduction)
            annual = income_grown_by_id.get(inc.id, 0.0)
            if ytd_imputed:
                full_share = ss_calendar_window(inc)
                annual = ss_calendar_amounts.get(inc.id, 0.0) / full_share if full_share else 0.0
            ss_withheld_months[inc.id] = ss_withheld_months.get(inc.id, 0) + fully_withheld_months(due * eligible_amounts.get(inc.id, 0.0) / total, annual, 12 * pre_fra)
            # Auxiliary spousal-type benefits on this record count their
            # own fully withheld months before the recipient's FRA.
            for benefit in linked:
                if not benefit.ss_spousal_reduction or not eligible_amounts.get(benefit.id):
                    continue
                aux_birth, aux_birth_month = owner_birth(plan_data, benefit.owner)
                aux_fra = retirement_fra_index(aux_birth, month_index(aux_birth, aux_birth_month))
                aux_months = min(12 * pre_fra, max(0, aux_fra - month_index(year, 1)))
                aux_annual = income_grown_by_id.get(benefit.id, 0.0)
                if ytd_imputed:
                    full_share = ss_calendar_window(benefit)
                    aux_annual = ss_calendar_amounts.get(benefit.id, 0.0) / full_share if full_share else 0.0
                aux_pool = benefit.ss_spousal_reduction[0]
                ss_aux_withheld_months[aux_pool] = ss_aux_withheld_months.get(aux_pool, 0) + fully_withheld_months(
                    due * eligible_amounts[benefit.id] / total, aux_annual, aux_months)
    survivor_history_net = 0.0
    if survivor_amount and survivor_context and survivor_context.own is None:
        recipient = survivor_context.recipient
        birth, birth_month = owner_birth(plan_data, recipient)
        fra = retirement_fra_index(birth, month_index(birth, birth_month))
        pre_fra = max(0.0, min(1.0, (fra - month_index(year, 1)) / 12))
        earnings = 0.0
        for job in plan_data.income_streams:
            if job.owner != recipient or not job.is_earned_income or job.is_social_security:
                continue
            paid = income_by_id.get(job.id, 0.0)
            share = income_active_share.get(job.id, 0.0)
            if ytd_imputed:
                paid = ss_calendar_amounts.get(job.id, 0.0)
                share = ss_calendar_window(job)
            if share:
                before = earnings_share_before(job, pre_fra)
                if ytd_imputed:
                    before = ss_calendar_window(job, pre_fra)
                earnings += paid * before / share
        if has_provided_ytd and year == start_year:
            history_share = max(0.0, 1 - year_fraction)
            historical = sum(float(ytd.get(key, {}).get(recipient, 0.0)) for key in ("w2_income_by_owner", "self_employment_income_by_owner"))
            earnings += historical * min(pre_fra, history_share) / history_share if history_share else 0.0
        ss_owner_test_due[recipient] = earnings_test_due(year, fra, earnings, ss_wage_index)
        eligible = survivor_before_fra(fra)
        cap_share = grace_year_share(("survivor", recipient), recipient, survivor_context.start_month_index, [
            m for m in range(1, 13)
            if survivor_context.start_month_index <= month_index(year, m) < fra])
        if ytd_imputed:
            calendar_eligible = calculate_survivor_top_up(pre_fra, fraction=1.0)
            annual_due = min(calendar_eligible * cap_share, ss_owner_test_due[recipient])
            reductions['survivor'] = annual_due * eligible / calendar_eligible if calendar_eligible else 0.0
            survivor_history_net = max(0.0, calculate_survivor_top_up(fraction=1.0) - survivor_amount - (annual_due - reductions['survivor']))
            ytd['social_security_income'] = ytd.get('social_security_income', 0.0) + survivor_history_net
        else:
            reductions['survivor'] = min(eligible * cap_share, ss_owner_test_due[recipient])
        record_withheld(recipient, reductions['survivor'])
        survivor_owner = recipient
    if survivor_context and survivor_context.pia_annual and survivor_amount:
        recipient = survivor_context.recipient
        birth, birth_month = owner_birth(plan_data, recipient)
        survivor_fra = month_index(birth, birth_month) + survivor_fra_months(birth)
        own_id = survivor_context.own.id if survivor_context.own else ''
        withheld = reductions.get('survivor', 0.0) + reductions.get(own_id, 0.0)
        annual_survivor = grown_benefit(survivor_context.deceased, income_growth_factors, social_security_inflation_factor, survivor_context.pia_annual)
        max_months = max(0, min(12, survivor_fra - max(month_index(year, 1), survivor_context.start_month_index)))
        ss_survivor_withheld_months += fully_withheld_months(withheld, annual_survivor, max_months)
    if reductions:
        for index, inc in enumerate(plan_data.income_streams):
            reduction = reductions.get(inc.id, 0.0)
            if reduction:
                income_by_id[inc.id] -= reduction
                amount, pct = income_details[index]
                income_details[index] = (amount - reduction, pct)
                state.record_retirement_income(inc.owner, "social_security", -reduction)
                for source in cf_income_sources:
                    if source.name == inc.name:
                        source.amount -= reduction
                        break
        if reductions.get('survivor'):
            reduction = reductions['survivor']
            survivor_amount -= reduction
            state.record_retirement_income(survivor_owner, "social_security", -reduction)
            income_details[-1] = (survivor_amount, 0.0)
            cf_income_sources[-1].amount -= reduction
        ss_earnings_test_withheld = sum(reductions.values())
        ss_income -= ss_earnings_test_withheld
    # One auxiliary benefit at a time (Act 202(k)): a stream paid as the
    # excess of a larger benefit over the household spousal benefit tops
    # up to the larger benefit when the partner's earnings withhold the
    # spousal benefit. The top-up stays subject to the claimant's own
    # earnings test.
    if reductions:
        aux_streams = {stream.id: stream for stream in plan_data.income_streams}
        def aux_window(stream, fraction):
            return prorate_for_year(
                milestone_map.get(stream.start_milestone_id), milestone_map.get(stream.end_milestone_id),
                stream.start_month, stream.end_month, state.triggered_milestones, newly_triggered,
                year, plan_data.birth_month, year_fraction,
                active_until=min(fraction, income_active_until[stream.id]),
            )
        def aux_pre_fra(owner):
            birth, birth_month = owner_birth(plan_data, owner)
            fra = retirement_fra_index(birth, month_index(birth, birth_month))
            return max(0.0, min(1.0, (fra - month_index(year, 1)) / 12))
        for inc in plan_data.income_streams:
            if not inc.ss_aux_offset or not income_active_share.get(inc.id):
                continue
            aux_offset_id, aux_larger_annual, aux_offset_annual = inc.ss_aux_offset
            aux_offset_stream = aux_streams.get(aux_offset_id)
            aux_offset_withheld = reductions.get(aux_offset_id, 0.0)
            if not aux_offset_withheld or aux_offset_stream is None or aux_offset_stream.ss_worker_income_id not in aux_streams:
                continue
            aux_worker_pre_fra = aux_pre_fra(aux_streams[aux_offset_stream.ss_worker_income_id].owner)
            aux_overlap = aux_window(inc, aux_worker_pre_fra)
            aux_eligible = aux_window(aux_offset_stream, aux_worker_pre_fra)
            if not aux_overlap or not aux_eligible:
                continue
            aux_growth = income_growth_factors[inc.id]
            aux_larger = aux_larger_annual * aux_growth * aux_overlap
            aux_offset_paid = aux_offset_annual * aux_growth * aux_overlap
            aux_withheld_here = min(aux_offset_withheld * aux_overlap / aux_eligible, aux_offset_paid)
            aux_increase = max(0.0, aux_larger - aux_offset_paid + aux_withheld_here) - max(0.0, aux_larger - aux_offset_paid)
            if aux_increase <= 0:
                continue
            aux_claimant = inc.ss_worker_income_id
            aux_group = {aux_claimant, *(stream.id for stream in plan_data.income_streams if stream.ss_worker_income_id == aux_claimant)}
            aux_deducted = sum(reductions.get(identity, 0.0) for identity in aux_group)
            if survivor_context and survivor_context.recipient == inc.owner:
                aux_deducted += reductions.get('survivor', 0.0)
            aux_remaining = max(0.0, ss_owner_test_due.get(inc.owner, 0.0) - aux_deducted)
            aux_testable = aux_increase * aux_window(inc, min(aux_worker_pre_fra, aux_pre_fra(inc.owner))) / aux_overlap
            aux_extra = min(aux_remaining, aux_testable)
            if aux_extra:
                reductions[inc.id] = reductions.get(inc.id, 0.0) + aux_extra
                record_withheld(inc.owner, aux_extra)
            aux_paid = aux_increase - aux_extra
            ss_earnings_test_withheld += aux_extra - aux_increase
            if aux_paid <= 0:
                continue
            ss_income += aux_paid
            income_by_id[inc.id] += aux_paid
            index = next(i for i, value in enumerate(plan_data.income_streams) if value.id == inc.id)
            amount, pct = income_details[index]
            income_details[index] = (amount + aux_paid, pct)
            state.record_retirement_income(inc.owner, "social_security", aux_paid)
            for source in cf_income_sources:
                if source.name == inc.name:
                    source.amount += aux_paid
                    break
    for inc in plan_data.income_streams:
        spousal_type = bool(inc.ss_worker_income_id and inc.ss_spousal_reduction)
        if not inc.is_social_security or (inc.ss_worker_income_id and not spousal_type):
            continue
        birth, birth_month = owner_birth(plan_data, inc.owner)
        fra = retirement_fra_index(birth, month_index(birth, birth_month))
        if not month_index(year, 1) < fra < month_index(year + 1, 1):
            continue
        revised_factor = spousal_arf(inc) if spousal_type else arf_factor(plan_data, inc, ss_claims[inc.id], ss_withheld_months.get(inc.id, 0))
        post_share = prorate_for_year(milestone_map.get(inc.start_milestone_id), milestone_map.get(inc.end_milestone_id), inc.start_month, inc.end_month, state.triggered_milestones, newly_triggered, year, plan_data.birth_month, year_fraction, active_from=(fra - month_index(year, 1))/12, active_until=income_active_until[inc.id])
        previous_factor = ss_adjustments.get(inc.id, 1.0)
        addition = inc.annual_amount * income_growth_factors[inc.id] * (revised_factor - previous_factor) * post_share
        if ytd_imputed and revised_factor > previous_factor:
            full_post = ss_calendar_window(inc) - ss_calendar_window(inc, (fra - month_index(year, 1))/12)
            historical_post = max(0.0, full_post - post_share)
            history_addition = inc.annual_amount * income_growth_factors[inc.id] * (revised_factor - previous_factor) * historical_post
            past = ytd.get("_pre_start_income_by_id", {})
            past[inc.id] = past.get(inc.id, 0.0) + history_addition
            ytd["social_security_income"] = ytd.get("social_security_income", 0.0) + history_addition
        if addition > 0:
            ss_income += addition
            income_by_id[inc.id] += addition
            index = next(i for i, value in enumerate(plan_data.income_streams) if value.id == inc.id)
            amount, pct = income_details[index]
            income_details[index] = (amount + addition, pct)
            state.record_retirement_income(inc.owner, "social_security", addition)
            for source in cf_income_sources:
                if source.name == inc.name:
                    source.amount += addition
                    break
    if survivor_context and survivor_gross_amount:
        survivor_arf = survivor_arf_annual(plan_data, survivor_context, ss_survivor_withheld_months)
        revised_survivor = calculate_survivor_top_up()
        # Reconcile the survivor entitlement only within earnings-test
        # months. Own retirement credits start at retirement FRA; they
        # cannot reduce withholding in earlier survivor-FRA months.
        revised_before_retirement = calculate_survivor_top_up(
            max(0.0, min(1.0, (survivor_retirement_fra - month_index(year, 1)) / 12))
        )
        increase_before_retirement = max(0.0, revised_before_retirement - survivor_pre_retirement_gross)
        if increase_before_retirement:
            own_id = survivor_context.own.id if survivor_context.own else ''
            deducted = reductions.get(own_id, 0.0) + reductions.get('survivor', 0.0)
            remaining_due = max(0.0, ss_owner_test_due.get(survivor_context.recipient, 0.0) - deducted)
            extra_withheld = min(remaining_due, increase_before_retirement)
            reductions['survivor'] = reductions.get('survivor', 0.0) + extra_withheld
            ss_earnings_test_withheld += extra_withheld
            record_withheld(survivor_context.recipient, extra_withheld)
        revised_paid = max(0.0, revised_survivor - reductions.get('survivor', 0.0))
        difference = revised_paid - survivor_amount
        if difference:
            ss_income += difference
            state.record_retirement_income(survivor_context.recipient, 'social_security', difference)
            income_details[-1] = (revised_paid, 0.0)
            for source in cf_income_sources:
                if source.name == 'Social Security survivor top-up':
                    source.amount += difference
                    break
            survivor_amount = revised_paid
    return ss_income, ss_earnings_test_withheld, ss_survivor_withheld_months, withheld_by_earner


def _rental_activity(
    state: SimState, plan_data: PlanData, year: int, *, start_year: int,
    asset_fractions: Mapping[str, float], asset_windows: Mapping[str, tuple[float, float]],
    purchases_this_year: list[tuple[RealAssetData, real_estate.PurchaseTerms]],
    rental_building_basis: Mapping[str, float | None], coverage_warnings: set[str],
    cf_income_sources: list[NamedAmount],
) -> tuple[dict[str, real_estate.RentalYear], dict[str, float], float, float]:
    """Step 3: each rental's rent, operating expenses and depreciation for the year.

    Returns (activity by rental, rental-use share by rental, rent collected,
    operating expenses).
    """
    rental_year: dict[str, real_estate.RentalYear] = {}
    # Rental-use share of each rental this year; a mixed-use property's
    # rent, expenses, depreciation, carrying costs and interest follow it.
    rental_share: dict[str, float] = {}
    rental_cash_income = 0.0
    rental_operating_expenses = 0.0
    purchased_ids = {asset.id for asset, _ in purchases_this_year}
    for asset in plan_data.real_assets:
        if not real_estate.is_rental(asset) or asset.id not in asset_windows:
            continue
        fraction = asset_fractions[asset.id]
        share = rental_share[asset.id] = real_estate.rental_use_share(asset, year)
        if real_estate.is_mixed_use(asset):
            coverage_warnings.add(
                f"{asset.name}: the rented share is modeled as a separate rental activity. The "
                "limit that caps rental deductions at rental income for a home you also use "
                "personally is not applied.")
        growth = (state.inflation_factor if asset.rental_income_growth_rate is None
                  else (1.0 + asset.rental_income_growth_rate) ** (year - start_year))
        rent = (max(0.0, asset.rental_income) * growth
                * (1.0 - min(1.0, max(0.0, asset.vacancy_rate))) * fraction * share)
        operating = (rent * max(0.0, asset.rental_expense_rate) if asset.rental_expense_rate is not None
                     else max(0.0, asset.rental_expenses) * state.inflation_factor * fraction * share)
        depreciation = 0.0
        building = rental_building_basis.get(asset.id)
        if building is None:
            coverage_warnings.add(
                f"{asset.name}: rental depreciation is omitted because the land value share or "
                "building basis is not entered. Depreciation and its recapture on sale are understated.")
        elif fraction > 0 or asset.sale_year == year:
            # A sale at the start of January still disposes mid-month.
            window_start, window_end = asset_windows[asset.id]
            # Mid-month convention: placed in service and disposed of at
            # the midpoint of the month (IRC 168(d)(2), (d)(4)(B)).
            if asset.id in purchased_ids:
                window_start += 0.5
            if asset.sale_year == year:
                window_end += 0.5
            taken = state.real_estate_depreciation.get(asset.id, 0.0) + (
                0.0 if asset.id in state.real_asset_purchase_dates else max(0.0, asset.prior_depreciation))
            depreciation = real_estate.depreciation_for_year(
                building, real_estate.recovery_years(asset), taken, window_start, window_end, share)
            state.real_estate_depreciation[asset.id] = (
                state.real_estate_depreciation.get(asset.id, 0.0) + depreciation)
        rental_year[asset.id] = real_estate.RentalYear(
            asset_id=asset.id, rent=rent, operating=operating, depreciation=depreciation,
            active_participation=asset.rental_active_participation,
            qbi_eligible=asset.qbi_eligible,
        )
        rental_cash_income += rent
        rental_operating_expenses += operating
        if rent > 0:
            cf_income_sources.append(NamedAmount(name=f"{asset.name} rent", amount=rent))
    return rental_year, rental_share, rental_cash_income, rental_operating_expenses


def _sepp_distribution(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, *,
    prior_year_balances: Mapping[str, float], gross_income: float, cf_income_sources: list[NamedAmount],
) -> tuple[float, float, float, float]:
    """Step 3b: pay the year's SEPP 72(t) series payment.

    Returns (payment, additional tax on an unqualified custom amount, share of
    the year the series runs, gross income including the payment).
    """
    sepp_income = 0.0
    sepp_penalty = 0.0
    sepp = plan_data.sepp_settings
    sepp_fraction = 0.0
    if sepp is not None and sepp.enabled and sepp.source_account_id is not None:
        source = plan_data.accounts.get(sepp.source_account_id)
        sepp_owner = ("spouse" if source is not None and source.owner == "spouse"
                      and plan_data.spouse_birth_year is not None else "self")
        sepp_age = year - (plan_data.spouse_birth_year if sepp_owner == "spouse" else plan_data.birth_year)
        sepp_fraction = sepp_year_fraction(
            sepp_age, sepp.start_age,
            plan_data.spouse_birth_month if sepp_owner == "spouse" else plan_data.birth_month,
            year_fraction, lifecycle.owner_alive_until(plan_data, state, sepp_owner, year),
        )
        if sepp.source_account_id in state.locked_account_ids:
            # A withdrawal-locked source pays nothing until it unlocks.
            sepp_fraction = 0.0
    if sepp_fraction > 0:
        # Always let calculate_sepp() use IRS Single Life Table
        sepp_divisor = None
        # Notice 2022-6 sec. 3.02(d): the balance is determined reasonably,
        # e.g. as of the prior December 31, never with this year's growth.
        # The opening year uses the entered balance, as /sepp-preview does.
        balance = prior_year_balances.get(sepp.source_account_id,
                                          state.get_balance(sepp.source_account_id))

        if sepp.annual_amount is not None:
            # A custom amount keeps the 72(t) exemption only when it equals
            # an approved method's payment; it is judged once, at the start.
            if state.sepp_fixed_amount is None:
                state.sepp_fixed_amount = sepp.annual_amount
                sepp_first = first_distribution_month(
                    plan_data.spouse_birth_year if sepp_owner == "spouse" else plan_data.birth_year,
                    plan_data.spouse_birth_month if sepp_owner == "spouse" else plan_data.birth_month,
                    sepp.start_age,
                )
                state.sepp_custom_qualified = custom_amount_qualifies(
                    sepp.annual_amount, balance, sepp_age, sepp.method, sepp.interest_rate,
                    sepp_rate_ceiling(*sepp_first))
            sepp_income = state.sepp_fixed_amount
        elif sepp.method == "rmd_method":
            # RMD recalculates each year from the prior year-end balance
            sepp_income = calculate_sepp(
                account_balance=balance,
                owner_age=sepp_age,
                method=sepp.method,
                interest_rate=sepp.interest_rate,
                life_expectancy_divisor=sepp_divisor,
            )
        else:
            # Fixed methods: compute once, reuse cached amount
            if state.sepp_fixed_amount is None:
                state.sepp_fixed_amount = calculate_sepp(
                    account_balance=balance,
                    owner_age=sepp_age,
                    method=sepp.method,
                    interest_rate=sepp.interest_rate,
                    life_expectancy_divisor=sepp_divisor,
                )
            sepp_income = state.sepp_fixed_amount

        # Cap at the available balance and, like RMDs, reserve the growth
        # the payments forgo by leaving the account during the year.
        growth_factor = state.withdrawal_growth_factors.get(sepp.source_account_id, 0.0)
        available = max(0.0, state.get_balance(sepp.source_account_id)) / (1 + growth_factor)
        scheduled_sepp = sepp_income * sepp_fraction
        sepp_income = min(scheduled_sepp, available)
        if sepp_income < scheduled_sepp - 0.005:
            # The account cannot pay the series: a modification (72(t)(4)).
            state.sepp_underfunded = True

        if sepp_income > 0:
            drag = sepp_income * growth_factor
            state.accounts[sepp.source_account_id].balance -= drag
            state.withdrawal_growth_adjustment -= drag
            sepp_account = state.accounts.get(sepp.source_account_id)
            if sepp_account is not None and sepp_account.account_type in ACCOUNT_TYPE_SOURCES:
                state.record_retirement_income(
                    sepp_account.owner, ACCOUNT_TYPE_SOURCES[sepp_account.account_type], sepp_income,
                    account_id=sepp.source_account_id)
            state.withdraw_from(sepp.source_account_id, sepp_income)
            gross_income += sepp_income
            cf_income_sources.append(NamedAmount(name="SEPP 72(t)", amount=sepp_income, source="sepp"))
            if (state.sepp_custom_qualified is False and sepp_account is not None
                    and sepp_account.account_type in EARLY_WITHDRAWAL_PENALTY_TYPES
                    and sepp_account.account_type not in ROTH_TYPES
                    and sepp_account.inherited_year is None
                    and not penalty_free_by_separation(
                        sepp_account.account_type, sepp_account.inherited_year,
                        sepp_account.distribution_settings, sepp_age, year)):
                # An unvalidated amount is an ordinary early distribution.
                sepp_penalty = sepp_income * early_withdrawal_penalty_rate(
                    sepp_age, plan_data.spouse_birth_month if sepp_owner == "spouse" else plan_data.birth_month,
                    year_fraction, state.early_distribution_state_rates)
    return sepp_income, sepp_penalty, sepp_fraction, gross_income


def _allocate_payroll(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, age: int, *,
    w2_by_owner: Mapping[str, float], se_by_owner: Mapping[str, float],
    prior_w2_by_owner: Mapping[str, float] | None, ytd: Mapping[str, Any],
    federal_inflation_factor: float, income_by_id: Mapping[str, float],
    income_active_share: Mapping[str, float], known_hsa: Mapping[str, Any], coverage_warnings: set[str],
) -> tuple[list, set[str], set[str], dict[str, float]]:
    """Step 4: fund the payroll contribution rules from this year's pay.

    Returns (payroll contributions, W-2 and self-employment income ids,
    FICA wages by owner after section 125 HSA reductions).
    """
    state.compensation_by_owner = {
        owner: w2_by_owner.get(owner, 0.0) + se_by_owner.get(owner, 0.0)
        for owner in w2_by_owner.keys() | se_by_owner.keys()
    }
    # SECURE 2.0 Roth catch-up test on prior-year W-2 wages. The opening
    # year has no wage history, so its own projected wages stand in,
    # annualized for a partial year like the expense basis (year-to-date
    # wages are history, not the annual rate). A zero-length opening year
    # has no rate and stays Roth-only.
    if prior_w2_by_owner is not None:
        catchup_wages: dict[str, float] | None = prior_w2_by_owner
    elif year_fraction > 0:
        opening_ytd_w2 = ytd.get("w2_income_by_owner", {})
        catchup_wages = {owner: (amount - opening_ytd_w2.get(owner, 0.0)) / year_fraction
                         for owner, amount in w2_by_owner.items()}
    else:
        catchup_wages = None
    state.roth_catchup_owners = {
        owner for owner in ("self", "spouse")
        if year >= 2026 and (catchup_wages is None or catchup_wages.get(owner, 0.0)
            > _CONTRIBUTION_DATA["roth_catchup_wage_threshold"] * state.coverage_inflation_factor)
    }
    w2_income_ids = {inc.id for inc in plan_data.income_streams
                     if inc.is_earned_income and not inc.is_self_employed and not inc.is_social_security}
    self_employment_income_ids = {inc.id for inc in plan_data.income_streams
                                  if inc.is_earned_income and inc.is_self_employed and not inc.is_social_security}
    state.self_employment_plan_ids = {
        p.target_account_id for p in plan_data.priorities
        if p.source_income_id in self_employment_income_ids and p.target_account_id in state.accounts
        and state.accounts[p.target_account_id].account_type in ANNUAL_ADDITIONS_415C_TYPES}
    # Pub. 560 rate table for the self-employed: the 25% plan rate allows
    # 20% of net profit less the deductible half of SE tax. Opening
    # employer history cannot be tied to a business, so it is not netted.
    plan_rate = _CONTRIBUTION_DATA["self_employed_plan_rate"]
    self_employed_employer_room = {
        owner: plan_rate / (1.0 + plan_rate) * max(0.0, profit - calculate_mixed_fica_tax(
            w2_by_owner.get(owner, 0.0), profit, state.current_filing_status or plan_data.filing_status,
            federal_inflation_factor, year)["se_employer_half"])
        for owner, profit in se_by_owner.items()
    }
    payroll_contributions = allocate_payroll_contributions(
        plan_data.priorities,
        {inc.id: income_by_id.get(inc.id, 0.0) for inc in plan_data.income_streams
         if inc.is_earned_income and not inc.is_social_security},
        state,
        age,
        contribution_fraction=year_fraction,
        income_owners={inc.id: inc.owner for inc in plan_data.income_streams
                       if inc.is_earned_income and not inc.is_social_security},
        w2_income_ids=w2_income_ids,
        self_employment_income_ids=self_employment_income_ids,
        self_employed_employer_room=self_employed_employer_room,
        # Owner-level year-to-date wages cannot be tied to one employer's
        # plan, so only imputed per-stream pre-start pay is netted.
        prior_compensation_by_income=ytd.get("_pre_start_income_by_id"),
        pay_months_by_income={iid: max(1, min(12, round(12 * share)))
                              for iid, share in income_active_share.items()},
    )
    # Pub 15: only explicit section 125 salary reductions lower FICA
    # wages. Employer deposits are already excluded from gross wages;
    # direct contributions and savings-waterfall funding do not lower FICA.
    fica_w2_by_owner = dict(w2_by_owner)
    for contribution in payroll_contributions:
        account = state.accounts[contribution.target_account_id]
        if account.account_type != "hsa":
            continue
        funding = known_hsa.get(account.owner, {}).get("payroll_funding")
        if funding == "cafeteria":
            fica_w2_by_owner[account.owner] = max(0.0, fica_w2_by_owner.get(account.owner, 0.0) - contribution.employee_amount)
        elif funding is None and contribution.employee_amount:
            coverage_warnings.add("HSA payroll funding is unknown; no cafeteria-plan FICA exclusion is assumed. Confirm whether employee funding is section 125 salary reduction or direct after-tax funding.")
    return payroll_contributions, w2_income_ids, self_employment_income_ids, fica_w2_by_owner


class _PayrollTaxTreatment(NamedTuple):
    """Step 4 payroll amounts by tax treatment."""

    after_tax_payroll: float
    # Schedule 1 adjustments for self-employed pre-tax contributions.
    self_employed_adjustments: float
    # Retirement-plan deductions tied to the business (they reduce QBI).
    self_employed_plan_deductions: float
    payroll_retirement_by_account: dict[str, float]
    payroll_retirement_deductions: float
    payroll_ira_deductions: float
    payroll_nj_deferrals: float
    nj_employer_403b_by_account: dict[str, float]
    payroll_tax_deductions: float
    payroll_deductions: float
    employer_contribution_income: float
    roth_employer_income: float


def _payroll_tax_treatment(
    state: SimState, payroll_contributions: list, *, w2_income_ids: set[str],
    self_employment_income_ids: set[str], coverage_warnings: set[str],
) -> _PayrollTaxTreatment:
    """Step 4: how the year's payroll contributions are taxed and paid."""
    def is_pre_tax(contribution) -> bool:
        return state.accounts[contribution.target_account_id].account_type in _PRE_TAX_CONTRIBUTION_TYPES

    payroll_contribution_deductions = sum(
        contribution.employee_amount for contribution in payroll_contributions
        if is_pre_tax(contribution)
    )
    after_tax_payroll = sum(c.employee_amount for c in payroll_contributions) - payroll_contribution_deductions
    # A self-employed person's own "employer" contribution is paid from
    # business profit already in gross income, so unlike W-2 employer
    # money it leaves cash. Their pre-tax contributions are Schedule 1
    # adjustments, not reductions of W-2 wages.
    self_employed_contributions = [c for c in payroll_contributions
                                   if c.source_income_id in self_employment_income_ids]
    self_employed_deferrals = sum(c.employee_amount for c in self_employed_contributions if is_pre_tax(c))
    self_employed_employer_pre_tax = sum(c.employer_amount for c in self_employed_contributions if is_pre_tax(c))
    after_tax_payroll += sum(c.employer_amount for c in self_employed_contributions if not is_pre_tax(c))
    self_employed_adjustments = self_employed_deferrals + self_employed_employer_pre_tax
    # Treas. Reg. 1.199A-3(b)(1)(vi): retirement-plan deductions tied to
    # the business reduce QBI; personal HSA deductions do not.
    self_employed_plan_deductions = sum(
        c.employee_amount + c.employer_amount for c in self_employed_contributions
        if state.accounts[c.target_account_id].account_type in TRADITIONAL_EMPLOYER_PLAN_TYPES
    )
    # Employee deferrals plus a self-employed person's own "employer"
    # share; W-2 employer money never entered gross income.
    payroll_retirement_by_type: dict[str, float] = {}
    # The same amounts by account, for the state-taxed contribution basis.
    payroll_retirement_by_account: dict[str, float] = {}
    for c in payroll_contributions:
        account_type = state.accounts[c.target_account_id].account_type
        if account_type in _RETIREMENT_CONTRIBUTION_TYPES:
            amount = (c.employee_amount
                      + (c.employer_amount if c.source_income_id in self_employment_income_ids else 0.0))
            payroll_retirement_by_type[account_type] = payroll_retirement_by_type.get(account_type, 0.0) + amount
            payroll_retirement_by_account[c.target_account_id] = (
                payroll_retirement_by_account.get(c.target_account_id, 0.0) + amount)
    payroll_retirement_deductions = sum(payroll_retirement_by_type.values())
    payroll_ira_deductions = payroll_retirement_by_type.get("traditional_ira", 0.0)
    # NJ adds 403(b) and 457 deferrals and W-2 employer 403(b) money. Only
    # payroll rules can fund these plans, so the surplus waterfall has none.
    payroll_nj_deferrals = sum(payroll_retirement_by_type.get(t, 0.0) for t in _NJ_TAXED_DEFERRAL_TYPES) + sum(
        c.employer_amount for c in payroll_contributions
        if c.source_income_id not in self_employment_income_ids
        and state.accounts[c.target_account_id].account_type == "traditional_403b")
    nj_employer_403b_by_account: dict[str, float] = {}
    for c in payroll_contributions:
        if (c.source_income_id not in self_employment_income_ids
                and state.accounts[c.target_account_id].account_type == "traditional_403b"):
            nj_employer_403b_by_account[c.target_account_id] = (
                nj_employer_403b_by_account.get(c.target_account_id, 0.0) + c.employer_amount)
    # ``payroll_deductions`` is the cash-flow/paycheck outflow reported to
    # clients. Keep a separate tax-only accumulator because an after-tax
    # payroll expense still reduces pay but cannot reduce taxable wages.
    payroll_tax_deductions = payroll_contribution_deductions - self_employed_deferrals
    payroll_deductions = payroll_contribution_deductions + self_employed_employer_pre_tax
    employer_contribution_income = sum(
        contribution.employer_amount
        for contribution in payroll_contributions
        if contribution.source_income_id not in self_employment_income_ids
    )
    # SECURE 2.0 sec. 604: an employer contribution to a designated Roth
    # account is the employee's Roth election. It is taxable income for
    # the contribution year, but neither FICA wages nor cash pay (IRS
    # Notice 2024-2, section L). Pre-tax employer money stays untaxed.
    roth_employer_income = sum(
        contribution.employer_amount for contribution in payroll_contributions
        if contribution.source_income_id in w2_income_ids
        and state.accounts[contribution.target_account_id].account_type in ROTH_EMPLOYER_PLAN_TYPES
    )
    if roth_employer_income > 0:
        for family in sorted({EMPLOYER_PLAN_FAMILY[state.accounts[c.target_account_id].account_type] for c in payroll_contributions
                              if c.employer_amount > 0 and c.source_income_id in w2_income_ids
                              and state.accounts[c.target_account_id].account_type in ROTH_EMPLOYER_PLAN_TYPES}):
            coverage_warnings.add(f"Employer contributions to a Roth {family} are taxed as income in the year they are made. Choose a traditional {family} for employer money your plan contributes pre-tax.")
    return _PayrollTaxTreatment(
        after_tax_payroll, self_employed_adjustments, self_employed_plan_deductions,
        payroll_retirement_by_account, payroll_retirement_deductions, payroll_ira_deductions,
        payroll_nj_deferrals, nj_employer_403b_by_account, payroll_tax_deductions, payroll_deductions,
        employer_contribution_income, roth_employer_income)


def _ira_active_participants(
    state: SimState, payroll_contributions: list, ytd: Mapping[str, Any],
) -> tuple[set[str], dict[str, float]]:
    """Owners covered by a workplace plan this year, and employer money in traditional IRAs."""
    # Pub. 590-A, "Are You Covered by an Employer Plan?": any employee or
    # employer contribution to a person's workplace plan this year makes
    # them an active participant (IRC 219(g)(5)), which phases out their
    # traditional IRA deduction in _compute_tax. Employer money paid into a
    # traditional IRA is a SEP or SIMPLE IRA, which counts as well.
    # Opening year-to-date contributions count; defined benefit accruals
    # are not modeled. Payroll is settled here, before any tax is figured.
    ira_covered_owners: set[str] = set()
    # Employer (SEP/SIMPLE) money in a traditional IRA is not the owner's
    # own contribution and is never subject to the phase-out.
    ira_employer_contributions: dict[str, float] = {}
    for account_id, employee_amount, employer_amount in (
        [(c.target_account_id, c.employee_amount, c.employer_amount) for c in payroll_contributions]
        + [(aid, amount, 0.0) for aid, amount in ytd.get("contributions_by_account", {}).items()]
        + [(aid, 0.0, amount) for aid, amount in ytd.get("employer_contributions_by_account", {}).items()]
    ):
        account = state.accounts.get(account_id)
        if account is None:
            continue
        if ((account.account_type in IRA_ACTIVE_PARTICIPANT_PLAN_TYPES and employee_amount + employer_amount > 0)
                or (account.account_type == "traditional_ira" and employer_amount > 0)):
            ira_covered_owners.add(account.owner)
    for c in payroll_contributions:
        if state.accounts[c.target_account_id].account_type == "traditional_ira" and c.employer_amount > 0:
            ira_employer_contributions[c.target_account_id] = (
                ira_employer_contributions.get(c.target_account_id, 0.0) + c.employer_amount)
    return ira_covered_owners, ira_employer_contributions


def _payroll_contribution_flows(
    state: SimState, plan_data: PlanData, payroll_contributions: list, *,
    self_employment_income_ids: set[str], cf_income_sources: list[NamedAmount],
) -> tuple[dict[str, float], list[NamedAmount]]:
    """Step 4: payroll deposits by account and their contribution flows.

    W-2 employer money is reported as income as well.
    """
    contributions_for_growth: dict[str, float] = {}
    pre_waterfall_contributions: list[NamedAmount] = []
    for contribution in payroll_contributions:
        contribution_total = (
            contribution.employee_amount + contribution.employer_amount
        )
        contributions_for_growth[contribution.target_account_id] = (
            contributions_for_growth.get(contribution.target_account_id, 0.0)
            + contribution_total
        )
        account = plan_data.accounts.get(contribution.target_account_id)
        account_name = account.name if account is not None and account.name else contribution.target_account_id
        # An unfunded after-tax 401(k) rule still reports why, as surplus rules do.
        if contribution.employee_amount > 0 or contribution.funding_reasons:
            pre_waterfall_contributions.append(NamedAmount(
                name=account_name,
                amount=contribution.employee_amount,
                account_id=contribution.target_account_id, account_name=account_name, source="payroll",
                category="pretax" if account is not None and account.account_type in _PRE_TAX_CONTRIBUTION_TYPES else "aftertax",
                priority_rank=contribution.priority_rank, requested_amount=contribution.requested_amount,
                limited_by=contribution.limited_by, funding_reasons=contribution.funding_reasons,
            ))
        if contribution.employer_amount > 0 and contribution.source_income_id in self_employment_income_ids:
            # Funded from the business profit already counted as income.
            pre_waterfall_contributions.append(NamedAmount(
                name=account_name,
                amount=contribution.employer_amount,
                account_id=contribution.target_account_id, account_name=account_name, source="payroll",
                category="pretax" if account is not None and account.account_type in _PRE_TAX_CONTRIBUTION_TYPES else "aftertax",
            ))
        elif contribution.employer_amount > 0:
            pre_waterfall_contributions.append(NamedAmount(
                name=f"Employer Match: {account_name}",
                amount=contribution.employer_amount,
                account_id=contribution.target_account_id, account_name=account_name, source="employer",
            ))
            cf_income_sources.append(NamedAmount(
                name=f"Employer Match: {account_name}",
                amount=contribution.employer_amount, source="employer",
            ))
    return contributions_for_growth, pre_waterfall_contributions


def _payroll_expense_deductions(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, *, start_year: int,
    milestone_map: Mapping[str, Any], newly_triggered: list[str], income_by_id: Mapping[str, float],
    income_active_until: Mapping[str, float], expense_activation_years: dict[str, int],
    self_employment_income_ids: set[str], fica_w2_by_owner: dict[str, float],
    payroll_deductions: float, payroll_tax_deductions: float,
) -> tuple[float, list[NamedAmount], float, float, float, float]:
    """Step 4: expenses paid by payroll deduction and the wage bases they reduce.

    Returns (payroll expenses, their flows, paycheck deductions and federal
    tax deductions so far, state and local add-backs).
    """
    payroll_expenses = 0.0
    cf_payroll_expenses: list[NamedAmount] = []
    payroll_state_addback = payroll_local_addback = 0.0
    for exp in plan_data.expenses:
        if not exp.is_payroll_deduction:
            continue
        tied = None
        prorate = prorate_for_year(
            start_ms=milestone_map.get(exp.start_milestone_id) if exp.start_milestone_id else None,
            end_ms=milestone_map.get(exp.end_milestone_id) if exp.end_milestone_id else None,
            start_month=exp.start_month,
            end_month=exp.end_month,
            triggered=state.triggered_milestones,
            newly_triggered=newly_triggered,
            year=year,
            birth_month=plan_data.birth_month,
            simulation_fraction=year_fraction,
        )
        if exp.tied_income_id:
            tied = next((i for i in plan_data.income_streams if i.id == exp.tied_income_id), None)
            if tied is None or income_by_id.get(tied.id, 0.0) <= 0:
                continue
            # Intersect the two event windows, including a partial first
            # year and partner death. Summing monthly overlap avoids
            # multiplying fractions from disjoint income/expense periods.
            prorate = 0.0
            for month in range(1, 13):
                fractions = []
                for event in (exp, tied):
                    fractions.append(prorate_for_year(
                        milestone_map.get(event.start_milestone_id),
                        milestone_map.get(event.end_milestone_id),
                        event.start_month, event.end_month,
                        state.triggered_milestones, newly_triggered, year,
                        plan_data.birth_month, year_fraction,
                        active_until=min(month / 12, income_active_until.get(tied.id, 1.0)),
                        active_from=(month - 1) / 12,
                    ))
                prorate += min(fractions)
        if prorate == 0.0:
            continue

        activation_year = expense_activation_years.setdefault(exp.id, year)
        amount = _expense_amount_for_year(
            exp,
            year,
            activation_year,
            state.inflation_factor,
            start_year=start_year,
        ) * prorate
        payroll_expenses += amount
        payroll_deductions += amount
        if amount > 0:
            cf_payroll_expenses.append(NamedAmount(name=exp.name, amount=amount, category=exp.category, source="payroll"))
        # Missing treatments from legacy engine callers are pre-tax; the
        # defaults reduce federal, state and local wages, never FICA wages.
        bases = payroll_wage_reductions(exp.payroll_tax_treatment, exp.payroll_tax_elections)
        if bases.federal:
            payroll_tax_deductions += amount
        # State and local bases start from the federal amount; these hold
        # the differences an explicit election makes.
        payroll_state_addback += amount * (bases.federal - bases.state)
        payroll_local_addback += amount * (bases.federal - bases.local)
        if bases.fica and tied is not None and tied.id not in self_employment_income_ids:
            fica_owner = tied.owner if tied.owner in fica_w2_by_owner else None
            if fica_owner is not None:
                fica_w2_by_owner[fica_owner] = max(0.0, fica_w2_by_owner[fica_owner] - amount)
    return (payroll_expenses, cf_payroll_expenses, payroll_deductions, payroll_tax_deductions,
            payroll_state_addback, payroll_local_addback)


def _regime_year_tax(
    plan_data: PlanData, state: SimState, year: int, *, year_country: str, year_region: str | None,
    regime_context: Any, regime_prior: tuple[str, Any] | None, regime_opening: tuple[dict, dict, dict],
    regime_wealth: dict, calendar_inflation: dict[int, float], default_inflation: float, filing_status: str,
    income_by_id: Mapping[str, float], ss_income: float, intl_benefits: list,
    ordinary_drawdown_income: float, taxable_rmd_total: float, qcd_rmd_offset: float, sepp_income: float,
    taxable_cash_interest: float, rental_year: Mapping[str, real_estate.RentalYear],
) -> TaxResult:
    """This country year's tax from the regime evaluator (coastmath.engine.intl_regime)."""
    people = intl_regime.people_this_year(plan_data, state, year)
    opening_balances, opening_real, opening_loans = regime_opening
    if "value" not in regime_wealth:
        regime_wealth["value"] = intl_regime.wealth_balances(
            state, plan_data, people, opening_balances, opening_real, opening_loans)
    wealth = regime_wealth["value"]
    parts = intl_regime.IncomeParts()
    # Income from the projected period only: year-to-date entries do
    # not apply in a country year.
    stream_types = {"qualified_pension": "pension", "nonqualified_annuity": "pension",
                    "nontaxable": "nontaxable"}
    for inc in plan_data.income_streams:
        amount = income_by_id.get(inc.id, 0.0)
        if not amount or inc.is_social_security:
            continue
        if inc.tax_category == "nontaxable":
            income_type = "nontaxable"
        elif inc.is_earned_income:
            income_type = "self_employment" if inc.is_self_employed else "employment"
        else:
            income_type = stream_types.get(inc.tax_category, "other_taxable")
        for owner, share in _stream_owner_shares(inc.owner, plan_data):
            parts.add(owner, income_type, amount * share)
    # Social Security (survivor benefits included) as each person received it.
    ss_by_owner = {owner: max(0.0, state.retirement_income_this_year.get(owner, {}).get("social_security", 0.0))
                   for owner in ("self", "spouse")}
    ss_recorded = sum(ss_by_owner.values())
    if ss_recorded > 0:
        for owner, amount in ss_by_owner.items():
            parts.add(owner, "government_pension", ss_income * amount / ss_recorded)
    else:
        parts.add("self", "government_pension", ss_income)
    for payment in intl_benefits:
        parts.add(payment.owner, payment.income_type, payment.amount)
    # Taxable withdrawals: country account kinds by owner; US accounts
    # by each owner's recorded distributions, any rest to the holder.
    country_withdrawals = intl_accounts.withdrawal_income(state)
    for owner, amount in country_withdrawals.taxable_by_owner.items():
        parts.add(owner, "retirement_withdrawal", amount)
    us_withdrawals = max(0.0, ordinary_drawdown_income + taxable_rmd_total - qcd_rmd_offset + sepp_income
                         + state.roth_conversions_this_year
                         + (state.roth_ledger.totals()[0] if state.roth_ledger else 0.0))
    sources = {"ira", "401k", "403b", "457b", "401a", "roth_conversion"}
    recorded = {owner: max(0.0, sum(amount for source, amount in state.retirement_income_this_year.get(owner, {}).items()
                                    if source in sources)) for owner in ("self", "spouse")}
    attributed = min(us_withdrawals, sum(recorded.values()))
    for owner, amount in recorded.items():
        if attributed > 0:
            parts.add(owner, "retirement_withdrawal", attributed * amount / sum(recorded.values()))
    parts.add("self", "retirement_withdrawal", us_withdrawals - attributed)
    # Household investment and other income.
    parts.add("household", "interest", taxable_cash_interest + state.bond_interest_this_year)
    parts.add("household", "dividends_qualified", state.qualified_dividends_this_year)
    parts.add("household", "dividends_other", state.ordinary_dividends_this_year)
    parts.add("household", "capital_gains", max(0.0, state.capital_gains_this_year))
    parts.add("household", "rental", sum(activity.rent - activity.expenses for activity in rental_year.values()))
    parts.add("household", "other_taxable", state.cod_income_this_year + state.hsa_taxable_distributions_this_year
              + state.education_taxable_earnings_this_year)
    benefits_by_owner: dict[str, dict[str, float]] = {}
    for payment in intl_benefits:
        owner_benefits = benefits_by_owner.setdefault(payment.owner, {})
        owner_benefits[payment.rule] = owner_benefits.get(payment.rule, 0.0) + payment.amount
    factor = intl_regime.regime_inflation_factor(year_country, year_region, year, regime_context,
                                                 calendar_inflation, default_inflation)
    shares = intl_regime.investment_shares(state, people, opening_balances)
    regime = intl_regime.evaluate_year(
        country=year_country, region=year_region, year=year, inflation_factor=factor,
        people=people, filing_unit=intl_regime.filing(people, filing_status),
        incomes=parts.by_person(people, shares),
        gain_parts=intl_cost_base.parts_by_person(state, shares),
        deductible=intl_accounts.deductible_contributions_by_owner(state),
        benefits=benefits_by_owner, wealth=wealth, trades=intl_regime.trade_amounts(state),
        prior=regime_prior[1] if regime_prior is not None and regime_prior[0] == year_country else None,
        context=regime_context,
    )
    # A death this year with a surviving partner: the country's estate
    # rule on the decedent's share (the final death is in net legacy).
    for decedent in intl_regime.deaths_this_year(plan_data, state, year):
        survivor = "spouse" if decedent == "self" else "self"
        survivor_end = lifecycle.death_year(plan_data, survivor)
        if (decedent not in wealth["by_person"] or survivor not in wealth["by_person"]
                or (survivor_end is not None and survivor_end <= year)):
            continue
        share = wealth["by_person"][decedent]
        decedent_birth = plan_data.birth_year if decedent == "self" else plan_data.spouse_birth_year
        regime = intl_regime.with_extra_line(
            regime, "estate", "Estate tax", "estate", decedent,
            intl_regime.estate_tax(year_country, year_region, year, decedent, year - decedent_birth,
                                   share, share["net_worth"], True, factor,
                                   death_income=intl_regime.death_income_inputs(
                                       state, plan_data, decedent, people),
                                   terminal_year=regime.inputs))
    return intl_regime.tax_result(regime, state.capital_loss_carryforward)


def _imputed_stream_tax_credit(
    plan_data: PlanData, state: SimState, year: int, *, ytd: Mapping[str, Any],
    income_by_id: Mapping[str, float], filing_status: str, annual_tax_settings: Mapping[str, Any] | None,
    resolved_state_code: str | None, resolved_local_tax: Any, tax_holder_age: int | None,
    tax_spouse_age: int | None, federal_inflation_factor: float, calendar_inflation: dict[int, float],
    year_adjustments: Any, salt_passes: int, salt_tolerance: float,
    ca_wage_context: Callable[[], CAPartYearWageContext | None],
) -> float:
    """Estimate the tax paid before start from streams with history.

    The opening-year settlement reports the full calendar-year tax,
    but only the pre-start share of income streams can support an
    imputed payment. Account income (RMDs, withdrawals, dividends,
    interest and realized gains) is modeled after plan start and is
    excluded from this payment estimate.
    """
    past_by_id = ytd.get("_pre_start_income_by_id", {})
    if not past_by_id:
        return 0.0

    full_income = past_income = stream_gross = stream_ss = 0.0
    stream_w2: dict[str, float] = {}
    stream_se: dict[str, float] = {}
    stream_non_earned = 0.0
    stream_local_categories: dict[str | None, float] = {}
    # Only this scratch state's retirement-income tracker is used.
    stream_retirement = SimState(year=year)
    for inc in plan_data.income_streams:
        past_amount = float(past_by_id.get(inc.id, 0.0))
        if past_amount <= 0.0:
            continue
        current_amount = float(income_by_id.get(inc.id, 0.0))
        annual_stream_amount = past_amount + current_amount
        past_income += past_amount
        full_income += annual_stream_amount
        for owner, owner_share in _stream_owner_shares(inc.owner, plan_data):
            source = ("social_security" if inc.is_social_security
                      else STREAM_CATEGORY_SOURCES.get(inc.tax_category))
            if source:
                stream_retirement.record_retirement_income(
                    owner, source, annual_stream_amount * owner_share)
        if inc.is_social_security:
            stream_ss += annual_stream_amount
            continue

        stream_gross += annual_stream_amount
        if inc.is_earned_income:
            destination = stream_se if inc.is_self_employed else stream_w2
            destination[inc.owner] = destination.get(inc.owner, 0.0) + annual_stream_amount
        else:
            stream_local_categories[inc.tax_category] = (
                stream_local_categories.get(inc.tax_category, 0.0) + annual_stream_amount
            )
            if inc.tax_category not in {"qualified_pension", "other_ordinary"}:
                stream_non_earned += annual_stream_amount

    if full_income <= 0.0 or past_income <= 0.0:
        return 0.0
    pre_start_share = max(0.0, min(1.0, past_income / full_income))
    local_stream_income = LocalIncome(
        wages=sum(stream_w2.values()),
        medicare_wages=sum(stream_w2.values()),
        taxable_wages=sum(stream_w2.values()),
        self_employment=sum(stream_se.values()),
        investment_income=(stream_local_categories.get("investment", 0.0)
                           + stream_local_categories.get(None, 0.0)),
        annuity_income=stream_local_categories.get("nonqualified_annuity", 0.0),
        pension_income=stream_local_categories.get("qualified_pension", 0.0),
    )

    state_tax_estimate = 0.0
    for _ in range(salt_passes):
        stream_result = calculate_tax(
            gross_income=stream_gross,
            deductions=0.0,
            filing_status=filing_status,
            settings=annual_tax_settings,
            capital_gains=0.0,
            state_code=resolved_state_code,
            itemized_deductions={"salt": state_tax_estimate},
            social_security_income=stream_ss,
            earned_income=sum(stream_w2.values()) + sum(stream_se.values()),
            is_self_employed=bool(stream_se),
            net_investment_income=stream_non_earned,
            qualified_business_income=sum(stream_se.values()),
            tax_year=year,
            w2_income_by_owner=stream_w2,
            self_employment_income_by_owner=stream_se,
            inflation_factor=state.inflation_factor,
            qualified_dividends=0.0,
            capital_loss_carryforward=0.0,
            holder_age=tax_holder_age,
            spouse_age=tax_spouse_age,
            federal_inflation_factor=federal_inflation_factor,
            calendar_inflation=calendar_inflation,
            ca_part_year_context=ca_wage_context(),
            state_income_adjustment=0.0,
            local_tax=resolved_local_tax,
            local_income=local_stream_income if resolved_local_tax else None,
            retirement_income=_retirement_income(stream_retirement, plan_data, year),
            adjustments=year_adjustments,
        )
        revised_state_tax = stream_result.state + stream_result.local
        if abs(revised_state_tax - state_tax_estimate) < salt_tolerance:
            break
        state_tax_estimate = revised_state_tax

    return max(0.0, stream_result.total_tax) * pre_start_share


def _standard_expenses(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, *, start_year: int,
    active_standard_expenses: list[ExpenseData], flex_adjusted_expenses: list[ExpenseData],
    milestone_map: Mapping[str, Any], newly_triggered: list[str],
    expense_activation_years: dict[str, int], planned_essential: float,
) -> tuple[float, float, list[NamedAmount], float]:
    """Step 7: the year's ordinary expenses, after flex rules.

    Returns (flexed spending, planned spending, expense flows, planned
    essential spending so far). Sets the year's 529 qualified allowance.
    """
    standard_expenses = 0.0
    original_expenses = 0.0
    # Qualified education expenses this year (529 allowance below).
    education_expenses = 0.0
    cf_expenses: list[NamedAmount] = []
    # apply_flex_rules returns one expense for each expense it is given.
    for orig, adj in zip(active_standard_expenses, flex_adjusted_expenses, strict=True):
        prorate = prorate_for_year(
            start_ms=milestone_map.get(adj.start_milestone_id) if adj.start_milestone_id else None,
            end_ms=milestone_map.get(adj.end_milestone_id) if adj.end_milestone_id else None,
            start_month=adj.start_month,
            end_month=adj.end_month,
            triggered=state.triggered_milestones,
            newly_triggered=newly_triggered,
            year=year,
            birth_month=plan_data.birth_month,
            simulation_fraction=year_fraction,
        )

        if prorate == 0.0:
            continue
        activation_year = expense_activation_years.setdefault(orig.id, year)
        full_year_amount = _expense_amount_for_year(
            orig,
            year,
            activation_year,
            state.inflation_factor,
            start_year=start_year,
        )
        flex_ratio = (
            adj.annual_amount / orig.annual_amount
            if orig.annual_amount > 0
            else 1.0
        )
        orig_amount = full_year_amount * prorate
        adj_amount = orig_amount * flex_ratio
        planned_essential += orig_amount * (1.0 - (discretionary_share(orig) or 0.0))
        standard_expenses += adj_amount
        original_expenses += orig_amount
        if orig.qualified_education:
            education_expenses += adj_amount
        if adj_amount > 0:
            cf_expenses.append(NamedAmount(
                name=adj.name, amount=adj_amount, category=adj.category,
                discretionary_amount=_discretionary_amount(orig, orig_amount, adj_amount),
            ))

    # 529 withdrawals up to these expenses are tax free (IRC 529(c)(3)(B)).
    state.education_allowance = education_expenses
    return standard_expenses, original_expenses, cf_expenses, planned_essential


class _StrategyYear(NamedTuple):
    """Step 7b results: spending after the strategy and what later steps need."""

    standard_expenses: float
    original_expenses: float
    cf_expenses: list[NamedAmount]
    strategy_spent: float | None
    # "withdrawal_plus_income": the portfolio withdrawal step 9c spends.
    strategy_withdrawal_target: float | None
    # Start year only: spending already counted before the strategy starts.
    strategy_planned_part: float | None
    planned_for_year: float | None
    # Flex change booked once the income-plus-withdrawal amount is known.
    pending_strategy_flex_delta: float


def _withdrawal_strategy_spending(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, age: int, *,
    end_year: int, withdrawal_strategy: WithdrawalStrategySpec | None,
    milestone_map: Mapping[str, Any], newly_triggered: list[str], prior_year_balances: Mapping[str, float],
    bond_allocation: float, flex_mult: Any, planned_essential: float, standard_expenses: float,
    original_expenses: float, cf_expenses: list[NamedAmount],
) -> _StrategyYear:
    """Step 7b: replace planned spending with the withdrawal strategy's amount.

    The textbook strategy is saved on the plan or passed by the comparison.
    Once it starts, its amount replaces the plan's ordinary expenses;
    planned expenses are kept for reporting. Under "withdrawal_plus_income"
    the amount is the year's portfolio withdrawal instead, and step 9c sets
    ordinary spending to that withdrawal plus the net income left.
    """
    strategy_spent: float | None = None
    strategy_withdrawal_target: float | None = None
    # Start year only: spending already counted for the months before the
    # strategy starts, or None when the strategy covers the whole year.
    strategy_planned_part: float | None = None
    planned_for_year: float | None = standard_expenses
    # Strategy spending added or removed by flex (flexed minus planned);
    # the pending part is booked when the income-plus-withdrawal amount is
    # known.
    strategy_flex_delta = 0.0
    pending_strategy_flex_delta = 0.0
    if withdrawal_strategy is not None:
        ws_state = state.withdrawal_strategy_state
        if ws_state is None:
            ws_state = WithdrawalStrategyState()
            state.withdrawal_strategy_state = ws_state
        starts = (
            (withdrawal_strategy.start_milestone_id is not None
             and withdrawal_strategy.start_milestone_id in state.triggered_milestones)
            or (withdrawal_strategy.start_age is not None and age >= withdrawal_strategy.start_age)
            or (withdrawal_strategy.start_milestone_id is None and withdrawal_strategy.start_age is None)
        )
        if starts or ws_state.started:
            # In the start year the plan's own spending covers the months
            # before the strategy's start month (a milestone's month, or
            # the birthday month of the start age); the strategy covers
            # the rest of the modeled year.
            start_point = 0.0
            if not ws_state.started:
                if withdrawal_strategy.start_milestone_id in newly_triggered:
                    start_point = (resolve_trigger_month(milestone_map.get(withdrawal_strategy.start_milestone_id),
                                                         plan_data.birth_month, year) - 1) / 12
                elif (withdrawal_strategy.start_milestone_id is None
                      and withdrawal_strategy.start_age is not None and age == withdrawal_strategy.start_age):
                    start_point = ((plan_data.birth_month or 1) - 1) / 12
            strategy_share = 1.0 - max(start_point, 1.0 - year_fraction)
            planned_share = (year_fraction - strategy_share) / year_fraction if year_fraction > 0 else 0.0
            portfolio_start = sum(prior_year_balances.values())
            strategy_base = strategy_spending(
                withdrawal_strategy, ws_state, year=year, age=age, portfolio=portfolio_start,
                inflation_factor=state.inflation_factor,
                years_remaining=end_year - year,
                prior_year_return=state.return_history[-2] if len(state.return_history) > 1 else 0.0,
                bond_allocation=bond_allocation,
            )
            strategy_amount = strategy_base * strategy_share
            strategy_multiplier = scope_multiplier(plan_data, flex_mult, "strategy_spending")
            if strategy_multiplier != 1.0:
                # Flex acts on the strategy's amount after its own bounds,
                # stays inside those bounds and above planned essentials.
                flexed_amount = flex_strategy_spending(
                    strategy_base, strategy_multiplier, share=strategy_share,
                    spec=withdrawal_strategy, portfolio=portfolio_start,
                    inflation_factor=state.inflation_factor,
                    essential_floor=planned_essential * (1.0 - planned_share),
                )
                strategy_flex_delta = flexed_amount - strategy_amount
                strategy_amount = flexed_amount
            planned_for_year = standard_expenses
            if withdrawal_strategy.income_handling == "withdrawal_plus_income":
                # Step 9c sets this mode's spending from the withdrawal.
                strategy_withdrawal_target = strategy_amount
                strategy_amount = 0.0
                pending_strategy_flex_delta = strategy_flex_delta
                strategy_flex_delta = 0.0
            cf_expenses = [replace(flow, amount=flow.amount * planned_share,
                                   discretionary_amount=(flow.discretionary_amount * planned_share
                                                         if flow.discretionary_amount is not None else None))
                           for flow in cf_expenses] if planned_share > 0 else []
            if strategy_amount > 0:
                cf_expenses.append(NamedAmount(name="Strategy spending", amount=strategy_amount, category="discretionary"))
            standard_expenses = standard_expenses * planned_share + strategy_amount
            original_expenses = original_expenses * planned_share + strategy_amount - strategy_flex_delta
            strategy_spent = standard_expenses
            if planned_share > 0:
                strategy_planned_part = standard_expenses - strategy_amount
    return _StrategyYear(standard_expenses, original_expenses, cf_expenses, strategy_spent,
                         strategy_withdrawal_target, strategy_planned_part, planned_for_year,
                         pending_strategy_flex_delta)


def _fund_specific_expenses(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, age: int, *,
    start_year: int, milestone_map: Mapping[str, Any], newly_triggered: list[str],
    expense_activation_years: dict[str, int], annual_account_rates: Mapping[str, tuple],
    annual_income_composition: Mapping[str, IncomeComposition], sepp_account_ids: set[str],
    drawdown_withholding_rates: Mapping[str, float], ordinary_drawdown_income: float,
    early_withdrawal_penalty: float, specific_drawdowns: dict[str, float],
    cf_expenses: list[NamedAmount],
) -> tuple[float, float, float]:
    """Step 8: pay expenses that name their funding accounts from those accounts.

    Returns (expenses funded, ordinary drawdown income and early withdrawal
    penalty so far).
    """
    # The uniform factors were established before required distributions.
    specific_funded_expenses = 0.0
    for exp in plan_data.expenses:
        selected_ids = _expense_funding_ids(exp)
        if not selected_ids:
            continue
        if exp.is_payroll_deduction:
            continue
        prorate = prorate_for_year(
            start_ms=milestone_map.get(exp.start_milestone_id) if exp.start_milestone_id else None,
            end_ms=milestone_map.get(exp.end_milestone_id) if exp.end_milestone_id else None,
            start_month=exp.start_month,
            end_month=exp.end_month,
            triggered=state.triggered_milestones,
            newly_triggered=newly_triggered,
            year=year,
            birth_month=plan_data.birth_month,
            simulation_fraction=year_fraction,
        )
        if prorate == 0.0:
            continue

        activation_year = expense_activation_years.setdefault(exp.id, year)
        amount = _expense_amount_for_year(
            exp,
            year,
            activation_year,
            state.inflation_factor,
            start_year=start_year,
        ) * prorate
        if exp.qualified_education:
            state.education_allowance += amount
        ordered_ids = _ordered_specific_funding_ids(selected_ids, plan_data)
        previous_factors = {
            account_id: (
                state.withdrawal_growth_factors.get(account_id),
                state.withdrawal_dividend_factors.get(account_id),
            )
            for account_id in ordered_ids
        }
        args = (exp, milestone_map, state.triggered_milestones, newly_triggered,
                year, plan_data.birth_month, year_fraction)
        for account_id in ordered_ids:
            if previous_factors[account_id][0] is None:
                continue
            source = state.accounts.get(account_id)
            if source is None:
                continue
            rate, stock_income_rate, bond_income_rate = _price_and_income_rates(
                annual_account_rates[account_id], annual_income_composition[account_id],
                source.account_type)
            state.withdrawal_growth_factors[account_id], state.withdrawal_dividend_factors[account_id] = (
                _withdrawal_factors(source, rate, stock_income_rate + bond_income_rate,
                                    lambda r, args=args: _scheduled_growth_factor(r, *args)))
        specific_unfunded_before = state.unfunded_expenses
        withdrawals, penalty = execute_drawdown(
            amount,
            [DrawdownEntryData(index + 1, account_id) for index, account_id in enumerate(ordered_ids)],
            state,
            age=age, birth_month=plan_data.birth_month, sepp_account_ids=sepp_account_ids,
            # Spending the user funds from an HSA is their designation of
            # qualified medical costs; only shortfall draws use the allowance.
            # Likewise spending funded from a 529 is qualified education.
            withholding_rates=drawdown_withholding_rates, hsa_qualified=True,
            education_qualified=True)
        restricted_shortfall = (
            state.unfunded_expenses - specific_unfunded_before
            if exp.specific_funding_source_ids is not None
            else 0.0
        )
        if restricted_shortfall > 0:
            state.restricted_unfunded_expenses += restricted_shortfall
        for account_id, (previous_factor, previous_dividend_factor) in previous_factors.items():
            if previous_factor is not None:
                state.withdrawal_growth_factors[account_id] = previous_factor
                state.withdrawal_dividend_factors[account_id] = previous_dividend_factor or 0.0
        ordinary_drawdown_income += _ordinary_income_from_drawdowns(withdrawals, state)
        early_withdrawal_penalty += penalty
        for aid, value in withdrawals.items():
            specific_drawdowns[aid] = specific_drawdowns.get(aid, 0.0) + value
        specific_funded_expenses += amount
        if amount > 0:
            cf_expenses.append(NamedAmount(
                name=exp.name, amount=amount, category=exp.category,
                discretionary_amount=_discretionary_amount(exp, amount, amount),
            ))
    return specific_funded_expenses, ordinary_drawdown_income, early_withdrawal_penalty


def _fund_real_estate_purchases(
    state: SimState, plan_data: PlanData, age: int, *,
    purchases_this_year: list[tuple[RealAssetData, real_estate.PurchaseTerms]],
    sepp_account_ids: set[str], drawdown_withholding_rates: Mapping[str, float],
    ordinary_drawdown_income: float, early_withdrawal_penalty: float,
    specific_drawdowns: dict[str, float], cf_expenses: list[NamedAmount],
) -> tuple[float, float, float, float]:
    """Step 8: pay this year's planned purchases from their funding accounts.

    Returns (cash due at purchase, the part the year's cash flow pays,
    ordinary drawdown income and early withdrawal penalty so far).
    """
    # Planned real estate purchases: the down payment (or the whole
    # price without a loan) plus closing costs. An explicit funding
    # account pays it like an expense funded from that account, and its
    # shortfall stays unfunded; otherwise the year's cash flow and the
    # withdrawal order pay it in step 9b.
    real_estate_purchase_cash = 0.0
    purchase_cash_from_flow = 0.0
    for asset, terms in purchases_this_year:
        if terms.cash_due <= 0:
            continue
        real_estate_purchase_cash += terms.cash_due
        cf_expenses.append(NamedAmount(
            name=f"{asset.name} purchase (down payment and closing costs)"
            if asset.purchase_loan_term_months else f"{asset.name} purchase",
            amount=terms.cash_due, category="essential"))
        source_id = asset.purchase_funding_account_id
        if source_id not in state.accounts:
            purchase_cash_from_flow += terms.cash_due
            continue
        unfunded_before = state.unfunded_expenses
        withdrawals, penalty = execute_drawdown(
            terms.cash_due, [DrawdownEntryData(1, source_id)], state,
            age=age, birth_month=plan_data.birth_month, sepp_account_ids=sepp_account_ids,
            withholding_rates=drawdown_withholding_rates)
        state.restricted_unfunded_expenses += state.unfunded_expenses - unfunded_before
        ordinary_drawdown_income += _ordinary_income_from_drawdowns(withdrawals, state)
        early_withdrawal_penalty += penalty
        for aid, value in withdrawals.items():
            specific_drawdowns[aid] = specific_drawdowns.get(aid, 0.0) + value
    return real_estate_purchase_cash, purchase_cash_from_flow, ordinary_drawdown_income, early_withdrawal_penalty


def _pay_liabilities(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, *,
    milestone_map: Mapping[str, Any], newly_triggered: list[str], asset_fractions: Mapping[str, float],
    asset_windows: Mapping[str, tuple[float, float]], real_asset_map: Mapping[str, RealAssetData],
    rental_year: dict[str, real_estate.RentalYear], rental_share: Mapping[str, float],
    mortgage_interest: float, cf_expenses: list[NamedAmount],
) -> tuple[float, float]:
    """Step 9b: amortize every loan for the months it is active this year.

    Returns (payments made, deductible mortgage interest paid so far).
    """
    total_liability_payments = 0.0
    for liab in plan_data.liabilities:
        ls = state.liability_states.get(liab.id)
        if ls is None or ls.remaining_balance + ls.accrued_interest <= 0.01:
            continue

        offset_balance = 0.0
        if liab.offset_account_id is not None:
            offset_balance = state.get_balance(liab.offset_account_id)

        loan_fraction = asset_fractions.get(liab.linked_asset_id, year_fraction)
        payoff_now = liab.payoff_milestone_id in state.triggered_milestones
        if payoff_now:
            payoff_month = resolve_trigger_month(milestone_map[liab.payoff_milestone_id], plan_data.birth_month, year) if liab.payoff_milestone_id in newly_triggered else 1
            loan_fraction = min(loan_fraction, max(0.0, (payoff_month - 1) / 12.0 - (1.0 - year_fraction)))
        # First active calendar month: owned-window start for a loan on
        # a property, else the plan's start month in a partial year.
        window_start = (asset_windows[liab.linked_asset_id][0] if liab.linked_asset_id in asset_windows
                        else 12.0 * (1.0 - year_fraction))
        result = amortize_year(
            principal_balance=ls.remaining_balance,
            annual_rate=liab.interest_rate,
            monthly_payment=liab.monthly_payment or 0.0,
            extra_payment_annual=liab.extra_payment,
            offset_balance=offset_balance,
            payment_type=liab.payment_type,
            months=12.0 * loan_fraction,
            interest_method=liab.interest_method,
            accrued_interest=ls.accrued_interest,
            year=year,
            first_month=int(window_start + 1e-9) + 1,
        )
        ls.remaining_balance = result.remaining_balance
        ls.accrued_interest = result.accrued_interest
        payment = result.principal_paid + result.interest_paid
        if payoff_now:
            payment += ls.remaining_balance + ls.accrued_interest
            ls.remaining_balance = 0.0
            ls.accrued_interest = 0.0
        linked_asset = real_asset_map.get(liab.linked_asset_id)
        if linked_asset is not None and linked_asset.id in rental_year:
            # Interest on a rental property's loan is a Schedule E expense;
            # a mixed-use home's personal share stays mortgage interest.
            share = rental_share[linked_asset.id]
            rental_year[linked_asset.id].interest += result.interest_paid * share
            if linked_asset.is_primary_residence:
                mortgage_interest += result.interest_paid * (1.0 - share)
        elif linked_asset is not None and linked_asset.is_primary_residence:
            mortgage_interest += result.interest_paid
        total_liability_payments += payment
        if payment > 0:
            cf_expenses.append(NamedAmount(
                name=liab.name, amount=payment, category="essential",
            ))
    return total_liability_payments, mortgage_interest


def _asset_carrying_costs(
    state: SimState, plan_data: PlanData, year_fraction: float, *,
    real_asset_start_values: Mapping[str, float], asset_fractions: Mapping[str, float],
    rental_year: dict[str, real_estate.RentalYear], rental_share: Mapping[str, float],
    property_tax_paid: float, cf_expenses: list[NamedAmount],
) -> tuple[float, float]:
    """Step 9b: property tax, upkeep and insurance on every asset still owned.

    Returns (carrying costs paid, itemizable property tax paid so far).
    """
    asset_carrying_costs = 0.0
    for asset in plan_data.real_assets:
        if asset.id not in state.real_asset_values:
            continue  # sold / auto-liquidated
        cost_basis_value = real_asset_start_values.get(
            asset.id,
            state.get_real_asset_value(asset.id),
        )
        property_tax = (
            cost_basis_value * asset.property_tax_rate
            if asset.property_tax_rate is not None
            else asset.annual_property_tax * state.inflation_factor
        )
        maintenance = (
            cost_basis_value * asset.maintenance_rate
            if asset.maintenance_rate is not None
            else asset.annual_maintenance * state.inflation_factor
        )
        insurance = (
            cost_basis_value * asset.insurance_rate
            if asset.insurance_rate is not None
            else 0.0
        )
        annual_cost = (
            (property_tax + maintenance + insurance)
            * asset_fractions.get(asset.id, year_fraction)
        )
        if asset.id in rental_year:
            # A rental's property tax and upkeep are Schedule E expenses,
            # not itemized deductions. A mixed-use property's personal
            # share of property tax stays itemized (IRC 280A(e), 164).
            share = rental_share[asset.id]
            rental_year[asset.id].carrying += annual_cost * share
            if share < 1.0:
                property_tax_paid += property_tax * asset_fractions.get(asset.id, year_fraction) * (1.0 - share)
        else:
            property_tax_paid += property_tax * asset_fractions.get(asset.id, year_fraction)
        if annual_cost > 0:
            asset_carrying_costs += annual_cost
            cf_expenses.append(NamedAmount(
                name=f"{asset.name} (property tax & upkeep)",
                amount=annual_cost,
                category="essential",
            ))
    return asset_carrying_costs, property_tax_paid


def _contribution_timing_growth(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, *,
    contributions_for_growth: Mapping[str, float], payroll_contributions: list,
    annual_account_rates: Mapping[str, tuple], annual_income_composition: Mapping[str, IncomeComposition],
    milestone_map: Mapping[str, Any], newly_triggered: list[str], spend_leftover_mode: bool,
    cf_income_sources: list[NamedAmount], cf_contributions: list[NamedAmount],
) -> float:
    """Step 10a: growth on contributions made through the year (monthly cash flow).

    Returns the growth earned; taxable income it pays is recorded on ``state``
    and in the cash-flow lists.
    """
    cash_flow_timing_investment_growth = 0.0
    cash_flow_frequency = (plan_data.tax_settings or {}).get(
        "cash_flow_frequency",
        "monthly",
    )
    if cash_flow_frequency == "monthly" and contributions_for_growth:
        active_months = max(1, min(12, round(12 * year_fraction)))
        taxable_contribution_dividends = 0.0
        taxable_contribution_bond_interest = 0.0
        # Income a taxable account pays out (reinvest_income false).
        paid_out_contribution_dividends = 0.0
        paid_out_contribution_bond_interest = 0.0
        for account_id, contributed in contributions_for_growth.items():
            account = state.accounts.get(account_id)
            if account is None or account.account_type in _ZERO_GROWTH_TYPES:
                continue
            annual_price_rate, stock_income_rate, bond_income_rate = _price_and_income_rates(
                annual_account_rates[account_id], annual_income_composition[account_id],
                account.account_type)
            yield_rate = stock_income_rate + bond_income_rate
            total_factor = _average_monthly_deposit_growth_factor(annual_price_rate + yield_rate, active_months)
            dividend_factor = _average_monthly_deposit_growth_factor(yield_rate, active_months)
            total_gain = contributed * total_factor
            dividend_gain = contributed * dividend_factor
            for contribution in payroll_contributions:
                if contribution.target_account_id != account_id or not contribution.source_income_id:
                    continue
                source = next((i for i in plan_data.income_streams if i.id == contribution.source_income_id), None)
                if source is None:
                    continue
                amount = contribution.employee_amount + contribution.employer_amount
                args = (source, milestone_map, state.triggered_milestones,
                        newly_triggered, year, plan_data.birth_month, year_fraction)
                total_gain += amount * (_scheduled_growth_factor(annual_price_rate + yield_rate, *args) - total_factor)
                dividend_gain += amount * (_scheduled_growth_factor(yield_rate, *args) - dividend_factor)
            price_gain = total_gain - dividend_gain
            account.balance += price_gain
            if account.account_type in _TAXABLE_TYPES and dividend_gain > 0:
                paid_out = not reinvests_income(account)
                if not paid_out:
                    state.deposit_to(account_id, dividend_gain)
                state.recognize_yield_income(account_id, dividend_gain)
                stock_dividend_gain = dividend_gain * state.income_character[account_id].stock_dividends
                taxable_contribution_dividends += stock_dividend_gain
                taxable_contribution_bond_interest += dividend_gain - stock_dividend_gain
                if paid_out:
                    paid_out_contribution_dividends += stock_dividend_gain
                    paid_out_contribution_bond_interest += dividend_gain - stock_dividend_gain
                    # Paid-out income leaves the account, as on opening balances.
                    cash_flow_timing_investment_growth += price_gain
                    continue
            else:
                account.balance += dividend_gain
            cash_flow_timing_investment_growth += price_gain + dividend_gain

        if taxable_contribution_dividends > 0:
            cf_income_sources.append(NamedAmount(
                name="Taxable Stock Dividends on Contributions",
                amount=taxable_contribution_dividends,
            ))
        if taxable_contribution_dividends - paid_out_contribution_dividends > 0.005:
            cf_contributions.append(NamedAmount(name="Reinvested dividends on contributions",
                amount=taxable_contribution_dividends - paid_out_contribution_dividends,
                source="reinvestment"))
        if taxable_contribution_bond_interest > 0:
            cf_income_sources.append(NamedAmount(
                name="Taxable-Account Bond Interest on Contributions",
                amount=taxable_contribution_bond_interest,
            ))
        if taxable_contribution_bond_interest - paid_out_contribution_bond_interest > 0.005:
            cf_contributions.append(NamedAmount(name="Reinvested bond interest on contributions",
                amount=taxable_contribution_bond_interest - paid_out_contribution_bond_interest,
                source="reinvestment"))
        # Paid-out income goes to household cash like the year's other
        # unallocated cash: held for leftover spending, else banked.
        paid_out_contribution_income = paid_out_contribution_dividends + paid_out_contribution_bond_interest
        if paid_out_contribution_income > 0.005 and spend_leftover_mode:
            state.leftover_cash_held += paid_out_contribution_income
        elif paid_out_contribution_income > 0.005:
            sink_id = state.cash_account()
            state.deposit_to(sink_id, paid_out_contribution_income)
            sink_name = state.accounts[sink_id].name or "Unallocated cash"
            cf_contributions.append(NamedAmount(
                name=sink_name, amount=paid_out_contribution_income, account_id=sink_id,
                account_name=sink_name, source="default_sink",
            ))
    return cash_flow_timing_investment_growth


def _spend_or_save_leftover(
    state: SimState, plan_data: PlanData, *, flex_mult: Any, net_cash: float, standard_expenses: float,
    original_expenses: float, cf_expenses: list[NamedAmount], cf_contributions: list[NamedAmount],
) -> tuple[float, float, float, float]:
    """Spend the leftover share of cash held through settlement and save the rest.

    Returns (leftover spent, net cash, flexed and planned spending).
    """
    leftover_spent = 0.0
    if state.leftover_cash_held > 0.0:
        held = state.leftover_cash_held
        state.leftover_cash_held = 0.0
        leftover_share = min(1.0, max(0.0, scope_multiplier(plan_data, flex_mult, "leftover_spending")))
        leftover_spent = held * leftover_share
        if leftover_spent <= .005:
            leftover_spent = 0.0
        leftover_saved = held - leftover_spent
        if leftover_saved > 0.0:
            sink_id = state.cash_account()
            state.deposit_to(sink_id, leftover_saved)
            sink_name = state.accounts[sink_id].name or "Unallocated cash"
            cf_contributions.append(NamedAmount(
                name=sink_name, amount=leftover_saved, account_id=sink_id,
                account_name=sink_name, source="default_sink",
            ))
        if leftover_spent > 0.0:
            net_cash -= leftover_spent
            standard_expenses += leftover_spent
            original_expenses += leftover_spent
            cf_expenses.append(NamedAmount(
                name="Leftover spending", amount=leftover_spent, category="discretionary",
            ))
    return leftover_spent, net_cash, standard_expenses, original_expenses


def _inflate_for_next_year(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, *,
    override_returns: dict[int, tuple] | None, curves: Any, default_inflation: float,
    federal_inflation_factor: float, social_security_inflation_factor: float,
    income_scheduled_amounts: dict[str, float], income_growth_factors: dict[str, float],
) -> tuple[float, float, float]:
    """Step 11: advance inflation and income growth to next year.

    Returns the new federal and Social Security inflation factors and the
    factor this year's amounts used.
    """
    if override_returns is not None and year in override_returns:
        inflation_rate = override_returns[year][2]
    else:
        inflation_rate = resolve_assumption(
            curves, "inflation", year, plan_data.birth_year, default_inflation,
        )
    if year >= 2026:
        federal_inflation_factor *= 1.0 + inflation_rate
    for inc in plan_data.income_streams:
        rate = inc.growth_rate
        if rate is None and (inc.is_social_security or inc.is_earned_income):
            rate = resolve_assumption(curves, "social_security_cola" if inc.is_social_security else "wage_growth",
                year, plan_data.spouse_birth_year if inc.owner == "spouse" and plan_data.spouse_birth_year else plan_data.birth_year,
                inflation_rate)
        # Income growth, including default SS COLA, takes a full January
        # step after the opening year. Cash-flow proration is independent.
        if inc.id in income_scheduled_amounts:
            income_scheduled_amounts[inc.id] = next_amount(
                inc, income_scheduled_amounts[inc.id], year + 1, rate or 0.0,
                inflation_rate, state.inflation_factor * (1.0 + inflation_rate),
            )
        income_growth_factors[inc.id] *= 1.0 + (rate or 0.0)
    social_security_inflation_factor *= 1.0 + _rate_for_fraction(inflation_rate, year_fraction)
    # Plan-start-year amounts advance a full step each January, including
    # after a partial opening year. That year's flow proration is unchanged.
    # The snapshot reports the factor this year's amounts used (first year
    # 1.0), matching the web deflators and withdrawal comparison.
    year_inflation_factor = state.inflation_factor
    state.inflation_factor *= 1.0 + inflation_rate
    return federal_inflation_factor, social_security_inflation_factor, year_inflation_factor


def _net_legacy_at_end(
    plan_data: PlanData, state: SimState, *, start_year: int, end_year: int,
    calendar_inflation: dict[int, float], regime_plan: bool, final_regime: tuple[str, Any],
    regime_context: Any, default_inflation: float, final_regime_inputs: Any,
) -> tuple[dict, int]:
    """Estate tax and net legacy at the end of the plan, and the plan's last year."""
    estate = plan_data.estate_settings or EstateSettingsData()
    final_liquid = sum(a.balance for a in state.accounts.values())
    final_real = state.total_real_asset_value()
    accrued_taxes_at_death = state.unfunded_expenses - sum(state.pending_tax_settlements.values())
    final_liabilities = state.total_liability_balance() + accrued_taxes_at_death
    # A nonspouse HSA beneficiary includes its death-date FMV in income
    # (IRS Pub. 969); a surviving spouse continues the HSA tax treatment.
    pretax_at_death = sum(a.balance for a in state.accounts.values() if a.account_type in _ORDINARY_DRAWDOWN_ACCOUNT_TYPES | {"hsa"})
    # 529 accounts are outside the owner's gross estate (IRC 529(c)(4)).
    education_at_death = sum(a.balance for a in state.accounts.values() if a.account_type == EDUCATION_ACCOUNT_TYPE)
    unrealized_at_death = sum(
        max(0.0, a.balance - (a.cost_basis if a.cost_basis is not None else a.balance))
        for a in state.accounts.values() if a.account_type in _TAXABLE_TYPES)
    # Marital deduction applies if spouse is still alive at plan holder's death
    marital = (
        not lifecycle.enabled(plan_data)
        and not state.partner_deceased
        and plan_data.spouse_birth_year is not None
    )
    last_year = end_year - 1 if end_year > start_year else start_year
    net_legacy_result = calculate_net_legacy(
        total_assets=final_liquid + final_real,
        total_liabilities=final_liabilities,
        estate_settings=estate,
        final_year=last_year,
        marital_deduction=marital,
        partner_death_year=lifecycle.first_death_year(plan_data) if lifecycle.enabled(plan_data) else state.partner_death_year,
        same_year_deaths=(lifecycle.enabled(plan_data)
                          and lifecycle.death_year(plan_data, "spouse") == lifecycle.death_year(plan_data, "self")),
        accrued_taxes=accrued_taxes_at_death,
        pretax_balance=pretax_at_death,
        calendar_inflation=calendar_inflation,
        education_savings_balance=education_at_death,
        real_asset_value=final_real,
        unrealized_gains=unrealized_at_death,
    )
    if regime_plan and final_regime[0] != "US":
        # The final year is taxed by another country: its estate rule (none
        # without one) replaces US estate tax.
        final_country, final_region = final_regime
        decedent = "self"
        if lifecycle.enabled(plan_data) and state.primary_deceased and plan_data.spouse_birth_year is not None:
            decedent = "spouse"
        decedent_birth = plan_data.spouse_birth_year if decedent == "spouse" else plan_data.birth_year
        net_legacy_result = intl_regime.apply_final_estate(
            net_legacy_result, final_country,
            intl_regime.estate_tax(
                final_country, final_region, last_year, decedent, last_year - decedent_birth,
                # Final balances by category (home and pension detail for the rule).
                intl_regime.final_estate_wealth(state, plan_data, decedent),
                net_legacy_result["gross_estate"], marital,
                intl_regime.regime_inflation_factor(final_country, final_region, last_year, regime_context,
                                                    calendar_inflation, default_inflation),
                # A couple's last death: the other partner died first.
                predeceased_partner=plan_data.spouse_birth_year is not None and not marital,
                # Everything left is the decedent's: income deemed at death.
                death_income=intl_regime.death_income_inputs(state, plan_data, decedent, None),
                terminal_year=final_regime_inputs))
    return net_legacy_result, last_year


def _result_warnings(
    plan_data: PlanData, state: SimState, *, coverage_warnings: set[str],
    missing_target_rate_years: list[int], plan_tax_target: Any,
    missing_rule_rate_years: dict[tuple, tuple[float, list[int]]], opening_ytd_imputed: bool,
    provided_ytd: Mapping[str, Any], purchase_positions: dict[str, Any], used_historical_yields: bool,
    used_assumed_yield_fallback: bool, timeline: list[YearSnapshot], healthcare_warning_set: list[str],
    survivor_context: Any, spousal_workers: Mapping[str, str], plan_milestone_ids: set[str],
) -> list[str]:
    """The plan-level warnings reported in the result metadata."""
    estate = plan_data.estate_settings or EstateSettingsData()
    if missing_target_rate_years:
        coverage_warnings.add(missing_bracket_target_warning(plan_tax_target.bracket_rate, missing_target_rate_years))
    def rule_account_name(account_id):
        account = plan_data.accounts.get(account_id)
        return (account.name if account is not None else None) or account_id
    for (_, source_id, target_id, _), (rate, years) in missing_rule_rate_years.items():
        coverage_warnings.add(missing_bracket_target_warning(
            rate, years, subject=f"The {rule_account_name(source_id)} to {rule_account_name(target_id)} conversion rule's"))

    # Workplace plans with deferral rules, named in the catch-up note.
    catchup_families = sorted({EMPLOYER_PLAN_FAMILY[plan_data.accounts[p.target_account_id].account_type]
                               for p in plan_data.priorities
                               if plan_data.accounts.get(p.target_account_id) is not None
                               and plan_data.accounts[p.target_account_id].account_type in ELECTIVE_DEFERRAL_TYPES})
    return (
        [inherited_history_note(a.name or aid, a.inheritance_settings or {})
         for aid,a in plan_data.accounts.items()
         if a.inherited_year is not None and a.account_type in TRADITIONAL_RETIREMENT_TYPES
         and (a.inheritance_settings or {}).get('distribution_method') != 'spousal_rollover'
         and ((a.inheritance_settings or {}).get('decedent_died_after_rbd') is None
              or (a.inheritance_settings or {}).get('decedent_birth_year') is None)]
        +
        (["Household mismatch: spouse-owned accounts or income exist without a partner profile. Review account ownership, income recipients and Partner and estate before relying on this plan."]
         if plan_data.spouse_birth_year is None and (any(a.owner == "spouse" for a in plan_data.accounts.values())
             or any(i.owner == "spouse" for i in plan_data.income_streams)) else [])
        + (["Household mismatch: joint filing requires a partner profile. Review Plan details and Partner and estate."]
           if plan_data.filing_status == "married_filing_jointly" and plan_data.spouse_birth_year is None else [])
        +
        (["Midyear projection: Enter YTD income and tax paid to replace pro-rata estimates."]
         if opening_ytd_imputed else [])
        + (["Midyear projection: Enter YTD income and tax paid; missing history is zero."]
           if plan_data.first_year_fraction < 1 and not provided_ytd and not opening_ytd_imputed else [])
        + [note for a in plan_data.real_assets
           if (note := property_sale_note(a, purchased=a.id in purchase_positions)) is not None]
        + ([DIVIDEND_YIELD_PROVENANCE] if used_historical_yields else [])
        + (["Some replayed years had no recorded dividend yield; those years were split using the plan's dividend yield assumption."]
           if used_assumed_yield_fallback else [])
        + ([f"No surplus allocation rules: first-year excess income goes to {flow.account_name} (default destination). Set an allocation rule to choose where it goes."
            for flow in timeline[0].cash_flow.contributions if flow.source == "default_sink"]
           if timeline and timeline[0].cash_flow and not any(p.priority_type in (None, "contribution") for p in plan_data.priorities) else [])
        + healthcare_warning_set
        + (["Last-survivor projection models deaths at calendar year end, transfers sole-owner accounts to the spouse next January, and retains original owner income boundaries. Joint taxable basis is retained because ownership share and community-property step-up evidence are unspecified."] if lifecycle.enabled(plan_data) and not estate.joint_account_step_up else [])
        + (["Last-survivor projection models deaths at calendar year end, transfers sole-owner accounts to the spouse next January, and retains original owner income boundaries. Joint taxable accounts step up the decedent's half of their basis at the first death, or all of it when the residence then is a community property state."] if lifecycle.enabled(plan_data) and estate.joint_account_step_up else [])
        + (["Social Security survivor benefits are off; household longevity does not establish eligibility or enable a disabled benefit assumption."] if lifecycle.enabled(plan_data) and plan_data.spouse_birth_year is not None and survivor_context is None else [])
        + (["Survivor Social Security uses an explicitly confirmed eligibility assumption, the deceased's already-claimed unreduced benefit and its existing COLA, and the survivor FRA month. Birth-day exceptions and future eligibility changes/remarriage are not modeled."] if survivor_context is not None and survivor_context.pia_annual is None else [])
        + (["Survivor Social Security uses an explicitly confirmed eligibility assumption and both spouses' PIAs: the deceased's benefit with delayed credits or the reduced-worker limit, reduced for the survivor's age, from the later of the January after the death and the survivor's own claim month, replacing the survivor's own benefit when larger. Birth-day exceptions and future eligibility changes/remarriage are not modeled."] if survivor_context is not None and survivor_context.pia_annual is not None else [])
        + sorted(coverage_warnings)
        + never_active_windows(
            [(e.name, e.start_milestone_id, e.end_milestone_id) for e in (*plan_data.income_streams, *plan_data.expenses)
             if e.id not in spousal_workers],
            plan_data.milestones, state.triggered_milestone_years,
        )
        + unresolved_lock_warnings(plan_data.accounts.values(), plan_milestone_ids)
        + (["Unearned income without a tax category is taxed as investment income."]
           if any(not i.is_earned_income and not i.is_social_security and i.tax_category is None for i in plan_data.income_streams) else [])
        + (["Roth tax history is incomplete: unknown basis counts as zero and the five-year clock starts at plan start."]
           if any(a.account_type in ROTH_TYPES and a.balance > 0 and (a.roth_settings is None or (a.roth_settings.get("first_contribution_year") is None and not a.roth_settings.get("conversions"))) for a in plan_data.accounts.values()) else [])
        + (["Backdoor Roth contributions were partly taxable under the pro-rata rule because pre-tax traditional IRA balances exist; the after-tax basis left behind in the traditional IRA is not tracked."]
           if state.backdoor_prorata_taxable > 0 else [])
        + ([f"{'/'.join(catchup_families)} catch-up eligibility: the opening year tests the Roth catch-up wage threshold against that year's projected wages, annualized for a partial year, because prior-year wages are not entered. Later years use the prior year's projected wages, with a partial opening year annualized unless year-to-date wages are entered. Employer limits are conservatively shared across this person's plans; plan-specific eligibility and limits must be confirmed."]
           if catchup_families else [])
        + (["SEPP fixed annuitization uses an approximate mortality table; switch to fixed amortization for a verified payment."]
           if plan_data.sepp_settings is not None and plan_data.sepp_settings.enabled
           and plan_data.sepp_settings.method == "fixed_annuitization" else [])
        + (["The custom SEPP payment does not match the fixed amortization amount for the entered balance, age and interest rate (at most 5%), so it is projected as an ordinary early withdrawal with the 10% additional tax. Only an IRS-approved method keeps the 72(t) exemption."]
           if state.sepp_custom_qualified is False else [])
        + (["The custom SEPP payment matches an approved method and runs until the later of five years or age 59 1/2. Changing or missing a payment before then modifies the series and applies the 10% additional tax to all earlier payments; the projection does not charge that retroactive tax."]
           if state.sepp_custom_qualified is True else [])
        + (["The SEPP source account could not pay the scheduled amount. A shortfall modifies the series (IRC 72(t)(4)); the projection does not charge the retroactive additional tax."]
           if state.sepp_underfunded else [])
    )


def _snapshot_schema(s: YearSnapshot) -> YearSnapshotSchema:
    """The wire-format schema for one engine year snapshot."""
    return YearSnapshotSchema(
        year=s.year,
        age=s.age,
        gross_income=s.gross_income,
        calendar_year_gross_income=s.calendar_year_gross_income,
        taxes=s.taxes,
        expenses=s.expenses,
        net_cash_flow=s.net_cash_flow,
        accounts=s.accounts,
        real_assets_value=s.real_assets_value,
        liabilities_balance=s.liabilities_balance,
        net_worth=s.net_worth,
        effective_rate=s.effective_rate,
        marginal_rate=s.marginal_rate,
        deduction_used=s.deduction_used,
        deduction_amount=s.deduction_amount,
        standard_deduction=s.standard_deduction,
        flex_spending_reduction=s.flex_spending_reduction,
        flex_spending_increase=s.flex_spending_increase,
        leftover_spending=s.leftover_spending,
        investment_growth=s.investment_growth,
        investment_fees=s.investment_fees,
        tax_balance=s.tax_balance,
        unfunded_expenses=s.unfunded_expenses,
        capital_loss_carryforward=s.capital_loss_carryforward,
        federal_tax=s.federal_tax,
        state_tax=s.state_tax,
        local_tax=s.local_tax,
        state_retirement_exclusion=s.state_retirement_exclusion,
        ss_earnings_test_withheld=s.ss_earnings_test_withheld,
        state_social_security_subtraction=s.state_social_security_subtraction,
        state_capital_gains_excise=s.state_capital_gains_excise,
        tax_adjustment_deductions=s.tax_adjustment_deductions,
        tax_adjustment_credits=s.tax_adjustment_credits,
        tax_adjustment_surcharge=s.tax_adjustment_surcharge,
        rental_income=s.rental_income,
        rental_expenses=s.rental_expenses,
        rental_depreciation=s.rental_depreciation,
        rental_taxable_income=s.rental_taxable_income,
        suspended_passive_losses=s.suspended_passive_losses,
        unrecaptured_section_1250_gain=s.unrecaptured_section_1250_gain,
        real_estate_purchases=s.real_estate_purchases,
        rule_funding_shortfall=s.rule_funding_shortfall,
        tax_country=s.tax_country,
        intl_tax_lines=s.intl_tax_lines,
        national_income_tax=s.national_income_tax,
        regional_income_tax=s.regional_income_tax,
        social_contributions=s.social_contributions,
        wealth_tax=s.wealth_tax,
        transaction_tax=s.transaction_tax,
        benefit_recovery_tax=s.benefit_recovery_tax,
        capital_gains_tax=s.capital_gains_tax,
        fica_tax=s.fica_tax,
        niit_tax=s.niit_tax,
        amt_tax=s.amt_tax,
        early_withdrawal_penalty=s.early_withdrawal_penalty,
        milestones_triggered=s.milestones_triggered,
        healthcare=HealthcareYearSchema(**asdict(s.healthcare)) if s.healthcare is not None else None,
        harvested_gains=s.harvested_gains,
        debt_forgiven=s.debt_forgiven,
        debt_forgiveness_taxable=s.debt_forgiveness_taxable,
        tax_target_room=s.tax_target_room,
        tax_target_blended_withdrawals=s.tax_target_blended_withdrawals,
        bond_allocation_by_account=dict(s.bond_allocation_by_account),
        strategy_spending=s.strategy_spending,
        planned_expenses=s.planned_expenses,
        inflation_factor=s.inflation_factor,
        post_start_taxes=s.post_start_taxes,
        warnings=list(s.warnings),
        transfers=[
            TransferFlowSchema(
                source_account_id=t.source_account_id,
                target_account_id=t.target_account_id,
                amount=t.amount,
                source_account_name=t.source_account_name,
                target_account_name=t.target_account_name,
            )
            for t in s.transfers
        ],
        cash_flow=CashFlowBreakdownSchema(
            income_sources=[
                NamedAmountSchema(name=na.name, amount=na.amount, category=na.category, source=na.source)
                for na in s.cash_flow.income_sources
            ],
            gross_income=s.cash_flow.gross_income,
            tax_withheld=s.cash_flow.tax_withheld,
            payroll_deductions=s.cash_flow.payroll_deductions,
            net_pay=s.cash_flow.net_pay,
            early_withdrawal_penalty=s.cash_flow.early_withdrawal_penalty,
            tax_delta=s.cash_flow.tax_delta,
            estimated_tax_payments=s.cash_flow.estimated_tax_payments,
            required_annual_payment=s.cash_flow.required_annual_payment,
            underpayment_penalty=s.cash_flow.underpayment_penalty,
            expenses=[
                NamedAmountSchema(name=na.name, amount=na.amount, category=na.category,
                                  discretionary_amount=na.discretionary_amount)
                for na in s.cash_flow.expenses
            ],
            payroll_expenses=[
                NamedAmountSchema(name=na.name, amount=na.amount, category=na.category, source=na.source)
                for na in s.cash_flow.payroll_expenses
            ],
            contributions=[
                NamedAmountSchema(
                    name=na.name, amount=na.amount, category=na.category,
                    account_id=na.account_id, account_name=na.account_name,
                    source=na.source, priority_rank=na.priority_rank,
                    requested_amount=na.requested_amount, limited_by=na.limited_by,
                    funding_reasons=na.funding_reasons,
                )
                for na in s.cash_flow.contributions
            ],
            transfers=[
                TransferFlowSchema(
                    source_account_id=t.source_account_id,
                    target_account_id=t.target_account_id,
                    amount=t.amount,
                    source_account_name=t.source_account_name,
                    target_account_name=t.target_account_name,
                )
                for t in s.cash_flow.transfers
            ],
            drawdowns=[
                NamedAmountSchema(name=na.name, amount=na.amount, category=na.category,
                                  account_id=na.account_id, account_name=na.account_name)
                for na in s.cash_flow.drawdowns
            ],
        ) if s.cash_flow is not None else None,
    )


def _ss_wage_index(wage_indices: dict[int, float], curves, birth_year: int, default_inflation: float,
                   target_year: int) -> float:
    """The national average wage index for ``target_year``, relative to 2024.

    Years outside the published series follow the plan's wage-growth
    curve. ``wage_indices`` keeps every year filled in.
    """
    if target_year not in wage_indices:
        if target_year > 2024:
            for wage_year in range(2024, target_year):
                rate = resolve_assumption(curves, "wage_growth", wage_year, birth_year, default_inflation)
                wage_indices[wage_year + 1] = wage_indices[wage_year] * (1 + rate)
        else:
            for wage_year in range(2023, target_year - 1, -1):
                rate = resolve_assumption(curves, "wage_growth", wage_year, birth_year, default_inflation)
                wage_indices[wage_year] = wage_indices[wage_year + 1] / (1 + rate)
    return wage_indices[target_year]


@dataclass
class _YearTax:
    """One year's income tax computation (step 6 and every recomputation).

    The inputs are bound once the year's income, payroll and residence are
    known. Steps 8 to 10 add to the accumulators before recomputing, and
    each computation records its by-products for the year's close.
    """

    plan_data: PlanData
    state: SimState
    year: int
    age: int
    ytd: Mapping[str, Any]
    ytd_imputed: bool
    tax_settings: Mapping[str, Any]
    annual_tax_settings: Mapping[str, Any] | None
    filing_status: str
    tax_holder_age: int | None
    tax_spouse_age: int | None
    federal_inflation_factor: float
    calendar_inflation: dict[int, float]
    default_inflation: float
    year_adjustments: Any
    # A year taxed by another country (coastmath.engine.intl_regime).
    intl_year: bool
    year_country: str
    year_region: str | None
    regime_context: Any
    regime_prior: tuple[str, object] | None
    regime_opening: Any
    intl_benefits: list
    # Income (step 3) and required distributions (steps 2c to 3b).
    income_by_id: dict[str, float]
    gross_income: float
    ss_income: float
    earned_income: float
    w2_income: float
    ca_w2_income: float
    non_earned_income: float
    local_stream_income: dict[str | None, float]
    has_self_employment: bool
    w2_by_owner: dict[str, float]
    fica_w2_by_owner: dict[str, float]
    se_by_owner: dict[str, float]
    taxable_cash_interest: float
    taxable_rmd_total: float
    qcd_rmd_offset: float
    sepp_income: float
    rental_year: dict
    # Payroll (step 4).
    roth_employer_income: float
    payroll_tax_deductions: float
    self_employed_adjustments: float
    self_employed_plan_deductions: float
    payroll_retirement_deductions: float
    payroll_ira_deductions: float
    payroll_nj_deferrals: float
    payroll_state_addback: float
    payroll_local_addback: float
    payroll_salt: float
    ira_covered_owners: set[str]
    ira_employer_contributions: dict[str, float]
    opening_ira_by_owner: dict[str, float]
    # Gifts (step 5b).
    charitable_result: CharitableResult
    charitable_deduction: float
    charitable_property: float
    # Residence.
    resolved_state_code: str | None
    resolved_local_tax: Any
    residency_states: tuple[str, ...]
    ca_move_year: bool
    nonresident_payroll_wages: bool
    salt_passes: int
    salt_tolerance: float
    # Accumulators later steps change before recomputing.
    ordinary_drawdown_income: float
    mortgage_interest: float
    property_tax_paid: float
    hsa_exposure: bool
    # Pre-tax contributions funded from after-tax cash in the savings
    # waterfall (step 10). They are cash-neutral but reduce taxable
    # income; the settlement loop recomputes the tax after allocation.
    waterfall_pretax_deductions: float = 0.0
    # The IRA/401(k) share of those, which some states tax.
    waterfall_retirement_deductions: float = 0.0
    # The traditional IRA share, which NJ taxes.
    waterfall_ira_deductions: float = 0.0
    # Health coverage (step 6b); medical deductions are opt-in.
    healthcare_year: HealthcareYear | None = None
    hc_settings: Any = None
    medical_deductions: bool = False
    hsa_medical_start: float = 0.0
    # By-products of the latest computation.
    regime_wealth: dict = field(default_factory=dict)
    imputed_tax_credit: float | None = None
    state_allocation_diagnostics: tuple[str, ...] = ()
    local_tax_diagnostics: tuple[str, ...] = ()
    # State-taxed contribution basis recovered by the latest computation.
    basis_recovery: dict[str, float] = field(default_factory=dict)
    # Passive loss result of the latest computation (rentals only).
    passive_result: real_estate.PassiveResult | None = None


def _ca_wage_context(tax: _YearTax) -> CAPartYearWageContext | None:
    """Bound the repair to timed W2 wages; preserve explicit fallbacks.

    Existing inputs do not identify nonresident work, deferred pay or
    state-specific YTD income. Do not infer those facts from residence
    or from payroll insurance coverage. Tax settlement calls this again
    after contributions and withdrawals so unsupported deductions cannot
    appear after an initially supported calculation unnoticed.
    """
    state, ytd = tax.state, tax.ytd
    if not tax.ca_move_year or tax.tax_settings.get("mode") == "flat":
        return None
    unsupported = []
    if tax.w2_income <= 0:
        unsupported.append("no supported timed W2 wages")
    ytd_amounts = (
        "gross_income", "deductions", "capital_gains", "qualified_dividends",
        "social_security_income", "net_investment_income",
    )
    if any(float(ytd.get(key, 0.0)) != 0 for key in ytd_amounts) or any(
        float(value) != 0
        for key in ("w2_income_by_owner", "self_employment_income_by_owner")
        for value in ytd.get(key, {}).values()
    ):
        unsupported.append("supplied year-to-date income has no state attribution")
    tax.hsa_exposure = tax.hsa_exposure or any(
        account.account_type == "hsa" and (
            account.balance != 0
            or state.ytd_contributions.get(identity, 0.0) != 0
        )
        for identity, account in state.accounts.items()
    )
    if tax.hsa_exposure:
        unsupported.append("HSA California conformity is not established")
    if tax.nonresident_payroll_wages:
        unsupported.append(
            "explicit payroll work coverage requires separate nonresident wage sourcing"
        )
    # The tax layer independently rejects unallocated deductions, SE,
    # losses and unsupported state/custom-bracket combinations. Actual
    # funded contributions remain untouched; payment timing and CA
    # conformity must be demonstrated before classifying a deduction.
    return CAPartYearWageContext(
        total_w2_wages=tax.w2_income,
        ca_w2_wages=tax.ca_w2_income,
        legacy_residual_in_ca=tax.resolved_state_code == "CA",
        residency_state_codes=tax.residency_states,
        unsupported_reason="; ".join(unsupported) if unsupported else None,
    )


def _local_income(tax: _YearTax) -> LocalIncome:
    """Calendar-year income by local-tax category, including opening YTD.

    Opening wages and business income are already in the by-owner
    totals; opening investment income has no finer category.
    """
    state, ytd = tax.state, tax.ytd
    return LocalIncome(
        wages=sum(tax.w2_by_owner.values()),
        medicare_wages=sum(tax.fica_w2_by_owner.values()),
        # Box 1 wages: payroll pre-tax deductions, not savings-waterfall ones.
        taxable_wages=max(0.0, sum(tax.w2_by_owner.values()) - tax.payroll_tax_deductions
                          + tax.payroll_local_addback - float(ytd.get("deductions", 0.0))),
        self_employment=sum(tax.se_by_owner.values()),
        # Local dividend bases (Philadelphia) tax nonqualified dividends too.
        dividends=(state.qualified_dividends_this_year + state.ordinary_dividends_this_year
                   + float(ytd.get("qualified_dividends", 0.0))),
        us_obligation_interest=state.treasury_interest_this_year,
        # Uncategorized legacy streams follow their NIIT treatment.
        investment_income=(tax.local_stream_income.get("investment", 0.0)
                           + tax.local_stream_income.get(None, 0.0)
                           + float(ytd.get("net_investment_income", 0.0))),
        annuity_income=tax.local_stream_income.get("nonqualified_annuity", 0.0),
        pension_income=tax.local_stream_income.get("qualified_pension", 0.0),
        retirement_distributions=(
            tax.ordinary_drawdown_income + tax.sepp_income + tax.taxable_rmd_total - tax.qcd_rmd_offset
            + state.roth_conversions_this_year
            + (state.roth_ledger.totals()[0] if state.roth_ledger else 0.0)
        ),
    )


def _ira_contributions_by_owner(tax: _YearTax) -> dict[str, float]:
    """This year's own traditional IRA contributions, opening YTD included."""
    state = tax.state
    contributed: dict[str, float] = {}
    for account_id, account in state.accounts.items():
        if account.account_type == "traditional_ira":
            amount = (state.ytd_contributions.get(account_id, 0.0)
                      - tax.ira_employer_contributions.get(account_id, 0.0))
            if amount > 0:
                contributed[account.owner] = contributed.get(account.owner, 0.0) + amount
    return contributed


def _projected_ira_contributions(tax: _YearTax, contributed: dict[str, float]) -> float:
    """Contributions beyond the opening YTD ones already in ``deductions``."""
    return sum(max(0.0, amount - tax.opening_ira_by_owner.get(owner, 0.0))
               for owner, amount in contributed.items())


def _ira_deduction_addback(tax: _YearTax) -> float:
    """Traditional IRA contributions inside ``deductions`` before the 219(g) cut."""
    return (_projected_ira_contributions(tax, _ira_contributions_by_owner(tax))
            + min(sum(tax.opening_ira_by_owner.values()), float(tax.ytd.get("deductions", 0.0))))


def _ira_nondeductible_contributions(tax: _YearTax, federal_args: dict) -> float:
    """Projected traditional IRA contributions the phase-out leaves undeducted.

    IRC 219(g), Pub. 590-A Worksheets 1-1 and 1-2. Modified AGI is this
    year's AGI figured without any IRA deduction, so Roth conversions
    count and taxable Social Security is figured without it too (Pub.
    590-A Appendix B). The engine models no other Worksheet 1-1
    add-back. Each owner's limit uses the joint MAGI of the return.
    """
    if not tax.ira_covered_owners:
        return 0.0
    contributed = _ira_contributions_by_owner(tax)
    projected = _projected_ira_contributions(tax, contributed)
    if projected <= 0:
        return 0.0
    magi_result = calculate_tax(**{
        **federal_args, "deductions": federal_args["deductions"] - projected,
        "state_code": None, "local_tax": None, "local_income": None,
        "ca_part_year_context": None, "state_income_adjustment": 0.0, "retirement_income": None,
    })
    magi = magi_result.modified_agi + min(sum(tax.opening_ira_by_owner.values()),
                                          float(tax.ytd.get("deductions", 0.0)))
    nondeductible = 0.0
    for owner, amount in contributed.items():
        limit = traditional_ira_deduction_limit(
            tax.state.owner_ages.get(owner, tax.age), tax.filing_status, magi,
            covered=owner in tax.ira_covered_owners,
            spouse_covered={"self": "spouse", "spouse": "self"}.get(owner) in tax.ira_covered_owners,
            inflation_factor=tax.state.coverage_inflation_factor,
            lived_apart=bool((tax.annual_tax_settings or {}).get("mfs_lived_apart_all_year", False)),
        )
        nondeductible += max(0.0, amount - max(limit, tax.opening_ira_by_owner.get(owner, 0.0)))
    return nondeductible


def _aca_magi(tax: _YearTax, result: TaxResult) -> float:
    """Premium tax credit MAGI for a tax result."""
    # IRS PTC MAGI adds back the final nontaxable SS amount. IRA
    # withdrawals/conversions can change that split during settlement.
    # IRC 36B(d)(2)(B) also adds back tax-exempt (municipal) interest.
    nontaxable_ss = max(0.0, tax.ss_income + float(tax.ytd.get("social_security_income", 0.0))
                        - result.taxable_social_security)
    return result.modified_agi + nontaxable_ss + result.tax_exempt_interest


def _ptc_final(tax: _YearTax, result: TaxResult) -> float:
    """Final premium tax credit for the year on post-withdrawal MAGI."""
    hc = tax.healthcare_year
    if hc is None or hc.aca_covered_adults <= 0 or hc.aca_gross_premium <= 0:
        return 0.0
    return calculate_premium_tax_credit(
        _aca_magi(tax, result), hc.aca_household_size, hc.aca_benchmark_premium,
        hc.aca_gross_premium, covered_adults=hc.aca_covered_adults,
        state_group=tax.hc_settings.aca_state_group, inflation_factor=tax.state.coverage_inflation_factor,
        coverage_periods=tax.healthcare_year.aca_coverage_periods, filing_status=tax.filing_status,
    ).credit


def _medical_deductions(tax: _YearTax, result: TaxResult) -> tuple[float, float]:
    """Medical deductions for this result's AGI (IRC 162(l), 213).

    Returns (self-employed health insurance deduction, itemizable medical
    expenses). Premiums are ACA premiums net of the final premium tax
    credit plus Medicare premiums (Parts A, B, D, IRMAA, Medigap). A
    self-employed household deducts them above the line up to net
    self-employment profit (after the deductible half of SE tax and SE
    retirement contributions); employer-plan eligibility is not modeled.
    The rest, with out-of-pocket, itemized-mode and net long-term care
    costs, is itemizable, less what HSA withdrawals reimbursed tax free.
    """
    hc = tax.healthcare_year
    aca_net = max(0.0, hc.aca_gross_premium - _ptc_final(tax, result))
    premiums = aca_net + (hc.medicare_part_a + hc.medicare_part_b + hc.medicare_irmaa_part_b
                          + hc.medicare_irmaa_part_d + hc.medicare_part_d_plan
                          + hc.medicare_supplement)
    se_profit = (sum(tax.se_by_owner.values()) - tax.self_employed_plan_deductions
                 - result.self_employment_tax / 2.0)
    se_deduction = min(premiums, max(0.0, se_profit)) if tax.has_self_employment else 0.0
    hsa_paid = max(0.0, tax.hsa_medical_start - max(0.0, tax.state.hsa_medical_allowance or 0.0))
    itemizable = max(0.0, premiums - se_deduction + hc.itemized_medical + hc.out_of_pocket
                     + hc.long_term_care - hsa_paid)
    return se_deduction, itemizable


def _tax_with_salt_estimate(
    tax: _YearTax, federal_args: dict, *, ira_nondeductible: float, state_529_deduction: float,
    extra_deductions: float, medical_expenses: float,
) -> TaxResult:
    """The year's tax, iterating the SALT itemized deduction to a fixed point.

    State and local income tax are both itemized SALT, and opt-in state
    deduction rules feed the federal tax back into the state's.
    """
    state = tax.state
    resolved_state_code = tax.resolved_state_code
    state_tax_estimate = local_tax_estimate = 0.0
    for _ in range(tax.salt_passes):
        itemized = {"property_tax": tax.property_tax_paid,
            "mortgage_interest": tax.mortgage_interest,
            "salt": max(state_tax_estimate, float(tax.ytd.get("state_tax_paid", 0.0))) + tax.payroll_salt}
        if tax.tax_settings.get("state_deduction_rules"):
            # The local part of SALT, which some states deduct.
            itemized["local_income_tax"] = local_tax_estimate
        result = calculate_tax(
            **{**federal_args, "deductions": federal_args["deductions"] + extra_deductions},
            medical_expenses=medical_expenses,
            state_code=resolved_state_code,
            local_tax=tax.resolved_local_tax,
            local_income=_local_income(tax) if tax.resolved_local_tax else None,
            ca_part_year_context=_ca_wage_context(tax),
            retirement_income=_retirement_income(state, tax.plan_data, tax.year),
            real_estate_capital_gains=state.real_estate_gains_this_year,
            state_contribution_basis_recovery=sum(tax.basis_recovery.values()),
            state_contribution_basis_distributions=basis_distributions(state, resolved_state_code),
            # Schedule CA: employee deductions are added back and
            # employer funding is taxable once. HSA YTD totals already
            # include both sources, including earlier-year payments.
            state_income_adjustment=(sum(amount for aid, amount in state.ytd_contributions.items()
                if aid in state.accounts and state.accounts[aid].account_type == "hsa")
                if resolved_state_code == "CA"
                else tax.payroll_retirement_deductions + tax.waterfall_retirement_deductions - ira_nondeductible
                if resolved_state_code in _STATES_TAXING_RETIREMENT_CONTRIBUTIONS
                else tax.payroll_ira_deductions + tax.waterfall_ira_deductions - ira_nondeductible + (tax.payroll_nj_deferrals if resolved_state_code == "NJ" else 0.0)
                if resolved_state_code in _STATES_TAXING_IRA_CONTRIBUTIONS else 0.0)
                - state_529_deduction + tax.payroll_state_addback,
            itemized_deductions=itemized,
        )
        # Retain the final recomputation's diagnostics for this year;
        # intermediate settlement amounts must not masquerade as final.
        tax.state_allocation_diagnostics = result.state_allocation_diagnostics
        tax.local_tax_diagnostics = result.local_tax_diagnostics
        if abs(result.state + result.local - state_tax_estimate) < tax.salt_tolerance:
            break
        state_tax_estimate = result.state + result.local
        local_tax_estimate = result.local
    return result


def _compute_tax(tax: _YearTax) -> TaxResult:
    """Step 6: the year's income tax on everything recorded so far.

    Later steps call this again after each change to income, deductions
    or withdrawals. A year taxed by another country uses its regime.
    """
    state, ytd = tax.state, tax.ytd
    if tax.intl_year:
        return _regime_year_tax(
            tax.plan_data, state, tax.year, year_country=tax.year_country, year_region=tax.year_region,
            regime_context=tax.regime_context, regime_prior=tax.regime_prior, regime_opening=tax.regime_opening,
            regime_wealth=tax.regime_wealth, calendar_inflation=tax.calendar_inflation,
            default_inflation=tax.default_inflation, filing_status=tax.filing_status, income_by_id=tax.income_by_id,
            ss_income=tax.ss_income, intl_benefits=tax.intl_benefits,
            ordinary_drawdown_income=tax.ordinary_drawdown_income,
            taxable_rmd_total=tax.taxable_rmd_total, qcd_rmd_offset=tax.qcd_rmd_offset, sepp_income=tax.sepp_income,
            taxable_cash_interest=tax.taxable_cash_interest, rental_year=tax.rental_year)
    # Full calendar-year calculation; prior earnings affect brackets
    # but never become new cash. Prior payments are credited separately.
    # State and local income taxes are both itemized SALT.
    federal_args = dict(
        # Reinvested ordinary dividends and taxable bond interest
        # are ordinary income (and NII) without being spendable cash.
        gross_income=(tax.gross_income + tax.ordinary_drawdown_income + tax.roth_employer_income
                      # Cancelled debt is income that creates no cash (IRC 61(a)(11)).
                      + state.cod_income_this_year
                      + state.hsa_taxable_distributions_this_year
                      # Earnings in nonqualified 529 withdrawals (IRC 529(c)(3)(A)).
                      + state.education_taxable_earnings_this_year
                      + (state.roth_ledger.totals()[0] if state.roth_ledger else 0.0)
                      + float(ytd.get("gross_income", 0.0))
                      + state.ordinary_investment_income_this_year
                      # Taxable withdrawals from country account kinds.
                      + (intl_accounts.withdrawal_income(state).taxable if state.intl_kinds else 0.0)),
        deductions=(tax.payroll_tax_deductions + tax.self_employed_adjustments
                    + tax.waterfall_pretax_deductions + float(ytd.get("deductions", 0.0))),
        filing_status=tax.filing_status, settings=tax.annual_tax_settings,
        holder_age=tax.tax_holder_age, spouse_age=tax.tax_spouse_age,
        capital_gains=state.capital_gains_this_year + float(ytd.get("capital_gains", 0.0)),
        qualified_dividends=state.qualified_dividends_this_year + float(ytd.get("qualified_dividends", 0.0)),
        capital_loss_carryforward=state.capital_loss_carryforward,
        roth_conversions=state.roth_conversions_this_year,
        # Direct QCDs were never income; offset only IRA RMDs already included.
        rmd_income=tax.taxable_rmd_total, qcd_offset=tax.qcd_rmd_offset,
        charitable_deduction=tax.charitable_deduction,
        charitable_direct_cash=tax.charitable_result.direct_cash_contributions,
        charitable_capital_gain_property=tax.charitable_property,
        social_security_income=tax.ss_income + float(ytd.get("social_security_income", 0.0)),
        earned_income=tax.earned_income, is_self_employed=tax.has_self_employment,
        # 529 earnings are taxed as annuity income under IRC 72, which
        # IRC 1411(c)(1)(A)(i) includes; 529s are not among the
        # retirement plans 1411(c)(5) excludes.
        net_investment_income=(tax.non_earned_income + float(ytd.get("net_investment_income", 0.0))
                               + state.ordinary_investment_income_this_year
                               + state.education_taxable_earnings_this_year),
        tax_exempt_interest=state.municipal_interest_this_year,
        in_state_municipal_interest=state.state_exempt_municipal_interest_this_year,
        us_obligation_interest=state.treasury_interest_this_year,
        tax_year=tax.year, w2_income_by_owner=tax.fica_w2_by_owner,
        self_employment_income_by_owner=tax.se_by_owner,
        qualified_business_income=max(0.0, sum(tax.se_by_owner.values()) - tax.self_employed_plan_deductions),
        inflation_factor=state.inflation_factor,
        federal_inflation_factor=tax.federal_inflation_factor,
        calendar_inflation=tax.calendar_inflation,
        adjustments=tax.year_adjustments,
    )
    # Rental real estate (coastmath.engine.real_estate): the net Schedule E
    # amount the passive loss rules allow is ordinary income and net
    # investment income, never self-employment income. The special
    # allowance phase-out uses AGI before rental items and the
    # section 219 IRA deduction (IRC 469(i)(3)(F)); taxable Social
    # Security is not in gross_income.
    # A net section 1231 loss on a rental sale is ordinary.
    tax.passive_result = None
    if tax.rental_year or state.disposed_rentals_this_year:
        taxable_rmd = tax.taxable_rmd_total - min(tax.qcd_rmd_offset, tax.taxable_rmd_total)
        allowance_magi = (federal_args["gross_income"] + federal_args["roth_conversions"] + taxable_rmd
                          - federal_args["deductions"] + _ira_deduction_addback(tax)
                          + max(0.0, federal_args["capital_gains"] - federal_args["capital_loss_carryforward"])
                          + federal_args["qualified_dividends"])
        tax.passive_result = real_estate.passive_activity_result(
            list(tax.rental_year.values()), state.suspended_passive_losses,
            state.disposed_rentals_this_year, allowance_magi, tax.filing_status,
            lived_apart=bool((tax.annual_tax_settings or {}).get("mfs_lived_apart_all_year", False)),
        )
        federal_args["gross_income"] += tax.passive_result.allowed
        federal_args["net_investment_income"] += tax.passive_result.allowed
        qbi_rental = sum(amount for asset_id, amount in tax.passive_result.allowed_by_asset.items()
                         if asset_id in tax.rental_year and tax.rental_year[asset_id].qbi_eligible)
        if qbi_rental:
            federal_args["qualified_business_income"] = max(
                0.0, sum(tax.se_by_owner.values()) - tax.self_employed_plan_deductions + qbi_rental)
    federal_args["gross_income"] -= state.real_estate_ordinary_loss_this_year
    if state.unrecaptured_1250_this_year > 0:
        federal_args["unrecaptured_section_1250_gain"] = state.unrecaptured_1250_this_year
    # The deposit stays whole; only the deduction shrinks. Federal AGI
    # then already contains the nondeductible part, so states without an
    # IRA deduction add back only the part that was deducted.
    ira_nondeductible = _ira_nondeductible_contributions(tax, federal_args)
    federal_args["deductions"] -= ira_nondeductible
    tax.basis_recovery = basis_recovery_by_account(state, tax.resolved_state_code)
    # Optional state deduction for 529 contributions (state data).
    state_529_deduction = (
        state_contribution_deduction(
            tax.resolved_state_code, tax.filing_status, state.education_contributions_this_year,
            state.education_qualified_withdrawals_this_year)
        if tax.tax_settings.get("state_529_deduction") and tax.tax_settings.get("mode") != "flat" else 0.0)

    # Medical deductions (opt-in): the self-employed health insurance
    # deduction lowers AGI and so raises the premium tax credit, which
    # lowers the deductible premium. Alternate the two until they
    # settle (IRS Pub. 974 iterative method).
    se_health_deduction = medical_expenses = 0.0
    for _ in range(10):
        result = _tax_with_salt_estimate(
            tax, federal_args, ira_nondeductible=ira_nondeductible, state_529_deduction=state_529_deduction,
            extra_deductions=se_health_deduction, medical_expenses=medical_expenses)
        if not tax.medical_deductions:
            break
        next_se, next_medical = _medical_deductions(tax, result)
        if abs(next_se - se_health_deduction) < .5 and abs(next_medical - medical_expenses) < .5:
            break
        se_health_deduction, medical_expenses = next_se, next_medical
    return replace(result, ira_nondeductible_contributions=ira_nondeductible) if ira_nondeductible else result


def _opening_tax_paid(tax: _YearTax) -> float:
    """Tax for the year paid before the projection starts."""
    if tax.intl_year:
        # A country year taxes only the projected period.
        return 0.0
    if tax.ytd_imputed:
        # Only the pre-start share of modeled income streams is
        # treated as paid. Account withdrawals, RMDs and realized
        # gains arise after the projection starts, so their tax must
        # not be credited to an unobserved pre-start period.
        if tax.imputed_tax_credit is None:
            tax.imputed_tax_credit = _imputed_stream_tax_credit(
                tax.plan_data, tax.state, tax.year, ytd=tax.ytd, income_by_id=tax.income_by_id,
                filing_status=tax.filing_status, annual_tax_settings=tax.annual_tax_settings,
                resolved_state_code=tax.resolved_state_code, resolved_local_tax=tax.resolved_local_tax,
                tax_holder_age=tax.tax_holder_age, tax_spouse_age=tax.tax_spouse_age,
                federal_inflation_factor=tax.federal_inflation_factor, calendar_inflation=tax.calendar_inflation,
                year_adjustments=tax.year_adjustments, salt_passes=tax.salt_passes,
                salt_tolerance=tax.salt_tolerance, ca_wage_context=partial(_ca_wage_context, tax))
        return tax.imputed_tax_credit
    return float(tax.ytd.get("tax_paid", 0.0))


@dataclass
class _YearCash:
    """The year's cash once income, spending and tax are known (steps 9b to 10).

    Net cash, the flows reported for it and the tax settled against it.
    Targeted Roth conversion trials checkpoint and restore these fields
    together with the simulation state.
    """

    tax: _YearTax
    year_fraction: float
    sepp_account_ids: set[str]
    withholding_rates: dict[str, float]
    tax_withheld: float
    settlement_lag_years: int
    estimated_tax_plan: Any
    estimated_tax_prior: Any
    spend_leftover_mode: bool
    contributions_for_growth: dict[str, float]
    coverage_warnings: set[str]
    net_cash: float
    tax_result: TaxResult
    actual_tax: float
    ytd_tax_paid: float
    early_withdrawal_penalty: float
    # Plan tax target (step 9c).
    year_target: YearTaxTarget | None = None
    target_aca_active: bool = False
    # Waterfall or drawdown (step 10).
    contribution_filing_status: str | None = None
    cf_drawdowns: list[NamedAmount] = field(default_factory=list)
    cf_contributions: list[NamedAmount] = field(default_factory=list)
    swept_by_rank: dict[int, float] = field(default_factory=dict)
    # Tax settlement.
    settled_tax_cash: float = 0.0
    ptc_reconciliation: float = 0.0


def _estimated_tax_year(cash: _YearCash, result: TaxResult, ptc: float):
    """IRC 6654 estimated tax for the year: this result against the payments so far."""
    tax = cash.tax
    return estimated_tax.evaluate_year(
        cash.estimated_tax_plan, tax_year=tax.year, filing_status=tax.filing_status, tax=result,
        payments=cash.ytd_tax_paid + cash.tax_withheld + tax.state.drawdown_tax_withheld_this_year,
        ptc_reconciliation=ptc, prior=cash.estimated_tax_prior)


def _conversion_context(tax: _YearTax, result: TaxResult) -> ConversionTaxContext:
    """The tax position Roth conversion and gain harvest rules are sized against."""
    state = tax.state
    healthcare_year = tax.healthcare_year
    return ConversionTaxContext(
        ordinary_taxable_income=result.taxable_income,
        modified_agi=(_aca_magi(tax, result) if healthcare_year is not None
            and healthcare_year.aca_covered_adults > 0 else result.modified_agi),
        brackets=federal_ordinary_brackets(tax.annual_tax_settings, tax.filing_status, tax.year,
                                           tax.federal_inflation_factor, state.inflation_factor),
        inflation_factor=state.inflation_factor,
        flat_tax=tax.tax_settings.get("mode") == "flat",
        ltcg_brackets=[(upper * tax.federal_inflation_factor, rate)
                       for upper, rate in get_ltcg_brackets(tax.filing_status, tax.year)],
        capital_gains_so_far=max(0.0, state.capital_gains_this_year) + state.qualified_dividends_this_year,
        unused_deduction=max(0.0, result.deduction_amount - result.agi),
    )


def _target_fits(cash: _YearCash, result: TaxResult) -> bool:
    """Whether a tax result stays within the year's plan tax target."""
    return cash.year_target is not None and cash.year_target.fits(
        tax_measures(result, aca_magi=_aca_magi(cash.tax, result), aca_active=cash.target_aca_active))


def _final_harvest_limit(cash: _YearCash, rule: PriorityData, upper: float) -> float:
    """The largest gain harvest ``rule`` allows, solved on the post-harvest tax."""
    tax = cash.tax
    state = tax.state
    if tax.intl_year and not rule.use_plan_tax_target:
        return 0.0  # US capital gains brackets do not apply abroad
    # A harvest raises MAGI, so it can raise taxable Social Security
    # (IRC 86) and phase out the senior deduction (IRC 151(d)(5)).
    # Solve the band and MAGI cap on the post-harvest tax instead of
    # the pre-harvest room. Earlier rules' gains are already in state.
    if rule.use_plan_tax_target:
        def fits_target(amount):
            realised = state.capital_gains_this_year
            state.capital_gains_this_year = realised + amount
            try:
                return _target_fits(cash, _compute_tax(tax))
            finally:
                state.capital_gains_this_year = realised
        return largest_fitting(fits_target, upper, tolerance=.001)
    context = _conversion_context(tax, cash.tax_result)
    if context.flat_tax or not context.ltcg_brackets:
        return 0.0
    band_top = None
    for bound, rate in context.ltcg_brackets:
        if abs(rate - rule.bracket_ceiling_rate) < 1e-9:
            band_top = bound
    if band_top is None:
        return 0.0

    def fits(amount):
        realised = state.capital_gains_this_year
        state.capital_gains_this_year = realised + amount
        try:
            trial = _compute_tax(tax)
        finally:
            state.capital_gains_this_year = realised
        # IRC 1(h): preferential income stacks on ordinary taxable
        # income after any deduction ordinary income could not absorb.
        taxable_gains = max(0.0, (trial.modified_agi - trial.agi)
                            - max(0.0, trial.deduction_amount - trial.agi))
        final_magi = (_aca_magi(tax, trial) if tax.healthcare_year is not None
            and tax.healthcare_year.aca_covered_adults > 0 else trial.modified_agi)
        return (trial.taxable_income + taxable_gains <= band_top
                and (rule.magi_cap is None or final_magi <= rule.magi_cap * state.inflation_factor))

    if fits(upper):
        return upper
    if not fits(0.0):
        return 0.0
    lower = 0.0
    for _ in range(40):
        if upper - lower <= .001:
            break
        middle = (lower + upper) / 2
        if fits(middle):
            lower = middle
        else:
            upper = middle
    return lower


def _transfer_months(
    state: SimState, plan_data: PlanData, year: int, year_fraction: float, milestone_map: Mapping[str, Any],
    newly_triggered: list[str], p: PriorityData,
) -> list[int]:
    """The months of the year a transfer rule moves money; none if a bounding milestone is missing."""
    if any(mid is not None and mid not in milestone_map
           for mid in (p.start_milestone_id, p.end_milestone_id)):
        return []
    return _active_months(milestone_map.get(p.start_milestone_id), milestone_map.get(p.end_milestone_id),
                          state.triggered_milestones, newly_triggered, year, plan_data.birth_month,
                          year_fraction)


def _transfer_month_growth(
    state: SimState, annual_account_rates: Mapping[str, Any], annual_income_composition: Mapping[str, Any],
    account_id: str, months: list[int],
) -> float:
    """An account's average growth from the end of each transfer month to year end."""
    account = state.accounts.get(account_id)
    if account is None or account.account_type in _ZERO_GROWTH_TYPES or not months:
        return 0.0
    rate, stock_income_rate, bond_income_rate = _price_and_income_rates(
        annual_account_rates[account_id], annual_income_composition[account_id], account.account_type)
    if reinvests_income(account):
        rate += stock_income_rate + bond_income_rate
    return _end_of_month_growth_factor(rate, months)


def _withdrawal_flow(state: SimState, aid: str, value: float, *, ordinary: bool = True) -> NamedAmount:
    """The cash-flow entry for a withdrawal from one account."""
    account = state.accounts[aid]
    name = account.name or account.account_type
    # "pretax": a distribution from a pre-tax account, ordinary income. A QCD is
    # excluded from income (IRC 408(d)(8)), so it is not one.
    pretax = ordinary and account.account_type in _ORDINARY_DRAWDOWN_ACCOUNT_TYPES
    return NamedAmount(name=name, amount=value, category="pretax" if pretax else None,
                       account_id=aid, account_name=name)


def _shortfall_order(plan_data: PlanData, state: SimState) -> list[DrawdownEntryData]:
    """The saved withdrawal order, spending generated cash first.

    Surplus in plans without a cash account is banked in generated
    cash, which no saved order can list.
    """
    order = list(plan_data.drawdown_order)
    if "unallocated_cash" in state.accounts and not any(e.source_account_id == "unallocated_cash" for e in order):
        order.insert(0, DrawdownEntryData(-1, "unallocated_cash"))
    return order


def _drawdown_trial(
    cash: _YearCash, need: float, aid: str, source: list[DrawdownEntryData], drawdown_args: dict,
    gross: float | None,
) -> tuple[float, TaxResult]:
    """(gross taken, tax result) for a withdrawal undone afterwards."""
    tax = cash.tax
    state = tax.state
    acct = state.accounts[aid]
    saved = (acct.balance, acct.cost_basis,
             {name: getattr(state, name) for name in _DRAWDOWN_TRIAL_FIELDS},
             deepcopy(state.retirement_income_this_year), tax.ordinary_drawdown_income)
    try:
        dd, _ = execute_drawdown(need, source, state, **drawdown_args,
            gross_limits=None if gross is None else {aid: gross})
        tax.ordinary_drawdown_income += _ordinary_income_from_drawdowns(dd, state)
        return dd.get(aid, 0.0), _compute_tax(tax)
    finally:
        acct.balance, acct.cost_basis, fields, retirement_income, tax.ordinary_drawdown_income = saved
        for name, value in fields.items():
            setattr(state, name, value)
        state.retirement_income_this_year = retirement_income


def _drawdown_trial_fits_target(
    cash: _YearCash, need: float, aid: str, source: list[DrawdownEntryData], drawdown_args: dict,
    gross: float,
) -> bool:
    """Whether withdrawing ``gross`` from one account keeps the year within the tax target."""
    return _target_fits(cash, _drawdown_trial(cash, need, aid, source, drawdown_args, gross)[1])


def _blend_to_tax_target(cash: _YearCash, need: float) -> tuple[dict[str, float], float, float]:
    """First drawdown pass: fill the plan tax target's room.

    Walks the withdrawal order over sources whose withdrawals create
    taxable income (see blend_source_eligible) and takes from each
    only what keeps the year's tax within the target, solved on the
    post-withdrawal tax (taxable Social Security, deduction
    phase-outs). Returns (gross withdrawals, penalty, unmet need).
    """
    tax = cash.tax
    state, plan_data = tax.state, tax.plan_data
    taken: dict[str, float] = {}
    penalty_total = 0.0
    drawdown_args = dict(age=tax.age, sepp_account_ids=cash.sepp_account_ids,
                         birth_month=plan_data.birth_month,
                         withholding_rates=cash.withholding_rates,
                         reserve_fallback=False)
    for entry in sorted(_shortfall_order(plan_data, state), key=lambda e: e.rank):
        if need <= .01:
            break
        aid = entry.source_account_id
        if aid is None or not blend_source_eligible(
                aid, state, age=tax.age, birth_month=plan_data.birth_month,
                sepp_account_ids=cash.sepp_account_ids):
            continue
        source = [DrawdownEntryData(1, aid)]
        full_gross, _ = _drawdown_trial(cash, need, aid, source, drawdown_args, None)
        cap = largest_fitting(partial(_drawdown_trial_fits_target, cash, need, aid, source, drawdown_args),
                              full_gross)
        if cap <= .005:
            continue
        prior_failure, prior_unfunded = state.failure_year, state.unfunded_expenses
        dd, penalty = execute_drawdown(need, source, state, **drawdown_args, gross_limits={aid: cap})
        # An unmet remainder here is the second pass's to fund.
        need = max(0.0, state.unfunded_expenses - prior_unfunded)
        state.failure_year, state.unfunded_expenses = prior_failure, prior_unfunded
        tax.ordinary_drawdown_income += _ordinary_income_from_drawdowns(dd, state)
        penalty_total += penalty
        for key, value in dd.items():
            taken[key] = taken.get(key, 0.0) + value
    return taken, penalty_total, need


def _record_allocations(cash: _YearCash, allocations: dict[str, float], grows_all_year: bool = True) -> None:
    """Book waterfall deposits: their growth timing and the deductions they earn."""
    tax = cash.tax
    for acct_id, amt in allocations.items():
        if grows_all_year:
            cash.contributions_for_growth[acct_id] = (
                cash.contributions_for_growth.get(acct_id, 0.0) + amt
            )
        acct_state = tax.state.accounts.get(acct_id)
        if acct_state is not None and acct_state.account_type in _PRE_TAX_CONTRIBUTION_TYPES:
            tax.waterfall_pretax_deductions += amt
        if acct_state is not None and acct_state.account_type in _RETIREMENT_CONTRIBUTION_TYPES:
            tax.waterfall_retirement_deductions += amt
            _record_waterfall_retirement_contribution(tax.state, acct_id, amt)
        if acct_state is not None and acct_state.account_type == "traditional_ira":
            tax.waterfall_ira_deductions += amt


def _draw_for_shortfall(cash: _YearCash, need: float, excluded: frozenset[str]) -> float:
    """Withdraw ``need`` for a withdraw-if-short rule; return the cash raised.

    Uses the saved withdrawal order (locks, 72(t) series,
    penalties, withholding and Roth ordering apply) without the
    excluded accounts and without spending a protected cash
    reserve. An unmet remainder is the rule's shortfall, not an
    unfunded expense. The tax the withdrawal causes is settled
    with the year's tax.
    """
    tax = cash.tax
    state, plan_data = tax.state, tax.plan_data
    order = [entry for entry in _shortfall_order(plan_data, state) if entry.source_account_id not in excluded]
    prior_failure, prior_unfunded = state.failure_year, state.unfunded_expenses
    dd, penalty = execute_drawdown(
        need, order, state, age=tax.age, sepp_account_ids=cash.sepp_account_ids,
        birth_month=plan_data.birth_month, withholding_rates=cash.withholding_rates,
        reserve_fallback=False)
    unmet = max(0.0, state.unfunded_expenses - prior_unfunded)
    state.failure_year, state.unfunded_expenses = prior_failure, prior_unfunded
    tax.ordinary_drawdown_income += _ordinary_income_from_drawdowns(dd, state)
    cash.early_withdrawal_penalty += penalty
    for acct_id, amt in dd.items():
        cash.cf_drawdowns.append(_withdrawal_flow(state, acct_id, amt))
    return max(0.0, need - unmet)


def _shortfall_magi(cash: _YearCash) -> float:
    """Roth IRA modified AGI including the withdrawals made so far."""
    tax = cash.tax
    state = tax.state
    current = _compute_tax(tax)
    magi = current.agi + max(0.0, state.capital_gains_this_year) + state.qualified_dividends_this_year
    if tax.year == tax.plan_data.start_year and 0 < cash.year_fraction < 1 and not tax.ytd:
        magi /= cash.year_fraction
    return magi


def _keep_shortfall_cash(cash: _YearCash, amount: float) -> None:
    """Cash withdrawn for a Roth IRA goal that its income limit no longer allows."""
    state = cash.tax.state
    if cash.spend_leftover_mode:
        state.leftover_cash_held += amount
        return
    sink_id = state.cash_account()
    state.deposit_to(sink_id, amount)
    cash.contributions_for_growth[sink_id] = cash.contributions_for_growth.get(sink_id, 0.0) + amount
    sink_name = state.accounts[sink_id].name or "Unallocated cash"
    cash.cf_contributions.append(NamedAmount(
        name=sink_name, amount=amount, account_id=sink_id,
        account_name=sink_name, source="default_sink",
    ))


def _fund(cash: _YearCash, amount: float) -> None:
    """Pay a bill, liquidating assets as needed without losing the deficit."""
    tax = cash.tax
    state, plan_data = tax.state, tax.plan_data
    # Cash held back from the year's surplus pays first, so a late bill
    # never sells assets while the same year's leftover is unspent.
    if state.leftover_cash_held > 0.0:
        from_held = min(amount, state.leftover_cash_held)
        state.leftover_cash_held -= from_held
        amount -= from_held
        if amount <= .005:
            return
    prior_failure = state.failure_year
    prior_unfunded = state.unfunded_expenses
    dd, penalty = execute_drawdown(amount, _shortfall_order(plan_data, state), state, age=tax.age,
        sepp_account_ids=cash.sepp_account_ids, birth_month=plan_data.birth_month,
        withholding_rates=cash.withholding_rates)
    tax.ordinary_drawdown_income += _ordinary_income_from_drawdowns(dd, state)
    cash.early_withdrawal_penalty += penalty
    for aid, value in dd.items():
        cash.cf_drawdowns.append(_withdrawal_flow(state, aid, value))
    shortfall = state.unfunded_expenses - prior_unfunded
    for asset in sorted(plan_data.real_assets, key=lambda a: a.is_primary_residence):
        if shortfall <= .01:
            break
        if not asset.auto_liquidate_on_depletion or asset.id not in state.real_asset_values:
            continue
        _sell_real_asset(state, plan_data, asset)
        aid = asset.liquidation_target_account_id
        if aid not in state.accounts:
            aid = state.cash_account()
        # Sale proceeds are available at liquidation, not a monthly
        # stream. Do not apply an earlier withdrawal growth penalty.
        factor = state.withdrawal_growth_factors.pop(aid, None)
        state.unfunded_expenses -= shortfall
        dd, penalty = execute_drawdown(shortfall, [DrawdownEntryData(1, aid)], state,
            age=tax.age, birth_month=plan_data.birth_month, withholding_rates=cash.withholding_rates)
        if factor is not None:
            state.withdrawal_growth_factors[aid] = factor
        tax.ordinary_drawdown_income += _ordinary_income_from_drawdowns(dd, state)
        cash.early_withdrawal_penalty += penalty
        for aid, value in dd.items():
            cash.cf_drawdowns.append(_withdrawal_flow(state, aid, value))
        shortfall = state.unfunded_expenses - prior_unfunded
    if shortfall <= .01:
        state.failure_year = prior_failure


def _settle_tax(cash: _YearCash, *, finalize_refunds: bool = True) -> None:
    """Reconcile the year's tax with every payment until the cash settles.

    A refund funds unmet contribution rules, then the year's leftover; a
    bill is funded like any expense. Without ``finalize_refunds`` a refund
    stays unbooked and the premium tax credit is not reconciled.
    """
    tax = cash.tax
    state, plan_data = tax.state, tax.plan_data
    healthcare_year = tax.healthcare_year
    year_fraction = cash.year_fraction
    for _ in range(100):
        cash.tax_result = _compute_tax(tax)
        cash.actual_tax = cash.tax_result.total_tax
        cash.ytd_tax_paid = _opening_tax_paid(tax)
        if (finalize_refunds and healthcare_year is not None
                and healthcare_year.aca_covered_adults > 0):
            cash.ptc_reconciliation = _ptc_final(tax, cash.tax_result) - healthcare_year.aca_credit_advanced
        else:
            cash.ptc_reconciliation = 0.0
        if cash.settlement_lag_years > 0 and cash.estimated_tax_plan is None:
            break
        roth_penalty_refund = (state.roth_penalty_charged - state.roth_ledger.totals()[1]) if state.roth_ledger else 0.0
        desired_cash = (cash.ytd_tax_paid + cash.tax_withheld + state.drawdown_tax_withheld_this_year
                        - cash.actual_tax + cash.ptc_reconciliation + roth_penalty_refund)
        if cash.estimated_tax_plan is not None:
            # A carried balance leaves only the estimates in this year;
            # same-year settlement adds the penalty. Neither feeds _compute_tax.
            desired_cash = ((desired_cash if cash.settlement_lag_years == 0 else 0.0)
                            + _estimated_tax_year(cash, cash.tax_result, cash.ptc_reconciliation)
                            .in_year_cash(cash.settlement_lag_years))
        change = desired_cash - cash.settled_tax_cash
        if abs(change) <= .005:
            break
        if change > 0 and not finalize_refunds:
            break
        cash.settled_tax_cash += change
        cash.net_cash += change
        if change > 0:
            # Fill unmet fixed requests in rank order before their later
            # remaining rules. Preserve annual caps and do not repeat a
            # percentage allocation on the same year's available cash.
            refund_rules = []
            for priority in plan_data.priorities:
                if priority.priority_type not in (None, "contribution") or priority.allocation_mode not in ("amount", "remaining"):
                    continue
                funded = sum(flow.amount for flow in cash.cf_contributions
                             if flow.source == "priority" and flow.priority_rank == priority.priority_rank)
                funded += cash.swept_by_rank.get(priority.priority_rank, 0.0)
                cap = None if priority.max_annual_amount is None else max(0.0, priority.max_annual_amount - funded)
                value = priority.allocation_value
                if priority.allocation_mode == "amount":
                    unfilled = max(0.0, (value or 0.0) * year_fraction - funded)
                    value = unfilled / year_fraction if year_fraction > 0 else 0.0
                refund_rules.append(replace(priority, max_annual_amount=cap, allocation_value=value))
            offset = len(state.allocation_flows)
            # Pub. 590-A worksheet 2-1 excludes conversion income.
            refund_magi = cash.tax_result.modified_agi - state.roth_conversions_this_year
            if tax.year == plan_data.start_year and 0 < year_fraction < 1 and not tax.ytd:
                refund_magi /= year_fraction
            refund_allocations = allocate_surplus(change, refund_rules, state, age=tax.age,
                filing_status=cash.contribution_filing_status, modified_agi=refund_magi,
                target_balance_fraction=year_fraction)
            for flow in state.allocation_flows[offset:]:
                existing = next((c for c in cash.cf_contributions if c.source == "priority"
                                 and c.priority_rank == flow.priority_rank), None)
                if existing is not None:
                    existing.amount += flow.amount
                    rule = next(p for p in refund_rules if p.priority_rank == flow.priority_rank)
                    if rule.allocation_mode == "remaining":
                        existing.requested_amount = (existing.requested_amount or 0) + (flow.requested_amount or 0)
                    if existing.amount > 0:
                        existing.funding_reasons = []
                else:
                    cash.cf_contributions.append(flow)
            for aid, amount in refund_allocations.items():
                if state.accounts[aid].account_type in _PRE_TAX_CONTRIBUTION_TYPES:
                    tax.waterfall_pretax_deductions += amount
                if state.accounts[aid].account_type in _RETIREMENT_CONTRIBUTION_TYPES:
                    tax.waterfall_retirement_deductions += amount
                    _record_waterfall_retirement_contribution(state, aid, amount)
                if state.accounts[aid].account_type == "traditional_ira":
                    tax.waterfall_ira_deductions += amount
            leftover_refund = change - sum(refund_allocations.values())
            if leftover_refund > .005 and cash.spend_leftover_mode:
                # A refund is spent only once, with the year's leftover.
                state.leftover_cash_held += leftover_refund
            elif leftover_refund > .005:
                sink_id = state.cash_account()
                state.deposit_to(sink_id, leftover_refund)
                cash.cf_contributions.append(NamedAmount(name=state.accounts[sink_id].name or "Unallocated cash",
                    amount=leftover_refund, account_id=sink_id, source="default_sink"))
        else:
            _fund(cash, -change)
    else:
        raise ValueError("Tax settlement did not converge; check tax and withholding assumptions")


def _conversion_checkpoint(cash: _YearCash) -> tuple:
    """A deep copy of everything a targeted Roth conversion trial changes."""
    tax = cash.tax
    return deepcopy((tax.state, cash.cf_drawdowns, cash.cf_contributions,
        tax.ordinary_drawdown_income, cash.early_withdrawal_penalty,
        tax.waterfall_pretax_deductions, tax.waterfall_retirement_deductions, tax.waterfall_ira_deductions,
        cash.net_cash, cash.settled_tax_cash, cash.tax_result, cash.actual_tax, cash.ytd_tax_paid,
        cash.ptc_reconciliation, tax.state_allocation_diagnostics, tax.local_tax_diagnostics,
        tax.hsa_exposure, cash.coverage_warnings))


def _restore_conversion_checkpoint(cash: _YearCash, checkpoint: tuple) -> None:
    """Return the year to a checkpoint taken by _conversion_checkpoint."""
    tax = cash.tax
    (restored_state, cash.cf_drawdowns, cash.cf_contributions,
        tax.ordinary_drawdown_income, cash.early_withdrawal_penalty,
        tax.waterfall_pretax_deductions, tax.waterfall_retirement_deductions, tax.waterfall_ira_deductions,
        cash.net_cash, cash.settled_tax_cash, cash.tax_result, cash.actual_tax, cash.ytd_tax_paid,
        cash.ptc_reconciliation, tax.state_allocation_diagnostics, tax.local_tax_diagnostics,
        tax.hsa_exposure, cash.coverage_warnings) = deepcopy(checkpoint)
    # Keep the object passed to execute_roth_conversions alive;
    # replacing it here would leave that caller holding a trial.
    tax.state.__dict__.update(restored_state.__dict__)


def _final_conversion_limit(
    cash: _YearCash, checkpoint: tuple, missing_rule_rate_years: dict[tuple, tuple[float, list[int]]],
    rule: PriorityData, upper: float,
) -> float:
    """The largest conversion ``rule`` allows, solved on the year's final settled tax.

    Every trial starts from ``checkpoint`` and runs the full settlement.
    """
    tax = cash.tax
    state = tax.state
    if tax.intl_year and rule.conversion_mode == "fill_bracket":
        return 0.0  # federal brackets do not apply abroad
    if rule.use_plan_tax_target:
        def fits_target(amount):
            try:
                _restore_conversion_checkpoint(cash, checkpoint)
                execute_roth_conversions([replace(
                    rule, conversion_mode="fixed", bracket_ceiling_rate=None, magi_cap=None,
                    use_plan_tax_target=False, max_annual_amount=amount)], state,
                    triggered_milestones=state.triggered_milestones)
                _settle_tax(cash)
                return (_target_fits(cash, cash.tax_result)
                        and state.unfunded_expenses <= checkpoint[0].unfunded_expenses + .005)
            finally:
                _restore_conversion_checkpoint(cash, checkpoint)
        return largest_fitting(fits_target, upper, tolerance=.001)
    if rule.conversion_mode != "fill_bracket" and rule.magi_cap is None:
        return upper
    bracket_top = None
    if rule.conversion_mode == "fill_bracket" and rule.bracket_ceiling_rate is not None:
        year_brackets = _conversion_context(tax, cash.tax_result).brackets
        # A rate the year's schedule lacks fills only brackets
        # taxed at or below it, like the plan's bracket target.
        bracket_top = bracket_target_top(year_brackets, rule.bracket_ceiling_rate)
        if bracket_top is None:
            bracket_top = float("inf")
        if not bracket_rate_in_schedule(year_brackets, rule.bracket_ceiling_rate):
            key = (rule.priority_rank, rule.source_account_id, rule.target_account_id,
                   rule.bracket_ceiling_rate)
            years = missing_rule_rate_years.setdefault(key, (rule.bracket_ceiling_rate, []))[1]
            if tax.year not in years:
                years.append(tax.year)

    def fits(amount):
        try:
            _restore_conversion_checkpoint(cash, checkpoint)
            trial_rule = replace(rule, conversion_mode="fixed", bracket_ceiling_rate=None,
                magi_cap=None, max_annual_amount=amount)
            execute_roth_conversions([trial_rule], state,
                triggered_milestones=state.triggered_milestones)
            # Even an intermediate rule must fit final tax/ACA
            # costs if every later rule is inactive or unfunded.
            _settle_tax(cash)
            final_magi = (_aca_magi(tax, cash.tax_result) if tax.healthcare_year is not None
                and tax.healthcare_year.aca_covered_adults > 0 else cash.tax_result.modified_agi)
            return ((rule.conversion_mode != "fill_bracket" or
                    (bracket_top is not None and cash.tax_result.taxable_income <= bracket_top))
                and (rule.magi_cap is None or final_magi <= rule.magi_cap * state.inflation_factor)
                and state.unfunded_expenses <= checkpoint[0].unfunded_expenses + .005)
        finally:
            _restore_conversion_checkpoint(cash, checkpoint)

    if fits(upper):
        return upper
    if not fits(0.0):
        # Existing mandatory income can exceed a cap already;
        # a conversion cannot remove that income.
        return 0.0
    lower = 0.0
    for _ in range(40):
        if upper - lower <= .001:
            break
        middle = (lower + upper) / 2
        if fits(middle):
            lower = middle
        else:
            upper = middle
    return lower


def _year_snapshot(
    cash: _YearCash, *, year_regime: Any, expenses: float, investment_growth: float, rmd_total: float,
    roth_rmd_income: float, rental_cash_income: float, nontaxable_income: float,
    employer_contribution_income: float, real_estate_purchase_cash: float,
    cf_income_sources: list[NamedAmount], cf_expenses: list[NamedAmount], cf_payroll_expenses: list[NamedAmount],
    payroll_deductions: float, payroll_retirement_by_account: Mapping[str, float],
    nj_employer_403b_by_account: Mapping[str, float], flex_spending_reduction: float,
    flex_spending_increase: float, leftover_spent: float, newly_triggered: list[str],
    ss_earnings_test_withheld: float, ss_withheld_by_earner: Mapping[str, float],
    tax_target_room: Any, tax_target_blended: float,
    bond_allocation_by_account: Any, strategy_spent: float | None, planned_for_year: Any,
    year_inflation_factor: float, liquid_excluded_ids: frozenset[str], coverage_warnings: set[str],
    healthcare_warning_set: list[str],
) -> tuple[YearSnapshot, Any]:
    """Step 12: close the year's tax and build its snapshot.

    Finishes the Roth ledger, books the estimated tax penalty, the final
    premium tax credit and any lagged settlement, commits the state-taxed
    basis and suspended passive losses, and records the year's warnings.
    Returns the snapshot and the estimated tax prior year for next year.
    """
    tax = cash.tax
    state, year, ytd = tax.state, tax.year, tax.ytd
    gross_income, ss_income = tax.gross_income, tax.ss_income
    healthcare_year = tax.healthcare_year
    tax_withheld = cash.tax_withheld
    estimated_tax_plan = cash.estimated_tax_plan
    estimated_tax_prior = cash.estimated_tax_prior
    roth_income, roth_penalty = state.roth_ledger.totals() if state.roth_ledger else (0.0, 0.0)
    roth_penalty_refund = state.roth_penalty_charged - roth_penalty
    cash.early_withdrawal_penalty -= roth_penalty_refund
    if state.roth_ledger:
        state.roth_ledger.finish(state.accounts)
    total_taxes = cash.actual_tax + cash.early_withdrawal_penalty
    if estimated_tax_plan is not None:
        # Same final tax and payments the settlement converged on.
        estimated_year = _estimated_tax_year(cash, cash.tax_result, cash.ptc_reconciliation)
        estimated_tax_prior = estimated_year.next_prior_year()
        total_taxes += estimated_year.underpayment_penalty
    tax_withheld += state.drawdown_tax_withheld_this_year
    final_tax_delta = cash.ytd_tax_paid + tax_withheld - cash.actual_tax + cash.ptc_reconciliation + roth_penalty_refund
    if healthcare_year is not None and healthcare_year.aca_covered_adults > 0:
        _final_magi = _aca_magi(tax, cash.tax_result)
        _final = calculate_premium_tax_credit(
            _final_magi, healthcare_year.aca_household_size, healthcare_year.aca_benchmark_premium,
            healthcare_year.aca_gross_premium, covered_adults=healthcare_year.aca_covered_adults,
            state_group=tax.hc_settings.aca_state_group, inflation_factor=state.coverage_inflation_factor,
            coverage_periods=healthcare_year.aca_coverage_periods, filing_status=tax.filing_status,
        )
        healthcare_year.aca_magi = _final_magi
        healthcare_year.aca_fpl_ratio = _final.fpl_ratio
        healthcare_year.aca_applicable_percentage = _final.applicable_percentage
        healthcare_year.aca_credit = _final.credit
        healthcare_year.aca_eligible = _final.eligible
        healthcare_year.aca_reason = _final.reason
        healthcare_year.aca_reconciliation = cash.ptc_reconciliation
        healthcare_year.aca_net_premium = healthcare_year.aca_gross_premium - _final.credit
        healthcare_year.total = medical_total(healthcare_year)
        if _final.reason and "below 100%" in _final.reason:
            _w = "Household income fell below 100% of the poverty line in at least one ACA year; Medicaid is not modeled, so the full premium is charged."
            if _w not in healthcare_warning_set:
                healthcare_warning_set.append(_w)
    if cash.settlement_lag_years > 0:
        settlement_year = year + cash.settlement_lag_years
        state.pending_tax_settlements[settlement_year] = (
            state.pending_tax_settlements.get(settlement_year, 0.0)
            + final_tax_delta
        )
        if estimated_tax_plan is not None:
            state.pending_tax_settlements[settlement_year] += estimated_year.carried_adjustment()
    real_assets_value = state.total_real_asset_value()
    liabilities_balance = state.total_liability_balance()
    liquid_assets = sum(a.balance for a in state.accounts.values())
    tax_balance = -sum(state.pending_tax_settlements.values())
    net_worth = liquid_assets + real_assets_value - liabilities_balance - tax_balance - state.unfunded_expenses

    taxable_and_spendable_income = (
        gross_income + ss_income + rmd_total + tax.ordinary_drawdown_income + roth_income - roth_rmd_income
        + state.hsa_taxable_distributions_this_year + rental_cash_income + nontaxable_income
    )
    total_gross_income = (
        taxable_and_spendable_income
        + employer_contribution_income
        + state.capital_gains_this_year + state.qualified_dividends_this_year
        # Reinvested ordinary dividends and bond interest, municipal included.
        + state.ordinary_dividends_this_year + state.bond_interest_this_year
    )
    calendar_year_gross_income = (
        total_gross_income
        + float(ytd.get("gross_income", 0.0))
        + float(ytd.get("social_security_income", 0.0))
        + float(ytd.get("capital_gains", 0.0))
        + float(ytd.get("qualified_dividends", 0.0))
    )
    # Solver iterations are bookkeeping, not distinct user cash flows.
    withdrawals_by_account: dict[str, NamedAmount] = {}
    for flow in cash.cf_drawdowns:
        if flow.account_id in withdrawals_by_account:
            withdrawals_by_account[flow.account_id].amount += flow.amount
        else:
            withdrawals_by_account[flow.account_id] = flow
    cash.cf_drawdowns = [flow for flow in withdrawals_by_account.values() if flow.amount >= .005]
    cash_flow = CashFlowBreakdown(
        income_sources=cf_income_sources,
        # Taxable account distributions and realized gains are already
        # represented by drawdowns. They are not a second cash receipt.
        gross_income=sum(source.amount for source in cf_income_sources),
        tax_withheld=tax_withheld,
        payroll_deductions=payroll_deductions,
        net_pay=gross_income + ss_income + nontaxable_income + rmd_total + rental_cash_income - tax_withheld - payroll_deductions,
        tax_delta=final_tax_delta,
        early_withdrawal_penalty=cash.early_withdrawal_penalty,
        expenses=cf_expenses,
        payroll_expenses=cf_payroll_expenses,
        contributions=cash.cf_contributions,
        transfers=list(state.transfers),
        drawdowns=cash.cf_drawdowns,
    )
    if estimated_tax_plan is not None:
        cash_flow.tax_delta += estimated_year.estimated_payments
        cash_flow.estimated_tax_payments = estimated_year.estimated_payments
        cash_flow.required_annual_payment = estimated_year.required_annual_payment
        cash_flow.underpayment_penalty = estimated_year.underpayment_penalty

    coverage_warnings.update(
        f"{year}: {message}" for message in tax.state_allocation_diagnostics
    )
    # Jurisdiction limitations repeat every year; report them once.
    coverage_warnings.update(tax.local_tax_diagnostics)
    coverage_warnings.update(cash.tax_result.tax_adjustment_diagnostics)
    if tax.ca_move_year and tax.tax_settings.get("mode") != "flat":
        coverage_warnings.add(
            f"{year}: California residency and wage overlap use month precision; "
            "a move takes effect at the start of its modeled trigger month."
        )
    # Close the year's state-taxed contribution basis: the final tax
    # computation's recovery, then this year's add-back by account.
    commit_state_taxed_basis(
        state, tax.resolved_state_code, tax.basis_recovery,
        _state_taxed_contributions_by_account(
            tax.resolved_state_code, state, payroll_retirement_by_account,
            nj_employer_403b_by_account, cash.tax_result.ira_nondeductible_contributions),
    )
    # Close the year's passive losses: the final tax computation's
    # suspended amounts carry to next year (IRC 469(b)).
    if tax.passive_result is not None:
        state.suspended_passive_losses = dict(tax.passive_result.suspended)
    coverage_warnings.update(state.real_estate_warnings)
    state.real_estate_warnings.clear()
    snapshot = YearSnapshot(
        year=year,
        age=tax.age,
        gross_income=total_gross_income,
        calendar_year_gross_income=calendar_year_gross_income,
        taxes=total_taxes,
        tax_balance=tax_balance,
        unfunded_expenses=state.unfunded_expenses,
        capital_loss_carryforward=state.capital_loss_carryforward,
        expenses=expenses,
        net_cash_flow=cash.net_cash,
        accounts=state.snapshot(),
        real_assets_value=real_assets_value,
        liabilities_balance=liabilities_balance,
        net_worth=net_worth,
        # The tax lines are full-year when earlier history is entered or
        # imputed. Include that history in the denominator as well.
        # Taxable Roth conversions (and backdoor pro-rata amounts) are
        # income the numerator taxes, though not spendable gross income.
        effective_rate=(total_taxes / (calendar_year_gross_income + state.roth_conversions_this_year)
                        if calendar_year_gross_income + state.roth_conversions_this_year > 0 else 0.0),
        marginal_rate=cash.tax_result.marginal_rate,
        deduction_used=cash.tax_result.deduction_used,
        deduction_amount=cash.tax_result.deduction_amount,
        standard_deduction=cash.tax_result.standard_deduction,
        flex_spending_reduction=flex_spending_reduction,
        flex_spending_increase=flex_spending_increase,
        leftover_spending=leftover_spent,
        investment_growth=investment_growth,
        investment_fees=state.investment_fees_this_year,
        milestones_triggered=list(newly_triggered),
        transfers=list(state.transfers),
        cash_flow=cash_flow,
        federal_tax=cash.tax_result.federal,
        state_tax=cash.tax_result.state,
        local_tax=cash.tax_result.local,
        state_retirement_exclusion=cash.tax_result.state_retirement_exclusion,
        ss_earnings_test_withheld=ss_earnings_test_withheld,
        ss_earnings_test_withheld_by_earner=dict(ss_withheld_by_earner),
        state_social_security_subtraction=cash.tax_result.state_social_security_subtraction,
        state_capital_gains_excise=cash.tax_result.state_capital_gains_excise,
        tax_adjustment_deductions=cash.tax_result.tax_adjustment_deductions,
        tax_adjustment_credits=cash.tax_result.tax_adjustment_credits,
        tax_adjustment_surcharge=cash.tax_result.tax_adjustment_surcharge,
        rental_income=rental_cash_income,
        rental_expenses=sum(activity.expenses for activity in tax.rental_year.values()),
        rental_depreciation=sum(activity.depreciation for activity in tax.rental_year.values()),
        rental_taxable_income=tax.passive_result.allowed if tax.passive_result is not None else 0.0,
        suspended_passive_losses=sum(state.suspended_passive_losses.values()),
        unrecaptured_section_1250_gain=state.unrecaptured_1250_this_year,
        real_estate_purchases=real_estate_purchase_cash,
        rule_funding_shortfall=state.rule_funding_shortfall,
        tax_country=tax.year_country,
        intl_tax_lines=[dict(line) for line in year_regime.lines] if year_regime is not None else [],
        national_income_tax=year_regime.national_income_tax if year_regime is not None else 0.0,
        regional_income_tax=year_regime.regional_income_tax if year_regime is not None else 0.0,
        social_contributions=year_regime.social_contributions if year_regime is not None else 0.0,
        wealth_tax=year_regime.wealth_tax if year_regime is not None else 0.0,
        transaction_tax=year_regime.transaction_tax if year_regime is not None else 0.0,
        benefit_recovery_tax=year_regime.benefit_recovery_tax if year_regime is not None else 0.0,
        capital_gains_tax=cash.tax_result.capital_gains_tax,
        fica_tax=cash.tax_result.fica_tax,
        niit_tax=cash.tax_result.niit,
        # The AMT owed, which federal income tax already includes; the tentative minimum tax
        # is a comparison figure, not a tax.
        amt_tax=cash.tax_result.amt_excess,
        early_withdrawal_penalty=cash.early_withdrawal_penalty,
        healthcare=healthcare_year,
        harvested_gains=state.harvested_gains_this_year,
        debt_forgiven=state.debt_forgiven_this_year,
        debt_forgiveness_taxable=state.cod_income_this_year,
        tax_target_room=tax_target_room,
        tax_target_blended_withdrawals=tax_target_blended,
        bond_allocation_by_account=bond_allocation_by_account,
        strategy_spending=strategy_spent,
        planned_expenses=planned_for_year,
        inflation_factor=year_inflation_factor,
        # The tax lines above are the full calendar year. This amount
        # subtracts actual or imputed pre-start payments, leaving the
        # liability/refund attributable to the period after plan start.
        post_start_taxes=(total_taxes - cash.ytd_tax_paid) if 0.0 < cash.year_fraction < 1.0 else None,
        warnings=["ytd_imputed_pro_rata"] if tax.ytd_imputed else [],
        locked_account_ids=state.illiquid_account_ids(),
        liquid_excluded_account_ids=liquid_excluded_ids,
    )
    return snapshot, estimated_tax_prior


def _record_year_history(
    cash: _YearCash, snapshot: YearSnapshot, *, aca_magi_history: dict[int, float], rental_cash_income: float,
) -> dict[str, float]:
    """Step 12, after the snapshot: the history later years read.

    Records MAGI for IRMAA and the premium tax credit, the filing status,
    and the metrics condition milestones test. Returns the year's wages by
    owner for next year's Roth catch-up test.
    """
    tax = cash.tax
    state, plan_data, year, ytd = tax.state, tax.plan_data, tax.year, tax.ytd
    year_fraction = cash.year_fraction
    # Prior-year wages for next year's Roth catch-up test. A partial
    # opening year fills the months before the start with entered
    # year-to-date wages, or else annualizes like its own test.
    if 0 < year_fraction < 1:
        opening_ytd_w2 = ytd.get("w2_income_by_owner", {})
        prior_w2_by_owner = {owner: amount if owner in opening_ytd_w2 else amount / year_fraction
                             for owner, amount in tax.w2_by_owner.items()}
    else:
        prior_w2_by_owner = tax.w2_by_owner
    # IRMAA's lookback MAGI includes tax-exempt interest (42 U.S.C. 1395r(i)(4)(A)).
    state.magi_history[year] = cash.tax_result.modified_agi + cash.tax_result.tax_exempt_interest
    aca_magi_history[year] = _aca_magi(tax, cash.tax_result)
    state.filing_status_history[year] = state.current_filing_status or plan_data.filing_status
    # Expense-multiple milestones need the full annual spending rate, not
    # just the cash spent over a partial opening year. Use the completed
    # total so payroll expenses, specific funding, debt, and asset costs
    # all count, while leaving the snapshot's actual cash flows prorated.
    # A zero-duration year cannot establish an annual expense basis.
    if year_fraction > 0 and any(ms.trigger_type == "conditions" for ms in plan_data.milestones):
        passive_streams = sum(tax.income_by_id.get(inc.id, 0.0) for inc in plan_data.income_streams
                              if not inc.is_social_security and not inc.is_earned_income and not inc.is_self_employed
                              and inc.tax_category in {None, "investment", "qualified_pension", "nonqualified_annuity"})
        passive = (passive_streams + tax.ss_income + tax.taxable_cash_interest + rental_cash_income
                   + state.capital_gains_this_year
                   + state.qualified_dividends_this_year + state.ordinary_dividends_this_year
                   + state.bond_interest_this_year)
        contributions = sum(flow.amount for flow in cash.cf_contributions
                            if flow.source not in {"reinvestment", "transfer"})
        state.milestone_metric_history.append({
            "annual_spending": snapshot.expenses / year_fraction,
            "passive_income": passive / year_fraction,
            "savings_rate": contributions / snapshot.gross_income if snapshot.gross_income > 0 else 0.0,
            "net_worth": state.total_net_worth(),
            "liquid_net_worth": state.liquid_account_balance() - state.total_liability_balance(),
            "total_debt": state.total_liability_balance(),
            **{f"account_balance:{aid}": account.balance for aid, account in state.accounts.items()},
        })
        state.milestone_metric_history = state.milestone_metric_history[-10:]
    state.last_year_expenses = (
        snapshot.expenses / year_fraction if year_fraction > 0 else None
    )
    return prior_w2_by_owner


def _plan_tax_target_year(
    tax: _YearTax, plan_tax_target: TaxTargetSettings | None, *, target_aca_active: bool,
    override_returns: dict[int, tuple] | None, curves, missing_target_rate_years: list[int],
) -> YearTaxTarget | None:
    """Step 9c: the plan tax target's limits for this year, measured on the actual tax.

    None without a target, or in a year another country taxes when the
    target is defined only by US rules.
    """
    state, year = tax.state, tax.year
    if plan_tax_target is None or (tax.intl_year and plan_tax_target.kind in intl_regime.US_ONLY_TARGET_KINDS):
        return None
    flat_tax = tax.tax_settings.get("mode") == "flat"
    # IRMAA ranges for the premium year this income sets (t + 2), indexed
    # the way the premium calculation will index them then, assuming
    # this year's inflation rate continues.
    if override_returns is not None and year in override_returns:
        target_inflation_rate = override_returns[year][2]
    else:
        target_inflation_rate = resolve_assumption(
            curves, "inflation", year, tax.plan_data.birth_year, tax.default_inflation)
    irmaa_factor = tax.federal_inflation_factor
    for step_year in range(year, year + IRMAA_LOOKBACK_YEARS):
        if step_year >= 2026:
            irmaa_factor *= 1.0 + target_inflation_rate
    target_brackets = federal_ordinary_brackets(tax.annual_tax_settings, tax.filing_status, year,
                                                tax.federal_inflation_factor, state.inflation_factor)
    if (plan_tax_target.kind == "federal_bracket" and plan_tax_target.bracket_rate is not None
            and not flat_tax and not bracket_rate_in_schedule(target_brackets, plan_tax_target.bracket_rate)):
        missing_target_rate_years.append(year)
    return year_tax_target(
        plan_tax_target, filing_status=tax.filing_status, year=year, flat_tax=flat_tax,
        federal_brackets=target_brackets,
        inflation_factor=state.inflation_factor,
        irmaa_inflation_factor=irmaa_factor,
        irmaa_applies=any(owner_age + IRMAA_LOOKBACK_YEARS >= MEDICARE_AGE
                          for owner_age in state.owner_ages.values()),
        mfs_lived_apart_all_year=bool((tax.annual_tax_settings or {}).get("mfs_lived_apart_all_year", False)),
        aca_poverty_line=(poverty_line(tax.healthcare_year.aca_household_size, tax.hc_settings.aca_state_group,
                                       state.coverage_inflation_factor) if target_aca_active else None),
    )


def _conversions_harvests_and_transfers(
    cash: _YearCash, conversion_rules: list[PriorityData], *, defer_conversions: bool,
    milestone_map: Mapping[str, Any], newly_triggered: list[str], annual_account_rates: Mapping[str, Any],
    annual_income_composition: Mapping[str, Any],
) -> None:
    """Step 9c: Roth conversions, gain harvests and account-to-account transfers.

    Targeted conversions wait for the year's settled tax (step 10c).
    Transfer withdrawals add to the year's drawdown income and penalties.
    """
    tax = cash.tax
    state, plan_data = tax.state, tax.plan_data
    # Targeted conversions depend on spending sales and the taxes those
    # conversions create. Keep uncapped fixed-only plans' existing timing.
    validate_roth_conversion_rules(conversion_rules, state.accounts)
    if not defer_conversions:
        execute_roth_conversions(conversion_rules, state,
            tax_context=_conversion_context(tax, cash.tax_result), triggered_milestones=state.triggered_milestones)

    execute_gain_harvests(
        plan_data.priorities, state,
        tax_context=_conversion_context(tax, cash.tax_result),
        triggered_milestones=state.triggered_milestones,
        amount_limit=partial(_final_harvest_limit, cash),
    )
    execute_transfers(
        plan_data.priorities, state, age=tax.age, birth_month=plan_data.birth_month,
        withholding_rates=cash.withholding_rates, sepp_account_ids=cash.sepp_account_ids,
        active_months=partial(_transfer_months, state, plan_data, tax.year, cash.year_fraction, milestone_map,
                              newly_triggered),
        month_growth=partial(_transfer_month_growth, state, annual_account_rates, annual_income_composition))
    tax.ordinary_drawdown_income += state.transfer_income_this_year
    cash.early_withdrawal_penalty += state.transfer_penalty_this_year


def _spend_strategy_withdrawal(
    cash: _YearCash, *, strategy_withdrawal_target: float, strategy_planned_part: float | None,
    pending_strategy_flex_delta: float, spendable_rmd: float, standard_expenses: float,
    original_expenses: float, cf_expenses: list[NamedAmount],
) -> tuple[float, float, float]:
    """Step 9c: spend the withdrawal strategy's target once net cash is known.

    Returns (strategy spending, flexed spending, planned spending).
    """
    # Spend the strategy's portfolio withdrawal plus the year's net
    # income, so nothing is saved and the portfolio's net outflow is
    # the target. Required distributions (RMD, SEPP) count toward the
    # withdrawal; any excess over the target is reinvested. Fixed
    # costs beyond income can still draw more than the target. Tax on
    # the withdrawal is settled below and funded like any tax bill.
    forced_withdrawals = spendable_rmd + cash.tax.sepp_income
    if strategy_planned_part is None:
        strategy_part = max(0.0, cash.net_cash - forced_withdrawals + strategy_withdrawal_target)
    else:
        # Start year: the year's income mostly arrived before the
        # start (often salary ending at the start milestone), and the
        # plan saves that surplus. Only the prorated withdrawal is
        # spent on top of the plan's own spending for those months.
        strategy_part = strategy_withdrawal_target
    strategy_spent = strategy_part + (strategy_planned_part or 0.0)
    cash.net_cash -= strategy_part
    standard_expenses += strategy_part
    original_expenses += strategy_part - pending_strategy_flex_delta
    if strategy_part > 0:
        cf_expenses.insert(0, NamedAmount(name="Strategy spending", amount=strategy_part, category="discretionary"))
    return strategy_spent, standard_expenses, original_expenses


def _waterfall_or_drawdown(
    cash: _YearCash, *, pre_waterfall_contributions: list[NamedAmount], specific_drawdowns: Mapping[str, float],
    qcd_withdrawals: Mapping[str, float], taxable_dividends: float, taxable_bond_interest: float,
    blend_drawdown: bool,
) -> float:
    """Step 10: invest the year's surplus through the waterfall, or draw down a deficit.

    A deficit first sells shares reserved for gifts, then optionally fills
    the plan tax target's room, then follows the withdrawal order.
    Withdraw-if-short rules and the opt-in reserve sweep run after. Returns the
    withdrawals blended to the tax target.
    """
    tax = cash.tax
    state, plan_data, year, age, ytd = tax.state, tax.plan_data, tax.year, tax.age, tax.ytd
    filing_status, annual_tax_settings = tax.filing_status, tax.annual_tax_settings
    year_fraction = cash.year_fraction
    tax_target_blended = 0.0
    cash.cf_contributions = list(pre_waterfall_contributions)
    reinvested_dividends = taxable_dividends - state.paid_out_dividends_this_year
    reinvested_bond_interest = taxable_bond_interest - state.paid_out_bond_interest_this_year
    # Rounding dust from fully paid-out income is not a reinvestment.
    if reinvested_dividends > (0.005 if state.paid_out_dividends_this_year else 0.0):
        cash.cf_contributions.append(NamedAmount(name="Reinvested dividends", amount=reinvested_dividends,
                                                source="reinvestment"))
    if reinvested_bond_interest > (0.005 if state.paid_out_bond_interest_this_year else 0.0):
        cash.cf_contributions.append(NamedAmount(name="Reinvested bond interest", amount=reinvested_bond_interest,
                                                source="reinvestment"))
    cash.cf_drawdowns = [_withdrawal_flow(state, aid, value)
                         for aid, value in specific_drawdowns.items()]
    # Gifts have already left these accounts in step 5b. Report their
    # funding alongside their expense without withdrawing a second time.
    cash.cf_drawdowns.extend(_withdrawal_flow(state, aid, value)
                             for aid, value in tax.charitable_result.account_withdrawals.items())
    cash.cf_drawdowns.extend(_withdrawal_flow(state, aid, value, ordinary=False) for aid, value in qcd_withdrawals.items())
    roth_modified_agi = cash.tax_result.agi + max(0.0, state.capital_gains_this_year) + state.qualified_dividends_this_year
    # IRC 408A(c)(3)(D): a separate filer who lived apart from the spouse
    # all year is treated as unmarried for the Roth IRA income limit.
    contribution_filing_status = (
        "single" if filing_status == "married_filing_separately"
        and (annual_tax_settings or {}).get("mfs_lived_apart_all_year") else filing_status)
    if year == plan_data.start_year and 0 < year_fraction < 1 and not ytd:
        # A midyear plan start changes simulated cash flow, not the
        # taxpayer's full-calendar-year IRA eligibility.  Annualize
        # the captured portion to estimate full-year modified AGI.
        roth_modified_agi /= year_fraction
    cash.contribution_filing_status = contribution_filing_status

    # Withdraw-if-short rules run first; what the surplus cannot cover is
    # queued here and drawn after the year's spending deficit.
    shortfall_pending: list[ShortfallRequest] = []
    alloc_result = allocate_surplus(
        cash.net_cash,
        plan_data.priorities,
        state,
        age=age,
        filing_status=contribution_filing_status,
        modified_agi=roth_modified_agi,
        target_balance_fraction=year_fraction,
        shortfall_pending=shortfall_pending,
    )
    cash.cf_contributions.extend(state.allocation_flows)
    if cash.net_cash > 0:
        _record_allocations(cash, alloc_result)

        # Bank any unallocated surplus in a default cash sink account.
        # After all waterfall priorities are filled (user caps + IRS
        # limits), leftover cash is deposited into the first cash-like
        # account found in insertion order: checking → savings →
        # taxable_brokerage.  This prevents net-worth leakage for
        # plans with capped or empty priority lists.
        leftover = cash.net_cash - sum(alloc_result.values()) - sum(state.debt_prepayments.values())
        if leftover > 0 and cash.spend_leftover_mode:
            # Held, not deposited: tax settlement below can still raise a
            # bill or a refund. What is left is spent or saved at the end.
            state.leftover_cash_held += leftover
        elif leftover > 0:
            sink_id = state.cash_account()
            state.deposit_to(sink_id, leftover)
            cash.contributions_for_growth[sink_id] = cash.contributions_for_growth.get(sink_id, 0.0) + leftover
            sink_name = state.accounts[sink_id].name or "Unallocated cash"
            cash.cf_contributions.append(NamedAmount(
                name=sink_name, amount=leftover, account_id=sink_id,
                account_name=sink_name, source="default_sink",
            ))
    elif cash.net_cash < 0:
        # Sell the shares reserved for gifts before the withdrawal order,
        # as the gifts were funded before this change.
        gift_order = [DrawdownEntryData(-1, aid) for aid in tax.charitable_result.deferred_sales]
        gift_sale = min(abs(cash.net_cash), sum(min(amount, max(0.0, state.get_balance(aid)))
                                                for aid, amount in tax.charitable_result.deferred_sales.items()))
        gift_result, _ = execute_drawdown(gift_sale, gift_order, state, age=age) if gift_sale > 0 else ({}, 0.0)
        # TODO: Spouse-specific drawdown order. When spouse retires first, may want
        # different drawdown priority (e.g., draw from spouse's accounts before self).
        # Consider adding owner field to DrawdownEntryData for this.
        shortfall_need = abs(cash.net_cash) - gift_sale
        blended_result: dict[str, float] = dict(gift_result)
        if blend_drawdown and cash.year_target is not None and shortfall_need > .01:
            blended, blended_penalty, shortfall_need = _blend_to_tax_target(cash, shortfall_need)
            for acct_id, amt in blended.items():
                blended_result[acct_id] = blended_result.get(acct_id, 0.0) + amt
            cash.early_withdrawal_penalty += blended_penalty
            tax_target_blended = sum(blended.values())
        if shortfall_need <= .01:
            dd_result = {}
        else:
            dd_result, dd_penalty = execute_drawdown(
                shortfall_need, _shortfall_order(plan_data, state), state,
                age=age, sepp_account_ids=cash.sepp_account_ids,
                birth_month=plan_data.birth_month,
                withholding_rates=cash.withholding_rates,
            )
            tax.ordinary_drawdown_income += _ordinary_income_from_drawdowns(dd_result, state)
            cash.early_withdrawal_penalty += dd_penalty
        for acct_id, amt in dd_result.items():
            blended_result[acct_id] = blended_result.get(acct_id, 0.0) + amt
        dd_result = blended_result
        for acct_id, amt in dd_result.items():
            cash.cf_drawdowns.append(_withdrawal_flow(state, acct_id, amt))

    if shortfall_pending:
        _record_allocations(cash, fund_rule_shortfalls(
            shortfall_pending, state, partial(_draw_for_shortfall, cash),
            current_magi=None if tax.intl_year else partial(_shortfall_magi, cash),
            keep_cash=partial(_keep_shortfall_cash, cash),
        ))

    # Opt-in: cash above the reserve funds unmet rules.
    swept_by_rank = _sweep_excess_reserve_cash(
        plan_data, state, cash.cf_contributions, year_fraction,
        partial(allocate_surplus, state=state, age=age, filing_status=contribution_filing_status,
                modified_agi=roth_modified_agi, target_balance_fraction=year_fraction),
    ) if plan_data.cash_reserve is not None and plan_data.cash_reserve.sweep_excess else {}
    cash.swept_by_rank = swept_by_rank
    if swept_by_rank:
        # Year-end moves: deductible like any contribution, without a
        # year of growth.
        _record_allocations(cash, state.swept_reserve_cash, grows_all_year=False)
    return tax_target_blended


def _recover_unfunded_expenses(cash: _YearCash) -> None:
    """Step 10b: recover the original unpaid cash requirement before clearing failure.

    Past failures remain failures even if a later year restores liquidity.
    """
    state, year = cash.tax.state, cash.tax.year
    recoverable_unfunded = max(
        0.0,
        state.unfunded_expenses - state.restricted_unfunded_expenses,
    )
    if recoverable_unfunded > .01:
        old_failure = state.failure_year
        state.unfunded_expenses -= recoverable_unfunded
        if old_failure == year:
            state.failure_year = None
        _fund(cash, recoverable_unfunded)
        if old_failure is not None and old_failure < year:
            state.failure_year = old_failure


def _settle_year_tax(
    cash: _YearCash, conversion_rules: list[PriorityData], *, defer_conversions: bool,
    tax_settlement_cash: float, estimated_tax_cash: float,
    missing_rule_rate_years: dict[tuple, tuple[float, list[int]]],
) -> None:
    """Step 10c: settle the year's tax, then run targeted Roth conversions in rank order.

    Each targeted conversion is sized on the tax settled after it, from a
    checkpoint of the year that every trial restores.
    """
    tax = cash.tax
    cash.settled_tax_cash = tax_settlement_cash if cash.settlement_lag_years == 0 else 0.0
    if cash.estimated_tax_plan is not None:
        cash.settled_tax_cash += estimated_tax_cash
    cash.ptc_reconciliation = 0.0
    _settle_tax(cash, finalize_refunds=not defer_conversions)
    if defer_conversions:
        ranked_conversions = sorted(conversion_rules, key=lambda p: p.priority_rank)
        for rule_index, conversion_rule in enumerate(ranked_conversions):
            finalize_refunds = rule_index == len(ranked_conversions) - 1
            # Each trial starts from the same settled balances, basis, Roth
            # ledger and cash flows. Trials run the ordinary settlement
            # path and final ACA/refund effects. Actual cash reconciliation
            # waits until the final ranked rule has executed.
            checkpoint = _conversion_checkpoint(cash)
            execute_roth_conversions([conversion_rule], tax.state,
                tax_context=_conversion_context(tax, cash.tax_result), triggered_milestones=tax.state.triggered_milestones,
                amount_limit=partial(_final_conversion_limit, cash, checkpoint, missing_rule_rate_years))
            _settle_tax(cash, finalize_refunds=finalize_refunds)


class _YearReturn(NamedTuple):
    """Step 6: the return the year's income tax is figured on."""

    filing_status: str
    annual_tax_settings: Mapping[str, Any] | None
    year_adjustments: Any
    salt_passes: int
    salt_tolerance: float


def _year_return(
    state: SimState, plan_data: PlanData, year: int, *, start_year: int, tax_settings: Mapping[str, Any],
    base_tax_settings: Mapping[str, Any], tax_spouse_age: int | None,
) -> _YearReturn:
    """Step 6: the year's filing status, tax settings, adjustments and SALT iteration bounds."""
    filing_status = state.current_filing_status or plan_data.filing_status
    annual_tax_settings = plan_data.tax_settings if tax_settings is base_tax_settings else tax_settings
    # The user's tax adjustments for this return; a person's own items end
    # after the return for the year of their death.
    owners_on_return = {"self"} if not (lifecycle.enabled(plan_data) and state.primary_deceased) else set()
    if tax_spouse_age is not None or (lifecycle.enabled(plan_data) and state.primary_deceased):
        owners_on_return.add("spouse")
    year_adjustments = resolve_year_adjustments(
        tax_settings.get("adjustments"), year=year, plan_start_year=start_year,
        milestone_years=state.triggered_milestone_years, inflation_factor=state.inflation_factor,
        owners_on_return=frozenset(owners_on_return),
    )
    # Opt-in statutory state deduction rules solve the federal SALT and
    # state federal-income-tax feedback in the same bounded iteration.
    salt_passes, salt_tolerance = (5, 1.0) if tax_settings.get("state_deduction_rules") else (3, .001)
    oh_owners = tax_settings.get("oh_exemption_eligible_owners")
    if oh_owners is not None:
        # Owner assertions refer to original people, not inherited
        # account ownership. The death-year joint return retains them;
        # next January remove the deceased and identify the surviving
        # spouse as the taxpayer for an unmarried return.
        active_owners = set(oh_owners)
        if state.partner_deceased and year > (state.partner_death_year or year):
            active_owners.discard("spouse")
        if lifecycle.enabled(plan_data) and state.primary_deceased:
            active_owners.discard("self")
            if "spouse" in active_owners:
                active_owners = {"self"}
        annual_tax_settings = {**tax_settings,
                               "oh_exemption_eligible_owners": sorted(active_owners)}
    return _YearReturn(filing_status, annual_tax_settings, year_adjustments, salt_passes, salt_tolerance)


def _year_tax_jurisdictions(
    state: SimState, plan_data: PlanData, year: int, *, start_year: int, tax_settings: Mapping[str, Any],
    residency_spans: list, earned_income: float, coverage_warnings: set[str],
) -> tuple[str | None, Any]:
    """Step 6: the state and local income tax that apply to the year.

    Returns (state code, local tax). At plan start, records opening
    state-taxed contribution basis under the state of residence.
    """
    resolved_state_code = resolve_state_for_year(
        year, state.triggered_milestones, plan_data,
    )
    if year == start_year and resolved_state_code:
        # Opening state-taxed contributions were taxed by the state of
        # residence at plan start.
        for account_id, account in plan_data.accounts.items():
            if (account.state_taxed_basis and account.state_taxed_basis > 0
                    and account.account_type in _RETIREMENT_CONTRIBUTION_TYPES
                    and account_id in state.accounts):
                state.state_taxed_basis.setdefault(account_id, {})[resolved_state_code] = float(
                    account.state_taxed_basis)
    resolved_local_tax = resolve_local_tax_for_year(
        year, state.triggered_milestones, plan_data,
    )
    if tax_settings.get("mode") == "flat":
        if resolved_local_tax:
            coverage_warnings.add("Local income tax is not added in flat tax mode; the blended rate is the complete tax assumption.")
    else:
        if len({tuple(sorted((span.local_tax or {}).items())) for span in residency_spans}) > 1:
            coverage_warnings.add(
                f"{year}: Local income tax uses the residence after this year's move "
                "for the whole year; part-year local tax is not modeled."
            )
        # Pennsylvania localities tax earned income only.
        if (resolved_local_tax is None and resolved_state_code in _LOCAL_TAX_STATE_PROMPTS
                and (resolved_state_code != "PA" or earned_income > 0)):
            coverage_warnings.add(_LOCAL_TAX_STATE_PROMPTS[resolved_state_code])
    return resolved_state_code, resolved_local_tax


def _state_payroll_programs(
    state: SimState, year: int, year_fraction: float, *, start_year: int, tax_settings: Mapping[str, Any],
    intl_year: bool, ytd_imputed: bool, federal_inflation_factor: float, payroll_coverage: list,
    known_payroll: Mapping[str, Any], payroll_contributions: list, state_wages_by_owner: dict[str, float],
    state_ytd_wages: Mapping[str, float], covered_income_by_id: Mapping[str, float],
    income_by_id: Mapping[str, float], w2_by_owner: Mapping[str, float], resolved_state_code: str | None,
    coverage_warnings: set[str],
) -> tuple[dict[str, float], dict[str, float], float]:
    """Step 6: state payroll insurance programs (CA SDI, WA Paid Leave, WA Cares).

    Returns (obligations, payments already made, the employee share that
    is federal SALT).
    """
    # EDD DE 231TP: HSA deposits, including employer deposits and
    # section 125 reductions, remain CA SDI wages. Salary already includes
    # employee reductions. Opening W2 wages must be reported taxable wages;
    # add only projected employer HSA deposits, never opening deposits again.
    state_wage_history = tax_settings.get("state_payroll_wages_year_to_date", {}) if year == start_year else {}
    for owner, amount in state_wage_history.items():
        state_wages_by_owner[owner] = max(0.0, state_wages_by_owner.get(owner, 0.0)
            - state_ytd_wages.get(owner, 0.0) + amount)
    if any(amount > 0 and owner not in state_wage_history for owner, amount in state_ytd_wages.items()):
        coverage_warnings.add("Earlier state-program wages are unspecified; federal W2 history is used. Enter state payroll wage history if employer benefits or HSA funding made those wages different.")
    for contribution in payroll_contributions:
        account = state.accounts[contribution.target_account_id]
        if (account.account_type == "hsa"
                and known_payroll.get(account.owner, {}).get("state_code") == "CA"):
            source = contribution.source_income_id
            covered_share = (covered_income_by_id.get(source, 0.0) / income_by_id[source]
                             if income_by_id.get(source, 0.0) > 0 else 0.0)
            state_wages_by_owner[account.owner] = (
                state_wages_by_owner.get(account.owner, 0.0) + contribution.employer_amount * covered_share
            )
    # US state payroll programs apply only in US years.
    payroll_obligations = {} if intl_year else state_payroll_obligations(
        year, state_wages_by_owner, payroll_coverage, federal_inflation_factor,
    )
    payroll_paid = tax_settings.get("state_payroll_paid_year_to_date", {}) if year == start_year else {}
    if ytd_imputed and not payroll_paid:
        # Like the federal share, the pre-start share of each state
        # obligation is treated as paid; only the post-start share is charged.
        payroll_paid = {name: liability * (1.0 - year_fraction) for name, liability in payroll_obligations.items()}
    # Required employee CA SDI / WA PFML payments are federal SALT,
    # not above-the-line adjustments or reductions in FICA wages.
    # Opening payments are part of the full-year obligation, not extra.
    payroll_salt = sum(max(payroll_obligations.get(name, 0.0), payroll_paid.get(name, 0.0))
                       for name in ("California SDI", "Washington Paid Leave"))
    if any(r.get("employer_pays_fraction", 0) > 0 for r in known_payroll.values()):
        coverage_warnings.add("Employer-paid state employee premiums need payroll review: employer pickup income and wage gross-ups are not modeled. Only the employee-paid share is included in the current estimate.")
    if resolved_state_code in {"CA", "WA"} and any(
            wages > 0 and owner not in known_payroll for owner, wages in w2_by_owner.items()):
        coverage_warnings.add("State payroll coverage is unspecified for some wage years; those obligations are omitted. Confirm work location, covered programs and exemptions.")
    return payroll_obligations, payroll_paid, payroll_salt


def _state_income_tax_warnings(
    year: int, *, tax_settings: Mapping[str, Any], resolved_state_code: str | None, ca_move_year: bool,
    coverage_warnings: set[str],
) -> None:
    """Step 6: what the California and Ohio income tax estimates leave out."""
    if resolved_state_code == "CA" or (ca_move_year and tax_settings.get("mode") != "flat"):
        if tax_settings.get("ca_exemption_eligible_owners") is None:
            coverage_warnings.add("California personal and senior exemption eligibility is unknown; these credits are omitted. Confirm whether each person can claim their own exemption.")
        if year >= 2026:
            coverage_warnings.add("California income tax uses 2025 tables for the 2026 estimated-tax calculation; later values are inflation projections. Dependent credits require an explicit count for each year. Blind credits and part-year proration are not modeled.")
    if resolved_state_code == "OH" and tax_settings.get("mode") != "flat":
        if tax_settings.get("oh_exemption_eligible_owners") is None:
            coverage_warnings.add("Ohio personal exemption eligibility is unknown; those exemptions are omitted.")
        coverage_warnings.add("Ohio dependent exemptions require an explicit count for each year; later exemption amounts are inflation projections. Other Ohio adjustments and credits are not modeled.")


def _opening_ira_by_owner(state: SimState, ytd: Mapping[str, Any]) -> dict[str, float]:
    """Opening year-to-date traditional IRA contributions by owner.

    They are assumed to be inside the opening ``deductions`` already, so
    they use up the deductible limit first and are added back to MAGI.
    """
    opening_ira_by_owner: dict[str, float] = {}
    for account_id, amount in ytd.get("contributions_by_account", {}).items():
        account = state.accounts.get(account_id)
        if account is not None and account.account_type == "traditional_ira":
            opening_ira_by_owner[account.owner] = opening_ira_by_owner.get(account.owner, 0.0) + amount
    return opening_ira_by_owner


def run_simulation(
    plan_data: PlanData,
    override_returns: dict[int, tuple] | None = None,
    withdrawal_strategy: WithdrawalStrategySpec | None = None,
) -> SimulationResult:
    """Run the deterministic projection for a single financial plan.

    Iterates year-by-year from *start_year* to *birth_year + life_expectancy*,
    executing the 12-step engine loop each year.

    If *override_returns* is provided, it maps simulation year to
    ``(stock_return, bond_return, inflation_rate)`` tuples that replace
    the assumption-curve values for those years (used by historical stress tests).

    *withdrawal_strategy* (the strategy comparison) takes precedence over the
    plan's saved ``plan_data.withdrawal_strategy``.
    """
    if withdrawal_strategy is None:
        withdrawal_strategy = plan_data.withdrawal_strategy
    if override_returns is not None:
        validate_override_returns(override_returns)
    validate_account_history(plan_data.accounts, plan_data.start_year)
    validate_person_healthcare_plan(plan_data)
    for gift in plan_data.charity_entities:
        if gift.source_account_id is not None:
            acct = plan_data.accounts.get(gift.source_account_id)
            if gift.entity_type != "qcd" or acct is None or acct.account_type not in _QCD_ELIGIBLE_TYPES or acct.owner not in {"self", "spouse"}:
                raise ValueError("QCD source must be a traditional IRA in this plan.")
    start_year = plan_data.start_year
    end_year = lifecycle.simulation_end_year(plan_data)
    # Planned real estate purchases (coastmath.engine.real_estate). Their loans are
    # added to this run's own copy of the liability list at purchase.
    purchase_positions = {
        asset.id: position for asset in plan_data.real_assets
        if (position := real_estate.purchase_start(asset, start_year, plan_data.first_year_fraction)) is not None
    }
    # Repeating loans (LiabilityData.recurrence_years) add their later
    # occurrences to the same per-run copy.
    repeating_loans = [liab for liab in plan_data.liabilities if liab.recurrence_years]
    if purchase_positions or repeating_loans:
        plan_data = replace(plan_data, liabilities=list(plan_data.liabilities))
    # Depreciable building basis by rental property (None: land split unknown).
    rental_building_basis: dict[str, float | None] = {
        asset.id: real_estate.opening_building_basis(asset)
        for asset in plan_data.real_assets
        if real_estate.is_rental(asset) and asset.id not in purchase_positions
    }

    # --- Initialise mutable state from plan accounts ---
    state = _opening_state(plan_data, start_year, purchase_positions)
    next_year = date(start_year + 1, 1, 1)
    days_in_year = (next_year - date(start_year, 1, 1)).days
    start_date = next_year - timedelta(days=round(days_in_year * plan_data.first_year_fraction))
    initial_snapshot = OpeningSnapshot(
        as_of=start_date,
        accounts=state.snapshot(),
        real_assets_value=state.total_real_asset_value(),
        liabilities_balance=state.total_liability_balance(),
        net_worth=state.total_net_worth(),
    )
    tax_settings = plan_data.tax_settings or {}
    # Scheduled tax changes rebind ``tax_settings`` to each year's effective
    # settings below; these plan-level settings are never modified.
    base_tax_settings = tax_settings
    conversion_rules = [p for p in plan_data.priorities if p.priority_type == "roth_conversion"]
    defer_conversions = any(p.conversion_mode == "fill_bracket" or p.magi_cap is not None
                            or p.use_plan_tax_target for p in conversion_rules)
    plan_tax_target = parse_tax_target(tax_settings)
    blend_drawdown = plan_tax_target is not None and bool(tax_settings.get("blend_drawdown_to_tax_target"))
    asset_location = parse_asset_location(tax_settings)
    state.capital_loss_carryforward = float(tax_settings.get("capital_loss_carryforward", 0.0))
    raw_provided_ytd = tax_settings.get("year_to_date")
    has_provided_ytd = raw_provided_ytd is not None
    provided_ytd = raw_provided_ytd or {}
    if has_provided_ytd and provided_ytd.get("tax_year") != start_year:
        raise ValueError("year_to_date.tax_year must match the first simulation year")
    tax_settlement_lag_years = max(
        0,
        int(tax_settings.get("settlement_lag_years", 0)),
    )
    taxable_withholding_rate = max(
        0.0,
        min(0.99, float(tax_settings.get("taxable_withholding_rate", 0.0))),
    )
    tax_deferred_withholding_rate = max(
        0.0,
        min(0.99, float(tax_settings.get("tax_deferred_withholding_rate", 0.0))),
    )
    drawdown_withholding_rates = {
        "brokerage": taxable_withholding_rate,
        "taxable_brokerage": taxable_withholding_rate,
        "cryptocurrency": taxable_withholding_rate,
        **dict.fromkeys(TRADITIONAL_RETIREMENT_TYPES, tax_deferred_withholding_rate),
    }

    # Fixed-rate defaults, used when no curves are defined
    default_inflation = get_assumption_rate(plan_data.assumptions, "inflation_rate")
    default_stock_growth = get_assumption_rate(plan_data.assumptions, "stock_growth_rate")
    default_bond_return = get_assumption_rate(plan_data.assumptions, "bond_return_rate")
    default_dividend_yield = get_assumption_rate(
        plan_data.assumptions, "stock_dividend_yield",
    )
    default_cash_yield = get_assumption_rate(plan_data.assumptions, "cash_yield_rate")

    curves = plan_data.assumption_curves

    # Social Security streams start at their claiming age unless a milestone says otherwise.
    plan_data = with_social_security_claiming(plan_data)
    original_milestones = plan_data.milestones
    plan_data = replace(plan_data, milestones=resolve_deterministic_milestones(
        plan_data.milestones, plan_data.birth_year, plan_data.birth_month,
    ))
    # A growth schedule's set amount can replace the opening year's amount.
    if any(inc.growth_schedule for inc in plan_data.income_streams):
        plan_data = replace(plan_data, income_streams=[
            replace(inc, annual_amount=opening_amount(inc, start_year)) if inc.growth_schedule else inc
            for inc in plan_data.income_streams
        ])
    # PIA-basis Social Security: size own benefits from the claim month and
    # add spousal-excess and divorced-spouse streams (no-op without a
    # PIA-basis stream).
    ss_base_plan = plan_data
    wage_indices = {int(y): value / SS_EARNINGS_RULES["national_average_wage_index"]["2024"] for y, value in SS_EARNINGS_RULES["national_average_wage_index"].items()}
    ss_wage_index = partial(_ss_wage_index, wage_indices, curves, plan_data.birth_year, default_inflation)
    ss_records = CoveredRecords(ss_base_plan, ss_wage_index)
    ss_withheld_months = {}
    # Earnings-test withheld months of spousal-type auxiliary benefits, by
    # entitlement pool (IncomeData.ss_spousal_reduction).
    ss_aux_withheld_months = {}
    ss_survivor_withheld_months = 0
    # Benefits whose earnings-test grace year has passed (20 CFR 404.435(b)).
    ss_grace_used = set()
    ss_claims = {}
    plan_data, spousal_workers = apply_household_benefits(plan_data)

    # Build lookup for linked-asset costs (property tax, maintenance)
    real_asset_map = {asset.id: asset for asset in plan_data.real_assets}
    milestone_map = {ms.id: ms for ms in plan_data.milestones}
    plan_milestone_ids = set(milestone_map)
    has_withdrawal_locks = any(acct.withdrawal_lock for acct in state.accounts.values())
    liquid_excluded_ids = frozenset(aid for aid, acct in state.accounts.items() if acct.include_in_liquid is False)
    survivor_context = prepare_survivor_policy(plan_data)

    timeline: list[YearSnapshot] = []
    fi_estimate = FiEstimate(multiple=FI_ESTIMATE_MULTIPLE)

    healthcare_warning_set: list[str] = []
    aca_magi_history: dict[int, float] = {}
    coverage_warnings: set[str] = set()
    # Years whose federal brackets lack the tax target's bracket rate.
    missing_target_rate_years: list[int] = []
    # Conversion rules whose own bracket ceiling the year's schedule lacks:
    # rule key -> (rate, years).
    missing_rule_rate_years: dict[tuple, tuple[float, list[int]]] = {}
    prior_w2_by_owner: dict[str, float] | None = None
    opening_ytd_imputed = False
    used_historical_yields = False
    used_assumed_yield_fallback = False
    # Track the first year each expense becomes active (for recurrence cadence)
    expense_activation_years: dict[str, int] = {}
    pension_accrual = PensionAccrual(plan_data)
    income_growth_factors = {inc.id: 1.0 for inc in plan_data.income_streams}
    # Streams with a growth schedule carry their nominal amount directly
    # (coastmath.engine.income_growth_schedule); a factor cannot express a set
    # amount on a zero opening amount.
    income_scheduled_amounts = {
        inc.id: inc.annual_amount for inc in plan_data.income_streams if inc.growth_schedule
    }
    # Social Security's amount-date/COLA authority is separate from expenses.
    social_security_inflation_factor = 1.0

    # Published federal tables override assumed inflation through 2026. This
    # multiplier follows calendar years, independently of the projection's
    # start date and partial first-year economic exposure. Future-start plans
    # project intervening unpublished years using the entered assumptions.
    federal_inflation_factor = 1.0
    calendar_inflation = {2026: 1.0}
    for prior_year in range(2026, start_year):
        prior_inflation = resolve_assumption(
            curves, "inflation", prior_year, plan_data.birth_year, default_inflation,
        )
        federal_inflation_factor *= 1.0 + prior_inflation
        calendar_inflation[prior_year + 1] = federal_inflation_factor
    # Opt-in IRC 6654 estimated tax; None (absent or "off") leaves every year unchanged.
    estimated_tax_plan = estimated_tax.parse_settings(tax_settings)
    estimated_tax_prior = None
    if estimated_tax_plan is not None:
        estimated_tax_prior = estimated_tax.first_prior_year(estimated_tax_plan)
        if tax_settings.get("mode") == "flat":
            coverage_warnings.add("Flat tax mode has no federal and state split; estimated tax payments "
                                  "and the underpayment penalty treat the whole blended tax as federal.")
    # Country tax regimes (coastmath.engine.intl_regime) and country account kinds
    # (coastmath.engine.intl_accounts). A US plan without country accounts skips
    # every step below, so its projection is unchanged.
    regime_plan = intl_regime.uses_regimes(plan_data)
    country_accounts = any(account.intl_account_kind for account in plan_data.accounts.values())
    if country_accounts:
        intl_accounts.configure_room(state, plan_data.intl_settings)
    regime_context = None
    if regime_plan:
        intl_regime.validate_regime_settings(plan_data)
        regime_context = intl_regime.RegimeContext.for_plan(plan_data)
        coverage_warnings.add(
            "Each year is taxed entirely by the country lived in for most of it. Country tax uses the plan's "
            "currency without exchange rates, and historical and simulated returns are US market history.")
    base_estimated_tax_plan = estimated_tax_plan
    # The previous country year's evaluator result (country, result).
    regime_prior: tuple[str, object] | None = None
    benefit_history = intl_regime.BenefitState()
    final_regime = ("US", None)
    # The last country year's evaluator inputs (the terminal return at the last death).
    final_regime_inputs = None
    # Each year runs these steps in order; the numbers match the step comments.
    #   1   milestones; 1a loan forgiveness; 1b repeating loans; 1c filing status and deaths
    #   2   market growth; 2b real assets; 2c RMDs; 2d QCDs
    #   3   gross income, Social Security earnings test, rentals; 3b SEPP payments
    #   4   payroll contributions and deductions; 5 withholding; 5b charitable gifts
    #   6   tax (_compute_tax); 6b health coverage
    #   7   active expenses and flex rules; 7a standard expenses; 7b withdrawal strategy
    #   8   expenses paid from named accounts
    #   9   net cash flow; 9b loans and carrying costs; 9c Roth conversions, harvests, transfers,
    #       then strategy withdrawal spending
    #   10  surplus waterfall or drawdown; 10a contribution growth; 10b unfunded-expense
    #       recovery; 10c tax settlement and leftover spending; 10d charitable carryforwards
    #   11  inflation and income growth; 12 the year's snapshot
    for year in range(start_year, end_year):
        ytd = provided_ytd if year == start_year and has_provided_ytd else {}
        ytd_tax_paid = float(ytd.get("tax_paid", 0.0))
        ytd_imputed = False
        known_hsa = _begin_year_state(
            state, plan_data, year, tax_settings=tax_settings, federal_inflation_factor=federal_inflation_factor,
            calendar_inflation=calendar_inflation, ytd=ytd, coverage_warnings=coverage_warnings)
        age = year - plan_data.birth_year
        year_fraction = (
            max(0.0, min(1.0, plan_data.first_year_fraction))
            if year == start_year
            else 1.0
        )
        state.year_fraction = year_fraction
        # Latch current-year HSA exposure through later depletion/settlement.
        # An account emptied in a prior year does not block this year's wages.
        hsa_exposure_this_year = any(
            account.account_type == "hsa" and account.balance != 0
            for account in state.accounts.values()
        )

        # Locks as of the year's start, so liquid-net-worth milestones below
        # exclude balances that are still locked.
        if has_withdrawal_locks:
            update_locked_accounts(state, plan_milestone_ids)

        # ---------------------------------------------------------------
        # 1. Evaluate milestones
        # ---------------------------------------------------------------
        newly_triggered = evaluate_milestones(
            state,
            plan_data.milestones,
            year,
            plan_data.birth_year,
            plan_data.spouse_birth_year,
            annual_expenses=state.last_year_expenses,
            birth_month=plan_data.birth_month,
            spouse_birth_month=plan_data.spouse_birth_month,
        )
        for identity in newly_triggered:
            if milestone_map[identity].trigger_type in {"conditions", "relative"}:
                milestone_map[identity] = replace(milestone_map[identity],
                    resolved_month=state.triggered_milestone_months.get(identity, 1))
        # The FI estimate is the same expense-multiple rule, evaluated at the
        # same point, so turning it into a real milestone keeps its year.
        if (fi_estimate.year is None and state.last_year_expenses is not None
                and expense_multiple_reached(state, FI_ESTIMATE_MULTIPLE, state.last_year_expenses, FI_ESTIMATE_METRIC)):
            fi_estimate = FiEstimate(year=year, basis_year=year - 1, multiple=FI_ESTIMATE_MULTIPLE,
                                     target=FI_ESTIMATE_MULTIPLE * state.last_year_expenses)
        # Milestones reached before the plan started (an age already passed or
        # a past date) are already in effect. Treat them as continuing so the
        # events they bound are not pro-rated as if the milestone fired now.
        newly_triggered = [
            mid for mid in newly_triggered
            if state.triggered_milestone_years.get(mid, year) >= plan_data.start_year
        ]

        # ---------------------------------------------------------------
        # 1a. One-time loan forgiveness
        # ---------------------------------------------------------------
        _apply_loan_forgiveness(state, plan_data, year, newly_triggered, coverage_warnings)

        # ---------------------------------------------------------------
        # 1b. Repeating loans: take the loan again on its original terms
        # ---------------------------------------------------------------
        _take_repeating_loans(state, plan_data, year, start_year=start_year, repeating_loans=repeating_loans,
                              milestone_map=milestone_map, newly_triggered=newly_triggered)

        # ---------------------------------------------------------------
        # 1c. Filing status and deaths
        # ---------------------------------------------------------------
        _apply_filing_status_and_deaths(state, plan_data, year, coverage_warnings)
        tax_holder_age, tax_spouse_age = lifecycle.tax_ages(plan_data, state, year)
        # The country whose regime taxes this year (majority of months).
        year_country, year_region = (resolve_country_for_year(
            year, state.triggered_milestones, plan_data, state.triggered_milestone_years)
            if regime_plan else ("US", None))
        intl_year = year_country != "US"
        final_regime = (year_country, year_region)
        if regime_plan:
            intl_cost_base.start_year(
                state, plan_data, year,
                intl_bridge.capital_gains_spec(year_country, year, regime_context.custom_spec),
                calendar_inflation)
        # US estimated tax applies only in US years.
        estimated_tax_plan = None if intl_year else base_estimated_tax_plan
        if country_accounts:
            coverage_warnings.update(intl_accounts.start_year(state, state.owner_ages))
        # This year's effective tax settings (coastmath.engine.tax_schedule): every
        # tax consumer below (withholding, targets, conversions, settlement)
        # reads this one dict for the year.
        tax_settings = effective_tax_settings(base_tax_settings, year, state.triggered_milestone_years)
        # This year's locks, after milestones fire and ownership transitions.
        if has_withdrawal_locks:
            update_locked_accounts(state, plan_milestone_ids)
        if country_accounts:
            intl_accounts.lock_before_access_age(state)

        # Each stream's active share of the year, bounded by the owner's
        # lifetime. The income loop and the opening-year imputation share it.
        income_active_until: dict[str, float] = {}
        for inc in plan_data.income_streams:
            active_until = 1.0 if inc.is_active else 0.0
            if lifecycle.enabled(plan_data):
                active_until = min(active_until, lifecycle.owner_alive_until(plan_data, state, inc.owner, year))
            elif inc.owner == "spouse" and state.partner_deceased:
                # Life expectancy is reached at the partner's birthday. The
                # death month itself is excluded (including Social Security).
                active_until = min(active_until, ((plan_data.spouse_birth_month or 1) - 1) / 12.0 if year == state.partner_death_year else 0.0)
            income_active_until[inc.id] = active_until
        # A spousal excess also stops when the worker's benefits stop at death;
        # a divorced-spouse stream stops with the claimant's own stream.
        for spousal_id, worker_id in spousal_workers.items():
            income_active_until[spousal_id] = min(income_active_until[spousal_id], income_active_until[worker_id])

        if year == start_year and not has_provided_ytd and 0.0 < year_fraction < 1.0:
            estimated_ytd = _impute_pro_rata_year_to_date(
                plan_data,
                milestone_map,
                state.triggered_milestones,
                newly_triggered,
                year,
                year_fraction,
                income_active_until,
            )
            if estimated_ytd:
                ytd = estimated_ytd
                ytd_imputed = True
                opening_ytd_imputed = True

        # ---------------------------------------------------------------
        # 2. Apply market growth to investment accounts
        # ---------------------------------------------------------------
        market = _apply_market_growth(
            state, plan_data, year, year_fraction, override_returns=override_returns, curves=curves,
            tax_settings=tax_settings, asset_location=asset_location, country_accounts=country_accounts,
            coverage_warnings=coverage_warnings, default_stock_growth=default_stock_growth,
            default_bond_return=default_bond_return, default_dividend_yield=default_dividend_yield,
            default_cash_yield=default_cash_yield)
        used_historical_yields = used_historical_yields or market.used_historical_yields
        used_assumed_yield_fallback = used_assumed_yield_fallback or market.used_assumed_yield_fallback
        annual_account_rates = market.annual_account_rates
        annual_income_composition = market.annual_income_composition
        bond_allocation = market.bond_allocation
        bond_allocation_by_account = market.bond_allocation_by_account
        prior_year_balances = market.prior_year_balances
        regime_opening = market.regime_opening
        taxable_dividends = market.taxable_dividends
        taxable_cash_interest = market.taxable_cash_interest
        taxable_bond_interest = market.taxable_bond_interest
        total_start, total_end = market.total_start, market.total_end

        # ---------------------------------------------------------------
        # 2b. Appreciate real assets
        # ---------------------------------------------------------------
        (real_asset_start_values, asset_fractions, asset_windows, scheduled_sales,
         purchases_this_year) = _appreciate_real_assets(
            state, plan_data, year, year_fraction, purchase_positions=purchase_positions,
            rental_building_basis=rental_building_basis)

        # ---------------------------------------------------------------
        # 2c. Required Minimum Distributions (RMDs)
        # ---------------------------------------------------------------
        (rmd_total, taxable_rmd_total, roth_rmd_income, ira_rmd_total, ira_rmd_by_owner,
         ira_rmd_by_account) = _required_minimum_distributions(
            state, plan_data, year, age, prior_year_balances=prior_year_balances, ytd=ytd)

        # ---------------------------------------------------------------
        # 2d. Qualified Charitable Distributions (QCDs)
        # ---------------------------------------------------------------
        qcd_total, qcd_withdrawals, qcd_rmd_offset, rmd_tax_withheld = _qualified_charitable_distributions(
            state, plan_data, tax_holder_age=tax_holder_age, ira_rmd_total=ira_rmd_total,
            ira_rmd_by_owner=ira_rmd_by_owner, ira_rmd_by_account=ira_rmd_by_account,
            taxable_rmd_total=taxable_rmd_total, tax_deferred_withholding_rate=tax_deferred_withholding_rate)
        if country_accounts:
            # Country minimum withdrawals (an account kind's minimum) are paid like RMDs;
            # their taxable part is counted with the year's account withdrawals.
            rmd_total += intl_accounts.minimum_withdrawals(state, state.owner_ages, prior_year_balances)

        # ---------------------------------------------------------------
        # 3. Calculate gross income
        # ---------------------------------------------------------------
        residency_spans = resolve_residency_spans(
            year, state.triggered_milestones, plan_data,
            state.triggered_milestone_years,
        )
        residency_states = tuple(dict.fromkeys(span.state_code for span in residency_spans))
        ca_move_year = "CA" in residency_states and len(residency_states) > 1
        # State additional taxes on early distributions (CA FTB 3805P) apply
        # for resident months. Flat mode's blended rate replaces state taxes.
        state.early_distribution_state_rates = () if tax_settings.get("mode") == "flat" else tuple(
            (span.start_month - 1.0, span.end_month - 1.0, rate)
            for span in residency_spans
            if (rate := state_early_distribution_rate(span.state_code)) > 0.0
        )
        if tax_settings.get("mode") != "flat":
            residency_bound_ids = {
                identity
                for period in plan_data.residency_periods
                for identity in (period.start_milestone_id, period.end_milestone_id)
                if identity is not None
            }
            for identity in residency_bound_ids.intersection(newly_triggered):
                milestone = milestone_map.get(identity)
                if milestone is None or milestone.trigger_type not in {"date", "age"}:
                    coverage_warnings.add(
                        f"{year}: Residency milestone {identity} has no determined "
                        "trigger month; the January state-tax timing estimate remains unresolved."
                    )
        payroll_coverage = tax_settings.get("state_payroll_coverage", [])
        known_payroll = active_coverage(year, payroll_coverage)
        pension_salary_share = partial(_pension_salary_share, state, plan_data, year, year_fraction, start_year,
                                       milestone_map, newly_triggered, income_active_until)
        pension_amounts = {
            inc.id: pension_accrual.amount(inc, year, start_year, state.triggered_milestone_years,
                income_growth_factors, state.inflation_factor, pension_salary_share,
                resolve_trigger_month(milestone_map[inc.start_milestone_id], plan_data.birth_month, year)
                if inc.start_milestone_id in milestone_map else 1,
                scheduled_amounts=income_scheduled_amounts)
            for inc in plan_data.income_streams if inc.pension_formula
        }
        if ss_records.records:
            revised, _ = apply_household_benefits(ss_records.adjusted_plan())
            replacements = {inc.id: inc for inc in revised.income_streams}
            # Existing stream identity and lifecycle windows remain authoritative.
            plan_data = replace(plan_data, income_streams=[replacements.get(inc.id, inc) for inc in plan_data.income_streams])
            survivor_context = prepare_survivor_policy(plan_data)
        ss_adjustments = {}
        for inc in plan_data.income_streams:
            if not inc.is_social_security or inc.ss_worker_income_id:
                continue
            # A spouse's stream needs the partner's birth year; this raises without it.
            owner_birth(plan_data, inc.owner)
            milestone = milestone_map.get(inc.start_milestone_id)
            claim = month_index(int(milestone.trigger_date[:4]), inc.start_month or int(milestone.trigger_date[5:7])) if milestone and milestone.trigger_date else month_index(start_year, 1)
            ss_claims[inc.id] = claim
            multiplier = arf_factor(plan_data, inc, claim, ss_withheld_months.get(inc.id, 0))
            ss_adjustments[inc.id] = multiplier
        spousal_arf = partial(_spousal_arf, ss_aux_withheld_months)
        for inc in plan_data.income_streams:
            if inc.is_social_security and inc.ss_worker_income_id and inc.ss_spousal_reduction:
                ss_adjustments[inc.id] = spousal_arf(inc)

        income = _income_streams(
            state, plan_data, year, year_fraction, start_year=start_year, ytd=ytd, milestone_map=milestone_map,
            newly_triggered=newly_triggered, income_active_until=income_active_until,
            income_growth_factors=income_growth_factors, income_scheduled_amounts=income_scheduled_amounts,
            pension_amounts=pension_amounts, social_security_inflation_factor=social_security_inflation_factor,
            ss_adjustments=ss_adjustments, known_payroll=known_payroll, residency_spans=residency_spans,
            ca_move_year=ca_move_year, taxable_dividends=taxable_dividends,
            taxable_bond_interest=taxable_bond_interest, taxable_cash_interest=taxable_cash_interest)
        gross_income, nontaxable_income, ss_income = income.gross_income, income.nontaxable_income, income.ss_income
        earned_income, w2_income, ca_w2_income = income.earned_income, income.w2_income, income.ca_w2_income
        non_earned_income, has_self_employment = income.non_earned_income, income.has_self_employment
        w2_by_owner, se_by_owner = income.w2_by_owner, income.se_by_owner
        state_ytd_wages, state_wages_by_owner = income.state_ytd_wages, income.state_wages_by_owner
        covered_income_by_id = income.covered_income_by_id
        nonresident_payroll_wages = income.nonresident_payroll_wages
        local_stream_income = income.local_stream_income
        income_details, income_by_id = income.income_details, income.income_by_id
        income_grown_by_id, income_active_share = income.income_grown_by_id, income.income_active_share
        cf_income_sources = income.cf_income_sources

        # ---------------------------------------------------------------
        # Social Security survivor top-up and earnings test
        ss_income, ss_earnings_test_withheld, ss_survivor_withheld_months, ss_withheld_by_earner = (
            _social_security_survivor_and_earnings_test(
                state, plan_data, year, year_fraction, start_year=start_year, ytd=ytd, ytd_imputed=ytd_imputed,
                has_provided_ytd=has_provided_ytd, milestone_map=milestone_map, newly_triggered=newly_triggered,
                survivor_context=survivor_context, income_by_id=income_by_id, income_details=income_details,
                income_grown_by_id=income_grown_by_id, income_active_share=income_active_share,
                income_active_until=income_active_until, income_growth_factors=income_growth_factors,
                social_security_inflation_factor=social_security_inflation_factor,
                ss_adjustments=ss_adjustments, ss_claims=ss_claims, ss_withheld_months=ss_withheld_months,
                ss_aux_withheld_months=ss_aux_withheld_months,
                ss_survivor_withheld_months=ss_survivor_withheld_months, ss_grace_used=ss_grace_used,
                ss_wage_index=ss_wage_index, spousal_arf=spousal_arf, ss_income=ss_income,
                cf_income_sources=cf_income_sources))
        # Country benefits (intl_settings.benefits): income like a stream. In
        # a US year they are taxed as ordinary income.
        intl_benefits: list[intl_regime.BenefitPayment] = []
        if regime_plan and (plan_data.intl_settings or {}).get("benefits"):
            benefit_people = intl_regime.people_this_year(plan_data, state, year)
            intl_benefits = intl_regime.benefit_payments(
                plan_data, state, year, history=benefit_history, people=benefit_people,
                filing_unit=intl_regime.filing(benefit_people, state.current_filing_status or plan_data.filing_status),
                prior=regime_prior[1] if regime_prior is not None and regime_prior[0] == year_country else None,
                milestone_months=state.triggered_milestone_months)
            intl_regime.remember_benefits(benefit_history, intl_benefits, benefit_people)
            for payment in intl_benefits:
                if payment.income_type == "nontaxable":
                    nontaxable_income += payment.amount
                else:
                    gross_income += payment.amount
                income_details.append((payment.amount, 0.0))
                cf_income_sources.append(NamedAmount(name=payment.label, amount=payment.amount))
        projected_wages, projected_se = {}, {}
        for job in plan_data.income_streams:
            if not job.is_earned_income or job.is_social_security:
                continue
            totals = projected_se if job.is_self_employed else projected_wages
            totals[job.owner] = totals.get(job.owner, 0.0) + income_by_id.get(job.id, 0.0)
        if year == start_year:
            for key, totals in (("w2_income_by_owner", projected_wages), ("self_employment_income_by_owner", projected_se)):
                for owner, amount in ytd.get(key, {}).items():
                    totals[owner] = totals.get(owner, 0.0) + float(amount)
        ss_records.add_year(year, projected_wages, projected_se)

        # Rental properties: collected rent, operating expenses and
        # depreciation (coastmath.engine.real_estate). Property tax, upkeep and
        # loan interest join in step 9b. Rent is cash but enters AGI only as
        # the net amount the passive loss rules allow (_compute_tax).
        rental_year, rental_share, rental_cash_income, rental_operating_expenses = _rental_activity(
            state, plan_data, year, start_year=start_year, asset_fractions=asset_fractions,
            asset_windows=asset_windows, purchases_this_year=purchases_this_year,
            rental_building_basis=rental_building_basis, coverage_warnings=coverage_warnings,
            cf_income_sources=cf_income_sources)

        # 3b. SEPP 72(t) mandatory withdrawals
        # ---------------------------------------------------------------
        # A series uses the IRA owner's age and life expectancy and runs to
        # the later of five years or that owner's 59.5 (Notice 2022-6); the
        # requirement ends at the owner's death. Ownership is the original
        # one, before any inheritance moves the account to a survivor.
        sepp = plan_data.sepp_settings
        sepp_income, sepp_penalty, sepp_fraction, gross_income = _sepp_distribution(
            state, plan_data, year, year_fraction, prior_year_balances=prior_year_balances,
            gross_income=gross_income, cf_income_sources=cf_income_sources)

        if rmd_total > 0:
            cf_income_sources.append(NamedAmount(name="RMD", amount=rmd_total, source="rmd"))

        # ---------------------------------------------------------------
        # 4. Payroll deductions (expenses tied to income; tax treatment is
        # explicit below while the cash-flow deduction remains unchanged)
        # ---------------------------------------------------------------
        payroll_contributions, w2_income_ids, self_employment_income_ids, fica_w2_by_owner = _allocate_payroll(
            state, plan_data, year, year_fraction, age, w2_by_owner=w2_by_owner, se_by_owner=se_by_owner,
            prior_w2_by_owner=prior_w2_by_owner, ytd=ytd, federal_inflation_factor=federal_inflation_factor,
            income_by_id=income_by_id, income_active_share=income_active_share, known_hsa=known_hsa,
            coverage_warnings=coverage_warnings)
        (after_tax_payroll, self_employed_adjustments, self_employed_plan_deductions,
         payroll_retirement_by_account, payroll_retirement_deductions, payroll_ira_deductions,
         payroll_nj_deferrals, nj_employer_403b_by_account, payroll_tax_deductions, payroll_deductions,
         employer_contribution_income, roth_employer_income) = _payroll_tax_treatment(
            state, payroll_contributions, w2_income_ids=w2_income_ids,
            self_employment_income_ids=self_employment_income_ids, coverage_warnings=coverage_warnings)
        ira_covered_owners, ira_employer_contributions = _ira_active_participants(state, payroll_contributions, ytd)
        contributions_for_growth, pre_waterfall_contributions = _payroll_contribution_flows(
            state, plan_data, payroll_contributions, self_employment_income_ids=self_employment_income_ids,
            cf_income_sources=cf_income_sources)

        (payroll_expenses, cf_payroll_expenses, payroll_deductions, payroll_tax_deductions,
         payroll_state_addback, payroll_local_addback) = _payroll_expense_deductions(
            state, plan_data, year, year_fraction, start_year=start_year, milestone_map=milestone_map,
            newly_triggered=newly_triggered, income_by_id=income_by_id,
            income_active_until=income_active_until, expense_activation_years=expense_activation_years,
            self_employment_income_ids=self_employment_income_ids, fica_w2_by_owner=fica_w2_by_owner,
            payroll_deductions=payroll_deductions, payroll_tax_deductions=payroll_tax_deductions)

        # ---------------------------------------------------------------
        # 5. Tax withholding
        # ---------------------------------------------------------------
        tax_withheld = sum(
            amt * pct for amt, pct in income_details
        )

        # ---------------------------------------------------------------
        # 5b. DAF / direct charitable contributions
        # ---------------------------------------------------------------
        charitable_result = _process_charitable_contributions(
            state, plan_data, gross_income, newly_triggered,
            ss_income=ss_income, rmd_total=rmd_total, defer_sales=True,
        )
        coverage_warnings.update(charitable_result.warnings)
        # Pass all claimable cash gifts; calculate_tax caps them at final AGI.
        charitable_deduction = (charitable_result.total_contributions
            + sum(amount for _, amount in charitable_result.prior_carryforward))
        charitable_property = (charitable_result.property_contributions
            + sum(amount for _, amount in charitable_result.prior_property_carryforward))

        # ---------------------------------------------------------------
        # 6. Actual tax liability
        # ---------------------------------------------------------------
        filing_status, annual_tax_settings, year_adjustments, salt_passes, salt_tolerance = _year_return(
            state, plan_data, year, start_year=start_year, tax_settings=tax_settings,
            base_tax_settings=base_tax_settings, tax_spouse_age=tax_spouse_age)
        resolved_state_code, resolved_local_tax = _year_tax_jurisdictions(
            state, plan_data, year, start_year=start_year, tax_settings=tax_settings,
            residency_spans=residency_spans, earned_income=earned_income, coverage_warnings=coverage_warnings)
        payroll_obligations, payroll_paid, payroll_salt = _state_payroll_programs(
            state, year, year_fraction, start_year=start_year, tax_settings=tax_settings, intl_year=intl_year,
            ytd_imputed=ytd_imputed, federal_inflation_factor=federal_inflation_factor,
            payroll_coverage=payroll_coverage, known_payroll=known_payroll,
            payroll_contributions=payroll_contributions, state_wages_by_owner=state_wages_by_owner,
            state_ytd_wages=state_ytd_wages, covered_income_by_id=covered_income_by_id, income_by_id=income_by_id,
            w2_by_owner=w2_by_owner, resolved_state_code=resolved_state_code, coverage_warnings=coverage_warnings)
        _state_income_tax_warnings(
            year, tax_settings=tax_settings, resolved_state_code=resolved_state_code, ca_move_year=ca_move_year,
            coverage_warnings=coverage_warnings)
        opening_ira_by_owner = _opening_ira_by_owner(state, ytd)
        tax = _YearTax(
            plan_data=plan_data, state=state, year=year, age=age, ytd=ytd, ytd_imputed=ytd_imputed,
            tax_settings=tax_settings, annual_tax_settings=annual_tax_settings, filing_status=filing_status,
            tax_holder_age=tax_holder_age, tax_spouse_age=tax_spouse_age,
            federal_inflation_factor=federal_inflation_factor, calendar_inflation=calendar_inflation,
            default_inflation=default_inflation, year_adjustments=year_adjustments,
            intl_year=intl_year, year_country=year_country, year_region=year_region,
            regime_context=regime_context, regime_prior=regime_prior, regime_opening=regime_opening,
            intl_benefits=intl_benefits, income_by_id=income_by_id, gross_income=gross_income,
            ss_income=ss_income, earned_income=earned_income, w2_income=w2_income, ca_w2_income=ca_w2_income,
            non_earned_income=non_earned_income, local_stream_income=local_stream_income,
            has_self_employment=has_self_employment, w2_by_owner=w2_by_owner, fica_w2_by_owner=fica_w2_by_owner,
            se_by_owner=se_by_owner, taxable_cash_interest=taxable_cash_interest,
            taxable_rmd_total=taxable_rmd_total, qcd_rmd_offset=qcd_rmd_offset, sepp_income=sepp_income,
            rental_year=rental_year, roth_employer_income=roth_employer_income,
            payroll_tax_deductions=payroll_tax_deductions, self_employed_adjustments=self_employed_adjustments,
            self_employed_plan_deductions=self_employed_plan_deductions,
            payroll_retirement_deductions=payroll_retirement_deductions,
            payroll_ira_deductions=payroll_ira_deductions, payroll_nj_deferrals=payroll_nj_deferrals,
            payroll_state_addback=payroll_state_addback, payroll_local_addback=payroll_local_addback,
            payroll_salt=payroll_salt, ira_covered_owners=ira_covered_owners,
            ira_employer_contributions=ira_employer_contributions, opening_ira_by_owner=opening_ira_by_owner,
            charitable_result=charitable_result, charitable_deduction=charitable_deduction,
            charitable_property=charitable_property, resolved_state_code=resolved_state_code,
            resolved_local_tax=resolved_local_tax, residency_states=residency_states,
            ca_move_year=ca_move_year, nonresident_payroll_wages=nonresident_payroll_wages,
            salt_passes=salt_passes, salt_tolerance=salt_tolerance,
            ordinary_drawdown_income=0.0,
            mortgage_interest=float(ytd.get("mortgage_interest", 0.0)),
            property_tax_paid=float(ytd.get("property_tax", 0.0)),
            hsa_exposure=hsa_exposure_this_year,
        )
        tax_result = _compute_tax(tax)
        actual_tax = tax_result.total_tax
        ytd_tax_paid = _opening_tax_paid(tax)
        tax_delta = tax_withheld + rmd_tax_withheld + ytd_tax_paid - actual_tax

        # ---------------------------------------------------------------
        # 6b. Health coverage (ACA credit uses this year's MAGI; IRMAA uses
        #     MAGI from two years earlier). Premiums are added to standard
        #     expenses below exactly once; the credit is netted, not income.
        # ---------------------------------------------------------------
        _hc_settings = parse_healthcare_settings(plan_data.healthcare_settings)

        _hc_nontaxable_ss = max(0.0, ss_income + float(ytd.get("social_security_income", 0.0)) - tax_result.taxable_social_security)
        if (year - 1) in aca_magi_history:
            _hc_magi_estimate = aca_magi_history[year - 1]
        elif _hc_settings.magi_prior_year is not None:
            _hc_magi_estimate = _hc_settings.magi_prior_year
        else:
            _hc_magi_estimate = _aca_magi(tax, tax_result)
        # Marketplace coverage runs from the start milestone's month through
        # the month before the end milestone, like milestone-bounded expenses.
        # A start milestone missing from the plan never triggers.
        aca_start_known = (_hc_settings.aca_start_milestone_id is None
                           or _hc_settings.aca_start_milestone_id in milestone_map)
        aca_months = frozenset(
            month for month in range(1, 13)
            if aca_start_known and prorate_for_year(
                milestone_map.get(_hc_settings.aca_start_milestone_id),
                milestone_map.get(_hc_settings.aca_end_milestone_id),
                None, None, state.triggered_milestones, newly_triggered, year,
                plan_data.birth_month, active_from=(month - 1) / 12, active_until=month / 12,
            ) > 0
        )
        if intl_year and _hc_settings.enabled:
            coverage_warnings.add("US health coverage costs (ACA, Medicare and IRMAA) are not projected in years taxed "
                                  "by another country. Enter local health costs as expenses.")
        healthcare_year, healthcare_warnings = (None, []) if intl_year else _compute_healthcare_year(
            state, plan_data, year=year, start_year=start_year, age=age,
            year_fraction=year_fraction, filing_status=filing_status,
            # IRMAA MAGI adds tax-exempt interest (42 U.S.C. 1395r(i)(4)(A)).
            agi=tax_result.modified_agi + tax_result.tax_exempt_interest,
            nontaxable_ss=_hc_nontaxable_ss,
            aca_active=bool(aca_months),
            aca_magi_estimate=_hc_magi_estimate,
            aca_months=aca_months,
        )

        tax.healthcare_year, tax.hc_settings = healthcare_year, _hc_settings
        for _w in healthcare_warnings:
            if _w not in healthcare_warning_set:
                healthcare_warning_set.append(_w)
        healthcare_total = healthcare_year.total if healthcare_year is not None else 0.0
        state.hsa_medical_allowance, state.hsa_medicare_premium_allowance = (
            _hsa_qualified_medical_costs(healthcare_year))
        if (healthcare_year is not None and tax_settings.get("medical_expense_deductions")
                and tax_settings.get("mode") != "flat"):
            tax.medical_deductions = True
            tax.hsa_medical_start = state.hsa_medical_allowance

            if has_self_employment:
                coverage_warnings.add("The self-employed health insurance deduction assumes no month with "
                                      "eligibility for an employer-subsidized health plan.")

        # ---------------------------------------------------------------
        # 7. Collect active standard expenses and apply flex rules
        # ---------------------------------------------------------------
        newly_triggered_set = set(newly_triggered)
        active_standard_expenses = [
            exp for exp in plan_data.expenses
            if not exp.is_payroll_deduction
            and not _expense_funding_ids(exp)
            and (
                is_event_active(exp.start_milestone_id, exp.end_milestone_id, state.triggered_milestones)
                or (exp.end_milestone_id is not None and exp.end_milestone_id in newly_triggered_set
                    and (exp.start_milestone_id is None or exp.start_milestone_id in state.triggered_milestones))
            )
        ]
        flex_adjusted_expenses = apply_flex_rules(
            active_standard_expenses, plan_data, state, year,
        )
        # One multiplier per year feeds, in order: ordinary expenses (above),
        # strategy spending (7b) and leftover spending (10c).
        flex_mult = flex_multiplier(plan_data, state)
        spend_leftover_mode = spends_leftover(plan_data, state)
        # Planned spending that flex never cuts, for the strategy's floor.
        planned_essential = 0.0

        # ---------------------------------------------------------------
        # 7a. Standard expenses (using flex-adjusted amounts)
        # ---------------------------------------------------------------
        standard_expenses, original_expenses, cf_expenses, planned_essential = _standard_expenses(
            state, plan_data, year, year_fraction, start_year=start_year,
            active_standard_expenses=active_standard_expenses, flex_adjusted_expenses=flex_adjusted_expenses,
            milestone_map=milestone_map, newly_triggered=newly_triggered,
            expense_activation_years=expense_activation_years, planned_essential=planned_essential)

        # ---------------------------------------------------------------
        # 7b. Textbook withdrawal strategy spending
        # ---------------------------------------------------------------
        (standard_expenses, original_expenses, cf_expenses, strategy_spent, strategy_withdrawal_target,
         strategy_planned_part, planned_for_year, pending_strategy_flex_delta) = _withdrawal_strategy_spending(
            state, plan_data, year, year_fraction, age, end_year=end_year,
            withdrawal_strategy=withdrawal_strategy, milestone_map=milestone_map,
            newly_triggered=newly_triggered, prior_year_balances=prior_year_balances,
            bond_allocation=bond_allocation, flex_mult=flex_mult, planned_essential=planned_essential,
            standard_expenses=standard_expenses, original_expenses=original_expenses, cf_expenses=cf_expenses)

        if healthcare_total > 0:
            standard_expenses += healthcare_total
            original_expenses += healthcare_total
            cf_expenses.append(NamedAmount(name="Health coverage", amount=healthcare_total, category="essential"))

        # These employee obligations are paid from cash, outside income-tax
        # settlement. Keeping named flows avoids overloading state income tax
        # and lets clients display the statutory payroll cost explicitly.
        if payroll_obligations:
            coverage_warnings.add("State payroll obligations appear once as named expenses, separate from the taxes total. Mandatory employee CA SDI and WA Paid Leave payments enter federal itemized SALT subject to limits; WA Cares deductibility is not assumed. State income-tax SALT uses estimated annual payments; delayed settlement/refunds require review. Future rates are assumptions.")
            if ytd.get("w2_income_by_owner") and not payroll_paid:
                coverage_warnings.add("Year-to-date state payroll payments are unspecified; the full calculated payroll obligation remains due. Enter payments already made to avoid charging them twice.")
        for name, liability in payroll_obligations.items():
            amount = max(0.0, liability - payroll_paid.get(name, 0.0))
            standard_expenses += amount
            original_expenses += amount
            if amount:
                cf_expenses.append(NamedAmount(name=name, amount=amount, category="state_payroll_tax"))

        planned_flex_net = original_expenses - standard_expenses

        # ---------------------------------------------------------------
        # 8. Specific drawdown overrides
        # ---------------------------------------------------------------
        early_withdrawal_penalty = sepp_penalty
        specific_drawdowns = {}
        # An active series' account is never tapped beyond its payment.
        sepp_account_ids = {sepp.source_account_id} if sepp_fraction > 0 else set()
        specific_funded_expenses, tax.ordinary_drawdown_income, early_withdrawal_penalty = _fund_specific_expenses(
            state, plan_data, year, year_fraction, age, start_year=start_year, milestone_map=milestone_map,
            newly_triggered=newly_triggered, expense_activation_years=expense_activation_years,
            annual_account_rates=annual_account_rates, annual_income_composition=annual_income_composition,
            sepp_account_ids=sepp_account_ids, drawdown_withholding_rates=drawdown_withholding_rates,
            ordinary_drawdown_income=tax.ordinary_drawdown_income, early_withdrawal_penalty=early_withdrawal_penalty,
            specific_drawdowns=specific_drawdowns, cf_expenses=cf_expenses)

        (real_estate_purchase_cash, purchase_cash_from_flow, tax.ordinary_drawdown_income,
         early_withdrawal_penalty) = _fund_real_estate_purchases(
            state, plan_data, age, purchases_this_year=purchases_this_year, sepp_account_ids=sepp_account_ids,
            drawdown_withholding_rates=drawdown_withholding_rates,
            ordinary_drawdown_income=tax.ordinary_drawdown_income, early_withdrawal_penalty=early_withdrawal_penalty,
            specific_drawdowns=specific_drawdowns, cf_expenses=cf_expenses)

        # ---------------------------------------------------------------
        # 9. Net cash flow
        # ---------------------------------------------------------------
        spendable_rmd = (
            rmd_total
            - qcd_rmd_offset
            - rmd_tax_withheld
        )
        tax_settlement_cash = (
            tax_delta
            if tax_settlement_lag_years == 0
            else state.pending_tax_settlements.pop(year, 0.0)
        )
        if defer_conversions and tax_settlement_lag_years == 0:
            # A targeted conversion can consume an estimated refund. Do not
            # invest that provisional cash and sell it again at final tax time.
            tax_settlement_cash = min(0.0, tax_settlement_cash)
        net_cash = (
            gross_income + ss_income + nontaxable_income - payroll_deductions - after_tax_payroll - tax_withheld
        ) + tax_settlement_cash - standard_expenses + spendable_rmd
        net_cash += rental_cash_income - rental_operating_expenses - purchase_cash_from_flow
        # The additional tax on an unvalidated custom SEPP amount is paid in cash.
        net_cash -= sepp_penalty
        # Taxable-account income paid out instead of reinvested (taxed through
        # the investment income accumulators, not gross_income).
        net_cash += state.paid_out_dividends_this_year + state.paid_out_bond_interest_this_year
        # Gifts reserved against brokerage shares (step 5b) are paid from the
        # year's cash first; a deficit sells the reserved shares below.
        net_cash -= sum(charitable_result.deferred_sales.values())

        # ---------------------------------------------------------------
        # 9b. Liability payments (amortization + linked asset costs)
        # ---------------------------------------------------------------
        # XXX Missed-payment precision: the annual engine assumes scheduled
        # liability payments are made, then tests whether the plan can fund
        # the resulting cash deficit. If liquidity is insufficient and the
        # plan fails, later liability balances are non-authoritative until a
        # missed-payment/accrued-interest model is added.
        total_liability_payments, tax.mortgage_interest = _pay_liabilities(
            state, plan_data, year, year_fraction, milestone_map=milestone_map,
            newly_triggered=newly_triggered, asset_fractions=asset_fractions, asset_windows=asset_windows,
            real_asset_map=real_asset_map, rental_year=rental_year, rental_share=rental_share,
            mortgage_interest=tax.mortgage_interest, cf_expenses=cf_expenses)

        net_cash -= total_liability_payments

        if tax.mortgage_interest > 0 and tax_settings.get("mode") != "flat":
            coverage_warnings.add("Mortgage interest is deducted without an acquisition-debt limit. Loan origination dates, qualified acquisition balances and refinancing history are unavailable, so the applicable $750,000/$375,000 or grandfathered limit cannot be determined; federal tax may be understated.")

        # Carrying costs accrue for every asset still owned, mortgage or not.
        asset_carrying_costs, tax.property_tax_paid = _asset_carrying_costs(
            state, plan_data, year_fraction, real_asset_start_values=real_asset_start_values,
            asset_fractions=asset_fractions, rental_year=rental_year, rental_share=rental_share,
            property_tax_paid=tax.property_tax_paid, cf_expenses=cf_expenses)
        net_cash -= asset_carrying_costs
        for asset in plan_data.real_assets:
            activity = rental_year.get(asset.id)
            if activity is not None and activity.operating > 0:
                cf_expenses.append(NamedAmount(
                    name=f"{asset.name} (rental expenses)", amount=activity.operating, category="essential"))
        for asset in scheduled_sales:
            _sell_real_asset(state, plan_data, asset, asset.sale_month)
        # Refresh deductions and sales before allocating cash. The earlier
        # estimate was used only to construct net_cash.
        tax_result = _compute_tax(tax)
        actual_tax = tax_result.total_tax
        ytd_tax_paid = _opening_tax_paid(tax)
        new_settlement = tax_withheld + state.drawdown_tax_withheld_this_year + ytd_tax_paid - actual_tax
        if tax_settlement_lag_years == 0:
            if defer_conversions:
                new_settlement = min(new_settlement, 0.0)
            net_cash += new_settlement - tax_settlement_cash
            tax_settlement_cash = new_settlement
        cash = _YearCash(
            tax=tax, year_fraction=year_fraction, sepp_account_ids=sepp_account_ids,
            withholding_rates=drawdown_withholding_rates, tax_withheld=tax_withheld,
            settlement_lag_years=tax_settlement_lag_years, estimated_tax_plan=estimated_tax_plan,
            estimated_tax_prior=estimated_tax_prior, spend_leftover_mode=spend_leftover_mode,
            contributions_for_growth=contributions_for_growth, coverage_warnings=coverage_warnings,
            net_cash=net_cash, tax_result=tax_result, actual_tax=actual_tax, ytd_tax_paid=ytd_tax_paid,
            early_withdrawal_penalty=early_withdrawal_penalty)
        estimated_tax_cash = 0.0
        if estimated_tax_plan is not None:
            # Fund this year's estimate cash before surplus is allocated, as the
            # balance due above is; settlement below trues it up.
            estimated_tax_cash = _estimated_tax_year(cash, cash.tax_result, 0.0).in_year_cash(tax_settlement_lag_years)
            cash.net_cash += estimated_tax_cash

        # Charitable outflows (DAF/direct — step 5b) — reporting only, already
        # withdrew from accounts above; this makes them visible in cf_expenses.
        charitable_total = 0.0
        for ent_name, ent_amount in charitable_result.entity_outflows:
            cf_expenses.append(NamedAmount(
                name=ent_name, amount=ent_amount, category="discretionary",
            ))
            charitable_total += ent_amount

        # QCD outflows (step 2d) — reporting only.  The QCD amount already
        # reduces spendable_rmd and is NOT subtracted from net_cash again.
        # Including it in snapshot.expenses documents the outflow for Sankey /
        # tooltip purposes without affecting the cash movement math.
        if qcd_total > 0:
            cf_expenses.append(NamedAmount(
                name="QCD to charity", amount=qcd_total, category="discretionary",
            ))

        # ---------------------------------------------------------------
        # 9c. Roth conversions & transfers (account-to-account, independent of surplus)
        # ---------------------------------------------------------------
        target_aca_active = healthcare_year is not None and healthcare_year.aca_covered_adults > 0
        year_target = _plan_tax_target_year(
            tax, plan_tax_target, target_aca_active=target_aca_active, override_returns=override_returns,
            curves=curves, missing_target_rate_years=missing_target_rate_years)
        cash.year_target, cash.target_aca_active = year_target, target_aca_active
        tax_target_room = (year_target.room(tax_measures(
            cash.tax_result, aca_magi=_aca_magi(tax, cash.tax_result), aca_active=target_aca_active))
            if year_target is not None else None)

        _conversions_harvests_and_transfers(
            cash, conversion_rules, defer_conversions=defer_conversions, milestone_map=milestone_map,
            newly_triggered=newly_triggered, annual_account_rates=annual_account_rates,
            annual_income_composition=annual_income_composition)
        if strategy_withdrawal_target is not None:
            strategy_spent, standard_expenses, original_expenses = _spend_strategy_withdrawal(
                cash, strategy_withdrawal_target=strategy_withdrawal_target,
                strategy_planned_part=strategy_planned_part, pending_strategy_flex_delta=pending_strategy_flex_delta,
                spendable_rmd=spendable_rmd, standard_expenses=standard_expenses,
                original_expenses=original_expenses, cf_expenses=cf_expenses)

        # ---------------------------------------------------------------
        # 10. Waterfall or drawdown
        # ---------------------------------------------------------------
        tax_target_blended = _waterfall_or_drawdown(
            cash, pre_waterfall_contributions=pre_waterfall_contributions, specific_drawdowns=specific_drawdowns,
            qcd_withdrawals=qcd_withdrawals, taxable_dividends=taxable_dividends,
            taxable_bond_interest=taxable_bond_interest, blend_drawdown=blend_drawdown)

        # ---------------------------------------------------------------
        # 10a. Growth earned by contributions made throughout the year
        # ---------------------------------------------------------------
        cash_flow_timing_investment_growth = _contribution_timing_growth(
            state, plan_data, year, year_fraction, contributions_for_growth=contributions_for_growth,
            payroll_contributions=payroll_contributions, annual_account_rates=annual_account_rates,
            annual_income_composition=annual_income_composition, milestone_map=milestone_map,
            newly_triggered=newly_triggered, spend_leftover_mode=spend_leftover_mode,
            cf_income_sources=cf_income_sources, cf_contributions=cash.cf_contributions)

        # ---------------------------------------------------------------
        # 10b. Retry funding expenses left unfunded
        # ---------------------------------------------------------------
        _recover_unfunded_expenses(cash)

        # ---------------------------------------------------------------
        # 10c. Tax settlement, then leftover spending
        # ---------------------------------------------------------------
        # Reconcile actual tax with ALL payments, including withholding from
        # distributions. A refund is real cash; a bill must be funded or owed.
        _settle_year_tax(
            cash, conversion_rules, defer_conversions=defer_conversions, tax_settlement_cash=tax_settlement_cash,
            estimated_tax_cash=estimated_tax_cash, missing_rule_rate_years=missing_rule_rate_years)
        # A conversion trial restores the warnings along with the rest of the year.
        coverage_warnings = cash.coverage_warnings
        # Leftover cash held through settlement: spend the share the leftover
        # multiplier allows (never more than is held), save the rest.
        leftover_spent, cash.net_cash, standard_expenses, original_expenses = _spend_or_save_leftover(
            state, plan_data, flex_mult=flex_mult, net_cash=cash.net_cash, standard_expenses=standard_expenses,
            original_expenses=original_expenses, cf_expenses=cf_expenses, cf_contributions=cash.cf_contributions)
        # Leftover spending is added to planned and actual alike, and a flexed
        # income-plus-withdrawal amount is booked after this point.
        flex_net = planned_flex_net - pending_strategy_flex_delta
        flex_spending_increase = max(0.0, -flex_net) if flex_net < -1e-9 else 0.0
        flex_spending_reduction = 0.0 if flex_spending_increase > 0.0 else flex_net

        if state.hsa_taxable_distributions_this_year > 0:
            coverage_warnings.add("HSA withdrawals beyond the year's modeled medical costs are taxed as income, plus 20% before 65.")
        if state.education_taxable_earnings_this_year > 0:
            coverage_warnings.add("529 withdrawals beyond the year's qualified education expenses are taxed on their earnings share as income, plus a 10% additional tax. Mark education expenses as qualified or fund them from the 529 to keep withdrawals tax free.")
        if tax_settings.get("state_529_deduction") and state.education_contributions_this_year > 0 \
                and not state_deduction_supported(resolved_state_code):
            coverage_warnings.add(f"A state deduction for 529 contributions is not modeled for {resolved_state_code or 'this plan'}; no deduction was taken.")
        if cash.tax_result.ira_nondeductible_contributions > .005:
            coverage_warnings.add("Traditional IRA contributions were only partly deductible because of the workplace-plan income phase-out; the full contribution is still deposited. The after-tax basis this leaves in the traditional IRA is not tracked, so later withdrawals and conversions tax it again.")
        state.capital_loss_carryforward = cash.tax_result.capital_loss_carryforward
        cash_flow_timing_investment_growth += state.withdrawal_growth_adjustment

        # ---------------------------------------------------------------
        # 10d. Commit DAF carryforward based on final contribution limits
        # ---------------------------------------------------------------
        # Current gifts use the limit first, then oldest carryovers. Electing
        # the standard deduction does not preserve otherwise usable amounts.
        charitable_result = _limit_charitable_deduction(charitable_result, cash.tax_result.modified_agi, year)
        state.daf_carryforward = charitable_result.committed_carryforward
        state.capital_gain_gift_carryforward = charitable_result.committed_property_carryforward

        # ---------------------------------------------------------------
        # 11. Inflate for next year. Blank earned-income growth follows the
        # wage-growth curve, or this year's inflation when no curve is set.
        # ---------------------------------------------------------------
        federal_inflation_factor, social_security_inflation_factor, year_inflation_factor = _inflate_for_next_year(
            state, plan_data, year, year_fraction, override_returns=override_returns, curves=curves,
            default_inflation=default_inflation, federal_inflation_factor=federal_inflation_factor,
            social_security_inflation_factor=social_security_inflation_factor,
            income_scheduled_amounts=income_scheduled_amounts, income_growth_factors=income_growth_factors)

        # ---------------------------------------------------------------
        # 12. Snapshot
        # ---------------------------------------------------------------
        year_regime = cash.tax_result.regime if intl_year else None
        final_regime_inputs = year_regime.inputs if year_regime is not None else None
        snapshot, estimated_tax_prior = _year_snapshot(
            cash, year_regime=year_regime,
            expenses=(payroll_expenses + standard_expenses + specific_funded_expenses + asset_carrying_costs
                      + total_liability_payments + charitable_total + qcd_total
                      + rental_operating_expenses + real_estate_purchase_cash),
            investment_growth=total_end - total_start + cash_flow_timing_investment_growth,
            rmd_total=rmd_total, roth_rmd_income=roth_rmd_income, rental_cash_income=rental_cash_income,
            nontaxable_income=nontaxable_income, employer_contribution_income=employer_contribution_income,
            real_estate_purchase_cash=real_estate_purchase_cash, cf_income_sources=cf_income_sources,
            cf_expenses=cf_expenses, cf_payroll_expenses=cf_payroll_expenses, payroll_deductions=payroll_deductions,
            payroll_retirement_by_account=payroll_retirement_by_account,
            nj_employer_403b_by_account=nj_employer_403b_by_account,
            flex_spending_reduction=flex_spending_reduction, flex_spending_increase=flex_spending_increase,
            leftover_spent=leftover_spent, newly_triggered=newly_triggered,
            ss_earnings_test_withheld=ss_earnings_test_withheld, ss_withheld_by_earner=ss_withheld_by_earner,
            tax_target_room=tax_target_room,
            tax_target_blended=tax_target_blended, bond_allocation_by_account=bond_allocation_by_account,
            strategy_spent=strategy_spent, planned_for_year=planned_for_year,
            year_inflation_factor=year_inflation_factor, liquid_excluded_ids=liquid_excluded_ids,
            coverage_warnings=coverage_warnings, healthcare_warning_set=healthcare_warning_set)
        timeline.append(snapshot)
        if country_accounts:
            intl_accounts.finish_year(state)
        regime_prior = (year_country, year_regime.raw) if year_regime is not None else None
        prior_w2_by_owner = _record_year_history(
            cash, snapshot, aca_magi_history=aca_magi_history, rental_cash_income=rental_cash_income)

    # --- Estate tax / net legacy at end of life ---
    net_legacy_result, last_year = _net_legacy_at_end(
        plan_data, state, start_year=start_year, end_year=end_year,
        calendar_inflation=calendar_inflation, regime_plan=regime_plan, final_regime=final_regime,
        regime_context=regime_context if regime_plan else None, default_inflation=default_inflation,
        final_regime_inputs=final_regime_inputs)

    # --- Build result ---
    success = state.failure_year is None
    warnings = _result_warnings(
        plan_data, state, coverage_warnings=coverage_warnings,
        missing_target_rate_years=missing_target_rate_years, plan_tax_target=plan_tax_target,
        missing_rule_rate_years=missing_rule_rate_years, opening_ytd_imputed=opening_ytd_imputed,
        provided_ytd=provided_ytd, purchase_positions=purchase_positions,
        used_historical_yields=used_historical_yields, used_assumed_yield_fallback=used_assumed_yield_fallback,
        timeline=timeline, healthcare_warning_set=healthcare_warning_set, survivor_context=survivor_context,
        spousal_workers=spousal_workers, plan_milestone_ids=plan_milestone_ids,
    )
    metadata = SimMetadata(
        plan_id=uuid.UUID(plan_data.plan_id) if not isinstance(plan_data.plan_id, uuid.UUID) else plan_data.plan_id,
        start_year=start_year,
        end_year=last_year,
        start_date=start_date,
        first_year_fraction=plan_data.first_year_fraction,
        success=success,
        failure_year=state.failure_year,
        net_legacy=net_legacy_result,
        rmd_start_age=(rmd_start_age_override(plan_data.tax_settings, "self")
                       or get_rmd_start_age(plan_data.birth_year)),
        milestone_outcomes=[
            MilestoneOutcome(
                id=ms.id, name=ms.name, trigger_type=ms.trigger_type,
                year=state.triggered_milestone_years.get(ms.id),
                missed_year=state.missed_milestone_years.get(ms.id),
            )
            for ms in original_milestones
        ],
        fi_estimate=fi_estimate,
        warnings=warnings,
    )

    yearly_snapshots = [_snapshot_schema(s) for s in timeline]
    # Engine-only liquidity input for Monte Carlo and earnings-test attribution
    # for the claiming explorer; not part of the wire format.
    # One schema snapshot was built from each timeline snapshot.
    for schema_snapshot, s in zip(yearly_snapshots, timeline, strict=True):
        schema_snapshot._locked_account_ids = s.locked_account_ids
        schema_snapshot._liquid_excluded_account_ids = s.liquid_excluded_account_ids
        schema_snapshot._ss_earnings_test_withheld_by_earner = s.ss_earnings_test_withheld_by_earner

    return SimulationResult(metadata=metadata, initial_snapshot=initial_snapshot, yearly_snapshots=yearly_snapshots)

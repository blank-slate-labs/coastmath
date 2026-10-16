"""Opt-in calendar-year-end household longevity and surviving-owner transitions.

This annual convention is an explicit planning assumption, not an actual death
month or eligibility determination. Legacy timing is retained when omitted.
"""

from __future__ import annotations

from coastmath.engine.account_types import EMPLOYER_PLAN_TYPES
from coastmath.engine.estate_tax import step_up_joint_accounts
from coastmath.engine.residency import resolve_state_for_year
from coastmath.engine.types import _TAXABLE_TYPES, PlanData, SimState

LEGACY = "legacy_primary_endpoint"
LAST_SURVIVOR = "last_survivor_calendar_year_end"


class UnsupportedLifecycleInput(ValueError):
    """An authored lifecycle needs successor treatment the engine cannot model."""


def enabled(plan: PlanData) -> bool:
    return bool(
        plan.estate_settings
        and plan.estate_settings.household_lifecycle == LAST_SURVIVOR
    )


def death_year(plan: PlanData, owner: str) -> int | None:
    if owner == "self":
        return plan.birth_year + plan.life_expectancy
    if (
        owner == "spouse"
        and plan.spouse_birth_year is not None
        and plan.spouse_life_expectancy is not None
    ):
        return plan.spouse_birth_year + plan.spouse_life_expectancy
    return None


def simulation_end_year(plan: PlanData) -> int:
    mode = plan.estate_settings.household_lifecycle if plan.estate_settings else LEGACY
    if mode not in {LEGACY, LAST_SURVIVOR}:
        raise ValueError("Unknown household lifecycle convention")
    primary = death_year(plan, "self")
    if mode == LEGACY:
        return primary
    if plan.spouse_birth_year is not None and plan.spouse_life_expectancy is None:
        raise ValueError("Last-survivor planning requires explicit spouse longevity")
    if plan.spouse_life_expectancy is not None and (
        type(plan.spouse_life_expectancy) is not int
        or not 50 <= plan.spouse_life_expectancy <= 120
    ):
        raise ValueError("Spouse longevity must be an explicit age from 50 to 120")
    if plan.spouse_birth_year is None and (
        plan.spouse_life_expectancy is not None
        or plan.filing_status.startswith("married_")
        or any(a.owner == "spouse" for a in plan.accounts.values())
        or any(i.owner == "spouse" for i in plan.income_streams)
    ):
        raise ValueError(
            "Last-survivor planning requires the spouse birth year and longevity"
        )
    if plan.estate_settings.filing_status_after_death.startswith("married_"):
        raise ValueError(
            "Last-survivor planning requires an unmarried filing status after the first death"
        )
    spouse = death_year(plan, "spouse")
    endpoint = max(primary, spouse or primary) + 1
    if endpoint <= plan.start_year:
        raise ValueError("Household longevity ends before the projection starts")
    return endpoint


def longevity_end_month_index(plan: PlanData, owner: str) -> int | None:
    """Exclusive absolute month endpoint, January year Y == Y*12."""
    year = death_year(plan, owner)
    if year is None:
        return None
    if enabled(plan):
        return (year + 1) * 12
    if owner == "spouse":
        return year * 12 + (plan.spouse_birth_month or 1) - 1
    return year * 12


def owner_alive_until(plan: PlanData, state: SimState, owner: str, year: int) -> float:
    """Available portion of this calendar year, before first-year clipping."""
    if enabled(plan):
        endpoint = longevity_end_month_index(plan, owner)
        if owner == "joint":
            endpoint = simulation_end_year(plan) * 12
        return (
            1.0 if endpoint is None else max(0.0, min(1.0, (endpoint - year * 12) / 12))
        )
    if owner == "spouse" and state.partner_deceased:
        return (
            ((plan.spouse_birth_month or 1) - 1) / 12
            if year == state.partner_death_year
            else 0.0
        )
    return 1.0


def first_death_year(plan: PlanData) -> int | None:
    spouse = death_year(plan, "spouse")
    primary = death_year(plan, "self")
    return min(primary, spouse) if spouse is not None and spouse != primary else None


def apply_transitions(plan: PlanData, state: SimState, year: int) -> None:
    """Transfer at the January after first death, before growth/RMDs.

    Retain account IDs, balances and all Roth/inheritance history. Joint taxable
    basis steps up only with the opt-in ``joint_account_step_up``
    (coastmath.engine.estate_tax.step_up_joint_accounts).
    """
    if not enabled(plan):
        return
    for deceased, survivor in (("self", "spouse"), ("spouse", "self")):
        ended = death_year(plan, deceased)
        survivor_end = death_year(plan, survivor)
        flag = "primary_deceased" if deceased == "self" else "partner_deceased"
        if ended is None or year <= ended or getattr(state, flag):
            continue
        # Check the actual balance at succession: a ten-year inherited IRA may
        # have paid out completely many years before this owner's death.
        if survivor_end is not None and year <= survivor_end and any(
            a.owner == deceased and a.inherited_year is not None and a.balance > 0
            for a in state.accounts.values()
        ):
            raise UnsupportedLifecycleInput("Inherited-account successor beneficiary treatment is not supported")
        setattr(state, flag, True)
        if deceased == "spouse":
            state.partner_death_year = ended
        if survivor_end is None or year > survivor_end:
            continue
        step_up_joint_accounts(state, plan.estate_settings,
                               resolve_state_for_year(ended, state.triggered_milestones, plan))
        for account_id, account in state.accounts.items():
            if account.owner == deceased:
                # Ownership transfer does not establish employment in the
                # deceased person's employer plan for the surviving spouse.
                if account.account_type in EMPLOYER_PLAN_TYPES:
                    state.closed_employer_account_ids.add(account_id)
                if (
                    plan.estate_settings.step_up_basis_on_death
                    and account.account_type in _TAXABLE_TYPES
                ):
                    account.cost_basis = account.balance
                account.owner = survivor
            elif account.owner == "joint":
                account.owner = survivor
        state.roth_ledger = None
    first = first_death_year(plan)
    if first is not None and year > first:
        state.current_filing_status = plan.estate_settings.filing_status_after_death


def tax_ages(plan: PlanData, state: SimState, year: int) -> tuple[int, int | None]:
    if enabled(plan) and state.primary_deceased:
        return year - plan.spouse_birth_year, None
    spouse_age = (
        year - plan.spouse_birth_year
        if plan.spouse_birth_year is not None
        and (not state.partner_deceased or state.partner_death_year == year)
        else None
    )
    return year - plan.birth_year, spouse_age

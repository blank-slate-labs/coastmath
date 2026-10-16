"""Narrow opt-in survivor election for an already-claimed unreduced benefit.

SSA: https://www.ssa.gov/survivor/amount (benefits are not added together)
https://secure.ssa.gov/poms.nsf/lnx/0300615004 (survivor FRA cohorts)
https://www.ssa.gov/OP_Home/handbook/handbook.04/handbook-0407.html
(reduced-worker widow limit needs PIA, so that case is deliberately rejected).
This engine has month, not birth-day, precision; SSA day-one conventions are
not inferred. Eligibility/no disqualifying remarriage must be expressly supplied.

When both the deceased's and the survivor's benefits use PIA basis, the same
gate instead computes the widow(er)'s benefit from the PIAs
(``coastmath.engine.ss_household.survivor_monthly_benefit``): early claims, deaths
before claiming and the reduced-worker limit are then supported. It starts at
the later of the January after the death and the survivor's own claim month.
"""

from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise

from coastmath.engine.household_lifecycle import death_year, enabled, first_death_year
from coastmath.engine.social_security import full_retirement_age
from coastmath.engine.ss_household import (
    PIA_BASIS,
    expected_fraction,
    month_index,
    pia_record,
    survivor_monthly_benefit,
)
from coastmath.engine.types import IncomeData, PlanData

POLICY = "claimed_benefit_at_survivor_fra"


def survivor_fra_months(birth_year: int) -> int:
    if birth_year <= 1939:
        return 65 * 12
    if birth_year <= 1944:
        return 65 * 12 + (birth_year - 1939) * 2
    if birth_year <= 1956:
        return 66 * 12
    return min(67 * 12, 66 * 12 + (birth_year - 1956) * 2)


@dataclass(frozen=True)
class SurvivorContext:
    deceased: IncomeData
    own: IncomeData | None
    recipient: str
    start_month_index: int
    end_month_index: int
    # PIA basis: the survivor benefit in plan-start dollars, grown with the
    # deceased stream's COLA. None uses the deceased stream's amount.
    pia_annual: float | None = None


def prepare_survivor_policy(plan: PlanData) -> SurvivorContext | None:
    estate = plan.estate_settings
    policy = estate.survivor_social_security_policy if estate else "off"
    if policy == "off":
        return None
    if policy != POLICY or not enabled(plan):
        raise ValueError(
            "Survivor Social Security requires the explicit last-survivor lifecycle and supported policy"
        )
    if (
        estate.survivor_social_security_eligibility_confirmed is not True
        or not (estate.survivor_social_security_eligibility_source or "").strip()
    ):
        raise ValueError(
            "Survivor Social Security eligibility, including remarriage restrictions, requires explicit source confirmation"
        )
    first = first_death_year(plan)
    if first is None:
        return None
    deceased = "self" if death_year(plan, "self") == first else "spouse"
    recipient = "spouse" if deceased == "self" else "self"
    birthdays = {
        "self": (plan.birth_year, plan.birth_month),
        "spouse": (plan.spouse_birth_year, plan.spouse_birth_month),
    }
    if any(year is None or month is None for year, month in birthdays.values()):
        raise ValueError(
            "Survivor Social Security requires both birth years and months"
        )
    streams = [
        i for i in plan.income_streams
        if i.is_social_security and i.is_active and i.ss_worker_income_id is None
    ]
    if any(i.owner not in birthdays for i in streams):
        raise ValueError("Social Security stream owner is ambiguous")
    deceased_streams = [i for i in streams if i.owner == deceased]
    own_streams = [i for i in streams if i.owner == recipient]
    if len(deceased_streams) != 1 or len(own_streams) > 1:
        raise ValueError(
            "Survivor policy requires one active deceased benefit and at most one own benefit"
        )
    income = deceased_streams[0]
    own = own_streams[0] if own_streams else None
    pia_streams = [i for i in (income, own) if i is not None and i.ss_benefit_basis == PIA_BASIS]
    if pia_streams:
        if len(pia_streams) != 2:
            raise ValueError(
                "Survivor Social Security for a PIA-basis benefit requires both spouses' benefits to use PIA basis"
            )
        return _pia_context(plan, income, own, recipient, first, birthdays[recipient])
    milestone = next(
        (m for m in plan.milestones if m.id == income.start_milestone_id), None
    )
    if (
        milestone is None
        or milestone.trigger_type != "date"
        or not milestone.trigger_date
        or income.end_milestone_id
    ):
        raise ValueError(
            "Deceased benefit must have an explicit deterministic claim date and no ambiguous end event"
        )
    claim_year = int(milestone.trigger_date[:4])
    claim_month = income.start_month or int(milestone.trigger_date[5:7])
    claim_index = claim_year * 12 + claim_month - 1
    birth_year, birth_month = birthdays[deceased]
    fra = (
        birth_year * 12 + birth_month - 1 + round(full_retirement_age(birth_year) * 12)
    )
    if claim_index < fra:
        raise ValueError(
            "Early-claimed deceased benefit requires PIA and widow-limit evidence; unsupported by claimed-benefit policy"
        )
    if claim_index >= (first + 1) * 12:
        raise ValueError(
            "Unclaimed deceased benefit requires separate survivor award evidence"
        )
    own_birth_year, own_birth_month = birthdays[recipient]
    survivor_start = (
        own_birth_year * 12 + own_birth_month - 1 + survivor_fra_months(own_birth_year)
    )
    return SurvivorContext(
        income,
        own_streams[0] if own_streams else None,
        recipient,
        max((first + 1) * 12, survivor_start),
        (death_year(plan, recipient) + 1) * 12,
    )


def _pia_context(
    plan: PlanData,
    deceased: IncomeData,
    own: IncomeData,
    recipient: str,
    first: int,
    recipient_birth: tuple[int, int],
) -> SurvivorContext:
    milestones = {m.id: m for m in plan.milestones}
    deceased_record = pia_record(plan, deceased, milestones)
    own_record = pia_record(plan, own, milestones)
    # Lifecycle deaths fall at calendar year end; benefits start next January
    # or at the survivor's own claim month, whichever is later.
    death_index = month_index(first, 12)
    start = max((first + 1) * 12, own_record.claim_index)
    monthly = survivor_monthly_benefit(
        deceased_record,
        month_index(*recipient_birth),
        survivor_fra_months(recipient_birth[0]),
        death_index,
        start,
    )
    return SurvivorContext(
        deceased,
        own,
        recipient,
        start,
        (death_year(plan, recipient) + 1) * 12,
        pia_annual=monthly * 12.0 * expected_fraction(own),
    )


def grown_benefit(
    income: IncomeData, growth_factors: dict, inflation_factor: float,
    base: float | None = None,
) -> float:
    amount = (income.annual_amount if base is None else base) * growth_factors[income.id]
    if income.growth_cap is not None:
        amount = min(
            amount,
            income.growth_cap
            * (inflation_factor if income.growth_cap_inflation_linked else 1.0),
        )
    return amount


def survivor_top_up(
    context: SurvivorContext | None,
    *,
    year: int,
    year_fraction: float,
    growth_factors: dict,
    inflation_factor: float,
    own_overlap: Callable[[IncomeData, float, float], float],
    own_adjustment: Callable[[IncomeData, float, float], float] | None = None,
    adjusted_pia_annual: float | None = None,
    adjustment_month_index: int | None = None,
    own_adjustment_month_index: int | None = None,
    active_until: float = 1.0,
) -> float:
    if context is None:
        return 0.0
    start = max(1 - year_fraction, (context.start_month_index - year * 12) / 12, 0.0)
    end = min(1.0, active_until, (context.end_month_index - year * 12) / 12)
    fraction = max(0.0, end - start)
    if not fraction:
        return 0.0
    boundaries = [start, end]
    for boundary in (adjustment_month_index, own_adjustment_month_index):
        if boundary is not None:
            adjustment = (boundary - year * 12) / 12
            if start < adjustment < end:
                boundaries.append(adjustment)
    boundaries = sorted(set(boundaries))
    total = 0.0
    for beginning, ending in pairwise(boundaries):
        base = context.pia_annual
        if adjusted_pia_annual is not None and adjustment_month_index is not None and year * 12 + beginning * 12 >= adjustment_month_index:
            base = adjusted_pia_annual
        deceased = grown_benefit(context.deceased, growth_factors, inflation_factor, base)
        own_amount = grown_benefit(context.own, growth_factors, inflation_factor) if context.own else 0.0
        overlap = own_overlap(context.own, beginning, ending) if context.own else 0.0
        extra = own_adjustment(context.own, beginning, ending) if context.own and own_adjustment else 0.0
        own_offset = min(deceased * overlap, own_amount * overlap + extra)
        total += max(0.0, deceased * (ending - beginning) - own_offset)
    return total


def survivor_arf_annual(plan: PlanData, context: SurvivorContext | None, credited_months: int) -> tuple[int, float] | None:
    """Recompute the survivor reduction from credited months, preserving the widow limit."""
    if context is None or context.pia_annual is None or not context.own or credited_months <= 0:
        return None
    birth = (plan.spouse_birth_year, plan.spouse_birth_month) if context.recipient == 'spouse' else (plan.birth_year, plan.birth_month)
    birth_index = month_index(birth[0], birth[1] or 1)
    fra_months = survivor_fra_months(birth[0])
    fra = birth_index + fra_months
    if context.start_month_index >= fra:
        return None
    record = pia_record(plan, context.deceased, {m.id:m for m in plan.milestones})
    first = first_death_year(plan)
    monthly = survivor_monthly_benefit(record, birth_index, fra_months, month_index(first, 12), min(fra, context.start_month_index + credited_months))
    return fra, monthly * 12 * expected_fraction(context.own)

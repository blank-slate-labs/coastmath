"""Social Security benefits sized from a monthly PIA, with household rules.

A Social Security stream with ``ss_benefit_basis == "pia"`` carries the
recipient's monthly primary insurance amount (PIA) at full retirement age in
plan-start dollars. Before the yearly loop, ``apply_pia_benefits``:

- replaces the stream's ``annual_amount`` with its own retirement benefit,
  ``PIA x 12 x claiming factor x expected percent``. The claiming factor uses
  the stream's actual first payment month (its resolved start milestone and
  start month), so the factor always matches when benefits begin. The yearly
  loop then grows it from plan start with the stream's Social Security COLA
  and prorates the claim year, exactly as for an amount-basis stream;
- adds one synthetic spousal-excess stream per eligible spouse when both
  spouses have one active PIA-basis stream. The excess is
  ``max(0, 50% x other PIA - own PIA)``, begins at the later of the two claim
  months (deemed filing: own and spousal start together, but never before
  the worker files), is reduced for months before the recipient's full
  retirement age with no delayed credits, and ends with the recipient's own
  stream or at the worker's death.

Survivor benefits for PIA-basis couples are computed here but applied only
through the explicit survivor policy gate (``survivor_social_security``).

Rates: ``coastmath/data/social_security_household.json``; sources in
``_sources`` in ``social_security_household.json``. Month precision only: SSA's
birth-day conventions (for example, attaining an age the day before a
birthday) are not modeled. Divorced-spouse benefits are added by
``coastmath.engine.ss_divorced``; family maximum and child benefits are not
modeled. The annual earnings test is applied in the simulation loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from coastmath.engine.social_security import claiming_factor, full_retirement_age
from coastmath.engine.types import IncomeData, MilestoneData, PlanData

_RULES = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "social_security_household.json").read_text()
)
_SPOUSAL = _RULES["spousal"]
_SURVIVOR = _RULES["survivor"]

PIA_BASIS = "pia"


def month_index(year: int, month: int) -> int:
    return year * 12 + month - 1


def expected_fraction(income: IncomeData) -> float:
    pct = income.expected_benefit_percent
    return 1.0 if pct is None else max(0.0, min(100.0, pct)) / 100.0


def retirement_fra_index(birth_year: int, birth_index: int) -> int:
    return birth_index + round(full_retirement_age(birth_year) * 12)


def spousal_reduction_factor(months_early: int) -> float:
    """Spouse's benefit factor for months of entitlement before FRA."""
    months = max(0, months_early)
    return (
        1.0
        - min(months, 36) * _SPOUSAL["reduction_per_month_first_36"]
        - max(0, months - 36) * _SPOUSAL["reduction_per_month_beyond_36"]
    )


def survivor_reduction_factor(months_early: int, survivor_fra_months: int) -> float:
    """Widow(er)'s factor, falling linearly to 71.5% at age 60."""
    period = survivor_fra_months - _SURVIVOR["earliest_age_months"]
    if period <= 0:
        return 1.0
    months = max(0, min(months_early, period))
    return 1.0 - _SURVIVOR["total_reduction_at_earliest_age"] * months / period


@dataclass(frozen=True)
class PiaRecord:
    """One PIA-basis stream with its owner's birth and first payment month."""

    income: IncomeData
    birth_year: int
    birth_index: int
    claim_index: int

    @property
    def pia(self) -> float:
        return float(self.income.pia_monthly or 0.0)

    @property
    def claim_age(self) -> float:
        return (self.claim_index - self.birth_index) / 12.0

    @property
    def own_factor(self) -> float:
        return claiming_factor(self.claim_age, self.birth_year)

    @property
    def fra_index(self) -> int:
        return retirement_fra_index(self.birth_year, self.birth_index)


def owner_birth(plan: PlanData, owner: str) -> tuple[int, int]:
    if owner == "spouse":
        if plan.spouse_birth_year is None:
            raise ValueError("A PIA-basis spouse benefit requires the partner's birth year")
        return plan.spouse_birth_year, plan.spouse_birth_month or 1
    return plan.birth_year, plan.birth_month or 1


def claim_month_index(income: IncomeData, milestones: dict[str, MilestoneData]) -> int:
    """First payment month of a stream whose start milestone is a fixed date."""
    milestone = milestones.get(income.start_milestone_id or "")
    if milestone is None or milestone.trigger_type != "date" or not milestone.trigger_date:
        raise ValueError(
            f"{income.name}: a PIA-basis Social Security benefit needs a claiming age "
            "or a start milestone with a fixed date"
        )
    year = int(milestone.trigger_date[:4])
    return month_index(year, income.start_month or int(milestone.trigger_date[5:7]))


def pia_record(plan: PlanData, income: IncomeData, milestones: dict[str, MilestoneData]) -> PiaRecord:
    birth_year, birth_month = owner_birth(plan, income.owner)
    return PiaRecord(
        income, birth_year, month_index(birth_year, birth_month), claim_month_index(income, milestones)
    )


def own_annual_benefit(record: PiaRecord) -> float:
    """Own retirement benefit in plan-start dollars, before COLA."""
    return record.pia * 12.0 * record.own_factor * expected_fraction(record.income)


def spousal_terms(recipient: PiaRecord, worker: PiaRecord) -> tuple[int, float, int] | None:
    """(start month, annual excess in plan-start dollars, months of reduction)
    or None when no excess."""
    excess = _SPOUSAL["worker_pia_share"] * worker.pia - recipient.pia
    if excess <= 0 and not any(r.income.pia_reflects == "current_record" for r in (recipient, worker)):
        return None
    excess = max(0.0, excess)
    start = max(recipient.claim_index, worker.claim_index)
    fra = recipient.fra_index
    earliest = recipient.birth_index + _SPOUSAL["earliest_age_months"]
    months_early = max(0, min(fra - start, fra - earliest))
    annual = excess * 12.0 * spousal_reduction_factor(months_early) * expected_fraction(recipient.income)
    return start, annual, months_early


def survivor_monthly_benefit(
    deceased: PiaRecord,
    survivor_birth_index: int,
    survivor_fra_months: int,
    death_index: int,
    start_index: int,
) -> float:
    """Widow(er)'s monthly benefit in plan-start dollars, before any haircut.

    The deceased's PIA is deemed to include delayed credits: those already in
    a claimed benefit, or, when they died after FRA without claiming, those
    earned through the month before the month of death. A deceased who
    claimed early limits the benefit to the larger of their reduced benefit
    and 82.5% of PIA (Act 202(e)(2)(D)); that limit applies after the
    survivor's own age reduction.
    """
    pia = deceased.pia
    limit = None
    if deceased.claim_index <= death_index:
        benefit = pia * deceased.own_factor
        if benefit < pia:
            deemed = pia
            limit = max(benefit, _SURVIVOR["reduced_worker_limit_pia_share"] * pia)
        else:
            deemed = benefit
    else:
        entitlement = death_index - 1
        deemed = pia
        if entitlement > deceased.fra_index:
            deemed = pia * claiming_factor(
                (entitlement - deceased.birth_index) / 12.0, deceased.birth_year
            )
    survivor_fra = survivor_birth_index + survivor_fra_months
    widow = deemed * survivor_reduction_factor(survivor_fra - start_index, survivor_fra_months)
    return widow if limit is None else min(widow, limit)


def apply_pia_benefits(plan: PlanData) -> tuple[PlanData, dict[str, str]]:
    """Size PIA-basis streams and add spousal-excess streams.

    Call after deterministic milestones are resolved to dates. Returns the
    plan unchanged (and an empty mapping) when no stream uses PIA basis, so
    amount-basis plans are untouched. The mapping links each synthetic
    spousal stream id to its worker's stream id.
    """
    pia_streams = [
        i for i in plan.income_streams
        if i.is_social_security and i.ss_benefit_basis == PIA_BASIS and i.ss_worker_income_id is None
    ]
    if not pia_streams:
        return plan, {}
    milestones = {m.id: m for m in plan.milestones}
    records = {i.id: pia_record(plan, i, milestones) for i in pia_streams}
    streams = [
        replace(i, annual_amount=own_annual_benefit(records[i.id])) if i.id in records else i
        for i in plan.income_streams
    ]

    active = [records[i.id] for i in pia_streams if i.is_active]
    by_owner: dict[str, list[PiaRecord]] = {}
    for record in active:
        by_owner.setdefault(record.income.owner, []).append(record)
    if any(len(group) > 1 for group in by_owner.values()):
        raise ValueError("Each person can have only one active PIA-basis Social Security benefit")

    extra_milestones: list[MilestoneData] = []
    spousal_workers: dict[str, str] = {}
    if plan.spouse_birth_year is not None and set(by_owner) == {"self", "spouse"}:
        pair = (by_owner["self"][0], by_owner["spouse"][0])
        for recipient, worker in (pair, pair[::-1]):
            terms = spousal_terms(recipient, worker)
            if terms is None:
                continue
            start, annual, months_early = terms
            year, month0 = divmod(start, 12)
            source = recipient.income
            ms_id = f"{source.id}:spousal_start"
            extra_milestones.append(MilestoneData(
                id=ms_id, name=f"{source.name} spousal start",
                trigger_type="date", trigger_date=f"{year:04d}-{month0 + 1:02d}-01",
            ))
            spousal_id = f"{source.id}:spousal"
            streams.append(replace(
                source, id=spousal_id, name=f"{source.name} (spousal)", annual_amount=annual,
                start_milestone_id=ms_id, start_month=None, claiming_age=None,
                ss_benefit_basis="amount", pia_monthly=None, ss_worker_income_id=worker.income.id,
                ss_spousal_reduction=(spousal_id, months_early, annual, 0.0),
            ))
            spousal_workers[spousal_id] = worker.income.id
    return replace(
        plan, income_streams=streams, milestones=[*plan.milestones, *extra_milestones],
    ), spousal_workers

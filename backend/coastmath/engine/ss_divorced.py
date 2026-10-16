"""Divorced-spouse and surviving-divorced-spouse Social Security benefits.

A PIA-basis Social Security stream may carry one former spouse's record
(``IncomeData.ex_spouse``; schema ``coastmath.schemas.income.ExSpouseRecord``). The
former spouse is not a household member: only their PIA, birth, claim age and
death year are used. ``apply_divorced_benefits`` turns the record into
synthetic auxiliary streams linked to the claimant's own stream, the same way
``ss_household`` adds spousal-excess streams, so COLA, proration, the annual
earnings test (the claimant's own earnings), taxation and the snapshot treat
them like other Social Security payments.

Rules, by month (``coastmath/data/social_security_household.json``; sources in
``_sources`` in ``social_security_household.json``):

- Divorced spouse (Act 202(b)/(c), 20 CFR 404.331): marriage of at least 10
  years; the claimant is at least 62, unmarried and entitled to their own
  benefit (deemed filing: both start together); the former spouse is alive,
  at least 62, and either entitled or divorced for 2 continuous years. The
  amount is the excess of half the former spouse's PIA over the claimant's
  PIA, reduced for months before the claimant's full retirement age at first
  entitlement, with no delayed credits.
- Surviving divorced spouse (Act 202(e)/(f), 20 CFR 404.336): marriage of at
  least 10 years; from the January after the former spouse's death year, at
  60 or later, starting with the claimant's own claim unless the record sets
  a survivor claim age. The widow(er)'s benefit uses the deceased's PIA with
  delayed credits or the reduced-worker limit and the survivor reduction
  (``ss_household.survivor_monthly_benefit``). It is paid only above the
  claimant's own benefit. A current marriage bars it unless it began at 60
  or later.
- Marriage: the claimant is married while the year's filing status is a
  married status and the plan partner, if any, is alive. Filing-status
  changes (by year or fixed-date milestone) and the partner's death end or
  start a marriage; a marriage in place at the plan start began in the
  record's ``current_marriage_year`` (unknown means before 60).
- One auxiliary benefit at a time (Act 202(k)): in each month the payment is
  the excess of the larger divorced or surviving-divorced amount over the
  spousal excess or survivor top-up already paid from the plan partner. The
  comparison uses the spousal excess payable after the partner's
  earnings-test withholding (simulator).
- Earnings test: the claimant's own earnings withhold these streams with
  their own benefit. At full retirement age the divorced-spouse reduction is
  recomputed without the months withheld (Act 202(q)(7); POMS RS 00615.482),
  like the household spousal benefit.

Month precision; former-spouse deaths fall at calendar year end like the
household lifecycle. Family maximum, child benefits and several former
spouses are not modeled.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from coastmath.engine.household_lifecycle import longevity_end_month_index
from coastmath.engine.ss_household import (
    PIA_BASIS,
    PiaRecord,
    apply_pia_benefits,
    expected_fraction,
    month_index,
    own_annual_benefit,
    pia_record,
    spousal_reduction_factor,
    survivor_monthly_benefit,
)
from coastmath.engine.survivor_social_security import (
    prepare_survivor_policy,
    survivor_fra_months,
)
from coastmath.engine.types import IncomeData, MilestoneData, PlanData

_RULES = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "social_security_household.json").read_text()
)
_SPOUSAL = _RULES["spousal"]
_SURVIVOR = _RULES["survivor"]
_DIVORCED = _RULES["divorced"]

_NEVER = 10**9
_LIFESPAN_MONTHS = 125 * 12


def _filing_status_for_year(plan: PlanData):
    milestones = {m.id: m for m in plan.milestones}
    changes = []
    for index, change in enumerate(plan.filing_status_changes or []):
        year = change.get("year")
        if year is None:
            milestone = milestones.get(change.get("milestone_id") or "")
            if milestone is None or milestone.trigger_type != "date" or not milestone.trigger_date:
                raise ValueError(
                    "Divorced-spouse Social Security needs filing status changes at a fixed year or date"
                )
            year = int(milestone.trigger_date[:4])
        changes.append((int(year), index, change["filing_status"]))

    def status(year: int) -> str:
        applicable = [change for change in changes if change[0] <= year]
        return max(applicable)[2] if applicable else plan.filing_status

    return status


def _ex_record(ex: dict) -> PiaRecord:
    birth = month_index(ex["birth_year"], ex.get("birth_month") or 1)
    claim = birth + round(float(ex["claim_age"]) * 12) if ex.get("claim_age") is not None else _NEVER
    worker = IncomeData(
        id="former_spouse", name="Former spouse", annual_amount=0.0,
        tax_category="social_security", ss_benefit_basis=PIA_BASIS, pia_monthly=float(ex["pia_monthly"]),
    )
    return PiaRecord(worker, ex["birth_year"], birth, claim)


def _marriage_qualifies(ex: dict) -> bool:
    years = ex.get("marriage_years")
    return bool(ex.get("marriage_lasted_10_years")) or (
        years is not None and float(years) >= _DIVORCED["minimum_marriage_years"]
    )


def _divorced_streams(
    plan: PlanData, own: IncomeData, milestones: dict[str, MilestoneData],
) -> tuple[list[IncomeData], list[MilestoneData]]:
    ex = own.ex_spouse or {}
    if not _marriage_qualifies(ex):
        return [], []
    record = pia_record(plan, own, milestones)
    status = _filing_status_for_year(plan)
    partner = "spouse" if own.owner == "self" else "self"
    partner_end = (
        longevity_end_month_index(plan, partner) if plan.spouse_birth_year is not None else None
    )

    def married(month: int) -> bool:
        if partner_end is not None and month >= partner_end:
            return False
        return status(month // 12).startswith("married_")

    def marriage_start(month: int) -> int | None:
        year = month // 12
        while year > plan.start_year and married((year - 1) * 12 + 11):
            year -= 1
        if year <= plan.start_year:
            began = ex.get("current_marriage_year")
            return None if began is None else int(began) * 12
        return year * 12

    birth = record.birth_index
    claim = record.claim_index
    worker = _ex_record(ex)
    death_year = ex.get("death_year")
    worker_alive_until = (int(death_year) + 1) * 12 if death_year is not None else _NEVER
    divorce = month_index(ex["divorce_year"], ex.get("divorce_month") or 12)
    independent = divorce + _DIVORCED["independent_entitlement_months"]
    worker_eligible = worker.birth_index + _DIVORCED["worker_earliest_age_months"]
    survivor_from = (
        birth + round(float(ex["survivor_claim_age"]) * 12)
        if ex.get("survivor_claim_age") is not None else claim
    )

    def divorced_ok(month: int) -> bool:
        return (
            month >= claim
            and month >= birth + _SPOUSAL["earliest_age_months"]
            and divorce <= month < worker_alive_until
            and month >= worker_eligible
            and (month >= worker.claim_index or month >= independent)
            and not married(month)
        )

    def survivor_ok(month: int) -> bool:
        if death_year is None or month < worker_alive_until:
            return False
        if month < birth + _SURVIVOR["earliest_age_months"] or month < survivor_from:
            return False
        if married(month):
            began = marriage_start(month)
            return began is not None and began - birth >= _DIVORCED["survivor_remarriage_age_months"]
        return True

    # Auxiliary benefits already paid from the plan partner's record.
    spousal = next((i for i in plan.income_streams if i.id == f"{own.id}:spousal"), None)
    spousal_start = _NEVER
    if spousal is not None:
        start_ms = milestones.get(spousal.start_milestone_id or "")
        if start_ms is not None and start_ms.trigger_date:
            spousal_start = month_index(int(start_ms.trigger_date[:4]), int(start_ms.trigger_date[5:7]))
    spousal_end = partner_end if partner_end is not None else _NEVER
    context = prepare_survivor_policy(plan)
    if context is not None and context.recipient != own.owner:
        context = None
    own_annual = own_annual_benefit(record)
    survivor_top_up = (
        max(0.0, context.pia_annual - own_annual) if context is not None and context.pia_annual is not None else 0.0
    )

    end = longevity_end_month_index(plan, own.owner) or birth + _LIFESPAN_MONTHS
    begin = min(claim, survivor_from)
    windows: list[tuple[int, int, tuple]] = []
    for month in range(begin, end):
        key = (
            divorced_ok(month),
            survivor_ok(month),
            spousal_start <= month < spousal_end,
            context is not None and context.start_month_index <= month < context.end_month_index,
            month >= claim,
        )
        if not (key[0] or key[1]):
            continue
        if windows and windows[-1][1] == month and windows[-1][2] == key:
            windows[-1] = (windows[-1][0], month + 1, key)
        else:
            windows.append((month, month + 1, key))
    if not windows:
        return [], []

    expected = expected_fraction(own)
    first_divorced = next((w[0] for w in windows if w[2][0]), None)
    divorced_annual = 0.0
    early = 0
    if first_divorced is not None:
        excess = max(0.0, _SPOUSAL["worker_pia_share"] * worker.pia - record.pia)
        early = max(0, record.fra_index - first_divorced)
        divorced_annual = excess * 12.0 * spousal_reduction_factor(early) * expected
    first_survivor = next((w[0] for w in windows if w[2][1]), None)
    survivor_annual = 0.0
    if first_survivor is not None:
        survivor_annual = 12.0 * expected * survivor_monthly_benefit(
            worker, birth, survivor_fra_months(record.birth_year),
            month_index(int(death_year), 12), first_survivor,
        )

    streams: list[IncomeData] = []
    extra_milestones: list[MilestoneData] = []
    for index, (start, stop, key) in enumerate(windows):
        is_divorced, is_survivor, spousal_on, survivor_on, own_on = key
        candidate = divorced_annual if is_divorced else max(
            0.0, survivor_annual - (own_annual if own_on else 0.0)
        )
        paid = spousal.annual_amount if spousal_on and spousal is not None else survivor_top_up if survivor_on else 0.0
        stream_id = f"{own.id}:divorced:{index}"
        # The divorced-spouse reduction is adjusted at FRA for withheld months;
        # its windows are one entitlement and share those months.
        reduction = (f"{own.id}:divorced", early, candidate, paid) if is_divorced and early else None
        # Only spousal withholding (the partner's earnings) is not shared
        # proportionally with this stream, so only it changes the comparison.
        offset = (spousal.id, candidate, paid) if spousal_on and spousal is not None and paid > 0 else None
        label = "divorced spouse" if is_divorced else "surviving divorced spouse"
        start_id = f"{stream_id}:start"
        year, month0 = divmod(start, 12)
        extra_milestones.append(MilestoneData(
            id=start_id, name=f"{own.name} {label} start",
            trigger_type="date", trigger_date=f"{year:04d}-{month0 + 1:02d}-01",
        ))
        end_id, end_month = own.end_milestone_id, own.end_month
        if stop < end:
            end_id, end_month = f"{stream_id}:end", None
            year, month0 = divmod(stop, 12)
            extra_milestones.append(MilestoneData(
                id=end_id, name=f"{own.name} {label} end",
                trigger_type="date", trigger_date=f"{year:04d}-{month0 + 1:02d}-01",
            ))
        streams.append(replace(
            own, id=stream_id, name=f"{own.name} ({label})", annual_amount=max(0.0, candidate - paid),
            start_milestone_id=start_id, start_month=None, end_milestone_id=end_id, end_month=end_month,
            claiming_age=None, ss_benefit_basis="amount", pia_monthly=None, ss_worker_income_id=own.id,
            ex_spouse=None, growth_schedule=None, ss_spousal_reduction=reduction, ss_aux_offset=offset,
        ))
    return streams, extra_milestones


def apply_divorced_benefits(
    plan: PlanData, linked: dict[str, str],
) -> tuple[PlanData, dict[str, str]]:
    """Add divorced and surviving-divorced streams after ``apply_pia_benefits``.

    Returns the plan unchanged when no active PIA-basis stream has a former
    spouse's record. The mapping gains each synthetic stream's own stream id.
    """
    claimants = [
        i for i in plan.income_streams
        if i.ex_spouse and i.is_active and i.is_social_security
        and i.ss_benefit_basis == PIA_BASIS and i.ss_worker_income_id is None
    ]
    if not claimants:
        return plan, linked
    milestones = {m.id: m for m in plan.milestones}
    streams: list[IncomeData] = []
    extra: list[MilestoneData] = []
    for own in claimants:
        added, added_milestones = _divorced_streams(plan, own, milestones)
        streams.extend(added)
        extra.extend(added_milestones)
    if not streams:
        return plan, linked
    return replace(
        plan, income_streams=[*plan.income_streams, *streams], milestones=[*plan.milestones, *extra],
    ), {**linked, **{s.id: s.ss_worker_income_id for s in streams}}


def apply_household_benefits(plan: PlanData) -> tuple[PlanData, dict[str, str]]:
    """PIA sizing, spousal excess, then divorced-spouse streams."""
    return apply_divorced_benefits(*apply_pia_benefits(plan))

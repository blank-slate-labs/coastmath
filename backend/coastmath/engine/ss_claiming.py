"""Social Security claiming-age explorer.

Varies when each person claims their own US Social Security benefit and runs
the whole plan once per combination: whole-year ages 62 through 70, claimed
in the person's birth month. One adjustable person gives a sweep with the
other person as planned; two give the full cross product (at most 81 runs).
The plan as it is runs once more as the "current" point at its real
(possibly fractional) claim ages.

A run changes only the varied streams: the claiming age is set and the start
milestone and start month are cleared, so the claim month is the birth month
at that age. An ``"amount"`` basis benefit is rescaled by the ratio of the
claiming factors at the new and current ages; a ``"pia"`` basis benefit is
sized by the engine from the claim month, with spousal, survivor and
divorced-spouse benefits following the new dates. Nothing else changes.

Runs are ranked by end net worth with pre-tax balances after income tax at
``pre_tax_discount_rate``, as the tax suggestions rank them; successful runs
first. Household Social Security comes from each year's cash-flow income
sources, after the earnings test. A person's ``earnings_test_withholds`` is set
when the earnings test, counting that person's earnings, withholds benefits in
any run (the current plan or a candidate).
"""

from __future__ import annotations

import copy
import datetime
from dataclasses import dataclass, field, replace

from coastmath.engine.milestones import (
    resolve_deterministic_milestones,
    with_social_security_claiming,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.social_security import claiming_factor, full_retirement_age
from coastmath.engine.ss_divorced import apply_household_benefits
from coastmath.engine.ss_household import month_index
from coastmath.engine.tax_strategy import pre_tax_discount, pre_tax_discount_rate
from coastmath.engine.types import IncomeData, PlanData
from coastmath.schemas.simulation import SimulationResult

CLAIM_AGES = tuple(range(62, 71))
# Cash-flow income source name of the survivor top-up (coastmath.engine.simulator).
SURVIVOR_TOP_UP = "Social Security survivor top-up"

# Machine-readable reasons a person's claiming age is not varied.
NO_BENEFIT = "no_benefit"
MULTIPLE_BENEFITS = "multiple_benefits"
ALREADY_CLAIMED = "already_claimed"
UNRESOLVED_CLAIM_DATE = "unresolved_claim_date"
MISSING_BIRTH_YEAR = "missing_birth_year"
NO_CANDIDATE_AGES = "no_candidate_ages"


@dataclass
class ClaimingPerson:
    owner: str
    adjustable: bool
    reason: str | None = None
    income_id: str | None = None
    birth_year: int | None = None
    birth_month: int = 1
    full_retirement_age: float | None = None
    current_claim_age: float | None = None
    candidate_ages: list[int] = field(default_factory=list)
    benefit_basis: str | None = None
    #: The earnings test, counting this person's earnings, withholds benefits
    #: before full retirement age in at least one run.
    earnings_test_withholds: bool = False


@dataclass
class ClaimingRun:
    #: Claim age by adjustable owner ("self"/"spouse").
    claim_ages: dict[str, float]
    #: Own retirement benefit at claim by adjustable owner, annual, plan-start dollars.
    first_year_benefits: dict[str, float]
    #: Household Social Security received in each projection year, nominal.
    social_security_by_year: list[float]
    lifetime_social_security: float
    lifetime_taxes: float
    end_net_worth: float
    end_net_worth_after_tax: float
    success: bool
    failure_year: int | None
    #: This run minus the current run.
    end_net_worth_after_tax_change: float = 0.0
    lifetime_social_security_change: float = 0.0


@dataclass
class ClaimingPatch:
    """Income-stream fields to save through the income update route to adopt ``claiming_age``."""
    owner: str
    claiming_age: int
    income_id: str
    changes: dict


@dataclass
class ClaimingExploration:
    persons: list[ClaimingPerson]
    years: list[int] = field(default_factory=list)
    current: ClaimingRun | None = None
    runs: list[ClaimingRun] = field(default_factory=list)
    best_index: int | None = None
    best_end_net_worth_after_tax_change: float | None = None
    best_lifetime_social_security_change: float | None = None
    pre_tax_discount_rate: float = 0.0
    patches: list[ClaimingPatch] = field(default_factory=list)


@dataclass
class _Adjustable:
    person: ClaimingPerson
    income: IncomeData


def first_month_index(plan: PlanData) -> int:
    """Month index of the plan's first simulated month (as the simulator dates it)."""
    next_year = datetime.date(plan.start_year + 1, 1, 1)
    days = (next_year - datetime.date(plan.start_year, 1, 1)).days
    start = next_year - datetime.timedelta(days=round(days * plan.first_year_fraction))
    return month_index(start.year, start.month)


def _birth(plan: PlanData, owner: str) -> tuple[int | None, int]:
    if owner == "spouse":
        return plan.spouse_birth_year, plan.spouse_birth_month or 1
    return plan.birth_year, plan.birth_month or 1


def current_claim_index(plan: PlanData, income: IncomeData) -> int | None:
    """First payment month of ``income`` as the simulator resolves it, or None.

    None when the stream has no fixed claim date: a start milestone that is
    switched off, never resolves, or depends on simulated balances. A stream
    with neither a claiming age nor a start milestone pays from plan start.
    """
    if income.start_milestone_id is None and income.claiming_age is None:
        return first_month_index(plan)
    prepared = with_social_security_claiming(plan)
    stream = next(i for i in prepared.income_streams if i.id == income.id)
    try:
        milestones = resolve_deterministic_milestones(prepared.milestones, plan.birth_year, plan.birth_month)
    except ValueError:
        return None
    milestone = next((m for m in milestones if m.id == stream.start_milestone_id), None)
    if milestone is None or milestone.trigger_type != "date" or not milestone.trigger_date:
        return None
    return month_index(int(milestone.trigger_date[:4]), stream.start_month or int(milestone.trigger_date[5:7]))


def _person(plan: PlanData, owner: str, first_index: int) -> tuple[ClaimingPerson, _Adjustable | None]:
    birth_year, birth_month = _birth(plan, owner)
    person = ClaimingPerson(owner=owner, adjustable=False, birth_year=birth_year, birth_month=birth_month,
                            full_retirement_age=full_retirement_age(birth_year) if birth_year else None)
    streams = [i for i in plan.income_streams
               if i.is_social_security and i.is_active and i.owner == owner and i.ss_worker_income_id is None]
    if not streams:
        person.reason = NO_BENEFIT
        return person, None
    if len(streams) > 1:
        person.reason = MULTIPLE_BENEFITS
        return person, None
    income = streams[0]
    person.income_id, person.benefit_basis = income.id, income.ss_benefit_basis
    if birth_year is None:
        person.reason = MISSING_BIRTH_YEAR
        return person, None
    birth_index = month_index(birth_year, birth_month)
    claim_index = current_claim_index(plan, income)
    if claim_index is None:
        person.reason = UNRESOLVED_CLAIM_DATE
        return person, None
    if claim_index <= first_index:
        person.reason = ALREADY_CLAIMED
        return person, None
    person.current_claim_age = (claim_index - birth_index) / 12.0
    person.candidate_ages = [age for age in CLAIM_AGES if birth_index + age * 12 >= first_index]
    if not person.candidate_ages:
        person.reason = NO_CANDIDATE_AGES
        return person, None
    person.adjustable = True
    return person, _Adjustable(person, income)


def _rescaled_amount(adjustable: _Adjustable, age: int) -> float | None:
    """Amount-basis annual benefit at ``age`` in the stored unit (cents), else None."""
    if adjustable.income.ss_benefit_basis == "pia":
        return None
    birth_year = adjustable.person.birth_year
    ratio = (claiming_factor(age, birth_year)
             / claiming_factor(adjustable.person.current_claim_age, birth_year))
    return round(adjustable.income.annual_amount * ratio, 2)


def claim_changes(adjustable: _Adjustable, age: int) -> dict:
    changes: dict = {"claiming_age": age, "start_milestone_id": None, "start_month": None}
    amount = _rescaled_amount(adjustable, age)
    if amount is not None:
        changes["annual_amount"] = amount
    return changes


def with_claims(plan: PlanData, claims: dict[str, tuple[_Adjustable, int]]) -> PlanData:
    """A deep copy of ``plan`` with each varied stream claiming at its age."""
    scenario = copy.deepcopy(plan)
    by_id = {adjustable.income.id: claim_changes(adjustable, age) for adjustable, age in claims.values()}
    scenario.income_streams = [replace(i, **by_id[i.id]) if i.id in by_id else i for i in scenario.income_streams]
    return scenario


def _household_streams(plan: PlanData) -> list[IncomeData]:
    """Income streams after the simulator's claiming and household preparation."""
    prepared = with_social_security_claiming(plan)
    prepared = replace(prepared, milestones=resolve_deterministic_milestones(
        prepared.milestones, prepared.birth_year, prepared.birth_month))
    return apply_household_benefits(prepared)[0].income_streams


def _run(plan: PlanData, adjustables: list[_Adjustable], ages: dict[str, float],
         rate: float) -> tuple[ClaimingRun, list[int], set[str]]:
    """One projection: its run, its years and the owners whose earnings the earnings test withheld on."""
    streams = _household_streams(plan)
    names = {i.name for i in streams if i.is_social_security} | {SURVIVOR_TOP_UP}
    own = {i.id: i.annual_amount for i in streams}
    result: SimulationResult = run_simulation(copy.deepcopy(plan))
    snaps = result.yearly_snapshots
    # run_simulation sets every snapshot's cash flow.
    by_year = [sum(s.amount for s in snap.cash_flow.income_sources if s.name in names) for snap in snaps]
    end = snaps[-1].net_worth if snaps else 0.0
    withholding_earners = {owner for snap in snaps
                           for owner, amount in snap._ss_earnings_test_withheld_by_earner.items() if amount > 0}
    return ClaimingRun(
        claim_ages=ages,
        first_year_benefits={a.person.owner: own[a.income.id] for a in adjustables},
        social_security_by_year=by_year,
        lifetime_social_security=sum(by_year),
        lifetime_taxes=sum(s.taxes for s in snaps),
        end_net_worth=end,
        end_net_worth_after_tax=end - pre_tax_discount(result, rate),
        success=result.metadata.success,
        failure_year=result.metadata.failure_year,
    ), [snap.year for snap in snaps], withholding_earners


def best_run_index(runs: list[ClaimingRun]) -> int | None:
    """Highest after-tax end net worth among successful runs, else among all; ties keep the first."""
    pool = [i for i, r in enumerate(runs) if r.success] or list(range(len(runs)))
    best = None
    for i in pool:
        if best is None or runs[i].end_net_worth_after_tax > runs[best].end_net_worth_after_tax:
            best = i
    return best


def explore_claiming_ages(plan: PlanData) -> ClaimingExploration:
    """Run the plan at each candidate claiming-age combination. ``plan`` is not mutated."""
    first_index = first_month_index(plan)
    owners = ["self"]
    if plan.spouse_birth_year is not None or any(
            i.is_social_security and i.owner == "spouse" for i in plan.income_streams):
        owners.append("spouse")
    persons: list[ClaimingPerson] = []
    adjustables: list[_Adjustable] = []
    for owner in owners:
        person, adjustable = _person(plan, owner, first_index)
        persons.append(person)
        if adjustable is not None:
            adjustables.append(adjustable)
    rate = pre_tax_discount_rate(plan)
    exploration = ClaimingExploration(persons=persons, pre_tax_discount_rate=rate)
    if not adjustables:
        return exploration

    current, years, withholding_earners = _run(
        plan, adjustables, {a.person.owner: a.person.current_claim_age for a in adjustables}, rate)
    combos: list[dict[str, tuple[_Adjustable, int]]] = [{}]
    for adjustable in adjustables:
        combos = [{**combo, adjustable.person.owner: (adjustable, age)}
                  for combo in combos for age in adjustable.person.candidate_ages]
    runs = []
    for combo in combos:
        run, _, earners = _run(with_claims(plan, combo), adjustables,
                               {owner: float(age) for owner, (_, age) in combo.items()}, rate)
        withholding_earners |= earners
        run.end_net_worth_after_tax_change = run.end_net_worth_after_tax - current.end_net_worth_after_tax
        run.lifetime_social_security_change = run.lifetime_social_security - current.lifetime_social_security
        runs.append(run)
    best = best_run_index(runs)
    for person in persons:
        person.earnings_test_withholds = person.owner in withholding_earners
    exploration.years = years
    exploration.current = current
    exploration.runs = runs
    exploration.best_index = best
    exploration.best_end_net_worth_after_tax_change = runs[best].end_net_worth_after_tax_change
    exploration.best_lifetime_social_security_change = runs[best].lifetime_social_security_change
    exploration.patches = [
        ClaimingPatch(owner=a.person.owner, claiming_age=age, income_id=a.income.id, changes=claim_changes(a, age))
        for a in adjustables for age in a.person.candidate_ages
    ]
    return exploration

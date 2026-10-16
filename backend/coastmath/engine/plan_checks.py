"""Plan accuracy checklist: missing inputs that change a projection, and
inputs worth a second look.

Completeness checks are scored. Each has a stable key and a weight; a check
that does not apply to the plan is left out of the score. The score is the
weighted share of applicable checks that pass, 0-100, rounded half up; a plan
with no applicable check scores 100. Review items are never scored.

The rules read engine ``PlanData``, the milestone outcomes of one
deterministic projection of it, and, for connected balances, whether each
linked account's balance is current (decided by the caller with the
connection rules in ``app.integrations.balance_sync``). Nothing is persisted.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from coastmath.engine.assumption_curves import resolve_assumption
from coastmath.engine.household_lifecycle import simulation_end_year
from coastmath.engine.types import _TAXABLE_TYPES, IncomeData, PlanData
from coastmath.schemas.healthcare_settings import HealthcareSettings
from coastmath.schemas.person_healthcare import PersonHealthcareSettings

ItemKind = Literal["missing", "review"]
Person = Literal["self", "spouse"]

#: Completeness check weights, in item order. Accounts, spending and Social
#: Security dominate because each moves the whole projection. CoastMath
#: planning choices, stated in the plan accuracy help article.
CHECK_WEIGHTS: dict[str, int] = {
    "accounts_entered": 20,
    "expenses_entered": 20,
    "social_security_self": 15,
    "social_security_spouse": 15,
    "earned_income_ends": 10,
    "pre_medicare_coverage": 10,
    "balances_current": 5,
}

#: Review items, in item order.
REVIEW_KEYS = ("high_real_stock_return", "low_inflation", "event_never_runs", "milestone_missed",
               "zero_social_security", "cost_basis_assumed")

#: CoastMath planning choice, not law: a stock total return (price growth plus
#: dividend yield) more than this far above inflation is flagged for review.
REAL_STOCK_RETURN_REVIEW_ABOVE = 0.08
#: CoastMath planning choice, not law: inflation below this is flagged for review.
INFLATION_REVIEW_BELOW = 0.01
# Absorbs float noise so a rate exactly at a threshold is not flagged.
_EPSILON = 1e-9


@dataclass(frozen=True)
class CheckResult:
    key: str
    weight: int
    passes: bool


@dataclass(frozen=True)
class CheckItem:
    key: str
    kind: ItemKind
    section: str
    title: str
    target_id: str | None = None
    person: Person | None = None


@dataclass(frozen=True)
class PlanChecks:
    score: int
    checks: list[CheckResult] = field(default_factory=list)
    items: list[CheckItem] = field(default_factory=list)


def score(checks: Iterable[CheckResult]) -> int:
    """Weighted share of passing checks, 0-100, rounded half up; 100 when none apply."""
    checks = list(checks)
    total = sum(c.weight for c in checks)
    if total == 0:
        return 100
    passed = sum(c.weight for c in checks if c.passes)
    return math.floor(100 * passed / total + 0.5)


def _person_label(person: Person) -> str:
    return "your partner" if person == "spouse" else "you"


def _people(plan: PlanData) -> list[Person]:
    return ["self", "spouse"] if plan.spouse_birth_year is not None else ["self"]


def _birth_year(plan: PlanData, person: Person) -> int:
    return plan.spouse_birth_year if person == "spouse" else plan.birth_year  # type: ignore[return-value]


def _life_expectancy(plan: PlanData, person: Person) -> int | None:
    return plan.spouse_life_expectancy if person == "spouse" else plan.life_expectancy


def _never_starts(stream: Any, milestones: Mapping[str, Any], fired: Mapping[str, int]) -> bool:
    """Whether a switched-on start milestone never fires in the projection."""
    start = milestones.get(stream.start_milestone_id) if stream.start_milestone_id else None
    return start is not None and start.is_active and stream.start_milestone_id not in fired


def _earned_streams(plan: PlanData, milestones: Mapping[str, Any], fired: Mapping[str, int]) -> list[IncomeData]:
    """Recurring pay that runs at some point in the projection."""
    return [inc for inc in plan.income_streams
            if inc.is_active and inc.is_earned_income and not inc.is_social_security
            and inc.frequency != "once" and inc.annual_amount > 0
            and not _never_starts(inc, milestones, fired)]


def _healthcare(plan: PlanData):
    return HealthcareSettings.model_validate(plan.healthcare_settings or {})


def _medicare_age(settings, person: Person) -> int:
    override = next((p for p in settings.persons if p.owner == person), None)
    if override is not None:
        return override.medicare_start_age
    return PersonHealthcareSettings.model_fields["medicare_start_age"].default


def _pre_medicare_covered(settings, person: Person) -> bool:
    """An itemized medical budget, or marketplace coverage that includes the person."""
    if not settings.enabled:
        return False
    override = next((p for p in settings.persons if p.owner == person), None)
    if override is not None and override.mode == "itemized":
        return True
    if override is not None and (override.mode != "coverage" or not override.aca_enabled):
        return False
    return settings.aca_enabled and (person == "self" or settings.aca_cover_spouse)


def _rates_by_year(plan: PlanData) -> list[tuple[float, float, float]]:
    """(stock price growth, dividend yield, inflation) for each projected year."""
    curves, base = plan.assumption_curves, plan.assumptions
    return [(
        resolve_assumption(curves, "market_return", year, plan.birth_year, base.stock_growth_rate),
        resolve_assumption(curves, "dividend_yield", year, plan.birth_year, base.stock_dividend_yield),
        resolve_assumption(curves, "inflation", year, plan.birth_year, base.inflation_rate),
    ) for year in range(plan.start_year, simulation_end_year(plan) + 1)]


def evaluate_plan_checks(
    plan: PlanData,
    milestone_outcomes: Iterable[Any],
    balance_current: Mapping[str, bool] | None = None,
) -> PlanChecks:
    """Score a plan's completeness and list its gaps and review items.

    ``milestone_outcomes`` are the projection's ``SimMetadata.milestone_outcomes``
    (``id``, ``year``, ``missed_year``). ``balance_current`` maps each account
    with a connected balance to whether that balance is current.
    """
    outcomes = list(milestone_outcomes)
    fired = {o.id: o.year for o in outcomes if o.year is not None}
    milestones = {m.id: m for m in plan.milestones}
    us_plan = plan.tax_country == "US"
    checks: list[CheckResult] = []
    missing: dict[str, list[CheckItem]] = {}

    def check(key: str, applies: bool, failures: list[CheckItem]) -> None:
        if not applies:
            return
        checks.append(CheckResult(key, CHECK_WEIGHTS[key], not failures))
        if failures:
            missing[key] = failures

    # Accounts and spending.
    check("accounts_entered", True,
          [] if sum(a.balance for a in plan.accounts.values()) > 0
          else [CheckItem("accounts_entered", "missing", "accounts", "No account balances")])
    check("expenses_entered", True,
          [] if any(e.annual_amount > 0 for e in plan.expenses)
          else [CheckItem("expenses_entered", "missing", "expenses", "No expenses")])

    # US Social Security for each person in a plan taxed in the US.
    for person in _people(plan):
        has_benefit = any(inc.is_active and inc.is_social_security and inc.owner == person
                          for inc in plan.income_streams)
        key = f"social_security_{person}"
        check(key, us_plan, [] if has_benefit else [CheckItem(
            key, "missing", "income", f"No Social Security for {_person_label(person)}", person=person)])

    # Recurring pay ends at a milestone that fires in the projection.
    earned = _earned_streams(plan, milestones, fired)
    check("earned_income_ends", bool(earned), [
        CheckItem("earned_income_ends", "missing", "income", f"Salary never ends: {inc.name}",
                  target_id=inc.id, person="spouse" if inc.owner == "spouse" else "self")
        for inc in earned if inc.end_milestone_id not in fired
    ])

    # Coverage for anyone under their Medicare age when the household's last pay ends.
    if us_plan and all(inc.end_milestone_id in fired for inc in earned):
        work_ends = max((fired[inc.end_milestone_id] for inc in earned), default=plan.start_year)
        settings = _healthcare(plan)
        uncovered = []
        needs_cover = False
        for person in _people(plan):
            age = work_ends - _birth_year(plan, person)
            longevity = _life_expectancy(plan, person)
            if age >= _medicare_age(settings, person) or (longevity is not None and age > longevity):
                continue
            needs_cover = True
            if not _pre_medicare_covered(settings, person):
                uncovered.append(CheckItem(
                    "pre_medicare_coverage", "missing", "healthcare",
                    "No partner coverage before Medicare" if person == "spouse" else "No coverage before Medicare",
                    person=person))
        check("pre_medicare_coverage", needs_cover, uncovered)

    # Connected balances are current.
    linked = {aid: current for aid, current in (balance_current or {}).items() if aid in plan.accounts}
    check("balances_current", bool(linked), [
        CheckItem("balances_current", "missing", "accounts", f"Stale balance: {plan.accounts[aid].name or 'Account'}",
                  target_id=aid)
        for aid, current in linked.items() if not current
    ])

    review: list[CheckItem] = []
    rates = _rates_by_year(plan)
    if any((1 + growth + dividends) / (1 + inflation) - 1 > REAL_STOCK_RETURN_REVIEW_ABOVE + _EPSILON
           for growth, dividends, inflation in rates):
        review.append(CheckItem("high_real_stock_return", "review", "assumptions",
                                f"Stock return over {REAL_STOCK_RETURN_REVIEW_ABOVE:.0%} after inflation"))
    if any(inflation < INFLATION_REVIEW_BELOW - _EPSILON for _, _, inflation in rates):
        review.append(CheckItem("low_inflation", "review", "assumptions",
                                f"Inflation under {INFLATION_REVIEW_BELOW:.0%}"))

    for section, streams in (("income", [i for i in plan.income_streams if i.is_active]), ("expenses", plan.expenses)):
        for stream in streams:
            start_year = fired.get(stream.start_milestone_id or "")
            end_year = fired.get(stream.end_milestone_id or "")
            reversed_window = (start_year is not None and end_year is not None
                               and stream.start_milestone_id != stream.end_milestone_id and start_year > end_year)
            if _never_starts(stream, milestones, fired) or reversed_window:
                review.append(CheckItem("event_never_runs", "review", section, f"Never runs: {stream.name}",
                                        target_id=stream.id))

    for outcome in outcomes:
        if outcome.missed_year is not None and outcome.id in milestones:
            review.append(CheckItem("milestone_missed", "review", "milestones", f"Missed milestone: {outcome.name}",
                                    target_id=outcome.id))

    for inc in plan.income_streams:
        if inc.is_active and inc.is_social_security and inc.ss_benefit_basis == "amount" and inc.annual_amount == 0:
            review.append(CheckItem("zero_social_security", "review", "income", f"Social Security is $0: {inc.name}",
                                    target_id=inc.id, person="spouse" if inc.owner == "spouse" else "self"))

    # A blank basis is valid input (projected as equal to the balance), so it is reviewed, not scored.
    for aid, a in plan.accounts.items():
        if (a.account_type in _TAXABLE_TYPES and a.balance > 0 and not a.intl_account_kind
                and a.cost_basis is None):
            review.append(CheckItem("cost_basis_assumed", "review", "accounts",
                                    f"Basis assumed equal to balance: {a.name or 'Taxable account'}",
                                    target_id=aid))

    ordered = [item for key in sorted(missing, key=lambda k: (-CHECK_WEIGHTS[k], list(CHECK_WEIGHTS).index(k)))
               for item in missing[key]]
    ordered += sorted(review, key=lambda item: REVIEW_KEYS.index(item.key))
    return PlanChecks(score=score(checks), checks=checks, items=ordered)

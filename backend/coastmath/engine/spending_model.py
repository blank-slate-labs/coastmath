"""Spending models: project a plan as if its current spending were given amounts.

A spending model states annual essential and discretionary spending and,
optionally, monthly take-home pay. The overlay turns it into ordinary plan
inputs on a copy of ``PlanData``; nothing here sees a transaction, and every
projection still runs ``run_simulation``.

- **Covered expenses** are living expenses: not payroll deductions, not
  qualified education, not periodic (``recurrence_years``), not tied to an
  income and not paid from a specific funding account. A caller may name the
  covered set instead.
- **Current phase**: covered expenses active in the plan's first projection
  year, decided with the simulator's milestone timing. Milestones that only
  resolve during a projection (balances, conditions, relatives of either) are
  treated as not reached in the first year.
- **Scaling**: each bucket's ratio is the model amount over the current
  phase's annualized total; an expense with a discretionary share scales each
  part by its own ratio. Expenses scale in place, so phases, end milestones,
  inflation links, growth and flex settings survive. ``future_phases="scale"``
  applies the same ratios to covered expenses that start later;
  ``"as_planned"`` leaves them.
- A bucket the plan lacks becomes a lifetime, inflation-linked expense.
- Amounts round to cents and discretionary percents to two decimals, the
  precision the saved plan stores, so an applied model reproduces the preview.

Invariant: in the overlaid plan, first-year covered spending (annualized for
a partial first year) equals the model per bucket, within that rounding, and
every input outside the covered set is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, replace
from typing import Literal

import numpy as np

from coastmath.engine.flex_spending import discretionary_share
from coastmath.engine.milestones import (
    is_event_active,
    prorate_for_year,
    resolve_deterministic_milestones,
)
from coastmath.engine.monte_carlo import run_monte_carlo
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import ExpenseData, IncomeData, PlanData
from coastmath.schemas.expense import category_for_discretionary_percent

FuturePhases = Literal["scale", "as_planned"]
IncomeMode = Literal["as_planned", "scale_to_take_home"]
FUTURE_PHASES: tuple[str, ...] = ("scale", "as_planned")
INCOME_MODES: tuple[str, ...] = ("as_planned", "scale_to_take_home")

MAX_MODELS = 6
#: Earned-income scale factors outside this range are refused.
INCOME_RATIO_BOUNDS = (0.1, 10.0)
#: Re-runs after the first estimate; tax is progressive, so one is rarely exact.
INCOME_REFINEMENTS = 3
#: Annual net pay within this many dollars of the target ends the refinement.
TAKE_HOME_TOLERANCE = 1.0
#: A bucket whose current total is at most this is treated as absent.
_ABSENT = 0.005

ADDED_EXPENSES = {
    "essential": ("spending_model:essential", "Essential spending"),
    "discretionary": ("spending_model:discretionary", "Discretionary spending"),
}
_EARNED_TAX_CATEGORIES = frozenset({None, "employment", "self_employment"})

CAVEAT_UNRESOLVED = "Spending tied to balance or condition milestones counts as not started or ended in year one."
CAVEAT_NO_EARNED = "Take-home not scaled: no earned income in year one."
CAVEAT_RATIO = "Take-home not scaled: it needs earned income below 0.1× or above 10× the plan's."


class SpendingModelError(ValueError):
    """A spending model or comparison request the overlay cannot use."""


@dataclass(frozen=True)
class SpendingModel:
    """Annual essential and discretionary spending, optional monthly take-home."""

    label: str
    essential: float
    discretionary: float
    take_home_monthly: float | None = None

    def __post_init__(self):
        for name in ("essential", "discretionary"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise SpendingModelError(f"{name} must be a finite amount of at least zero")
        if self.take_home_monthly is not None and (
                not math.isfinite(self.take_home_monthly) or self.take_home_monthly <= 0):
            raise SpendingModelError("take_home_monthly must be a finite amount above zero")


# ---------------------------------------------------------------------------
# First-year timing (the simulator's milestone semantics, before simulation)
# ---------------------------------------------------------------------------

class _FirstYear:
    """Which milestone-bounded events run in the plan's first projection year.

    Mirrors the simulator's first iteration: milestones resolve to dates
    (``resolve_deterministic_milestones``), a date at or before the start year
    has fired, one that fired before the plan began counts as continuing, and
    the event's share comes from ``prorate_for_year`` within the modeled part
    of the year. Milestones without a date before simulation are not reached.
    """

    def __init__(self, plan_data: PlanData):
        self.year = plan_data.start_year
        self.fraction = max(0.0, min(1.0, plan_data.first_year_fraction))
        self.birth_month = plan_data.birth_month
        self.milestones = {ms.id: ms for ms in resolve_deterministic_milestones(
            plan_data.milestones, plan_data.birth_year, plan_data.birth_month)}
        self.triggered: set[str] = set()
        self.newly: list[str] = []
        self.unresolved: set[str] = set()
        for ms in self.milestones.values():
            if not ms.is_active:
                continue  # Switched off: never fires, and that is already known.
            if ms.trigger_type == "date" and ms.trigger_date:
                fired = int(ms.trigger_date[:4])
                if fired <= self.year:
                    self.triggered.add(ms.id)
                if fired == self.year:
                    self.newly.append(ms.id)
            else:
                self.unresolved.add(ms.id)

    def share(self, start_id: str | None, end_id: str | None,
              start_month: int | None, end_month: int | None) -> float:
        """Fraction of the first calendar year the event is active (0-1)."""
        active = is_event_active(start_id, end_id, self.triggered) or (
            end_id is not None and end_id in self.newly
            and (start_id is None or start_id in self.triggered))
        if not active:
            return 0.0
        return prorate_for_year(
            self.milestones.get(start_id) if start_id else None,
            self.milestones.get(end_id) if end_id else None,
            start_month, end_month, self.triggered, self.newly, self.year,
            self.birth_month, simulation_fraction=self.fraction,
        )

    def annualized(self, start_id, end_id, start_month, end_month) -> float:
        """``share`` scaled to a full year for a partial opening year."""
        share = self.share(start_id, end_id, start_month, end_month)
        return share / self.fraction if self.fraction > 0 else 0.0

    def depends_on_unresolved(self, start_id: str | None, end_id: str | None) -> bool:
        return bool({start_id, end_id} & self.unresolved)


# ---------------------------------------------------------------------------
# Covered set and current phase
# ---------------------------------------------------------------------------

def is_living_expense(expense: ExpenseData) -> bool:
    """An ordinary living expense a spending model replaces."""
    return not (
        expense.is_payroll_deduction
        or expense.qualified_education
        or expense.recurrence_years is not None
        or expense.tied_income_id is not None
        or expense.specific_funding_source_id is not None
        or bool(expense.specific_funding_source_ids)
    )


def covered_expense_ids(plan_data: PlanData, explicit: list[str] | set[str] | None = None) -> list[str]:
    """IDs of the expenses a model replaces, in plan order.

    ``explicit`` replaces the living-expense rule; IDs the plan does not have are ignored.
    """
    if explicit is not None:
        wanted = {str(value) for value in explicit}
        return [exp.id for exp in plan_data.expenses if exp.id in wanted]
    return [exp.id for exp in plan_data.expenses if is_living_expense(exp)]


@dataclass
class SpendingBaseline:
    """The plan's current-phase covered spending, annualized."""

    essential: float
    discretionary: float
    covered_ids: list[str]
    current_ids: list[str]
    later_ids: list[str]
    unresolved: bool


def spending_baseline(plan_data: PlanData, covered_ids: list[str] | set[str] | None = None) -> SpendingBaseline:
    """Sum first-year covered spending by bucket.

    An expense without a category or discretionary share counts as essential,
    as the simulator's planned-essential total does.
    """
    timing = _FirstYear(plan_data)
    covered = covered_expense_ids(plan_data, covered_ids)
    covered_set = set(covered)
    essential = discretionary = 0.0
    current: list[str] = []
    later: list[str] = []
    unresolved = False
    for exp in plan_data.expenses:
        if exp.id not in covered_set:
            continue
        unresolved = unresolved or timing.depends_on_unresolved(exp.start_milestone_id, exp.end_milestone_id)
        weight = timing.annualized(exp.start_milestone_id, exp.end_milestone_id, exp.start_month, exp.end_month)
        if weight <= 0:
            later.append(exp.id)
            continue
        current.append(exp.id)
        share = discretionary_share(exp) or 0.0
        amount = exp.annual_amount * weight
        essential += amount * (1.0 - share)
        discretionary += amount * share
    return SpendingBaseline(essential, discretionary, covered, current, later, unresolved)


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExpenseChange:
    """New values for one existing expense; what an apply persists."""

    expense_id: str
    annual_amount: float
    growth_cap: float | None
    discretionary_percent: float | None  # 0-100, two decimals; None = unchanged
    category: str | None


@dataclass
class SpendingOverlay:
    plan_data: PlanData
    covered_expense_ids: list[str]
    essential_ratio: float | None  # None: the plan had no spending in this bucket
    discretionary_ratio: float | None
    current_essential: float
    current_discretionary: float
    changes: list[ExpenseChange] = field(default_factory=list)
    added: list[ExpenseData] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def _scale_expense(expense: ExpenseData, essential_ratio: float, discretionary_ratio: float
                   ) -> tuple[ExpenseData, ExpenseChange | None]:
    share = discretionary_share(expense) or 0.0
    factor = (1.0 - share) * essential_ratio + share * discretionary_ratio
    amount = round(expense.annual_amount * factor, 2)
    cap = round(expense.growth_cap * factor, 2) if expense.growth_cap is not None else None
    fraction, category, percent = expense.discretionary_fraction, expense.category, None
    if 0.0 < share < 1.0 and factor > 0 and not math.isclose(essential_ratio, discretionary_ratio):
        # Stored as a percent with two decimals; keep the engine on that value.
        percent = round(share * discretionary_ratio / factor * 100.0, 2)
        fraction = percent / 100.0
        category = category_for_discretionary_percent(percent)
    scaled = replace(expense, annual_amount=amount, growth_cap=cap, discretionary_fraction=fraction, category=category)
    if scaled == expense:
        return expense, None
    return scaled, ExpenseChange(expense.id, amount, cap, percent, category)


def overlay_spending_model(
    plan_data: PlanData,
    model: SpendingModel,
    *,
    covered_ids: list[str] | set[str] | None = None,
    future_phases: str = "scale",
) -> SpendingOverlay:
    """Return a copy of ``plan_data`` whose current covered spending is ``model``.

    Pure: ``plan_data`` is not modified. Income is unchanged (see
    ``scale_income_to_take_home``).
    """
    if future_phases not in FUTURE_PHASES:
        raise SpendingModelError(f"future_phases must be one of {FUTURE_PHASES}")
    baseline = spending_baseline(plan_data, covered_ids)
    essential_ratio = model.essential / baseline.essential if baseline.essential > _ABSENT else None
    discretionary_ratio = model.discretionary / baseline.discretionary if baseline.discretionary > _ABSENT else None
    scale_ids = set(baseline.current_ids)
    if future_phases == "scale":
        scale_ids |= set(baseline.later_ids)

    expenses: list[ExpenseData] = []
    changes: list[ExpenseChange] = []
    for exp in plan_data.expenses:
        if exp.id in scale_ids:
            exp, change = _scale_expense(
                exp,
                essential_ratio if essential_ratio is not None else 1.0,
                discretionary_ratio if discretionary_ratio is not None else 1.0,
            )
            if change is not None:
                changes.append(change)
        expenses.append(exp)

    added: list[ExpenseData] = []
    for bucket, ratio, current, target in (
        ("essential", essential_ratio, baseline.essential, model.essential),
        ("discretionary", discretionary_ratio, baseline.discretionary, model.discretionary),
    ):
        amount = round(target - current, 2)
        if ratio is None and amount > 0:
            expense_id, name = ADDED_EXPENSES[bucket]
            added.append(ExpenseData(id=expense_id, name=name, annual_amount=amount,
                                     inflation_linked=True, category=bucket))
    caveats = [CAVEAT_UNRESOLVED] if baseline.unresolved else []
    return SpendingOverlay(
        plan_data=replace(plan_data, expenses=[*expenses, *added]),
        covered_expense_ids=baseline.covered_ids,
        essential_ratio=essential_ratio,
        discretionary_ratio=discretionary_ratio,
        current_essential=baseline.essential,
        current_discretionary=baseline.discretionary,
        changes=changes,
        added=added,
        caveats=caveats,
    )


# ---------------------------------------------------------------------------
# Take-home income scaling
# ---------------------------------------------------------------------------

def is_scalable_earned_income(income: IncomeData) -> bool:
    """Recurring wages or self-employment pay; never Social Security or pensions."""
    return (
        income.is_active
        and income.is_earned_income
        and not income.is_social_security
        and income.pension_formula is None
        and income.frequency != "once"
        and income.tax_category in _EARNED_TAX_CATEGORIES
    )


def _scale_income(income: IncomeData, ratio: float) -> IncomeData:
    """Scale a stream's whole path: its amount, cap and dollar growth steps.

    Percent and inflation-offset segments are relative and stay as entered;
    dollar-change and set-amount segments scale so every year is ``ratio``
    times the planned amount.
    """
    schedule = None
    if income.growth_schedule is not None:
        schedule = [
            {**segment, "value": float(segment["value"]) * ratio}
            if segment.get("kind") in {"dollar_change", "set_amount"} else dict(segment)
            for segment in income.growth_schedule
        ]
    return replace(
        income,
        annual_amount=income.annual_amount * ratio,
        growth_cap=income.growth_cap * ratio if income.growth_cap is not None else None,
        growth_schedule=schedule,
    )


def first_year_take_home(result, plan_data: PlanData) -> float:
    """Year-one net pay, annualized for a partial first year, per month."""
    snaps = result.yearly_snapshots
    if not snaps or snaps[0].cash_flow is None:
        return 0.0
    fraction = max(0.0, min(1.0, plan_data.first_year_fraction))
    annual = snaps[0].cash_flow.net_pay / fraction if fraction > 0 else 0.0
    return annual / 12.0


@dataclass
class IncomeScaling:
    plan_data: PlanData
    ratio: float | None  # None: not scaled
    caveats: list[str]
    result: object | None = None  # the projection of ``plan_data`` when one was run


def scale_income_to_take_home(plan_data: PlanData, take_home_monthly: float,
                              *, baseline_result=None) -> IncomeScaling:
    """Scale year-one earned income so year-one net pay is ``12 ×`` the target.

    One proportional estimate, then secant refinements (at most
    ``INCOME_REFINEMENTS`` re-runs in total). Refused, with a caveat and no
    scaling, when no earned stream runs in year one or a ratio leaves
    ``INCOME_RATIO_BOUNDS``.
    """
    timing = _FirstYear(plan_data)
    earned = {
        inc.id for inc in plan_data.income_streams
        if is_scalable_earned_income(inc)
        and timing.share(inc.start_milestone_id, inc.end_milestone_id, inc.start_month, inc.end_month) > 0
    }
    if not earned:
        return IncomeScaling(plan_data, None, [CAVEAT_NO_EARNED], baseline_result)
    target = 12.0 * take_home_monthly
    if baseline_result is None:
        baseline_result = run_simulation(plan_data)
    net = 12.0 * first_year_take_home(baseline_result, plan_data)
    if net <= 0:
        return IncomeScaling(plan_data, None, [CAVEAT_RATIO], baseline_result)
    low, high = INCOME_RATIO_BOUNDS
    prev_ratio, prev_net = 1.0, net
    ratio = target / net
    best: tuple[float, PlanData, object] | None = None
    for _ in range(INCOME_REFINEMENTS):
        if not low <= ratio <= high:
            return IncomeScaling(plan_data, None, [CAVEAT_RATIO], baseline_result)
        scaled = replace(plan_data, income_streams=[
            _scale_income(inc, ratio) if inc.id in earned else inc for inc in plan_data.income_streams])
        result = run_simulation(scaled)
        net = 12.0 * first_year_take_home(result, scaled)
        best = (ratio, scaled, result)
        if abs(net - target) <= TAKE_HOME_TOLERANCE or net == prev_net:
            break
        prev_ratio, prev_net, ratio = ratio, net, ratio + (target - net) * (ratio - prev_ratio) / (net - prev_net)
    ratio, scaled, result = best
    return IncomeScaling(scaled, ratio, [], result)


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

def expense_fingerprint(plan_data: PlanData, covered_ids: list[str] | set[str] | None = None) -> str:
    """Hash of every plan input the overlay reads, for apply's conflict check.

    Covers the expenses (all fields, by ID), the milestones that time them,
    the start year and fraction, the birth year and month, and the covered set.
    """
    payload = {
        "start_year": plan_data.start_year,
        "first_year_fraction": plan_data.first_year_fraction,
        "birth_year": plan_data.birth_year,
        "birth_month": plan_data.birth_month,
        "covered": sorted(covered_expense_ids(plan_data, covered_ids)),
        "milestones": sorted((asdict(ms) for ms in plan_data.milestones), key=lambda row: row["id"]),
        "expenses": sorted((asdict(exp) for exp in plan_data.expenses), key=lambda row: row["id"]),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

@dataclass
class SpendingOutcome:
    label: str
    essential: float
    discretionary: float
    take_home_monthly: float | None
    essential_ratio: float | None
    discretionary_ratio: float | None
    income_ratio: float | None
    projected_take_home_monthly: float
    fi_year: int | None
    fi_age: int | None
    success: bool
    failure_year: int | None
    final_net_worth: float
    net_worth_path: list[dict] = field(default_factory=list)
    monte_carlo_success_rate: float | None = None
    caveats: list[str] = field(default_factory=list)


@dataclass
class SpendingComparison:
    fingerprint: str
    covered_expense_ids: list[str]
    plan: SpendingOutcome
    models: list[SpendingOutcome]
    caveats: list[str]
    seed: int | None


def _outcome(plan_data: PlanData, result, *, label: str, essential: float, discretionary: float,
             take_home_monthly: float | None, essential_ratio: float | None, discretionary_ratio: float | None,
             income_ratio: float | None, caveats: list[str], mc_trials: int, seed: int | None,
             max_workers: int | None, deadline: float | None) -> SpendingOutcome:
    snaps = result.yearly_snapshots
    ages = {s.year: s.age for s in snaps}
    fi = result.metadata.fi_estimate
    fi_year = fi.year if fi is not None else None
    path = [{"year": s.year, "age": s.age, "net_worth": s.net_worth,
             "inflation_factor": s.inflation_factor if s.inflation_factor is not None else 1.0} for s in snaps]
    outcome = SpendingOutcome(
        label=label, essential=essential, discretionary=discretionary, take_home_monthly=take_home_monthly,
        essential_ratio=essential_ratio, discretionary_ratio=discretionary_ratio, income_ratio=income_ratio,
        projected_take_home_monthly=first_year_take_home(result, plan_data),
        fi_year=fi_year, fi_age=ages.get(fi_year) if fi_year is not None else None,
        success=result.metadata.success, failure_year=result.metadata.failure_year,
        final_net_worth=snaps[-1].net_worth if snaps else 0.0, net_worth_path=path, caveats=list(caveats),
    )
    if mc_trials > 0:
        outcome.monte_carlo_success_rate = run_monte_carlo(
            plan_data, n_trials=mc_trials, seed=seed, max_workers=max_workers, deadline=deadline).success_rate
    return outcome


def compare_spending_models(
    plan_data: PlanData,
    models: list[SpendingModel],
    *,
    covered_ids: list[str] | set[str] | None = None,
    future_phases: str = "scale",
    income: str = "as_planned",
    mc_trials: int = 0,
    seed: int | None = None,
    max_workers: int | None = None,
    deadline: float | None = None,
) -> SpendingComparison:
    """Project the plan as-is and under each model.

    Every run is deterministic; with ``mc_trials`` every variant also runs a
    Monte Carlo with one shared seed, so variants differ only by spending.
    ``deadline`` bounds all of those Monte Carlo runs together (:func:`run_monte_carlo`).
    """
    if len(models) > MAX_MODELS:
        raise SpendingModelError(f"Compare at most {MAX_MODELS} spending models")
    if future_phases not in FUTURE_PHASES:
        raise SpendingModelError(f"future_phases must be one of {FUTURE_PHASES}")
    if income not in INCOME_MODES:
        raise SpendingModelError(f"income must be one of {INCOME_MODES}")
    if mc_trials > 0 and seed is None:
        seed = int(np.random.SeedSequence().generate_state(1)[0])
    baseline = spending_baseline(plan_data, covered_ids)
    plan_result = run_simulation(plan_data)
    shared = dict(mc_trials=mc_trials, seed=seed, max_workers=max_workers, deadline=deadline)
    plan_outcome = _outcome(
        plan_data, plan_result, label="This plan", essential=baseline.essential,
        discretionary=baseline.discretionary, take_home_monthly=None,
        essential_ratio=1.0 if baseline.essential > _ABSENT else None,
        discretionary_ratio=1.0 if baseline.discretionary > _ABSENT else None,
        income_ratio=None, caveats=[CAVEAT_UNRESOLVED] if baseline.unresolved else [], **shared,
    )
    outcomes: list[SpendingOutcome] = []
    for model in models:
        overlay = overlay_spending_model(plan_data, model, covered_ids=covered_ids, future_phases=future_phases)
        variant, result, income_ratio, caveats = overlay.plan_data, None, None, list(overlay.caveats)
        if income == "scale_to_take_home" and model.take_home_monthly is not None:
            scaling = scale_income_to_take_home(variant, model.take_home_monthly)
            variant, result, income_ratio = scaling.plan_data, scaling.result, scaling.ratio
            caveats += scaling.caveats
        if result is None:
            result = run_simulation(variant)
        outcomes.append(_outcome(
            variant, result, label=model.label, essential=model.essential, discretionary=model.discretionary,
            take_home_monthly=model.take_home_monthly, essential_ratio=overlay.essential_ratio,
            discretionary_ratio=overlay.discretionary_ratio, income_ratio=income_ratio, caveats=caveats, **shared,
        ))
    caveats = ["Only the covered spending changes; payroll, account-funded, education and periodic expenses stay as planned."
               if covered_ids is None else "Only the selected spending expenses change."]
    return SpendingComparison(
        fingerprint=expense_fingerprint(plan_data, covered_ids),
        covered_expense_ids=baseline.covered_ids,
        plan=plan_outcome,
        models=outcomes,
        caveats=caveats,
        seed=seed if mc_trials > 0 else None,
    )

"""Compare textbook withdrawal strategies against the plan's own spending.

Each strategy is run through the full deterministic projection (and,
optionally, a seeded Monte Carlo) with the strategy amount replacing the
plan's ordinary expenses from the chosen start. The plan's own expenses are
reported as "planned spending" so the two are never confused.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from coastmath.engine.assumption_curves import resolve_assumption
from coastmath.engine.household_lifecycle import simulation_end_year
from coastmath.engine.monte_carlo import run_monte_carlo
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import PlanData
from coastmath.engine.withdrawal_strategy import (
    STRATEGY_METHODS,
    WithdrawalStrategySpec,
)


@dataclass
class StrategyOutcome:
    method: str
    label: str
    success: bool
    failure_year: int | None
    start_year: int | None
    first_year_spending: float
    total_real_spending: float
    median_real_spending: float
    min_real_spending: float
    max_real_spending: float
    real_spending_drawdown: float  # largest peak-to-trough fall in real spending (fraction)
    years_below_planned: int
    final_net_worth: float
    lifetime_taxes: float
    monte_carlo_success_rate: float | None = None
    monte_carlo_p10_final_net_worth: float | None = None
    spending_path: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class WithdrawalComparison:
    initial_rate: float
    planned: StrategyOutcome
    strategies: list[StrategyOutcome]
    caveats: list[str]


def plan_inflation_factor(plan_data: PlanData, start_year: int, year: int) -> float:
    default = plan_data.assumptions.inflation_rate if plan_data.assumptions else .03
    factor = 1.0
    # Plan amounts step a full year each January, even after a partial
    # opening year (EXPENSE_INFLATION_CONVENTION); deflate the same way.
    for prior_year in range(start_year, year):
        rate = resolve_assumption(plan_data.assumption_curves, "inflation", prior_year, plan_data.birth_year, default)
        factor *= 1.0 + rate
    return factor


def _outcome(plan_data: PlanData, spec: WithdrawalStrategySpec | None, label: str, method: str,
             mc_trials: int, seed: int | None, comparison_start_year: int | None = None,
             max_workers: int | None = None, deadline: float | None = None) -> StrategyOutcome:
    result = run_simulation(plan_data, withdrawal_strategy=spec)
    snaps = result.yearly_snapshots
    sim_start = snaps[0].year if snaps else plan_data.start_year
    path: list[dict] = []
    reals: list[float] = []
    total_real = 0.0
    below = 0
    start_year = None
    for s in snaps:
        if comparison_start_year is not None and s.year < comparison_start_year:
            continue
        spent = s.strategy_spending if spec is not None else None
        planned = s.planned_expenses
        if spec is None:
            spent = planned
        if spent is None:
            continue
        if start_year is None:
            start_year = s.year
        factor = plan_inflation_factor(plan_data, sim_start, s.year)
        total_real += spent / factor
        # A partial opening year spends only its modeled share. Report its
        # annual rate so the stub is not read as a spending cut; the total
        # above remains what was actually spent.
        annual = (1.0 / plan_data.first_year_fraction
                  if s.year == sim_start and 0 < plan_data.first_year_fraction < 1 else 1.0)
        real = spent * annual / factor
        reals.append(real)
        if planned is not None and spent < planned - 0.005:
            below += 1
        path.append({"year": s.year, "age": s.age, "nominal": spent * annual, "real": real,
                     "planned_nominal": planned * annual if planned is not None else None,
                     "net_worth": s.net_worth})
    drawdown = 0.0
    peak = 0.0
    for r in reals:
        peak = max(peak, r)
        if peak > 0:
            drawdown = max(drawdown, (peak - r) / peak)
    outcome = StrategyOutcome(
        method=method, label=label, success=result.metadata.success, failure_year=result.metadata.failure_year,
        start_year=start_year, first_year_spending=path[0]["nominal"] if path else 0.0,
        total_real_spending=float(total_real), median_real_spending=float(np.median(reals)) if reals else 0.0,
        min_real_spending=float(min(reals)) if reals else 0.0, max_real_spending=float(max(reals)) if reals else 0.0,
        real_spending_drawdown=drawdown, years_below_planned=below,
        final_net_worth=snaps[-1].net_worth if snaps else 0.0, lifetime_taxes=float(sum(s.taxes for s in snaps)),
        spending_path=path,
    )
    if mc_trials > 0:
        mc = run_monte_carlo(plan_data, n_trials=mc_trials, seed=seed, withdrawal_strategy=spec, max_workers=max_workers,
                             deadline=deadline)
        outcome.monte_carlo_success_rate = mc.success_rate
        outcome.monte_carlo_p10_final_net_worth = mc.p10_final_net_worth
    if not result.metadata.success:
        outcome.notes.append(f"Plan fails in {result.metadata.failure_year}.")
    return outcome


def compare_withdrawal_strategies(
    plan_data: PlanData,
    *,
    methods: list[str],
    initial_rate: float,
    start_milestone_id: str | None,
    start_age: int | None,
    mc_trials: int = 0,
    seed: int | None = None,
    max_workers: int | None = None,
    deadline: float | None = None,
) -> WithdrawalComparison:
    unknown = [m for m in methods if m not in STRATEGY_METHODS]
    if unknown:
        raise ValueError(f"Unknown withdrawal strategies: {unknown}")
    # The planned-spending baseline is the plan's own expenses, never a
    # strategy saved on the plan; each compared rule is passed explicitly.
    plan_data = replace(plan_data, withdrawal_strategy=None)
    if mc_trials > 0 and seed is None:
        # Draw once per comparison, including the planned-spending baseline.
        seed = int(np.random.SeedSequence().generate_state(1)[0])
    strategies = [
        _outcome(plan_data, WithdrawalStrategySpec(method=m, initial_rate=initial_rate,
                                                   start_milestone_id=start_milestone_id, start_age=start_age),
                 STRATEGY_METHODS[m], m, mc_trials, seed, max_workers=max_workers, deadline=deadline)
        for m in methods
    ]
    starts = [s.start_year for s in strategies if s.start_year is not None]
    comparison_start = min(starts) if starts else simulation_end_year(plan_data) + 1
    planned = _outcome(plan_data, None, "Planned spending (this plan's expenses)", "planned", mc_trials, seed,
                       comparison_start_year=comparison_start, max_workers=max_workers, deadline=deadline)
    caveats = [
        # One line each: modeling boundaries only (product copy rules).
        "Rules replace ordinary expenses only; debts, property, charity and health costs continue.",
        "Each rule sizes spending from liquid accounts at the start of the year.",
        "A partial first year is shown at its annual rate.",
    ]
    return WithdrawalComparison(initial_rate=initial_rate, planned=planned, strategies=strategies, caveats=caveats)

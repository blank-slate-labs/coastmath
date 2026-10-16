"""Hypothetical stress presets — one deterministic run with a life-event overlay.

Each preset applies an overlay to a deep copy of the plan (and, for a market
crash or downturn, a return override for the shocked years) and runs
``run_simulation``. Every year
the overlay does not touch keeps the plan's own inputs and assumptions.
Nothing is persisted.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Literal

from coastmath.engine.assumption_curves import resolve_assumption
from coastmath.engine.historical_data import DIVIDEND_YIELD_PROVENANCE
from coastmath.engine.household_lifecycle import simulation_end_year
from coastmath.engine.simulator import get_assumption_rate, run_simulation
from coastmath.engine.types import ExpenseData, MilestoneData, PlanData

Preset = Literal["job_loss", "market_crash", "tech_bust", "new_child", "downturn"]
PRESETS: tuple[str, ...] = ("job_loss", "market_crash", "tech_bust", "new_child", "downturn")

CHILD_COST_YEARS = 18


class ScenarioInputError(ValueError):
    """The preset does not apply to this plan (no partner, no earned income)."""


@dataclass(frozen=True)
class ScenarioParams:
    start_year: int
    person: Literal["self", "spouse"] = "self"
    months_without_pay: int = 6
    resume_percent: float = 80.0
    stock_drop_percent: float = 35.0
    child_annual_cost: float = 18_000.0
    # ``downturn`` only: stock_drop_percent is the cumulative decline over
    # downturn_years; None keeps the plan's own bond return / inflation.
    downturn_years: int = 3
    recovery_years: int = 0
    bond_return_percent: float | None = None
    inflation_percent: float | None = None


def plan_years(plan_data: PlanData) -> tuple[int, int]:
    """First and last simulated calendar years (inclusive)."""
    return plan_data.start_year, simulation_end_year(plan_data) - 1


def _pause_start(plan_data: PlanData, year: int) -> float:
    """Fractional calendar year at which an event in ``year`` begins.

    January, or the plan's first simulated month when ``year`` is the
    plan's partial opening year.
    """
    if year == plan_data.start_year:
        return year + 1.0 - max(0.0, min(1.0, plan_data.first_year_fraction))
    return float(year)


def apply_job_loss(plan_data: PlanData, params: ScenarioParams) -> PlanData:
    """Stop the person's earned income for N months, then resume at X%."""
    if params.person == "spouse" and plan_data.spouse_birth_year is None:
        raise ScenarioInputError("This plan has no partner.")
    pause_start = _pause_start(plan_data, params.start_year)
    interruption = (
        pause_start,
        pause_start + params.months_without_pay / 12.0,
        params.resume_percent / 100.0,
    )
    streams = []
    matched = False
    for inc in plan_data.income_streams:
        if inc.owner == params.person and inc.is_earned_income and not inc.is_social_security:
            inc = replace(inc, pay_interruption=interruption)
            matched = True
        streams.append(inc)
    if not matched:
        who = "your partner" if params.person == "spouse" else "you"
        raise ScenarioInputError(f"The plan has no earned income for {who}.")
    return replace(plan_data, income_streams=streams)


def _plan_rates(plan_data: PlanData, year: int) -> tuple[float, float, float]:
    """The plan's own bond return, inflation and dividend yield for ``year``."""
    curves = plan_data.assumption_curves
    assumptions = plan_data.assumptions
    bond = resolve_assumption(curves, "bond_return", year, plan_data.birth_year,
                              get_assumption_rate(assumptions, "bond_return_rate"))
    inflation = resolve_assumption(curves, "inflation", year, plan_data.birth_year,
                                   get_assumption_rate(assumptions, "inflation_rate"))
    dividend = resolve_assumption(curves, "dividend_yield", year, plan_data.birth_year,
                                  get_assumption_rate(assumptions, "stock_dividend_yield"))
    return bond, inflation, dividend


def _override_row(plan_data: PlanData, year: int, stock: float, bond: float,
                  inflation: float, dividend: float) -> tuple:
    """One override row for a year whose stock total return is ``stock``.

    A partial opening year models only its trailing months, and the simulator
    compounds the annual rate over that share, so the stock rate is annualized
    for the months modeled to still lose (or gain) the full yearly factor, as
    the job-loss pause starts at the plan's first month. The plan's dividend
    split is capped by the total return so price cannot fall below zero.
    """
    fraction = plan_data.first_year_fraction
    if year == plan_data.start_year and 0.0 < fraction < 1.0:
        stock = (1.0 + stock) ** (1.0 / fraction) - 1.0
    return (stock, bond, inflation, max(0.0, min(dividend, 1.0 + stock)))


def crash_returns(plan_data: PlanData, params: ScenarioParams) -> dict[int, tuple]:
    """A one-year override: stocks lose Y% (total return) in the start year.

    Bonds, inflation and the dividend split keep the plan's own assumption for
    that year; years outside the override are untouched by construction.
    """
    year = params.start_year
    bond, inflation, dividend = _plan_rates(plan_data, year)
    stock = -params.stock_drop_percent / 100.0
    return {year: _override_row(plan_data, year, stock, bond, inflation, dividend)}


def downturn_path(plan_data: PlanData, params: ScenarioParams) -> list[dict]:
    """Yearly rates of a multi-year downturn and its recovery, as applied.

    Stocks fall ``stock_drop_percent`` in total over ``downturn_years`` along
    an even geometric path, then earn the constant return that brings the
    stock index back to its pre-downturn level over ``recovery_years``.
    Bond return and inflation overrides apply to downturn years only; blank
    ones, and every recovery year, keep the plan's assumption. Years past the
    plan's last year are dropped. Stock returns are yearly factors before the
    partial-opening-year annualization in ``_override_row``.
    """
    if params.downturn_years < 1 or params.recovery_years < 0 \
            or not 0.0 < params.stock_drop_percent < 100.0:
        raise ScenarioInputError("Downturn needs 1+ years and a decline between 0% and 100%.")
    _, last = plan_years(plan_data)
    drop = params.stock_drop_percent / 100.0
    n = params.downturn_years
    # One year reduces to the market_crash rate exactly (no float round trip).
    decline = -drop if n == 1 else (1.0 - drop) ** (1.0 / n) - 1.0
    path: list[dict] = []
    for offset in range(n + params.recovery_years):
        year = params.start_year + offset
        if year > last:
            break
        bond, inflation, _ = _plan_rates(plan_data, year)
        if offset < n:
            if params.bond_return_percent is not None:
                bond = params.bond_return_percent / 100.0
            if params.inflation_percent is not None:
                inflation = params.inflation_percent / 100.0
            stock, phase = decline, "downturn"
        else:
            stock = (1.0 - drop) ** (-1.0 / params.recovery_years) - 1.0
            phase = "recovery"
        path.append({"year": year, "stock_return": stock, "bond_return": bond,
                     "inflation": inflation, "phase": phase})
    return path


def downturn_returns(plan_data: PlanData, path: list[dict]) -> dict[int, tuple]:
    """Override rows for every year of a ``downturn_path``."""
    return {
        entry["year"]: _override_row(plan_data, entry["year"], entry["stock_return"],
                                     entry["bond_return"], entry["inflation"],
                                     _plan_rates(plan_data, entry["year"])[2])
        for entry in path
    }


def apply_new_child(plan_data: PlanData, params: ScenarioParams) -> PlanData:
    """A child born in the start year: a cost for 18 years and a CTC dependent."""
    year = params.start_year
    start = MilestoneData(id="scenario_child_born", name="Child born",
                          trigger_type="date", trigger_date=f"{year:04d}-01-01")
    end = MilestoneData(id="scenario_child_grown", name="Child turns 18",
                        trigger_type="date", trigger_date=f"{year + CHILD_COST_YEARS:04d}-01-01")
    expense = ExpenseData(
        id="scenario_child_cost", name="Child", annual_amount=params.child_annual_cost,
        start_milestone_id=start.id, end_milestone_id=end.id,
        inflation_linked=True, category="essential",
    )
    settings = dict(plan_data.tax_settings or {})
    settings["dependent_birth_years"] = [*settings.get("dependent_birth_years", []), year]
    return replace(
        plan_data,
        milestones=[*plan_data.milestones, start, end],
        expenses=[*plan_data.expenses, expense],
        tax_settings=settings,
    )


def run_scenario_stress_test(plan_data: PlanData, preset: str, params: ScenarioParams) -> dict:
    """Run one hypothetical preset against a copy of the plan.

    Returns ``{"simulation_result": SimulationResult, "metadata": dict}``,
    the shape of the historical stress test.
    """
    if preset not in PRESETS:
        raise ScenarioInputError(f"Unknown stress preset: {preset}")
    first, last = plan_years(plan_data)
    if not first <= params.start_year <= last:
        raise ScenarioInputError(f"start_year must be between {first} and {last}")

    plan_copy = copy.deepcopy(plan_data)
    override = None
    if preset in ("job_loss", "tech_bust"):
        plan_copy = apply_job_loss(plan_copy, params)
    if preset in ("market_crash", "tech_bust"):
        override = crash_returns(plan_copy, params)
    if preset == "new_child":
        plan_copy = apply_new_child(plan_copy, params)
    path = None
    if preset == "downturn":
        path = downturn_path(plan_copy, params)
        override = downturn_returns(plan_copy, path)

    result = run_simulation(plan_copy, override_returns=override)
    if override is not None:
        # Shocked years carry the plan's own dividend split, not history.
        result.metadata.warnings = [w for w in result.metadata.warnings if w != DIVIDEND_YIELD_PROVENANCE]

    metadata: dict = {"preset": preset, "start_year": params.start_year}
    if preset in ("job_loss", "tech_bust"):
        metadata |= {"person": params.person, "months_without_pay": params.months_without_pay,
                     "resume_percent": params.resume_percent}
    if preset in ("market_crash", "tech_bust"):
        metadata["stock_drop_percent"] = params.stock_drop_percent
    if preset == "new_child":
        metadata |= {"child_annual_cost": params.child_annual_cost, "child_cost_years": CHILD_COST_YEARS}
    if preset == "downturn":
        metadata |= {"stock_drop_percent": params.stock_drop_percent,
                     "downturn_years": params.downturn_years, "recovery_years": params.recovery_years,
                     "bond_return_percent": params.bond_return_percent,
                     "inflation_percent": params.inflation_percent, "downturn_path": path}
    return {"simulation_result": result, "metadata": metadata}

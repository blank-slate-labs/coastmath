"""Monte Carlo simulation utilities.

Return sequences per trial from historical years (circular or moving block
bootstrap, chronological replay from each or a random start year, or
independent random years) and optional independent normal draws per
variable and for crypto,
plus aggregation of multiple trial results into percentile curves and
success/failure statistics, and a parallelised runner that orchestrates
many trials via ProcessPoolExecutor.
"""

from __future__ import annotations

import math
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor, wait
from dataclasses import dataclass
from itertools import pairwise
from numbers import Real

import numpy as np
import pandas as pd

from coastmath.engine.assumption_curves import resolve_assumption
from coastmath.engine.historical_data import load_historical_returns
from coastmath.engine.household_lifecycle import simulation_end_year
from coastmath.engine.milestone_statistics import milestone_distributions
from coastmath.engine.return_validation import validate_return_components
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import AssumptionData, PlanData
from coastmath.engine.withdrawal_strategy import WithdrawalStrategySpec
from coastmath.schemas.monte_carlo import (
    DEFAULT_BLOCK_LENGTH,
    ExtraMetric,
    FailureDetail,
    FailureMode,
    FailureTiming,
    MonteCarloResult,
    MonteCarloTrialDetail,
    OutcomeCategory,
    OutcomeDetail,
    OutcomeThresholds,
    PercentileCurves,
    SuccessTargets,
    SurplusClasses,
    TrialSummaries,
)
from coastmath.schemas.simulation import SimMetadata, SimulationResult


def validate_historical_returns(
    historical_data: pd.DataFrame,
    *,
    require_year: bool = False,
) -> None:
    """Validate return rows before they reach a simulation.

    Stock and bond inputs are total returns, so -100% is the lower bound.
    Inflation is a price-level change and must be strictly above -100%.
    Missing dividend yields remain allowed because the shipped history has
    years without a sourced yield; supplied yields must be finite and nonnegative.
    """
    if not isinstance(historical_data, pd.DataFrame) or historical_data.empty:
        raise ValueError("historical return data must contain at least one row")
    if not historical_data.columns.is_unique:
        raise ValueError("historical return data columns must be unique")

    required = {"stock_return", "bond_return", "inflation"}
    if require_year:
        required.add("year")
    missing = sorted(required.difference(historical_data.columns))
    if missing:
        raise ValueError(
            "historical return data is missing required columns: " + ", ".join(missing)
        )

    columns = ["stock_return", "bond_return", "inflation"]
    if "dividend_yield" in historical_data.columns:
        columns.append("dividend_yield")
    # Validate original scalar types before numeric conversion. Otherwise bools
    # and numeric strings pass here but reach a different domain downstream.
    for row in historical_data[columns].itertuples(index=True, name=None):
        index, stock, bond, inflation, *yields = row
        dividend = yields[0] if yields and not pd.isna(yields[0]) else None
        try:
            validate_return_components(stock, bond, inflation, dividend)
        except ValueError as exc:
            raise ValueError(f"historical return data row {index}: {exc}") from exc

    if require_year:
        years = historical_data["year"].tolist()
        if any(not isinstance(year, Real) or isinstance(year, bool)
               or not np.isfinite(year) or year != int(year) for year in years):
            raise ValueError("historical return data years must be finite integers")
        # Replay uses calendar offsets to index rows: gaps or duplicates would
        # silently select the wrong year or index beyond the provided history.
        ordered = sorted(years)
        if any(right - left != 1 for left, right in pairwise(ordered)):
            raise ValueError("historical return data years must be unique and consecutive")


def build_block_bootstrap_sequence(
    historical_data: pd.DataFrame,
    plan_years: int,
    block_size_range: tuple[int, int] = (3, 7),
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Build a synthetic return sequence by stitching random blocks.

    Uses circular block bootstrap: blocks that extend past the end of
    the data wrap around to the beginning, preserving intra-block
    autocorrelation structure.

    Parameters
    ----------
    historical_data:
        DataFrame with columns ``stock_return``, ``bond_return``, ``inflation``.
    plan_years:
        Number of simulated years to generate.
    block_size_range:
        Inclusive (min, max) range for random block lengths.
    rng:
        NumPy random generator for reproducibility.  When *None* a new
        unseeded generator is created.

    Returns
    -------
    np.ndarray
        Array of shape ``(plan_years, 3)`` with columns
        [stock_return, bond_return, inflation].
    """
    validate_historical_returns(historical_data)
    if rng is None:
        rng = np.random.default_rng()

    columns = ["stock_return", "bond_return", "inflation"]
    if "dividend_yield" in historical_data.columns:
        columns.append("dividend_yield")  # sampled with its year so income stays aligned
    data = historical_data[columns].to_numpy(dtype=float, na_value=np.nan)
    return data[block_bootstrap_indices(len(data), plan_years, block_size_range, rng)]


def block_bootstrap_indices(
    n_rows: int,
    plan_years: int,
    block_size_range: tuple[int, int],
    rng: np.random.Generator,
) -> np.ndarray:
    """Row indices for a circular block bootstrap.

    Each block draws its length, then its start row; a block running past the
    last row wraps to the first. The final block is truncated to the plan.
    """
    min_block, max_block = block_size_range
    result = np.empty(plan_years, dtype=np.int64)
    filled = 0
    while filled < plan_years:
        block_size = int(rng.integers(min_block, max_block + 1))
        start_idx = int(rng.integers(0, n_rows))
        indices = np.arange(start_idx, start_idx + block_size) % n_rows
        take = min(block_size, plan_years - filled)
        result[filled : filled + take] = indices[:take]
        filled += take
    return result


# ---------------------------------------------------------------------------
# Other sampling methods and parametric (normal) return sources
# ---------------------------------------------------------------------------

class MonteCarloInputError(ValueError):
    """Settings that cannot produce a run for this plan (reported as a 422)."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class MonteCarloTimeLimit(Exception):
    """The trials did not finish by the caller's deadline; the unstarted ones were cancelled."""


#: Sequence columns: stock total return, bond return, inflation, dividend yield.
STOCK, BOND, INFLATION, DIVIDEND = 0, 1, 2, 3
_SOURCE_COLUMNS = {"stocks": STOCK, "bonds": BOND, "inflation": INFLATION, "dividend_yield": DIVIDEND}


@dataclass(frozen=True, slots=True)
class ReturnSampling:
    """How a trial's yearly market returns are produced (pickle-safe).

    ``normal`` lists ``(column, mean, stdev)`` in decimals for every variable
    drawn from a normal distribution instead of the sampled historical year.
    Normal draws are independent across variables and years.
    """

    method: str = "block_bootstrap"
    block_length: int = 5
    on_data_end: str = "loop"
    iterations: int = 1
    normal: tuple[tuple[int, float, float], ...] = ()
    #: (mean, stdev) in decimals for cryptocurrency accounts, or None.
    crypto: tuple[float, float] | None = None

    @property
    def all_normal(self) -> bool:
        return len({column for column, _, _ in self.normal}) == len(_SOURCE_COLUMNS)

    @property
    def chronological(self) -> bool:
        return self.method in ("historical_sequential", "random_start") and not self.all_normal

    @classmethod
    def from_options(cls, options) -> ReturnSampling:
        """Build from a request carrying ``MonteCarloMethodOptions`` fields."""
        normal = []
        if options.sources is not None:
            for name, column in _SOURCE_COLUMNS.items():
                source = getattr(options.sources, name)
                if source.source == "normal":
                    normal.append((column, source.mean / 100, source.stdev / 100))
        normal.sort()
        crypto = (options.crypto.mean / 100, options.crypto.stdev / 100) if options.crypto else None
        return cls(
            method=options.sampling,
            block_length=options.block_length or DEFAULT_BLOCK_LENGTH,
            on_data_end=options.on_data_end or "loop",
            iterations=options.iterations or 1,
            normal=tuple(normal),
            crypto=crypto,
        )


DEFAULT_SAMPLING = ReturnSampling()


def moving_block_indices(
    n_rows: int, plan_years: int, block_length: int, rng: np.random.Generator,
) -> np.ndarray:
    """Fixed-length blocks of consecutive years that never wrap past the last year."""
    if block_length > n_rows:
        raise MonteCarloInputError(
            "block_length", f"block_length ({block_length}) exceeds the {n_rows} years of historical data")
    result = np.empty(plan_years, dtype=np.int64)
    filled = 0
    while filled < plan_years:
        start = int(rng.integers(0, n_rows - block_length + 1))
        take = min(block_length, plan_years - filled)
        result[filled : filled + take] = np.arange(start, start + take)
        filled += take
    return result


def chronological_indices(
    start: int, n_rows: int, plan_years: int, on_data_end: str, rng: np.random.Generator,
) -> np.ndarray:
    """Consecutive years from ``start``; after the last year loop, restart or stop."""
    result = np.empty(plan_years, dtype=np.int64)
    row = start
    for i in range(plan_years):
        if row >= n_rows:
            if on_data_end == "loop":
                row = 0
            elif on_data_end == "random_restart":
                row = int(rng.integers(0, n_rows))
            else:
                raise MonteCarloInputError("on_data_end", "the historical data ended before the projection")
        result[i] = row
        row += 1
    return result


def sequential_start_count(n_rows: int, plan_years: int, on_data_end: str) -> int:
    """Historical start years a ``historical_sequential`` run uses."""
    if on_data_end != "stop":
        return n_rows
    count = n_rows - plan_years + 1
    if count < 1:
        raise MonteCarloInputError(
            "on_data_end",
            f"The {n_rows} years of historical data are fewer than this {plan_years}-year "
            "projection, so no start year has enough data. Loop back or switch to a random year instead.",
        )
    return count


def monte_carlo_trial_count(sampling: ReturnSampling, n_rows: int, plan_years: int, n_trials: int) -> int:
    """Trials in a run: start years x iterations for ``historical_sequential``, else ``n_trials``."""
    if sampling.method == "historical_sequential" and not sampling.all_normal:
        return sequential_start_count(n_rows, plan_years, sampling.on_data_end) * sampling.iterations
    return n_trials


def sampled_row_indices(
    sampling: ReturnSampling,
    n_rows: int,
    plan_years: int,
    block_size_range: tuple[int, int],
    rng: np.random.Generator,
    trial_index: int,
) -> np.ndarray:
    """Historical row for each plan year under the sampling method.

    ``historical_sequential`` maps the trial index to its start year
    (``trial_index // iterations``) so every trial is reproducible from its
    index and seed alone.
    """
    method = sampling.method
    if method == "block_bootstrap":
        return block_bootstrap_indices(n_rows, plan_years, block_size_range, rng)
    if method == "moving_block":
        return moving_block_indices(n_rows, plan_years, sampling.block_length, rng)
    if method == "historical_sequential":
        start = trial_index // sampling.iterations
        if start >= sequential_start_count(n_rows, plan_years, sampling.on_data_end):
            raise MonteCarloInputError("index", "trial index is beyond the run's start years")
        return chronological_indices(start, n_rows, plan_years, sampling.on_data_end, rng)
    if method == "random_start":
        start = int(rng.integers(0, n_rows))
        return chronological_indices(start, n_rows, plan_years, "random_restart", rng)
    if method == "random_years":
        return rng.integers(0, n_rows, size=plan_years).astype(np.int64)
    raise ValueError(f"unknown sampling method {method!r}")


def apply_normal_sources(
    sequence: np.ndarray,
    normal: tuple[tuple[int, float, float], ...],
    rng: np.random.Generator,
) -> np.ndarray:
    """Replace the listed columns with independent yearly normal draws.

    Returns and inflation are clamped at -100% (inflation just above, so price
    levels stay positive); dividend yields at zero. Each yield is then capped
    by its year's stock total return so the derived price return stays at or
    above -100%.
    """
    out = np.array(sequence, dtype=np.float64, copy=True)
    if any(column == DIVIDEND for column, _, _ in normal) and out.shape[1] <= DIVIDEND:
        out = np.hstack([out, np.full((len(out), 1), np.nan)])
    if normal:
        draws = rng.normal(size=(len(out), len(normal)))
        for k, (column, mean, stdev) in enumerate(normal):
            values = mean + stdev * draws[:, k]
            if column == DIVIDEND:
                values = np.maximum(values, 0.0)
            elif column == INFLATION:
                values = np.maximum(values, _MIN_RATE)
            else:
                values = np.maximum(values, -1.0)
            out[:, column] = values
    if out.shape[1] > DIVIDEND:
        yields = out[:, DIVIDEND]
        known = ~np.isnan(yields)
        out[known, DIVIDEND] = np.minimum(yields[known], 1.0 + out[known, STOCK])
    return out


def crypto_returns(crypto: tuple[float, float], plan_years: int, rng: np.random.Generator) -> np.ndarray:
    """Independent yearly crypto total returns, clamped at -100%."""
    mean, stdev = crypto
    return np.maximum(mean + stdev * rng.normal(size=plan_years), -1.0)


# ---------------------------------------------------------------------------
# Calibration of sampled history to the plan's return assumptions
# ---------------------------------------------------------------------------

# Columns of the bootstrapped sequence that carry a rate the plan assumes.
_CALIBRATED_COLUMNS = 3  # stock_return (total), bond_return, inflation
_MIN_RATE = -0.999  # keep log(1 + r) finite for any historical loss

# A seeded run must give the same result on every host. NumPy picks SIMD
# kernels by CPU (SVML log1p/expm1 on AVX-512, and reductions whose summation
# order follows the vector width), which differ in the last bit. Calibration
# therefore calls the C library per element and sums with math.fsum, which is
# correctly rounded and so independent of summation order.
_log1p_ufunc = np.frompyfunc(math.log1p, 1, 1)
_expm1_ufunc = np.frompyfunc(math.expm1, 1, 1)


def _log1p(values: np.ndarray) -> np.ndarray:
    return _log1p_ufunc(values).astype(np.float64)


def _expm1(values: np.ndarray) -> np.ndarray:
    return _expm1_ufunc(values).astype(np.float64)


def _exact_mean(values: np.ndarray) -> float:
    return math.fsum(values.tolist()) / values.size


def plan_return_targets(plan_data: PlanData, plan_years: int, start_year: int) -> np.ndarray:
    """Per-year expected (stock total return, bond return, inflation) rates.

    Stock growth in the plan is price return; the assumed dividend yield is
    added so the target matches the total return recorded in the historical
    dataset, which the simulator later splits back into price and income.
    Assumption curves are honoured year by year.
    """
    assumptions = plan_data.assumptions or AssumptionData()
    curves = plan_data.assumption_curves or []
    rows = []
    for i in range(plan_years):
        year = start_year + i
        stock = (
            resolve_assumption(curves, "market_return", year, plan_data.birth_year, assumptions.stock_growth_rate)
            + resolve_assumption(curves, "dividend_yield", year, plan_data.birth_year, assumptions.stock_dividend_yield)
        )
        bond = resolve_assumption(curves, "bond_return", year, plan_data.birth_year, assumptions.bond_return_rate)
        inflation = resolve_assumption(curves, "inflation", year, plan_data.birth_year, assumptions.inflation_rate)
        rows.append((stock, bond, inflation))
    return np.array(rows, dtype=np.float64).reshape(-1, _CALIBRATED_COLUMNS)


def historical_log_means(values: np.ndarray) -> np.ndarray:
    """Mean of log(1 + r) for the stock, bond and inflation columns.

    Calibration centers historical log returns on the plan targets; it does
    not constrain any sampled path or the median portfolio outcome.
    """
    logs = _log1p(np.clip(values[:, :_CALIBRATED_COLUMNS], _MIN_RATE, None))
    return np.array([_exact_mean(logs[:, column]) for column in range(logs.shape[1])], dtype=np.float64)


def calibrate_sequence(
    sequence: np.ndarray,
    targets: np.ndarray,
    hist_log_means: np.ndarray,
) -> np.ndarray:
    """Shift sampled years so their compound return matches the plan.

    Each year's log return is moved by the same offset (plan target minus
    the historical geometric mean), which preserves the historical
    variation and within-block sequence in log space. It does not force the
    median portfolio path to equal the deterministic projection. Without this,
    the sampler reproduces the raw 1928-2024 averages (about 11.8% nominal
    for stocks) regardless of what the plan assumes.
    """
    out = np.array(sequence, dtype=np.float64, copy=True)
    n = len(out)
    logs = _log1p(np.clip(out[:, :_CALIBRATED_COLUMNS], _MIN_RATE, None))
    logs = logs - hist_log_means + _log1p(targets[:n])
    out[:, :_CALIBRATED_COLUMNS] = _expm1(logs)
    return out


def plan_dividend_yield_targets(plan_data: PlanData, plan_years: int, start_year: int) -> np.ndarray:
    """Per-year assumed stock dividend yield, honouring assumption curves."""
    assumptions = plan_data.assumptions or AssumptionData()
    curves = plan_data.assumption_curves or []
    return np.array([
        resolve_assumption(curves, "dividend_yield", start_year + i, plan_data.birth_year,
                           assumptions.stock_dividend_yield)
        for i in range(plan_years)
    ], dtype=np.float64)


def historical_mean_dividend_yield(values: np.ndarray) -> float | None:
    """Arithmetic mean of the recorded yields, or None when none are recorded."""
    if values.shape[1] <= _CALIBRATED_COLUMNS:
        return None
    recorded = values[:, _CALIBRATED_COLUMNS]
    recorded = recorded[~np.isnan(recorded)]
    mean = _exact_mean(recorded) if recorded.size else 0.0
    return mean if mean > 0 else None


def calibrate_dividend_yields(
    sequence: np.ndarray,
    yield_targets: np.ndarray,
    hist_mean_yield: float | None,
) -> np.ndarray:
    """Scale sampled dividend yields so they average the plan's assumed yield.

    The simulator takes price growth as the calibrated total return less the
    sampled yield. Calibration centers the total on market return plus the
    plan's yield, so the yield must be centered on the plan's yield too.
    Otherwise accounts that receive no stock dividend (crypto) or their own
    yield are centered about 3.65%/yr (the historical mean yield) below the
    deterministic projection. Scaling keeps each year's relative variation.
    Unrecorded years stay unknown and use the plan's yield in the simulator.
    """
    if hist_mean_yield is None or sequence.shape[1] <= _CALIBRATED_COLUMNS:
        return sequence
    out = np.array(sequence, dtype=np.float64, copy=True)
    n = len(out)
    scaled = out[:, _CALIBRATED_COLUMNS] * (yield_targets[:n] / hist_mean_yield)
    # Keep each row valid: a yield cannot be negative or exceed the total.
    out[:, _CALIBRATED_COLUMNS] = np.minimum(np.maximum(scaled, 0.0), 1.0 + out[:, 0])
    return out


def aggregate_results(
    all_results: list[SimulationResult],
    plan_years: int,
    failure_mode: FailureMode = "liquid_assets",
    success_targets: SuccessTargets | None = None,
    calibrated_to_plan: bool = True,
    outcome_thresholds: OutcomeThresholds | None = None,
    extra_metrics: list[ExtraMetric] | tuple[ExtraMetric, ...] = (),
    sampling: ReturnSampling = DEFAULT_SAMPLING,
) -> MonteCarloResult:
    """Aggregate multiple simulation trial results into summary statistics.

    Parameters
    ----------
    all_results:
        List of :class:`SimulationResult` from individual Monte Carlo trials.
    plan_years:
        Number of projection years (columns in the percentile matrix).
    failure_mode:
        How to detect trial failure.  ``"liquid_assets"`` (default) marks a
        trial as failed when total liquid account balances drop to zero or
        below — this correctly handles leveraged-but-solvent households.
        ``"net_worth"`` preserves legacy behaviour (net worth <= 0).

    Returns
    -------
    MonteCarloResult
        Percentile curves, success rate, and failure analysis.
    """
    n_trials = len(all_results)

    # Build 2D net-worth matrix: (n_trials, plan_years)
    net_worth_matrix = np.empty((n_trials, plan_years), dtype=np.float64)
    years: list[int] = []

    for i, result in enumerate(all_results):
        snapshots = result.yearly_snapshots
        n_snap = min(len(snapshots), plan_years)
        for j in range(n_snap):
            net_worth_matrix[i, j] = snapshots[j].net_worth
        # Pad with last value if fewer snapshots than plan_years
        if n_snap < plan_years:
            last_val = snapshots[-1].net_worth if snapshots else 0.0
            net_worth_matrix[i, n_snap:] = last_val
        # Capture year labels from the first trial
        if i == 0:
            years = [snapshots[j].year for j in range(n_snap)]
            if n_snap < plan_years:
                last_year = snapshots[-1].year if snapshots else 0
                years.extend(range(last_year + 1, last_year + 1 + plan_years - n_snap))

    # Percentile curves along the trial axis (axis=0)
    p10 = np.percentile(net_worth_matrix, 10, axis=0).tolist()
    p25 = np.percentile(net_worth_matrix, 25, axis=0).tolist()
    p50 = np.percentile(net_worth_matrix, 50, axis=0).tolist()
    p75 = np.percentile(net_worth_matrix, 75, axis=0).tolist()
    p90 = np.percentile(net_worth_matrix, 90, axis=0).tolist()

    percentile_curves = PercentileCurves(
        years=years, p10=p10, p25=p25, p50=p50, p75=p75, p90=p90,
    )

    # Failure analysis: trial fails when the chosen metric drops to zero
    failures: list[FailureDetail] = []
    for i, result in enumerate(all_results):
        snapshots = result.yearly_snapshots
        failed = False
        for snap in snapshots:
            if failure_mode == "liquid_assets":
                # Withdrawal-locked balances are not liquid while locked.
                metric = snap.liquid_account_total()
                cause = "liquid_assets_depleted"
            else:
                metric = snap.net_worth
                cause = "net_worth_depleted"
            if metric <= 0:
                failures.append(FailureDetail(
                    trial_index=i,
                    failure_year=snap.year,
                    failure_age=snap.age,
                    cause=cause,
                    net_worth_at_failure=snap.net_worth,
                ))
                failed = True
                break
        # Also check metadata.failure_year if engine flagged failure
        if not failed and result.metadata.failure_year is not None:
            # Find matching snapshot for age
            fy = result.metadata.failure_year
            age = 0
            for snap in snapshots:
                if snap.year == fy:
                    age = snap.age
                    break
            nw = net_worth_matrix[i, min(fy - years[0], plan_years - 1)] if years else 0.0
            failures.append(FailureDetail(
                trial_index=i,
                failure_year=fy,
                failure_age=age,
                cause="simulation_failure",
                net_worth_at_failure=nw,
            ))

    success_count = n_trials - len(failures)
    success_rate = success_count / n_trials if n_trials > 0 else 0.0

    # Outcome categories: every trial lands in exactly one. Funding failure
    # is never merged with target shortfalls or spending cuts.
    failed_trials = {f.trial_index for f in failures}
    targets = success_targets or SuccessTargets()
    counts = {"funding_failure": 0, "survived_below_target": 0, "survived_with_spending_cuts": 0, "met_targets": 0}
    outcomes: list[str] = []  # each trial's category key, for the trial explorer
    for i, result in enumerate(all_results):
        if i in failed_trials:
            counts["funding_failure"] += 1
            outcomes.append("funding_failure")
            continue
        final_nw = net_worth_matrix[i, -1]
        cuts = sum(s.flex_spending_reduction for s in result.yearly_snapshots)
        if targets.terminal_net_worth_min is not None and final_nw < targets.terminal_net_worth_min:
            key = "survived_below_target"
        elif targets.count_spending_cuts_as_shortfall and cuts > 0:
            key = "survived_with_spending_cuts"
        else:
            key = "met_targets"
        counts[key] += 1
        outcomes.append(key)
    target_label = (
        f"final net worth of at least ${targets.terminal_net_worth_min:,.0f} (nominal)"
        if targets.terminal_net_worth_min is not None else "no terminal target set"
    )
    outcome_categories = [
        OutcomeCategory(key="met_targets", label="Met all targets", count=counts["met_targets"],
                        rate=counts["met_targets"] / n_trials if n_trials else 0.0,
                        definition=f"No funding failure, {target_label}" + (", and no flexible-spending cuts" if targets.count_spending_cuts_as_shortfall else "") + "."),
        OutcomeCategory(key="survived_with_spending_cuts", label="Survived with spending cuts", count=counts["survived_with_spending_cuts"],
                        rate=counts["survived_with_spending_cuts"] / n_trials if n_trials else 0.0,
                        definition="No funding failure and target met, but flexible-spending rules cut discretionary spending in at least one year (counted only when enabled)."),
        OutcomeCategory(key="survived_below_target", label="Survived below target", count=counts["survived_below_target"],
                        rate=counts["survived_below_target"] / n_trials if n_trials else 0.0,
                        definition="No funding failure, but final net worth ended below the terminal target."),
        OutcomeCategory(key="funding_failure", label="Funding failure", count=counts["funding_failure"],
                        rate=counts["funding_failure"] / n_trials if n_trials else 0.0,
                        definition=("Liquid account balances" if failure_mode == "liquid_assets" else "Total net worth") + " reached zero, or the engine could not fund a mandatory outflow."),
    ]
    target_success_rate = (
        (counts["met_targets"] + (0 if targets.count_spending_cuts_as_shortfall else counts["survived_with_spending_cuts"])) / n_trials
        if n_trials and (targets.terminal_net_worth_min is not None or targets.count_spending_cuts_as_shortfall) else None
    )
    definitions = {
        "milestone_distributions": "Reach rates include all trials when every trial reports the milestone. Timing percentiles use observed years among reached trials only; unreached or unreported outcomes are not replaced with years.",
        "success_rate": "Share of trials that funded all required spending and avoided depletion under the selected failure definition.",
        "funding_success_rate": "Share of trials that never exhausted " + ("liquid accounts" if failure_mode == "liquid_assets" else "net worth") + " and funded every mandatory outflow.",
        "target_success_rate": "Share of trials that avoided funding failure and met your selected goals. Shown only when a goal is set.",
        "terminal_net_worth": "Net worth in the final projection year in nominal dollars of that year; inflation is not removed.",
        "market_returns": market_returns_definition(sampling, calibrated_to_plan),
    }

    # Final net worth stats from the last column
    final_col = net_worth_matrix[:, -1]
    median_final = float(np.percentile(final_col, 50))
    p10_final = float(np.percentile(final_col, 10))
    p90_final = float(np.percentile(final_col, 90))
    distributions = milestone_distributions(all_results)

    detail = outcome_detail(
        all_results, net_worth_matrix, years, failures, outcome_thresholds or OutcomeThresholds(),
    )
    metric_percentiles = (
        {metric: _metric_percentiles(all_results, metric, plan_years, years) for metric in extra_metrics}
        if extra_metrics else None
    )

    return MonteCarloResult(
        success_rate=success_rate,
        funding_success_rate=success_rate,
        target_success_rate=target_success_rate,
        outcome_categories=outcome_categories,
        success_targets=targets if success_targets is not None else None,
        definitions=definitions,
        n_trials=n_trials,
        percentile_curves=percentile_curves,
        failure_analysis=failures,
        milestone_distributions=distributions,
        median_final_net_worth=median_final,
        p10_final_net_worth=p10_final,
        p90_final_net_worth=p90_final,
        trials=_trial_summaries(
            all_results, net_worth_matrix, years, failures, outcomes,
            [d.id for d in distributions],
        ),
        sampling=sampling.method,
        outcome_detail=detail,
        metric_percentiles=metric_percentiles,
    )


_METHOD_DESCRIPTIONS = {
    "block_bootstrap": "Historical years are sampled in consecutive blocks.",
    "moving_block": "Historical years are sampled in fixed-length blocks of consecutive years that never wrap past the last year.",
    "historical_sequential": "Each trial replays history in order from a different start year.",
    "random_start": "Each trial replays history in order from a random start year, switching to another random year when the data ends.",
    "random_years": "Each plan year uses an independently chosen historical year.",
}


def market_returns_definition(sampling: ReturnSampling, calibrated_to_plan: bool) -> str:
    """How the run produced its market returns, for the result's definitions."""
    if sampling == DEFAULT_SAMPLING:
        # Unchanged wording for the default run (frozen baselines include it).
        return (
            "Historical years are sampled in consecutive blocks. Stock returns, bond returns and inflation are adjusted around your plan’s yearly assumptions using historical average compound rates. Each trial still has different market conditions and timing. The median balance can differ from the steady-return forecast because of return sequences, cash flows, taxes and a finite number of trials."
            if calibrated_to_plan else
            "Historical years are sampled in consecutive blocks without adjustment. Stock returns, bond returns and inflation come from the historical data instead of your plan’s assumptions for those rates. The median balance can differ from the steady-return forecast."
        )
    parts = []
    if not sampling.all_normal:
        parts.append(_METHOD_DESCRIPTIONS[sampling.method])
        parts.append(
            "Historical values are adjusted around your plan’s yearly assumptions using historical average compound rates."
            if calibrated_to_plan else
            "Historical values are used without adjustment to your plan’s assumptions."
        )
    if sampling.normal:
        names = {STOCK: "stock returns", BOND: "bond returns", INFLATION: "inflation", DIVIDEND: "dividend yields"}
        listed = ", ".join(names[column] for column, _, _ in sampling.normal)
        parts.append(f"These are drawn each year from independent normal distributions: {listed}. They are not adjusted.")
    if sampling.crypto is not None:
        parts.append("Cryptocurrency accounts grow by independent yearly normal draws.")
    parts.append("The median balance can differ from the steady-return forecast because of return sequences, cash flows, taxes and a finite number of trials.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Outcome detail: failure timing, surplus classes, extra metric percentiles
# ---------------------------------------------------------------------------

_RETIREMENT_NAME = re.compile(r"retire", re.IGNORECASE)
_PARTNER_NAME = re.compile(r"partner|spouse", re.IGNORECASE)


def _retirement_milestone(result, milestone_id: str | None = None) -> tuple[str, str, int | None] | None:
    """The retirement milestone and the year it fired.

    An explicit ``milestone_id`` wins when the plan has that milestone;
    otherwise the plan holder's retirement milestone is found by name.
    """
    outcomes = result.metadata.milestone_outcomes
    if milestone_id is not None:
        for item in outcomes:
            if item.id == milestone_id:
                return item.id, item.name, item.year
    for item in outcomes:
        if _RETIREMENT_NAME.search(item.name) and not _PARTNER_NAME.search(item.name):
            return item.id, item.name, item.year
    return None


def _real(snapshot) -> float:
    factor = snapshot.inflation_factor
    return snapshot.net_worth / factor if factor else snapshot.net_worth


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def outcome_detail(
    all_results: list,
    net_worth_matrix: np.ndarray,
    years: list[int],
    failures: list[FailureDetail],
    thresholds: OutcomeThresholds,
) -> OutcomeDetail:
    """Failure timing for failed trials and surplus classes for successful ones.

    A failure's timing is the share of projection years completed before its
    failure year. A successful trial compares its final net worth with its net
    worth at the end of the plan holder's retirement year (the milestone
    chosen in ``thresholds.retirement_milestone_id``, else the first milestone
    whose name mentions retirement and not a partner), or of the first
    projection year when there is none or it never fires. Both are in today's
    dollars of the trial's own inflation path, so inflation alone cannot move a
    trial between classes. A nonpositive reference net worth classes a trial
    as a thin margin when its final net worth is also nonpositive, otherwise
    as a moderate margin.
    """
    plan_years = net_worth_matrix.shape[1]
    first_year = years[0] if years else 0
    timing = {"early": 0, "mid": 0, "late": 0}
    for failure in failures:
        fraction = (failure.failure_year - first_year) / plan_years if plan_years else 0.0
        if fraction < thresholds.failure_early_fraction:
            timing["early"] += 1
        elif fraction >= thresholds.failure_late_fraction:
            timing["late"] += 1
        else:
            timing["mid"] += 1
    failed = {failure.trial_index for failure in failures}

    chosen = thresholds.retirement_milestone_id
    reference = _retirement_milestone(all_results[0], chosen) if all_results else None
    surplus = {"thin_margin": 0, "moderate_margin": 0, "wide_margin": 0}
    for i, result in enumerate(all_results):
        snapshots = result.yearly_snapshots
        if i in failed or not snapshots:
            continue
        milestone = _retirement_milestone(result, chosen)
        start = snapshots[0]
        if milestone is not None and milestone[2] is not None:
            start = next((snap for snap in snapshots if snap.year == milestone[2]), start)
        base = _real(start)
        final = _real(snapshots[-1])
        if base <= 0:
            key = "thin_margin" if final <= 0 else "moderate_margin"
        elif final < base * thresholds.thin_margin_percent / 100:
            key = "thin_margin"
        elif final > base * thresholds.wide_margin_percent / 100:
            key = "wide_margin"
        else:
            key = "moderate_margin"
        surplus[key] += 1
    n_failed = len(failures)
    n_success = sum(surplus.values())
    early_pct = f"{thresholds.failure_early_fraction:.0%}"
    late_pct = f"{thresholds.failure_late_fraction:.0%}"
    thin = f"{thresholds.thin_margin_percent:g}%"
    wide = f"{thresholds.wide_margin_percent:g}%"
    return OutcomeDetail(
        failure_timing=FailureTiming(
            early_fraction=thresholds.failure_early_fraction,
            late_fraction=thresholds.failure_late_fraction,
            **timing,
            early_rate=_rate(timing["early"], n_failed),
            mid_rate=_rate(timing["mid"], n_failed),
            late_rate=_rate(timing["late"], n_failed),
        ),
        surplus=SurplusClasses(
            thin_margin_percent=thresholds.thin_margin_percent,
            wide_margin_percent=thresholds.wide_margin_percent,
            reference_milestone_id=reference[0] if reference else None,
            reference_milestone_name=reference[1] if reference else None,
            **surplus,
            thin_margin_rate=_rate(surplus["thin_margin"], n_success),
            moderate_margin_rate=_rate(surplus["moderate_margin"], n_success),
            wide_margin_rate=_rate(surplus["wide_margin"], n_success),
        ),
        definitions={
            "failure_timing": (
                f"Failed trials by the share of projection years completed before the failure year: early below {early_pct}, "
                f"late from {late_pct}, mid in between. Rates are shares of failed trials."
            ),
            "surplus": (
                "Successful trials by final net worth relative to net worth at the end of the retirement year "
                "(or the first projection year), both in today’s dollars of each trial’s inflation path: "
                f"thin margin below {thin}, wide margin above {wide}, moderate margin in between. "
                "Rates are shares of successful trials."
            ),
        },
    )


def _metric_value(snapshot, metric: str) -> float:
    if metric == "liquid_net_worth":
        # Net worth without real assets: account balances less liabilities,
        # leaving out accounts the plan excludes from liquid net worth.
        return snapshot.net_worth - snapshot.real_assets_value - snapshot.liquid_excluded_total()
    if metric == "spending":
        return snapshot.expenses
    if metric == "taxes":
        return snapshot.taxes
    if metric == "income":
        return snapshot.gross_income
    raise ValueError(f"unknown metric {metric!r}")


def _metric_percentiles(all_results: list, metric: str, plan_years: int, years: list[int]) -> PercentileCurves:
    """p10-p90 by projection year of one snapshot metric, nominal dollars.

    A trial with fewer snapshots than the projection carries its last value,
    like the net worth curves.
    """
    matrix = np.zeros((len(all_results), plan_years), dtype=np.float64)
    for i, result in enumerate(all_results):
        snapshots = result.yearly_snapshots
        n_snap = min(len(snapshots), plan_years)
        for j in range(n_snap):
            matrix[i, j] = _metric_value(snapshots[j], metric)
        if 0 < n_snap < plan_years:
            matrix[i, n_snap:] = matrix[i, n_snap - 1]
    return PercentileCurves(
        years=list(years),
        **{f"p{q}": np.percentile(matrix, q, axis=0).tolist() for q in (10, 25, 50, 75, 90)},
    )


# ---------------------------------------------------------------------------
# Per-trial summaries for the trial explorer
# ---------------------------------------------------------------------------

SPARKLINE_POINTS = 24


def sparkline_indices(plan_years: int) -> list[int]:
    """Up to ``SPARKLINE_POINTS`` evenly spaced year columns, first and last included."""
    if plan_years <= SPARKLINE_POINTS:
        return list(range(plan_years))
    # Spacing exceeds one column, so rounding never produces duplicates.
    return [int(round(x)) for x in np.linspace(0, plan_years - 1, SPARKLINE_POINTS)]


def _three_significant_figures(value: float) -> int:
    """Whole dollars rounded to three significant figures: shape without bulk."""
    return int(float(f"{value:.3g}")) if np.isfinite(value) else 0


def _trial_summaries(
    all_results: list,
    net_worth_matrix: np.ndarray,
    years: list[int],
    failures: list[FailureDetail],
    outcomes: list[str],
    milestone_ids: list[str],
) -> TrialSummaries:
    """Columns describing each trial, derived from the values the aggregates use.

    ``ending_net_worth`` is the final column of the matrix behind the final
    percentiles; ``failure_year`` comes from ``failure_analysis``. Nothing here
    feeds back into an aggregate.
    """
    failure_year: list[int | None] = [None] * len(all_results)
    for failure in failures:
        failure_year[failure.trial_index] = failure.failure_year
    milestone_years: dict[str, list[int | None]] = {mid: [] for mid in milestone_ids}
    ending_liquid: list[float] = []
    for result in all_results:
        snapshots = result.yearly_snapshots
        ending_liquid.append(float(sum(snapshots[-1].accounts.values()) - snapshots[-1].liquid_excluded_total())
                             if snapshots else 0.0)
        reached = {item.id: item.year for item in result.metadata.milestone_outcomes}
        for mid, column in milestone_years.items():
            column.append(reached.get(mid))
    first = all_results[0].yearly_snapshots if all_results else []
    columns = sparkline_indices(net_worth_matrix.shape[1])
    return TrialSummaries(
        success=[year is None for year in failure_year],
        failure_year=failure_year,
        ending_net_worth=[float(v) for v in net_worth_matrix[:, -1]] if net_worth_matrix.shape[1] else [],
        ending_liquid=ending_liquid,
        outcome=outcomes,
        milestone_years=milestone_years,
        start_year=years[0] if years else 0,
        start_age=first[0].age if first else 0,
        sparkline_years=[years[j] for j in columns if j < len(years)],
        sparklines=[
            [_three_significant_figures(v) for v in row]
            for row in net_worth_matrix[:, columns].tolist()
        ],
    )


# ---------------------------------------------------------------------------
# Single-trial helper (top-level for pickle compatibility)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _TrialSnapshot:
    year: int
    age: int
    net_worth: float
    accounts: dict[str, float]
    flex_spending_reduction: float
    # Account balances excluding withdrawal-locked accounts (not liquid).
    liquid_assets: float
    # Outcome detail and extra metric inputs, same names as YearSnapshot.
    real_assets_value: float = 0.0
    expenses: float = 0.0
    taxes: float = 0.0
    gross_income: float = 0.0
    inflation_factor: float | None = None
    # Balances of accounts excluded from liquid net worth by their override.
    liquid_excluded: float = 0.0

    def liquid_account_total(self) -> float:
        """Same contract as ``YearSnapshot.liquid_account_total``."""
        return self.liquid_assets

    def liquid_excluded_total(self) -> float:
        """Same contract as ``YearSnapshot.liquid_excluded_total``."""
        return self.liquid_excluded


@dataclass(slots=True)
class _TrialResult:
    yearly_snapshots: list[_TrialSnapshot]
    metadata: SimMetadata


def _compact_trial(result: SimulationResult) -> _TrialResult:
    """Transfer only aggregation inputs across processes, preserving all values.

    Full snapshots contain item-level cash flows and tax breakdowns. Returning
    thousands of those Pydantic graphs spends time serializing data no Monte
    Carlo consumer uses. The canonical simulation and aggregation stay intact.
    """
    return _TrialResult([
        _TrialSnapshot(s.year, s.age, s.net_worth, s.accounts, s.flex_spending_reduction, s.liquid_account_total(),
                       s.real_assets_value, s.expenses, s.taxes, s.gross_income, s.inflation_factor,
                       s.liquid_excluded_total())
        for s in result.yearly_snapshots
    ], result.metadata)

@dataclass(frozen=True, slots=True)
class _TrialInputs:
    """Every trial argument except its seed and index (pickle-safe).

    The runner and :func:`replay_monte_carlo_trial` both build trials from
    :func:`_trial_inputs`, so a replayed trial receives exactly the inputs it
    had in its run.
    """

    plan_data: PlanData
    historical_values: np.ndarray
    plan_years: int
    start_year: int
    block_size_range: tuple[int, int]
    withdrawal_strategy: WithdrawalStrategySpec | None = None
    targets: np.ndarray | None = None
    hist_log_means: np.ndarray | None = None
    yield_targets: np.ndarray | None = None
    hist_mean_yield: float | None = None
    sampling: ReturnSampling = DEFAULT_SAMPLING
    first_data_year: int | None = None


def _run_single_trial(inputs: _TrialInputs, seed: int, trial_index: int = 0) -> _TrialResult:
    """Run one Monte Carlo trial: sample → calibrate → simulate.

    This function is top-level (not a closure or method) so it can be
    pickled by :class:`ProcessPoolExecutor`.
    """
    return _compact_trial(_simulate_trial(inputs, seed, trial_index)[0])


def trial_return_sequence(
    historical_values: np.ndarray,
    plan_years: int,
    block_size_range: tuple[int, int],
    rng: np.random.Generator,
    sampling: ReturnSampling = DEFAULT_SAMPLING,
    trial_index: int = 0,
    targets: np.ndarray | None = None,
    hist_log_means: np.ndarray | None = None,
    yield_targets: np.ndarray | None = None,
    hist_mean_yield: float | None = None,
) -> tuple[np.ndarray, np.ndarray | None, int | None]:
    """One trial's yearly returns, its crypto returns and its first historical row.

    Draw order is fixed so a trial depends only on its seed and index:
    historical rows first (none when every variable is normal), then the
    normal variables, then crypto. The default settings make exactly the
    draws of the original block bootstrap.
    """
    n_rows = len(historical_values)
    start_row: int | None = None
    if sampling.all_normal:
        sequence = np.full((plan_years, max(historical_values.shape[1], DIVIDEND + 1)), np.nan)
    else:
        indices = sampled_row_indices(sampling, n_rows, plan_years, block_size_range, rng, trial_index)
        sequence = historical_values[indices]
        if sampling.chronological and plan_years:
            start_row = int(indices[0])
        if targets is not None and hist_log_means is not None:
            # Normal columns are replaced below, so calibration reaches only
            # the historical variables.
            sequence = calibrate_sequence(sequence, targets, hist_log_means)
            if yield_targets is not None:
                sequence = calibrate_dividend_yields(sequence, yield_targets, hist_mean_yield)
    if sampling.normal:
        sequence = apply_normal_sources(sequence, sampling.normal, rng)
    crypto = crypto_returns(sampling.crypto, plan_years, rng) if sampling.crypto is not None else None
    return sequence, crypto, start_row


def _simulate_trial(
    inputs: _TrialInputs, seed: int, trial_index: int = 0,
) -> tuple[SimulationResult, int | None]:
    """One trial's full projection and its first historical year (chronological methods).

    Its own generator, seeded by ``seed`` alone, makes every draw, and the
    sequential start year comes from ``trial_index``, so a trial replays
    exactly without its neighbours.
    """
    rng = np.random.default_rng(seed)
    sequence, crypto, start_row = trial_return_sequence(
        inputs.historical_values, inputs.plan_years, inputs.block_size_range, rng, inputs.sampling, trial_index,
        inputs.targets, inputs.hist_log_means, inputs.yield_targets, inputs.hist_mean_yield,
    )

    # ndarray (plan_years, 3|4) → dict[year, (stock, bond, inflation, dividend_yield[, crypto])]
    has_yield = sequence.shape[1] > DIVIDEND
    override_returns: dict[int, tuple] = {}
    for i, row in enumerate(sequence):
        dividend = None if (not has_yield or np.isnan(row[DIVIDEND])) else float(row[DIVIDEND])
        values = (float(row[STOCK]), float(row[BOND]), float(row[INFLATION]), dividend)
        override_returns[inputs.start_year + i] = values + ((float(crypto[i]),) if crypto is not None else ())

    first_data_year = inputs.first_data_year
    historical_start_year = (
        first_data_year + start_row if first_data_year is not None and start_row is not None else None
    )
    simulation = run_simulation(
        inputs.plan_data, override_returns=override_returns, withdrawal_strategy=inputs.withdrawal_strategy,
    )
    return simulation, historical_start_year


# ---------------------------------------------------------------------------
# Main Monte Carlo runner
# ---------------------------------------------------------------------------

def run_monte_carlo(
    plan_data: PlanData,
    n_trials: int = 1000,
    block_size_range: tuple[int, int] = (3, 7),
    historical_data: pd.DataFrame | None = None,
    max_workers: int | None = None,
    seed: int | None = None,
    failure_mode: FailureMode = "liquid_assets",
    success_targets: SuccessTargets | None = None,
    withdrawal_strategy=None,
    calibrate_to_plan: bool = True,
    sampling: ReturnSampling = DEFAULT_SAMPLING,
    outcome_thresholds: OutcomeThresholds | None = None,
    extra_metrics: list[ExtraMetric] | tuple[ExtraMetric, ...] = (),
    deadline: float | None = None,
) -> MonteCarloResult:
    """Run a full Monte Carlo simulation with parallel trial execution.

    Parameters
    ----------
    plan_data:
        The financial plan to simulate.
    n_trials:
        Number of Monte Carlo trials to run.
    block_size_range:
        Inclusive (min, max) range for bootstrap block lengths.
    historical_data:
        Historical returns DataFrame.  When *None*, loads the built-in
        dataset via :func:`load_historical_returns`.
    max_workers:
        Maximum parallel processes.  Defaults to ``min(os.cpu_count(), 8)``.
    seed:
        Base random seed for reproducibility.  Each trial uses
        ``base_seed + trial_index``.  When *None*, a random base seed
        is generated.
    failure_mode:
        How to detect trial failure.  ``"liquid_assets"`` (default) checks
        liquid account balances; ``"net_worth"`` checks total net worth.
    calibrate_to_plan:
        When True (default) each sampled sequence is shifted so its
        long-run compound stock, bond and inflation rates equal the plan's
        assumptions (see :func:`calibrate_sequence`).  When False the raw
        historical averages are used and the plan's assumptions are ignored.
        Variables drawn from a normal distribution are never calibrated.
    sampling:
        Sampling method and per-variable return sources. The default is the
        circular block bootstrap of historical years. ``historical_sequential``
        runs one trial per start year (times its iterations) and ignores
        ``n_trials``; the result reports the actual count.
    outcome_thresholds, extra_metrics:
        Cut-offs for ``outcome_detail`` and the snapshot metrics to report
        per-year percentiles for.
    deadline:
        A :func:`time.monotonic` value. Trials not finished by then are
        cancelled and :class:`MonteCarloTimeLimit` is raised. None waits for all.

    Returns
    -------
    MonteCarloResult
        Aggregated percentile curves, success rate, and failure analysis.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be at least 1")
    if max_workers is None:
        max_workers = min(os.cpu_count() or 4, 8)

    trial_inputs = _trial_inputs(
        plan_data, historical_data, block_size_range, withdrawal_strategy, calibrate_to_plan, sampling,
    )
    plan_years = trial_inputs.plan_years
    n_trials = monte_carlo_trial_count(sampling, len(trial_inputs.historical_values), plan_years, n_trials)

    # Deterministic base seed
    if seed is not None:
        base_seed = seed
    else:
        base_seed = int(np.random.default_rng().integers(0, 2**32))

    # Run trials in parallel
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_run_single_trial, trial_inputs, base_seed + i, i)
            for i in range(n_trials)
        ]
        _, unfinished = wait(futures, timeout=None if deadline is None else max(0.0, deadline - time.monotonic()))
        if unfinished:
            # Only the trials already running finish; leaving the block waits for them.
            executor.shutdown(wait=False, cancel_futures=True)
            raise MonteCarloTimeLimit(f"{len(unfinished)} of {n_trials} trials were unfinished at the deadline")
        all_results = [f.result() for f in futures]

    result = aggregate_results(
        all_results, plan_years, failure_mode=failure_mode,
        success_targets=success_targets, calibrated_to_plan=calibrate_to_plan,
        outcome_thresholds=outcome_thresholds, extra_metrics=extra_metrics, sampling=sampling,
    )
    result.base_seed = base_seed
    return result


def _trial_inputs(
    plan_data: PlanData,
    historical_data: pd.DataFrame | None,
    block_size_range: tuple[int, int],
    withdrawal_strategy,
    calibrate_to_plan: bool,
    sampling: ReturnSampling = DEFAULT_SAMPLING,
) -> _TrialInputs:
    """Every trial argument except its seed, shared by the runner and the replay."""
    if historical_data is None:
        historical_data = load_historical_returns()
    validate_historical_returns(historical_data)

    plan_years = simulation_end_year(plan_data) - plan_data.start_year
    if plan_years <= 0:
        raise ValueError("Life expectancy must extend beyond the projection start age.")
    start_year = plan_data.start_year

    # Extract a numpy array for pickle-safe transfer
    hist_columns = ["stock_return", "bond_return", "inflation"]
    if "dividend_yield" in historical_data.columns:
        hist_columns.append("dividend_yield")
    hist_values = historical_data[hist_columns].to_numpy(dtype=float, na_value=np.nan)
    first_data_year = (
        int(historical_data["year"].iloc[0])
        if "year" in historical_data.columns and len(historical_data) else None
    )

    return _TrialInputs(
        plan_data=plan_data,
        historical_values=hist_values,
        plan_years=plan_years,
        start_year=start_year,
        block_size_range=block_size_range,
        withdrawal_strategy=withdrawal_strategy,
        targets=plan_return_targets(plan_data, plan_years, start_year) if calibrate_to_plan else None,
        hist_log_means=historical_log_means(hist_values) if calibrate_to_plan else None,
        yield_targets=plan_dividend_yield_targets(plan_data, plan_years, start_year) if calibrate_to_plan else None,
        hist_mean_yield=historical_mean_dividend_yield(hist_values) if calibrate_to_plan else None,
        sampling=sampling,
        first_data_year=first_data_year,
    )


def replay_monte_carlo_trial(
    plan_data: PlanData,
    index: int,
    base_seed: int,
    *,
    n_trials: int,
    block_size_range: tuple[int, int] = (3, 7),
    historical_data: pd.DataFrame | None = None,
    failure_mode: FailureMode = "liquid_assets",
    success_targets: SuccessTargets | None = None,
    withdrawal_strategy=None,
    calibrate_to_plan: bool = True,
    sampling: ReturnSampling = DEFAULT_SAMPLING,
    outcome_thresholds: OutcomeThresholds | None = None,
) -> MonteCarloTrialDetail:
    """Re-run trial ``index`` of a run that reported ``base_seed``, in process.

    Pass the run's own plan and settings. The trial's sampled history depends
    only on ``base_seed + index``, and its summary is classified by the same
    aggregation as the run, so it matches the run's ``trials`` entry exactly.
    """
    trial_inputs = _trial_inputs(
        plan_data, historical_data, block_size_range, withdrawal_strategy, calibrate_to_plan, sampling,
    )
    plan_years = trial_inputs.plan_years
    # A historical_sequential run's size comes from its start years, not the request.
    n_trials = monte_carlo_trial_count(sampling, len(trial_inputs.historical_values), plan_years, n_trials)
    if not 0 <= index < n_trials:
        raise MonteCarloInputError("index", f"trial index must be from 0 to {n_trials - 1}")
    seed = base_seed + index
    simulation, historical_start_year = _simulate_trial(trial_inputs, seed, index)
    single = aggregate_results(
        [simulation], plan_years, failure_mode=failure_mode,
        success_targets=success_targets, calibrated_to_plan=calibrate_to_plan,
        outcome_thresholds=outcome_thresholds, sampling=sampling,
    )
    summary = single.trials
    assert summary is not None
    failure = single.failure_analysis[0].model_copy(update={"trial_index": index}) if single.failure_analysis else None
    return MonteCarloTrialDetail(
        index=index,
        seed=seed,
        success=summary.success[0],
        failure=failure,
        outcome=summary.outcome[0],
        ending_net_worth=summary.ending_net_worth[0],
        ending_liquid=summary.ending_liquid[0],
        milestone_years={mid: years[0] for mid, years in summary.milestone_years.items()},
        simulation=simulation,
        historical_start_year=historical_start_year,
    )

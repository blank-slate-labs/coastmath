"""Monte Carlo sampling methods, normal return sources, crypto draws and outcome detail.

The default settings must keep producing the original block bootstrap; the
frozen aggregate baseline in ``test_monte_carlo_trial_explorer`` guards that
for whole runs, and ``test_default_indices_match_block_bootstrap`` guards the
draws themselves.
"""

from dataclasses import replace
from itertools import pairwise

import numpy as np
import pandas as pd
import pytest

from coastmath.engine.historical_data import load_historical_returns
from coastmath.engine.monte_carlo import (
    BOND,
    DIVIDEND,
    INFLATION,
    STOCK,
    MonteCarloInputError,
    ReturnSampling,
    _TrialResult,
    _TrialSnapshot,
    aggregate_results,
    apply_normal_sources,
    build_block_bootstrap_sequence,
    chronological_indices,
    crypto_returns,
    historical_log_means,
    monte_carlo_trial_count,
    moving_block_indices,
    replay_monte_carlo_trial,
    run_monte_carlo,
    sampled_row_indices,
    sequential_start_count,
    trial_return_sequence,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import AccountInfo
from coastmath.schemas.monte_carlo import (
    MAX_MONTE_CARLO_TRIALS,
    MAX_SEQUENTIAL_ITERATIONS,
    MonteCarloRequest,
    OutcomeThresholds,
)
from coastmath.schemas.simulation import MilestoneOutcome, SimMetadata
from tests.monte_carlo_trial_plan import trial_plan

N_ROWS = 97


def _history(n_rows: int = 20) -> np.ndarray:
    """Rows whose values encode their own index, so alignment is checkable."""
    rows = np.arange(n_rows, dtype=float)
    return np.column_stack([
        0.01 * rows,            # stock total return
        0.001 * rows,           # bond return
        0.0001 * rows,          # inflation
        0.00001 * rows,         # dividend yield
    ])


# ---------------------------------------------------------------------------
# Year sequences per method
# ---------------------------------------------------------------------------

def test_default_indices_match_block_bootstrap():
    data = _history(30)
    frame = pd.DataFrame(data, columns=["stock_return", "bond_return", "inflation", "dividend_yield"])
    expected = build_block_bootstrap_sequence(frame, 40, (3, 7), np.random.default_rng(11))
    sequence, crypto, start = trial_return_sequence(data, 40, (3, 7), np.random.default_rng(11))
    np.testing.assert_array_equal(sequence, expected)
    assert crypto is None and start is None


def test_moving_block_uses_fixed_consecutive_blocks_without_wrapping():
    rng = np.random.default_rng(4)
    indices = moving_block_indices(10, 23, 4, rng)
    assert len(indices) == 23
    for block_start in range(0, 23, 4):
        block = indices[block_start:block_start + 4]
        assert np.all(np.diff(block) == 1)  # consecutive, never wraps 9 -> 0
        assert block[0] <= 10 - 4
    with pytest.raises(MonteCarloInputError):
        moving_block_indices(10, 5, 11, rng)


def test_chronological_loop_stop_and_random_restart():
    rng = np.random.default_rng(1)
    assert chronological_indices(8, 10, 5, "loop", rng).tolist() == [8, 9, 0, 1, 2]
    with pytest.raises(MonteCarloInputError):
        chronological_indices(8, 10, 5, "stop", rng)
    restarted = chronological_indices(8, 10, 6, "random_restart", np.random.default_rng(1))
    jump = int(np.random.default_rng(1).integers(0, 10))
    assert restarted[:2].tolist() == [8, 9] and restarted[2] == jump
    # After the jump the sequence runs forward again (restarting once more at the end).
    for previous, current in pairwise(restarted[2:]):
        assert current == previous + 1 or previous == 9


def test_sequential_trial_count_and_start_year_per_trial():
    loop = ReturnSampling(method="historical_sequential")
    stop = ReturnSampling(method="historical_sequential", on_data_end="stop")
    repeated = ReturnSampling(method="historical_sequential", on_data_end="random_restart", iterations=3)
    assert monte_carlo_trial_count(loop, N_ROWS, 30, 1000) == N_ROWS
    assert monte_carlo_trial_count(stop, N_ROWS, 30, 1000) == N_ROWS - 30 + 1
    assert monte_carlo_trial_count(repeated, N_ROWS, 30, 1000) == N_ROWS * 3
    assert monte_carlo_trial_count(ReturnSampling(), N_ROWS, 30, 1000) == 1000
    with pytest.raises(MonteCarloInputError) as caught:
        sequential_start_count(N_ROWS, N_ROWS + 1, "stop")
    assert caught.value.field == "on_data_end"
    # Trial index -> start year (index // iterations); each start runs its iterations.
    for index in range(6):
        rows = sampled_row_indices(repeated, 10, 4, (3, 7), np.random.default_rng(index), index)
        assert rows[0] == index // 3
    # stop: the last start year still has data for the whole plan.
    last = sampled_row_indices(stop, 10, 4, (3, 7), np.random.default_rng(0), 6)
    assert last.tolist() == [6, 7, 8, 9]
    with pytest.raises(MonteCarloInputError):
        sampled_row_indices(stop, 10, 4, (3, 7), np.random.default_rng(0), 7)


def test_largest_sequential_run_stays_within_the_trial_cap():
    # Every start year times the most runs per start year must fit the cap that
    # bounds the run and its replay requests. Extending the data past 100 years
    # needs a lower MAX_SEQUENTIAL_ITERATIONS.
    widest = ReturnSampling(method="historical_sequential", on_data_end="random_restart",
                            iterations=MAX_SEQUENTIAL_ITERATIONS)
    n_rows = len(load_historical_returns())
    assert monte_carlo_trial_count(widest, n_rows, 1, 1) <= MAX_MONTE_CARLO_TRIALS


def test_random_start_and_random_years():
    start = sampled_row_indices(ReturnSampling(method="random_start"), 10, 25, (3, 7), np.random.default_rng(9), 0)
    first = int(np.random.default_rng(9).integers(0, 10))
    assert start[0] == first
    # Chronological until the data ends, then a random restart.
    assert start[: 10 - first].tolist() == list(range(first, 10))
    years = sampled_row_indices(ReturnSampling(method="random_years"), 10, 500, (3, 7), np.random.default_rng(2), 0)
    assert years.min() >= 0 and years.max() <= 9 and len(set(years.tolist())) == 10
    again = sampled_row_indices(ReturnSampling(method="random_years"), 10, 500, (3, 7), np.random.default_rng(2), 0)
    np.testing.assert_array_equal(years, again)


# ---------------------------------------------------------------------------
# Normal sources and crypto
# ---------------------------------------------------------------------------

def test_normal_draws_match_mean_and_stdev():
    normal = ((STOCK, 0.07, 0.15), (BOND, 0.03, 0.06), (INFLATION, 0.025, 0.01), (DIVIDEND, 0.02, 0.004))
    out = apply_normal_sources(np.zeros((200_000, 4)), normal, np.random.default_rng(5))
    for column, mean, stdev in normal:
        assert out[:, column].mean() == pytest.approx(mean, abs=0.002)
        assert out[:, column].std() == pytest.approx(stdev, rel=0.02)


def test_normal_draws_are_clamped():
    normal = ((STOCK, -0.9, 1.0), (BOND, -0.9, 1.0), (INFLATION, -0.9, 1.0), (DIVIDEND, -0.01, 0.5))
    out = apply_normal_sources(np.zeros((20_000, 4)), normal, np.random.default_rng(6))
    assert out[:, STOCK].min() == -1.0 and out[:, BOND].min() == -1.0
    assert out[:, INFLATION].min() > -1.0
    assert out[:, DIVIDEND].min() >= 0.0
    # The yield never exceeds the year's total stock return plus 100%.
    assert np.all(out[:, DIVIDEND] <= 1.0 + out[:, STOCK])
    assert crypto_returns((-0.5, 2.0), 10_000, np.random.default_rng(1)).min() == -1.0


def test_mixed_sources_keep_historical_variables_aligned_by_year():
    data = _history(20)
    sampling = ReturnSampling(method="random_years", normal=((STOCK, 0.08, 0.2),))
    sequence, _, _ = trial_return_sequence(data, 300, (3, 7), np.random.default_rng(3), sampling)
    rows = np.rint(sequence[:, BOND] / 0.001)
    np.testing.assert_allclose(sequence[:, INFLATION], rows * 0.0001)
    np.testing.assert_allclose(sequence[:, DIVIDEND], np.minimum(rows * 0.00001, 1 + sequence[:, STOCK]))
    # Historical rows come from the method's own draws, made before any normal draw.
    expected_rows = np.random.default_rng(3).integers(0, 20, size=300)
    np.testing.assert_array_equal(rows, expected_rows)
    assert sequence[:, STOCK].std() > 0.15


def test_calibration_skips_normal_variables():
    data = _history(20) + np.array([0.05, 0.02, 0.01, 0.02])
    sampling = ReturnSampling(method="random_years", normal=((BOND, 0.03, 0.05),))
    targets = np.tile([0.09, 0.04, 0.02], (50, 1))
    raw, _, _ = trial_return_sequence(data, 50, (3, 7), np.random.default_rng(8), sampling)
    calibrated, _, _ = trial_return_sequence(
        data, 50, (3, 7), np.random.default_rng(8), sampling,
        targets=targets, hist_log_means=historical_log_means(data),
    )
    np.testing.assert_array_equal(raw[:, BOND], calibrated[:, BOND])
    assert not np.allclose(raw[:, STOCK], calibrated[:, STOCK])


def test_all_normal_ignores_the_sampling_method():
    normal = ((STOCK, 0.07, 0.15), (BOND, 0.03, 0.06), (INFLATION, 0.025, 0.01), (DIVIDEND, 0.02, 0.004))
    sequential = ReturnSampling(method="historical_sequential", on_data_end="stop", normal=normal)
    assert sequential.all_normal and not sequential.chronological
    assert monte_carlo_trial_count(sequential, N_ROWS, 200, 12) == 12
    a, _, start = trial_return_sequence(_history(), 200, (3, 7), np.random.default_rng(1), sequential)
    b, _, _ = trial_return_sequence(_history(), 200, (3, 7), np.random.default_rng(1), ReturnSampling(normal=normal))
    np.testing.assert_array_equal(a, b)
    assert start is None


def _crypto_plan():
    plan = trial_plan()
    plan.accounts["coins"] = AccountInfo(50_000, "cryptocurrency", cost_basis=40_000)
    return plan


def test_crypto_return_applies_only_to_crypto_accounts():
    plan = _crypto_plan()
    rows = dict.fromkeys(range(2026, 2054), (0.05, 0.03, 0.02, 0.02))
    base = run_simulation(plan, override_returns=rows)
    boom = run_simulation(plan, override_returns={year: row + (0.5,) for year, row in rows.items()})
    first, boom_first = base.yearly_snapshots[0], boom.yearly_snapshots[0]
    assert first.accounts["brokerage"] == boom_first.accounts["brokerage"]
    assert boom_first.accounts["coins"] == pytest.approx(50_000 * 1.5)
    assert first.accounts["coins"] == pytest.approx(50_000 * 1.03)  # stock price return
    # Even a fixed account rate gives way to the sampled crypto return.
    plan.accounts["coins"].investment_settings = {"stock_growth_rate": 0.01}
    fixed = run_simulation(plan, override_returns={year: row + (0.5,) for year, row in rows.items()})
    assert fixed.yearly_snapshots[0].accounts["coins"] == pytest.approx(50_000 * 1.5)
    # A None crypto return keeps today's treatment, and deterministic runs ignore none of it.
    same = run_simulation(_crypto_plan(), override_returns={year: row + (None,) for year, row in rows.items()})
    assert same.yearly_snapshots[0].accounts == first.accounts
    assert run_simulation(_crypto_plan()).model_dump() == run_simulation(_crypto_plan()).model_dump()


def test_override_rows_reject_invalid_crypto_returns():
    with pytest.raises(ValueError, match="crypto"):
        run_simulation(_crypto_plan(), override_returns={2026: (0.05, 0.03, 0.02, 0.02, -1.5)})


# ---------------------------------------------------------------------------
# Whole runs: determinism and replay per method
# ---------------------------------------------------------------------------

NORMAL_STOCKS = ((STOCK, 0.07, 0.16),)
METHODS = {
    "moving_block": ReturnSampling(method="moving_block", block_length=4),
    "sequential_loop": ReturnSampling(method="historical_sequential"),
    "sequential_restart": ReturnSampling(method="historical_sequential", on_data_end="random_restart", iterations=2),
    "random_start": ReturnSampling(method="random_start"),
    "random_years": ReturnSampling(method="random_years", normal=NORMAL_STOCKS, crypto=(0.15, 0.6)),
    "bootstrap_crypto": ReturnSampling(crypto=(0.15, 0.6)),
}


@pytest.mark.parametrize("name", list(METHODS))
def test_replay_is_exact_for_every_method(name):
    sampling = METHODS[name]
    plan = _crypto_plan()
    result = run_monte_carlo(plan, n_trials=5, seed=77, max_workers=2, sampling=sampling)
    assert result.sampling == sampling.method
    expected = {"sequential_loop": N_ROWS, "sequential_restart": N_ROWS * 2}.get(name, 5)
    assert result.n_trials == len(result.trials.ending_net_worth) == expected
    for index in (0, 3, result.n_trials - 1):
        detail = replay_monte_carlo_trial(_crypto_plan(), index, result.base_seed,
                                          n_trials=result.n_trials, sampling=sampling)
        assert detail.ending_net_worth == result.trials.ending_net_worth[index]
        assert detail.outcome == result.trials.outcome[index]
        if name.startswith("sequential"):
            per_start = sampling.iterations
            assert detail.historical_start_year == 1928 + index // per_start
        elif name == "random_start":
            assert detail.historical_start_year is not None
        else:
            assert detail.historical_start_year is None
    again = run_monte_carlo(_crypto_plan(), n_trials=5, seed=77, max_workers=2, sampling=sampling)
    assert again.trials.ending_net_worth == result.trials.ending_net_worth


def test_sequential_trials_loop_through_history_in_order():
    sampling = ReturnSampling(method="historical_sequential", on_data_end="stop")
    result = run_monte_carlo(trial_plan(), n_trials=1, seed=1, max_workers=2, sampling=sampling,
                             calibrate_to_plan=False)
    plan_years = len(result.percentile_curves.years)
    assert result.n_trials == N_ROWS - plan_years + 1
    with pytest.raises(MonteCarloInputError):
        replay_monte_carlo_trial(trial_plan(), result.n_trials, 1, n_trials=result.n_trials, sampling=sampling)


def test_crypto_distribution_changes_only_crypto_balances():
    plain = run_monte_carlo(_crypto_plan(), n_trials=3, seed=5, max_workers=2)
    crypto = run_monte_carlo(_crypto_plan(), n_trials=3, seed=5, max_workers=2, sampling=ReturnSampling(crypto=(0.3, 0.0)))
    for index in range(3):
        a = replay_monte_carlo_trial(_crypto_plan(), index, 5, n_trials=3)
        b = replay_monte_carlo_trial(_crypto_plan(), index, 5, n_trials=3, sampling=ReturnSampling(crypto=(0.3, 0.0)))
        assert a.simulation.yearly_snapshots[0].accounts["brokerage"] == b.simulation.yearly_snapshots[0].accounts["brokerage"]
        assert b.simulation.yearly_snapshots[0].accounts["coins"] == pytest.approx(50_000 * 1.3)
    assert plain.trials.ending_net_worth != crypto.trials.ending_net_worth


def test_options_map_to_sampling():
    body = MonteCarloRequest.model_validate({
        "sampling": "historical_sequential", "on_data_end": "random_restart", "iterations": 4,
        "sources": {"bonds": {"source": "normal", "mean": 4, "stdev": 7},
                    "stocks": {"source": "normal", "mean": 9, "stdev": 18}},
        "crypto": {"mean": 20, "stdev": 70},
    })
    sampling = ReturnSampling.from_options(body)
    assert sampling == ReturnSampling(
        method="historical_sequential", on_data_end="random_restart", iterations=4,
        normal=((STOCK, 0.09, 0.18), (BOND, 0.04, 0.07)), crypto=(0.2, 0.7),
    )
    default = ReturnSampling.from_options(MonteCarloRequest())
    assert default == ReturnSampling()
    assert replace(ReturnSampling.from_options(MonteCarloRequest(sampling="moving_block")), method="x").block_length == 5


# ---------------------------------------------------------------------------
# Outcome detail and extra metric percentiles
# ---------------------------------------------------------------------------

def _trial(net_worths, *, retire_year=None, inflation=None, start=2030, expenses=None, liquid=None):
    snapshots = []
    for j, value in enumerate(net_worths):
        factor = (1 + inflation) ** j if inflation is not None else None
        cash = float(value) if liquid is None else liquid
        snapshots.append(_TrialSnapshot(start + j, 50 + j, float(value), {"cash": cash}, 0.0, cash,
                                        real_assets_value=10.0, expenses=float(expenses[j]) if expenses else 0.0,
                                        taxes=1.0 * j, gross_income=2.0 * j, inflation_factor=factor))
    outcomes = [MilestoneOutcome(id="partner", name="Partner retires", trigger_type="age", year=start + 1),
                MilestoneOutcome(id="ret", name="Retirement", trigger_type="age", year=retire_year)]
    metadata = SimMetadata(plan_id="00000000-0000-4000-8000-000000000003", start_year=start,
                           end_year=start + len(net_worths) - 1, milestone_outcomes=outcomes)
    return _TrialResult(snapshots, metadata)


def test_failure_timing_and_surplus_classes():
    trials = [
        _trial([100, -1, -1, -1, -1, -1, -1, -1, -1, -1]),        # fails in year 1 of 10: early
        _trial([100, 90, 80, 70, -1, -1, -1, -1, -1, -1]),        # year 4: 0.4 -> mid
        _trial([100] * 7 + [-1, -1, -1]),                         # year 7: 0.7 -> late
        _trial([100, 100, 1000, 900, 800, 700, 600, 500, 400, 200], retire_year=2032),  # 200/1000: thin margin
        _trial([100, 100, 1000, 900, 800, 700, 600, 500, 400, 300], retire_year=2032),  # 30%: moderate margin
        _trial([100] * 9 + [250]),                                # no retirement year fired: vs first year -> wide margin
        # Home equity underwater at first, liquid savings intact: a nonpositive
        # reference with a positive final net worth is a moderate margin.
        _trial([-50] * 9 + [5], liquid=1.0),
    ]
    detail = aggregate_results(trials, 10).outcome_detail
    timing = detail.failure_timing
    assert (timing.early, timing.mid, timing.late) == (1, 1, 1)
    assert timing.early_rate == pytest.approx(1 / 3)
    surplus = detail.surplus
    assert (surplus.thin_margin, surplus.moderate_margin, surplus.wide_margin) == (1, 2, 1)
    assert surplus.reference_milestone_id == "ret"  # the partner's milestone is skipped
    assert surplus.wide_margin_rate == pytest.approx(0.25)
    custom = aggregate_results(trials, 10, outcome_thresholds=OutcomeThresholds(
        failure_early_fraction=0.5, failure_late_fraction=0.9, thin_margin_percent=35, wide_margin_percent=300,
    )).outcome_detail
    assert (custom.failure_timing.early, custom.failure_timing.mid, custom.failure_timing.late) == (2, 1, 0)
    assert (custom.surplus.thin_margin, custom.surplus.moderate_margin, custom.surplus.wide_margin) == (2, 2, 0)


def test_surplus_uses_the_chosen_retirement_milestone():
    # Net worth peaks in 2031 (the partner's milestone) and ends at 200.
    trial = _trial([100, 1000, 400, 200], retire_year=2032)
    default = aggregate_results([trial], 4).outcome_detail.surplus
    assert default.reference_milestone_id == "ret"
    assert default.moderate_margin == 1  # 200 / 400
    chosen = aggregate_results([trial], 4, outcome_thresholds=OutcomeThresholds(
        retirement_milestone_id="partner",
    )).outcome_detail.surplus
    assert (chosen.reference_milestone_id, chosen.reference_milestone_name) == ("partner", "Partner retires")
    assert chosen.thin_margin == 1  # 200 / 1000
    # A choice the plan no longer has falls back to the name match.
    stale = aggregate_results([trial], 4, outcome_thresholds=OutcomeThresholds(
        retirement_milestone_id="deleted",
    )).outcome_detail.surplus
    assert stale.reference_milestone_id == "ret" and stale.moderate_margin == 1


def test_surplus_compares_todays_dollars():
    # Nominal growth of exactly the inflation rate is no real surplus at all.
    flat_real = _trial([100 * 1.1 ** j for j in range(12)], inflation=0.10)
    detail = aggregate_results([flat_real], 12).outcome_detail
    assert detail.surplus.moderate_margin == 1 and detail.surplus.wide_margin == 0


def test_extra_metric_percentiles_only_when_requested():
    trials = [_trial([100 + 10 * i] * 5, expenses=[5 * i] * 5) for i in range(11)]
    assert aggregate_results(trials, 5).metric_percentiles is None
    result = aggregate_results(trials, 5, extra_metrics=["liquid_net_worth", "spending", "taxes", "income"])
    curves = result.metric_percentiles
    assert set(curves) == {"liquid_net_worth", "spending", "taxes", "income"}
    assert curves["liquid_net_worth"].p50 == [140.0] * 5  # median 150 less 10 of real assets
    assert curves["spending"].p10 == [5.0] * 5 and curves["spending"].p90 == [45.0] * 5
    assert curves["taxes"].p50 == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert curves["income"].years == result.percentile_curves.years


def test_payload_with_every_extra_metric_at_ten_thousand_trials():
    rng = np.random.default_rng(3)
    years = 60
    metadata = SimMetadata(plan_id="00000000-0000-4000-8000-000000000002", start_year=2026, end_year=2085)
    results = []
    for _ in range(10_000):
        path = 1_000_000 * np.cumprod(1 + rng.normal(0.03, 0.12, years))
        results.append(_TrialResult([
            _TrialSnapshot(2026 + j, 40 + j, float(v), {"cash": float(v)}, 0.0, float(v),
                           expenses=60_000.0, taxes=10_000.0, gross_income=80_000.0, inflation_factor=1.0)
            for j, v in enumerate(path)
        ], metadata))
    result = aggregate_results(results, years, extra_metrics=["liquid_net_worth", "spending", "taxes", "income"])
    assert len(result.model_dump_json()) < 4_000_000

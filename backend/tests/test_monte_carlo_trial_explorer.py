"""Per-trial Monte Carlo summaries and exact single-trial replay.

The frozen baseline in ``fixtures/monte_carlo_trial_baseline.json`` was
captured from ``origin/main`` at f74d6cd, before trial summaries existed, so
it proves the aggregate outputs did not move for a given seed. Floats are
compared to a relative 1e-6 (a cent on $10,000): CPUs and math libraries round
transcendental functions differently (macOS arm64 vs Linux x86-64 differ near
1e-14), while a real change moves results by far more.
"""

import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from coastmath.engine.monte_carlo import (
    SPARKLINE_POINTS,
    _TrialResult,
    _TrialSnapshot,
    aggregate_results,
    replay_monte_carlo_trial,
    run_monte_carlo,
    sparkline_indices,
)
from coastmath.schemas.monte_carlo import SuccessTargets
from coastmath.schemas.simulation import MilestoneOutcome, SimMetadata
from tests.monte_carlo_trial_plan import BASELINE_RUNS, trial_plan

BASELINE = json.loads((Path(__file__).parent / "fixtures" / "monte_carlo_trial_baseline.json").read_text())
RUNS = dict(BASELINE_RUNS)


@pytest.fixture(scope="module")
def runs():
    return {name: run_monte_carlo(trial_plan(), max_workers=2, **kwargs) for name, kwargs in BASELINE_RUNS}


def _assert_matches_baseline(current, baseline, path="result"):
    """Same structure and exact non-float values; floats within host rounding."""
    if isinstance(baseline, float) and isinstance(current, (int, float)) and not isinstance(current, bool):
        assert math.isclose(current, baseline, rel_tol=1e-6, abs_tol=1e-6), f"{path}: {current} != {baseline}"
    elif isinstance(baseline, dict):
        assert isinstance(current, dict) and current.keys() == baseline.keys(), f"{path}: keys differ"
        for key, value in baseline.items():
            _assert_matches_baseline(current[key], value, f"{path}.{key}")
    elif isinstance(baseline, list):
        assert isinstance(current, list) and len(current) == len(baseline), f"{path}: lengths differ"
        for i, value in enumerate(baseline):
            _assert_matches_baseline(current[i], value, f"{path}[{i}]")
    else:
        assert current == baseline, f"{path}: {current!r} != {baseline!r}"


def _replay(name: str, result, index: int):
    kwargs = dict(RUNS[name])
    kwargs.pop("seed")
    return replay_monte_carlo_trial(trial_plan(), index, result.base_seed, **kwargs)


@pytest.mark.parametrize("name", list(RUNS))
def test_seeded_aggregates_are_unchanged(runs, name):
    # Additive result fields are excluded by name; everything else is frozen.
    additive = {"base_seed", "trials", "sampling", "outcome_detail", "metric_percentiles"}
    current = json.loads(runs[name].model_dump_json(exclude=additive))
    _assert_matches_baseline(current, BASELINE[name])


@pytest.mark.parametrize("name", list(RUNS))
def test_summaries_describe_every_trial_consistently_with_aggregates(runs, name):
    result = runs[name]
    trials = result.trials
    n = result.n_trials
    assert result.base_seed == RUNS[name]["seed"]
    for column in (trials.success, trials.failure_year, trials.ending_net_worth, trials.ending_liquid,
                   trials.outcome, trials.sparklines):
        assert len(column) == n
    assert sum(trials.success) / n == result.success_rate
    assert {i: y for i, y in enumerate(trials.failure_year) if y is not None} == {
        f.trial_index: f.failure_year for f in result.failure_analysis
    }
    assert Counter(trials.outcome) == {c.key: c.count for c in result.outcome_categories if c.count}
    assert [o == "funding_failure" for o in trials.outcome] == [not s for s in trials.success]
    ending = np.array(trials.ending_net_worth)
    assert float(np.percentile(ending, 50)) == result.median_final_net_worth
    assert float(np.percentile(ending, 10)) == result.p10_final_net_worth
    for distribution in result.milestone_distributions:
        years = [y for y in trials.milestone_years[distribution.id] if y is not None]
        assert len(years) == distribution.reached_trials
        assert dict(Counter(years)) == distribution.year_counts
    assert trials.start_year == result.percentile_curves.years[0]
    assert trials.start_age == 60
    assert trials.sparkline_years[0] == result.percentile_curves.years[0]
    assert trials.sparkline_years[-1] == result.percentile_curves.years[-1]
    assert all(len(row) == len(trials.sparkline_years) <= SPARKLINE_POINTS for row in trials.sparklines)


def test_runs_include_successful_and_failed_trials(runs):
    # The replay tests below need both kinds in each run.
    for result in runs.values():
        assert 0 < sum(result.trials.success) < result.n_trials


@pytest.mark.parametrize("name", list(RUNS))
def test_replay_reproduces_trials_exactly(runs, name):
    result = runs[name]
    trials = result.trials
    failed = [i for i, ok in enumerate(trials.success) if not ok]
    succeeded = [i for i, ok in enumerate(trials.success) if ok]
    indices = sorted({0, failed[0], failed[-1], succeeded[-1], result.n_trials - 1})
    failures = {f.trial_index: f for f in result.failure_analysis}
    for index in indices:
        detail = _replay(name, result, index)
        assert detail.index == index and detail.seed == result.base_seed + index
        assert detail.ending_net_worth == trials.ending_net_worth[index]
        assert detail.ending_liquid == trials.ending_liquid[index]
        assert detail.success == trials.success[index]
        assert detail.outcome == trials.outcome[index]
        assert detail.failure == failures.get(index)
        assert detail.milestone_years == {mid: years[index] for mid, years in trials.milestone_years.items()}
        path = {s.year: s.net_worth for s in detail.simulation.yearly_snapshots}
        assert detail.simulation.yearly_snapshots[-1].net_worth == trials.ending_net_worth[index]
        assert [int(float(f"{path[y]:.3g}")) for y in trials.sparkline_years] == trials.sparklines[index]


def test_replay_uses_drawn_seed_and_run_targets():
    # No requested seed: the run reports the seed it drew, and that seed replays.
    targets = SuccessTargets(terminal_net_worth_min=900_000, count_spending_cuts_as_shortfall=True)
    result = run_monte_carlo(trial_plan(), n_trials=6, max_workers=2, block_size_range=(1, 9),
                             success_targets=targets)
    assert result.base_seed is not None and 0 <= result.base_seed < 2**32
    for index in (2, 5):
        detail = replay_monte_carlo_trial(trial_plan(), index, result.base_seed, n_trials=6,
                                          block_size_range=(1, 9), success_targets=targets)
        assert detail.ending_net_worth == result.trials.ending_net_worth[index]
        assert detail.outcome == result.trials.outcome[index]


def test_replay_does_not_depend_on_other_trials():
    # Each trial's generator is seeded from base_seed + index alone; a run of a
    # different size shares the leading trials exactly.
    small = run_monte_carlo(trial_plan(), n_trials=3, seed=11, max_workers=1)
    large = run_monte_carlo(trial_plan(), n_trials=8, seed=11, max_workers=2)
    assert small.trials.ending_net_worth == large.trials.ending_net_worth[:3]
    assert small.trials.sparklines == large.trials.sparklines[:3]


@pytest.mark.parametrize("index", [-1, 5])
def test_replay_rejects_an_index_outside_the_run(index):
    with pytest.raises(ValueError, match="trial index"):
        replay_monte_carlo_trial(trial_plan(), index, 1, n_trials=5)


def test_sparkline_indices_cover_first_and_last_year():
    assert sparkline_indices(5) == [0, 1, 2, 3, 4]
    assert sparkline_indices(24) == list(range(24))
    long = sparkline_indices(61)
    assert len(long) == SPARKLINE_POINTS == len(set(long))
    assert long[0] == 0 and long[-1] == 60
    assert sparkline_indices(0) == []


def test_payload_size_at_ten_thousand_trials():
    """A 10,000-trial, 60-year run with two milestones stays near 2.6 MB."""
    rng = np.random.default_rng(3)
    years = list(range(2026, 2086))
    results = []
    for i in range(10_000):
        path = 1_000_000 * np.cumprod(1 + rng.normal(0.03, 0.12, len(years)))
        if i % 4 == 0:
            path[40:] = -rng.uniform(1_000, 400_000)  # a quarter fail
        snapshots = [_TrialSnapshot(y, 40 + j, float(v), {"cash": float(v)}, 0.0, float(v))
                     for j, (y, v) in enumerate(zip(years, path, strict=True))]
        metadata = SimMetadata(plan_id="00000000-0000-4000-8000-000000000002", start_year=2026, end_year=2085,
                               milestone_outcomes=[
                                   MilestoneOutcome(id="retire", name="Retire", trigger_type="age", year=2051),
                                   MilestoneOutcome(id="fi", name="FI", trigger_type="net_worth",
                                                    year=None if i % 3 == 0 else 2040 + i % 20),
                               ])
        results.append(_TrialResult(snapshots, metadata))
    result = aggregate_results(results, len(years))
    trials_bytes = len(result.trials.model_dump_json())
    total_bytes = len(result.model_dump_json())
    print(f"10,000 trials: trials {trials_bytes / 1e6:.2f} MB, whole result {total_bytes / 1e6:.2f} MB")
    assert len(result.trials.sparklines) == 10_000
    assert trials_bytes < 3_000_000
    assert total_bytes < 4_000_000

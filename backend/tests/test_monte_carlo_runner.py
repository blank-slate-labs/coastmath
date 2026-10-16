"""Tests for the Monte Carlo runner with parallelization."""

import time

import numpy as np

from coastmath.engine.monte_carlo import run_monte_carlo
from coastmath.engine.types import PlanData

# ---------------------------------------------------------------------------
# Basic functionality
# ---------------------------------------------------------------------------

class TestBasic:
    """run_monte_carlo returns a valid MonteCarloResult."""

    def test_100_trials_valid_result(self, standard_plan: PlanData) -> None:
        result = run_monte_carlo(
            standard_plan, n_trials=100, seed=42, max_workers=2,
        )
        assert result.n_trials == 100
        assert 0.0 <= result.success_rate <= 1.0
        assert len(result.percentile_curves.p50) > 0
        assert result.median_final_net_worth is not None

    def test_trial_count_matches(self, standard_plan: PlanData) -> None:
        result = run_monte_carlo(
            standard_plan, n_trials=20, seed=99, max_workers=2,
        )
        assert result.n_trials == 20

    def test_percentile_ordering(self, standard_plan: PlanData) -> None:
        """p10 <= p25 <= p50 <= p75 <= p90 at every year."""
        result = run_monte_carlo(
            standard_plan, n_trials=50, seed=42, max_workers=2,
        )
        curves = result.percentile_curves
        for i in range(len(curves.p50)):
            assert curves.p10[i] <= curves.p25[i] + 1e-6
            assert curves.p25[i] <= curves.p50[i] + 1e-6
            assert curves.p50[i] <= curves.p75[i] + 1e-6
            assert curves.p75[i] <= curves.p90[i] + 1e-6


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Same seed produces identical results."""

    def test_same_seed_same_result(self, standard_plan: PlanData) -> None:
        a = run_monte_carlo(
            standard_plan, n_trials=30, seed=12345, max_workers=2,
        )
        b = run_monte_carlo(
            standard_plan, n_trials=30, seed=12345, max_workers=2,
        )
        assert a.success_rate == b.success_rate
        assert a.median_final_net_worth == b.median_final_net_worth
        np.testing.assert_array_almost_equal(a.percentile_curves.p50, b.percentile_curves.p50)

    def test_different_seed_different_result(self, standard_plan: PlanData) -> None:
        a = run_monte_carlo(
            standard_plan, n_trials=30, seed=1, max_workers=2,
        )
        b = run_monte_carlo(
            standard_plan, n_trials=30, seed=2, max_workers=2,
        )
        # Results should differ (extremely unlikely to be identical)
        assert a.percentile_curves.p50 != b.percentile_curves.p50


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

class TestPerformance:
    """100 trials in under 5 seconds."""

    def test_100_trials_under_5s(self, standard_plan: PlanData) -> None:
        start = time.perf_counter()
        result = run_monte_carlo(
            standard_plan, n_trials=100, seed=42,
        )
        elapsed = time.perf_counter() - start

        assert result.n_trials == 100
        assert elapsed < 5.0, f"100 trials took {elapsed:.1f}s (target <5s)"

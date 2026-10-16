"""Monte Carlo integration tests: performance and correctness.

Tests cover:
- 100 trials under 5 seconds (acceptance criteria)
- Success rate stability across trial counts
- Block bootstrap autocorrelation preservation
- Seed divergence
- Guaranteed success / failure scenarios
"""

import copy
import time

import numpy as np
import pytest

from coastmath.engine.historical_data import load_historical_returns
from coastmath.engine.monte_carlo import build_block_bootstrap_sequence, run_monte_carlo
from coastmath.engine.types import PlanData

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def wealthy_plan(standard_plan: PlanData) -> PlanData:
    """Standard plan with $10M across accounts — guaranteed success."""
    plan = copy.deepcopy(standard_plan)
    for acct in plan.accounts.values():
        acct.balance = 2_500_000.0  # 4 accounts x $2.5M = $10M
    return plan


@pytest.fixture()
def broke_plan(standard_plan: PlanData) -> PlanData:
    """$0 balances, no income — guaranteed failure."""
    plan = copy.deepcopy(standard_plan)
    for acct in plan.accounts.values():
        acct.balance = 0.0
    plan.income_streams = []
    return plan


# ---------------------------------------------------------------------------
# 1. Performance: 100 trials under 5 seconds
# ---------------------------------------------------------------------------

class TestPerformance:
    """100 MC trials must complete within 5 seconds."""

    def test_100_trials_under_5s(self, standard_plan: PlanData) -> None:
        start = time.perf_counter()
        result = run_monte_carlo(standard_plan, n_trials=100, seed=42)
        elapsed = time.perf_counter() - start

        assert result.n_trials == 100
        assert elapsed < 5.0, f"100 trials took {elapsed:.1f}s (target <5s)"


# ---------------------------------------------------------------------------
# 2. Stability: more trials → stable success rate
# ---------------------------------------------------------------------------

class TestStability:
    """500 vs 1000 trials should produce success rates within 5%."""

    def test_success_rate_converges(self, standard_plan: PlanData) -> None:
        r500 = run_monte_carlo(
            standard_plan, n_trials=500, seed=42, max_workers=2,
        )
        r1000 = run_monte_carlo(
            standard_plan, n_trials=1000, seed=42, max_workers=2,
        )
        diff = abs(r500.success_rate - r1000.success_rate)
        assert diff <= 0.05, (
            f"Success rates diverged: 500-trial={r500.success_rate:.3f}, "
            f"1000-trial={r1000.success_rate:.3f}, diff={diff:.3f}"
        )


# ---------------------------------------------------------------------------
# 3. Block bootstrap preserves autocorrelation (contiguous subsequences)
# ---------------------------------------------------------------------------

class TestBlockBootstrapAutocorrelation:
    """Block bootstrap output consists of contiguous subsequences from source."""

    def test_blocks_are_contiguous_real_data(self) -> None:
        """Every row maps to historical data; consecutive rows within a
        block have consecutive (mod N) source indices."""
        hist = load_historical_returns()
        data = hist[["stock_return", "bond_return", "inflation", "dividend_yield"]].to_numpy()
        n = len(data)

        result = build_block_bootstrap_sequence(
            hist, plan_years=60, block_size_range=(3, 7),
            rng=np.random.default_rng(42),
        )

        def find_index(row: np.ndarray) -> int:
            matches = np.where(np.all(np.isclose(data, row), axis=1))[0]
            assert len(matches) > 0, "Row not found in source data"
            return int(matches[0])

        source_indices = [find_index(result[i]) for i in range(len(result))]

        # Count block boundaries (non-contiguous jumps)
        boundaries = 0
        for i in range(1, len(source_indices)):
            if source_indices[i] != (source_indices[i - 1] + 1) % n:
                boundaries += 1

        # With 60 years and block sizes 3-7 (avg 5), expect ~12 blocks
        n_blocks = boundaries + 1
        assert n_blocks >= 4, f"Too few blocks ({n_blocks})"
        assert n_blocks <= 30, f"Too many blocks ({n_blocks})"

    def test_block_lengths_within_range(self) -> None:
        """Each block length falls within the configured [3, 7] range."""
        hist = load_historical_returns()
        data = hist[["stock_return", "bond_return", "inflation", "dividend_yield"]].to_numpy()
        n = len(data)

        result = build_block_bootstrap_sequence(
            hist, plan_years=100, block_size_range=(3, 7),
            rng=np.random.default_rng(99),
        )

        def find_index(row: np.ndarray) -> int:
            matches = np.where(np.all(np.isclose(data, row), axis=1))[0]
            return int(matches[0])

        source_indices = [find_index(result[i]) for i in range(len(result))]

        # Extract block lengths
        block_lengths = []
        current_len = 1
        for i in range(1, len(source_indices)):
            if source_indices[i] == (source_indices[i - 1] + 1) % n:
                current_len += 1
            else:
                block_lengths.append(current_len)
                current_len = 1
        block_lengths.append(current_len)

        # All blocks except the last (may be truncated) should be in [3, 7]
        for length in block_lengths[:-1]:
            assert 3 <= length <= 7, f"Block length {length} outside [3, 7]"
        # Last block can be truncated to [1, 7]
        assert 1 <= block_lengths[-1] <= 7


# ---------------------------------------------------------------------------
# 4. Different seeds → different results
# ---------------------------------------------------------------------------

class TestSeedDivergence:
    """Different seeds must produce different simulation outcomes."""

    def test_different_seeds_different_curves(self, standard_plan: PlanData) -> None:
        a = run_monte_carlo(
            standard_plan, n_trials=100, seed=1, max_workers=2,
        )
        b = run_monte_carlo(
            standard_plan, n_trials=100, seed=9999, max_workers=2,
        )
        assert a.percentile_curves.p50 != b.percentile_curves.p50, (
            "Different seeds produced identical p50 curves"
        )


# ---------------------------------------------------------------------------
# 5. Guaranteed success (~100% with $10M savings)
# ---------------------------------------------------------------------------

class TestGuaranteedSuccess:
    """$10M starting balance should produce near-100% success rate."""

    def test_wealthy_plan_succeeds(self, wealthy_plan: PlanData) -> None:
        result = run_monte_carlo(
            wealthy_plan, n_trials=200, seed=42, max_workers=2,
        )
        assert result.success_rate >= 0.95, (
            f"Expected >=95% success with $10M, got {result.success_rate:.1%}"
        )


# ---------------------------------------------------------------------------
# 6. Guaranteed failure (~0% with $0 savings, no income)
# ---------------------------------------------------------------------------

class TestGuaranteedFailure:
    """$0 balances and no income should produce near-0% success rate."""

    def test_broke_plan_fails(self, broke_plan: PlanData) -> None:
        result = run_monte_carlo(
            broke_plan, n_trials=200, seed=42, max_workers=2,
        )
        assert result.success_rate <= 0.05, (
            f"Expected <=5% success with $0 and no income, got {result.success_rate:.1%}"
        )

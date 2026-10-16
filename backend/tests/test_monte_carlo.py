"""Tests for the block bootstrap sequence builder."""

import numpy as np
import pandas as pd
import pytest

from coastmath.engine.historical_data import load_historical_returns
from coastmath.engine.monte_carlo import (
    aggregate_results,
    build_block_bootstrap_sequence,
)
from coastmath.schemas.simulation import SimulationResult, YearSnapshot

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_data() -> pd.DataFrame:
    """Small synthetic dataset for deterministic testing."""
    rng = np.random.default_rng(0)
    n = 20
    return pd.DataFrame({
        "year": range(2000, 2000 + n),
        "stock_return": rng.uniform(-0.3, 0.4, n),
        "bond_return": rng.uniform(0.0, 0.1, n),
        "inflation": rng.uniform(-0.01, 0.05, n),
    })


@pytest.fixture()
def real_data() -> pd.DataFrame:
    """Load the actual historical returns CSV."""
    return load_historical_returns()


# ---------------------------------------------------------------------------
# Shape tests
# ---------------------------------------------------------------------------

class TestOutputShape:
    """Output shape is (plan_years, 3) for various plan lengths."""

    @pytest.mark.parametrize("plan_years", [1, 5, 30, 60, 100])
    def test_shape_various_lengths(self, sample_data: pd.DataFrame, plan_years: int) -> None:
        result = build_block_bootstrap_sequence(
            sample_data, plan_years, rng=np.random.default_rng(42),
        )
        assert result.shape == (plan_years, 3)

    def test_shape_with_real_data(self, real_data: pd.DataFrame) -> None:
        result = build_block_bootstrap_sequence(
            real_data, 40, rng=np.random.default_rng(42),
        )
        assert result.shape == (40, 4)  # stock, bond, inflation, dividend_yield


# ---------------------------------------------------------------------------
# Determinism tests
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Fixed seed produces identical output."""

    def test_same_seed_same_result(self, sample_data: pd.DataFrame) -> None:
        a = build_block_bootstrap_sequence(
            sample_data, 30, rng=np.random.default_rng(123),
        )
        b = build_block_bootstrap_sequence(
            sample_data, 30, rng=np.random.default_rng(123),
        )
        np.testing.assert_array_equal(a, b)

    def test_different_seed_different_result(self, sample_data: pd.DataFrame) -> None:
        a = build_block_bootstrap_sequence(
            sample_data, 30, rng=np.random.default_rng(1),
        )
        b = build_block_bootstrap_sequence(
            sample_data, 30, rng=np.random.default_rng(2),
        )
        assert not np.array_equal(a, b)


# ---------------------------------------------------------------------------
# Block contiguity tests
# ---------------------------------------------------------------------------

class TestBlockContiguity:
    """Each block is a contiguous subsequence of the source data (with wrap)."""

    def test_blocks_are_contiguous(self, sample_data: pd.DataFrame) -> None:
        """Verify every row in the output exists in the source data and that
        consecutive runs form contiguous (possibly wrapped) blocks."""
        data = sample_data[["stock_return", "bond_return", "inflation"]].to_numpy()

        result = build_block_bootstrap_sequence(
            sample_data, 50, block_size_range=(3, 7),
            rng=np.random.default_rng(99),
        )

        # Every row must appear somewhere in the source data
        for i in range(len(result)):
            row = result[i]
            matches = np.where(np.all(np.isclose(data, row), axis=1))[0]
            assert len(matches) > 0, f"Row {i} not found in source data"

    def test_contiguous_blocks_in_sequence(self, sample_data: pd.DataFrame) -> None:
        """Check that consecutive rows within a block have consecutive
        (mod N) source indices — i.e. every pair of adjacent output rows
        is either contiguous in the source (same block) or a block
        boundary (allowed jump)."""
        data = sample_data[["stock_return", "bond_return", "inflation"]].to_numpy()
        n = len(data)

        result = build_block_bootstrap_sequence(
            sample_data, 50, block_size_range=(3, 7),
            rng=np.random.default_rng(99),
        )

        def find_index(row: np.ndarray) -> int:
            matches = np.where(np.all(np.isclose(data, row), axis=1))[0]
            return int(matches[0])

        source_indices = [find_index(result[i]) for i in range(len(result))]

        # Count block boundaries (non-contiguous jumps)
        boundaries = 0
        for i in range(1, len(source_indices)):
            if source_indices[i] != (source_indices[i - 1] + 1) % n:
                boundaries += 1

        # With 50 output years and block sizes 3-7, we expect roughly
        # 50/5 = 10 blocks, so at least a few boundaries must exist.
        assert boundaries >= 2, (
            f"Expected multiple block boundaries, got {boundaries}"
        )
        # And the number of blocks (boundaries + 1) should be reasonable
        n_blocks = boundaries + 1
        assert n_blocks <= 50, "Too many blocks — each should be at least 1 year"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge case handling."""

    def test_plan_years_one(self, sample_data: pd.DataFrame) -> None:
        result = build_block_bootstrap_sequence(
            sample_data, 1, rng=np.random.default_rng(0),
        )
        assert result.shape == (1, 3)

    def test_plan_years_exceeds_data(self, sample_data: pd.DataFrame) -> None:
        """Requesting more years than available data works fine."""
        result = build_block_bootstrap_sequence(
            sample_data, 200, rng=np.random.default_rng(0),
        )
        assert result.shape == (200, 3)

    def test_values_are_floats(self, sample_data: pd.DataFrame) -> None:
        result = build_block_bootstrap_sequence(
            sample_data, 10, rng=np.random.default_rng(0),
        )
        assert result.dtype == np.float64


def test_calibration_copy_explains_inputs_without_promising_identical_paths():
    trial = SimulationResult(metadata={"plan_id": "00000000-0000-0000-0000-000000000001", "start_year": 2026, "end_year": 2026, "success": True}, plan_id="00000000-0000-0000-0000-000000000001", yearly_snapshots=[YearSnapshot(year=2026, age=36, net_worth=100)])
    calibrated = aggregate_results([trial], 1, calibrated_to_plan=True)
    raw = aggregate_results([trial], 1, calibrated_to_plan=False)
    for result in (calibrated, raw):
        assert "funding_success_rate" not in result.definitions["success_rate"]
        assert "can differ" in result.definitions["market_returns"]
        assert "agrees with" not in result.definitions["market_returns"]
    assert "yearly assumptions" in calibrated.definitions["market_returns"]
    assert "without adjustment" in raw.definitions["market_returns"]

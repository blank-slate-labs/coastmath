"""Seeded calibration must not depend on the host CPU's SIMD extensions.

NumPy routes float64 ``log1p``/``expm1`` arrays to SVML kernels on AVX-512
hosts and to the C library elsewhere, and its reductions sum in an order that
follows the vector width. Both disagree in the last bit across hosts, so a
seeded Monte Carlo run produced different trial values on different CI
machines. Calibration therefore evaluates both functions with the C library
one element at a time and takes historical means with ``math.fsum``.
"""

import math

import numpy as np
import pytest

from coastmath.engine import monte_carlo
from coastmath.engine.historical_data import load_historical_returns
from coastmath.engine.monte_carlo import calibrate_sequence, historical_log_means

_COLUMNS = ["stock_return", "bond_return", "inflation", "dividend_yield"]


def _history() -> np.ndarray:
    return load_historical_returns()[_COLUMNS].to_numpy(dtype=np.float64)


def _libm_log_means(values: np.ndarray) -> list[float]:
    columns = zip(*(row[:3] for row in values.tolist()), strict=True)
    return [math.fsum(math.log1p(max(x, -0.999)) for x in column) / len(values) for column in columns]


def _skewed(ufunc):
    """A stand-in for a vector kernel that rounds one ulp differently."""
    def run(values, *args, **kwargs):
        exact = ufunc(values, *args, **kwargs)
        return np.nextafter(exact, np.inf)
    return run


def test_log_means_equal_the_c_library_bit_for_bit() -> None:
    hist = _history()
    assert historical_log_means(hist).tolist() == _libm_log_means(hist)


def test_historical_means_do_not_depend_on_summation_order() -> None:
    hist = _history()
    shuffled = hist[np.random.default_rng(3).permutation(len(hist))]
    assert historical_log_means(shuffled).tolist() == historical_log_means(hist).tolist()
    assert (monte_carlo.historical_mean_dividend_yield(shuffled)
            == monte_carlo.historical_mean_dividend_yield(hist))


def test_calibrated_years_equal_the_c_library_bit_for_bit() -> None:
    hist = _history()
    means = historical_log_means(hist)
    targets = np.tile([0.07, 0.04, 0.03], (len(hist), 1))
    adjusted = calibrate_sequence(hist, targets, means)
    for row, target, out in zip(hist, targets, adjusted, strict=True):
        expected = [
            math.expm1(math.log1p(max(x, -0.999)) - m + math.log1p(t))
            for x, m, t in zip(row[:3], means, target, strict=True)
        ]
        assert out[:3].tolist() == expected
    # The dividend column is not calibrated here and passes through unchanged.
    np.testing.assert_array_equal(adjusted[:, 3], hist[:, 3])


def test_calibration_ignores_numpy_vector_kernels(monkeypatch: pytest.MonkeyPatch) -> None:
    hist = _history()
    targets = np.tile([0.05, 0.035, 0.025], (len(hist), 1))
    means = historical_log_means(hist)
    before = calibrate_sequence(hist, targets, means)

    monkeypatch.setattr(monte_carlo.np, "log1p", _skewed(np.log1p))
    monkeypatch.setattr(monte_carlo.np, "expm1", _skewed(np.expm1))

    np.testing.assert_array_equal(historical_log_means(hist), means)
    np.testing.assert_array_equal(calibrate_sequence(hist, targets, means), before)


def test_losses_beyond_the_floor_are_clamped_before_the_log() -> None:
    seq = np.array([[-1.0, -1.5, 0.02]])
    adjusted = calibrate_sequence(seq, np.array([[0.0, 0.0, 0.0]]), np.zeros(3))
    assert adjusted[0, :2].tolist() == [math.expm1(math.log1p(-0.999))] * 2
    assert adjusted[0, 2] == pytest.approx(0.02)

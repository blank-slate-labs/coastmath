"""Monte Carlo calibration: sampled history is shifted to the plan's
assumed compound returns so the median path tracks the deterministic
projection instead of the raw 1928-2024 averages."""

import uuid

import numpy as np
import pytest

from coastmath.engine.historical_data import load_historical_returns
from coastmath.engine.monte_carlo import (
    calibrate_sequence,
    historical_log_means,
    plan_return_targets,
    run_monte_carlo,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    DrawdownEntryData,
    PlanData,
)


def _plan(**overrides) -> PlanData:
    base = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1980,
        filing_status="single",
        life_expectancy=76,
        start_year=2026,
        assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.07),
        accounts={"b": AccountInfo(100_000, "taxable_brokerage")},
        drawdown_order=[DrawdownEntryData(1, "b")],
    )
    base.update(overrides)
    return PlanData(**base)


class TestCalibrateSequence:
    def test_geometric_mean_matches_target_and_dispersion_is_kept(self) -> None:
        hist = load_historical_returns()[["stock_return", "bond_return", "inflation"]].to_numpy()
        means = historical_log_means(hist)
        targets = np.tile([0.07, 0.04, 0.03], (len(hist), 1))
        adjusted = calibrate_sequence(hist, targets, means)
        geometric = np.expm1(np.log1p(adjusted).mean(axis=0))
        assert geometric == pytest.approx([0.07, 0.04, 0.03], abs=1e-9)
        for col in range(3):
            assert np.log1p(adjusted[:, col]).std() == pytest.approx(np.log1p(hist[:, col]).std())
        # Ordering of years is preserved, so sequence risk survives.
        assert np.all(np.argsort(adjusted[:, 0]) == np.argsort(hist[:, 0]))

    def test_extra_columns_such_as_dividend_yield_pass_through(self) -> None:
        seq = np.array([[0.10, 0.03, 0.02, 0.025], [-0.20, 0.05, 0.04, 0.03]])
        adjusted = calibrate_sequence(seq, np.tile([0.07, 0.04, 0.03], (2, 1)), np.zeros(3))
        assert adjusted[:, 3].tolist() == [0.025, 0.03]
        assert adjusted.shape == seq.shape


class TestPlanReturnTargets:
    def test_stock_target_is_price_growth_plus_dividend_yield(self) -> None:
        plan = _plan(assumptions=AssumptionData(
            inflation_rate=0.025, stock_growth_rate=0.05, bond_return_rate=0.04, stock_dividend_yield=0.02,
        ))
        targets = plan_return_targets(plan, 3, 2026)
        assert targets.shape == (3, 3)
        assert targets[0].tolist() == pytest.approx([0.07, 0.04, 0.025])

    def test_assumption_curves_are_evaluated_per_year(self) -> None:
        plan = _plan(assumption_curves=[AssumptionCurveData(
            curve_type="market_return", mode="curve",
            control_points=[{"x": 46, "y": 0.08}, {"x": 47, "y": 0.06}],
        )])
        targets = plan_return_targets(plan, 2, 2026)
        assert targets[0, 0] == pytest.approx(0.08)
        assert targets[1, 0] == pytest.approx(0.06)


class TestRunnerCalibration:
    def test_calibrated_median_tracks_deterministic_projection(self) -> None:
        plan = _plan()
        deterministic = run_simulation(plan).yearly_snapshots[-1].net_worth
        calibrated = run_monte_carlo(plan, n_trials=150, seed=7, max_workers=2)
        raw = run_monte_carlo(plan, n_trials=150, seed=7, max_workers=2, calibrate_to_plan=False)
        assert 0.6 * deterministic < calibrated.median_final_net_worth < 1.6 * deterministic
        # Raw 1928-2024 history compounds far faster than the plan's 7%.
        assert raw.median_final_net_worth > 1.8 * deterministic
        assert "yearly assumptions" in calibrated.definitions["market_returns"]
        assert "without adjustment" in raw.definitions["market_returns"]

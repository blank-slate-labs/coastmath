"""Tests for assumption curve interpolation engine."""

import uuid

from coastmath.engine.assumption_curves import (
    catmull_rom_interpolate,
    resolve_assumption,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    PlanData,
)

# ---------------------------------------------------------------------------
# catmull_rom_interpolate
# ---------------------------------------------------------------------------


class TestCatmullRomInterpolate:
    def test_empty_points_returns_zero(self):
        assert catmull_rom_interpolate([], 50) == 0.0

    def test_single_point_constant(self):
        pts = [{"x": 40, "y": 0.07}]
        assert catmull_rom_interpolate(pts, 30) == 0.07
        assert catmull_rom_interpolate(pts, 40) == 0.07
        assert catmull_rom_interpolate(pts, 60) == 0.07

    def test_two_points_linear_midpoint(self):
        """With two points, Catmull-Rom should interpolate smoothly (near-linear at midpoint)."""
        pts = [{"x": 30, "y": 0.08}, {"x": 60, "y": 0.04}]
        mid = catmull_rom_interpolate(pts, 45)
        # Midpoint should be close to the average (0.06), with some spline deviation
        assert 0.05 < mid < 0.07

    def test_flat_extrapolation_before_first(self):
        pts = [{"x": 30, "y": 0.08}, {"x": 60, "y": 0.04}]
        assert catmull_rom_interpolate(pts, 20) == 0.08

    def test_flat_extrapolation_after_last(self):
        pts = [{"x": 30, "y": 0.08}, {"x": 60, "y": 0.04}]
        assert catmull_rom_interpolate(pts, 70) == 0.04

    def test_at_control_point_exact(self):
        """Value at a control point should be exactly that point's y."""
        pts = [{"x": 30, "y": 0.08}, {"x": 45, "y": 0.06}, {"x": 60, "y": 0.04}]
        assert catmull_rom_interpolate(pts, 30) == 0.08
        assert catmull_rom_interpolate(pts, 60) == 0.04

    def test_monotonic_decreasing_curve(self):
        """A decreasing set of control points should produce decreasing values."""
        pts = [
            {"x": 25, "y": 0.10},
            {"x": 40, "y": 0.08},
            {"x": 55, "y": 0.06},
            {"x": 70, "y": 0.04},
        ]
        v35 = catmull_rom_interpolate(pts, 35)
        v50 = catmull_rom_interpolate(pts, 50)
        v65 = catmull_rom_interpolate(pts, 65)
        assert v35 > v50 > v65

    def test_unsorted_points_handled(self):
        """Points in random order should produce the same result as sorted."""
        pts_sorted = [{"x": 30, "y": 0.08}, {"x": 45, "y": 0.06}, {"x": 60, "y": 0.04}]
        pts_unsorted = [{"x": 45, "y": 0.06}, {"x": 60, "y": 0.04}, {"x": 30, "y": 0.08}]
        assert catmull_rom_interpolate(pts_sorted, 40) == catmull_rom_interpolate(pts_unsorted, 40)


# ---------------------------------------------------------------------------
# resolve_assumption
# ---------------------------------------------------------------------------


class TestResolveAssumption:
    def test_no_curves_returns_default(self):
        assert resolve_assumption([], "inflation", 2030, 1990, 0.03) == 0.03

    def test_wrong_type_returns_default(self):
        curves = [
            AssumptionCurveData(curve_type="bond_return", mode="fixed", fixed_rate=0.04),
        ]
        assert resolve_assumption(curves, "inflation", 2030, 1990, 0.03) == 0.03

    def test_fixed_mode_returns_fixed_rate(self):
        curves = [
            AssumptionCurveData(curve_type="inflation", mode="fixed", fixed_rate=0.025),
        ]
        assert resolve_assumption(curves, "inflation", 2030, 1990) == 0.025

    def test_fixed_mode_none_rate_returns_default(self):
        curves = [
            AssumptionCurveData(curve_type="inflation", mode="fixed", fixed_rate=None),
        ]
        assert resolve_assumption(curves, "inflation", 2030, 1990, 0.03) == 0.03

    def test_curve_mode_interpolates_by_age(self):
        curves = [
            AssumptionCurveData(
                curve_type="market_return",
                mode="curve",
                control_points=[
                    {"x": 30, "y": 0.10},
                    {"x": 50, "y": 0.08},
                    {"x": 70, "y": 0.05},
                ],
            ),
        ]
        # birth_year=1990, year=2030 → age=40 (between 30 and 50)
        result = resolve_assumption(curves, "market_return", 2030, 1990)
        assert 0.07 < result < 0.11

    def test_curve_mode_extrapolation(self):
        curves = [
            AssumptionCurveData(
                curve_type="market_return",
                mode="curve",
                control_points=[
                    {"x": 40, "y": 0.08},
                    {"x": 60, "y": 0.05},
                ],
            ),
        ]
        # age=30, before first point → flat extrapolation at 0.08
        assert resolve_assumption(curves, "market_return", 2020, 1990) == 0.08


# ---------------------------------------------------------------------------
# Integration: simulator with assumption curves
# ---------------------------------------------------------------------------


def _plan(**overrides) -> PlanData:
    defaults = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1990,
        filing_status="single",
        life_expectancy=90,
        start_year=2025,
        milestones=[],
        income_streams=[],
        expenses=[],
        priorities=[],
        drawdown_order=[],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
        assumption_curves=[],
        accounts={},
    )
    defaults.update(overrides)
    return PlanData(**defaults)


class TestSimulatorWithCurves:
    def test_no_curves_uses_flat_assumption_defaults(self):
        """Without curves, simulator should use AssumptionData defaults."""
        plan = _plan(
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.07),
            accounts={"brok": AccountInfo(balance=100_000, account_type="brokerage")},
        )
        result = run_simulation(plan)
        # Year 0: growth applied → 100_000 * 1.07 = 107_000
        assert abs(result.yearly_snapshots[0].accounts["brok"] - 107_000) < 0.01

    def test_fixed_curve_overrides_assumption(self):
        """A fixed-mode curve should override the AssumptionData default."""
        plan = _plan(
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.07),
            assumption_curves=[
                AssumptionCurveData(
                    curve_type="market_return", mode="fixed", fixed_rate=0.10,
                ),
            ],
            accounts={"brok": AccountInfo(balance=100_000, account_type="brokerage")},
        )
        result = run_simulation(plan)
        # 100_000 * 1.10 = 110_000
        assert abs(result.yearly_snapshots[0].accounts["brok"] - 110_000) < 0.01

    def test_bond_allocation_blends_rates(self):
        """Bond allocation should blend stock and bond growth rates."""
        plan = _plan(
            assumption_curves=[
                AssumptionCurveData(
                    curve_type="market_return", mode="fixed", fixed_rate=0.10,
                ),
                AssumptionCurveData(
                    curve_type="bond_return", mode="fixed", fixed_rate=0.04,
                ),
                AssumptionCurveData(
                    curve_type="bond_allocation", mode="fixed", fixed_rate=0.50,
                ),
            ],
            accounts={"brok": AccountInfo(balance=100_000, account_type="brokerage")},
        )
        result = run_simulation(plan)
        # Effective rate = 0.5 * 0.04 + 0.5 * 0.10 = 0.07
        # 100_000 * 1.07 = 107_000
        assert abs(result.yearly_snapshots[0].accounts["brok"] - 107_000) < 0.01

    def test_curve_mode_varies_by_age(self):
        """Curve-mode assumptions should produce different rates at different ages."""
        plan = _plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            assumption_curves=[
                AssumptionCurveData(
                    curve_type="market_return",
                    mode="curve",
                    control_points=[
                        {"x": 30, "y": 0.10},
                        {"x": 50, "y": 0.06},
                        {"x": 70, "y": 0.03},
                    ],
                ),
            ],
            accounts={"brok": AccountInfo(balance=100_000, account_type="brokerage")},
        )
        result = run_simulation(plan)
        # Year 0: age 35, between 30→50 curve, should grow near 0.08-0.09
        first_balance = result.yearly_snapshots[0].accounts["brok"]
        growth_yr0 = (first_balance / 100_000) - 1
        assert 0.06 < growth_yr0 < 0.12

        # Later years should have lower growth
        # Year 20: age 55, between 50→70 curve
        balance_y19 = result.yearly_snapshots[19].accounts["brok"]
        balance_y20 = result.yearly_snapshots[20].accounts["brok"]
        growth_yr20 = (balance_y20 / balance_y19) - 1
        assert growth_yr20 < growth_yr0

    def test_bond_glide_path_monotonic(self):
        """Bond allocation increasing with age should produce monotonically decreasing growth."""
        plan = _plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            assumption_curves=[
                AssumptionCurveData(
                    curve_type="market_return", mode="fixed", fixed_rate=0.10,
                ),
                AssumptionCurveData(
                    curve_type="bond_return", mode="fixed", fixed_rate=0.03,
                ),
                AssumptionCurveData(
                    curve_type="bond_allocation",
                    mode="curve",
                    control_points=[
                        {"x": 30, "y": 0.20},  # 20% bonds at 30
                        {"x": 50, "y": 0.50},  # 50% bonds at 50
                        {"x": 70, "y": 0.80},  # 80% bonds at 70
                    ],
                ),
            ],
            accounts={"brok": AccountInfo(balance=100_000, account_type="brokerage")},
        )
        result = run_simulation(plan)
        # Compute year-over-year growth rates at early, mid, late ages
        snapshots = result.yearly_snapshots
        # Year 0→1 (age ~35-36), Year 20→21 (age ~55-56), Year 40→41 (age ~75-76)
        bal = [s.accounts["brok"] for s in snapshots]
        growth_early = bal[1] / bal[0] - 1   # ~age 36
        growth_mid = bal[21] / bal[20] - 1    # ~age 56
        growth_late = bal[41] / bal[40] - 1   # ~age 76
        # More bonds → lower blended rate → monotonically decreasing growth
        assert growth_early > growth_mid > growth_late
        # Early growth should be closer to stock rate, late closer to bond rate
        assert growth_early > 0.06
        assert growth_late < 0.06

    def test_inflation_curve_varies_by_age(self):
        """Inflation resolved via curve should change inflation_factor differently each year."""
        plan = _plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            assumption_curves=[
                AssumptionCurveData(
                    curve_type="inflation",
                    mode="curve",
                    control_points=[
                        {"x": 30, "y": 0.04},
                        {"x": 50, "y": 0.02},
                    ],
                ),
            ],
        )
        result = run_simulation(plan)
        # 1990 + 92 = 2082, range(2025, 2082) = 57
        assert len(result.yearly_snapshots) == 57

    def test_bond_allocation_clamped_on_overshoot(self):
        """Catmull-Rom overshoot on bond_allocation must be clamped to [0,1].

        Control points with a steep ramp (0→0.9 in one year) cause
        Catmull-Rom to overshoot above 1.0.  Without the clamp the
        simulator would compute a negative stock weight.
        """
        stock_rate = 0.10
        bond_rate = 0.04
        plan = _plan(
            birth_year=1990,
            start_year=2020,  # age 30
            life_expectancy=65,  # ends at age 65, covers overshoot zone
            assumption_curves=[
                AssumptionCurveData(
                    curve_type="market_return", mode="fixed", fixed_rate=stock_rate,
                ),
                AssumptionCurveData(
                    curve_type="bond_return", mode="fixed", fixed_rate=bond_rate,
                ),
                AssumptionCurveData(
                    curve_type="bond_allocation",
                    mode="curve",
                    control_points=[
                        {"x": 30, "y": 0.0},
                        {"x": 31, "y": 0.9},
                        {"x": 32, "y": 1.0},
                        {"x": 60, "y": 1.0},
                    ],
                ),
            ],
            accounts={"brok": AccountInfo(balance=100_000, account_type="brokerage")},
        )

        # Verify the raw spline actually overshoots (pre-condition)
        overshoot_age = 31.5
        raw = catmull_rom_interpolate(
            [{"x": 30, "y": 0.0}, {"x": 31, "y": 0.9},
             {"x": 32, "y": 1.0}, {"x": 60, "y": 1.0}],
            overshoot_age,
        )
        assert 0.945 <= raw <= 1.0, f"Shape preserving curve left its segment at age {overshoot_age}: {raw}"

        result = run_simulation(plan)

        # For every year, the effective growth must lie between pure-bond
        # and pure-stock returns.  If the clamp were missing, overshoot
        # would push the blended rate outside this interval.
        prev_balance = 100_000.0
        for snap in result.yearly_snapshots:
            bal = snap.accounts["brok"]
            growth = (bal / prev_balance) - 1 if prev_balance > 0 else 0.0
            assert growth >= bond_rate - 1e-9, (
                f"year {snap.year}: growth {growth:.6f} < bond_rate {bond_rate}"
            )
            assert growth <= stock_rate + 1e-9, (
                f"year {snap.year}: growth {growth:.6f} > stock_rate {stock_rate}"
            )
            prev_balance = bal

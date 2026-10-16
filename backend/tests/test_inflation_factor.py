"""Per-year inflation_factor on simulation snapshots.

The factor is the cumulative plan inflation applied to that year's amounts,
anchored at the start year: the first snapshot is 1.0 and year n is the product
of (1 + rate) over the n prior years (the web deflators' convention).
"""

import math
import uuid
from itertools import pairwise

from coastmath.engine.assumption_curves import resolve_assumption
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    PlanData,
)


def _plan(**overrides) -> PlanData:
    defaults = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1990,
        filing_status="single",
        life_expectancy=70,
        start_year=2026,
        milestones=[],
        income_streams=[],
        expenses=[],
        priorities=[],
        drawdown_order=[],
        assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.05),
        assumption_curves=[],
        accounts={"brok": AccountInfo(balance=100_000, account_type="brokerage")},
    )
    defaults.update(overrides)
    return PlanData(**defaults)


def test_fixed_rate_compounds_from_start_year():
    snaps = run_simulation(_plan()).yearly_snapshots
    assert len(snaps) > 10
    for n, snap in enumerate(snaps):
        assert math.isclose(snap.inflation_factor, 1.03 ** n, rel_tol=1e-12), (snap.year, snap.inflation_factor)
    assert snaps[0].model_dump()["inflation_factor"] == 1.0


def test_fixed_inflation_curve_overrides_assumption():
    plan = _plan(assumption_curves=[AssumptionCurveData(curve_type="inflation", mode="fixed", fixed_rate=0.025)])
    snaps = run_simulation(plan).yearly_snapshots
    for n, snap in enumerate(snaps):
        assert math.isclose(snap.inflation_factor, 1.025 ** n, rel_tol=1e-12)


def test_curve_mode_follows_the_curve():
    curves = [AssumptionCurveData(curve_type="inflation", mode="curve",
                                  control_points=[{"x": 36, "y": 0.05}, {"x": 60, "y": 0.01}])]
    plan = _plan(assumption_curves=curves)
    snaps = run_simulation(plan).yearly_snapshots
    expected = 1.0
    for snap in snaps:
        assert math.isclose(snap.inflation_factor, expected, rel_tol=1e-12), (snap.year, snap.inflation_factor, expected)
        expected *= 1.0 + resolve_assumption(curves, "inflation", snap.year, plan.birth_year, 0.03)
    ratios = [b.inflation_factor / a.inflation_factor for a, b in pairwise(snaps)]
    assert ratios[0] > 1.045 and ratios[-1] < 1.015

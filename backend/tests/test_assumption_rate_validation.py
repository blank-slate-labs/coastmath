"""Assumption rates and curve points are validated on every input path.

Rates are fractions above -1 (-100%), curve control points are finite numbers,
and the stateless mode is "fixed" or "curve", for saved curves, curve updates
and stateless requests alike.
"""

import pytest
from pydantic import ValidationError

from app.schemas.assumption_curve import AssumptionCurveCreate, AssumptionCurveUpdate
from coastmath.schemas.plan_data_request import (
    AssumptionCurveRequest,
    AssumptionRequest,
)

# ---------------------------------------------------------------------------
# Assumption rates are fractions above -1 (-100%); points
# must be finite numbers, and the stateless mode must be "fixed" or "curve".
# ---------------------------------------------------------------------------


class TestAssumptionDomain:
    @pytest.mark.parametrize("rate", [-1.0, -1.5, float("nan"), float("inf")])
    def test_fixed_rate_rejected(self, rate):
        for model in (AssumptionCurveCreate, AssumptionCurveRequest):
            with pytest.raises(ValidationError):
                model(curve_type="market_return", mode="fixed", fixed_rate=rate)
        with pytest.raises(ValidationError):
            AssumptionCurveUpdate(fixed_rate=rate)
        with pytest.raises(ValidationError):
            AssumptionRequest(stock_growth_rate=rate)

    @pytest.mark.parametrize("point", [{"x": 40, "y": -3}, {"x": 40, "y": "0.05"},
                                       {"x": 40, "y": True}, {"x": float("nan"), "y": 0.05}])
    def test_control_point_rejected(self, point):
        for model in (AssumptionCurveCreate, AssumptionCurveRequest):
            with pytest.raises(ValidationError):
                model(curve_type="market_return", mode="curve", control_points=[point])

    def test_unknown_stateless_mode_rejected(self):
        with pytest.raises(ValidationError):
            AssumptionCurveRequest(curve_type="inflation", mode="Fixed", fixed_rate=0.03)

    def test_valid_values_accepted(self):
        AssumptionCurveCreate(curve_type="market_return", mode="fixed", fixed_rate=-0.5)
        AssumptionCurveRequest(curve_type="market_return", mode="curve",
                               control_points=[{"x": 40, "y": -0.2}, {"x": 90, "y": 0}])
        AssumptionRequest(inflation_rate=-0.02)

import math
from typing import Any, Literal

CurveType = Literal[
    "inflation",
    "market_return",
    "bond_return",
    "bond_allocation",
    "dividend_yield",
    "wage_growth",
    "social_security_cola",
    "cash_yield",
]


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def validate_rate(value: Any, name: str = "fixed_rate") -> float:
    """An assumption rate as a fraction. A rate of -100% or lower would turn
    balances negative or flip their sign, so it is rejected."""
    rate = _finite_number(value, name)
    if rate <= -1:
        raise ValueError(f"{name} must be greater than -1 (-100%)")
    return rate


def validate_control_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for i, point in enumerate(points):
        if "x" not in point or "y" not in point:
            msg = f"control_points[{i}] must have 'x' and 'y' keys"
            raise ValueError(msg)
        _finite_number(point["x"], f"control_points[{i}].x")
        validate_rate(point["y"], f"control_points[{i}].y")
    return points

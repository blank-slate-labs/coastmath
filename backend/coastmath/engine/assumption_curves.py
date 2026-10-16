"""Assumption curve interpolation engine.

Provides shape-preserving cubic interpolation for age-varying assumption rates
(inflation, market return, bond return, bond allocation, etc.).
"""

from __future__ import annotations

from coastmath.engine.types import AssumptionCurveData, AssumptionData

DEFAULT_BOND_ALLOCATION = 0.0


def default_assumption_rates() -> dict[str, float]:
    """Expose the engine's default decimal rates for client presentation."""
    defaults = AssumptionData()
    return {
        "inflation": defaults.inflation_rate,
        "market_return": defaults.stock_growth_rate,
        "dividend_yield": defaults.stock_dividend_yield,
        "bond_return": defaults.bond_return_rate,
        "bond_allocation": DEFAULT_BOND_ALLOCATION,
        "cash_yield": defaults.cash_yield_rate,
    }


def catmull_rom_interpolate(
    control_points: list[dict[str, float]], target_age: float,
) -> float:
    """Shape-preserving PCHIP with flat extrapolation (legacy function name).

    Weighted harmonic derivatives respect nonuniform age spacing and preserve
    plateaus. Reference: scipy.interpolate.PchipInterpolator algorithm notes.
    Duplicate ages use the last supplied value, identically in the web client.
    """
    values = {p["x"]: p["y"] for p in control_points}
    x = sorted(values)
    y = [values[age] for age in x]
    n = len(x)
    if not n:
        return 0.0
    if target_age <= x[0]:
        return y[0]
    if target_age >= x[-1]:
        return y[-1]
    h = [x[i + 1] - x[i] for i in range(n - 1)]
    d = [(y[i + 1] - y[i]) / h[i] for i in range(n - 1)]
    m = [d[0]] * n
    if n > 2:
        def endpoint(h0, h1, d0, d1):
            slope = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
            if slope * d0 <= 0:
                return 0.0
            if d0 * d1 <= 0 and abs(slope) > abs(3 * d0):
                return 3 * d0
            return slope
        m[0] = endpoint(h[0], h[1], d[0], d[1])
        m[-1] = endpoint(h[-1], h[-2], d[-1], d[-2])
        for i in range(1, n - 1):
            if d[i - 1] * d[i] <= 0:
                m[i] = 0.0
            else:
                w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
                m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    i = next(i for i in range(n - 1) if target_age <= x[i + 1])
    t = (target_age - x[i]) / h[i]
    result = ((2*t**3 - 3*t**2 + 1) * y[i] + (t**3 - 2*t**2 + t) * h[i] * m[i]
              + (-2*t**3 + 3*t**2) * y[i + 1] + (t**3 - t**2) * h[i] * m[i + 1])
    return min(max(y[i], y[i + 1]), max(min(y[i], y[i + 1]), result))


def resolve_assumption(
    curves: list[AssumptionCurveData],
    curve_type: str,
    year: int,
    birth_year: int,
    default: float = 0.0,
) -> float:
    """Resolve an assumption rate for a given year.

    Searches *curves* for one matching *curve_type*.

    - mode='fixed' → returns fixed_rate
    - mode='curve' → shape-preserving cubic interpolation at person's age
    - no match     → returns *default*
    """
    for curve in curves:
        if curve.curve_type == curve_type:
            if curve.mode == "fixed":
                return curve.fixed_rate if curve.fixed_rate is not None else default
            # mode == "curve"
            age = float(year - birth_year)
            return catmull_rom_interpolate(curve.control_points, age)
    return default

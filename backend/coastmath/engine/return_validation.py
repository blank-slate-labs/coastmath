"""Domain checks for market-return override inputs."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real


def validate_return_components(
    stock_return: object,
    bond_return: object,
    inflation: object,
    dividend_yield: object | None = None,
) -> None:
    """Validate one return row before applying it to account balances."""
    if any(
        not isinstance(value, Real) or isinstance(value, bool)
        for value in (stock_return, bond_return, inflation)
    ):
        raise ValueError("return override values must be numeric")
    try:
        stock = float(stock_return)
        bond = float(bond_return)
        cpi = float(inflation)
    except (TypeError, ValueError) as exc:
        raise ValueError("return override values must be numeric") from exc
    if not all(math.isfinite(value) for value in (stock, bond, cpi)):
        raise ValueError("return override values must be finite")
    if stock < -1.0:
        raise ValueError("stock return cannot be below -100%")
    if bond < -1.0:
        raise ValueError("bond return cannot be below -100%")
    if cpi <= -1.0:
        raise ValueError("inflation must be above -100%")
    if dividend_yield is None:
        return
    if not isinstance(dividend_yield, Real) or isinstance(dividend_yield, bool):
        raise ValueError("dividend_yield must be numeric when supplied")
    try:
        dividend = float(dividend_yield)
    except (TypeError, ValueError) as exc:
        raise ValueError("dividend_yield must be numeric when supplied") from exc
    if not math.isfinite(dividend) or dividend < 0.0:
        raise ValueError("dividend_yield must be finite and nonnegative when supplied")
    if stock - dividend < -1.0:
        raise ValueError("derived stock price return cannot be below -100%")


def validate_override_returns(override_returns: Mapping[object, Sequence[object]]) -> None:
    """Validate simulator return overrides without importing pandas.

    Rows are ``(stock, bond, inflation[, dividend_yield[, crypto_return]])``;
    a missing or None dividend yield uses the plan's yield, and a crypto
    return (Monte Carlo only) is a total return no lower than -100%.
    """
    if not isinstance(override_returns, Mapping):
        raise ValueError("return overrides must be a mapping")
    for year, row in override_returns.items():
        try:
            size = len(row)
        except TypeError as exc:
            raise ValueError(f"return override for {year!r} must be a 3- to 5-item sequence") from exc
        if size not in (3, 4, 5):
            raise ValueError(f"return override for {year!r} must contain 3 to 5 values")
        try:
            stock_return, bond_return, inflation = row[0], row[1], row[2]
            dividend = row[3] if size >= 4 else None
            crypto = row[4] if size == 5 else None
        except (IndexError, KeyError, TypeError) as exc:
            raise ValueError(
                f"return override for {year!r} must be a 3- to 5-item sequence"
            ) from exc
        validate_return_components(stock_return, bond_return, inflation, dividend)
        if crypto is not None:
            if not isinstance(crypto, Real) or isinstance(crypto, bool):
                raise ValueError("crypto return must be numeric when supplied")
            if not math.isfinite(float(crypto)) or float(crypto) < -1.0:
                raise ValueError("crypto return must be finite and not below -100%")

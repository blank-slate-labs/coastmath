"""State income tax law already enacted for years after the 2026 tables.

``data/state_tax_enacted_changes.json`` lists, per state, dated and
unconditional changes (rate phase-downs, new brackets and deductions,
sunsets); its sources are the ``_sources`` of ``state_tax_enacted_changes.json``.
Changes that depend on a future revenue determination are not data here.

For tax year Y, every change of the state with ``year <= Y`` applies to the
2026 state entry in ascending year order. A change replaces only the fields it
sets: nested objects merge key by key, lists and numbers are replaced.

The engine grows built-in dollar amounts with the calendar inflation factor
(1.0 in 2026). A change's bracket bounds, standard deductions and capital-gain
bands are in ``dollar_year`` dollars, so they are divided here by the factor
of that year; the engine's multiplication then leaves them at their statutory
amount in that year and grows them with inflation afterwards. Amounts already
in 2026 dollars (``dollar_year`` 2026) are not rescaled.

Years with no applicable change return the 2026 entry itself, so plans in
unaffected years and states see exactly the previous data.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from functools import lru_cache
from pathlib import Path

_DATA = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "state_tax_enacted_changes.json").read_text()
)
BASE_TAX_YEAR = int(_DATA["base_tax_year"])

# Keys whose numbers are dollar amounts the state layer multiplies by the
# inflation factor. Rates, ages and flags are never rescaled.
_DOLLAR_KEYS = frozenset({"min", "max", "standard_deduction", "band"})
# The open top bracket's sentinel upper bound stays as written.
_OPEN_BOUND = 999_999_999


def changes_for(state_code: str | None) -> list[dict]:
    """The state's enacted changes in ascending year order (empty if none)."""
    entry = _DATA["states"].get(state_code or "")
    return sorted(entry["changes"], key=lambda change: int(change["year"])) if entry else []


def applicable_changes(state_code: str | None, tax_year: int) -> list[dict]:
    """The changes in effect for ``tax_year``, oldest first."""
    return [change for change in changes_for(state_code) if int(change["year"]) <= tax_year]


def _scaled(value, factor: float, dollar: bool = False):
    """A copy of ``value`` with dollar amounts divided by ``factor``."""
    if isinstance(value, dict):
        return {key: _scaled(item, factor, dollar or key in _DOLLAR_KEYS) for key, item in value.items()}
    if isinstance(value, list):
        return [_scaled(item, factor, dollar) for item in value]
    if dollar and isinstance(value, (int, float)) and not isinstance(value, bool) and value < _OPEN_BOUND:
        return value / factor
    return value


def _merge(base: dict, patch: Mapping) -> dict:
    """``base`` with ``patch`` applied: dicts merge recursively, anything else is replaced."""
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=4096)
def _resolved(state_code: str, tax_year: int, anchor_factors: tuple[float, ...]) -> dict:
    from coastmath.engine.tax_engine import (  # noqa: PLC0415 - tax_engine imports this module
        _TAX_DATA,
    )

    data = _TAX_DATA["state"][state_code]
    for change, factor in zip(applicable_changes(state_code, tax_year), anchor_factors, strict=True):
        patch = change["set"] if factor == 1.0 else _scaled(change["set"], factor)
        data = _merge(data, patch)
    return data


def calendar_factor_for(
    inflation_factor: float,
    tax_year: int,
    calendar_inflation: Mapping[int, float] | None = None,
) -> Callable[[int], float]:
    """The calendar inflation factor of an earlier year (1.0 for 2026 and before).

    Uses the simulation's calendar factors when given. Otherwise it assumes
    constant inflation between 2026 and ``tax_year``, which reproduces
    ``inflation_factor`` in ``tax_year`` exactly.
    """
    def factor(year: int) -> float:
        if year <= BASE_TAX_YEAR:
            return 1.0
        if calendar_inflation is not None and year in calendar_inflation:
            return float(calendar_inflation[year])
        if tax_year <= BASE_TAX_YEAR or inflation_factor <= 0:
            return 1.0
        return inflation_factor ** ((min(year, tax_year) - BASE_TAX_YEAR) / (tax_year - BASE_TAX_YEAR))
    return factor


def state_data_for_year(
    base: Mapping | None,
    state_code: str | None,
    tax_year: int,
    calendar_factor: Callable[[int], float],
) -> Mapping | None:
    """The state's table entry in force for ``tax_year``.

    ``base`` is the 2026 entry (None for an unknown state). Without an
    applicable change it is returned unchanged.
    """
    if base is None or not state_code:
        return base
    changes = applicable_changes(state_code, tax_year)
    if not changes:
        return base
    anchors = tuple(
        1.0 if int(change.get("dollar_year", change["year"])) <= BASE_TAX_YEAR
        else float(calendar_factor(int(change.get("dollar_year", change["year"]))))
        for change in changes)
    return _resolved(state_code, tax_year, anchors)

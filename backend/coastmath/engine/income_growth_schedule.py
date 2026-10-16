"""Per-income growth schedules: ordered calendar-year segments.

An income stream's amount normally steps each January by its ``growth_rate``
or, when that is blank, along the plan's wage-growth curve (earned income).
A schedule replaces that step in the years its segments cover:

- ``percent``: the amount changes by ``value`` percent that year;
- ``inflation_offset``: by the prior year's realized inflation plus ``value``
  percentage points, the same inflation that advances every other
  inflation-linked figure (a Monte Carlo trial's sampled path included);
- ``dollar_change``: by ``value`` dollars, nominal or in plan-start dollars
  inflated to that year;
- ``set_amount``: the amount is ``value`` (nominal, or plan-start dollars
  inflated to that year).

Years no segment covers keep the default step. A segment covering the plan's
first year changes it only when it sets the amount; growth steps begin the
following January, like the default. Amounts never fall below zero. The
stream's growth cap still applies to the scheduled amount.
"""

from __future__ import annotations

from coastmath.engine.types import IncomeData


def segment_for(schedule: list[dict] | None, year: int) -> dict | None:
    """The segment covering ``year``, or None."""
    for segment in schedule or []:
        end = segment.get("end_year")
        if segment["start_year"] <= year and (end is None or year <= end):
            return segment
    return None


def _dollars(segment: dict, inflation_factor: float) -> float:
    value = float(segment["value"])
    return value * inflation_factor if segment.get("dollars") == "today" else value


def opening_amount(income: IncomeData, start_year: int) -> float:
    """The first year's amount: a set-amount segment covering it wins."""
    segment = segment_for(income.growth_schedule, start_year)
    if segment is not None and segment["kind"] == "set_amount":
        return max(0.0, _dollars(segment, 1.0))
    return income.annual_amount


def next_amount(
    income: IncomeData,
    amount: float,
    next_year: int,
    default_rate: float,
    inflation_rate: float,
    next_inflation_factor: float,
) -> float:
    """Step ``amount`` into ``next_year``.

    ``default_rate`` is the step the stream would take without a schedule;
    ``inflation_rate`` is the year's realized inflation and
    ``next_inflation_factor`` the plan-start-to-``next_year`` price factor.
    """
    segment = segment_for(income.growth_schedule, next_year)
    if segment is None:
        stepped = amount * (1.0 + default_rate)
    elif segment["kind"] == "percent":
        stepped = amount * (1.0 + float(segment["value"]) / 100.0)
    elif segment["kind"] == "inflation_offset":
        stepped = amount * (1.0 + inflation_rate + float(segment["value"]) / 100.0)
    elif segment["kind"] == "dollar_change":
        stepped = amount + _dollars(segment, next_inflation_factor)
    elif segment["kind"] == "set_amount":
        stepped = _dollars(segment, next_inflation_factor)
    else:
        raise ValueError(f"{income.name}: unknown growth segment kind {segment['kind']!r}")
    return max(0.0, stepped)

"""Effective tax settings for one projection year (tax_settings.scheduled_changes).

A scheduled change replaces whitelisted settings from the calendar year it
names, or from the year its milestone is reached, and the replacement lasts
through later years until another change replaces the same setting.

Precedence is deterministic: changes apply in order of their effective year,
and changes effective in the same year apply in their list order, so the later
entry wins. A change keyed to a year before the projection starts is already
in effect in the first year; so is a milestone reached before the start. A
milestone that is missing from the plan or never reached never applies.

Each call builds a new dict from the immutable plan settings, so no year,
deterministic run or Monte Carlo trial can leak changes into another.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

# The only settings a scheduled change may replace (see
# coastmath.schemas.tax_adjustments.ScheduledTaxSettings). Withholding, settlement
# timing, opening year-to-date figures and targets are fixed for the plan.
SCHEDULABLE_SETTINGS = (
    "mode",
    "ordinary_income_tax_rate",
    "capital_gains_tax_rate",
    "state_brackets",
    "adjustments",
    "state_deduction_rules",
    "federal_brackets",
    "federal_standard_deduction",
)


def change_effective_year(change: Mapping, milestone_years: Mapping[str, int]) -> int | None:
    """The first tax year a change applies to, or None if it never applies."""
    if change.get("year") is not None:
        return int(change["year"])
    milestone_id = change.get("milestone_id")
    if milestone_id is None:
        return None
    reached = milestone_years.get(str(milestone_id))
    return None if reached is None else int(reached)


def effective_tax_settings(base: Mapping | None, year: int, milestone_years: Mapping[str, int]) -> dict:
    """The tax settings in force for ``year``.

    Returns ``base`` itself when it has no scheduled changes, so plans without
    them pass the identical object to every consumer. Otherwise returns a new
    dict that never shares mutable values with ``base``.
    """
    settings = base if base is not None else {}
    changes = settings.get("scheduled_changes") or []
    if not changes:
        return settings  # type: ignore[return-value]
    applicable = []
    for index, change in enumerate(changes):
        effective = change_effective_year(change, milestone_years)
        if effective is not None and effective <= year:
            applicable.append((effective, index, change))
    effective_settings = {key: value for key, value in settings.items() if key != "scheduled_changes"}
    for _, _, change in sorted(applicable, key=lambda item: (item[0], item[1])):
        for key, value in (change.get("settings") or {}).items():
            if key not in SCHEDULABLE_SETTINGS or value is None:
                continue
            if key in ("state_brackets", "federal_brackets") and not value:
                # An empty schedule returns to the built-in tables.
                effective_settings.pop(key, None)
                continue
            effective_settings[key] = deepcopy(value)
    return effective_settings

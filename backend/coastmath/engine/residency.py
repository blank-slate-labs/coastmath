"""Per-year residency (country, state and local tax) resolution for tax calculations.

A residency period without a country is in the plan's ``tax_country``. A
residence outside the US has no US state or local tax. Each tax year is
assessed under one country's regime: the country of residence for most of
the year, the later one on a tie (:func:`resolve_country_for_year`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from coastmath.engine.milestones import (
    resolve_deterministic_milestones,
    resolve_trigger_month,
)
from coastmath.engine.types import PlanData, ResidencyPeriodData


def _active_period(
    year: int,
    triggered: set[str],
    plan_data: PlanData,
) -> ResidencyPeriodData | None:
    """Return the residency period governing ``year``, or None for the plan default.

    Iterates residency periods sorted by ``rank`` ascending (lower rank wins).
    A period is active when both:
      - start is satisfied: ``start_milestone_id`` in ``triggered`` OR
        ``start_year <= year`` OR both are NULL (always-started)
      - end not yet reached: ``end_milestone_id`` NOT in ``triggered`` AND
        (``end_year`` is NULL OR ``year <= end_year``)
    """
    periods = sorted(plan_data.residency_periods, key=lambda p: p.rank)
    for p in periods:
        start_ok = (
            (p.start_milestone_id is None and p.start_year is None)
            or (p.start_milestone_id is not None and p.start_milestone_id in triggered)
            or (p.start_year is not None and p.start_year <= year)
        )
        if not start_ok:
            continue
        end_ok = (
            p.end_milestone_id is None or p.end_milestone_id not in triggered
        ) and (p.end_year is None or year <= p.end_year)
        if not end_ok:
            continue
        return p
    return None


def period_country(period: ResidencyPeriodData | None, plan_data: PlanData) -> tuple[str, str | None]:
    """The (country, region) of a residence; None is the plan's default residence.

    A period without a country inherits the plan's country, and its region
    too unless the period names one.
    """
    if period is None:
        return plan_data.tax_country, plan_data.tax_region
    if period.country is None:
        return plan_data.tax_country, period.region or plan_data.tax_region
    return period.country, period.region


def resolve_state_for_year(
    year: int,
    triggered: set[str],
    plan_data: PlanData,
) -> str | None:
    """Return the state_code active in ``year`` per plan_data.residency_periods.

    Falls back to ``plan_data.state_code`` when no period matches. A residence
    outside the US has no state.
    """
    period = _active_period(year, triggered, plan_data)
    if period_country(period, plan_data)[0] != "US":
        return None
    return plan_data.state_code if period is None else period.state_code


def resolve_local_tax_for_year(
    year: int,
    triggered: set[str],
    plan_data: PlanData,
) -> dict | None:
    """Return the local income tax selection of the residence active in ``year``.

    The locality belongs to the same residency period as the state, so a
    period without a locality has no local tax even when the plan default has
    one: the plan-level selection describes the plan-level state only.
    """
    period = _active_period(year, triggered, plan_data)
    if period_country(period, plan_data)[0] != "US":
        return None
    return plan_data.local_tax if period is None else period.local_tax


@dataclass(frozen=True)
class ResidencySpan:
    """State residency over calendar months, with an exclusive end month.

    January is month 1; month 13 is the following January. Fractions use the
    engine's equal-month convention, rather than elapsed calendar days.
    """

    state_code: str | None
    start_month: int
    end_month: int
    # Local income tax selection of the residence (see resolve_local_tax_for_year);
    # excluded from the hash so spans stay hashable.
    local_tax: dict | None = field(default=None, hash=False)

    @property
    def start_fraction(self) -> float:
        return (self.start_month - 1) / 12

    @property
    def end_fraction(self) -> float:
        return (self.end_month - 1) / 12

    @property
    def year_fraction(self) -> float:
        return (self.end_month - self.start_month) / 12


def resolve_residency_spans(
    year: int,
    triggered: set[str],
    plan_data: PlanData,
    triggered_milestone_years: Mapping[str, int] | None = None,
) -> list[ResidencySpan]:
    """Resolve contiguous, nonoverlapping residency spans for the whole year.

    The annual resolver's rank, year bounds, and fallback rules apply in each
    month. A triggered start milestone takes effect at the start of its month;
    an end milestone excludes that month. ``end_year`` remains inclusive of
    December. Dated, age, and deterministic relative milestones retain the
    existing milestone engine's month precision. Dynamic or missing milestones
    have no known intra-year crossing and use January, as the engine does.

    Only IDs in ``triggered`` may take effect; this helper does not fire events.
    Pass the simulation state's ``triggered_milestone_years`` to distinguish
    current from previous triggers. Without a recorded year, deterministic
    dates still distinguish past/current/future years; an undated triggered ID
    is treated as already active. Past triggers apply from January, including
    dates first evaluated after their authored year.

    Always returns complete January-to-January coverage, merging adjacent
    months with the same state (including None) and local tax selection.
    Callers interested only in states must not assume one span per state.
    It deliberately does not use
    ``first_year_fraction``: callers must intersect these calendar fractions
    with their active simulation interval. Residency alone does not establish
    income sourcing, taxable amounts, or a state's part-year tax method.
    """
    if not plan_data.residency_periods:
        if plan_data.tax_country != "US":
            return [ResidencySpan(None, 1, 13, None)]
        return [ResidencySpan(plan_data.state_code, 1, 13, plan_data.local_tax)]

    spans: list[ResidencySpan] = []
    for month, active in enumerate(_monthly_triggers(year, triggered, plan_data, triggered_milestone_years), 1):
        state_code = resolve_state_for_year(year, active, plan_data)
        local_tax = resolve_local_tax_for_year(year, active, plan_data)
        if spans and (spans[-1].state_code, spans[-1].local_tax) == (state_code, local_tax):
            spans[-1] = ResidencySpan(state_code, spans[-1].start_month, month + 1, local_tax)
        else:
            spans.append(ResidencySpan(state_code, month, month + 1, local_tax))
    return spans


def resolve_country_for_year(
    year: int,
    triggered: set[str],
    plan_data: PlanData,
    triggered_milestone_years: Mapping[str, int] | None = None,
) -> tuple[str, str | None]:
    """The (country, region) whose regime taxes ``year``.

    The whole tax year is assessed under one country: the residence for most
    of the calendar year's months, and on a tie the one lived in later. This
    is an approximation of part-year residence rules, which differ by country.
    Month timing follows :func:`resolve_residency_spans`.
    """
    if not plan_data.residency_periods:
        return plan_data.tax_country, plan_data.tax_region
    months: dict[tuple[str, str | None], list[int]] = {}
    for month, active in enumerate(_monthly_triggers(year, triggered, plan_data, triggered_milestone_years), 1):
        residence = period_country(_active_period(year, active, plan_data), plan_data)
        months.setdefault(residence, []).append(month)
    return max(months, key=lambda residence: (len(months[residence]), months[residence][-1]))


def _monthly_triggers(
    year: int,
    triggered: set[str],
    plan_data: PlanData,
    triggered_milestone_years: Mapping[str, int] | None,
) -> list[set[str]]:
    """The milestones in effect in each month of ``year`` (see resolve_residency_spans)."""
    milestones = {
        ms.id: ms
        for ms in resolve_deterministic_milestones(
            plan_data.milestones, plan_data.birth_year, plan_data.birth_month,
        )
    }
    recorded_years = triggered_milestone_years or {}
    first_active_month: dict[str, int] = {}
    for milestone_id in triggered:
        milestone = milestones.get(milestone_id)
        trigger_year = recorded_years.get(milestone_id)
        if trigger_year is None and milestone is not None:
            if milestone.trigger_type == "date" and milestone.trigger_date:
                trigger_year = int(milestone.trigger_date[:4])
        if trigger_year is None or trigger_year < year:
            first_active_month[milestone_id] = 1
        elif trigger_year > year:
            first_active_month[milestone_id] = 13
        else:
            first_active_month[milestone_id] = resolve_trigger_month(
                milestone, plan_data.birth_month, year,
            )

    return [
        {milestone_id for milestone_id, first_month in first_active_month.items() if first_month <= month}
        for month in range(1, 13)
    ]

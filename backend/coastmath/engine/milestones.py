"""Milestone evaluation engine.

Evaluates milestone triggers (age, date, net worth, expense multiples, and
relative dates) and provides
helpers for event activation and year pro-rating.
"""

from __future__ import annotations

import math
from dataclasses import replace

from coastmath.engine.types import IncomeData, MilestoneData, PlanData, SimState

#: CoastMath's financial independence estimate is the ``expense_multiple``
#: rule at this multiple of spending, measured on liquid accounts minus debt.
FI_ESTIMATE_MULTIPLE = 25.0
FI_ESTIMATE_METRIC = "liquid_net_worth"


def expense_multiple_reached(
    state: SimState, multiple: float, annual_expenses: float, metric: str | None,
) -> bool:
    """Whether ``state`` strictly exceeds ``multiple`` times ``annual_expenses``.

    ``metric`` "net_worth" measures total net worth; any other value measures
    liquid accounts minus debt; withdrawal-locked accounts are not liquid.
    The threshold stays strict despite rounding from annualizing a partial
    opening year.
    """
    value = state.total_net_worth() if metric == "net_worth" else (
        state.liquid_account_balance() - state.total_liability_balance())
    target = multiple * annual_expenses
    return value > target and not math.isclose(value, target, rel_tol=1e-12, abs_tol=1e-6)


def claiming_milestone_id(income_id: str) -> str:
    """Id of the synthetic start milestone for a Social Security stream."""
    return f"{income_id}:claiming"


def with_social_security_claiming(plan_data: PlanData) -> PlanData:
    """Give Social Security streams a start milestone at their claiming age.

    A stream marked ``is_social_security`` with a ``claiming_age`` and no start
    milestone would otherwise pay from the plan's first year. This returns a
    shallow copy whose milestone list gains one age milestone per such stream
    and whose streams point at it. Age milestones fire on the plan owner's
    age, so a spouse's claiming age is shifted by the birth-year difference.
    An explicit start milestone always wins over the claiming age.
    """
    extra: list[MilestoneData] = []
    streams: list[IncomeData] = []
    for inc in plan_data.income_streams:
        if not inc.is_social_security or inc.claiming_age is None or inc.start_milestone_id:
            streams.append(inc)
            continue
        owner_age = float(inc.claiming_age)
        if inc.owner == "spouse" and plan_data.spouse_birth_year is not None:
            owner_age += plan_data.spouse_birth_year - plan_data.birth_year
            owner_age += ((plan_data.spouse_birth_month or 1) - (plan_data.birth_month or 1)) / 12.0
        ms_id = claiming_milestone_id(inc.id)
        extra.append(MilestoneData(
            id=ms_id, name=f"{inc.name} at {inc.claiming_age}",
            trigger_type="age", trigger_value=owner_age,
        ))
        streams.append(replace(inc, start_milestone_id=ms_id))
    if not extra:
        return plan_data
    return replace(plan_data, milestones=[*plan_data.milestones, *extra], income_streams=streams)


def never_active_windows(
    events: list[tuple[str, str | None, str | None]],
    milestones: list[MilestoneData],
    fired: dict[str, int],
) -> list[str]:
    """Describe events whose milestone window never opens in a finished projection.

    ``events`` holds ``(name, start_milestone_id, end_milestone_id)``; ``fired``
    maps milestone ids to the year they triggered. A window is dead when its
    end fired but its start never did, or when the start fired after the end.
    Windows whose end has not fired are left alone.
    """
    names = {ms.id: ms.name for ms in milestones}
    dead: list[str] = []
    for name, start_id, end_id in events:
        if not start_id or not end_id or start_id == end_id:
            continue
        end_year = fired.get(end_id)
        if end_year is None:
            continue
        start_year = fired.get(start_id)
        start_name, end_name = names.get(start_id, start_id), names.get(end_id, end_id)
        if start_year is None:
            dead.append(
                f"\u201c{name}\u201d never runs: it ends at \u201c{end_name}\u201d ({end_year}) "
                f"but its start milestone \u201c{start_name}\u201d is never reached in this projection."
            )
        elif start_year > end_year:
            dead.append(
                f"\u201c{name}\u201d never runs: it starts at \u201c{start_name}\u201d ({start_year}) "
                f"after it ends at \u201c{end_name}\u201d ({end_year}). Swap the milestones or choose a later end."
            )
    return dead


def resolve_deterministic_milestones(
    milestones: list[MilestoneData], birth_year: int, birth_month: int | None = None,
) -> list[MilestoneData]:
    """Resolve age/date dependency chains before simulation, preserving months.

    Dynamic bases remain runtime conditions. Cycles have no resolvable date;
    the bounded runtime loop leaves them inactive without hanging. A
    switched-off milestone (``is_active`` False) has no date, so relative
    milestones built on it stay unresolved and never fire, like milestones
    built on one that is never reached.
    """
    lookup = {ms.id: ms for ms in milestones}
    cache: dict[str, tuple[int, int] | None] = {}
    visiting: set[str] = set()

    def date_for(mid: str) -> tuple[int, int] | None:
        if mid in cache:
            return cache[mid]
        if mid in visiting:
            return None
        ms = lookup.get(mid)
        if ms is None or not ms.is_active:
            return None
        visiting.add(mid)
        resolved = None
        if ms.trigger_type == "age" and ms.trigger_value is not None:
            months = math.ceil(float(ms.trigger_value) * 12 - 1e-9)
            year_offset, month_zero = divmod((birth_month or 1) - 1 + months, 12)
            resolved = (birth_year + year_offset, month_zero + 1)
        elif ms.trigger_type == "date" and ms.trigger_date:
            resolved = (int(ms.trigger_date[:4]), int(ms.trigger_date[5:7]))
        elif ms.trigger_type == "relative":
            base = date_for(ms.relative_to_id or "")
            base_ms = lookup.get(ms.relative_to_id or "")
            if base is not None:
                resolved = (base[0] + ms.offset_years, base[1])
            elif base_ms is not None and not base_ms.is_active:
                pass  # Never reached: the base is switched off.
            elif ms.offset_years < 0:
                raise ValueError(f"{ms.name}: cannot anticipate a future financial milestone; use an age or date base")
        visiting.remove(mid)
        cache[mid] = resolved
        return resolved

    result = []
    for ms in milestones:
        resolved = date_for(ms.id)
        result.append(replace(ms, trigger_type="date",
            trigger_date=f"{resolved[0]:04d}-{resolved[1]:02d}-01") if resolved else ms)
    return result


def _temporal_condition_year(condition: dict, state: SimState, birth_year: int,
                             spouse_birth_year: int | None, birth_month: int | None,
                             spouse_birth_month: int | None, dates: dict[str, int]) -> int | None:
    kind = condition["kind"]
    if kind == "age":
        spouse = condition.get("owner", "self") == "spouse"
        born = spouse_birth_year if spouse else birth_year
        month = spouse_birth_month if spouse else birth_month
        if born is None:
            return None
        return born + ((month or 1) - 1 + math.ceil(condition["age"] * 12 - 1e-9)) // 12
    if kind == "year":
        return int(condition["year"])
    if kind == "date":
        return int(condition["date"][:4])
    if kind == "milestone":
        base = state.triggered_milestone_years.get(condition["milestone_id"])
        if base is None:
            base = dates.get(condition["milestone_id"])
        return base + condition.get("offset_years", 0) if base is not None else None
    return None


def _condition_metric(state: SimState, metric: str, account_id: str | None) -> float | None:
    if metric == "net_worth":
        return state.total_net_worth()
    if metric == "liquid_net_worth":
        return state.liquid_account_balance() - state.total_liability_balance()
    if metric == "total_debt":
        return state.total_liability_balance()
    if metric == "account_balance":
        account = state.accounts.get(account_id or "")
        return account.balance if account is not None else None
    if state.milestone_metric_history:
        return state.milestone_metric_history[-1].get(metric)
    return state.last_year_expenses if metric == "annual_spending" else None


def _metric_condition_reached(condition: dict, state: SimState) -> bool:
    account_id = condition.get("account_id")
    measured = _condition_metric(state, condition["metric"], account_id)
    if measured is None:
        return False
    target = condition["value"]
    unit = condition["value_unit"]
    if unit == "today_dollars":
        target *= state.inflation_factor
    elif unit == "percent":
        target /= 100.0
    elif unit == "multiple_of_metric":
        other = condition["other_metric"]
        key = f"account_balance:{account_id}" if other == "account_balance" else other
        window = state.milestone_metric_history[-condition.get("average_years", 1):]
        values = [row[key] for row in window if key in row]
        # Only completed simulated years establish a rolling comparison basis.
        if not values or len(values) != len(window):
            return False
        target *= sum(values) / len(values)
    return measured >= target if condition["comparator"] == ">=" else measured <= target


def _temporal_condition_month(condition: dict, state: SimState, year: int, birth_year: int,
                              spouse_birth_year: int | None, birth_month: int | None,
                              spouse_birth_month: int | None, dates: dict[str, int],
                              date_months: dict[str, int]) -> int | None:
    target = _temporal_condition_year(condition, state, birth_year, spouse_birth_year,
                                      birth_month, spouse_birth_month, dates)
    if target is None or target > year:
        return None
    if target < year:
        return 1
    kind = condition["kind"]
    if kind == "age":
        month = spouse_birth_month if condition.get("owner") == "spouse" else birth_month
        return ((month or 1) - 1 + math.ceil(condition["age"] * 12 - 1e-9)) % 12 + 1
    if kind == "date":
        return int(condition["date"][5:7])
    if kind == "milestone":
        identity = condition["milestone_id"]
        return state.triggered_milestone_months.get(identity, date_months.get(identity, 1))
    return 1


def _conditions_month(conditions: dict, state: SimState, year: int, birth_year: int,
                      spouse_birth_year: int | None, birth_month: int | None,
                      spouse_birth_month: int | None, dates: dict[str, int],
                      date_months: dict[str, int]) -> int | None:
    months = []
    for item in conditions["items"]:
        if item["kind"] == "metric":
            months.append(1 if _metric_condition_reached(item, state) else None)
        else:
            months.append(_temporal_condition_month(item, state, year, birth_year, spouse_birth_year,
                                                    birth_month, spouse_birth_month, dates, date_months))
    if conditions["combinator"] == "all":
        return max(months) if all(month is not None for month in months) else None
    return min((month for month in months if month is not None), default=None)


def _deadline_condition(deadline: dict) -> dict:
    field = {"age": "age", "year": "year", "date": "date", "milestone": "milestone_id"}[deadline["kind"]]
    return {"kind": deadline["kind"], field: deadline["value"], "owner": deadline.get("owner", "self")}


def _deadline_month(deadline: dict | None, state: SimState, year: int, birth_year: int,
                    spouse_birth_year: int | None, birth_month: int | None,
                    spouse_birth_month: int | None, dates: dict[str, int],
                    date_months: dict[str, int]) -> int | None:
    if not deadline:
        return None
    return _temporal_condition_month(
        _deadline_condition(deadline),
        state, year, birth_year, spouse_birth_year, birth_month, spouse_birth_month, dates, date_months)


def evaluate_milestones(
    state: SimState,
    milestones: list[MilestoneData],
    year: int,
    birth_year: int,
    spouse_birth_year: int | None = None,
    annual_expenses: float | None = None,
    birth_month: int | None = None,
    spouse_birth_month: int | None = None,
) -> list[str]:
    """Fire deterministic dates and dynamic chains to a fixed point this year.

    Switched-off milestones never fire or miss. Conditions, deadlines and
    relative milestones that reference one see it as never reached.
    """
    milestones = [ms for ms in resolve_deterministic_milestones(milestones, birth_year, birth_month)
                  if ms.is_active]
    dates = {ms.id: int(ms.trigger_date[:4]) for ms in milestones
             if ms.trigger_type == "date" and ms.trigger_date}
    date_months = {ms.id: int(ms.trigger_date[5:7]) for ms in milestones
                   if ms.trigger_type == "date" and ms.trigger_date}
    newly_triggered: list[str] = []
    for _ in range(len(milestones)):
        changed = False
        for ms in milestones:
            if ms.id in state.missed_milestone_years:
                continue
            if ms.id in state.triggered_milestones and (ms.id not in newly_triggered or ms.trigger_type not in {"conditions", "relative"}):
                continue
            triggered = False
            milestone_year = year
            milestone_month = 1
            if ms.trigger_type == "date" and ms.trigger_date:
                milestone_year = int(ms.trigger_date[:4])
                triggered = year >= milestone_year
                milestone_month = int(ms.trigger_date[5:7])
            elif ms.trigger_type == "net_worth":
                triggered = ms.trigger_value is not None and state.total_net_worth() >= ms.trigger_value
            elif ms.trigger_type == "expense_multiple":
                multiple = ms.expense_multiple if ms.expense_multiple is not None else ms.trigger_value
                if multiple is not None and annual_expenses is not None:
                    triggered = expense_multiple_reached(state, multiple, annual_expenses, ms.metric)
            elif ms.trigger_type == "relative":
                base_year = state.triggered_milestone_years.get(ms.relative_to_id or "")
                if base_year is not None:
                    milestone_year = base_year + ms.offset_years
                    triggered = year >= milestone_year
                    milestone_month = state.triggered_milestone_months.get(ms.relative_to_id or "", 1)
            elif ms.trigger_type == "conditions" and ms.conditions:
                ready_month = _conditions_month(ms.conditions, state, year, birth_year,
                                                spouse_birth_year, birth_month, spouse_birth_month, dates, date_months)
                deadline = ms.conditions.get("deadline")
                limit_month = _deadline_month(deadline, state, year, birth_year, spouse_birth_year,
                                               birth_month, spouse_birth_month, dates, date_months)
                deadline_year = (_temporal_condition_year(_deadline_condition(deadline), state, birth_year,
                                                          spouse_birth_year, birth_month, spouse_birth_month, dates)
                                 if deadline else None)
                triggered = ready_month is not None
                milestone_month = ready_month or 1
                if limit_month is not None and (ready_month is None or ready_month > limit_month
                                                or (deadline_year is not None and deadline_year < year)):
                    triggered = deadline["action"] == "fire"
                    milestone_month = limit_month
                    milestone_year = deadline_year if deadline_year is not None else year
            if triggered:
                if ms.id not in state.triggered_milestones:
                    newly_triggered.append(ms.id)
                    state.triggered_milestones.add(ms.id)
                    changed = True
                elif (state.triggered_milestone_years[ms.id], state.triggered_milestone_months[ms.id]) != (milestone_year, milestone_month):
                    changed = True
                state.triggered_milestone_years[ms.id] = milestone_year
                state.triggered_milestone_months[ms.id] = milestone_month
        if not changed:
            break
    for ms in milestones:
        if ms.trigger_type != "conditions" or not ms.conditions or ms.id in state.triggered_milestones or ms.id in state.missed_milestone_years:
            continue
        deadline = ms.conditions.get("deadline")
        if not deadline or deadline["action"] != "miss":
            continue
        limit_month = _deadline_month(deadline, state, year, birth_year, spouse_birth_year,
                                       birth_month, spouse_birth_month, dates, date_months)
        if limit_month is not None:
            target_year = _temporal_condition_year(_deadline_condition(deadline), state, birth_year,
                                                     spouse_birth_year, birth_month, spouse_birth_month, dates)
            state.missed_milestone_years[ms.id] = target_year if target_year is not None else year
    return newly_triggered


def resolve_trigger_month(
    ms: MilestoneData | None,
    birth_month: int | None,
    year: int,
) -> int:
    """Return the 1–12 month within ``year`` when the milestone fires.

    - Age-triggered → ``birth_month`` (NULL treated as January).
    - Date-triggered → month component of ``trigger_date``.
    - Net-worth or unknown → January (we don't model intra-year crossings).
    """
    if ms is None:
        return 1
    if ms.resolved_month is not None:
        return ms.resolved_month
    if ms.trigger_type == "age":
        return ((birth_month or 1) - 1 + math.ceil(float(ms.trigger_value or 0) * 12 - 1e-9)) % 12 + 1
    if ms.trigger_type == "date" and ms.trigger_date is not None:
        return int(ms.trigger_date[5:7])
    return 1


def is_event_active(
    start_milestone_id: str | None,
    end_milestone_id: str | None,
    triggered: set[str],
) -> bool:
    """Determine whether an event bounded by milestones is currently active.

    Rules:
    - No start milestone → active from the beginning.
    - Start milestone not yet triggered → not active.
    - Start triggered, no end milestone → active indefinitely.
    - Start triggered, end not triggered → active.
    - End milestone triggered → no longer active.
    """
    if start_milestone_id is None:
        return end_milestone_id is None or end_milestone_id not in triggered

    if start_milestone_id not in triggered:
        return False

    return end_milestone_id is None or end_milestone_id not in triggered


def prorate_for_year(
    start_ms: MilestoneData | None,
    end_ms: MilestoneData | None,
    start_month: int | None,
    end_month: int | None,
    triggered: set[str],
    newly_triggered: list[str],
    year: int,
    birth_month: int | None = None,
    simulation_fraction: float = 1.0,
    active_until: float = 1.0,
    active_from: float = 0.0,
) -> float:
    """Return the fraction of *year* during which the event is active (0.0–1.0).

    Pro-rates in the year a bounding milestone triggers:
    - Start triggers this year → active from ``start_month`` onward.
    - End triggers this year → active through ``end_month``.
    - Both trigger this year → active from ``start_month`` through ``end_month``.
    - Neither triggered this year → full year (1.0).

    When ``start_month``/``end_month`` is NULL **and the milestone is triggering
    this year**, the month is derived via ``resolve_trigger_month`` — so an
    age-triggered "retire at 45" with ``birth_month=6`` yields an end-month of 5
    (salary stops in May of the trigger year). For continuing events (milestone
    not firing this year), NULL months fall back to Jan (1) for start and Dec
    (12) for end.

    ``simulation_fraction`` restricts the active period to the trailing part
    of a partial first simulation year. For example, ``0.25`` means the plan
    begins three quarters through the year, and only the overlap between that
    final quarter and the event's active months is counted.
    """
    start_id = start_ms.id if start_ms is not None else None
    end_id = end_ms.id if end_ms is not None else None

    # A newly triggered end still permits part of this year. Ignore the end
    # bound, not its triggered state: it may also be the start milestone.
    end_is_new = end_id is not None and end_id in newly_triggered
    if not is_event_active(start_id, None if end_is_new else end_id, triggered):
        return 0.0

    start_is_new = start_id is not None and start_id in newly_triggered

    if start_is_new:
        sm = start_month if start_month is not None else resolve_trigger_month(
            start_ms, birth_month, year
        )
    else:
        sm = start_month if start_month is not None else 1

    if end_is_new:
        em = end_month if end_month is not None else (
            resolve_trigger_month(end_ms, birth_month, year) - 1
        )
    else:
        em = end_month if end_month is not None else 12

    event_start = (sm - 1) / 12.0 if start_is_new else 0.0
    event_end = em / 12.0 if end_is_new else 1.0
    simulation_start = 1.0 - max(0.0, min(1.0, simulation_fraction))

    # Explicit clamp: em < sm (e.g., age trigger in Jan → em=0) means the event
    # is not active in the trigger year, not a negative fraction.
    overlap_start = max(event_start, simulation_start, active_from)
    fraction = max(0.0, min(event_end, active_until) - overlap_start)
    return max(0.0, min(1.0, fraction))

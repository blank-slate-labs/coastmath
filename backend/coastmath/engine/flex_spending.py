"""Flexible spending rules.

The legacy contract is one trailing-return threshold and reduction.  The
additive advanced contract can instead compare a time-weighted return index
with its prior all-time high and interpolate between explicit rules.  In both
cases the current year's return is excluded because it is appended to state
before these functions run.

One multiplier is computed per simulated year from completed returns only
(``flex_multiplier``).  It is applied in a fixed order, the same for the
deterministic run and every Monte Carlo trial:

1. ordinary expenses, on their discretionary share (scope ``expenses``);
2. withdrawal-strategy spending, re-clamped to the strategy's bounds and kept
   at or above the plan's essential spending (scope ``strategy_spending``);
3. spend-the-leftover cash, after priorities, tax settlement and bills
   (scope ``leftover_spending``); it can only reduce the amount spent, and the
   part not spent is saved.
"""

from __future__ import annotations

import copy
import math
from itertools import pairwise

from coastmath.engine.milestones import is_event_active
from coastmath.engine.types import (
    ExpenseData,
    PlanData,
    SimState,
    SpendingRulesData,
    SpendingRuleThresholdData,
)
from coastmath.engine.withdrawal_strategy import (
    WithdrawalStrategySpec,
    bounded_strategy_spending,
)

DEFAULT_FLEX_SCOPE = ("expenses",)


def discretionary_share(expense: ExpenseData) -> float | None:
    """The share (0-1) of an expense that flexible spending may cut.

    An explicit ``discretionary_fraction`` wins. Otherwise the category keeps
    its all-or-nothing meaning: discretionary 1.0, essential 0.0. An expense
    with neither returns None: it is never cut and stays uncategorized in
    spending outputs, as before partial shares existed.
    """
    if expense.discretionary_fraction is not None:
        return min(1.0, max(0.0, expense.discretionary_fraction))
    if expense.category == "discretionary":
        return 1.0
    if expense.category == "essential":
        return 0.0
    return None


def _prior_returns(state: SimState) -> list[float]:
    """Return only completed annual returns from the simulation state."""
    return state.return_history[:-1] if state.return_history else []


def time_weighted_return_index(returns: list[float]) -> list[float]:
    """Build a cumulative return index, starting at 1.0.

    ``returns`` is expected to contain market returns rather than balance
    changes.  Contributions and withdrawals therefore cannot move this index.
    """
    index = 1.0
    result = [index]
    for annual_return in returns:
        index *= 1.0 + annual_return
        result.append(index)
    return result


def all_time_high_drawdown(returns: list[float]) -> float | None:
    """Return the current index drawdown from its prior all-time high."""
    if not returns:
        return None
    index_path = time_weighted_return_index(returns)
    high_water_mark = max(index_path)
    current_index = index_path[-1]
    if high_water_mark <= 0:
        return -1.0
    return current_index / high_water_mark - 1.0


def all_time_high_delta(returns: list[float]) -> float | None:
    """Signed change of the latest completed index from the high before it.

    Unlike ``all_time_high_drawdown`` the latest index is not part of the high
    it is compared with, so a new all-time high gives a positive value.  A
    value below the earlier high equals the drawdown.
    """
    if not returns:
        return None
    index_path = time_weighted_return_index(returns)
    prior_high = max(index_path[:-1])
    if prior_high <= 0:
        return -1.0
    return index_path[-1] / prior_high - 1.0


def _trailing_return(returns: list[float], lookback_years: int) -> float | None:
    if len(returns) < lookback_years:
        return None
    compound = 1.0
    for annual_return in returns[-lookback_years:]:
        compound *= 1.0 + annual_return
    return compound - 1.0


def _thresholds(rules: SpendingRulesData) -> tuple[list[SpendingRuleThresholdData], bool]:
    """Return sorted rules and whether they came from the advanced list."""
    if rules.thresholds:
        return sorted(rules.thresholds, key=lambda item: item.threshold, reverse=True), True
    if rules.flex_threshold is None:
        return [], False
    return [SpendingRuleThresholdData(rules.flex_threshold, rules.flex_reduction)], False


def _reduction_for_performance(
    performance: float | None,
    rules: SpendingRulesData,
) -> float:
    thresholds, is_explicit_list = _thresholds(rules)
    if performance is None or not thresholds:
        return 0.0

    # Preserve the legacy strict-below comparison.  Explicit lists use an
    # inclusive threshold so their reduction values are stable interpolation
    # endpoints; this is opt-in and does not change old JSONB documents.
    if not is_explicit_list:
        return rules.flex_reduction if performance < thresholds[0].threshold else 0.0
    if performance > thresholds[0].threshold and not math.isclose(
        performance, thresholds[0].threshold, abs_tol=1e-12,
    ):
        return 0.0
    if math.isclose(performance, thresholds[0].threshold, abs_tol=1e-12):
        return thresholds[0].reduction
    if len(thresholds) == 1:
        return thresholds[0].reduction
    if performance <= thresholds[-1].threshold:
        return thresholds[-1].reduction

    for upper, lower in pairwise(thresholds):
        if not (lower.threshold < performance <= upper.threshold):
            continue
        if rules.interpolation == "step":
            return upper.reduction
        span = upper.threshold - lower.threshold
        if span <= 0:
            return upper.reduction
        weight = (upper.threshold - performance) / span
        return upper.reduction + weight * (lower.reduction - upper.reduction)
    return thresholds[-1].reduction


def _increase_for_performance(performance: float | None, rules: SpendingRulesData) -> float:
    """Additive spending increase for a positive performance, 0 at neutral.

    The curve always passes through an explicit neutral point at zero.  Step
    mode returns the increase of the highest point reached; linear mode
    interpolates from the neutral point through the sorted points and holds the
    last increase beyond them.
    """
    if performance is None or not rules.upside_thresholds:
        return 0.0
    if performance <= 0.0 or math.isclose(performance, 0.0, abs_tol=1e-12):
        return 0.0
    points = sorted(rules.upside_thresholds, key=lambda item: item.threshold)
    if rules.interpolation != "linear":
        reached = 0.0
        for point in points:
            if performance >= point.threshold or math.isclose(performance, point.threshold, abs_tol=1e-12):
                reached = point.increase
        return reached
    previous_threshold, previous_increase = 0.0, 0.0
    for point in points:
        if performance <= point.threshold:
            span = point.threshold - previous_threshold
            if span <= 0:
                return point.increase
            weight = (performance - previous_threshold) / span
            return previous_increase + weight * (point.increase - previous_increase)
        previous_threshold, previous_increase = point.threshold, point.increase
    return previous_increase


def flex_multiplier(plan_data: PlanData, state: SimState) -> float:
    """This year's spending multiplier, 1.0 when no rule changes spending.

    Below 1 is a cut (never under the spending floor); above 1 is upside from
    a new all-time high.  Only completed returns are used.
    """
    rules = plan_data.spending_rules
    if rules is None:
        return 1.0
    if not is_event_active(
        rules.start_milestone_id,
        rules.end_milestone_id,
        state.triggered_milestones,
    ):
        return 1.0

    prior_returns = _prior_returns(state)
    if rules.performance_mode == "all_time_high":
        performance = all_time_high_drawdown(prior_returns)
    else:
        performance = _trailing_return(prior_returns, rules.lookback_years)
    reduction = _reduction_for_performance(performance, rules)
    reduction_factor = max(1.0 - reduction, rules.spending_floor)
    factor = reduction_factor if reduction > 0.0 and reduction_factor < 1.0 else 1.0
    if rules.upside_thresholds and rules.performance_mode == "all_time_high":
        factor += _increase_for_performance(all_time_high_delta(prior_returns), rules)
    return factor


def flex_scope(rules: SpendingRulesData | None) -> tuple[str, ...]:
    """The spending streams the multiplier applies to."""
    if rules is None or not rules.flex_scope:
        return DEFAULT_FLEX_SCOPE
    return tuple(rules.flex_scope)


def spends_leftover(plan_data: PlanData, state: SimState) -> bool:
    """Whether this year's unallocated surplus is spent instead of saved.

    The mode follows the same milestone window as the flex rules.  The default
    ("save") never spends, so existing plans are unchanged.
    """
    rules = plan_data.spending_rules
    if rules is None or rules.surplus_mode != "spend_leftover":
        return False
    return is_event_active(rules.start_milestone_id, rules.end_milestone_id, state.triggered_milestones)


def scope_multiplier(plan_data: PlanData, multiplier: float, scope: str) -> float:
    """``multiplier`` when the plan's flex scope includes ``scope``, else 1.0."""
    return multiplier if scope in flex_scope(plan_data.spending_rules) else 1.0


def flex_strategy_spending(
    base: float,
    multiplier: float,
    *,
    share: float,
    spec: WithdrawalStrategySpec,
    portfolio: float,
    inflation_factor: float,
    essential_floor: float,
) -> float:
    """Flexed amount of a strategy's spending for the part of the year it covers.

    ``base`` is the full-year amount the strategy produced after its own
    bounds, and ``share`` the part of the year it covers.  The flexed amount
    stays inside the strategy's minimum and maximum, and a cut never goes below
    ``essential_floor`` (the plan's essential spending for that part of the
    year) unless the strategy's own amount was already lower.
    """
    unflexed = base * share
    if multiplier == 1.0 or unflexed <= 0.0:
        return unflexed
    flexed = bounded_strategy_spending(
        spec, base * multiplier, portfolio=portfolio, inflation_factor=inflation_factor,
    ) * share
    return max(flexed, min(unflexed, max(0.0, essential_floor)))


def apply_flex_rules(
    expenses: list[ExpenseData],
    plan_data: PlanData,
    state: SimState,
    year: int,
) -> list[ExpenseData]:
    """Apply configured flex rules to standard discretionary expenses.

    Args:
        expenses: The current list of expense objects for the year.
        plan_data: Full plan data (contains spending_rules).
        state: Mutable simulation state with annual market returns.
        year: Current simulation year.

    Returns:
        A new list of ExpenseData. Only the discretionary share of each
        expense (``discretionary_share``) is scaled; original objects are
        never mutated.  Plans whose flex scope excludes ordinary expenses are
        returned unchanged.
    """
    del year
    if "expenses" not in flex_scope(plan_data.spending_rules):
        return list(expenses)
    reduction_factor = flex_multiplier(plan_data, state)
    if reduction_factor == 1.0:
        return list(expenses)

    result: list[ExpenseData] = []
    for expense in expenses:
        share = discretionary_share(expense)
        if share is None or share <= 0.0:
            result.append(expense)
            continue
        reduced = copy.copy(expense)
        if share >= 1.0:
            reduced.annual_amount = expense.annual_amount * reduction_factor
        else:
            # Only the discretionary part is scaled; the essential part is paid in full.
            reduced.annual_amount = expense.annual_amount * ((1.0 - share) + share * reduction_factor)
        result.append(reduced)

    return result

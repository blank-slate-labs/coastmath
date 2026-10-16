"""Textbook retirement withdrawal strategies.

Each strategy sets the year's *strategy spending* from the liquid portfolio
at the start of the year and the strategy's own history. When a strategy is
active the simulator replaces the plan's ordinary (non-payroll, non-specific)
expenses with this amount, so the plan's own expenses stay untouched as the
"planned spending" reference and every other mechanic (taxes, drawdown
order, health coverage, milestones) runs unchanged.

Methods (all amounts nominal; ``initial_rate`` is a decimal):
- ``constant_dollar``: initial_rate x starting portfolio, then grown with
  inflation each year (Bengen 1994 "4% rule").
- ``constant_percentage``: initial_rate x current portfolio every year.
- ``guyton_klinger``: constant-dollar with guardrails (Guyton & Klinger 2006):
  the inflation raise is skipped after a year with a negative portfolio
  return when the withdrawal rate exceeds the initial rate; spending is cut
  10% when the current withdrawal rate exceeds 120% of the initial rate and
  raised 10% when it falls below 80%; capital-preservation cuts stop in the
  last 15 years of the plan, while prosperity raises remain available.
- ``vanguard_dynamic``: last year's spending grown with inflation, then held
  within a floor and ceiling around the initial-rate share of the current
  portfolio (Vanguard 2013 dynamic spending; floor -2.5%, ceiling +5%).
- ``rmd_table``: current portfolio divided by the IRS life-expectancy factor
  for the holder's age (Uniform Lifetime Table from 72, Single Life earlier).
- ``fixed_amount``: a today's-dollars amount, inflation-adjusted each year
  unless ``fixed_amount_inflation_adjusted`` is false (then held at its
  first-year nominal value).
- ``one_over_n``: current portfolio divided by the years left in the plan,
  this year included.
- ``vpw``: Bogleheads Variable Percentage Withdrawal. The rate is the
  beginning-of-year annuity payment (spreadsheet PMT with type 1) that spends
  the portfolio over the years left, at the real return of the plan's
  stock/bond mix under the method's stock and bond return assumptions.
- ``kitces_ratchet``: constant-dollar at the initial rate; when the portfolio
  is at least ``ratchet_threshold`` times its inflation-adjusted starting
  value, spending rises by ``ratchet_increase``, at most once every
  ``ratchet_cooldown_years``. Spending is never cut by the rule.
- ``clyatt_95``: the larger of ``initial_rate`` x current portfolio and
  ``clyatt_floor`` x last year's withdrawal.

Every method can be bounded by an optional minimum and maximum, each in
today's dollars (inflation-indexed) or as a share of the current portfolio.
Bounds apply after the method's own rule, and the bounded amount is what the
next year's rule sees as last year's withdrawal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from coastmath.engine.rmd import _DIVISORS as _UNIFORM_DIVISORS
from coastmath.engine.sepp import single_life_expectancy

STRATEGY_METHODS = {
    "constant_dollar": "Constant dollar (inflation-adjusted initial withdrawal)",
    "constant_percentage": "Constant percentage of the current portfolio",
    "guyton_klinger": "Guyton-Klinger guardrails",
    "vanguard_dynamic": "Vanguard dynamic spending (floor/ceiling)",
    "rmd_table": "IRS life-expectancy (RMD-style) percentage",
}

# Methods a plan can save in addition to the comparison set above. The
# comparison endpoint keeps STRATEGY_METHODS as its catalog and default.
SAVED_ONLY_METHODS = {
    "fixed_amount": "Fixed amount (today's dollars)",
    "one_over_n": "1/N: portfolio divided by years remaining",
    "vpw": "Variable Percentage Withdrawal (VPW)",
    "kitces_ratchet": "Kitces ratcheting (raise-only constant dollar)",
    "clyatt_95": "Clyatt 95% rule",
}
ALL_STRATEGY_METHODS = {**STRATEGY_METHODS, **SAVED_ONLY_METHODS}

INCOME_HANDLING_MODES = ("replace_expenses", "withdrawal_plus_income")
CLAMP_UNITS = ("today_dollars", "portfolio_percent")

# Real return assumptions documented for VPW (Bogleheads wiki, "Variable
# percentage withdrawal"); both are editable on the saved strategy.
VPW_STOCK_RETURN = 0.05
VPW_BOND_RETURN = 0.019


@dataclass
class StrategyBound:
    """A minimum or maximum withdrawal: ``amount`` is today's dollars for
    ``today_dollars`` or a decimal share of the current portfolio for
    ``portfolio_percent``."""
    amount: float
    unit: str = "today_dollars"

    def value(self, *, portfolio: float, inflation_factor: float) -> float:
        if self.unit == "portfolio_percent":
            return self.amount * portfolio
        return self.amount * inflation_factor


@dataclass
class WithdrawalStrategySpec:
    method: str
    initial_rate: float = 0.04
    start_milestone_id: str | None = None
    start_age: int | None = None
    # Guyton-Klinger parameters
    upper_guardrail: float = 1.20
    lower_guardrail: float = 0.80
    guardrail_adjustment: float = 0.10
    guardrail_freeze_years: int = 15
    # Vanguard dynamic parameters
    floor: float = -0.025
    ceiling: float = 0.05
    # Fixed amount (today's dollars)
    fixed_amount: float = 0.0
    fixed_amount_inflation_adjusted: bool = True
    # VPW real return assumptions
    vpw_stock_return: float = VPW_STOCK_RETURN
    vpw_bond_return: float = VPW_BOND_RETURN
    # Kitces ratchet parameters
    ratchet_threshold: float = 1.50
    ratchet_increase: float = 0.10
    ratchet_cooldown_years: int = 3
    # Clyatt: share of last year's withdrawal kept as a floor
    clyatt_floor: float = 0.95
    # Optional bounds applied after the method's rule
    minimum: StrategyBound | None = None
    maximum: StrategyBound | None = None
    # How the strategy amount combines with the household's other income
    income_handling: str = "replace_expenses"


@dataclass
class WithdrawalStrategyState:
    started: bool = False
    initial_portfolio: float = 0.0
    initial_spending: float = 0.0
    last_spending: float = 0.0
    last_portfolio: float = 0.0
    guardrail_cuts: int = 0
    guardrail_raises: int = 0
    inflation_freezes: int = 0
    years_active: int = 0
    inflation_factor_at_start: float = 1.0
    last_inflation_factor: float = 1.0
    start_year: int | None = None
    last_ratchet_year: int | None = None
    ratchets: int = 0
    history: list[tuple[int, float]] = field(default_factory=list)


def strategy_spending(
    spec: WithdrawalStrategySpec,
    state: WithdrawalStrategyState,
    *,
    year: int,
    age: int,
    portfolio: float,
    inflation_factor: float,
    years_remaining: int,
    prior_year_return: float = 0.0,
    bond_allocation: float = 0.0,
) -> float:
    """Return this year's strategy spending and update the strategy state.

    ``years_remaining`` counts the modeled plan years left, this one included
    (1 in the final modeled year), so 1/N and VPW spend the whole portfolio in
    that year; ``bond_allocation`` is the plan's bond share this year (VPW only).
    """
    portfolio = max(0.0, portfolio)
    if spec.method not in ALL_STRATEGY_METHODS:
        raise ValueError(f"Unknown withdrawal strategy {spec.method!r}")
    years_left = max(1, years_remaining)
    if not state.started:
        state.started = True
        state.start_year = year
        state.last_ratchet_year = year
        state.initial_portfolio = portfolio
        state.initial_spending = spec.initial_rate * portfolio
        state.inflation_factor_at_start = inflation_factor
        spending = state.initial_spending
        if spec.method in ("constant_percentage", "clyatt_95"):
            spending = spec.initial_rate * portfolio
        elif spec.method == "rmd_table":
            spending = portfolio / _life_expectancy_factor(age)
        elif spec.method == "fixed_amount":
            spending = spec.fixed_amount * inflation_factor
        elif spec.method == "one_over_n":
            spending = portfolio / years_left
        elif spec.method == "vpw":
            spending = portfolio * vpw_rate(spec, years_left, bond_allocation)
        spending = _bounded(spec, spending, portfolio=portfolio, inflation_factor=inflation_factor)
        # The first year's amount is recorded before the portfolio cap, as it
        # always has been; only the returned amount is capped.
        state.last_spending = spending
        state.last_portfolio = portfolio
        state.last_inflation_factor = inflation_factor
        state.years_active = 1
        state.history.append((year, spending))
        return min(spending, portfolio)

    inflation_step = inflation_factor / state.last_inflation_factor if state.last_inflation_factor > 0 else 1.0
    state.last_inflation_factor = inflation_factor
    if spec.method == "constant_dollar":
        spending = state.last_spending * inflation_step
    elif spec.method == "constant_percentage":
        spending = spec.initial_rate * portfolio
    elif spec.method == "rmd_table":
        spending = portfolio / _life_expectancy_factor(age)
    elif spec.method == "vanguard_dynamic":
        # Target the initial-rate share of today's portfolio, but keep the
        # change within the floor/ceiling around last year's inflation-adjusted
        # spending (Vanguard "dynamic spending").
        target = spec.initial_rate * portfolio
        base = state.last_spending * inflation_step
        spending = min(max(target, base * (1 + spec.floor)), base * (1 + spec.ceiling))
    elif spec.method == "guyton_klinger":
        spending = state.last_spending
        prior_return_negative = prior_year_return < 0
        current_rate = (state.last_spending / portfolio) if portfolio > 0 else float("inf")
        # Portfolio management rule: skip the inflation raise after a losing
        # year when the withdrawal rate is above the initial rate.
        if prior_return_negative and current_rate > spec.initial_rate:
            state.inflation_freezes += 1
        else:
            spending *= inflation_step
        if portfolio > 0:
            rate_now = spending / portfolio
            if rate_now > spec.initial_rate * spec.upper_guardrail and years_remaining > spec.guardrail_freeze_years:
                spending *= 1 - spec.guardrail_adjustment
                state.guardrail_cuts += 1
            elif rate_now < spec.initial_rate * spec.lower_guardrail:
                spending *= 1 + spec.guardrail_adjustment
                state.guardrail_raises += 1
    elif spec.method == "fixed_amount":
        spending = spec.fixed_amount * (
            inflation_factor if spec.fixed_amount_inflation_adjusted else state.inflation_factor_at_start
        )
    elif spec.method == "one_over_n":
        spending = portfolio / years_left
    elif spec.method == "vpw":
        spending = portfolio * vpw_rate(spec, years_left, bond_allocation)
    elif spec.method == "kitces_ratchet":
        spending = state.last_spending * inflation_step
        real_growth = inflation_factor / state.inflation_factor_at_start if state.inflation_factor_at_start > 0 else 1.0
        threshold_value = state.initial_portfolio * real_growth * spec.ratchet_threshold
        cooled_down = year - (state.last_ratchet_year or year) >= spec.ratchet_cooldown_years
        if cooled_down and portfolio > 0 and portfolio >= threshold_value:
            spending *= 1 + spec.ratchet_increase
            state.last_ratchet_year = year
            state.ratchets += 1
    else:  # clyatt_95
        spending = max(spec.initial_rate * portfolio, spec.clyatt_floor * state.last_spending)

    spending = _bounded(spec, spending, portfolio=portfolio, inflation_factor=inflation_factor)
    spending = max(0.0, min(spending, portfolio))
    state.last_spending = spending
    state.last_portfolio = portfolio
    state.years_active += 1
    state.history.append((year, spending))
    return spending


def vpw_rate(spec: WithdrawalStrategySpec, years_left: int, bond_allocation: float) -> float:
    """VPW withdrawal rate: the beginning-of-year payment that spends 1 over
    ``years_left`` years at the mix's real return (PMT with type 1)."""
    if years_left <= 1:
        return 1.0
    bonds = min(1.0, max(0.0, bond_allocation))
    rate = (1.0 - bonds) * spec.vpw_stock_return + bonds * spec.vpw_bond_return
    if abs(rate) < 1e-12:
        return 1.0 / years_left
    return rate / ((1.0 - (1.0 + rate) ** -years_left) * (1.0 + rate))


def _bounded(spec: WithdrawalStrategySpec, spending: float, *, portfolio: float, inflation_factor: float) -> float:
    """Apply the optional minimum, then maximum (the maximum wins a conflict)."""
    if spec.minimum is not None:
        spending = max(spending, spec.minimum.value(portfolio=portfolio, inflation_factor=inflation_factor))
    if spec.maximum is not None:
        spending = min(spending, spec.maximum.value(portfolio=portfolio, inflation_factor=inflation_factor))
    return spending


def bounded_strategy_spending(
    spec: WithdrawalStrategySpec, spending: float, *, portfolio: float, inflation_factor: float,
) -> float:
    """``spending`` inside the strategy's optional minimum and maximum."""
    return _bounded(spec, spending, portfolio=portfolio, inflation_factor=inflation_factor)


def spec_from_settings(settings: dict | None) -> WithdrawalStrategySpec | None:
    """The engine spec for a saved ``withdrawal_strategy`` setting, or None
    when the setting is absent or disabled."""
    if not settings or not settings.get("enabled"):
        return None
    known = set(WithdrawalStrategySpec.__dataclass_fields__) - {"minimum", "maximum"}
    values = {key: settings[key] for key in known if settings.get(key) is not None}
    if values.get("start_milestone_id") is not None:
        values["start_milestone_id"] = str(values["start_milestone_id"])

    def bound(raw):
        if not isinstance(raw, dict) or raw.get("amount") is None:
            return None
        return StrategyBound(amount=float(raw["amount"]), unit=raw.get("unit") or "today_dollars")

    return WithdrawalStrategySpec(**values, minimum=bound(settings.get("minimum")),
                                  maximum=bound(settings.get("maximum")))


def _life_expectancy_factor(age: int) -> float:
    if age in _UNIFORM_DIVISORS:
        return float(_UNIFORM_DIVISORS[age])
    return max(1.0, single_life_expectancy(age))

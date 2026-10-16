"""Tests for the flex spending module."""

import pytest

from coastmath.engine.flex_spending import (
    all_time_high_drawdown,
    apply_flex_rules,
    time_weighted_return_index,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PlanData,
    PriorityData,
    SimState,
    SpendingRulesData,
    SpendingRuleThresholdData,
)


def _make_plan(**overrides) -> PlanData:
    defaults = dict(
        plan_id="test-plan",
        birth_year=1990,
        filing_status="single",
        life_expectancy=95,
        start_year=2024,
    )
    defaults.update(overrides)
    return PlanData(**defaults)


def _make_expenses() -> list[ExpenseData]:
    return [
        ExpenseData(id="e1", name="Rent", annual_amount=24000, category="essential"),
        ExpenseData(id="e2", name="Travel", annual_amount=6000, category="discretionary"),
        ExpenseData(id="e3", name="Dining", annual_amount=3000, category="discretionary"),
        ExpenseData(id="e4", name="Insurance", annual_amount=5000),  # no category
    ]


def _make_state(year: int = 2026) -> SimState:
    return SimState(year=year)


def _make_state_with_prior_returns(
    prior_returns: list[float],
    year: int = 2026,
) -> SimState:
    """Create a SimState whose return_history has the given prior-year returns
    plus a dummy current-year entry (which flex spending ignores)."""
    state = SimState(year=year)
    state.return_history = list(prior_returns) + [0.0]  # current year = dummy
    return state


class TestNoOp:
    """Cases where flex rules should NOT modify expenses."""

    def test_no_spending_rules(self):
        plan = _make_plan(spending_rules=None)
        expenses = _make_expenses()
        result = apply_flex_rules(expenses, plan, _make_state(), 2026)
        assert len(result) == 4
        assert result[1].annual_amount == 6000

    def test_no_flex_threshold(self):
        rules = SpendingRulesData(flex_threshold=None)
        plan = _make_plan(spending_rules=rules)
        expenses = _make_expenses()
        result = apply_flex_rules(expenses, plan, _make_state(), 2026)
        assert result[1].annual_amount == 6000

    def test_return_above_threshold(self):
        rules = SpendingRulesData(flex_threshold=-0.05, flex_reduction=0.20)
        plan = _make_plan(spending_rules=rules)
        expenses = _make_expenses()
        state = _make_state_with_prior_returns([0.07])

        result = apply_flex_rules(expenses, plan, state, 2026)

        assert result[1].annual_amount == 6000
        assert result[2].annual_amount == 3000

    def test_return_at_threshold_no_reduction(self):
        # Return just at threshold boundary — should NOT trigger reduction.
        # Use a value slightly above -5% to avoid float rounding in compound calc.
        rules = SpendingRulesData(flex_threshold=-0.05, flex_reduction=0.20)
        plan = _make_plan(spending_rules=rules)
        expenses = _make_expenses()
        state = _make_state_with_prior_returns([-0.049])

        result = apply_flex_rules(expenses, plan, state, 2026)

        assert result[1].annual_amount == 6000


class TestReduction:
    """Cases where flex rules SHOULD reduce discretionary expenses."""

    def test_discretionary_reduced(self):
        rules = SpendingRulesData(flex_threshold=-0.05, flex_reduction=0.20)
        plan = _make_plan(spending_rules=rules)
        expenses = _make_expenses()
        state = _make_state_with_prior_returns([-0.10])

        result = apply_flex_rules(expenses, plan, state, 2026)

        # Discretionary reduced by 20%
        assert result[1].annual_amount == pytest.approx(4800)  # 6000 * 0.8
        assert result[2].annual_amount == pytest.approx(2400)  # 3000 * 0.8

    def test_essential_untouched(self):
        rules = SpendingRulesData(flex_threshold=-0.05, flex_reduction=0.30)
        plan = _make_plan(spending_rules=rules)
        expenses = _make_expenses()
        state = _make_state_with_prior_returns([-0.10])

        result = apply_flex_rules(expenses, plan, state, 2026)

        assert result[0].annual_amount == 24000  # essential — unchanged

    def test_uncategorized_untouched(self):
        rules = SpendingRulesData(flex_threshold=-0.05, flex_reduction=0.30)
        plan = _make_plan(spending_rules=rules)
        expenses = _make_expenses()
        state = _make_state_with_prior_returns([-0.10])

        result = apply_flex_rules(expenses, plan, state, 2026)

        assert result[3].annual_amount == 5000  # no category — unchanged

    def test_originals_not_mutated(self):
        rules = SpendingRulesData(flex_threshold=-0.05, flex_reduction=0.25)
        plan = _make_plan(spending_rules=rules)
        expenses = _make_expenses()
        state = _make_state_with_prior_returns([-0.10])

        result = apply_flex_rules(expenses, plan, state, 2026)

        # Original expense objects should be untouched
        assert expenses[1].annual_amount == 6000
        assert expenses[2].annual_amount == 3000
        # Returned objects should be different instances for discretionary
        assert result[1] is not expenses[1]
        assert result[2] is not expenses[2]
        # Essential/uncategorized can be same instance (not mutated)

    def test_lookback_years_used(self):
        rules = SpendingRulesData(
            flex_threshold=-0.05, flex_reduction=0.20, lookback_years=3,
        )
        plan = _make_plan(spending_rules=rules)
        expenses = _make_expenses()
        # 3 prior years of bad returns + dummy current year
        state = _make_state_with_prior_returns([-0.04, -0.04, -0.04])

        result = apply_flex_rules(expenses, plan, state, 2026)

        # Compound of 3 years at -4% ≈ -11.5%, well below -5% threshold
        assert result[1].annual_amount == pytest.approx(4800)  # 6000 * 0.8

    def test_custom_reduction_pct(self):
        rules = SpendingRulesData(flex_threshold=0.0, flex_reduction=0.50, spending_floor=0.0)
        plan = _make_plan(spending_rules=rules)
        expenses = _make_expenses()
        state = _make_state_with_prior_returns([-0.01])

        result = apply_flex_rules(expenses, plan, state, 2026)

        assert result[1].annual_amount == pytest.approx(3000)  # 6000 * 0.5
        assert result[2].annual_amount == pytest.approx(1500)  # 3000 * 0.5

    def test_spending_floor_clamps_reduction(self):
        """When flex_reduction exceeds (1 - floor), the floor wins."""
        rules = SpendingRulesData(flex_threshold=0.0, flex_reduction=1.0, spending_floor=0.8)
        plan = _make_plan(spending_rules=rules)
        expenses = _make_expenses()
        state = _make_state_with_prior_returns([-0.10])

        result = apply_flex_rules(expenses, plan, state, 2026)

        # Floor of 0.8 means discretionary keeps 80%
        assert result[1].annual_amount == pytest.approx(4800)  # 6000 * 0.8
        assert result[2].annual_amount == pytest.approx(2400)  # 3000 * 0.8

    def test_insufficient_lookback_not_triggered(self):
        """Not enough prior-year history → trailing return is None → no reduction."""
        rules = SpendingRulesData(
            flex_threshold=-0.05, flex_reduction=0.20, lookback_years=3,
        )
        plan = _make_plan(spending_rules=rules)
        expenses = _make_expenses()
        # Only 1 prior year + current year, but lookback needs 3 prior years
        state = _make_state_with_prior_returns([-0.20])

        result = apply_flex_rules(expenses, plan, state, 2026)

        # Insufficient history → not triggered, amounts unchanged
        assert result[1].annual_amount == 6000
        assert result[2].annual_amount == 3000


class TestAllTimeHighFlexSpending:
    def test_time_weighted_index_and_drawdown_follow_path(self):
        returns = [0.50, -0.20, 0.10, -0.10]
        assert time_weighted_return_index(returns) == pytest.approx([1.0, 1.5, 1.2, 1.32, 1.188])
        assert all_time_high_drawdown(returns) == pytest.approx(-0.208)

    def test_ath_path_can_trigger_when_one_year_return_cannot(self):
        rules = SpendingRulesData(
            performance_mode="all_time_high",
            thresholds=[SpendingRuleThresholdData(-0.20, 0.30)],
            spending_floor=0.0,
        )
        plan = _make_plan(spending_rules=rules)
        state = _make_state_with_prior_returns([0.50, -0.20, 0.10, -0.10])
        result = apply_flex_rules(_make_expenses(), plan, state, 2026)
        assert result[1].annual_amount == pytest.approx(4200)

    def test_contributions_and_withdrawals_do_not_enter_trigger(self):
        rules = SpendingRulesData(
            performance_mode="all_time_high",
            thresholds=[SpendingRuleThresholdData(-0.10, 0.30)],
            spending_floor=0.0,
        )
        plan = _make_plan(spending_rules=rules)
        state = _make_state_with_prior_returns([0.10, -0.10])
        state.ytd_contributions["contribution"] = 1_000_000
        state.withdrawal_growth_factors["withdrawal"] = 0.01
        baseline = apply_flex_rules(_make_expenses(), plan, state, 2026)
        state.accounts.clear()
        changed_cash_flows = apply_flex_rules(_make_expenses(), plan, state, 2026)
        assert changed_cash_flows[1].annual_amount == baseline[1].annual_amount

    def test_current_year_return_is_excluded(self):
        rules = SpendingRulesData(
            performance_mode="all_time_high",
            thresholds=[SpendingRuleThresholdData(-0.10, 0.30)],
            spending_floor=0.0,
        )
        plan = _make_plan(spending_rules=rules)
        state = _make_state_with_prior_returns([0.0])
        state.return_history[-1] = -0.80
        result = apply_flex_rules(_make_expenses(), plan, state, 2026)
        assert result[1].annual_amount == 6000

    def test_step_and_linear_interpolate_at_rule_endpoints(self):
        thresholds = [
            SpendingRuleThresholdData(-0.10, 0.10),
            SpendingRuleThresholdData(-0.20, 0.30),
        ]
        linear_plan = _make_plan(spending_rules=SpendingRulesData(
            performance_mode="all_time_high", interpolation="linear",
            thresholds=thresholds, spending_floor=0.0,
        ))
        midpoint = _make_state_with_prior_returns([-0.15])
        linear = apply_flex_rules(_make_expenses(), linear_plan, midpoint, 2026)
        assert linear[1].annual_amount == pytest.approx(4800)

        step_plan = _make_plan(spending_rules=SpendingRulesData(
            performance_mode="all_time_high", interpolation="step",
            thresholds=thresholds, spending_floor=0.0,
        ))
        step = apply_flex_rules(_make_expenses(), step_plan, midpoint, 2026)
        assert step[1].annual_amount == pytest.approx(5400)

        upper = apply_flex_rules(_make_expenses(), linear_plan, _make_state_with_prior_returns([-0.10]), 2026)
        lower = apply_flex_rules(_make_expenses(), linear_plan, _make_state_with_prior_returns([-0.20]), 2026)
        assert upper[1].annual_amount == pytest.approx(5400)
        assert lower[1].annual_amount == pytest.approx(4200)

    def test_floor_and_milestone_window(self):
        rules = SpendingRulesData(
            performance_mode="all_time_high",
            thresholds=[SpendingRuleThresholdData(-0.10, 0.30)],
            spending_floor=0.70,
            start_milestone_id="retirement",
        )
        plan = _make_plan(spending_rules=rules)
        state = _make_state_with_prior_returns([-0.20])
        before = apply_flex_rules(_make_expenses(), plan, state, 2029)
        assert before[1].annual_amount == 6000
        state.triggered_milestones.add("retirement")
        during = apply_flex_rules(_make_expenses(), plan, state, 2030)
        assert during[1].annual_amount == pytest.approx(4200)


def test_simulated_ath_ignores_cash_flows_with_the_same_investment_mix():
    spending = []
    for salary in (0, 100_000):
        plan = _make_plan(
            plan_id="00000000-0000-4000-8000-000000000003",
            birth_year=1980, birth_month=1, life_expectancy=49, start_year=2026,
            accounts={"stocks": AccountInfo(100_000, "taxable_brokerage", cost_basis=100_000)},
            income_streams=[IncomeData("salary", "Salary", salary, growth_rate=0)],
            expenses=[ExpenseData("travel", "Travel", 1_000, inflation_linked=False, category="discretionary")],
            priorities=[PriorityData(1, "stocks")],
            drawdown_order=[DrawdownEntryData(1, "stocks")],
            tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0, "capital_gains_tax_rate": 0},
            spending_rules=SpendingRulesData(performance_mode="all_time_high", spending_floor=0,
                thresholds=[SpendingRuleThresholdData(-0.15, 0.30)]),
        )
        result = run_simulation(plan, override_returns={2026: (.1, 0, 0), 2027: (-.2, 0, 0), 2028: (0, 0, 0)})
        spending.append([row.expenses for row in result.yearly_snapshots])
    # Contributions/withdrawals change dollars held, not the measured return.
    # Allocating flows to assets with DIFFERENT returns can legitimately change
    # subsequent portfolio performance by changing its investment mix.
    assert spending[0] == pytest.approx([1000, 1000, 700])
    assert spending[1] == pytest.approx(spending[0])

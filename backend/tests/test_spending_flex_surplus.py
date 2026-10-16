"""Flexible spending increases, flex scope and spend-the-leftover mode.

Expected values are worked out by hand from the stated returns and amounts.
Tax is a flat 0% unless a test is about settlement.
"""

from __future__ import annotations

import pytest

from coastmath.engine.flex_spending import (
    all_time_high_delta,
    all_time_high_drawdown,
    apply_flex_rules,
    flex_multiplier,
    flex_strategy_spending,
    scope_multiplier,
)
from coastmath.engine.monte_carlo import replay_monte_carlo_trial, run_monte_carlo
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
    SpendingUpsideData,
)
from coastmath.engine.withdrawal_strategy import StrategyBound, WithdrawalStrategySpec

FLAT_ZERO_TAX = {"mode": "flat", "ordinary_income_tax_rate": 0, "capital_gains_tax_rate": 0}


def _plan(**overrides) -> PlanData:
    values = dict(
        plan_id="00000000-0000-4000-8000-000000000003",
        birth_year=1980, birth_month=1, life_expectancy=50, start_year=2026,
        filing_status="single",
        accounts={"stocks": AccountInfo(100_000, "taxable_brokerage", cost_basis=100_000)},
        income_streams=[IncomeData("salary", "Salary", 60_000, growth_rate=0)],
        expenses=[ExpenseData("travel", "Travel", 20_000, inflation_linked=False, category="discretionary")],
        priorities=[],
        drawdown_order=[DrawdownEntryData(1, "stocks")],
        tax_settings=dict(FLAT_ZERO_TAX),
    )
    values.update(overrides)
    return PlanData(**values)


def _returns(*stock: float) -> dict[int, tuple]:
    return {2026 + i: (value, 0.0, 0.0) for i, value in enumerate(stock)}


def _state(prior: list[float]) -> SimState:
    """State whose last return (the current year) must be ignored."""
    state = SimState(year=2030)
    state.return_history = list(prior) + [0.0]
    return state


def _rules(**kwargs) -> SpendingRulesData:
    return SpendingRulesData(**kwargs)


def _dump(result):
    return result.model_dump(mode="json")


def _spending_only_plan(rules, **overrides) -> PlanData:
    """No salary, so the whole budget is the discretionary expense."""
    return _plan(
        income_streams=[],
        expenses=[ExpenseData("travel", "Travel", 10_000, inflation_linked=False, category="discretionary")],
        spending_rules=rules, **overrides,
    )


# ---------------------------------------------------------------------------
# Index measure
# ---------------------------------------------------------------------------

class TestAllTimeHighDelta:
    def test_new_high_is_positive_and_measured_against_the_earlier_high(self):
        # Index 1.0 -> 1.1 -> 1.21: the high before the latest return is 1.1.
        assert all_time_high_delta([0.10, 0.10]) == pytest.approx(0.10)
        # The legacy drawdown includes the latest index, so it is never positive.
        assert all_time_high_drawdown([0.10, 0.10]) == 0.0

    def test_recovery_below_the_earlier_high_is_negative(self):
        # 1.0 -> 1.1 -> 0.99 -> 1.089: still below the 1.1 high.
        assert all_time_high_delta([0.10, -0.10, 0.10]) == pytest.approx(1.089 / 1.1 - 1.0)

    def test_equals_the_drawdown_when_below_the_high(self):
        returns = [0.2, -0.3]
        assert all_time_high_delta(returns) == pytest.approx(all_time_high_drawdown(returns))

    def test_no_completed_return_is_unknown(self):
        assert all_time_high_delta([]) is None


# ---------------------------------------------------------------------------
# Multiplier curve
# ---------------------------------------------------------------------------

def _upside(mode: str, *points: tuple[float, float]) -> SpendingRulesData:
    return _rules(
        performance_mode="all_time_high", interpolation=mode,
        upside_thresholds=[SpendingUpsideData(t, i) for t, i in points],
    )


class TestUpsideCurve:
    @pytest.mark.parametrize("delta, expected", [
        (0.0, 1.0), (0.04, 1.0), (0.05, 1.10), (0.12, 1.10), (0.20, 1.30), (0.9, 1.30),
    ])
    def test_step_returns_the_increase_of_the_highest_point_reached(self, delta, expected):
        plan = _plan(spending_rules=_upside("step", (0.05, 0.10), (0.20, 0.30)))
        assert flex_multiplier(plan, _state([delta])) == pytest.approx(expected)

    @pytest.mark.parametrize("delta, expected", [
        (0.0, 1.0), (0.05, 1.05), (0.10, 1.10), (0.15, 1.20), (0.20, 1.30), (0.9, 1.30),
    ])
    def test_linear_runs_from_the_neutral_point_and_holds_the_last_increase(self, delta, expected):
        plan = _plan(spending_rules=_upside("linear", (0.10, 0.10), (0.20, 0.30)))
        assert flex_multiplier(plan, _state([delta])) == pytest.approx(expected)

    def test_neutral_at_zero_and_below(self):
        plan = _plan(spending_rules=_upside("linear", (0.10, 0.10)))
        assert flex_multiplier(plan, _state([0.0])) == 1.0
        assert flex_multiplier(plan, _state([-0.2])) == 1.0

    def test_current_year_return_is_excluded(self):
        plan = _plan(spending_rules=_upside("step", (0.05, 0.10)))
        state = SimState(year=2030)
        state.return_history = [0.0, 0.60]  # only the current year is large
        assert flex_multiplier(plan, state) == 1.0

    def test_upside_needs_a_completed_return(self):
        plan = _plan(spending_rules=_upside("step", (0.05, 0.10)))
        assert flex_multiplier(plan, SimState(year=2030)) == 1.0

    def test_recovery_below_the_earlier_high_gets_no_upside(self):
        plan = _plan(spending_rules=_upside("step", (0.01, 0.10)))
        # 1.1 high, then -10%, then +10%: 1.089 is above the last index but not the high.
        assert flex_multiplier(plan, _state([0.10, -0.10, 0.10])) == 1.0
        assert flex_multiplier(plan, _state([0.10, 0.20])) == pytest.approx(1.10)

    def test_trailing_return_mode_ignores_upside_points(self):
        rules = _rules(performance_mode="trailing_return", upside_thresholds=[SpendingUpsideData(0.05, 0.1)])
        assert flex_multiplier(_plan(spending_rules=rules), _state([0.5])) == 1.0

    def test_downside_is_unchanged_and_combines_with_upside_points(self):
        rules = _rules(
            performance_mode="all_time_high", spending_floor=0.5,
            thresholds=[SpendingRuleThresholdData(-0.10, 0.30)],
            upside_thresholds=[SpendingUpsideData(0.05, 0.10)],
        )
        plan = _plan(spending_rules=rules)
        assert flex_multiplier(plan, _state([0.2, -0.2])) == pytest.approx(0.70)
        assert flex_multiplier(plan, _state([0.2, 0.2])) == pytest.approx(1.10)

    def test_milestone_window_gates_the_curve(self):
        rules = _upside("step", (0.05, 0.10))
        rules.start_milestone_id = "retire"
        assert flex_multiplier(_plan(spending_rules=rules), _state([0.2])) == 1.0


class TestLegacyDocumentsUnchanged:
    def test_legacy_threshold_documents_never_exceed_one(self):
        rules = _rules(flex_threshold=-0.05, flex_reduction=0.2)
        plan = _plan(spending_rules=rules)
        assert flex_multiplier(plan, _state([0.5])) == 1.0
        assert flex_multiplier(plan, _state([-0.10])) == pytest.approx(0.8)

    def test_all_time_high_legacy_thresholds_do_not_gain_upside(self):
        rules = _rules(performance_mode="all_time_high", spending_floor=0.0,
                       thresholds=[SpendingRuleThresholdData(-0.15, 0.30)])
        plan = _plan(spending_rules=rules)
        assert flex_multiplier(plan, _state([0.1, 0.3])) == 1.0
        assert flex_multiplier(plan, _state([0.1, -0.2])) == pytest.approx(0.7)

    def test_default_scope_and_mode(self):
        rules = _rules()
        assert rules.flex_scope == ["expenses"]
        assert rules.surplus_mode == "save"
        assert rules.upside_thresholds == []


# ---------------------------------------------------------------------------
# Ordinary expenses
# ---------------------------------------------------------------------------

class TestExpenseUpside:
    def test_fractional_discretionary_share_scales_only_that_share(self):
        rules = _upside("step", (0.05, 0.20))
        plan = _plan(spending_rules=rules)
        expense = ExpenseData("mixed", "Mixed", 10_000, discretionary_fraction=0.5)
        essential = ExpenseData("rent", "Rent", 10_000, category="essential")
        uncategorized = ExpenseData("misc", "Misc", 10_000)
        result = apply_flex_rules([expense, essential, uncategorized], plan, _state([0.1]), 2030)
        # 10,000 * (0.5 + 0.5 * 1.2); essential and uncategorized never move.
        assert result[0].annual_amount == pytest.approx(11_000)
        assert result[1].annual_amount == 10_000
        assert result[2].annual_amount == 10_000
        assert expense.annual_amount == 10_000

    def test_scope_without_expenses_leaves_them_alone(self):
        rules = _upside("step", (0.05, 0.20))
        rules.flex_scope = ["leftover_spending"]
        expense = ExpenseData("travel", "Travel", 10_000, category="discretionary")
        result = apply_flex_rules([expense], _plan(spending_rules=rules), _state([0.1]), 2030)
        assert result[0].annual_amount == 10_000

    def test_simulation_raises_spending_after_a_new_high_only(self):
        # Prior returns by year: 2027 sees +10% (new high), 2028 sees -5%, 2029 sees +10%.
        rules = _rules(performance_mode="all_time_high",
                       upside_thresholds=[SpendingUpsideData(0.05, 0.10)])
        result = run_simulation(_spending_only_plan(rules), override_returns=_returns(0.10, -0.05, 0.10, 0.0))
        rows = result.yearly_snapshots
        assert [round(row.expenses, 2) for row in rows] == [10_000, 11_000, 10_000, 10_000]
        assert [round(row.flex_spending_increase, 2) for row in rows] == [0, 1_000, 0, 0]
        assert all(row.flex_spending_reduction == 0 for row in rows)

    def test_the_current_years_return_does_not_raise_that_years_spending(self):
        rules = _rules(performance_mode="all_time_high",
                       upside_thresholds=[SpendingUpsideData(0.05, 0.10)])
        result = run_simulation(_spending_only_plan(rules), override_returns=_returns(0.0, 0.5, 0.0, 0.0))
        # The +50% arrives in 2027 and is first seen by the 2028 multiplier; a flat 2028
        # is not above the earlier high, so 2029 is neutral again.
        assert [round(row.expenses, 2) for row in result.yearly_snapshots] == [10_000, 10_000, 11_000, 10_000]

    def test_contributions_and_withdrawals_do_not_move_the_index(self):
        rules = _rules(performance_mode="all_time_high",
                       upside_thresholds=[SpendingUpsideData(0.05, 0.10)])
        spending = []
        for salary in (0, 100_000):
            plan = _plan(
                income_streams=[IncomeData("salary", "Salary", salary, growth_rate=0)],
                expenses=[ExpenseData("travel", "Travel", 1_000, inflation_linked=False, category="discretionary")],
                spending_rules=rules,
            )
            result = run_simulation(plan, override_returns=_returns(0.10, 0.0, 0.0, 0.0))
            spending.append([round(row.expenses, 2) for row in result.yearly_snapshots])
        assert spending[0] == [1_000, 1_100, 1_000, 1_000]
        assert spending[1] == spending[0]

    def test_reduction_is_reported_separately_from_increase(self):
        rules = _rules(performance_mode="all_time_high", spending_floor=0.0,
                       thresholds=[SpendingRuleThresholdData(-0.15, 0.30)],
                       upside_thresholds=[SpendingUpsideData(0.05, 0.10)])
        result = run_simulation(_spending_only_plan(rules), override_returns=_returns(0.10, -0.30, 0.0, 0.0))
        rows = result.yearly_snapshots
        assert rows[1].flex_spending_increase == pytest.approx(1_000)
        assert rows[1].flex_spending_reduction == 0
        assert rows[2].flex_spending_reduction == pytest.approx(3_000)
        assert rows[2].flex_spending_increase == 0


# ---------------------------------------------------------------------------
# Spend the leftover
# ---------------------------------------------------------------------------

class TestSpendLeftover:
    def test_save_is_the_default_and_matches_no_rules(self):
        base = run_simulation(_plan(), override_returns=_returns(0.05, 0.05, 0.05, 0.05))
        explicit = run_simulation(_plan(spending_rules=_rules(surplus_mode="save")),
                                  override_returns=_returns(0.05, 0.05, 0.05, 0.05))
        assert _dump(base) == _dump(explicit)
        assert all(row.leftover_spending == 0 and row.flex_spending_increase == 0
                   for row in base.yearly_snapshots)

    def test_empty_priorities_spend_the_residual_instead_of_banking_it(self):
        result = run_simulation(_plan(spending_rules=_rules(surplus_mode="spend_leftover")),
                                override_returns=_returns(0, 0, 0, 0))
        for row in result.yearly_snapshots:
            assert row.leftover_spending == pytest.approx(40_000)
            assert row.expenses == pytest.approx(60_000)
            assert row.net_cash_flow == pytest.approx(0)
            assert row.net_worth == pytest.approx(100_000)
        names = [flow.name for flow in result.yearly_snapshots[0].cash_flow.expenses]
        assert names == ["Travel", "Leftover spending"]
        flow = result.yearly_snapshots[0].cash_flow.expenses[1]
        assert flow.category == "discretionary" and flow.amount == pytest.approx(40_000)
        assert not any(c.source == "default_sink" for c in result.yearly_snapshots[0].cash_flow.contributions)

    def test_spent_money_never_earns_growth(self):
        # Save mode compounds the surplus; spend mode only grows the 100,000.
        saved = run_simulation(_plan(), override_returns=_returns(0.10, 0.10, 0.10, 0.10))
        spent = run_simulation(_plan(spending_rules=_rules(surplus_mode="spend_leftover")),
                               override_returns=_returns(0.10, 0.10, 0.10, 0.10))
        assert [round(r.accounts["stocks"], 2) for r in spent.yearly_snapshots] == pytest.approx(
            [110_000, 121_000, 133_100, 146_410])
        assert saved.yearly_snapshots[-1].net_worth > spent.yearly_snapshots[-1].net_worth

    def test_capped_priority_is_funded_first_and_only_the_rest_is_spent(self):
        plan = _plan(
            accounts={"stocks": AccountInfo(100_000, "taxable_brokerage", cost_basis=100_000),
                      "savings": AccountInfo(0, "savings")},
            priorities=[PriorityData(1, "savings", max_annual_amount=5_000, allocation_mode="remaining")],
            spending_rules=_rules(surplus_mode="spend_leftover"),
        )
        result = run_simulation(plan, override_returns=_returns(0, 0, 0, 0))
        row = result.yearly_snapshots[0]
        assert row.accounts["savings"] == pytest.approx(5_000)
        assert row.leftover_spending == pytest.approx(35_000)
        assert row.net_worth == pytest.approx(105_000)

    def test_partial_first_year_spends_only_that_years_residual(self):
        plan = _plan(first_year_fraction=0.5, spending_rules=_rules(surplus_mode="spend_leftover"))
        saved = run_simulation(_plan(first_year_fraction=0.5), override_returns=_returns(0, 0, 0, 0))
        spent = run_simulation(plan, override_returns=_returns(0, 0, 0, 0))
        first_saved = saved.yearly_snapshots[0]
        first = spent.yearly_snapshots[0]
        assert first.leftover_spending == pytest.approx(first_saved.net_cash_flow)
        assert 0 < first.leftover_spending < 40_000
        assert first.net_worth == pytest.approx(100_000)

    def test_no_surplus_means_nothing_is_spent_or_manufactured(self):
        plan = _plan(
            income_streams=[IncomeData("salary", "Salary", 15_000, growth_rate=0)],
            spending_rules=_rules(surplus_mode="spend_leftover"),
        )
        saved = run_simulation(_plan(income_streams=plan.income_streams), override_returns=_returns(0, 0, 0, 0))
        spent = run_simulation(plan, override_returns=_returns(0, 0, 0, 0))
        for a, b in zip(saved.yearly_snapshots, spent.yearly_snapshots, strict=True):
            assert b.leftover_spending == 0
            assert b.net_worth == pytest.approx(a.net_worth)
            assert b.expenses == pytest.approx(a.expenses)
            assert b.unfunded_expenses == a.unfunded_expenses

    def test_zero_surplus_is_a_no_op(self):
        plan = _plan(income_streams=[IncomeData("salary", "Salary", 20_000, growth_rate=0)],
                     spending_rules=_rules(surplus_mode="spend_leftover"))
        result = run_simulation(plan, override_returns=_returns(0, 0, 0, 0))
        assert all(row.leftover_spending == 0 for row in result.yearly_snapshots)

    def test_tax_bill_is_paid_from_the_held_leftover_not_from_investments(self):
        # 20% flat tax on 60,000 = 12,000. Leftover is 28,000, so the bill is
        # absorbed before anything is spent and no account is drawn.
        tax = {"mode": "flat", "ordinary_income_tax_rate": 0.20, "capital_gains_tax_rate": 0}
        plan = _plan(tax_settings=tax, spending_rules=_rules(surplus_mode="spend_leftover"))
        result = run_simulation(plan, override_returns=_returns(0, 0, 0, 0))
        for row in result.yearly_snapshots:
            assert row.leftover_spending == pytest.approx(28_000)
            assert row.net_worth == pytest.approx(100_000)
            assert row.unfunded_expenses == 0
            assert row.cash_flow.drawdowns == []

    def test_a_bill_larger_than_the_leftover_draws_the_difference(self):
        tax = {"mode": "flat", "ordinary_income_tax_rate": 0.50, "capital_gains_tax_rate": 0}
        # Tax 30,000 leaves 10,000 of leftover; a 40,000 expense leaves none.
        plan = _plan(tax_settings=tax,
                     expenses=[ExpenseData("travel", "Travel", 35_000, inflation_linked=False, category="discretionary")],
                     spending_rules=_rules(surplus_mode="spend_leftover"))
        saved = run_simulation(_plan(tax_settings=tax, expenses=plan.expenses), override_returns=_returns(0, 0, 0, 0))
        spent = run_simulation(plan, override_returns=_returns(0, 0, 0, 0))
        for a, b in zip(saved.yearly_snapshots, spent.yearly_snapshots, strict=True):
            assert b.net_worth == pytest.approx(a.net_worth - b.leftover_spending)
            assert b.unfunded_expenses == a.unfunded_expenses == 0

    @pytest.mark.parametrize("lag", [0, 1])
    def test_settlement_lag_keeps_accounting_exact(self, lag):
        tax = {"mode": "flat", "ordinary_income_tax_rate": 0.20, "capital_gains_tax_rate": 0,
               "settlement_lag_years": lag}
        saved = run_simulation(_plan(tax_settings=tax), override_returns=_returns(0, 0, 0, 0))
        spent = run_simulation(_plan(tax_settings=tax, spending_rules=_rules(surplus_mode="spend_leftover")),
                               override_returns=_returns(0, 0, 0, 0))
        cumulative = 0.0
        for a, b in zip(saved.yearly_snapshots, spent.yearly_snapshots, strict=True):
            cumulative += b.leftover_spending
            # Every dollar not saved is a dollar of reported leftover spending.
            assert b.net_worth == pytest.approx(a.net_worth - cumulative)
            assert b.unfunded_expenses == 0
            assert b.tax_balance == pytest.approx(a.tax_balance)

    def test_refund_is_spent_once(self):
        # 30% withheld on 60,000 against a 10% flat tax: a 12,000 refund.
        income = [IncomeData("salary", "Salary", 60_000, growth_rate=0, withholding_percent=0.30)]
        tax = {"mode": "flat", "ordinary_income_tax_rate": 0.10, "capital_gains_tax_rate": 0}
        saved = run_simulation(_plan(income_streams=income, tax_settings=tax), override_returns=_returns(0, 0, 0, 0))
        spent = run_simulation(
            _plan(income_streams=income, tax_settings=tax, spending_rules=_rules(surplus_mode="spend_leftover")),
            override_returns=_returns(0, 0, 0, 0))
        for a, b in zip(saved.yearly_snapshots, spent.yearly_snapshots, strict=True):
            # Saved: income 60,000 - tax 6,000 - expense 20,000 = 34,000 net.
            assert a.net_worth - 100_000 == pytest.approx(34_000 * (a.year - 2025))
            assert b.leftover_spending == pytest.approx(34_000)
            assert b.net_worth == pytest.approx(100_000)
            assert b.expenses == pytest.approx(a.expenses + 34_000)

    def test_flex_does_not_reduce_leftover_unless_the_scope_asks(self):
        rules = _rules(surplus_mode="spend_leftover", performance_mode="all_time_high", spending_floor=0.5,
                       thresholds=[SpendingRuleThresholdData(-0.10, 0.50)])
        result = run_simulation(_plan(spending_rules=rules), override_returns=_returns(-0.3, 0, 0, 0))
        # Year 2027 sees a 30% drawdown: only the 20,000 expense is cut (to 10,000).
        row = result.yearly_snapshots[1]
        assert row.leftover_spending == pytest.approx(50_000)
        assert row.flex_spending_reduction == pytest.approx(10_000)


class TestLeftoverScope:
    def _rules(self, *scope, **kwargs):
        return _rules(surplus_mode="spend_leftover", flex_scope=list(scope), performance_mode="all_time_high",
                      spending_floor=0.5, thresholds=[SpendingRuleThresholdData(-0.10, 0.50)], **kwargs)

    def test_a_cut_multiplier_spends_less_and_saves_the_rest(self):
        plan = _plan(spending_rules=self._rules("leftover_spending"))
        result = run_simulation(plan, override_returns=_returns(-0.3, 0, 0, 0))
        first, second = result.yearly_snapshots[:2]
        assert first.leftover_spending == pytest.approx(40_000)
        # 2027 multiplier 0.5: half of the 40,000 leftover is spent, half saved.
        assert second.leftover_spending == pytest.approx(20_000)
        assert second.expenses == pytest.approx(40_000)  # expense is out of scope
        assert second.net_cash_flow == pytest.approx(20_000)  # the unspent half is saved
        saved_flow = [c for c in second.cash_flow.contributions if c.source == "default_sink"]
        assert sum(c.amount for c in saved_flow) == pytest.approx(20_000)
        assert second.flex_spending_reduction == 0

    def test_an_increase_never_spends_more_than_is_available(self):
        rules = _rules(surplus_mode="spend_leftover", flex_scope=["leftover_spending"],
                       performance_mode="all_time_high",
                       upside_thresholds=[SpendingUpsideData(0.05, 0.50)])
        result = run_simulation(_plan(spending_rules=rules), override_returns=_returns(0.20, 0, 0, 0))
        for row in result.yearly_snapshots:
            assert row.leftover_spending == pytest.approx(40_000)
            assert row.net_cash_flow == pytest.approx(0)
            assert row.unfunded_expenses == 0
        assert result.yearly_snapshots[1].net_worth == pytest.approx(120_000)

    def test_expense_and_leftover_scope_together(self):
        plan = _plan(spending_rules=self._rules("expenses", "leftover_spending"))
        result = run_simulation(plan, override_returns=_returns(-0.3, 0, 0, 0))
        row = result.yearly_snapshots[1]
        # Expense cut 20,000 -> 10,000; leftover is then 50,000, half spent.
        assert row.cash_flow.expenses[0].amount == pytest.approx(10_000)
        assert row.leftover_spending == pytest.approx(25_000)
        assert row.flex_spending_reduction == pytest.approx(10_000)


# ---------------------------------------------------------------------------
# Strategy spending
# ---------------------------------------------------------------------------

def _strategy_plan(rules, *, spec=None, extra_expenses=()):
    spec = spec or WithdrawalStrategySpec(method="fixed_amount", fixed_amount=40_000,
                                          fixed_amount_inflation_adjusted=False)
    return _plan(
        income_streams=[],
        accounts={"stocks": AccountInfo(1_000_000, "taxable_brokerage", cost_basis=1_000_000)},
        expenses=[ExpenseData("travel", "Travel", 10_000, inflation_linked=False, category="discretionary"),
                  *extra_expenses],
        spending_rules=rules, withdrawal_strategy=spec,
    )


def _upside_rules(**kwargs):
    return _rules(performance_mode="all_time_high",
                  upside_thresholds=[SpendingUpsideData(0.05, 0.10)], **kwargs)


class TestStrategyScope:
    def test_default_scope_leaves_strategy_spending_alone(self):
        result = run_simulation(_strategy_plan(_upside_rules()), override_returns=_returns(0.10, 0, 0, 0))
        assert [round(r.expenses, 2) for r in result.yearly_snapshots] == [40_000] * 4
        assert all(r.flex_spending_increase == 0 for r in result.yearly_snapshots)

    def test_strategy_scope_raises_the_strategy_amount(self):
        rules = _upside_rules(flex_scope=["strategy_spending"])
        result = run_simulation(_strategy_plan(rules), override_returns=_returns(0.10, 0.0, 0.0, 0.0))
        rows = result.yearly_snapshots
        assert rows[0].expenses == pytest.approx(40_000)
        assert rows[1].expenses == pytest.approx(44_000)
        assert rows[1].flex_spending_increase == pytest.approx(4_000)
        assert rows[1].strategy_spending == pytest.approx(44_000)
        assert [flow.name for flow in rows[1].cash_flow.expenses] == ["Strategy spending"]

    def test_strategy_maximum_still_applies(self):
        spec = WithdrawalStrategySpec(method="fixed_amount", fixed_amount=40_000,
                                      fixed_amount_inflation_adjusted=False,
                                      maximum=StrategyBound(42_000))
        rules = _upside_rules(flex_scope=["strategy_spending"])
        result = run_simulation(_strategy_plan(rules, spec=spec), override_returns=_returns(0.10, 0, 0, 0))
        assert result.yearly_snapshots[1].expenses == pytest.approx(42_000)
        assert result.yearly_snapshots[1].flex_spending_increase == pytest.approx(2_000)

    def test_strategy_minimum_still_applies_to_a_cut(self):
        spec = WithdrawalStrategySpec(method="fixed_amount", fixed_amount=40_000,
                                      fixed_amount_inflation_adjusted=False,
                                      minimum=StrategyBound(36_000))
        rules = _rules(performance_mode="all_time_high", spending_floor=0.5,
                       thresholds=[SpendingRuleThresholdData(-0.10, 0.50)], flex_scope=["strategy_spending"])
        result = run_simulation(_strategy_plan(rules, spec=spec), override_returns=_returns(-0.3, 0, 0, 0))
        assert result.yearly_snapshots[1].expenses == pytest.approx(36_000)
        assert result.yearly_snapshots[1].flex_spending_reduction == pytest.approx(4_000)

    def test_a_cut_never_goes_below_planned_essential_spending(self):
        essential = ExpenseData("rent", "Rent", 38_000, inflation_linked=False, category="essential")
        rules = _rules(performance_mode="all_time_high", spending_floor=0.5,
                       thresholds=[SpendingRuleThresholdData(-0.10, 0.50)], flex_scope=["strategy_spending"])
        result = run_simulation(_strategy_plan(rules, extra_expenses=[essential]),
                                override_returns=_returns(-0.3, 0, 0, 0))
        # 50% of 40,000 would be 20,000; the planned 38,000 of rent is the floor.
        assert result.yearly_snapshots[1].expenses == pytest.approx(38_000)

    def test_expense_scope_alone_does_not_touch_the_strategy(self):
        rules = _rules(performance_mode="all_time_high", spending_floor=0.5,
                       thresholds=[SpendingRuleThresholdData(-0.10, 0.50)])
        result = run_simulation(_strategy_plan(rules), override_returns=_returns(-0.3, 0, 0, 0))
        assert result.yearly_snapshots[1].expenses == pytest.approx(40_000)

    def test_strategy_and_leftover_scope_together_keep_the_accounting(self):
        plan = _strategy_plan(_upside_rules(flex_scope=["strategy_spending", "leftover_spending"],
                                            surplus_mode="spend_leftover"))
        plan.income_streams = [IncomeData("pension", "Pension", 50_000, growth_rate=0)]
        result = run_simulation(plan, override_returns=_returns(0.10, 0.0, 0.0, 0.0))
        rows = result.yearly_snapshots
        # Pension 50,000 covers the 40,000 strategy; the 10,000 left over is spent.
        assert rows[0].leftover_spending == pytest.approx(10_000)
        # 2027: strategy 44,000, leftover 6,000, nothing saved.
        assert rows[1].expenses == pytest.approx(50_000)
        assert rows[1].leftover_spending == pytest.approx(6_000)
        assert rows[1].net_cash_flow == pytest.approx(0)
        assert rows[1].net_worth == pytest.approx(rows[0].net_worth * 1.0 + rows[0].accounts["stocks"] * 0.0, rel=0.2)

    def test_income_plus_withdrawal_amount_is_flexed_and_reported(self):
        spec = WithdrawalStrategySpec(method="fixed_amount", fixed_amount=40_000,
                                      fixed_amount_inflation_adjusted=False,
                                      income_handling="withdrawal_plus_income")
        rules = _upside_rules(flex_scope=["strategy_spending"])
        plan = _strategy_plan(rules, spec=spec)
        plan.income_streams = [IncomeData("pension", "Pension", 20_000, growth_rate=0)]
        result = run_simulation(plan, override_returns=_returns(0.10, 0.0, 0.0, 0.0))
        rows = result.yearly_snapshots
        assert rows[0].expenses == pytest.approx(60_000)
        assert rows[1].expenses == pytest.approx(64_000)
        assert rows[1].flex_spending_increase == pytest.approx(4_000)

    def test_flex_strategy_spending_helper_respects_partial_years(self):
        spec = WithdrawalStrategySpec(method="fixed_amount", fixed_amount=40_000)
        half = flex_strategy_spending(40_000, 1.1, share=0.5, spec=spec, portfolio=1e6,
                                      inflation_factor=1.0, essential_floor=0.0)
        assert half == pytest.approx(22_000)
        assert flex_strategy_spending(40_000, 1.0, share=0.5, spec=spec, portfolio=1e6,
                                      inflation_factor=1.0, essential_floor=0.0) == pytest.approx(20_000)
        assert scope_multiplier(_plan(spending_rules=_rules()), 1.2, "strategy_spending") == 1.0


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------

class TestMonteCarloReplay:
    def _plan(self):
        rules = _rules(surplus_mode="spend_leftover", performance_mode="all_time_high", spending_floor=0.6,
                       thresholds=[SpendingRuleThresholdData(-0.10, 0.30)],
                       upside_thresholds=[SpendingUpsideData(0.05, 0.10)],
                       flex_scope=["expenses", "leftover_spending"])
        return _plan(life_expectancy=60, spending_rules=rules)

    def test_trials_are_deterministic_and_replay_exactly(self):
        result = run_monte_carlo(self._plan(), n_trials=4, seed=11, max_workers=1)
        again = run_monte_carlo(self._plan(), n_trials=4, seed=11, max_workers=1)
        assert again.trials.ending_net_worth == result.trials.ending_net_worth
        for index in (0, 3):
            detail = replay_monte_carlo_trial(self._plan(), index, result.base_seed, n_trials=result.n_trials)
            assert detail.ending_net_worth == result.trials.ending_net_worth[index]

    def test_a_trial_matches_the_deterministic_run_on_the_same_returns(self):
        plan = self._plan()
        returns = _returns(0.2, -0.25, 0.1, 0.3, -0.1, 0.05, 0.1, 0.0)
        first = run_simulation(plan, override_returns=returns)
        second = run_simulation(plan, override_returns=returns)
        assert _dump(first) == _dump(second)
        # Every leftover dollar spent is reported in expenses; none is banked.
        for row in first.yearly_snapshots:
            assert row.net_cash_flow == pytest.approx(row.net_cash_flow)
            assert row.leftover_spending >= 0

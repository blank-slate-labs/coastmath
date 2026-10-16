"""Textbook withdrawal strategies."""

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.withdrawal_comparison import compare_withdrawal_strategies
from coastmath.engine.withdrawal_strategy import (
    WithdrawalStrategySpec,
    WithdrawalStrategyState,
)
from tests.engine_support import strategy_plan, strategy_spend


class TestStrategyFormulas:
    def test_constant_dollar_grows_with_inflation_only(self):
        spec, st = WithdrawalStrategySpec("constant_dollar", 0.04), WithdrawalStrategyState()
        assert strategy_spend(spec, st) == pytest.approx(40_000)
        assert strategy_spend(spec, st, year=2031, portfolio=1_500_000, inflation_factor=1.03) == pytest.approx(41_200)
        assert strategy_spend(spec, st, year=2032, portfolio=500_000, inflation_factor=1.03 * 1.02) == pytest.approx(41_200 * 1.02)

    def test_constant_percentage_tracks_portfolio(self):
        spec, st = WithdrawalStrategySpec("constant_percentage", 0.05), WithdrawalStrategyState()
        assert strategy_spend(spec, st) == pytest.approx(50_000)
        assert strategy_spend(spec, st, year=2031, portfolio=800_000) == pytest.approx(40_000)

    def test_rmd_table_uses_irs_factors(self):
        spec, st = WithdrawalStrategySpec("rmd_table"), WithdrawalStrategyState()
        assert strategy_spend(spec, st, age=75) == pytest.approx(1_000_000 / 24.6)   # Uniform Lifetime Table
        assert strategy_spend(spec, st, year=2031, age=65, portfolio=1_000_000) == pytest.approx(1_000_000 / 22.9)  # Single Life below 72

    def test_vanguard_dynamic_respects_floor_and_ceiling(self):
        spec, st = WithdrawalStrategySpec("vanguard_dynamic", 0.04), WithdrawalStrategyState()
        assert strategy_spend(spec, st) == pytest.approx(40_000)
        # Portfolio jumps 50%: target 60k but ceiling is +5% over inflation-adjusted 40k*1.02
        assert strategy_spend(spec, st, year=2031, portfolio=1_500_000, inflation_factor=1.02) == pytest.approx(40_000 * 1.02 * 1.05)
        # Portfolio halves: target 30k but floor is -2.5%
        prev = st.last_spending
        assert strategy_spend(spec, st, year=2032, portfolio=600_000, inflation_factor=1.02) == pytest.approx(prev * 0.975)

    def test_guyton_klinger_guardrails_and_inflation_freeze(self):
        spec, st = WithdrawalStrategySpec("guyton_klinger", 0.05), WithdrawalStrategyState()
        assert strategy_spend(spec, st) == pytest.approx(50_000)
        # Portfolio falls to 700k: withdrawal rate 7.1% > 6% (120% of 5%) -> inflation frozen and 10% cut.
        cut = strategy_spend(spec, st, year=2031, portfolio=700_000, inflation_factor=1.03, prior_year_return=-0.25)
        assert cut == pytest.approx(45_000)
        assert st.inflation_freezes == 1 and st.guardrail_cuts == 1
        # Portfolio soars to 2.5M: rate 1.9% < 4% (80% of 5%) -> inflation raise then 10% increase.
        raised = strategy_spend(spec, st, year=2032, portfolio=2_500_000, inflation_factor=1.03 * 1.02)
        assert raised == pytest.approx(45_000 * 1.02 * 1.10)
        assert st.guardrail_raises == 1
        # No guardrail adjustments in the final 15 years.
        st2 = WithdrawalStrategyState()
        strategy_spend(spec, st2, years_remaining=10)
        assert strategy_spend(spec, st2, year=2031, portfolio=500_000, years_remaining=9) == pytest.approx(50_000)  # frozen, no cut
        assert st2.guardrail_cuts == 0

    def test_spending_never_exceeds_portfolio(self):
        spec, st = WithdrawalStrategySpec("constant_dollar", 0.04), WithdrawalStrategyState()
        strategy_spend(spec, st)
        assert strategy_spend(spec, st, year=2031, portfolio=10_000) == pytest.approx(10_000)

    def test_unknown_method_rejected(self):
        with pytest.raises(ValueError):
            spec, st = WithdrawalStrategySpec("magic"), WithdrawalStrategyState()
            strategy_spend(spec, st)
            strategy_spend(spec, st, year=2031)


class TestSimulatorIntegration:
    def test_strategy_replaces_planned_expenses_from_start_and_keeps_them_for_reporting(self):
        plan = strategy_plan()
        spec = WithdrawalStrategySpec("constant_dollar", 0.04, start_milestone_id="retire")
        base = {s.year: s for s in run_simulation(plan).yearly_snapshots}
        strat = {s.year: s for s in run_simulation(plan, withdrawal_strategy=spec).yearly_snapshots}
        # Before retirement (age 63 in 2028) nothing changes.
        assert strat[2026].strategy_spending is None and strat[2026].expenses == pytest.approx(base[2026].expenses)
        # From 2028 the strategy amount replaces the plan's living expense.
        first = strat[2028]
        assert first.strategy_spending == pytest.approx(0.04 * sum(strat[2027].accounts.values()))
        assert first.planned_expenses == pytest.approx(base[2028].expenses)
        assert first.expenses == pytest.approx(first.strategy_spending)
        assert strat[2029].strategy_spending == pytest.approx(first.strategy_spending * 1.02)
        assert any(e.name == "Strategy spending" for e in first.cash_flow.expenses)

    def test_healthcare_is_added_on_top_of_strategy_spending(self):
        plan = strategy_plan(healthcare_settings={"enabled": True, "medicare_enabled": True, "magi_prior_year": 10_000, "magi_two_years_prior": 10_000})
        spec = WithdrawalStrategySpec("constant_percentage", 0.04, start_age=65)
        snaps = {s.year: s for s in run_simulation(plan, withdrawal_strategy=spec).yearly_snapshots}
        s = snaps[2031]  # age 66: Medicare premiums apply
        assert s.healthcare is not None and s.healthcare.total > 0
        assert s.expenses == pytest.approx(s.strategy_spending + s.healthcare.total)


def test_comparison_reports_planned_and_each_strategy_with_real_spending():
    plan = strategy_plan()
    out = compare_withdrawal_strategies(plan, methods=["constant_dollar", "guyton_klinger", "rmd_table"],
                                        initial_rate=0.04, start_milestone_id="retire", start_age=None, mc_trials=0)
    assert out.planned.method == "planned"
    assert out.planned.start_year == 2028
    assert out.planned.spending_path[0]["nominal"] == pytest.approx(50_000 * 1.02 ** 2)
    assert [s.method for s in out.strategies] == ["constant_dollar", "guyton_klinger", "rmd_table"]
    cd = out.strategies[0]
    assert cd.start_year == 2028 and cd.first_year_spending > 0
    assert out.planned.first_year_spending == pytest.approx(cd.spending_path[0]["planned_nominal"])
    # Constant-dollar real spending is flat: min == max within rounding.
    assert cd.min_real_spending == pytest.approx(cd.max_real_spending, rel=1e-6)
    assert cd.real_spending_drawdown == pytest.approx(0.0, abs=1e-9)
    rmd = out.strategies[2]
    assert rmd.max_real_spending > rmd.min_real_spending  # varies with the portfolio and age
    assert out.caveats and all(s.monte_carlo_success_rate is None for s in out.strategies)
    with pytest.raises(ValueError):
        compare_withdrawal_strategies(plan, methods=["nope"], initial_rate=0.04, start_milestone_id=None, start_age=None)

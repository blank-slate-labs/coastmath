"""Saved withdrawal strategies: added methods, bounds, income handling and
the plan-level setting used by projections and Monte Carlo."""

import uuid
from dataclasses import replace

import pytest

from coastmath.engine.assumption_curves import DEFAULT_BOND_ALLOCATION
from coastmath.engine.monte_carlo import run_monte_carlo
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
)
from coastmath.engine.withdrawal_comparison import compare_withdrawal_strategies
from coastmath.engine.withdrawal_strategy import (
    StrategyBound,
    WithdrawalStrategySpec,
    WithdrawalStrategyState,
    spec_from_settings,
    vpw_rate,
)
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data
from coastmath.schemas.withdrawal_strategy import WithdrawalStrategySettings
from tests.engine_support import strategy_spend


def _pmt_due(rate, n):
    """Independent beginning-of-period annuity factor: 1 / sum of discount factors."""
    return 1.0 / sum((1 + rate) ** -k for k in range(n))


class TestAddedMethods:
    def test_fixed_amount_in_todays_dollars_with_and_without_inflation(self):
        spec, st = WithdrawalStrategySpec("fixed_amount", fixed_amount=60_000), WithdrawalStrategyState()
        assert strategy_spend(spec, st, inflation_factor=1.10) == pytest.approx(66_000)
        assert strategy_spend(spec, st, year=2031, inflation_factor=1.10 * 1.03) == pytest.approx(60_000 * 1.10 * 1.03)
        assert strategy_spend(spec, st, year=2032, portfolio=200_000, inflation_factor=1.2) == pytest.approx(72_000)
        flat = WithdrawalStrategySpec("fixed_amount", fixed_amount=60_000, fixed_amount_inflation_adjusted=False)
        st = WithdrawalStrategyState()
        assert strategy_spend(flat, st, inflation_factor=1.10) == pytest.approx(66_000)
        assert strategy_spend(flat, st, year=2031, inflation_factor=1.25) == pytest.approx(66_000)
        assert strategy_spend(flat, st, year=2032, inflation_factor=1.40) == pytest.approx(66_000)

    def test_one_over_n_divides_by_years_left_including_this_one(self):
        spec, st = WithdrawalStrategySpec("one_over_n"), WithdrawalStrategyState()
        assert strategy_spend(spec, st, years_remaining=30) == pytest.approx(1_000_000 / 30)
        assert strategy_spend(spec, st, year=2031, portfolio=900_000, years_remaining=10) == pytest.approx(90_000)
        assert strategy_spend(spec, st, year=2032, portfolio=500_000, years_remaining=1) == pytest.approx(500_000)

    def test_vpw_rate_is_annuity_due_at_the_mix_return_and_rises_as_years_shrink(self):
        spec = WithdrawalStrategySpec("vpw")
        mix = 0.4 * 0.05 + 0.6 * 0.019  # 40% stocks, 60% bonds
        rates = [vpw_rate(spec, n, bond_allocation=0.6) for n in (40, 30, 20, 10, 5, 2)]
        assert rates == sorted(rates)
        for n, rate in zip((40, 30, 20, 10, 5, 2), rates, strict=True):
            assert rate == pytest.approx(_pmt_due(mix, n), rel=1e-12)
        assert vpw_rate(spec, 1, 0.6) == 1.0
        # More stock means a higher assumed return and a higher rate.
        assert vpw_rate(spec, 30, 0.0) > vpw_rate(spec, 30, 1.0)
        assert vpw_rate(spec, 30, 1.0) == pytest.approx(_pmt_due(0.019, 30))
        # Editable return assumptions; a zero return reduces to 1/N.
        assert vpw_rate(replace(spec, vpw_stock_return=0.0, vpw_bond_return=0.0), 25, 0.5) == pytest.approx(1 / 25)

    def test_vpw_spending_over_several_years(self):
        spec, st = WithdrawalStrategySpec("vpw"), WithdrawalStrategyState()
        first = strategy_spend(spec, st, years_remaining=30, bond_allocation=0.4)
        assert first == pytest.approx(1_000_000 * _pmt_due(0.6 * 0.05 + 0.4 * 0.019, 30))
        later = strategy_spend(spec, st, year=2031, portfolio=1_000_000, years_remaining=29, bond_allocation=0.4)
        assert later > first
        assert strategy_spend(spec, st, year=2059, portfolio=50_000, years_remaining=1, bond_allocation=0.4) == pytest.approx(50_000)

    def test_kitces_ratchet_raises_on_threshold_respects_cooldown_and_never_cuts(self):
        spec, st = WithdrawalStrategySpec("kitces_ratchet", 0.04), WithdrawalStrategyState()
        assert strategy_spend(spec, st) == pytest.approx(40_000)
        # Portfolio 160% of start in year 2: cooldown (3 years) not elapsed, plain inflation step.
        assert strategy_spend(spec, st, year=2031, portfolio=1_600_000, inflation_factor=1.02) == pytest.approx(40_800)
        assert st.ratchets == 0
        assert strategy_spend(spec, st, year=2032, portfolio=1_600_000, inflation_factor=1.02) == pytest.approx(40_800)
        # Year 4: three years since start; 1.6M >= 1.5 x 1.0M x 1.02 -> raise 10%.
        assert strategy_spend(spec, st, year=2033, portfolio=1_600_000, inflation_factor=1.02) == pytest.approx(40_800 * 1.10)
        assert st.ratchets == 1
        # Next year qualifies again but is inside the new cooldown.
        assert strategy_spend(spec, st, year=2034, portfolio=2_000_000, inflation_factor=1.02) == pytest.approx(40_800 * 1.10)
        # A crash never cuts spending.
        assert strategy_spend(spec, st, year=2035, portfolio=600_000, inflation_factor=1.02) == pytest.approx(40_800 * 1.10)
        # Threshold is against the inflation-adjusted start: 1.6M < 1.5 x 1.2M.
        assert strategy_spend(spec, st, year=2036, portfolio=1_600_000, inflation_factor=1.2) == pytest.approx(40_800 * 1.10 * 1.2 / 1.02)
        assert st.ratchets == 1
        assert strategy_spend(spec, st, year=2037, portfolio=1_900_000, inflation_factor=1.2) == pytest.approx(40_800 * 1.10 * 1.2 / 1.02 * 1.10)
        assert st.ratchets == 2

    def test_clyatt_floor_keeps_95_percent_of_last_withdrawal(self):
        spec, st = WithdrawalStrategySpec("clyatt_95", 0.04), WithdrawalStrategyState()
        assert strategy_spend(spec, st) == pytest.approx(40_000)
        assert strategy_spend(spec, st, year=2031, portfolio=700_000) == pytest.approx(38_000)       # floor beats 28k
        assert strategy_spend(spec, st, year=2032, portfolio=700_000) == pytest.approx(36_100)       # floor of the floor
        assert strategy_spend(spec, st, year=2033, portfolio=1_200_000) == pytest.approx(48_000)     # rate beats floor
        custom = WithdrawalStrategySpec("clyatt_95", 0.05, clyatt_floor=0.90)
        st = WithdrawalStrategyState()
        strategy_spend(custom, st)
        assert strategy_spend(custom, st, year=2031, portfolio=500_000) == pytest.approx(45_000)


class TestBounds:
    def test_todays_dollar_bounds_are_inflation_indexed_and_feed_next_year(self):
        spec = WithdrawalStrategySpec("constant_dollar", 0.04, minimum=StrategyBound(45_000, "today_dollars"))
        st = WithdrawalStrategyState()
        assert strategy_spend(spec, st, inflation_factor=1.1) == pytest.approx(49_500)
        # Next year's constant-dollar step starts from the bounded amount.
        assert strategy_spend(spec, st, year=2031, inflation_factor=1.1 * 1.02) == pytest.approx(49_500 * 1.02)
        capped = WithdrawalStrategySpec("constant_percentage", 0.06, maximum=StrategyBound(50_000, "today_dollars"))
        st = WithdrawalStrategyState()
        assert strategy_spend(capped, st, inflation_factor=1.05) == pytest.approx(52_500)
        assert strategy_spend(capped, st, year=2031, portfolio=500_000, inflation_factor=1.05) == pytest.approx(30_000)

    def test_portfolio_share_bounds_use_current_portfolio(self):
        spec = WithdrawalStrategySpec("clyatt_95", 0.04, maximum=StrategyBound(0.05, "portfolio_percent"))
        st = WithdrawalStrategyState()
        assert strategy_spend(spec, st) == pytest.approx(40_000)
        # Clyatt floor would be 38k; the 5% cap of 600k is 30k and wins.
        assert strategy_spend(spec, st, year=2031, portfolio=600_000) == pytest.approx(30_000)
        assert st.last_spending == pytest.approx(30_000)
        # The floor now works from the bounded 30k.
        assert strategy_spend(spec, st, year=2032, portfolio=500_000) == pytest.approx(25_000)  # cap 25k < floor 28.5k
        floor = WithdrawalStrategySpec("rmd_table", minimum=StrategyBound(0.05, "portfolio_percent"))
        assert strategy_spend(floor, WithdrawalStrategyState(), age=60) == pytest.approx(50_000)

    def test_maximum_wins_a_conflict_and_portfolio_still_caps(self):
        spec = WithdrawalStrategySpec("constant_dollar", 0.04, minimum=StrategyBound(0.10, "portfolio_percent"),
                                      maximum=StrategyBound(70_000, "today_dollars"))
        assert strategy_spend(spec, WithdrawalStrategyState()) == pytest.approx(70_000)
        spec = WithdrawalStrategySpec("fixed_amount", fixed_amount=90_000)
        st = WithdrawalStrategyState()
        strategy_spend(spec, st)
        assert strategy_spend(spec, st, year=2031, portfolio=20_000) == pytest.approx(20_000)


def _plan(**overrides) -> PlanData:
    defaults = dict(
        plan_id=str(uuid.uuid4()), birth_year=1965, filing_status="single", life_expectancy=80,
        start_year=2026, income_streams=[], priorities=[],
        milestones=[MilestoneData(id="retire", name="Retire", trigger_type="age", trigger_value=63)],
        expenses=[ExpenseData(id="living", name="Living", annual_amount=50_000, inflation_linked=True)],
        accounts={"brok": AccountInfo(balance=1_500_000, account_type="taxable_brokerage", cost_basis=1_500_000)},
        drawdown_order=[DrawdownEntryData(rank=1, source_account_id="brok")],
        assumptions=AssumptionData(inflation_rate=0.02, stock_growth_rate=0.05, bond_return_rate=0.0),
    )
    defaults.update(overrides)
    return PlanData(**defaults)


def _dump(result):
    return [s.model_dump() for s in result.yearly_snapshots]


class TestSavedStrategy:
    def test_disabled_or_absent_setting_matches_baseline(self):
        assert spec_from_settings(None) is None
        assert spec_from_settings({}) is None
        assert spec_from_settings({"enabled": False, "method": "vpw"}) is None
        plan = _plan()
        assert _dump(run_simulation(plan)) == _dump(run_simulation(replace(plan, withdrawal_strategy=None)))

    def test_saved_strategy_drives_the_projection_and_explicit_spec_wins(self):
        settings = WithdrawalStrategySettings(enabled=True, method="clyatt_95", initial_rate=0.035,
                                              start_milestone_id="retire").model_dump(mode="json")
        spec = spec_from_settings(settings)
        assert spec.method == "clyatt_95" and spec.start_milestone_id == "retire" and spec.minimum is None
        saved = replace(_plan(), withdrawal_strategy=spec)
        assert _dump(run_simulation(saved)) == _dump(run_simulation(_plan(), withdrawal_strategy=spec))
        snaps = {s.year: s for s in run_simulation(saved).yearly_snapshots}
        assert snaps[2027].strategy_spending is None
        assert snaps[2028].strategy_spending == pytest.approx(0.035 * sum(snaps[2027].accounts.values()))
        explicit = WithdrawalStrategySpec("constant_dollar", 0.04, start_milestone_id="retire")
        assert _dump(run_simulation(saved, withdrawal_strategy=explicit)) == _dump(run_simulation(_plan(), withdrawal_strategy=explicit))

    def test_bounds_round_trip_from_settings(self):
        settings = WithdrawalStrategySettings(
            enabled=True, method="vpw", minimum={"unit": "today_dollars", "amount": 30_000},
            maximum={"unit": "portfolio_percent", "amount": 0.08}).model_dump(mode="json")
        spec = spec_from_settings(settings)
        assert spec.minimum == StrategyBound(30_000, "today_dollars")
        assert spec.maximum == StrategyBound(0.08, "portfolio_percent")

    def test_vpw_uses_the_plan_bond_allocation(self):
        plan = replace(_plan(), withdrawal_strategy=WithdrawalStrategySpec("vpw", start_age=65))
        snaps = {s.year: s for s in run_simulation(plan).yearly_snapshots}
        # Engine default allocation applies when the plan sets no curve.
        portfolio = sum(snaps[2029].accounts.values())
        # Life expectancy 80 ends the projection after 2044: 2030-2044 is 15 years.
        years_left = 1965 + 80 - 2030
        rate = (1 - DEFAULT_BOND_ALLOCATION) * 0.05 + DEFAULT_BOND_ALLOCATION * 0.019
        assert snaps[2030].strategy_spending == pytest.approx(portfolio * _pmt_due(rate, years_left), rel=1e-9)

    def test_monte_carlo_trials_use_the_saved_strategy(self):
        spec = WithdrawalStrategySpec("constant_percentage", 0.06, start_milestone_id="retire")
        saved = replace(_plan(), withdrawal_strategy=spec)
        via_saved = run_monte_carlo(saved, n_trials=6, seed=11, max_workers=1)
        via_arg = run_monte_carlo(_plan(), n_trials=6, seed=11, withdrawal_strategy=spec, max_workers=1)
        baseline = run_monte_carlo(_plan(), n_trials=6, seed=11, max_workers=1)
        assert via_saved.median_final_net_worth == pytest.approx(via_arg.median_final_net_worth)
        assert via_saved.success_rate == via_arg.success_rate
        assert via_saved.median_final_net_worth != pytest.approx(baseline.median_final_net_worth)

    def test_comparison_ignores_the_saved_strategy(self):
        kwargs = dict(methods=["constant_dollar", "rmd_table"], initial_rate=0.04, start_milestone_id="retire",
                      start_age=None, mc_trials=0)
        plain = compare_withdrawal_strategies(_plan(), **kwargs)
        saved = compare_withdrawal_strategies(
            replace(_plan(), withdrawal_strategy=WithdrawalStrategySpec("one_over_n", income_handling="withdrawal_plus_income")),
            **kwargs)
        assert saved.planned == plain.planned
        assert saved.strategies == plain.strategies


def _flat_tax(plan):
    return replace(plan, tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0.0, "capital_gains_tax_rate": 0.0})


class TestIncomeHandling:
    def _pension_plan(self, handling, rate=0.04):
        pension = IncomeData(id="pension", name="Pension", annual_amount=30_000, growth_rate=0.0,
                             start_milestone_id="retire", is_earned_income=False)
        spec = WithdrawalStrategySpec("constant_percentage", rate, start_milestone_id="retire", income_handling=handling)
        return replace(_plan(income_streams=[pension]), withdrawal_strategy=spec)

    def test_replace_expenses_is_the_default_semantics(self):
        plan = self._pension_plan("replace_expenses")
        explicit = run_simulation(replace(plan, withdrawal_strategy=None),
                                  withdrawal_strategy=WithdrawalStrategySpec("constant_percentage", 0.04, start_milestone_id="retire"))
        assert _dump(run_simulation(plan)) == _dump(explicit)

    def test_withdrawal_plus_income_spends_withdrawal_and_income_without_saving(self):
        plan = _flat_tax(self._pension_plan("withdrawal_plus_income"))
        snaps = {s.year: s for s in run_simulation(plan).yearly_snapshots}
        for year in (2028, 2032, 2040):
            s, prior = snaps[year], snaps[year - 1]
            target = 0.04 * sum(prior.accounts.values())
            drawn = sum(d.amount for d in s.cash_flow.drawdowns)
            saved = sum(c.amount for c in s.cash_flow.contributions if c.source != "reinvestment")
            assert drawn == pytest.approx(target, rel=1e-6)
            assert saved == pytest.approx(0.0, abs=0.01)
            assert s.strategy_spending == pytest.approx(target + 30_000, rel=1e-6)
            assert s.planned_expenses == pytest.approx(50_000 * 1.02 ** (year - 2026), rel=1e-6)

    def test_replace_expenses_saves_income_surplus_instead(self):
        plan = _flat_tax(self._pension_plan("replace_expenses", rate=0.01))
        s = {s.year: s for s in run_simulation(plan).yearly_snapshots}[2030]
        # 1% of ~1.6M is below the 30k pension, so the surplus is saved and nothing is drawn.
        assert sum(d.amount for d in s.cash_flow.drawdowns) == pytest.approx(0.0, abs=0.01)
        assert sum(c.amount for c in s.cash_flow.contributions if c.source != "reinvestment") > 1_000

    def test_withdrawal_plus_income_grosses_up_for_tax(self):
        pretax = {"ira": AccountInfo(balance=1_500_000, account_type="traditional_ira", cost_basis=0)}
        plan = replace(self._pension_plan("withdrawal_plus_income"), accounts=pretax,
                       drawdown_order=[DrawdownEntryData(rank=1, source_account_id="ira")])
        snaps = {s.year: s for s in run_simulation(plan).yearly_snapshots}
        s, prior = snaps[2029], snaps[2028]
        target = 0.04 * sum(prior.accounts.values())
        drawn = sum(d.amount for d in s.cash_flow.drawdowns)
        assert s.taxes > 0
        # Tax on the withdrawal is drawn on top of the target, not cut from spending.
        assert drawn > target
        assert s.strategy_spending > target


class TestStatelessRequest:
    def test_request_accepts_and_converts_the_setting(self):
        base = dict(plan_id=str(uuid.uuid4()), birth_year=1965, start_year=2026, life_expectancy=80,
                    milestones=[{"id": "retire", "name": "Retire", "trigger_type": "age", "trigger_value": 63}])
        data = request_to_engine_data(PlanDataRequest.model_validate(base))
        assert data.withdrawal_strategy is None
        assert "withdrawal_strategy" not in PlanDataRequest.model_validate(base).model_dump(exclude_unset=True)
        req = PlanDataRequest.model_validate({**base, "withdrawal_strategy": {
            "enabled": True, "method": "kitces_ratchet", "start_milestone_id": "retire", "ratchet_cooldown_years": 2}})
        spec = request_to_engine_data(req).withdrawal_strategy
        assert spec.method == "kitces_ratchet" and spec.ratchet_cooldown_years == 2
        with pytest.raises(ValueError):
            PlanDataRequest.model_validate({**base, "withdrawal_strategy": {"enabled": True, "start_milestone_id": "nope"}})


class TestSettingsValidation:
    def test_rejects_inconsistent_settings(self):
        with pytest.raises(ValueError):
            WithdrawalStrategySettings(enabled=True, method="fixed_amount")
        with pytest.raises(ValueError):
            WithdrawalStrategySettings(start_milestone_id="x", start_age=65)
        with pytest.raises(ValueError):
            WithdrawalStrategySettings(minimum={"amount": 60_000}, maximum={"amount": 50_000})
        with pytest.raises(ValueError):
            WithdrawalStrategySettings(maximum={"unit": "portfolio_percent", "amount": 4})
        with pytest.raises(ValueError):
            WithdrawalStrategySettings(method="magic")
        with pytest.raises(ValueError):
            WithdrawalStrategySettings(income_handling="portfolio_only")

"""Guardrail spending reacts to returns, and strategy comparisons share one sampling seed."""
from types import SimpleNamespace

import pytest

from coastmath.engine.types import PlanData
from coastmath.engine.withdrawal_comparison import compare_withdrawal_strategies
from coastmath.engine.withdrawal_strategy import (
    WithdrawalStrategySpec,
    WithdrawalStrategyState,
    strategy_spending,
)


def spending(state, *, year, portfolio, inflation, remaining=30, prior_return=0):
    return strategy_spending(WithdrawalStrategySpec('guyton_klinger'),state,year=year,age=65,
        portfolio=portfolio,inflation_factor=inflation,years_remaining=remaining,prior_year_return=prior_return)


@pytest.mark.parametrize('prior_return,expected',[(.02,41_200),(-.02,40_000)])
def test_freeze_uses_return_not_spending_depleted_balance(prior_return,expected):
    state=WithdrawalStrategyState()
    assert spending(state,year=2026,portfolio=1_000_000,inflation=1) == 40_000
    assert spending(state,year=2027,portfolio=980_000,inflation=1.03,prior_return=prior_return) == pytest.approx(expected)


def test_prosperity_raise_remains_available_in_last_fifteen_years():
    state=WithdrawalStrategyState()
    spending(state,year=2026,portfolio=1_000_000,inflation=1)
    assert spending(state,year=2027,portfolio=2_000_000,inflation=1,remaining=10,prior_return=.5) == pytest.approx(44_000)
    assert state.guardrail_raises == 1


def test_comparison_generates_one_shared_seed(monkeypatch):
    seen=[]
    def outcome(plan,spec,label,method,trials,seed,**kwargs):
        seen.append(seed)
        return SimpleNamespace(start_year=2026)
    monkeypatch.setattr('coastmath.engine.withdrawal_comparison._outcome',outcome)
    plan=PlanData('00000000-0000-0000-0000-000000000001',1980,'single',95,2026)
    compare_withdrawal_strategies(plan,methods=['constant_dollar','constant_percentage'],initial_rate=.04,
        start_milestone_id=None,start_age=None,mc_trials=10)
    assert len(seen)==3 and seen[0] is not None and len(set(seen))==1

"""A transport optimization must preserve every aggregate, including edge outcomes."""
import pickle

import pytest

from coastmath.engine.monte_carlo import _compact_trial, aggregate_results
from coastmath.engine.simulator import run_simulation
from coastmath.schemas.monte_carlo import SuccessTargets
from tests.engine_support import fixture_to_plan_data
from tests.fixtures import load_standard_plan


@pytest.mark.parametrize('failure_mode', ['liquid_assets', 'net_worth'])
@pytest.mark.parametrize('target', [None, SuccessTargets(terminal_net_worth_min=1e10, count_spending_cuts_as_shortfall=True)])
def test_compact_trials_preserve_exact_aggregation(failure_mode, target):
    plan = fixture_to_plan_data(load_standard_plan())
    full = [run_simulation(plan)]
    for account in plan.accounts.values():
        account.balance = 0
    plan.income_streams = []
    full.append(run_simulation(plan))
    compact = pickle.loads(pickle.dumps([_compact_trial(r) for r in full]))
    assert aggregate_results(compact, len(full[0].yearly_snapshots), failure_mode, target).model_dump() == aggregate_results(full, len(full[0].yearly_snapshots), failure_mode, target).model_dump()
    assert len(pickle.dumps(compact)) < len(pickle.dumps(full)) / 3

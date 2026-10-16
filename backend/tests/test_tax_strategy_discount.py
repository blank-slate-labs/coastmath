"""The strategy comparison ranks wealth with pre-tax balances after income tax."""

import copy

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_strategy import build_candidates, compare_strategies
from coastmath.engine.types import (
    AccountInfo,
    DrawdownEntryData,
    EstateSettingsData,
    ExpenseData,
    PlanData,
)


def _plan(estate=None) -> PlanData:
    return PlanData(
        plan_id="00000000-0000-0000-0000-0000000000b2", birth_year=1966, filing_status="single",
        life_expectancy=90, start_year=2026,
        accounts={"cash": AccountInfo(800_000, "checking"), "ira": AccountInfo(1_500_000, "traditional_ira"),
                  "roth": AccountInfo(50_000, "roth_ira")},
        expenses=[ExpenseData("living", "Living", 60_000)],
        drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "ira")],
        estate_settings=estate,
    )


@pytest.mark.parametrize("objective", ["net_legacy", "final_net_worth"])
@pytest.mark.parametrize("estate,rate", [(None, 0.24), (EstateSettingsData(heir_income_tax_rate=0.4), 0.4)])
def test_wealth_objectives_subtract_income_tax_on_pre_tax_balances(objective, estate, rate):
    p = _plan(estate)
    candidates = build_candidates(p, source_account_id="ira", target_account_id="roth", bracket_ceilings=[0.22],
                                  magi_cap=None, start_milestone_id=None, end_milestone_id=None)
    comparison = compare_strategies(p, candidates, objective)
    assert comparison.pre_tax_discount_rate == rate

    plain = run_simulation(copy.deepcopy(p))
    legacy = plain.metadata.net_legacy
    baseline = next(m for m in comparison.candidates if m.key == "baseline")
    # Reported figures stay the engine's; only the objective is discounted.
    assert baseline.net_legacy == pytest.approx(legacy.net_legacy)
    assert baseline.final_net_worth == pytest.approx(plain.yearly_snapshots[-1].net_worth)
    reported = baseline.net_legacy if objective == "net_legacy" else baseline.final_net_worth
    assert legacy.pretax_balance > 0
    assert baseline.objective_value == pytest.approx(reported - rate * legacy.pretax_balance)


def test_lifetime_tax_objective_is_not_discounted():
    p = _plan()
    candidates = build_candidates(p, source_account_id="ira", target_account_id="roth", bracket_ceilings=[0.22],
                                  magi_cap=None, start_milestone_id=None, end_milestone_id=None)
    comparison = compare_strategies(p, candidates, "lifetime_taxes")
    assert all(m.objective_value == m.lifetime_taxes for m in comparison.candidates)

"""Charitable carryovers follow statutory limits, not deduction elections.

A year that takes the standard deduction banks no carryover from small gifts,
still consumes an existing carryover, and carries forward only the excess over
the percentage-of-AGI limit. Plans use zero growth and inflation so each figure
can be checked by hand.
"""

import pytest

from coastmath.engine.simulator import _process_charitable_contributions, run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    CharityData,
    IncomeData,
    PlanData,
    SimState,
)


def gift_plan(amount=10_000):
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000002",
        birth_year=1980, life_expectancy=49, start_year=2026,
        filing_status="single",
        assumptions=AssumptionData(
            inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
            stock_dividend_yield=0, cash_yield_rate=0,
        ),
        accounts={"cash": AccountInfo(100_000, "checking")},
        income_streams=[IncomeData("pension", "Pension", 100_000,
                                   tax_category="qualified_pension", growth_rate=0)],
        charity_entities=[CharityData("gift", "Gift", "daf", amount)],
    )


def test_standard_deduction_does_not_bank_small_annual_daf_gifts():
    snapshots = run_simulation(gift_plan()).yearly_snapshots
    assert len(snapshots) == 3
    assert [s.deduction_used for s in snapshots] == ["standard"] * 3
    assert [s.federal_tax for s in snapshots] == pytest.approx(
        [snapshots[0].federal_tax] * 3,
    )


def test_existing_carryover_is_consumed_even_if_standard_deduction_wins():
    state = SimState(2025, {"cash": AccountInfo(100_000, "checking")},
                     daf_carryforward=[(2023, 2_000)])
    result = _process_charitable_contributions(state, gift_plan(5_000), 100_000, set())
    assert result.allowable_deduction == 7_000
    assert result.committed_carryforward == []
    assert result.preserved_carryforward == []
    assert state.daf_carryforward == [(2023, 2_000)]  # provisional helper is pure


def test_only_percentage_limit_excess_survives_the_deduction_choice():
    state = SimState(2025, {"cash": AccountInfo(100_000, "checking")},
                     daf_carryforward=[(2023, 2_000)])
    result = _process_charitable_contributions(state, gift_plan(10_000), 10_000, set())
    assert result.allowable_deduction == 6_000
    assert result.committed_carryforward == [(2023, 2_000), (2025, 4_000)]
    assert result.preserved_carryforward == result.committed_carryforward

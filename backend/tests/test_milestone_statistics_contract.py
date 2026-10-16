"""Milestone timing reports must retain unreached and unknown outcomes."""

from uuid import uuid4

from coastmath.engine.monte_carlo import aggregate_results, run_monte_carlo
from coastmath.engine.types import AccountInfo, AssumptionData, MilestoneData, PlanData
from coastmath.schemas.simulation import (
    MilestoneOutcome,
    SimMetadata,
    SimulationResult,
    YearSnapshot,
)


def trial(year, *, reported=True):
    outcomes = [MilestoneOutcome(id="fi", name="Financial independence", trigger_type="net_worth", year=year)] if reported else []
    return SimulationResult(metadata=SimMetadata(plan_id=uuid4(), start_year=2026,
        end_year=2035, milestone_outcomes=outcomes),
        yearly_snapshots=[YearSnapshot(year=2026, age=40, net_worth=100_000, accounts={"cash": 100_000})])


def test_aggregation_retains_unreached_trials_without_interpolating_calendar_years():
    result = aggregate_results([trial(2028), trial(2032), trial(2032), trial(None)], 1)
    summary = result.milestone_distributions[0]
    assert summary.reached_trials == 3
    assert summary.unreached_trials == 1
    assert summary.unreported_trials == 0
    assert summary.reach_rate == .75
    assert summary.year_counts == {2028: 1, 2032: 2}
    assert (summary.p10_year, summary.median_year, summary.p90_year) == (2028, 2032, 2032)
    assert result.success_rate == 1  # Reaching FI and avoiding depletion are separate.


def test_all_unreached_is_zero_reach_rate_and_unknown_timing():
    summary = aggregate_results([trial(None), trial(None)], 1).milestone_distributions[0]
    assert summary.reach_rate == 0
    assert summary.year_counts == {}
    assert summary.p10_year is summary.median_year is summary.p90_year is None


def test_missing_metadata_is_not_an_unreached_trial():
    summary = aggregate_results([trial(2030), trial(None, reported=False)], 1).milestone_distributions[0]
    assert (summary.reached_trials, summary.unreached_trials, summary.unreported_trials) == (1, 0, 1)
    assert summary.reach_rate is None
    assert summary.median_year == 2030


def test_real_trials_report_age_trigger_and_unreached_financial_trigger():
    plan = PlanData(plan_id=str(uuid4()), filing_status="single", birth_year=1980,
        birth_month=1, start_year=2026, life_expectancy=50,
        accounts={"cash": AccountInfo(100_000, "checking")},
        assumptions=AssumptionData(inflation_rate=0, cash_yield_rate=0),
        milestones=[MilestoneData("date", "Age 48", "age", trigger_value=48),
                    MilestoneData("fi", "FI", "net_worth", trigger_value=1_000_000)])
    result = run_monte_carlo(plan, n_trials=3, seed=19)
    by_id = {item.id: item for item in result.milestone_distributions}
    assert by_id["date"].year_counts == {2028: 3}
    assert by_id["date"].reach_rate == 1
    assert by_id["fi"].unreached_trials == 3

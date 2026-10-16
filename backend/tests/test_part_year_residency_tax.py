"""California wage attribution across a genuine midyear residency change.

The synthetic wages are earned and received in the modeled resident state
January through May, with no later or nonresident California-source income.
FTB: https://www.ftb.ca.gov/file/personal/residency-status/part-year-and-nonresident.html
The controls establish attribution; they do not certify exact return dollars.
"""

from dataclasses import replace

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    IncomeData,
    MilestoneData,
    PriorityData,
)
from tests.engine_support import wage_before_move_plan


def first_year(initial: str, destination: str):
    return run_simulation(wage_before_move_plan(initial, destination)).yearly_snapshots[0]


def test_moving_into_california_does_not_tax_earlier_texas_wages():
    moved = first_year("TX", "CA")
    stayed = first_year("TX", "TX")
    assert moved.gross_income == pytest.approx(50_000)
    assert moved.state_tax == pytest.approx(0)
    assert moved.net_worth == pytest.approx(stayed.net_worth)


def test_moving_to_nevada_does_not_erase_earlier_california_wages():
    moved = first_year("CA", "NV")
    stayed = first_year("CA", "CA")
    assert moved.gross_income == pytest.approx(50_000)
    assert stayed.state_tax > 0
    assert moved.state_tax == pytest.approx(stayed.state_tax)
    assert moved.net_worth == pytest.approx(stayed.net_worth)


@pytest.mark.parametrize("move_month", [1, 6, 12])
def test_continuing_wages_use_ca_income_share_of_annual_rate(move_month):
    plan = wage_before_move_plan("TX", "CA")
    plan.income_streams = [replace(plan.income_streams[0], end_milestone_id=None)]
    plan.milestones[1] = replace(
        plan.milestones[1], trigger_date=f"2026-{move_month:02d}-01",
    )
    moved = run_simulation(plan)
    control = run_simulation(replace(plan, state_code="CA", residency_periods=[]))
    actual = moved.yearly_snapshots[0]
    # For these wage-only, nonnegative bases, allocating the standard deduction
    # by AGI and using the annual effective rate gives this income-share identity.
    assert actual.gross_income == pytest.approx(120_000)
    assert actual.state_tax == pytest.approx(
        control.yearly_snapshots[0].state_tax * (13 - move_month) / 12,
    )
    if move_month != 1:
        assert any("2026:" in warning and "residence" in warning.lower()
                   for warning in moved.metadata.warnings)


def test_wages_beginning_after_departure_have_no_ca_attribution():
    plan = wage_before_move_plan("CA", "NV")
    plan.milestones.append(MilestoneData(
        id="new_job", name="New Nevada job", trigger_type="date",
        trigger_date="2026-09-01",
    ))
    plan.income_streams = [replace(
        plan.income_streams[0], start_milestone_id="new_job",
        end_milestone_id=None, start_month=9,
    )]
    actual = run_simulation(plan).yearly_snapshots[0]
    assert actual.gross_income == pytest.approx(40_000)
    assert actual.state_tax == pytest.approx(0)


def test_partial_first_year_intersects_residency_once():
    plan = wage_before_move_plan("CA", "NV")
    plan.first_year_fraction = 114 / 365
    plan.income_streams = [replace(plan.income_streams[0], end_milestone_id=None)]
    plan.milestones[1] = replace(plan.milestones[1], trigger_date="2026-11-01")
    # Keep this captured residency-allocation case focused on the post-start
    # period; the missing-history path is covered by the YTD default tests.
    plan.tax_settings = {**plan.tax_settings, "year_to_date": {"tax_year": 2026}}
    actual = run_simulation(plan).yearly_snapshots[0]
    control = run_simulation(replace(plan, residency_periods=[])).yearly_snapshots[0]
    ca_wages = 120_000 * (10 / 12 - (1 - 114 / 365))
    assert actual.gross_income == pytest.approx(120_000 * 114 / 365)
    assert actual.state_tax == pytest.approx(control.state_tax * ca_wages / actual.gross_income)


@pytest.mark.parametrize("initial,destination,ca_share", [
    ("TX", "CA", 24_000 / 74_000),
    ("CA", "NV", 50_000 / 74_000),
])
def test_unallocated_pension_retains_disclosed_legacy_component_only(
    initial, destination, ca_share,
):
    plan = wage_before_move_plan(initial, destination)
    plan.income_streams.append(IncomeData(
        id="pension", name="Annual pension", annual_amount=24_000,
        growth_rate=0, tax_category="qualified_pension",
    ))
    result = run_simulation(plan)
    actual = result.yearly_snapshots[0]
    control = run_simulation(replace(plan, state_code="CA", residency_periods=[]))
    assert actual.gross_income == pytest.approx(74_000)
    assert actual.state_tax == pytest.approx(control.yearly_snapshots[0].state_tax * ca_share)
    assert any("residual" in warning.lower() and "2026:" in warning
               for warning in result.metadata.warnings)
    assert actual.net_worth == pytest.approx(100_000 + actual.gross_income - actual.taxes)


def test_supplied_ytd_without_state_history_retains_explicit_fallback():
    plan = wage_before_move_plan("TX", "CA")
    plan.first_year_fraction = 7 / 12
    plan.income_streams = [replace(plan.income_streams[0], end_milestone_id=None)]
    plan.tax_settings = {
        **plan.tax_settings,
        "year_to_date": {
            "tax_year": 2026, "gross_income": 10_000,
            "w2_income_by_owner": {"self": 10_000},
        },
    }
    actual = run_simulation(plan)
    control = run_simulation(replace(plan, state_code="CA", residency_periods=[]))
    assert actual.yearly_snapshots[0].state_tax == pytest.approx(
        control.yearly_snapshots[0].state_tax,
    )
    assert any("year-to-date" in warning.lower() and "state attribution" in warning.lower()
               for warning in actual.metadata.warnings)


def test_dynamic_residency_trigger_warns_even_with_single_destination_span():
    plan = wage_before_move_plan("CA", "NV")
    plan.milestones[1] = replace(
        plan.milestones[1], trigger_type="net_worth", trigger_value=1,
        trigger_date=None,
    )
    result = run_simulation(plan)
    assert result.yearly_snapshots[0].state_tax == pytest.approx(0)
    assert any("Residency milestone move" in warning and "January" in warning
               for warning in result.metadata.warnings)


def test_partner_death_cutoff_limits_wages_before_residency_overlap():
    plan = wage_before_move_plan("CA", "NV")
    plan.filing_status = "married_filing_jointly"
    plan.spouse_birth_year = 1990
    plan.spouse_birth_month = 5
    plan.spouse_life_expectancy = 36
    plan.income_streams = [replace(plan.income_streams[0], owner="spouse")]
    actual = run_simulation(plan).yearly_snapshots[0]
    control = run_simulation(replace(plan, residency_periods=[])).yearly_snapshots[0]
    assert actual.gross_income == pytest.approx(40_000)
    assert actual.state_tax == pytest.approx(control.state_tax)
    assert actual.net_worth == pytest.approx(control.net_worth)


def test_flat_mode_preserves_explicit_blended_tax_without_residency_warnings():
    plan = wage_before_move_plan("CA", "NV")
    plan.tax_settings = {"mode": "flat", "ordinary_income_tax_rate": 0.2}
    actual = run_simulation(plan)
    control = run_simulation(replace(plan, state_code="NV", residency_periods=[]))
    assert actual.yearly_snapshots == control.yearly_snapshots
    assert actual.metadata.warnings == control.metadata.warnings
    assert not any("residency" in warning.lower() or "residence" in warning.lower()
                   for warning in actual.metadata.warnings)


def test_waterfall_deduction_recomputes_tax_and_final_fallback_diagnostics():
    plan = wage_before_move_plan("TX", "CA")
    plan.income_streams = [replace(plan.income_streams[0], end_milestone_id=None)]
    before_contribution = run_simulation(plan)
    assert not any("wage allocation unsupported" in warning
                   for warning in before_contribution.metadata.warnings)
    plan.accounts["401k"] = AccountInfo(balance=0, account_type="traditional_401k")
    plan.priorities = [
        PriorityData(priority_rank=1, target_account_id="401k", max_annual_amount=20_000),
        PriorityData(priority_rank=2, target_account_id="cash"),
    ]
    actual = run_simulation(plan)
    control = run_simulation(replace(plan, state_code="CA", residency_periods=[]))
    final = actual.yearly_snapshots[0]
    assert final.accounts["401k"] == pytest.approx(20_000)
    assert final.state_tax == pytest.approx(control.yearly_snapshots[0].state_tax)
    assert final.net_worth == pytest.approx(100_000 + final.gross_income - final.taxes)
    warnings = [warning for warning in actual.metadata.warnings if warning.startswith("2026:")]
    assert any("deductions $20,000.00" in warning and "unsupported" in warning for warning in warnings)
    assert not any("continuous rates" in warning for warning in warnings)

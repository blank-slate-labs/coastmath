"""Calendar residency boundaries, independently of tax amounts or sourcing."""

from copy import deepcopy

import pytest

from coastmath.engine.milestones import evaluate_milestones
from coastmath.engine.residency import resolve_residency_spans, resolve_state_for_year
from coastmath.engine.types import (
    MilestoneData,
    PlanData,
    ResidencyPeriodData,
    SimState,
)


def _plan(**overrides):
    values = dict(
        plan_id="residency-boundaries", birth_year=1980, birth_month=1,
        filing_status="single", life_expectancy=90, start_year=2026,
        state_code="FL",
    )
    values.update(overrides)
    return PlanData(**values)


def _move_plan(origin="CA", destination="NV", **overrides):
    values = dict(
        milestones=[MilestoneData("move", "Move", "date", trigger_date="2029-06-29")],
        residency_periods=[
            ResidencyPeriodData(origin, end_milestone_id="move", rank=0),
            ResidencyPeriodData(destination, start_milestone_id="move", rank=1),
        ],
    )
    values.update(overrides)
    return _plan(**values)


def _assert_spans(actual, expected):
    """Check exact boundaries and a partition of all twelve calendar months."""
    assert [(s.state_code, s.start_month, s.end_month) for s in actual] == expected
    assert actual[0].start_month == 1
    assert actual[-1].end_month == 13
    assert all(1 <= s.start_month < s.end_month <= 13 for s in actual)
    assert [s.end_month for s in actual[:-1]] == [s.start_month for s in actual[1:]]
    assert [month for s in actual for month in range(s.start_month, s.end_month)] == list(range(1, 13))
    assert sum(s.year_fraction for s in actual) == pytest.approx(1)
    for span in actual:
        assert span.start_fraction == pytest.approx((span.start_month - 1) / 12)
        assert span.end_fraction == pytest.approx((span.end_month - 1) / 12)
        assert span.year_fraction == pytest.approx(span.end_fraction - span.start_fraction)


@pytest.mark.parametrize("origin,destination", [("CA", "NV"), ("NV", "CA")])
def test_opposite_june_moves_keep_january_through_may_in_origin(origin, destination):
    plan = _move_plan(origin, destination)
    _assert_spans(
        resolve_residency_spans(2029, {"move"}, plan, {"move": 2029}),
        [(origin, 1, 6), (destination, 6, 13)],
    )
    # The compatibility API deliberately retains its original annual behavior.
    assert resolve_state_for_year(2029, {"move"}, plan) == destination


@pytest.mark.parametrize("month", [1, 2, 6, 12])
def test_start_month_inclusive_and_end_month_exclusive(month):
    plan = _move_plan(milestones=[MilestoneData(
        "move", "Move", "date", trigger_date=f"2029-{month:02d}-01",
    )])
    expected = ([('CA', 1, month)] if month > 1 else []) + [('NV', month, 13)]
    _assert_spans(resolve_residency_spans(2029, {"move"}, plan), expected)


@pytest.mark.parametrize("fallback", ["FL", None])
def test_empty_periods_cover_full_year_including_unknown_fallback(fallback):
    _assert_spans(resolve_residency_spans(2029, set(), _plan(state_code=fallback)), [(fallback, 1, 13)])


def test_no_periods_skip_milestone_resolution_and_monthly_sorting(monkeypatch):
    def unexpected_work(*args, **kwargs):
        pytest.fail("Plans without residency periods must use the constant-time fallback")

    monkeypatch.setattr("coastmath.engine.residency.resolve_deterministic_milestones", unexpected_work)
    monkeypatch.setattr("coastmath.engine.residency.resolve_state_for_year", unexpected_work)
    _assert_spans(resolve_residency_spans(2029, {"move"}, _plan()), [("FL", 1, 13)])


@pytest.mark.parametrize("year,state", [(2028, "CA"), (2029, "NV"), (2030, "FL")])
def test_year_bounds_start_january_and_end_after_december(year, state):
    plan = _plan(residency_periods=[
        ResidencyPeriodData("CA", end_year=2028),
        ResidencyPeriodData("NV", start_year=2029, end_year=2029, rank=1),
    ])
    _assert_spans(resolve_residency_spans(year, set(), plan), [(state, 1, 13)])


def test_multiple_transitions_and_an_uncovered_gap_use_fallback():
    plan = _plan(milestones=[
        MilestoneData("june", "June", "date", trigger_date="2029-06-01"),
        MilestoneData("march", "March", "date", trigger_date="2029-03-01"),
        MilestoneData("october", "October", "date", trigger_date="2029-10-01"),
    ], residency_periods=[
        ResidencyPeriodData("WA", start_milestone_id="october", rank=2),
        ResidencyPeriodData("CA", end_milestone_id="march", rank=0),
        ResidencyPeriodData("NV", start_milestone_id="march", end_milestone_id="june", rank=1),
    ])
    _assert_spans(resolve_residency_spans(2029, {"march", "june", "october"}, plan), [
        ("CA", 1, 3), ("NV", 3, 6), ("FL", 6, 10), ("WA", 10, 13),
    ])


def test_rank_applies_separately_in_each_month():
    plan = _plan(milestones=[
        MilestoneData("march", "March", "date", trigger_date="2029-03-01"),
        MilestoneData("september", "September", "date", trigger_date="2029-09-01"),
        MilestoneData("june", "June", "date", trigger_date="2029-06-01"),
    ], residency_periods=[
        ResidencyPeriodData("TX", start_milestone_id="june", rank=2),
        ResidencyPeriodData("CA", rank=1),
        ResidencyPeriodData("NV", start_milestone_id="march", end_milestone_id="september", rank=0),
    ])
    _assert_spans(resolve_residency_spans(2029, {"march", "june", "september"}, plan), [
        ("CA", 1, 3), ("NV", 3, 9), ("CA", 9, 13),
    ])


def test_equal_rank_retains_input_order():
    plan = _plan(residency_periods=[ResidencyPeriodData("WA", rank=2), ResidencyPeriodData("CA", rank=2)])
    _assert_spans(resolve_residency_spans(2029, set(), plan), [("WA", 1, 13)])


def test_adjacent_same_state_periods_and_fallback_are_merged():
    plan = _move_plan("CA", "CA", state_code="CA")
    _assert_spans(resolve_residency_spans(2029, {"move"}, plan), [("CA", 1, 13)])


def test_same_start_and_end_milestone_never_opens_a_period():
    plan = _move_plan(residency_periods=[
        ResidencyPeriodData("CA", start_milestone_id="move", end_milestone_id="move"),
    ])
    _assert_spans(resolve_residency_spans(2029, {"move"}, plan), [("FL", 1, 13)])


def test_end_year_still_closes_a_period_with_an_untriggered_end_milestone():
    plan = _move_plan(residency_periods=[
        ResidencyPeriodData("CA", end_year=2028, end_milestone_id="move"),
    ])
    _assert_spans(resolve_residency_spans(2029, set(), plan), [("FL", 1, 13)])


@pytest.mark.parametrize("history", [None, {"move": 2029}])
def test_past_dated_trigger_does_not_recur_in_june(history):
    _assert_spans(resolve_residency_spans(2030, {"move"}, _move_plan(), history), [("NV", 1, 13)])


def test_untriggered_authored_date_does_not_fire_inside_resolver():
    _assert_spans(resolve_residency_spans(2030, set(), _move_plan(), {"move": 2029}), [("CA", 1, 13)])


@pytest.mark.parametrize("history", [None, {"move": 2029}])
def test_future_trigger_is_not_applied_to_earlier_calendar_year(history):
    _assert_spans(resolve_residency_spans(2028, {"move"}, _move_plan(), history), [("CA", 1, 13)])


@pytest.mark.parametrize("birth_month,age,year,month", [(6, 49, 2029, 6), (10, 48.5, 2029, 4), (None, 49, 2029, 1)])
def test_age_milestones_use_birth_month_and_fractional_age_year_rollover(birth_month, age, year, month):
    plan = _move_plan(birth_month=birth_month, milestones=[MilestoneData(
        "move", "Move", "age", trigger_value=age,
    )])
    expected = ([('CA', 1, month)] if month > 1 else []) + [('NV', month, 13)]
    _assert_spans(resolve_residency_spans(year, {"move"}, plan), expected)
    _assert_spans(resolve_residency_spans(year + 1, {"move"}, plan), [("NV", 1, 13)])


def test_relative_chain_inherits_deterministic_month_independent_of_list_order():
    plan = _move_plan(birth_month=6, milestones=[
        MilestoneData("move", "Move", "relative", relative_to_id="before", offset_years=1),
        MilestoneData("before", "Before", "relative", relative_to_id="birthday", offset_years=-2),
        MilestoneData("birthday", "Birthday", "age", trigger_value=50),
    ])
    _assert_spans(resolve_residency_spans(2029, {"move"}, plan), [("CA", 1, 6), ("NV", 6, 13)])


@pytest.mark.parametrize("kind", ["net_worth", "expense_multiple", "relative", "missing"])
def test_undated_trigger_uses_existing_january_convention(kind):
    milestones = [] if kind == "missing" else [MilestoneData("move", "Move", kind)]
    plan = _move_plan(milestones=milestones)
    _assert_spans(resolve_residency_spans(2029, {"move"}, plan, {"move": 2029}), [("NV", 1, 13)])
    _assert_spans(resolve_residency_spans(2030, {"move"}, plan, {"move": 2029}), [("NV", 1, 13)])


def test_real_milestone_evaluation_records_past_date_and_keeps_current_month():
    plan = _plan(milestones=[
        MilestoneData("old", "Old move", "date", trigger_date="2028-10-01"),
        MilestoneData("current", "Current move", "date", trigger_date="2029-06-01"),
    ], residency_periods=[
        ResidencyPeriodData("CA", end_milestone_id="old", rank=0),
        ResidencyPeriodData("NV", start_milestone_id="old", end_milestone_id="current", rank=1),
        ResidencyPeriodData("WA", start_milestone_id="current", rank=2),
    ])
    state = SimState(year=2029)
    assert set(evaluate_milestones(state, plan.milestones, 2029, plan.birth_year)) == {"old", "current"}
    assert state.triggered_milestone_years == {"old": 2028, "current": 2029}
    _assert_spans(resolve_residency_spans(2029, state.triggered_milestones, plan, state.triggered_milestone_years), [
        ("NV", 1, 6), ("WA", 6, 13),
    ])
    assert evaluate_milestones(state, plan.milestones, 2030, plan.birth_year) == []
    _assert_spans(resolve_residency_spans(2030, state.triggered_milestones, plan, state.triggered_milestone_years), [("WA", 1, 13)])


def test_partial_first_year_remains_full_calendar_until_caller_intersection():
    plan = _move_plan(first_year_fraction=0.25)
    spans = resolve_residency_spans(2029, {"move"}, plan)
    _assert_spans(spans, [("CA", 1, 6), ("NV", 6, 13)])
    active_from = 1 - plan.first_year_fraction
    overlaps = [max(0, s.end_fraction - max(active_from, s.start_fraction)) for s in spans]
    assert overlaps == pytest.approx([0, 0.25])
    assert sum(overlaps) == pytest.approx(plan.first_year_fraction)


def test_resolution_does_not_mutate_inputs():
    plan = _move_plan()
    triggered, history = {"move"}, {"move": 2029}
    before = deepcopy((plan, triggered, history))
    resolve_residency_spans(2029, triggered, plan, history)
    assert (plan, triggered, history) == before

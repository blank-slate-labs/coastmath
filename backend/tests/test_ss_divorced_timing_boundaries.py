"""Divorced-spouse benefit timing set by milestones, survivor claim ages and remarriage."""

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import MilestoneData
from tests.engine_support import source
from tests.ss_divorced_support import DIVORCED, SURVIVOR, ex, pia_ss, plan


def test_a_dated_milestone_can_time_the_filing_status_change():
    wedding = MilestoneData(id="wed", name="Wedding", trigger_type="date", trigger_date="2029-05-01")
    changes = [{"milestone_id": "wed", "filing_status": "married_filing_jointly"}]
    result = run_simulation(plan(
        milestones=[wedding], filing_status_changes=changes, income_streams=[pia_ss(ex_spouse=ex())],
    ))
    assert source(result, 2028, DIVORCED) == pytest.approx(6_000)
    assert source(result, 2029, DIVORCED) == 0


def test_a_status_change_naming_an_unknown_milestone_is_rejected():
    changes = [{"milestone_id": "wed", "filing_status": "married_filing_jointly"}]
    with pytest.raises(ValueError, match="filing status changes at a fixed year or date"):
        run_simulation(plan(filing_status_changes=changes, income_streams=[pia_ss(ex_spouse=ex())]))


def test_survivor_benefit_waits_for_its_own_claim_age():
    # Own benefit at 62 (2028); the survivor benefit is claimed at 65 (2031).
    record = ex(birth_year=1964, claim_age=None, death_year=2025, survivor_claim_age=65)
    result = run_simulation(plan(birth_year=1966, income_streams=[pia_ss(claim=62, ex_spouse=record)]))
    for year in (2028, 2029, 2030):
        assert source(result, year, SURVIVOR) == 0
        assert source(result, year, DIVORCED) == 0
    assert source(result, 2031, SURVIVOR) > 0


def test_remarriage_after_60_during_the_projection_keeps_the_survivor_benefit():
    record = ex(birth_year=1964, claim_age=None, death_year=2025, survivor_claim_age=60)
    single = run_simulation(plan(birth_year=1966, income_streams=[pia_ss(ex_spouse=record)]))
    # Remarries at 64 in 2030: after 60, so the survivor benefit continues.
    late = run_simulation(plan(
        birth_year=1966, income_streams=[pia_ss(ex_spouse=record)],
        filing_status_changes=[{"year": 2030, "filing_status": "married_filing_jointly"}],
    ))
    assert source(single, 2031, SURVIVOR) > 0
    for year in (2029, 2030, 2031):
        assert source(late, year, SURVIVOR) == pytest.approx(source(single, year, SURVIVOR))

"""State insurance applies to wages during the explicitly covered window."""
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.schemas.plan import TaxSettings
from coastmath.engine.simulator import run_simulation
from tests.engine_support import wage_before_move_plan


def covered_plan(state='CA', month=6, continuing=False):
    plan = wage_before_move_plan('TX', state)
    if continuing:
        plan.income_streams = [replace(plan.income_streams[0], end_milestone_id=None)]
    plan.tax_settings = {**plan.tax_settings, 'state_payroll_coverage': [dict(
        owner='self', state_code=state, start_year=2026, start_month=month,
        ca_sdi=state == 'CA', wa_paid_leave=state == 'WA', wa_cares=state == 'WA')]}
    return plan


def premiums(row):
    return {x.name: x.amount for x in row.cash_flow.expenses if x.category == 'state_payroll_tax'}


def test_month_survives_wire_validation_and_rejects_out_of_range():
    payload = covered_plan().tax_settings
    assert TaxSettings.model_validate(payload).model_dump()['state_payroll_coverage'][0]['start_month'] == 6
    for invalid in (0, 13):
        payload['state_payroll_coverage'][0]['start_month'] = invalid
        with pytest.raises(ValidationError):
            TaxSettings.model_validate(payload)


@pytest.mark.parametrize('state', ['CA', 'WA'])
def test_pre_move_wages_are_not_covered_or_reassigned_to_california(state):
    row = run_simulation(covered_plan(state)).yearly_snapshots[0]
    assert sum(premiums(row).values()) == 0
    assert row.state_tax == 0


@pytest.mark.parametrize('month', [1, 6, 12])
def test_continuing_wages_pay_sdi_only_after_coverage_begins(month):
    plan = covered_plan(month=month, continuing=True)
    result = run_simulation(plan)
    row = result.yearly_snapshots[0]
    assert premiums(row)['California SDI'] == pytest.approx(120000 * (13-month)/12 * .013)
    if month >= 6:
        control = run_simulation(replace(plan, tax_settings={'ca_exemption_eligible_owners': []})).yearly_snapshots[0]
        assert row.state_tax == pytest.approx(control.state_tax)
        assert not any('nonresident wage sourcing' in w for w in result.metadata.warnings)
    else:
        assert any('nonresident wage sourcing' in w for w in result.metadata.warnings)


def test_wa_premiums_use_covered_wages_with_annual_cap():
    plan = covered_plan('WA', continuing=True)
    plan.income_streams[0].annual_amount = 600000
    row = run_simulation(plan).yearly_snapshots[0]
    amounts = premiums(row)
    assert amounts['Washington Paid Leave'] == pytest.approx(184500 * .0113 * .7143)
    assert amounts['Washington Cares'] == pytest.approx(350000 * .0058)


def test_partial_capture_intersects_coverage_and_wages():
    plan = covered_plan(continuing=True)
    plan.first_year_fraction = .25
    row = run_simulation(plan).yearly_snapshots[0]
    assert premiums(row)['California SDI'] == pytest.approx(30000 * .013)


def test_start_month_does_not_repeat_in_subsequent_years():
    plan = covered_plan(continuing=True)
    plan.life_expectancy = 38
    row = run_simulation(plan).yearly_snapshots[1]
    assert premiums(row)['California SDI'] == pytest.approx(120000 * .013)


@pytest.mark.parametrize('explicit_history', [None, 0, 1000])
def test_opening_wages_before_coverage_are_excluded_unless_explicitly_reported(explicit_history):
    plan = covered_plan(continuing=True)
    plan.first_year_fraction = .75  # Starts April; work coverage starts June.
    plan.tax_settings['year_to_date'] = {'tax_year': 2026, 'gross_income': 30000, 'w2_income_by_owner': {'self': 30000}}
    if explicit_history is not None:
        plan.tax_settings['state_payroll_wages_year_to_date'] = {'self': explicit_history}
    row = run_simulation(plan).yearly_snapshots[0]
    assert premiums(row)['California SDI'] == pytest.approx((70000+(explicit_history or 0))*.013)

"""Mandatory state premiums: federal SALT, no wage exclusion, no double cash."""

from copy import deepcopy

import pytest

from coastmath.engine.simulator import run_simulation
from tests.corrected_fixture_support import (
    corrected_fixture,
    engine_request,
    persist_fixture,
)
from tests.engine_support import premium_tax_example, reconcile


@pytest.mark.parametrize(
    "code,premium", [("CA", 1300), ("WA", 100000 * 0.0113 * 0.7143)]
)
def test_mandatory_premium_reduces_federal_tax_for_itemizer_only(code, premium):
    p = premium_tax_example(code)
    without = deepcopy(p)
    without.tax_settings["state_payroll_coverage"] = []
    r = run_simulation(p)
    s = r.yearly_snapshots[0]
    base = run_simulation(without).yearly_snapshots[0]
    assert base.federal_tax - s.federal_tax == pytest.approx(premium * 0.22, abs=0.01)
    assert s.state_tax == base.state_tax
    assert s.fica_tax == base.fica_tax
    assert s.expenses - base.expenses == pytest.approx(premium)
    assert s.net_worth - base.net_worth == pytest.approx(-premium * 0.78, abs=0.01)
    reconcile(r)


def test_opening_premium_payments_not_deducted_twice():
    a = run_simulation(premium_tax_example(paid=650)).yearly_snapshots[0]
    b = run_simulation(premium_tax_example(paid=0)).yearly_snapshots[0]
    assert a.federal_tax == b.federal_tax
    assert a.expenses == 650 and b.expenses == 1300


def test_standard_deduction_and_salt_cap_block_premium_benefit():
    for interest, property_tax in [(0, 0), (20000, 50000)]:
        p = premium_tax_example(interest=interest)
        p.tax_settings["year_to_date"]["property_tax"] = property_tax
        before = deepcopy(p)
        before.tax_settings["state_payroll_coverage"] = []
        assert (
            run_simulation(p).yearly_snapshots[0].federal_tax
            == run_simulation(before).yearly_snapshots[0].federal_tax
        )


def test_wa_cares_is_not_automatically_treated_as_paid_leave_salt():
    p = premium_tax_example("WA")
    p.tax_settings["state_payroll_coverage"][0].update(
        wa_paid_leave=False, wa_cares=True
    )
    before = deepcopy(p)
    before.tax_settings["state_payroll_coverage"] = []
    assert (
        run_simulation(p).yearly_snapshots[0].federal_tax
        == run_simulation(before).yearly_snapshots[0].federal_tax
    )


def test_ytd_state_income_payments_are_part_of_annual_salt_not_added_again():
    p = premium_tax_example()
    base = run_simulation(p).yearly_snapshots[0]
    p.tax_settings["year_to_date"]["state_tax_paid"] = 2000
    p.tax_settings["year_to_date"]["tax_paid"] = 2000
    after = run_simulation(p).yearly_snapshots[0]
    assert after.federal_tax == base.federal_tax
    assert after.net_worth - base.net_worth == pytest.approx(2000)


@pytest.mark.anyio
@pytest.mark.parametrize("code", ["CA", "WA"])
async def test_itemizer_premiums_match_both_http_paths(
    code, db_session, test_user, client
):
    raw = corrected_fixture("fire_persona")
    raw["life_expectancy"] = 50
    raw["state_code"] = code
    raw["residency_periods"] = []
    raw["tax_settings"] = premium_tax_example(code).tax_settings
    p = persist_fixture(raw, db_session, test_user)
    a = await client.post(f"/api/plans/{p.plan_id}/simulate")
    b = await client.post(
        "/api/simulate/stateless", json=engine_request(p).model_dump(mode="json")
    )
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    reconcile(run_simulation(p))

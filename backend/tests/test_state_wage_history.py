"""Reported state wages replace only earlier FICA wages; never new cash."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas.plan import TaxSettings
from coastmath.engine.simulator import run_simulation
from coastmath.schemas.plan_data_request import TaxSettingsRequest
from tests.corrected_fixture_support import (
    corrected_fixture,
    engine_request,
    persist_fixture,
)
from tests.engine_support import premium_tax_example, reconcile


def test_prior_ca_hsa_wage_difference_not_new_income_or_double_deposit():
    p = premium_tax_example(interest=0)
    p.life_expectancy = 42
    p.tax_settings["year_to_date"].update(w2_income_by_owner={"self": 48500})
    base = run_simulation(p)
    p.tax_settings["state_payroll_wages_year_to_date"] = {"self": 50500}
    result = run_simulation(p)
    before, after = base.yearly_snapshots[0], result.yearly_snapshots[0]
    # Earlier employee $1,500 salary reduction and employer $500 are
    # California wages. $2,000 * 1.3% = $26 extra SDI, no federal change.
    assert after.expenses - before.expenses == pytest.approx(26)
    assert after.net_worth - before.net_worth == pytest.approx(-26)
    assert after.fica_tax == before.fica_tax
    assert after.gross_income == before.gross_income
    assert result.yearly_snapshots[1].expenses == base.yearly_snapshots[1].expenses
    reconcile(result)
    zero = deepcopy(p)
    zero.tax_settings["state_payroll_wages_year_to_date"] = {"self": 0}
    assert run_simulation(zero).yearly_snapshots[0].expenses == pytest.approx(1300)


@pytest.mark.parametrize("model", [TaxSettings, TaxSettingsRequest])
def test_invalid_wage_history_and_explicit_zero(model):
    with pytest.raises(ValidationError):
        model(state_payroll_wages_year_to_date={"self": -1})
    with pytest.raises(ValidationError):
        model(state_payroll_wages_year_to_date={"joint": 100})
    assert model(state_payroll_wages_year_to_date={"self": 0}).state_payroll_wages_year_to_date == {"self": 0}


@pytest.mark.anyio
async def test_state_wage_history_persisted_and_stateless(db_session, test_user, client):
    raw = corrected_fixture("fire_persona")
    raw["life_expectancy"] = 50
    raw["tax_settings"] = premium_tax_example().tax_settings
    raw["tax_settings"]["state_payroll_wages_year_to_date"] = {"self": 50500, "spouse": 0}
    p = persist_fixture(raw, db_session, test_user)
    saved = (await client.get(f"/api/plans/{p.plan_id}")).json()["tax_settings"]
    assert saved["state_payroll_wages_year_to_date"] == {"self": 50500, "spouse": 0}
    a = await client.post(f"/api/plans/{p.plan_id}/simulate")
    b = await client.post("/api/simulate/stateless", json=engine_request(p).model_dump(mode="json"))
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()

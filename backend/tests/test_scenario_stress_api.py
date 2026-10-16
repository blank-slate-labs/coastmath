"""POST /plans/{id}/scenario-stress: result shape, validation envelope, usage count."""

from datetime import date

import pytest

pytestmark = pytest.mark.anyio


async def _plan_with_salary(client):
    plan = (await client.post("/api/plans", json={"name": "Plan", "birth_year": 1980})).json()
    response = await client.post(f"/api/plans/{plan['id']}/incomes", json={"name": "Salary", "annual_amount": 90000})
    assert response.status_code == 201, response.text
    return f"/api/plans/{plan['id']}"


async def test_job_loss_returns_stress_result_shape_and_counts_use(client, db_session, test_user, recorded_usage):
    base = await _plan_with_salary(client)
    year = date.today().year + 1
    response = await client.post(f"{base}/scenario-stress", json={"preset": "job_loss", "start_year": year})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"] == {
        "preset": "job_loss", "start_year": year, "person": "self", "months_without_pay": 6,
        "resume_percent": 80.0, "stock_drop_percent": None, "child_annual_cost": None, "child_cost_years": None,
        "downturn_years": None, "recovery_years": None, "bond_return_percent": None,
        "inflation_percent": None, "downturn_path": None,
    }
    assert body["simulation_result"]["yearly_snapshots"]
    assert recorded_usage.count("scenario_stress_test") == 1


async def test_new_child_and_crash_presets_run(client):
    base = await _plan_with_salary(client)
    year = date.today().year
    for body in ({"preset": "new_child", "start_year": year, "child_annual_cost": 20000},
                 {"preset": "market_crash", "start_year": year + 2, "stock_drop_percent": 50},
                 {"preset": "tech_bust", "start_year": year + 1}):
        response = await client.post(f"{base}/scenario-stress", json=body)
        assert response.status_code == 200, response.text
        assert response.json()["metadata"]["preset"] == body["preset"]


@pytest.mark.parametrize(("body", "field"), [
    ({"preset": "market_crash", "start_year": 2020}, "start_year"),
    ({"preset": "job_loss", "start_year": None, "person": "spouse"}, "preset"),
])
async def test_invalid_inputs_use_the_error_envelope(client, body, field):
    base = await _plan_with_salary(client)
    if body["start_year"] is None:
        body = {**body, "start_year": date.today().year + 1}
    response = await client.post(f"{base}/scenario-stress", json=body)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == field


async def test_unknown_preset_and_out_of_range_params_are_rejected(client):
    base = await _plan_with_salary(client)
    year = date.today().year + 1
    for body in ({"preset": "asteroid", "start_year": year},
                 {"preset": "market_crash", "start_year": year, "stock_drop_percent": 100},
                 {"preset": "job_loss", "start_year": year, "months_without_pay": 0}):
        response = await client.post(f"{base}/scenario-stress", json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_downturn_returns_parameters_and_path(client):
    base = await _plan_with_salary(client)
    year = date.today().year + 1
    response = await client.post(f"{base}/scenario-stress", json={
        "preset": "downturn", "start_year": year, "stock_drop_percent": 25, "downturn_years": 2,
        "recovery_years": 1, "bond_return_percent": -3, "inflation_percent": 8,
    })
    assert response.status_code == 200, response.text
    meta = response.json()["metadata"]
    assert {k: meta[k] for k in ("preset", "stock_drop_percent", "downturn_years", "recovery_years",
                                 "bond_return_percent", "inflation_percent")} == {
        "preset": "downturn", "stock_drop_percent": 25.0, "downturn_years": 2, "recovery_years": 1,
        "bond_return_percent": -3.0, "inflation_percent": 8.0,
    }
    path = meta["downturn_path"]
    assert [(e["year"], e["phase"]) for e in path] == [
        (year, "downturn"), (year + 1, "downturn"), (year + 2, "recovery")]
    assert path[0]["bond_return"] == pytest.approx(-0.03) and path[0]["inflation"] == pytest.approx(0.08)
    assert (1 + path[0]["stock_return"]) * (1 + path[1]["stock_return"]) == pytest.approx(0.75)
    assert path[2]["stock_return"] == pytest.approx(1 / 0.75 - 1)


async def test_downturn_defaults_and_bounds(client):
    base = await _plan_with_salary(client)
    year = date.today().year + 1
    response = await client.post(f"{base}/scenario-stress", json={"preset": "downturn", "start_year": year})
    assert response.status_code == 200, response.text
    meta = response.json()["metadata"]
    assert (meta["downturn_years"], meta["recovery_years"], meta["stock_drop_percent"]) == (3, 0, 35.0)
    assert meta["bond_return_percent"] is None and meta["inflation_percent"] is None
    for extra in ({"downturn_years": 0}, {"downturn_years": 11}, {"recovery_years": -1},
                  {"recovery_years": 11}, {"bond_return_percent": -51}, {"bond_return_percent": 51},
                  {"inflation_percent": -11}, {"inflation_percent": 31}, {"stock_drop_percent": 0.5},
                  {"stock_drop_percent": 91}, {"shape": "lost_decade"}):
        response = await client.post(f"{base}/scenario-stress",
                                     json={"preset": "downturn", "start_year": year, **extra})
        assert response.status_code == 422, extra
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_dependent_birth_years_round_trip_through_tax_settings(client):
    base = await _plan_with_salary(client)
    response = await client.put(base, json={"tax_settings": {"dependent_birth_years": [2019, 2022]}})
    assert response.status_code == 200, response.text
    assert response.json()["tax_settings"]["dependent_birth_years"] == [2019, 2022]
    assert (await client.get(base)).json()["tax_settings"]["dependent_birth_years"] == [2019, 2022]

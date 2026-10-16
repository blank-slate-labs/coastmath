"""The opening state-taxed contribution basis through the account, plan and simulation APIs."""
import pytest

from tests.scenario_support import post

IRA = {"name": "IRA", "account_type": "traditional_ira", "balance": 200_000}


async def _pa_plan(client, **extra):
    plan = await post(client, "/plans", {"name": "PA", "birth_year": 1976, "plan_type": "NOW",
                                         "state_code": "PA", **extra})
    await post(client, f"/plans/{plan['id']}/expenses", {"name": "Living", "annual_amount": 20_000})
    return plan


@pytest.mark.anyio
async def test_basis_round_trips_and_only_traditional_accounts_keep_it(client):
    plan = await _pa_plan(client)
    account = await post(client, f"/plans/{plan['id']}/accounts", {**IRA, "state_taxed_basis": 15_000})
    assert account["state_taxed_basis"] == 15_000
    path = f"/api/plans/{plan['id']}/accounts/{account['id']}"
    # A partial update keeps the saved basis.
    updated = (await client.put(path, json={"balance": 210_000})).json()
    assert updated["state_taxed_basis"] == 15_000
    listed = (await client.get(f"/api/plans/{plan['id']}/accounts")).json()
    assert listed[0]["state_taxed_basis"] == 15_000
    # Roth and taxable accounts never carry it.
    roth = await post(client, f"/plans/{plan['id']}/accounts",
                      {**IRA, "name": "Roth", "account_type": "roth_ira", "state_taxed_basis": 5_000})
    assert roth["state_taxed_basis"] is None
    moved = (await client.put(path, json={"account_type": "taxable_brokerage", "cost_basis": 1})).json()
    assert moved["state_taxed_basis"] is None
    rejected = await client.post(f"/api/plans/{plan['id']}/accounts", json={**IRA, "state_taxed_basis": -1})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.anyio
async def test_client_plan_duplicate_copies_the_basis(client):
    owner = (await client.post("/api/clients/personal")).json()
    plan = await _pa_plan(client, client_id=owner["id"])
    await post(client, f"/plans/{plan['id']}/accounts", {**IRA, "state_taxed_basis": 15_000})
    copied = await post(client, f"/plans/{plan['id']}/duplicate", {})
    copied_account = (await client.get(f"/api/plans/{copied['id']}/accounts")).json()[0]
    assert copied_account["state_taxed_basis"] == 15_000


@pytest.mark.anyio
async def test_persisted_and_stateless_simulations_recover_the_basis(client):
    plan = await _pa_plan(client)
    account = await post(client, f"/plans/{plan['id']}/accounts", {**IRA, "state_taxed_basis": 15_000})
    persisted = await client.post(f"/api/plans/{plan['id']}/simulate")
    assert persisted.status_code == 200, persisted.text
    with_basis = persisted.json()["yearly_snapshots"][0]
    await client.put(f"/api/plans/{plan['id']}/accounts/{account['id']}", json={"state_taxed_basis": None})
    cleared = (await client.post(f"/api/plans/{plan['id']}/simulate")).json()["yearly_snapshots"][0]
    assert with_basis["gross_income"] > 0
    assert cleared["state_tax"] == pytest.approx(0.0307 * cleared["gross_income"], abs=0.5)
    assert with_basis["state_tax"] == pytest.approx(0.0307 * max(0.0, with_basis["gross_income"] - 15_000), abs=0.5)

    def stateless_body(basis):
        return {
            "plan_id": plan["id"], "birth_year": 1976, "start_year": 2026, "life_expectancy": 90,
            "state_code": "PA",
            "accounts": {account["id"]: {**IRA, "state_taxed_basis": basis}},
            "drawdown_order": [{"rank": 1, "source_account_id": account["id"]}],
            "expenses": [{"id": "living", "name": "Living", "annual_amount": 20_000}],
        }
    stateless = await client.post("/api/simulate/stateless", json=stateless_body(15_000))
    assert stateless.status_code == 200, stateless.text
    without = await client.post("/api/simulate/stateless", json=stateless_body(None))
    recovered_tax = stateless.json()["yearly_snapshots"][0]["state_tax"]
    full_tax = without.json()["yearly_snapshots"][0]["state_tax"]
    # Pennsylvania cost recovery: the first $15,000 of distributions is untaxed
    # (the saving is a little larger because less is withdrawn to pay the tax).
    distributed = stateless.json()["yearly_snapshots"][0]["gross_income"]
    assert recovered_tax == pytest.approx(0.0307 * max(0.0, distributed - 15_000), abs=0.5)
    assert full_tax > recovered_tax

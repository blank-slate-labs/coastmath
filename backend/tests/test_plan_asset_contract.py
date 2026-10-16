import pytest


@pytest.mark.anyio
async def test_plan_responses_include_property_and_debt(client):
    plan = (await client.post("/api/plans", json={"name": "Contract", "birth_year": 1990})).json()
    assert plan["real_assets"] == [] and plan["liabilities"] == []
    url = f"/api/plans/{plan['id']}"
    asset = await client.post(f"{url}/real-assets", json={"name": "Home", "current_value": 100000, "adjusted_basis": 80000, "sale_year": 2030})
    assert asset.status_code == 201
    debt = await client.post(f"{url}/liabilities", json={"name": "Mortgage", "principal_balance": 50000, "interest_rate": 6, "term_months": 120, "linked_asset_id": asset.json()["id"]})
    assert debt.status_code == 201
    for response in [await client.get(url), await client.put(url, json={"name": "Updated"})]:
        assert response.status_code == 200
        data = response.json()
        assert data["real_assets"][0]["adjusted_basis"] == 80000
        assert data["liabilities"][0]["linked_asset_id"] == asset.json()["id"]
    listed = (await client.get("/api/plans")).json()
    assert listed[0]["real_assets"][0]["sale_year"] == 2030

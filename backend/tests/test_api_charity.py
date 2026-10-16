"""Tests for the charity CRUD API endpoints."""

import pytest
from httpx import AsyncClient

from tests.api_support import assert_error_shape, create_plan, new_id


async def _create_charity(client: AsyncClient, plan_id: str, **overrides) -> dict:
    defaults = {
        "name": "Local Food Bank",
        "entity_type": "direct",
        "annual_amount": 5000,
    }
    defaults.update(overrides)
    r = await client.post(f"/api/plans/{plan_id}/charities", json=defaults)
    assert r.status_code == 201
    return r.json()


class TestCharityCRUD:
    @pytest.mark.anyio
    async def test_create_charity(self, client: AsyncClient):
        plan = await create_plan(client)
        charity = await _create_charity(
            client, plan["id"], name="Red Cross", entity_type="daf", annual_amount=10000
        )
        assert charity["name"] == "Red Cross"
        assert charity["entity_type"] == "daf"
        assert charity["annual_amount"] == 10000
        assert charity["plan_id"] == plan["id"]
        assert "id" in charity
        assert charity["start_milestone_id"] is None
        assert charity["end_milestone_id"] is None

    @pytest.mark.anyio
    async def test_list_charities(self, client: AsyncClient):
        plan = await create_plan(client)
        await _create_charity(client, plan["id"], name="Charity A")
        await _create_charity(client, plan["id"], name="Charity B")
        r = await client.get(f"/api/plans/{plan['id']}/charities")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 2
        names = {c["name"] for c in items}
        assert "Charity A" in names
        assert "Charity B" in names

    @pytest.mark.anyio
    async def test_list_charities_scoped_to_plan(self, client: AsyncClient):
        plan_a = await create_plan(client, name="Plan A")
        plan_b = await create_plan(client, name="Plan B")
        await _create_charity(client, plan_a["id"], name="Charity A")
        await _create_charity(client, plan_b["id"], name="Charity B")

        r = await client.get(f"/api/plans/{plan_a['id']}/charities")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["name"] == "Charity A"

    @pytest.mark.anyio
    async def test_get_charity(self, client: AsyncClient):
        plan = await create_plan(client)
        charity = await _create_charity(client, plan["id"])
        r = await client.get(f"/api/plans/{plan['id']}/charities/{charity['id']}")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == charity["id"]
        assert data["name"] == charity["name"]

    @pytest.mark.anyio
    async def test_update_charity(self, client: AsyncClient):
        plan = await create_plan(client)
        charity = await _create_charity(client, plan["id"])
        r = await client.patch(
            f"/api/plans/{plan['id']}/charities/{charity['id']}",
            json={"name": "Updated Name", "annual_amount": 9999},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Updated Name"
        assert data["annual_amount"] == 9999
        assert data["entity_type"] == charity["entity_type"]

    @pytest.mark.anyio
    async def test_update_charity_entity_type(self, client: AsyncClient):
        plan = await create_plan(client)
        charity = await _create_charity(client, plan["id"], entity_type="direct")
        r = await client.patch(
            f"/api/plans/{plan['id']}/charities/{charity['id']}",
            json={"entity_type": "qcd"},
        )
        assert r.status_code == 200
        assert r.json()["entity_type"] == "qcd"

    @pytest.mark.anyio
    async def test_delete_charity(self, client: AsyncClient):
        plan = await create_plan(client)
        charity = await _create_charity(client, plan["id"])
        r = await client.delete(f"/api/plans/{plan['id']}/charities/{charity['id']}")
        assert r.status_code == 204

        # Verify gone
        r = await client.get(f"/api/plans/{plan['id']}/charities/{charity['id']}")
        assert r.status_code == 404

    @pytest.mark.anyio
    async def test_full_lifecycle(self, client: AsyncClient):
        plan = await create_plan(client)
        # Create
        charity = await _create_charity(client, plan["id"], name="Lifecycle Test")
        cid = charity["id"]
        # Read
        r = await client.get(f"/api/plans/{plan['id']}/charities/{cid}")
        assert r.status_code == 200
        assert r.json()["name"] == "Lifecycle Test"
        # Update
        r = await client.patch(
            f"/api/plans/{plan['id']}/charities/{cid}",
            json={"name": "Updated"},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Updated"
        # Delete
        r = await client.delete(f"/api/plans/{plan['id']}/charities/{cid}")
        assert r.status_code == 204
        # Verify gone
        r = await client.get(f"/api/plans/{plan['id']}/charities/{cid}")
        assert r.status_code == 404


class TestCharityErrors:
    @pytest.mark.anyio
    async def test_create_charity_nonexistent_plan_404(self, client: AsyncClient):
        r = await client.post(
            f"/api/plans/{new_id()}/charities",
            json={"name": "Test", "entity_type": "direct", "annual_amount": 1000},
        )
        assert r.status_code == 404
        assert_error_shape(r.json())
        assert r.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.anyio
    async def test_get_charity_nonexistent_404(self, client: AsyncClient):
        plan = await create_plan(client)
        r = await client.get(f"/api/plans/{plan['id']}/charities/{new_id()}")
        assert r.status_code == 404
        assert_error_shape(r.json())
        assert r.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.anyio
    async def test_update_charity_nonexistent_404(self, client: AsyncClient):
        plan = await create_plan(client)
        r = await client.patch(
            f"/api/plans/{plan['id']}/charities/{new_id()}",
            json={"name": "Nope"},
        )
        assert r.status_code == 404

    @pytest.mark.anyio
    async def test_delete_charity_nonexistent_404(self, client: AsyncClient):
        plan = await create_plan(client)
        r = await client.delete(f"/api/plans/{plan['id']}/charities/{new_id()}")
        assert r.status_code == 404

    @pytest.mark.anyio
    async def test_invalid_entity_type_422(self, client: AsyncClient):
        plan = await create_plan(client)
        r = await client.post(
            f"/api/plans/{plan['id']}/charities",
            json={"name": "Bad", "entity_type": "invalid_type", "annual_amount": 1000},
        )
        assert r.status_code == 422
        assert_error_shape(r.json())
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.anyio
    async def test_list_charities_nonexistent_plan_404(self, client: AsyncClient):
        r = await client.get(f"/api/plans/{new_id()}/charities")
        assert r.status_code == 404
        assert_error_shape(r.json())

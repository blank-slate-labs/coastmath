"""Tests for the compare mode API endpoint."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.models.plan import Plan
from app.models.user import User
from tests.api_support import assert_error_shape, create_plan, new_id


class TestCompareEndpoint:
    @pytest.mark.anyio
    async def test_compare_two_plans(self, client: AsyncClient):
        plan_a = await create_plan(client, name="Plan A")
        plan_b = await create_plan(client, name="Plan B")

        r = await client.post(
            f"/api/plans/{plan_a['id']}/compare",
            json={"baseline_plan_id": plan_b["id"]},
        )
        assert r.status_code == 200
        data = r.json()

        # Response structure
        assert "current" in data
        assert "baseline" in data
        assert "delta" in data

        # Both simulations should have metadata
        assert data["current"]["metadata"]["plan_id"] == plan_a["id"]
        assert data["baseline"]["metadata"]["plan_id"] == plan_b["id"]

        # Delta should have entries with correct fields
        assert isinstance(data["delta"], list)
        assert len(data["delta"]) > 0
        for entry in data["delta"]:
            assert "year" in entry
            assert "current_net_worth" in entry
            assert "baseline_net_worth" in entry
            assert "difference" in entry
            assert entry["difference"] == pytest.approx(
                entry["current_net_worth"] - entry["baseline_net_worth"]
            )

    @pytest.mark.anyio
    async def test_compare_nonexistent_baseline_404(self, client: AsyncClient):
        plan = await create_plan(client)
        r = await client.post(
            f"/api/plans/{plan['id']}/compare",
            json={"baseline_plan_id": new_id()},
        )
        assert r.status_code == 404
        assert_error_shape(r.json())
        assert r.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.anyio
    async def test_compare_nonexistent_current_404(self, client: AsyncClient):
        plan = await create_plan(client)
        r = await client.post(
            f"/api/plans/{new_id()}/compare",
            json={"baseline_plan_id": plan["id"]},
        )
        assert r.status_code == 404
        assert_error_shape(r.json())
        assert r.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.anyio
    async def test_compare_different_user_plan_404(self, client: AsyncClient, db_session):
        """Baseline owned by another user should return 404 (don't leak existence)."""
        plan = await create_plan(client)

        # Create another user and a plan owned by them directly in the DB
        other_user_id = uuid.uuid4()
        other_user = User(
            id=other_user_id,
            email="other@example.com",
            display_name="Other User",
            settings={},
            created_at=datetime.now(UTC),
        )
        db_session.add(other_user)
        db_session.flush()

        other_plan = Plan(
            id=uuid.uuid4(),
            user_id=other_user_id,
            name="Other User Plan",
            birth_year=1985,
            plan_type="NOW",
            created_at=datetime.now(UTC),
        )
        db_session.add(other_plan)
        db_session.commit()

        r = await client.post(
            f"/api/plans/{plan['id']}/compare",
            json={"baseline_plan_id": str(other_plan.id)},
        )
        assert r.status_code == 404
        assert_error_shape(r.json())
        assert r.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.anyio
    async def test_compare_plan_against_itself_zero_deltas(self, client: AsyncClient):
        """Comparing a plan against itself should produce all-zero deltas."""
        plan = await create_plan(client)

        r = await client.post(
            f"/api/plans/{plan['id']}/compare",
            json={"baseline_plan_id": plan["id"]},
        )
        assert r.status_code == 200
        data = r.json()

        assert len(data["delta"]) > 0
        for entry in data["delta"]:
            assert entry["difference"] == pytest.approx(0.0)
            assert entry["current_net_worth"] == pytest.approx(entry["baseline_net_worth"])

    @pytest.mark.anyio
    async def test_delta_values_are_current_minus_baseline(self, client: AsyncClient):
        """Delta difference must equal current_net_worth - baseline_net_worth."""
        plan_a = await create_plan(client, name="High Income", birth_year=1990)
        plan_b = await create_plan(client, name="Low Income", birth_year=1990)

        r = await client.post(
            f"/api/plans/{plan_a['id']}/compare",
            json={"baseline_plan_id": plan_b["id"]},
        )
        assert r.status_code == 200
        data = r.json()

        assert len(data["delta"]) > 0
        for entry in data["delta"]:
            expected = entry["current_net_worth"] - entry["baseline_net_worth"]
            assert entry["difference"] == pytest.approx(expected)

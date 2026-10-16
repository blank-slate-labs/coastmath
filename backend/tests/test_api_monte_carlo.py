"""Tests for the Monte Carlo API endpoint."""

import pytest
from httpx import AsyncClient

from tests.api_support import assert_error_shape, create_plan, new_id


@pytest.mark.anyio
async def test_seed_reproduces_invested_plan(client: AsyncClient):
    plan = await create_plan(client)
    account = await client.post("/api/accounts", json={"name": "Invested", "account_type": "taxable_brokerage", "balance": 100000})
    assert account.status_code == 201
    url = f"/api/plans/{plan['id']}/monte-carlo"
    first = await client.post(url, json={"n_trials": 5, "seed": 42})
    second = await client.post(url, json={"n_trials": 5, "seed": 42})
    other = await client.post(url, json={"n_trials": 5, "seed": 43})
    assert first.status_code == second.status_code == other.status_code == 200
    assert first.json() == second.json()
    assert first.json()["percentile_curves"] != other.json()["percentile_curves"]


@pytest.mark.anyio
@pytest.mark.parametrize("body", [{"seed": -1}, {"block_size_min": 0}, {"block_size_max": 31}])
async def test_invalid_sampling_parameters(client: AsyncClient, body):
    plan = await create_plan(client)
    response = await client.post(f"/api/plans/{plan['id']}/monte-carlo", json=body)
    assert response.status_code == 422


class TestMonteCarloEndpoint:
    @pytest.mark.anyio
    async def test_valid_plan_returns_result(self, client: AsyncClient):
        plan = await create_plan(client)

        r = await client.post(
            f"/api/plans/{plan['id']}/monte-carlo",
            json={"n_trials": 5, "block_size_min": 3, "block_size_max": 5},
        )
        assert r.status_code == 200
        data = r.json()

        # Check MonteCarloResult shape
        assert "success_rate" in data
        assert "n_trials" in data
        assert data["n_trials"] == 5
        assert "percentile_curves" in data
        assert "failure_analysis" in data
        assert "median_final_net_worth" in data
        assert "p10_final_net_worth" in data
        assert "p90_final_net_worth" in data

        # Percentile curves shape
        curves = data["percentile_curves"]
        assert "years" in curves
        assert "p10" in curves
        assert "p25" in curves
        assert "p50" in curves
        assert "p75" in curves
        assert "p90" in curves
        assert len(curves["p10"]) == len(curves["years"])

        # Success rate should be between 0 and 1
        assert 0.0 <= data["success_rate"] <= 1.0

    @pytest.mark.anyio
    async def test_nonexistent_plan_404(self, client: AsyncClient):
        r = await client.post(
            f"/api/plans/{new_id()}/monte-carlo",
            json={"n_trials": 5},
        )
        assert r.status_code == 404
        assert_error_shape(r.json())
        assert r.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.anyio
    async def test_default_request_body(self, client: AsyncClient):
        """Endpoint works with default MonteCarloRequest values (empty body)."""
        plan = await create_plan(client)

        r = await client.post(
            f"/api/plans/{plan['id']}/monte-carlo",
            json={},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["n_trials"] == 1000

    @pytest.mark.anyio
    async def test_invalid_block_size_range_422(self, client: AsyncClient):
        plan = await create_plan(client)

        r = await client.post(
            f"/api/plans/{plan['id']}/monte-carlo",
            json={"n_trials": 5, "block_size_min": 7, "block_size_max": 3},
        )
        assert r.status_code == 422
        assert_error_shape(r.json())
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.anyio
    async def test_failure_mode_parameter(self, client: AsyncClient):
        """failure_mode can be passed and defaults to liquid_assets."""
        plan = await create_plan(client)

        # Explicit liquid_assets mode
        r = await client.post(
            f"/api/plans/{plan['id']}/monte-carlo",
            json={"n_trials": 5, "failure_mode": "liquid_assets"},
        )
        assert r.status_code == 200

        # Legacy net_worth mode
        r = await client.post(
            f"/api/plans/{plan['id']}/monte-carlo",
            json={"n_trials": 5, "failure_mode": "net_worth"},
        )
        assert r.status_code == 200

    @pytest.mark.anyio
    async def test_invalid_failure_mode_422(self, client: AsyncClient):
        """Invalid failure_mode value is rejected."""
        plan = await create_plan(client)

        r = await client.post(
            f"/api/plans/{plan['id']}/monte-carlo",
            json={"n_trials": 5, "failure_mode": "invalid_mode"},
        )
        assert r.status_code == 422



@pytest.mark.anyio
async def test_success_targets_reported_with_definitions(client: AsyncClient):
    """Custom terminal targets produce a separate target success rate and
    outcome categories alongside the funding success rate."""
    r = await client.post("/api/plans", json={"name": "Targets", "birth_year": 1990, "life_expectancy": 60})
    pid = r.json()["id"]
    await client.post("/api/accounts", json={"name": "Cash", "account_type": "checking", "balance": 500_000})
    r = await client.post(f"/api/plans/{pid}/monte-carlo", json={"n_trials": 6, "seed": 7, "success_targets": {"terminal_net_worth_min": 10_000_000}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["funding_success_rate"] == body["success_rate"]
    assert body["target_success_rate"] == 0.0  # nobody reaches $10M
    cats = {c["key"]: c for c in body["outcome_categories"]}
    assert cats["survived_below_target"]["count"] + cats["funding_failure"]["count"] == 6
    assert set(body["definitions"]) >= {"success_rate", "funding_success_rate", "target_success_rate", "terminal_net_worth"}
    assert body["success_targets"]["terminal_net_worth_min"] == 10_000_000
    r = await client.post(f"/api/plans/{pid}/monte-carlo", json={"n_trials": 2, "seed": 7, "success_targets": {"terminal_net_worth_min": -5}})
    assert r.status_code == 422


@pytest.mark.anyio
async def test_saved_legacy_target_fills_an_omitted_terminal_target(client: AsyncClient):
    """The plan's legacy target (today's dollars) becomes the nominal final-year
    target when a request omits one; explicit values, including null, win."""
    r = await client.post("/api/plans", json={"name": "Heirs", "birth_year": 1990, "life_expectancy": 60})
    pid = r.json()["id"]
    await client.post("/api/accounts", json={"name": "Cash", "account_type": "checking", "balance": 500_000})
    r = await client.put(f"/api/plans/{pid}", json={"estate_settings": {"legacy_target": 1_000_000}})
    assert r.status_code == 200, r.text
    assert r.json()["estate_settings"]["legacy_target"] == 1_000_000
    url = f"/api/plans/{pid}/monte-carlo"

    async def target(**body):
        response = await client.post(url, json={"n_trials": 2, "seed": 7, **body})
        assert response.status_code == 200, response.text
        return response.json()

    omitted = await target()
    years = omitted["percentile_curves"]["years"]
    # Default plan inflation is a fixed 3%; amounts step each January after the start year.
    expected = 1_000_000 * 1.03 ** (years[-1] - years[0])
    assert omitted["success_targets"]["terminal_net_worth_min"] == pytest.approx(expected)
    assert omitted["target_success_rate"] is not None
    with_cuts = await target(success_targets={"count_spending_cuts_as_shortfall": True})
    assert with_cuts["success_targets"] == {"terminal_net_worth_min": pytest.approx(expected), "count_spending_cuts_as_shortfall": True}

    assert (await target(success_targets={"terminal_net_worth_min": 5}))["success_targets"]["terminal_net_worth_min"] == 5
    assert (await target(success_targets=None))["success_targets"] is None
    explicit_none = await target(success_targets={"terminal_net_worth_min": None, "count_spending_cuts_as_shortfall": True})
    assert explicit_none["success_targets"]["terminal_net_worth_min"] is None

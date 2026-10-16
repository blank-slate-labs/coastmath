"""Monte Carlo trial replay routes: exact replay, validation and ownership."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.models.plan import Plan
from app.models.user import User
from tests.api_support import assert_error, blob, invested_plan

pytestmark = pytest.mark.anyio

RUN = {"n_trials": 6, "block_size_min": 2, "block_size_max": 5, "failure_mode": "liquid_assets", "calibrate_to_plan": True}


async def test_replay_matches_the_run_for_requested_and_drawn_seeds(client: AsyncClient):
    plan_id = await invested_plan(client)
    url = f"/api/plans/{plan_id}/monte-carlo"
    for seed in (42, None):
        run = await client.post(url, json={**RUN, "seed": seed})
        assert run.status_code == 200, run.text
        result = run.json()
        trials = result["trials"]
        assert len(trials["ending_net_worth"]) == result["n_trials"] == 6
        if seed is not None:
            assert result["base_seed"] == seed
        for index in (0, 5):
            replay = await client.post(f"{url}/trials/{index}", json={**RUN, "seed": seed, "base_seed": result["base_seed"]})
            assert replay.status_code == 200, replay.text
            detail = replay.json()
            assert detail["index"] == index and detail["seed"] == result["base_seed"] + index
            assert detail["ending_net_worth"] == trials["ending_net_worth"][index]
            assert detail["success"] == trials["success"][index]
            assert detail["outcome"] == trials["outcome"][index]
            assert detail["simulation"]["yearly_snapshots"][-1]["net_worth"] == trials["ending_net_worth"][index]
            assert detail["simulation"]["yearly_snapshots"][-1]["year"] == result["percentile_curves"]["years"][-1]


async def test_replay_validates_index_seed_and_settings(client: AsyncClient):
    plan_id = await invested_plan(client)
    url = f"/api/plans/{plan_id}/monte-carlo/trials"
    body = {**RUN, "base_seed": 42}
    error = assert_error(await client.post(f"{url}/6", json=body), 422, "VALIDATION_ERROR")
    assert error["details"][0]["field"] == "index"
    assert_error(await client.post(f"{url}/-1", json=body), 422, "VALIDATION_ERROR")
    missing_seed = {key: value for key, value in body.items() if key != "base_seed"}
    assert_error(await client.post(f"{url}/0", json=missing_seed), 422, "VALIDATION_ERROR")
    missing_count = {key: value for key, value in body.items() if key != "n_trials"}
    assert_error(await client.post(f"{url}/0", json=missing_count), 422, "VALIDATION_ERROR")
    assert_error(await client.post(f"{url}/0", json={**body, "seed": 41}), 422, "VALIDATION_ERROR")
    assert_error(await client.post(f"{url}/0", json={**body, "base_seed": 2**32}), 422, "VALIDATION_ERROR")
    assert_error(await client.post(f"{url}/0", json={**body, "block_size_min": 6, "block_size_max": 3}), 422, "VALIDATION_ERROR")
    # The largest drawn seed is accepted.
    assert (await client.post(f"{url}/0", json={**body, "base_seed": 2**32 - 1})).status_code == 200


async def test_another_users_plan_is_not_found(client: AsyncClient, db_session):
    other = User(id=uuid.uuid4(), email="other@example.com", display_name="Other", settings={},
                 created_at=datetime.now(UTC))
    db_session.add(other)
    db_session.flush()
    plan = Plan(id=uuid.uuid4(), user_id=other.id, name="Other plan", birth_year=1980, plan_type="NOW",
                created_at=datetime.now(UTC))
    db_session.add(plan)
    db_session.commit()
    response = await client.post(f"/api/plans/{plan.id}/monte-carlo/trials/0", json={**RUN, "base_seed": 1})
    assert_error(response, 404, "NOT_FOUND")
    assert_error(await client.post(f"/api/plans/{uuid.uuid4()}/monte-carlo/trials/0", json={**RUN, "base_seed": 1}),
                  404, "NOT_FOUND")


async def test_replay_requires_a_session(client: AsyncClient):
    plan_id = await invested_plan(client)
    client.cookies.clear()
    response = await client.post(f"/api/plans/{plan_id}/monte-carlo/trials/0", json={**RUN, "base_seed": 1})
    assert response.status_code == 401


async def test_stateless_replay_matches_stateless_run(client: AsyncClient):
    plan = blob(accounts={"b": {"account_type": "taxable_brokerage", "balance": 200_000}},
                expenses=[{"id": "e", "name": "Living", "annual_amount": 15_000}],
                assumptions={"inflation_rate": 0.03, "stock_growth_rate": 0.06})
    body = {"plan": plan, "num_simulations": 4, "block_size": 4}
    run = await client.post("/api/monte-carlo/stateless", json=body)
    assert run.status_code == 200, run.text
    result = run.json()
    replay = await client.post("/api/monte-carlo/stateless/trials/3", json={**body, "base_seed": result["base_seed"]})
    assert replay.status_code == 200, replay.text
    assert replay.json()["ending_net_worth"] == result["trials"]["ending_net_worth"][3]
    assert_error(await client.post("/api/monte-carlo/stateless/trials/4", json={**body, "base_seed": result["base_seed"]}),
                  422, "VALIDATION_ERROR")

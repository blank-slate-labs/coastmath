"""Monte Carlo sampling options over the API: validation, run size and replay."""

import pytest
from httpx import AsyncClient

from tests.api_support import assert_error, blob, invested_plan

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("body", [
    {"block_length": 5},                                                   # block_bootstrap has no fixed length
    {"sampling": "random_years", "on_data_end": "loop"},
    {"sampling": "historical_sequential", "iterations": 3},               # repeats need random_restart
    {"sampling": "historical_sequential", "on_data_end": "loop", "iterations": 2},
    {"sampling": "historical_sequential", "on_data_end": "random_restart", "iterations": 11},  # 97 x 11 > 1,000 trials
    {"sampling": "moving_block", "block_length": 0},
    {"sampling": "monthly"},
    {"sources": {"stocks": {"source": "normal", "mean": 7}}},             # stdev missing
    {"sources": {"bonds": {"source": "historical", "mean": 4, "stdev": 6}}},
    {"sources": {"inflation": {"source": "normal", "mean": 3, "stdev": -1}}},
    {"sources": {"crypto": {"source": "normal", "mean": 3, "stdev": 1}}},
    {"crypto": {"mean": 20}},
    {"outcome_thresholds": {"failure_early_fraction": 0.7, "failure_late_fraction": 0.5}},
    {"outcome_thresholds": {"thin_margin_percent": 300, "wide_margin_percent": 200}},
    {"outcome_thresholds": {"almost_failed_percent": 300, "large_surplus_percent": 200}},  # older request names
    {"extra_metrics": ["taxes", "taxes"]},
    {"extra_metrics": ["net_worth"]},
])
async def test_invalid_options_return_the_shared_422(client: AsyncClient, body):
    plan_id = await invested_plan(client)
    response = await client.post(f"/api/plans/{plan_id}/monte-carlo", json={"n_trials": 2, **body})
    assert_error(response, 422, "VALIDATION_ERROR")


async def test_stop_without_enough_history_is_a_422(client: AsyncClient):
    plan = await client.post("/api/plans", json={"name": "Long", "birth_year": 2008, "life_expectancy": 120,
                                                 "plan_type": "NOW"})
    assert plan.status_code == 201, plan.text
    response = await client.post(f"/api/plans/{plan.json()['id']}/monte-carlo",
                                 json={"sampling": "historical_sequential", "on_data_end": "stop"})
    error = assert_error(response, 422, "VALIDATION_ERROR")
    assert error["details"][0]["field"] == "on_data_end"


async def test_sequential_run_reports_its_size_and_replays(client: AsyncClient):
    plan_id = await invested_plan(client)
    url = f"/api/plans/{plan_id}/monte-carlo"
    options = {"sampling": "historical_sequential", "on_data_end": "stop", "seed": 9,
               "sources": {"inflation": {"source": "normal", "mean": 2.5, "stdev": 1}},
               "crypto": {"mean": 15, "stdev": 60},
               "extra_metrics": ["spending", "taxes"]}
    run = await client.post(url, json={"n_trials": 3, **options})
    assert run.status_code == 200, run.text
    result = run.json()
    years = len(result["percentile_curves"]["years"])
    assert result["n_trials"] == 97 - years + 1 == len(result["trials"]["ending_net_worth"])
    assert result["sampling"] == "historical_sequential"
    assert set(result["metric_percentiles"]) == {"spending", "taxes"}
    detail = result["outcome_detail"]
    timing, surplus = detail["failure_timing"], detail["surplus"]
    assert timing["early"] + timing["mid"] + timing["late"] == len(result["failure_analysis"])
    assert surplus["thin_margin"] + surplus["moderate_margin"] + surplus["wide_margin"] == sum(result["trials"]["success"])
    last = result["n_trials"] - 1
    replay = await client.post(f"{url}/trials/{last}",
                               json={"n_trials": result["n_trials"], **options, "base_seed": result["base_seed"]})
    assert replay.status_code == 200, replay.text
    assert replay.json()["ending_net_worth"] == result["trials"]["ending_net_worth"][last]
    assert replay.json()["historical_start_year"] == 1928 + last
    beyond = await client.post(f"{url}/trials/{last + 1}",
                               json={"n_trials": result["n_trials"] + 1, **options, "base_seed": result["base_seed"]})
    assert assert_error(beyond, 422, "VALIDATION_ERROR")["details"][0]["field"] == "index"


async def test_default_run_has_no_metric_percentiles(client: AsyncClient):
    plan_id = await invested_plan(client)
    run = await client.post(f"/api/plans/{plan_id}/monte-carlo", json={"n_trials": 2, "seed": 1})
    assert run.status_code == 200, run.text
    result = run.json()
    assert result["sampling"] == "block_bootstrap"
    assert result["metric_percentiles"] is None
    assert result["outcome_detail"]["surplus"]["thin_margin_percent"] == 25


async def test_older_surplus_threshold_names_are_still_accepted(client: AsyncClient):
    plan_id = await invested_plan(client)
    url = f"/api/plans/{plan_id}/monte-carlo"
    old = await client.post(url, json={"n_trials": 2, "seed": 1, "outcome_thresholds": {
        "almost_failed_percent": 40, "large_surplus_percent": 300}})
    assert old.status_code == 200, old.text
    surplus = old.json()["outcome_detail"]["surplus"]
    assert (surplus["thin_margin_percent"], surplus["wide_margin_percent"]) == (40, 300)
    assert "almost_failed_percent" not in surplus and "large_surplus_percent" not in surplus
    new = await client.post(url, json={"n_trials": 2, "seed": 1, "outcome_thresholds": {
        "thin_margin_percent": 40, "wide_margin_percent": 300}})
    assert new.status_code == 200, new.text
    assert new.json()["outcome_detail"]["surplus"] == surplus


async def test_stateless_run_accepts_sampling_options(client: AsyncClient):
    plan = blob(accounts={"b": {"account_type": "taxable_brokerage", "balance": 200_000}},
                expenses=[{"id": "e", "name": "Living", "annual_amount": 15_000}],
                assumptions={"inflation_rate": 0.03, "stock_growth_rate": 0.06})
    body = {"plan": plan, "num_simulations": 4, "sampling": "random_years", "seed": 3}
    run = await client.post("/api/monte-carlo/stateless", json=body)
    assert run.status_code == 200, run.text
    result = run.json()
    assert result["sampling"] == "random_years"
    replay = await client.post("/api/monte-carlo/stateless/trials/2", json={**body, "base_seed": result["base_seed"]})
    assert replay.status_code == 200, replay.text
    assert replay.json()["ending_net_worth"] == result["trials"]["ending_net_worth"][2]
    assert_error(await client.post("/api/monte-carlo/stateless", json={**body, "block_length": 3}),
                  422, "VALIDATION_ERROR")

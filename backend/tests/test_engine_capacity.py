"""Projection work is bounded per worker and refused, not queued, when full."""
from threading import BoundedSemaphore

import pytest
from fastapi import HTTPException

from app import engine_capacity, monte_carlo_capacity
from app.routers import withdrawal_strategies
from coastmath.engine import withdrawal_comparison
from tests.engine_support import strategy_plan


@pytest.mark.parametrize(("raw", "expected"), [
    (None, 4), ("", 4), ("  ", 4), ("abc", 4), ("2.5", 4), ("0", 1), ("-3", 1), ("2", 2), (" 8 ", 8),
])
def test_engine_concurrency_setting_tolerates_blank_and_invalid_values(raw, expected):
    assert engine_capacity.parse_engine_concurrency(raw) == expected


def test_engine_slots_refuse_excess_work_and_release_after_errors(monkeypatch):
    monkeypatch.setattr(engine_capacity, "_slots", BoundedSemaphore(2))
    with engine_capacity.engine_slot(), engine_capacity.engine_slot():
        with pytest.raises(HTTPException) as error:
            with engine_capacity.engine_slot():
                pass
        assert error.value.status_code == 429
        assert error.value.headers == {"Retry-After": "2"}
    with pytest.raises(RuntimeError), engine_capacity.engine_slot():
        raise RuntimeError("engine failure")
    with engine_capacity.engine_slot(), engine_capacity.engine_slot():
        pass  # Both slots were returned.


@pytest.mark.anyio
async def test_projection_routes_answer_429_while_capacity_is_taken(client, demo_plan, monkeypatch):
    slots = BoundedSemaphore(1)
    monkeypatch.setattr(engine_capacity, "_slots", slots)
    slots.acquire()
    busy = await client.post(f"/api/plans/{demo_plan.id}/simulate")
    assert busy.status_code == 429
    assert busy.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert busy.headers["retry-after"] == "2"
    stress = await client.post(f"/api/plans/{demo_plan.id}/simulate", params={"historical_start_year": 1970})
    assert stress.status_code == 429
    slots.release()
    assert (await client.post(f"/api/plans/{demo_plan.id}/simulate")).status_code == 200


@pytest.mark.anyio
async def test_withdrawal_trials_share_the_monte_carlo_slot_and_two_processes(client, demo_plan, monkeypatch):
    calls = []

    def compare(plan_data, **kwargs):
        calls.append(kwargs)
        raise HTTPException(status_code=418)  # Stop before building a response.

    monkeypatch.setattr(withdrawal_strategies, "compare_withdrawal_strategies", compare)
    url = f"/api/plans/{demo_plan.id}/withdrawal-strategies/compare"
    assert monte_carlo_capacity._slot.acquire(blocking=False)
    try:
        busy = await client.post(url, json={"monte_carlo_trials": 50})
        assert busy.status_code == 429 and calls == []
        assert (await client.post(url, json={"monte_carlo_trials": 0})).status_code == 418  # No trials, no slot.
    finally:
        monte_carlo_capacity._slot.release()
    assert (await client.post(url, json={"monte_carlo_trials": 50})).status_code == 418
    assert [call["max_workers"] for call in calls] == [2, 2]


def test_withdrawal_comparison_passes_the_worker_limit_to_every_trial_run(monkeypatch):
    seen = []
    monkeypatch.setattr(withdrawal_comparison, "run_monte_carlo",
                        lambda *args, **kwargs: seen.append(kwargs["max_workers"]) or pytest.fail("stop"))
    with pytest.raises(pytest.fail.Exception):
        withdrawal_comparison.compare_withdrawal_strategies(
            strategy_plan(), methods=["constant_dollar"], initial_rate=0.04, start_milestone_id="retire",
            start_age=None, mc_trials=2, seed=1, max_workers=2)
    assert seen == [2]

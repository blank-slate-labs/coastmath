"""One client address cannot hold a worker or the engine, however many sessions it opens."""
import asyncio
import inspect
import subprocess
import sys
import time

import httpx
import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from limits import parse
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from app import access, client_slots, monte_carlo_capacity
from app.auth import router as auth_router
from app.main import app
from app.middleware.client_budget import ClientBudgetMiddleware
from app.plugins import extensions
from app.rate_limit import address_key, current_client, limiter
from app.routers import monte_carlo as monte_carlo_router
from app.routers.ledger_connections import PLAID_WEBHOOK_PATH
from coastmath.engine.monte_carlo import MonteCarloTimeLimit, run_monte_carlo
from tests.engine_support import strategy_plan


async def call(asgi, path="/api/plans", method="GET", peer="198.51.100.1", **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=asgi, client=(peer, 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as visitor:
        return await visitor.request(method, path, **kwargs)


def recording_app(seen: list):
    async def asgi(scope, receive, send):
        seen.append(current_client.get())
        await JSONResponse({})(scope, receive, send)
    return asgi


@pytest.mark.parametrize(("raw", "key"), [
    ("198.51.100.7", "198.51.100.7"),
    ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),
    ("::ffff:198.51.100.7", "198.51.100.7"),
    ("testclient", "testclient"),
])
def test_ipv6_clients_are_keyed_by_their_64(raw, key):
    assert address_key(raw) == key


@pytest.mark.anyio
async def test_request_and_write_budgets_refuse_before_the_app_runs():
    seen = []
    budget = ClientBudgetMiddleware(recording_app(seen), requests=parse("3/minute"), writes=parse("1/minute"))
    assert (await call(budget, method="POST")).status_code == 200
    refused = await call(budget, method="POST")
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert 1 <= int(refused.headers["retry-after"]) <= 61
    assert (await call(budget)).status_code == 200  # Reads have their own room.
    assert (await call(budget)).status_code == 429
    assert (await call(budget, peer="198.51.100.2")).status_code == 200
    assert (await call(budget, path="/api/health")).status_code == 200
    assert (await call(budget, path="/help")).status_code == 200  # Pages and assets are not budgeted.
    assert seen == ["198.51.100.1", "198.51.100.1", "198.51.100.2", None, None]


@pytest.mark.anyio
async def test_requests_in_flight_are_capped_per_address():
    release = asyncio.Event()

    async def slow(scope, receive, send):
        await release.wait()
        await JSONResponse({})(scope, receive, send)

    budget = ClientBudgetMiddleware(slow, max_in_flight=2)
    held = [asyncio.create_task(call(budget)) for _ in range(2)]
    while sum(budget.in_flight.values()) < 2:
        await asyncio.sleep(0)
    assert (await call(budget)).status_code == 429
    other = asyncio.create_task(call(budget, peer="198.51.100.2"))
    while sum(budget.in_flight.values()) < 3:
        await asyncio.sleep(0)
    release.set()
    assert [response.status_code for response in await asyncio.gather(*held, other)] == [200, 200, 200]
    assert not budget.in_flight


ENGINE_MARKERS = ("engine_errors(", "engine_slot()", "monte_carlo_slot()", "run_with_capacity(", "_load_and_simulate(")


def engine_routes() -> list[APIRoute]:
    # Plan-blob routes exist only for tests and local tools, with their own address limits.
    return [route for route in app.routes if isinstance(route, APIRoute) and "/stateless" not in route.path
            and any(marker in inspect.getsource(inspect.unwrap(route.endpoint)) for marker in ENGINE_MARKERS)]


def test_every_engine_route_draws_on_the_shared_address_budget():
    routes = engine_routes()
    assert len(routes) >= 10
    for route in routes:
        name = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
        assert any(limit.scope == "engine" for limit in limiter._route_limits[name]), route.path


@pytest.mark.anyio
async def test_engine_budget_is_shared_across_routes_and_sessions(client, demo_plan, monkeypatch):
    for limits in limiter._route_limits.values():
        for limit in limits:
            if limit.scope == "engine":
                monkeypatch.setattr(limit, "limit", parse("2/minute"))
    plan = f"/api/plans/{demo_plan.id}"
    assert (await client.post(f"{plan}/simulate")).status_code == 200
    assert (await client.post(f"{plan}/plan-checks")).status_code == 200
    refused = await client.post(f"{plan}/wellness")
    assert refused.status_code == 429


def test_one_address_holds_at_most_its_share_of_slots():
    def busy():
        return HTTPException(status_code=429)

    assert client_slots._bucket("198.51.100.1") != client_slots._bucket("198.51.100.2")
    token = current_client.set("198.51.100.1")
    try:
        with client_slots.client_slot("engine", 2, busy), client_slots.client_slot("engine", 2, busy):
            with pytest.raises(HTTPException):
                with client_slots.client_slot("engine", 2, busy):
                    pass
            other = current_client.set("198.51.100.2")
            with client_slots.client_slot("engine", 2, busy):
                pass
            current_client.reset(other)
        with client_slots.client_slot("engine", 2, busy):
            pass  # Both were released.
    finally:
        current_client.reset(token)


def test_an_unusable_lock_directory_never_stops_the_engine(monkeypatch, tmp_path):
    blocked = tmp_path / "not_a_directory"
    blocked.write_text("")
    monkeypatch.setattr(client_slots, "LOCK_DIR", blocked)
    token = current_client.set("198.51.100.1")
    try:
        with client_slots.client_slot("engine", 1, lambda: HTTPException(status_code=429)):
            with client_slots.client_slot("engine", 1, lambda: HTTPException(status_code=429)):
                pass  # Uncapped; the per-worker slots still apply.
    finally:
        current_client.reset(token)


def test_slot_caps_hold_across_worker_processes_and_free_when_one_exits():
    def busy():
        return HTTPException(status_code=429)

    client_slots.LOCK_DIR.mkdir(exist_ok=True)
    path = client_slots.LOCK_DIR / f"monte_carlo_{client_slots._bucket('198.51.100.1')}_0"
    worker = subprocess.Popen(
        [sys.executable, "-c", "import fcntl, os, sys; fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR);"
         " fcntl.flock(fd, fcntl.LOCK_EX); print('held', flush=True); sys.stdin.read()", str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    token = current_client.set("198.51.100.1")
    try:
        assert worker.stdout.readline().strip() == "held"
        with pytest.raises(HTTPException):
            with client_slots.client_slot("monte_carlo", 1, busy):
                pass
        worker.kill()  # A crashed worker never leaks its slot.
        worker.wait(timeout=10)
        with client_slots.client_slot("monte_carlo", 1, busy):
            pass
    finally:
        current_client.reset(token)
        worker.kill()


@pytest.mark.anyio
async def test_refused_monte_carlo_never_loads_the_plan(client, demo_plan, monkeypatch):
    loads = []
    load = monte_carlo_router.load_plan_data
    monkeypatch.setattr(monte_carlo_router, "load_plan_data", lambda *args, **kwargs: loads.append(1) or load(*args, **kwargs))
    url = f"/api/plans/{demo_plan.id}/monte-carlo"
    assert monte_carlo_capacity._slot.acquire(blocking=False)
    try:
        assert (await client.post(url, json={"n_trials": 5})).status_code == 429
    finally:
        monte_carlo_capacity._slot.release()
    # Another worker running this address's job also refuses it, though this worker is free.
    token = current_client.set("127.0.0.1")
    try:
        with client_slots.client_slot("monte_carlo", 1, monte_carlo_capacity._busy):
            assert (await client.post(url, json={"n_trials": 5})).status_code == 429
    finally:
        current_client.reset(token)
    assert loads == []
    assert (await client.post(url, json={"n_trials": 5})).status_code == 200
    assert loads == [1]


@pytest.mark.anyio
async def test_monte_carlo_stops_at_the_time_limit(client, demo_plan, monkeypatch):
    monkeypatch.setattr(monte_carlo_capacity, "TIME_LIMIT_SECONDS", 0)
    refused = await client.post(f"/api/plans/{demo_plan.id}/monte-carlo", json={"n_trials": 50})
    assert refused.status_code == 422
    assert refused.json()["error"]["details"][0]["field"] == "n_trials"
    assert refused.json()["error"]["message"] == "This run would take over 0 seconds. Run fewer trials."
    assert monte_carlo_capacity._slot.acquire(blocking=False)  # The slot was returned.
    monte_carlo_capacity._slot.release()


def test_monte_carlo_cancels_unstarted_trials_at_the_deadline():
    started = time.monotonic()
    with pytest.raises(MonteCarloTimeLimit):
        run_monte_carlo(strategy_plan(), n_trials=200, seed=1, max_workers=1, deadline=time.monotonic())
    assert time.monotonic() - started < 30
    assert run_monte_carlo(strategy_plan(), n_trials=3, seed=1, max_workers=1,
                           deadline=time.monotonic() + 300).n_trials == 3


@pytest.mark.anyio
async def test_new_anonymous_accounts_per_address_are_capped_per_day(client, monkeypatch):
    monkeypatch.setattr(auth_router, "ANONYMOUS_ACCOUNTS_PER_DAY", parse("2/day"))
    for _ in range(2):
        assert (await call(app, "/api/auth/session", "POST", peer="198.51.100.9")).status_code == 201
    refused = await call(app, "/api/auth/session", "POST", peer="198.51.100.9")
    assert refused.status_code == 429
    assert (await call(app, "/api/auth/session", "POST", peer="198.51.100.10")).status_code == 201
    assert (await client.post("/api/auth/session")).status_code == 200  # Resuming is not counted.


@pytest.mark.anyio
async def test_archiving_cannot_grow_an_account_past_the_plan_limit(client, monkeypatch):
    monkeypatch.setattr(access, "PLAN_LIMIT", 2)
    for _ in range(2):
        created = await client.post("/api/plans", json={"name": "Loop", "birth_year": 1980})
        assert created.status_code == 201
        assert (await client.post(f"/api/plans/{created.json()['id']}/archive")).status_code == 200
    refused = await client.post("/api/plans", json={"name": "Loop", "birth_year": 1980})
    assert refused.status_code == 422
    assert refused.json()["error"]["message"] == "Delete a plan before adding another."


def test_routes_that_read_the_database_on_the_event_loop_are_known():
    """Async routes run on the event loop, where a blocking query stalls every request on the worker.

    Each listed route hands its database work to the thread pool, or is a
    legacy sign-in route that LEGACY_PROVIDER_AUTH_ENABLED=false retires.
    """
    async_with_db = {
        route.path for route in app.routes
        if isinstance(route, APIRoute) and inspect.iscoroutinefunction(inspect.unwrap(route.endpoint))
        and any(parameter.annotation is Session
                for parameter in inspect.signature(inspect.unwrap(route.endpoint)).parameters.values())
    }
    assert async_with_db <= {
        "/api/plans/{plan_id}/monte-carlo",  # Loads on the job's thread.
        PLAID_WEBHOOK_PATH, *extensions.callback_paths,  # Signed callbacks; their work runs on the thread pool.
        "/api/auth/callback", "/api/auth/native/callback",
    }

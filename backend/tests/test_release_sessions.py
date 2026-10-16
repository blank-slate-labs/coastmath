"""Release regressions at the HTTP/session boundary; no live identity provider."""

import asyncio
from datetime import date
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.auth.router import create_jwt
from app.models.plan import Plan
from app.models.user import User
from app.monte_carlo_capacity import _slot, run_with_capacity
from app.routers import monte_carlo_stateless
from app.schemas.plan import PlanCreate, PlanUpdate
from app.schemas.spouse import SpouseCreate, SpouseUpdate
from coastmath.schemas import birth_year
from coastmath.schemas.plan_data_request import PlanDataRequest


@pytest.mark.anyio
async def test_repeated_resume_preserves_identity_and_still_limits_creation(
    client, db_session, test_user
):
    for _ in range(40):
        result = await client.get("/api/auth/me")
        assert result.status_code == 200
        assert result.json()["id"] == str(test_user.id)
        assert "session=" in result.headers["set-cookie"]
    for _ in range(30):
        result = await client.post("/api/auth/session")
        assert result.status_code == 200
    assert (await client.post("/api/auth/session")).status_code == 429
    assert db_session.query(User).count() == 1
    assert db_session.query(Plan).count() == 0


@pytest.mark.anyio
async def test_logout_revokes_replayed_cookie_on_every_session_path(client, test_user):
    old = create_jwt(test_user.id)
    assert (await client.post("/api/auth/logout")).status_code == 200
    client.cookies.clear()
    client.cookies.set("session", old)
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.get("/api/plans")).status_code == 401
    result = await client.post("/api/auth/session", json={"seed_demo": False})
    assert result.status_code == 201 and result.json()["id"] != str(test_user.id)


@pytest.mark.anyio
async def test_optional_session_probe_is_204_only_without_a_cookie(client, test_user):
    assert (await client.get("/api/auth/me?optional=true")).json()["id"] == str(test_user.id)
    old = create_jwt(test_user.id, test_user.session_version + 1)
    client.cookies.clear()
    probe = await client.get("/api/auth/me?optional=true")
    assert probe.status_code == 204 and probe.content == b"" and "set-cookie" not in probe.headers
    # Without the flag, and with a cookie that no longer verifies, a missing session stays a 401.
    assert (await client.get("/api/auth/me")).status_code == 401
    client.cookies.set("session", old)
    assert (await client.get("/api/auth/me?optional=true")).status_code == 401


@pytest.mark.anyio
async def test_both_monte_carlo_routes_share_capacity_and_retry_header(client):
    plan = (
        await client.post("/api/plans", json={"name": "Synthetic", "birth_year": 1980})
    ).json()
    assert _slot.acquire(blocking=False)
    try:
        for url, body in [
            (f"/api/plans/{plan['id']}/monte-carlo", {"n_trials": 1}),
            (
                "/api/monte-carlo/stateless",
                {
                    "plan": {
                        "plan_id": plan["id"],
                        "birth_year": 1980,
                        "start_year": 2026,
                    },
                    "num_simulations": 1,
                },
            ),
        ]:
            result = await client.post(url, json=body)
            assert result.status_code == 429
            assert result.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
            assert result.headers["retry-after"] == "5"
    finally:
        _slot.release()


@pytest.mark.anyio
async def test_stateless_monte_carlo_rejects_no_session_before_work(
    client, monkeypatch
):
    run = Mock()
    monkeypatch.setattr(monte_carlo_stateless, "run_monte_carlo", run)
    client.cookies.clear()
    response = await client.post(
        "/api/monte-carlo/stateless",
        json={
            "plan": {
                "plan_id": str(uuid4()),
                "birth_year": 1980,
                "start_year": 2026,
            },
            "num_simulations": 10000,
        },
    )
    assert response.status_code == 401
    run.assert_not_called()


@pytest.mark.anyio
async def test_cancelled_request_keeps_capacity_until_compute_finishes():
    started, finish, ended = Event(), Event(), Event()

    def work():
        started.set()
        try:
            assert finish.wait(5)
        finally:
            ended.set()

    task = asyncio.create_task(run_with_capacity(work))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(HTTPException) as busy:
            await run_with_capacity(lambda: None)
        assert busy.value.status_code == 429
    finally:
        finish.set()
        assert await asyncio.to_thread(ended.wait, 2)
    assert await run_with_capacity(lambda: 42) == 42


@pytest.mark.parametrize(
    "model,extra,field",
    [
        (PlanCreate, {"name": "New"}, "birth_year"),
        (PlanUpdate, {}, "birth_year"),
        (SpouseCreate, {}, "birth_year"),
        (SpouseUpdate, {}, "birth_year"),
        (PlanDataRequest, {"plan_id": uuid4(), "start_year": 2029}, "birth_year"),
        (
            PlanDataRequest,
            {"plan_id": uuid4(), "start_year": 2029, "birth_year": 1980},
            "spouse_birth_year",
        ),
    ],
)
def test_all_birth_year_inputs_follow_year_rollover(monkeypatch, model, extra, field):
    class Calendar(date):
        current_year = 2027

        @classmethod
        def today(cls):
            return cls(cls.current_year, 1, 1)

    monkeypatch.setattr(birth_year, "date", Calendar)
    for year in [2027, 2028]:
        Calendar.current_year = year
        assert getattr(model(**(extra | {field: year})), field) == year
        for bad in [1899, year + 1]:
            with pytest.raises(ValidationError):
                model(**(extra | {field: bad}))

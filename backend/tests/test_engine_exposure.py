"""Production runs the engine only for saved plans, under per-user limits."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.auth.router import create_jwt
from app.models.user import User

BACKEND = Path(__file__).resolve().parents[1]

# Routers and docs are chosen when app.main is imported, so each flag setting
# needs a fresh interpreter rather than this process's already-imported app.
_PROBE = """
import json
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
print(json.dumps({
    "stateless_routes": sorted(r.path for r in app.routes if "stateless" in getattr(r, "path", "")),
    "docs": {path: client.get(path).status_code for path in ("/openapi.json", "/docs", "/redoc")},
    "simulate_stateless": client.post("/api/simulate/stateless", json={}).status_code,
}))
"""


def _probe(**flags: str) -> dict:
    # Explicit values also keep app.db's dotenv load from supplying a developer's flags.
    env = {**os.environ, "ENABLE_STATELESS_API": "false", "ENABLE_API_DOCS": "false", **flags}
    result = subprocess.run([sys.executable, "-c", _PROBE], cwd=BACKEND, env=env,
                            capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_production_defaults_omit_plan_blob_routes_and_api_schema():
    probe = _probe()
    assert probe["stateless_routes"] == []
    # 405 when a built SPA's GET catch-all shares the path; 404 without one.
    assert probe["simulate_stateless"] in (404, 405)
    assert probe["docs"] == {"/openapi.json": 404, "/docs": 404, "/redoc": 404}


def test_flags_restore_plan_blob_routes_and_api_schema_for_local_tools():
    probe = _probe(ENABLE_STATELESS_API="true", ENABLE_API_DOCS="true")
    assert probe["stateless_routes"] == [
        "/api/compare/stateless", "/api/monte-carlo/stateless",
        "/api/monte-carlo/stateless/trials/{index}", "/api/simulate/stateless",
    ]
    assert probe["simulate_stateless"] == 422
    assert probe["docs"] == {"/openapi.json": 200, "/docs": 200, "/redoc": 200}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "route,body,limit,status",
    [
        ("/api/plans/{plan}/simulate", None, 60, 404),
        ("/api/plans/{plan}/compare", {"baseline_plan_id": str(uuid.uuid4())}, 60, 404),
        ("/api/plans/{plan}/monte-carlo", {}, 10, 404),
        ("/api/plans/{plan}/monte-carlo/trials/0", {"n_trials": 1, "base_seed": 0}, 60, 404),
        ("/api/plans/{plan}/tax-strategies/compare", {"source_account_id": str(uuid.uuid4())}, 10, 404),
        ("/api/plans/{plan}/tax-strategies/search", {"blend_withdrawals": True, "bracket_rates": [0.22]}, 10, 404),
        ("/api/plans/{plan}/tax-suggestions", None, 10, 404),
        ("/api/plans/{plan}/withdrawal-strategies/compare", {}, 10, 404),
        ("/api/plans/{plan}/plan-checks", None, 60, 404),
        ("/api/plans/{plan}/social-security/claiming", None, 10, 404),
        ("/api/plans/{plan}/wellness", None, 60, 404),
        ("/api/plans/sepp-preview", {"balance": 100000, "start_age": 50}, 60, 200),
        ("/api/plans/ss-estimate", {"current_annual_income": 60000}, 60, 200),
    ],
)
async def test_calculation_routes_limit_each_session_user(client, db_session, route, body, limit, status):
    # SlowAPI counts a request before the handler runs, so an unknown plan's 404
    # consumes the budget without running the engine.
    url = route.format(plan=uuid.uuid4())
    for _ in range(limit):
        response = await client.post(url, json=body)
        assert response.status_code == status, response.text
    rejected = await client.post(url, json=body)
    assert rejected.status_code == 429
    assert rejected.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"

    # Another household behind the same address keeps its own budget.
    other = User(is_anonymous=True, display_name="Other household", settings={})
    db_session.add(other)
    db_session.commit()
    client.cookies.set("session", create_jwt(other.id))
    assert (await client.post(url, json=body)).status_code == status

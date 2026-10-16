"""Plan responses expose the canonical engine defaults without saving overrides."""

import uuid

import pytest

from app.routers.helpers import load_plan_data
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import AssumptionData


@pytest.mark.anyio
async def test_plan_defaults_match_engine_and_preserve_saved_overrides(client, db_session, test_user):
    created = await client.post("/api/plans", json={
        "name": "Default assumption display", "birth_year": 1980,
        "life_expectancy": 50, "plan_type": "FIXED_DATE", "start_date": "2026-01-01",
        "snapshot_conditions": {
            "9aeb6f27-ed95-41a4-915b-c91ec9908adc": {
                "balance": 100_000, "account_type": "taxable_brokerage",
            },
        },
    })
    assert created.status_code == 201, created.text
    body = created.json()
    pid = body["id"]
    defaults = body["assumption_defaults"]
    engine = AssumptionData()
    assert defaults == {
        "inflation": engine.inflation_rate,
        "market_return": engine.stock_growth_rate,
        "dividend_yield": engine.stock_dividend_yield,
        "bond_return": engine.bond_return_rate,
        "bond_allocation": 0.0,
        "cash_yield": engine.cash_yield_rate,
    }
    assert body["assumption_curves"] == []

    plan = load_plan_data(uuid.UUID(pid), test_user, db_session)
    # The default all-stock allocation actually uses the advertised growth
    # and dividend rates; the API has not created any saved assumptions.
    first = run_simulation(plan).yearly_snapshots[0]
    assert first.investment_growth == pytest.approx(100_000 * defaults["market_return"])
    assert first.gross_income == pytest.approx(100_000 * defaults["dividend_yield"])

    override = await client.post(f"/api/plans/{pid}/assumptions", json={
        "curve_type": "market_return", "mode": "fixed", "fixed_rate": 0.06,
    })
    assert override.status_code == 201, override.text
    detail = await client.get(f"/api/plans/{pid}")
    listing = await client.get("/api/plans")
    assert detail.status_code == listing.status_code == 200
    for saved in (detail.json(), next(p for p in listing.json() if p["id"] == pid)):
        assert saved["assumption_defaults"] == defaults
        assert len(saved["assumption_curves"]) == 1
        assert saved["assumption_curves"][0]["fixed_rate"] == 0.06

    deleted = await client.delete(f"/api/plans/{pid}/assumptions/{override.json()['id']}")
    assert deleted.status_code == 204
    restored = (await client.get(f"/api/plans/{pid}")).json()
    assert restored["assumption_defaults"] == defaults
    assert restored["assumption_curves"] == []

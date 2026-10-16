"""Engine failures get the same envelope whichever analysis route ran the engine."""

from threading import BoundedSemaphore

import pytest
from fastapi import HTTPException

from app import engine_capacity
from app.errors import api_error, validation_error
from app.routers import (
    spending_models,
    tax_strategies,
    tax_suggestions,
    withdrawal_strategies,
)
from app.routers.engine_errors import engine_errors
from coastmath.engine.household_lifecycle import UnsupportedLifecycleInput

pytestmark = pytest.mark.anyio


async def _plan(client) -> dict:
    plan = (await client.post("/api/plans", json={"name": "Engine errors", "birth_year": 1966, "plan_type": "NOW",
                                                  "life_expectancy": 90, "filing_status": "single"})).json()
    pid = plan["id"]

    async def account(name, kind, balance):
        r = await client.post("/api/accounts", json={"name": name, "account_type": kind, "balance": balance})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    ira = await account("IRA", "traditional_ira", 500_000)
    roth = await account("Roth", "roth_ira", 50_000)
    cash = await account("Cash", "checking", 100_000)
    assert (await client.post(f"/api/plans/{pid}/incomes", json={"name": "Salary", "annual_amount": 120_000})).status_code == 201
    assert (await client.post(f"/api/plans/{pid}/expenses", json={"name": "Living", "annual_amount": 60_000,
                                                                  "category": "essential"})).status_code == 201
    r = await client.put(f"/api/plans/{pid}/drawdown-order",
                         json={"items": [{"rank": i + 1, "source_account_id": a} for i, a in enumerate((cash, ira, roth))]})
    assert r.status_code in (200, 201), r.text
    return {"pid": pid, "ira": ira, "roth": roth}


# (route module, engine entry point, path under the plan, request body)
ROUTES = {
    "tax_strategy_compare": (tax_strategies, "compare_strategies", "tax-strategies/compare",
                             lambda ids: {"source_account_id": ids["ira"], "target_account_id": ids["roth"],
                                          "bracket_ceilings": [0.12, 0.22]}),
    "tax_strategy_search": (tax_strategies, "run_search", "tax-strategies/search",
                            lambda ids: {"objective": "lifetime_taxes", "bracket_rates": [0.12, 0.22],
                                         "conversion": {"source_account_id": ids["ira"],
                                                        "target_account_id": ids["roth"]}}),
    "tax_suggestions": (tax_suggestions, "suggest_tax_strategies", "tax-suggestions", lambda ids: None),
    "withdrawal_compare": (withdrawal_strategies, "compare_withdrawal_strategies", "withdrawal-strategies/compare",
                           lambda ids: {"methods": ["constant_dollar"], "monte_carlo_trials": 0}),
    "spending_compare": (spending_models, "compare_spending_models", "spending-models/compare",
                         lambda ids: {"variants": [{"kind": "amounts", "essential_annual": 40_000,
                                                    "discretionary_annual": 10_000}]}),
}


async def _post_failing(client, monkeypatch, route, error):
    module, entry, path, body = ROUTES[route]

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(module, entry, fail)
    ids = await _plan(client)
    return await client.post(f"/api/plans/{ids['pid']}/{path}", json=body(ids))


@pytest.mark.usefixtures("transactions_on")
@pytest.mark.parametrize("route", list(ROUTES))
async def test_engine_failure_is_simulation_failed_without_its_message(client, monkeypatch, caplog, route):
    response = await _post_failing(client, monkeypatch, route, RuntimeError("boom"))
    assert response.status_code == 500, response.text
    error = response.json()["error"]
    assert error["code"] == "SIMULATION_FAILED"
    assert error["details"] == []
    assert "boom" not in error["message"] and "boom" not in response.text
    # The log locates the failure without repeating the engine's message.
    assert "RuntimeError (message withheld)" in caplog.text and "boom" not in caplog.text


@pytest.mark.usefixtures("transactions_on")
@pytest.mark.parametrize("route", list(ROUTES))
async def test_unsupported_lifecycle_input_keeps_the_422_envelope(client, monkeypatch, route):
    message = "Successor treatment is not modeled."
    response = await _post_failing(client, monkeypatch, route, UnsupportedLifecycleInput(message))
    assert response.status_code == 422, response.text
    assert response.json()["error"] == {"code": "VALIDATION_ERROR", "message": message, "details": [
        {"field": "estate_settings.household_lifecycle", "reason": message}]}


async def test_search_still_reports_value_errors_as_search_settings(client, monkeypatch):
    response = await _post_failing(client, monkeypatch, "tax_strategy_search", ValueError("Too many simulations."))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"] == [{"field": "plan", "reason": "Adjust the search settings"}]


def _raised(run) -> HTTPException:
    with pytest.raises(HTTPException) as caught:
        run()
    return caught.value


def test_http_exceptions_pass_through_unchanged():
    original = api_error(409, "CONFLICT", "Changed.")

    def run():
        with engine_errors("Engine failed", "Failed"):
            raise original

    assert _raised(run) is original


def test_translators_apply_after_the_lifecycle_check():
    translate = {ValueError: lambda exc: validation_error(str(exc), "plan")}

    def run(error):
        def go():
            with engine_errors("Engine failed", "Failed", slot=False, translate=translate):
                raise error
        return _raised(go)

    # UnsupportedLifecycleInput is a ValueError, but keeps its own field.
    assert run(UnsupportedLifecycleInput("No")).detail["error"]["details"][0]["field"] == \
        "estate_settings.household_lifecycle"
    assert run(ValueError("Bad")).detail["error"]["details"] == [{"field": "plan", "reason": "Bad"}]
    assert run(KeyError("x")).detail["error"]["code"] == "SIMULATION_FAILED"


def test_slot_is_taken_only_when_asked_and_released_after_errors(monkeypatch):
    slots = BoundedSemaphore(1)
    monkeypatch.setattr(engine_capacity, "_slots", slots)
    assert slots.acquire(blocking=False)

    def busy():
        with engine_errors("Engine failed", "Failed"):
            pass

    busy_error = _raised(busy)
    assert busy_error.status_code == 429 and busy_error.detail["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    with engine_errors("Engine failed", "Failed", slot=False):
        pass
    slots.release()

    def fail():
        with engine_errors("Engine failed", "Failed"):
            raise RuntimeError("boom")

    assert _raised(fail).status_code == 500
    assert slots.acquire(blocking=False)
    slots.release()

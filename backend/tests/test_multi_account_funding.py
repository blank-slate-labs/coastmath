"""Focused regressions for ordered expense funding selections."""

from uuid import uuid4

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    PlanData,
)
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data


def _plan(*, accounts, expenses, drawdown_order=(), tax_settings=None, birth_year=1980, life_expectancy=70):
    return PlanData(
        plan_id=str(uuid4()),
        birth_year=birth_year,
        filing_status="single",
        life_expectancy=life_expectancy,
        start_year=2026,
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0),
        accounts=accounts,
        expenses=expenses,
        drawdown_order=list(drawdown_order),
        tax_settings=tax_settings or {"mode": "flat", "ordinary_income_tax_rate": 0},
    )


def test_specific_expense_draws_ordered_same_type_backups_without_shortfall():
    plan = _plan(
        accounts={
            "checking": AccountInfo(6_000, "checking", name="Checking"),
            "savings": AccountInfo(10_000, "savings", name="Savings"),
        },
        expenses=[ExpenseData(
            "living", "Living", 10_000, inflation_linked=False,
            specific_funding_source_ids=["checking", "savings"],
        )],
        drawdown_order=[DrawdownEntryData(1, "checking"), DrawdownEntryData(2, "savings")],
    )

    snapshot = run_simulation(plan).yearly_snapshots[0]

    assert snapshot.accounts["checking"] == pytest.approx(0)
    assert snapshot.accounts["savings"] == pytest.approx(6_000)
    assert snapshot.unfunded_expenses == pytest.approx(0)


def test_specific_expense_does_not_fallback_to_unselected_accounts():
    plan = _plan(
        accounts={
            "checking": AccountInfo(6_000, "checking"),
            "savings": AccountInfo(10_000, "savings"),
        },
        expenses=[ExpenseData(
            "living", "Living", 10_000, inflation_linked=False,
            specific_funding_source_ids=["checking"],
        )],
        drawdown_order=[DrawdownEntryData(1, "checking"), DrawdownEntryData(2, "savings")],
    )

    snapshot = run_simulation(plan).yearly_snapshots[0]

    assert snapshot.accounts["checking"] == pytest.approx(0)
    assert snapshot.accounts["savings"] == pytest.approx(10_000)
    assert snapshot.unfunded_expenses == pytest.approx(4_000)


def test_specific_expense_uses_global_type_hierarchy_and_preserves_tax_mechanics():
    plan = _plan(
        accounts={
            "cash": AccountInfo(0, "checking", name="Cash"),
            "taxable": AccountInfo(10_000, "taxable_brokerage", name="Taxable", cost_basis=10_000),
            "ira": AccountInfo(20_000, "traditional_ira", name="IRA"),
        },
        expenses=[ExpenseData(
            "living", "Living", 10_000, inflation_linked=False,
            specific_funding_source_ids=["taxable", "ira"],
        )],
        # Traditional IRA is globally first, so it funds the bill despite the
        # selected list placing taxable first. Withholding gross-up is shared
        # with ordinary drawdowns and the resulting tax is fully credited.
        drawdown_order=[DrawdownEntryData(1, "ira"), DrawdownEntryData(2, "taxable")],
        tax_settings={
            "mode": "flat",
            "ordinary_income_tax_rate": 0.20,
            "tax_deferred_withholding_rate": 0.20,
        },
        birth_year=1950,
        life_expectancy=95,
    )

    result = run_simulation(plan)
    snapshot = result.yearly_snapshots[0]

    assert snapshot.accounts["ira"] < 20_000
    assert snapshot.accounts["taxable"] == pytest.approx(10_000)
    assert snapshot.taxes > 0
    assert snapshot.unfunded_expenses == pytest.approx(0)


def test_stateless_list_round_trip_validates_existing_unique_accounts():
    request = PlanDataRequest(
        plan_id=uuid4(),
        birth_year=1980,
        life_expectancy=70,
        start_year=2026,
        accounts={
            "checking": {"balance": 6_000, "account_type": "checking"},
            "savings": {"balance": 10_000, "account_type": "savings"},
        },
        expenses=[{
            "id": "living",
            "name": "Living",
            "annual_amount": 10_000,
            "inflation_linked": False,
            "specific_funding_source_ids": ["checking", "savings"],
        }],
    )

    converted = request_to_engine_data(request)
    assert converted.expenses[0].specific_funding_source_ids == ["checking", "savings"]

    with pytest.raises(ValueError, match="unique"):
        PlanDataRequest(
            plan_id=uuid4(), birth_year=1980, life_expectancy=70, start_year=2026,
            accounts={"checking": {"balance": 6_000, "account_type": "checking"}},
            expenses=[{
                "id": "living", "name": "Living", "annual_amount": 10_000,
                "specific_funding_source_ids": ["checking", "checking"],
            }],
        )

    with pytest.raises(ValueError, match="existing accounts"):
        PlanDataRequest(
            plan_id=uuid4(), birth_year=1980, life_expectancy=70, start_year=2026,
            accounts={"checking": {"balance": 6_000, "account_type": "checking"}},
            expenses=[{
                "id": "living", "name": "Living", "annual_amount": 10_000,
                "specific_funding_source_ids": ["missing"],
            }],
        )


@pytest.mark.anyio
async def test_saved_api_validates_and_persists_ordered_funding_and_copy(client):
    plan = (await client.post("/api/plans", json={
        "name": "Funding plan", "birth_year": 1980, "life_expectancy": 70,
    })).json()
    account_a = (await client.post("/api/accounts", json={
        "name": "Checking", "account_type": "checking", "balance": 6_000,
    })).json()
    account_b = (await client.post("/api/accounts", json={
        "name": "Savings", "account_type": "savings", "balance": 10_000,
    })).json()

    expense = await client.post(f"/api/plans/{plan['id']}/expenses", json={
        "name": "Living", "annual_amount": 10_000,
        "specific_funding_source_ids": [account_a["id"], account_b["id"]],
    })
    assert expense.status_code == 201, expense.text
    assert expense.json()["specific_funding_source_ids"] == [account_a["id"], account_b["id"]]
    assert expense.json()["specific_funding_source_id"] == account_a["id"]

    listed = await client.get(f"/api/plans/{plan['id']}/expenses")
    assert listed.json()[0]["specific_funding_source_ids"] == [account_a["id"], account_b["id"]]

    duplicate = await client.post(f"/api/plans/{plan['id']}/duplicate")
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["expenses"][0]["specific_funding_source_ids"] == [account_a["id"], account_b["id"]]

    duplicate_ids = [account_a["id"], account_a["id"]]
    invalid = await client.post(f"/api/plans/{plan['id']}/expenses", json={
        "name": "Invalid", "annual_amount": 1_000,
        "specific_funding_source_ids": duplicate_ids,
    })
    assert invalid.status_code == 422
    assert "unique" in invalid.text

    missing = await client.post(f"/api/plans/{plan['id']}/expenses", json={
        "name": "Missing", "annual_amount": 1_000,
        "specific_funding_source_ids": [str(uuid4())],
    })
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.anyio
async def test_client_plan_copy_remaps_ordered_funding_accounts(client):
    client_record = (await client.post("/api/clients/personal")).json()
    plan = (await client.post("/api/plans", json={
        "name": "Client funding plan", "birth_year": 1980,
        "life_expectancy": 70, "client_id": client_record["id"],
    })).json()
    account_a = (await client.post(f"/api/plans/{plan['id']}/accounts", json={
        "name": "Checking", "account_type": "checking", "balance": 6_000,
    })).json()
    account_b = (await client.post(f"/api/plans/{plan['id']}/accounts", json={
        "name": "Savings", "account_type": "savings", "balance": 10_000,
    })).json()
    expense = await client.post(f"/api/plans/{plan['id']}/expenses", json={
        "name": "Living", "annual_amount": 10_000,
        "specific_funding_source_ids": [account_a["id"], account_b["id"]],
    })
    assert expense.status_code == 201, expense.text

    duplicate = await client.post(f"/api/plans/{plan['id']}/duplicate", json={})
    assert duplicate.status_code == 201, duplicate.text
    copied = duplicate.json()
    copied_accounts = (await client.get(f"/api/plans/{copied['id']}/accounts")).json()
    copied_by_name = {account["name"]: account for account in copied_accounts}
    assert copied_by_name["Checking"]["id"] != account_a["id"]
    assert copied_by_name["Savings"]["id"] != account_b["id"]
    copied_expense = copied["expenses"][0]
    assert copied_expense["specific_funding_source_ids"] == [
        copied_by_name["Checking"]["id"], copied_by_name["Savings"]["id"],
    ]
    assert copied_expense["specific_funding_source_id"] == copied_by_name["Checking"]["id"]


@pytest.mark.anyio
async def test_ordered_funding_stale_edits_and_legacy_scalar_replacement(client):
    plan = (await client.post("/api/plans", json={"name": "Funding edits", "birth_year": 1980})).json()
    ids = [(await client.post("/api/accounts", json={"name": name, "account_type": "checking", "balance": 100})).json()["id"]
           for name in ("First", "Second")]
    base = f"/api/plans/{plan['id']}/expenses"
    expense = (await client.post(base, json={"name": "Bill", "annual_amount": 50,
                                             "specific_funding_source_ids": ids})).json()
    path = f"{base}/{expense['id']}"
    renamed = await client.put(path, json={"name": "Renamed"})
    assert renamed.json()["specific_funding_source_ids"] == ids
    reverse = ids[::-1]
    changed = await client.put(path, json={"specific_funding_source_ids": reverse,
        "expected_values": {"specific_funding_source_ids": ids}})
    assert changed.status_code == 200, changed.text
    assert changed.json()["specific_funding_source_id"] == reverse[0]
    stale = await client.put(path, json={"specific_funding_source_ids": [],
        "expected_values": {"specific_funding_source_ids": ids}})
    assert stale.status_code == 409
    legacy = await client.put(path, json={"specific_funding_source_id": ids[0]})
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["specific_funding_source_ids"] is None
    assert legacy.json()["specific_funding_source_id"] == ids[0]
    assert legacy.json()["name"] == "Renamed"

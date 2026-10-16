"""Household bond target, asset location and per-account bond glide paths."""

import numpy as np
import pytest
from pydantic import ValidationError

from app.schemas.account import AccountInvestmentSettings
from coastmath.engine.bond_location import glide_bond_allocation, linear_interpolate
from coastmath.engine.monte_carlo import _run_single_trial, _TrialInputs
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    IncomeData,
    PlanData,
)
from coastmath.schemas.asset_location import AssetLocation

STOCK, BOND = 0.10, 0.04


def _plan(accounts, *, bonds=0.4, location=None, income=None, spouse_birth_year=None):
    tax_settings = {"mode": "flat", "ordinary_income_tax_rate": 0.0, "capital_gains_tax_rate": 0.0}
    if location is not None:
        tax_settings["asset_location"] = location
    return PlanData(
        plan_id="00000000-0000-4000-8000-0000000000c1",
        birth_year=1980,
        birth_month=1,
        spouse_birth_year=spouse_birth_year,
        filing_status="married_filing_jointly" if spouse_birth_year else "single",
        life_expectancy=90,
        start_year=2026,
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=STOCK, bond_return_rate=BOND,
                                   stock_dividend_yield=0.0, cash_yield_rate=0.0),
        assumption_curves=[AssumptionCurveData("bond_allocation", fixed_rate=bonds)],
        accounts={**accounts, "cash": AccountInfo(0, "checking")},
        income_streams=income or [],
        tax_settings=tax_settings,
    )


def _grown(balance, bond_share):
    return balance * (1 + bond_share * BOND + (1 - bond_share) * STOCK)


HOUSEHOLD = {"bond_allocation_mode": "household"}


def _ira(balance=600_000, **settings):
    return AccountInfo(balance, "traditional_ira", investment_settings=settings or None)


def _brokerage(balance=400_000, **settings):
    return AccountInfo(balance, "taxable_brokerage", cost_basis=balance, investment_settings=settings or None)


def _first(plan):
    return run_simulation(plan).yearly_snapshots[0]


def test_household_target_fills_tax_deferred_first():
    first = _first(_plan({"ira": _ira(), "brokerage": _brokerage()}, location=HOUSEHOLD))
    # $400,000 of bonds (40% of $1M) all fit in the $600,000 IRA.
    assert first.bond_allocation_by_account == {"ira": pytest.approx(2 / 3, abs=1e-6), "brokerage": 0.0}
    assert first.accounts["ira"] == pytest.approx(_grown(600_000, 2 / 3))
    assert first.accounts["brokerage"] == pytest.approx(440_000)
    # The household as a whole earns the 60/40 blend.
    assert first.accounts["ira"] + first.accounts["brokerage"] == pytest.approx(_grown(1_000_000, 0.4))


def test_target_beyond_first_bucket_spills_into_next_in_order():
    accounts = {"ira": _ira(), "roth": AccountInfo(100_000, "roth_ira"), "brokerage": _brokerage(300_000)}
    first = _first(_plan(accounts, bonds=0.8, location=HOUSEHOLD))
    # $800,000 of bonds: IRA $600k, Roth $100k, then $100k of the $300k brokerage.
    assert first.bond_allocation_by_account == pytest.approx({"ira": 1.0, "roth": 1.0, "brokerage": 1 / 3}, abs=1e-6)
    assert first.accounts["brokerage"] == pytest.approx(_grown(300_000, 1 / 3))


def test_custom_order_with_account_id_and_shared_bucket():
    accounts = {"ira": _ira(300_000), "k401": AccountInfo(100_000, "traditional_401k"), "brokerage": _brokerage(600_000)}
    location = {**HOUSEHOLD, "bond_location_order": ["brokerage", "tax_deferred"]}
    first = _first(_plan(accounts, bonds=0.7, location=location))
    # $700k: the brokerage named by id takes $600k; the tax-deferred bucket
    # shares the remaining $100k in proportion to balance (25% each).
    assert first.bond_allocation_by_account == pytest.approx({"brokerage": 1.0, "ira": 0.25, "k401": 0.25})


def test_explicit_overrides_are_kept_and_count_toward_the_target():
    accounts = {"ira": _ira(bond_allocation=0.0), "brokerage": _brokerage()}
    first = _first(_plan(accounts, location=HOUSEHOLD))
    # The all-stock IRA keeps its setting, so the brokerage must hold all $400k of bonds.
    assert first.bond_allocation_by_account == {"ira": 0.0, "brokerage": 1.0}
    assert first.accounts["ira"] == pytest.approx(660_000)
    assert first.accounts["brokerage"] == pytest.approx(416_000)

    # An override holding more than the target leaves no bonds for others.
    over = _first(_plan({"ira": _ira(bond_allocation=1.0), "brokerage": _brokerage()}, location=HOUSEHOLD))
    assert over.bond_allocation_by_account == {"ira": 1.0, "brokerage": 0.0}


def test_excluded_and_never_pooled_accounts_keep_the_plan_allocation():
    accounts = {
        "ira": _ira(),
        "brokerage": _brokerage(),
        "hsa": AccountInfo(100_000, "hsa"),
        "other_ira": _ira(200_000),
        "coin": AccountInfo(50_000, "cryptocurrency"),
    }
    location = {**HOUSEHOLD, "excluded_account_ids": ["other_ira"]}
    first = _first(_plan(accounts, location=location))
    assert set(first.bond_allocation_by_account) == {"ira", "brokerage"}
    assert first.bond_allocation_by_account["ira"] == pytest.approx(2 / 3, abs=1e-6)
    assert first.accounts["hsa"] == pytest.approx(_grown(100_000, 0.4))
    assert first.accounts["other_ira"] == pytest.approx(_grown(200_000, 0.4))
    assert first.accounts["coin"] == pytest.approx(55_000)


def test_per_account_mode_is_identical_to_no_setting():
    accounts = {"ira": _ira(bond_allocation=0.1), "brokerage": _brokerage()}
    legacy = run_simulation(_plan(accounts))
    explicit = run_simulation(_plan(accounts, location={"bond_allocation_mode": "per_account",
                                                        "bond_location_order": ["taxable"]}))
    assert [s.accounts for s in explicit.yearly_snapshots] == [s.accounts for s in legacy.yearly_snapshots]
    assert all(s.bond_allocation_by_account == {} for s in explicit.yearly_snapshots)
    assert legacy.yearly_snapshots[0].accounts["brokerage"] == pytest.approx(_grown(400_000, 0.4))


def test_glide_interpolation_by_year_and_by_age():
    assert linear_interpolate([(0, 0.0), (10, 1.0)], 2.5) == pytest.approx(0.25)
    assert linear_interpolate([(0, 0.2), (10, 1.0)], -5) == 0.2
    assert linear_interpolate([(0, 0.2), (10, 1.0)], 50) == 1.0
    by_year = [{"year": 2030, "bond_allocation": 0.2}, {"year": 2040, "bond_allocation": 0.7}]
    assert glide_bond_allocation(by_year, 2035, owner_age=0) == pytest.approx(0.45)
    assert glide_bond_allocation(by_year, 2020, owner_age=0) == pytest.approx(0.2)
    by_age = [{"age": 50, "bond_allocation": 0.3}, {"age": 60, "bond_allocation": 0.8}]
    assert glide_bond_allocation(by_age, 2026, owner_age=56) == pytest.approx(0.6)
    assert glide_bond_allocation([], 2026, owner_age=56) is None


def test_glide_overrides_fixed_value_and_uses_owner_age():
    glide_year = [{"year": 2025, "bond_allocation": 0.0}, {"year": 2027, "bond_allocation": 1.0}]
    glide_age = [{"age": 40, "bond_allocation": 0.2}, {"age": 50, "bond_allocation": 0.8}]
    accounts = {
        "by_year": _brokerage(100_000, bond_allocation=0.9, bond_allocation_glide=glide_year),
        "by_age": _brokerage(100_000, bond_allocation_glide=glide_age),
        "spouse": AccountInfo(100_000, "traditional_ira", owner="spouse",
                              investment_settings={"bond_allocation_glide": glide_age}),
    }
    first = _first(_plan(accounts, bonds=0.0, spouse_birth_year=1984))
    assert first.accounts["by_year"] == pytest.approx(_grown(100_000, 0.5))
    # Age 46 in 2026: 0.2 + 0.6 * 6/10 = 0.56.
    assert first.accounts["by_age"] == pytest.approx(_grown(100_000, 0.56))
    # The partner is 42: 0.2 + 0.6 * 2/10 = 0.32.
    assert first.accounts["spouse"] == pytest.approx(_grown(100_000, 0.32))
    assert first.bond_allocation_by_account == {}


def test_glide_counts_as_override_in_household_mode():
    glide = [{"year": 2026, "bond_allocation": 0.5}]
    accounts = {"ira": _ira(bond_allocation_glide=glide), "brokerage": _brokerage()}
    first = _first(_plan(accounts, bonds=0.5, location=HOUSEHOLD))
    # IRA holds $300k of bonds; the brokerage holds the other $200k (50%).
    assert first.bond_allocation_by_account == pytest.approx({"ira": 0.5, "brokerage": 0.5})


def test_bond_income_character_follows_the_account_bond_share():
    accounts = {"ira": _ira(), "brokerage": _brokerage(bond_income_yield=0.04)}
    pension = [IncomeData("pension", "Pension", 50_000, growth_rate=0.0, tax_category="qualified_pension")]
    first = _first(_plan(accounts, bonds=0.7, location=HOUSEHOLD, income=pension))
    assert first.bond_allocation_by_account["brokerage"] == pytest.approx(0.25)
    interest = sum(f.amount for f in first.cash_flow.income_sources if f.name == "Taxable-Account Bond Interest")
    assert interest == pytest.approx(400_000 * 0.25 * 0.04)

    # All bonds fit in the IRA: the brokerage recognizes no bond interest.
    sheltered = _first(_plan(accounts, bonds=0.4, location=HOUSEHOLD, income=pension))
    assert not any(f.name == "Taxable-Account Bond Interest" and f.amount > 0
                   for f in sheltered.cash_flow.income_sources)


def test_monte_carlo_trial_places_bonds_each_year():
    plan = _plan({"ira": _ira(), "brokerage": _brokerage()}, location=HOUSEHOLD)
    # Every sampled year: stocks +25%, bonds 0%.
    history = np.array([[0.25, 0.0, 0.0]], dtype=float)
    result = _run_single_trial(
        _TrialInputs(plan, history, plan_years=2, start_year=2026, block_size_range=(1, 1)), seed=3,
    )
    first, second = result.yearly_snapshots[:2]
    # Year 1: $400k of bonds in the IRA, $200k of IRA stock and all brokerage stock grow 25%.
    assert first.accounts["ira"] == pytest.approx(650_000)
    assert first.accounts["brokerage"] == pytest.approx(500_000)
    # Year 2 re-solves from the new balances: 40% of $1.15M = $460k of IRA bonds.
    assert second.accounts["ira"] == pytest.approx(460_000 + 190_000 * 1.25)
    assert second.accounts["brokerage"] == pytest.approx(625_000)


def test_schema_validation():
    with pytest.raises(ValidationError):
        AccountInvestmentSettings(bond_allocation_glide=[{"year": 2030, "age": 50, "bond_allocation": 0.5}])
    with pytest.raises(ValidationError):
        AccountInvestmentSettings(bond_allocation_glide=[{"bond_allocation": 0.5}])
    with pytest.raises(ValidationError):
        AccountInvestmentSettings(bond_allocation_glide=[{"year": 2030, "bond_allocation": 0.5},
                                                         {"age": 60, "bond_allocation": 0.6}])
    with pytest.raises(ValidationError):
        AccountInvestmentSettings(bond_allocation_glide=[{"year": 2030, "bond_allocation": 1.5}])
    with pytest.raises(ValidationError):
        AssetLocation(bond_allocation_mode="household", bond_location_order=["taxable", "taxable"])
    assert AssetLocation().bond_location_order == ["tax_deferred", "tax_free", "taxable"]
    # Unset glide paths stay out of dumps, so stored settings are unchanged.
    assert "bond_allocation_glide" not in AccountInvestmentSettings(bond_allocation=0.2).model_dump()


@pytest.mark.anyio
async def test_api_round_trip_and_stateless_parity(client):
    location = {"bond_allocation_mode": "household", "bond_location_order": ["tax_deferred", "taxable"],
                "excluded_account_ids": []}
    created = await client.post("/api/plans", json={"name": "Location", "birth_year": 1980,
                                                    "tax_settings": {"asset_location": location}})
    assert created.status_code == 201, created.text
    plan = created.json()
    url = f"/api/plans/{plan['id']}"
    read = (await client.get(url)).json()["tax_settings"]
    assert read["asset_location"] == location

    glide = [{"year": 2026, "age": None, "bond_allocation": 0.1}, {"year": 2040, "age": None, "bond_allocation": 0.6}]
    ira = await client.post("/api/accounts", json={
        "name": "IRA", "account_type": "traditional_ira", "balance": 600_000,
        "investment_settings": {"bond_allocation_glide": glide}})
    assert ira.status_code == 201, ira.text
    ira = ira.json()
    assert ira["investment_settings"]["bond_allocation_glide"] == glide
    brokerage = (await client.post("/api/accounts", json={
        "name": "Brokerage", "account_type": "taxable_brokerage", "balance": 400_000,
        "cost_basis": 400_000})).json()
    assert "bond_allocation_glide" not in (brokerage["investment_settings"] or {})

    simulated = await client.post(f"{url}/simulate")
    assert simulated.status_code == 200, simulated.text
    persisted = simulated.json()
    shares = persisted["yearly_snapshots"][0]["bond_allocation_by_account"]
    assert set(shares) == {ira["id"], brokerage["id"]}

    stateless = await client.post("/api/simulate/stateless", json={
        "plan_id": plan["id"], "birth_year": 1980, "life_expectancy": plan["life_expectancy"],
        "start_year": persisted["metadata"]["start_year"],
        "first_year_fraction": persisted["metadata"]["first_year_fraction"],
        "tax_settings": {"asset_location": location},
        "accounts": {
            ira["id"]: {"balance": 600_000, "account_type": "traditional_ira", "name": "IRA",
                        "investment_settings": {"bond_allocation_glide": glide}},
            brokerage["id"]: {"balance": 400_000, "account_type": "taxable_brokerage", "name": "Brokerage",
                              "cost_basis": 400_000},
        },
    })
    assert stateless.status_code == 200, stateless.text
    assert stateless.json()["yearly_snapshots"][0]["bond_allocation_by_account"] == pytest.approx(shares)

    # An empty list clears the glide path; a client that omits the key keeps it.
    kept = await client.put(f"/api/accounts/{ira['id']}", json={"investment_settings": {"bond_allocation": 0.2}})
    assert kept.status_code == 200, kept.text
    assert kept.json()["investment_settings"]["bond_allocation_glide"] == glide
    cleared = await client.put(f"/api/accounts/{ira['id']}", json={"investment_settings": {"bond_allocation_glide": []}})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["investment_settings"]["bond_allocation_glide"] == []

    bad = await client.post("/api/accounts", json={
        "name": "Bad", "account_type": "roth_ira", "balance": 1,
        "investment_settings": {"bond_allocation_glide": [{"year": 2030, "age": 50, "bond_allocation": 0.5}]}})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "VALIDATION_ERROR"

    updated = await client.put(url, json={"tax_settings": {**read, "asset_location": None}})
    assert updated.status_code == 200, updated.text
    assert "asset_location" not in (await client.get(url)).json()["tax_settings"]
    snapshot = (await client.post(f"{url}/simulate")).json()["yearly_snapshots"][0]
    assert snapshot["bond_allocation_by_account"] == {}

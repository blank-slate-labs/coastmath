"""Spending flex additions through the saved-plan, stateless and copy paths."""

import pytest

from app.schemas.plan import SpendingRules
from coastmath.schemas.plan_data_request import SpendingRulesRequest
from tests.scenario_support import post

LEGACY = {"performance_mode": "all_time_high", "spending_floor": 0.5,
          "thresholds": [{"threshold": -0.1, "reduction": 0.3}]}
NEW = {
    **LEGACY,
    "upside_thresholds": [{"threshold": 0.05, "increase": 0.1}, {"threshold": 0.2, "increase": 0.3}],
    "flex_scope": ["expenses", "strategy_spending", "leftover_spending"],
    "surplus_mode": "spend_leftover",
}


def _stateless(rules):
    return {
        "plan_id": "00000000-0000-4000-8000-000000000003", "birth_year": 1980, "start_year": 2026,
        "life_expectancy": 55, "tax_settings": {"mode": "flat", "ordinary_income_tax_rate": 0,
                                                "capital_gains_tax_rate": 0},
        "accounts": {"stocks": {"name": "Stocks", "account_type": "taxable_brokerage",
                                "balance": 100_000, "cost_basis": 100_000}},
        "drawdown_order": [{"rank": 1, "source_account_id": "stocks"}],
        "income_streams": [{"id": "pay", "name": "Pay", "income_type": "salary", "annual_amount": 60_000,
                            "growth_rate": 0}],
        "expenses": [{"id": "trip", "name": "Trip", "annual_amount": 20_000, "inflation_linked": False,
                      "category": "discretionary"}],
        "spending_rules": rules,
    }


class TestSchemaOmission:
    def test_defaults_are_omitted_so_old_documents_keep_their_bytes(self):
        for model in (SpendingRules, SpendingRulesRequest):
            dumped = model(**LEGACY).model_dump(mode="json")
            assert not {"upside_thresholds", "flex_scope", "surplus_mode"} & set(dumped)
            assert model(**LEGACY).model_dump(exclude_unset=True) == model.model_validate(LEGACY).model_dump(
                exclude_unset=True)

    def test_new_settings_are_serialized_when_set(self):
        for model in (SpendingRules, SpendingRulesRequest):
            dumped = model(**NEW).model_dump(mode="json")
            assert dumped["surplus_mode"] == "spend_leftover"
            assert dumped["flex_scope"] == NEW["flex_scope"]
            assert dumped["upside_thresholds"] == NEW["upside_thresholds"]

    def test_surplus_only_document_is_valid_without_a_curve(self):
        assert SpendingRules(surplus_mode="spend_leftover").model_dump(mode="json")["surplus_mode"] == "spend_leftover"


BAD = [
    {"performance_mode": "all_time_high", "upside_thresholds": [{"threshold": float("inf"), "increase": 0.1}]},
    {"performance_mode": "all_time_high", "upside_thresholds": [{"threshold": 0.1, "increase": float("nan")}]},
    {"performance_mode": "all_time_high", "upside_thresholds": [{"threshold": 0.0, "increase": 0.1}]},
    {"performance_mode": "all_time_high", "upside_thresholds": [{"threshold": -0.1, "increase": 0.1}]},
    {"performance_mode": "all_time_high", "upside_thresholds": [{"threshold": 0.1, "increase": -0.1}]},
    {"performance_mode": "all_time_high", "upside_thresholds": [{"threshold": 0.1, "increase": 2.5}]},
    {"performance_mode": "all_time_high", "upside_thresholds": [{"threshold": 11, "increase": 0.1}]},
    {"performance_mode": "all_time_high", "upside_thresholds": [{"threshold": 0.1, "increase": 0.1}] * 2},
    {"performance_mode": "all_time_high",
     "upside_thresholds": [{"threshold": 0.01 * (i + 1), "increase": 0.1} for i in range(11)]},
    {"upside_thresholds": [{"threshold": 0.1, "increase": 0.1}]},  # trailing_return mode
    {"performance_mode": "all_time_high", "upside_thresholds": [{"threshold": 0.1, "increase": 0.1, "x": 1}]},
    {"flex_scope": []},
    {"flex_scope": ["expenses", "expenses"]},
    {"flex_scope": ["nonsense"]},
    {"flex_scope": ["leftover_spending"]},  # needs spend_leftover
    {"surplus_mode": "invest"},
]


class TestInvalidInputs:
    @pytest.mark.parametrize("rules", BAD)
    def test_models_reject(self, rules):
        for model in (SpendingRules, SpendingRulesRequest):
            with pytest.raises(ValueError):
                model(**rules)

    @pytest.mark.anyio
    @pytest.mark.parametrize("rules", [BAD[2], BAD[5], BAD[9], BAD[12], BAD[14], BAD[15]])
    async def test_saved_and_stateless_endpoints_reject(self, client, rules):
        response = await client.post("/api/plans", json={"name": "Bad", "birth_year": 1980, "spending_rules": rules})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        response = await client.post("/api/simulate/stateless", json=_stateless(rules))
        assert response.status_code == 422


@pytest.mark.anyio
async def test_saved_plan_round_trips_updates_and_copies(client):
    plan = await post(client, "/plans", {"name": "Flex", "birth_year": 1980, "spending_rules": LEGACY})
    assert plan["spending_rules"] == {**SpendingRules(**LEGACY).model_dump(mode="json")}
    assert "surplus_mode" not in plan["spending_rules"]

    updated = await client.put(f"/api/plans/{plan['id']}", json={"spending_rules": NEW})
    assert updated.status_code == 200, updated.text
    assert updated.json()["spending_rules"]["surplus_mode"] == "spend_leftover"
    fetched = (await client.get(f"/api/plans/{plan['id']}")).json()
    assert fetched["spending_rules"]["upside_thresholds"] == NEW["upside_thresholds"]
    assert fetched["spending_rules"]["flex_scope"] == NEW["flex_scope"]

    copied = await post(client, f"/plans/{plan['id']}/duplicate", {})
    assert copied["spending_rules"] == fetched["spending_rules"]

    # Going back to the defaults drops the keys again.
    reset = await client.put(f"/api/plans/{plan['id']}", json={"spending_rules": LEGACY})
    assert "surplus_mode" not in reset.json()["spending_rules"]


@pytest.mark.anyio
async def test_stateless_and_saved_simulations_spend_the_leftover(client):
    stateless = await client.post("/api/simulate/stateless", json=_stateless({"surplus_mode": "spend_leftover"}))
    assert stateless.status_code == 200, stateless.text
    rows = stateless.json()["yearly_snapshots"]
    assert rows[0]["leftover_spending"] == pytest.approx(40_000)
    assert all("flex_spending_increase" in row and "leftover_spending" in row for row in rows)

    saved = await client.post("/api/simulate/stateless", json=_stateless(None))
    assert saved.json()["yearly_snapshots"][0]["leftover_spending"] == 0
    # Saving keeps the 40,000 (and its growth); spending it leaves only the opening balance's growth.
    assert saved.json()["yearly_snapshots"][0]["net_worth"] > rows[0]["net_worth"] + 39_000

    plan = await post(client, "/plans", {"name": "Spend", "birth_year": 1980, "life_expectancy": 55,
                                         "spending_rules": {"surplus_mode": "spend_leftover"},
                                         "tax_settings": {"mode": "flat", "ordinary_income_tax_rate": 0,
                                                           "capital_gains_tax_rate": 0}})
    await post(client, f"/plans/{plan['id']}/accounts",
               {"name": "Stocks", "account_type": "taxable_brokerage", "balance": 100_000, "cost_basis": 100_000})
    await post(client, f"/plans/{plan['id']}/incomes",
               {"name": "Pay", "income_type": "salary", "annual_amount": 60_000, "growth_rate": 0})
    await post(client, f"/plans/{plan['id']}/expenses",
               {"name": "Trip", "annual_amount": 20_000, "inflation_linked": False, "category": "discretionary"})
    simulated = await client.post(f"/api/plans/{plan['id']}/simulate")
    assert simulated.status_code == 200, simulated.text
    rows = simulated.json()["yearly_snapshots"]
    # The saved plan starts mid-year, so the first year holds only a partial surplus.
    assert 0 < rows[0]["leftover_spending"] < 40_000
    assert rows[1]["leftover_spending"] == pytest.approx(40_000)

"""Federal bracket tax targets with custom and scheduled federal brackets.

Independent figures for a single filer aged 66 in 2026 with no other income:
$16,100 standard deduction (IRS Rev. Proc. 2025-32) + $2,050 additional
deduction at 65 (IRC 63(f)) + $6,000 senior deduction (IRC 151(d)(5)) =
$24,150 of deductions, so filling taxable income to T converts T + $24,150.
Built-in 12% bracket top: $50,400 of taxable income.
"""
import uuid
from dataclasses import replace

import pytest

from app.models.cash_flow_priority import CashFlowPriority
from app.models.plan import Plan
from app.schemas.plan import TaxSettings
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_strategy import build_candidates
from coastmath.engine.tax_target import bracket_target_top, plan_bracket_rates
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    PlanData,
    PriorityData,
)
from coastmath.engine.waterfall import ConversionTaxContext, bracket_fill_headroom
from coastmath.schemas.plan_data_request import TaxSettingsRequest
from coastmath.schemas.tax_target import bracket_ceiling_error, bracket_target_error
from tests.api_support import create_plan
from tests.engine_support import roth_converted

DEDUCTIONS = 24_150
TEN_TWENTY = [[50_000, .10], [1_000_000_000, .20]]
TEN_TWENTY_THIRTY = [[50_000, .10], [150_000, .20], [1_000_000_000, .30]]


def _target(rate):
    return {"kind": "federal_bracket", "bracket_rate": rate}


def _plan(settings, life_expectancy=67):
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000102", birth_year=1960, birth_month=1,
        life_expectancy=life_expectancy, start_year=2026, filing_status="single", state_code="FL",
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
                                   stock_dividend_yield=0),
        accounts={"cash": AccountInfo(100_000, "checking"),
                  "ira": AccountInfo(1_000_000, "traditional_ira"), "roth": AccountInfo(0, "roth_ira")},
        priorities=[PriorityData(1, priority_type="roth_conversion", source_account_id="ira",
                                 target_account_id="roth", use_plan_tax_target=True,
                                 conversion_mode="fill_bracket")],
        drawdown_order=[DrawdownEntryData(1, "cash")],
        tax_settings={"cash_flow_frequency": "annual", **settings},
    )


def _target_warnings(result):
    return [w for w in result.metadata.warnings if "tax target's" in w]


def test_custom_schedule_rate_fills_that_brackets_top():
    result = run_simulation(_plan({"federal_brackets": TEN_TWENTY_THIRTY, "tax_target": _target(.20)}))
    row = result.yearly_snapshots[0]
    assert row.tax_target_room == pytest.approx(150_000 + DEDUCTIONS, abs=.01)
    # The senior deduction phases out by 6% of MAGI above $75,000, so the
    # conversion x solves x = 150,000 + 18,150 + 6,000 - .06 (x - 75,000).
    assert roth_converted(row) == pytest.approx(178_650 / 1.06, abs=.05)
    assert _target_warnings(result) == []


def test_built_in_schedule_is_unchanged():
    row = run_simulation(_plan({"tax_target": _target(.12)})).yearly_snapshots[0]
    assert roth_converted(row) == pytest.approx(50_400 + DEDUCTIONS, abs=.05)


def test_saved_rate_missing_from_custom_schedule_fills_lower_brackets_and_warns():
    result = run_simulation(_plan({"federal_brackets": TEN_TWENTY, "tax_target": _target(.12)}))
    row = result.yearly_snapshots[0]
    # Only the 10% bracket is taxed at or below the saved 12%.
    assert row.tax_target_room == pytest.approx(50_000 + DEDUCTIONS, abs=.01)
    assert roth_converted(row) == pytest.approx(50_000 + DEDUCTIONS, abs=.05)
    assert row.federal_tax == pytest.approx(5_000, abs=.05)
    warnings = _target_warnings(result)
    assert len(warnings) == 1 and "12% federal bracket" in warnings[0] and "2026" in warnings[0]


def test_saved_rate_below_every_custom_bracket_allows_only_the_deductions():
    schedule = [[50_000, .15], [1_000_000_000, .25]]
    result = run_simulation(_plan({"federal_brackets": schedule, "tax_target": _target(.12)}))
    row = result.yearly_snapshots[0]
    assert roth_converted(row) == pytest.approx(DEDUCTIONS, abs=.05)
    assert row.federal_tax == pytest.approx(0, abs=.05)
    assert len(_target_warnings(result)) == 1


def test_scheduled_bracket_change_warns_only_for_the_years_it_lacks_the_rate():
    settings = {"tax_target": _target(.12),
                "scheduled_changes": [{"year": 2027, "settings": {"federal_brackets": TEN_TWENTY}},
                                      {"year": 2029, "settings": {"federal_brackets": []}}]}
    result = run_simulation(_plan(settings, life_expectancy=70))
    rows = {row.year: row for row in result.yearly_snapshots}
    assert rows[2026].tax_target_room == pytest.approx(50_400 + DEDUCTIONS, abs=.01)
    assert rows[2027].tax_target_room == pytest.approx(50_000 + DEDUCTIONS, abs=.01)
    # The senior deduction ends after 2028 (IRC 151(d)(5)).
    assert rows[2029].tax_target_room == pytest.approx(50_400 + DEDUCTIONS - 6_000, abs=.01)
    [warning] = _target_warnings(result)
    assert "2027–2028" in warning and "2026" not in warning and "2029" not in warning


def test_flat_mode_does_not_warn():
    result = run_simulation(_plan({"mode": "flat", "ordinary_income_tax_rate": .2,
                                   "federal_brackets": TEN_TWENTY, "tax_target": _target(.12)}))
    assert _target_warnings(result) == []


def test_bracket_target_top():
    assert bracket_target_top([(50_000, .1), (150_000, .2), (float("inf"), .3)], .2) == 150_000
    assert bracket_target_top([(50_000, .1), (150_000, .2), (float("inf"), .3)], .25) == 150_000
    assert bracket_target_top([(50_000, .15), (float("inf"), .25)], .12) == 0.0
    assert bracket_target_top([(50_000, .1), (float("inf"), .2)], .37) is None


def test_plan_bracket_rates_cover_custom_and_scheduled_schedules():
    assert plan_bracket_rates({}) == [.10, .12, .22, .24, .32, .35, .37]
    assert plan_bracket_rates({"federal_brackets": TEN_TWENTY}) == [.10, .20]
    scheduled = {"federal_brackets": TEN_TWENTY,
                 "scheduled_changes": [{"year": 2030, "settings": {"federal_brackets": []}},
                                       {"year": 2031, "settings": {"mode": "flat"}}]}
    assert plan_bracket_rates(scheduled) == [.10, .12, .20, .22, .24, .32, .35, .37]


def test_write_check_accepts_schedule_rates_and_reads_stay_tolerant():
    assert bracket_target_error({"federal_brackets": TEN_TWENTY, "tax_target": _target(.20)}) is None
    error = bracket_target_error({"federal_brackets": TEN_TWENTY, "tax_target": _target(.12)})
    assert error and "12%" in error and "10%, 20%" in error
    assert bracket_target_error({"tax_target": _target(.13)})
    assert bracket_target_error({"tax_target": {"kind": "magi", "amount": 1}}) is None
    # Saved settings read back whatever rate they hold. The stateless request
    # carries a locally stored plan, so it simulates a stale rate (with the
    # plan warning) instead of refusing to project it.
    for rate in (.12, .20):
        TaxSettings(federal_brackets=TEN_TWENTY, tax_target=_target(rate))
        TaxSettingsRequest(federal_brackets=TEN_TWENTY, tax_target=_target(rate))


def test_strategy_compare_candidates_use_the_plans_rates():
    plan = _plan({"federal_brackets": TEN_TWENTY_THIRTY})
    keys = [c.key for c in build_candidates(plan, source_account_id="ira", target_account_id="roth",
                                            bracket_ceilings=[.12, .20, .30], magi_cap=None,
                                            start_milestone_id=None, end_milestone_id=None)]
    assert keys == ["baseline", "fill_2000", "fill_3000"]
    built_in = build_candidates(replace(plan, tax_settings={}), source_account_id="ira", target_account_id="roth",
                                bracket_ceilings=[.12, .20], magi_cap=None,
                                start_milestone_id=None, end_milestone_id=None)
    assert [c.key for c in built_in] == ["baseline", "fill_1200"]


# --- API ---------------------------------------------------------------------

async def _api_plan(client):
    plan = await create_plan(client, name="Brackets", birth_year=1960, life_expectancy=80, filing_status="single")
    return plan["id"]


@pytest.mark.anyio
async def test_plan_write_validates_target_against_custom_brackets(client, db_session):
    pid = await _api_plan(client)
    saved = await client.put(f"/api/plans/{pid}", json={"tax_settings": {
        "federal_brackets": TEN_TWENTY, "tax_target": _target(.20)}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["tax_settings"]["tax_target"]["bracket_rate"] == .20

    rejected = await client.put(f"/api/plans/{pid}", json={"tax_settings": {
        "federal_brackets": TEN_TWENTY, "tax_target": _target(.12)}})
    assert rejected.status_code == 422
    error = rejected.json()["error"]
    assert error["code"] == "VALIDATION_ERROR" and "10%, 20%" in error["message"]
    assert error["details"][0]["field"] == "tax_settings.tax_target.bracket_rate"

    created = await client.post("/api/plans", json={"name": "Bad", "birth_year": 1960, "tax_settings": {
        "tax_target": _target(.20)}})
    assert created.status_code == 422 and created.json()["error"]["code"] == "VALIDATION_ERROR"

    # A target saved before its brackets changed still reads and simulates.
    plan = db_session.get(Plan, uuid.UUID(pid))
    plan.tax_settings = {"federal_brackets": TEN_TWENTY, "tax_target": _target(.12)}
    db_session.commit()
    read = await client.get(f"/api/plans/{pid}")
    assert read.status_code == 200 and read.json()["tax_settings"]["tax_target"]["bracket_rate"] == .12
    projected = await client.post(f"/api/plans/{pid}/simulate", headers={"X-Client-Date": "2026-01-01"})
    assert projected.status_code == 200, projected.text
    assert any("12% federal bracket" in w for w in projected.json()["metadata"]["warnings"])


@pytest.mark.anyio
async def test_strategy_search_accepts_only_the_plans_bracket_rates(client):
    pid = await _api_plan(client)
    ira = (await client.post("/api/accounts", json={"name": "IRA", "account_type": "traditional_ira",
                                                     "balance": 500_000})).json()
    roth = (await client.post("/api/accounts", json={"name": "Roth", "account_type": "roth_ira",
                                                      "balance": 0})).json()
    saved = await client.put(f"/api/plans/{pid}", json={"tax_settings": {"federal_brackets": TEN_TWENTY_THIRTY}})
    assert saved.status_code == 200, saved.text
    body = {"objective": "lifetime_taxes", "max_simulations": 4,
            "conversion": {"source_account_id": ira["id"], "target_account_id": roth["id"]}}

    ok = await client.post(f"/api/plans/{pid}/tax-strategies/search", json={**body, "bracket_rates": [.10, .20]})
    assert ok.status_code == 200, ok.text
    assert {c["bracket_rate"] for c in ok.json()["candidates"] if not c["is_baseline"]} == {.10, .20}

    bad = await client.post(f"/api/plans/{pid}/tax-strategies/search", json={**body, "bracket_rates": [.12]})
    assert bad.status_code == 422
    error = bad.json()["error"]
    assert error["code"] == "VALIDATION_ERROR" and error["details"][0]["field"] == "bracket_rates[0]"


# --- Roth conversion rules with their own bracket ceiling --------------------

def _rule_plan(settings, rate, life_expectancy=67):
    plan = _plan(settings, life_expectancy)
    plan.accounts["ira"].name = "IRA"
    plan.accounts["roth"].name = "Roth"
    return replace(plan, priorities=[PriorityData(
        1, priority_type="roth_conversion", source_account_id="ira", target_account_id="roth",
        conversion_mode="fill_bracket", bracket_ceiling_rate=rate)])


def _rule_warnings(result):
    return [w for w in result.metadata.warnings if "conversion rule's" in w]


def test_rule_ceiling_in_custom_schedule_fills_that_brackets_top():
    result = run_simulation(_rule_plan({"federal_brackets": TEN_TWENTY_THIRTY}, .20))
    # Same solve as the plan target: x = 150,000 + 24,150 - .06 (x - 75,000).
    assert roth_converted(result.yearly_snapshots[0]) == pytest.approx(178_650 / 1.06, abs=.05)
    assert _rule_warnings(result) == []


def test_rule_ceiling_top_of_unbounded_custom_bracket_is_not_blocked():
    row = run_simulation(_rule_plan({"federal_brackets": TEN_TWENTY}, .20)).yearly_snapshots[0]
    # The 20% bracket has no practical top; cash to pay the tax is the limit.
    assert roth_converted(row) > 200_000


def test_rule_ceiling_missing_from_custom_schedule_fills_lower_brackets_and_warns():
    result = run_simulation(_rule_plan({"federal_brackets": TEN_TWENTY}, .12, life_expectancy=68))
    for row in result.yearly_snapshots:
        assert roth_converted(row) == pytest.approx(50_000 + DEDUCTIONS, abs=.05)
        assert row.federal_tax == pytest.approx(5_000, abs=.05)
    [warning] = _rule_warnings(result)
    assert warning.startswith("The IRA to Roth conversion rule's 12% federal bracket")
    assert "2026–2027" in warning
    assert _target_warnings(result) == []


def test_rule_ceiling_on_built_in_brackets_is_unchanged():
    result = run_simulation(_rule_plan({}, .12))
    assert roth_converted(result.yearly_snapshots[0]) == pytest.approx(50_400 + DEDUCTIONS, abs=.05)
    assert _rule_warnings(result) == []


def test_bracket_fill_headroom_uses_bracket_target_semantics():
    context = ConversionTaxContext(ordinary_taxable_income=10_000, modified_agi=30_000,
                                   brackets=[(50_000, .10), (float("inf"), .20)], unused_deduction=0)
    assert bracket_fill_headroom(context, .10) == 40_000
    assert bracket_fill_headroom(context, .12) == 40_000
    assert bracket_fill_headroom(context, .20) == float("inf")
    assert bracket_fill_headroom(replace(context, brackets=[(50_000, .15), (float("inf"), .25)]), .12) == 0.0


def test_gain_harvest_ceiling_uses_capital_gains_brackets_not_custom_ordinary_ones():
    def harvested(settings):
        plan = _plan(settings)
        plan.accounts["brokerage"] = AccountInfo(500_000, "taxable_brokerage", cost_basis=100_000)
        plan = replace(plan, priorities=[PriorityData(
            1, priority_type="gain_harvest", source_account_id="brokerage",
            conversion_mode="fill_bracket", bracket_ceiling_rate=.0)])
        result = run_simulation(plan)
        return result.yearly_snapshots[0].harvested_gains, result.metadata.warnings

    built_in, _ = harvested({})
    custom, warnings = harvested({"federal_brackets": TEN_TWENTY})
    assert built_in > 0 and custom == pytest.approx(built_in, abs=.01)
    assert not any("federal bracket" in w for w in warnings)


def test_rule_ceiling_write_check():
    assert bracket_ceiling_error({"federal_brackets": TEN_TWENTY}, .20) is None
    assert bracket_ceiling_error({}, .22) is None
    error = bracket_ceiling_error({"federal_brackets": TEN_TWENTY}, .12)
    assert error and "12%" in error and "10%, 20%" in error


@pytest.mark.anyio
async def test_rule_write_validates_ceiling_against_custom_brackets(client, db_session):
    pid = await _api_plan(client)
    ira = (await client.post("/api/accounts", json={"name": "IRA", "account_type": "traditional_ira",
                                                     "balance": 500_000})).json()
    roth = (await client.post("/api/accounts", json={"name": "Roth", "account_type": "roth_ira",
                                                      "balance": 0})).json()
    saved = await client.put(f"/api/plans/{pid}", json={"tax_settings": {"federal_brackets": TEN_TWENTY}})
    assert saved.status_code == 200, saved.text

    def rule(rate, **extra):
        return {"priority_rank": 1, "priority_type": "roth_conversion", "source_account_id": ira["id"],
                "target_account_id": roth["id"], "conversion_mode": "fill_bracket",
                "bracket_ceiling_rate": rate, **extra}

    async def save(items):
        revision = (await client.get(f"/api/plans/{pid}/priorities")).json()["revision"]
        return await client.put(f"/api/plans/{pid}/priorities", json={"expected_revision": revision, "items": items})

    rejected = await save([rule(.12)])
    assert rejected.status_code == 422
    error = rejected.json()["error"]
    assert error["code"] == "VALIDATION_ERROR" and "10%, 20%" in error["message"]
    assert error["details"][0]["field"] == "bracket_ceiling_rate"
    assert (await client.get(f"/api/plans/{pid}/priorities")).json()["items"] == []

    accepted = await save([rule(.20)])
    assert accepted.status_code == 200, accepted.text

    # A rule saved before the brackets changed: the brackets can still change,
    # the rule reads back and simulates with a warning, and it can be saved
    # again unchanged; changing it requires a rate in the plan's brackets.
    db_session.query(CashFlowPriority).filter(CashFlowPriority.plan_id == uuid.UUID(pid)).update(
        {"bracket_ceiling_rate": .12})
    db_session.commit()
    changed = await client.put(f"/api/plans/{pid}", json={"tax_settings": {
        "federal_brackets": [[60_000, .10], [1_000_000_000, .20]]}})
    assert changed.status_code == 200, changed.text
    items = (await client.get(f"/api/plans/{pid}/priorities")).json()["items"]
    assert items[0]["bracket_ceiling_rate"] == .12
    projected = await client.post(f"/api/plans/{pid}/simulate", headers={"X-Client-Date": "2026-01-01"})
    assert projected.status_code == 200, projected.text
    assert any("IRA to Roth conversion rule's 12% federal bracket" in w
               for w in projected.json()["metadata"]["warnings"])
    unchanged = await save([rule(.12)])
    assert unchanged.status_code == 200, unchanged.text
    edited = await save([rule(.12, max_annual_amount=10_000)])
    assert edited.status_code == 422


@pytest.mark.anyio
async def test_stateless_request_simulates_a_stale_rule_ceiling_with_its_warning(client):
    body = {
        "plan_id": "00000000-0000-4000-8000-000000000103", "birth_year": 1960, "birth_month": 1,
        "start_year": 2026, "first_year_fraction": 1.0, "life_expectancy": 67, "filing_status": "single",
        "state_code": "FL",
        "accounts": {"cash": {"balance": 100_000, "account_type": "checking", "name": "Cash"},
                     "ira": {"balance": 1_000_000, "account_type": "traditional_ira", "name": "IRA"},
                     "roth": {"balance": 0, "account_type": "roth_ira", "name": "Roth"}},
        "priorities": [{"priority_rank": 1, "priority_type": "roth_conversion", "source_account_id": "ira",
                        "target_account_id": "roth", "conversion_mode": "fill_bracket",
                        "bracket_ceiling_rate": .12}],
        "tax_settings": {"federal_brackets": TEN_TWENTY},
    }
    r = await client.post("/api/simulate/stateless", json=body)
    assert r.status_code == 200, r.text
    assert any("IRA to Roth conversion rule's 12% federal bracket" in w for w in r.json()["metadata"]["warnings"])

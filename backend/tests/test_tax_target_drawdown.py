"""Plan tax target: drawdown blending and target-sized conversions/harvests.

Independent 2026 single-filer figures (IRS Rev. Proc. 2025-32): $16,100
standard deduction; the 12% ordinary bracket tops out at $50,400 of taxable
income, so $66,500 of ordinary income with no other income fills it. IRC
1411(b) NIIT threshold: $200,000 (single). IRMAA 2026 first boundary:
$109,000 (single), CMS 2026 Part B fact sheet. 2025 HHS poverty guideline for
one person in the contiguous states (used for 2026 coverage): $15,650.
"""
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.schemas.cash_flow_priority import CashFlowPriorityCreate
from coastmath.engine.healthcare import (
    _irmaa_tier,
    applicable_percentage,
    irmaa_threshold,
    poverty_line,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_target import FIT_TOLERANCE, parse_tax_target, year_tax_target
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    PlanData,
    PriorityData,
)
from tests.corrected_fixture_support import engine_request
from tests.engine_support import roth_converted

FILL_12 = {"kind": "federal_bracket", "bracket_rate": .12}
ZERO_GROWTH = AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
                             stock_dividend_yield=0)


def _plan(target=FILL_12, blend=True, **changes):
    settings = {"cash_flow_frequency": "annual"}
    if target is not None:
        settings["tax_target"] = target
    if blend:
        settings["blend_drawdown_to_tax_target"] = True
    options = dict(
        plan_id="00000000-0000-0000-0000-000000000001", birth_year=1964, start_year=2026,
        life_expectancy=63, filing_status="single", state_code="FL",
        accounts={"broker": AccountInfo(500_000, "taxable_brokerage", cost_basis=500_000),
                  "ira": AccountInfo(500_000, "traditional_ira"),
                  "roth": AccountInfo(0, "roth_ira")},
        drawdown_order=[DrawdownEntryData(1, "broker"), DrawdownEntryData(2, "ira"),
                        DrawdownEntryData(3, "roth")],
        expenses=[ExpenseData("living", "Living", 80_000)],
        assumptions=ZERO_GROWTH, tax_settings=settings)
    options.update(changes)
    return PlanData(**options)


def _drawn(row, account_id):
    return sum(d.amount for d in row.cash_flow.drawdowns if d.account_id == account_id)


def test_blending_fills_the_bracket_from_the_ira_before_a_taxable_first_order():
    row = run_simulation(_plan()).yearly_snapshots[0]
    assert _drawn(row, "ira") == pytest.approx(66_500, abs=.05)
    assert row.tax_target_blended_withdrawals == pytest.approx(66_500, abs=.05)
    assert row.tax_target_room == pytest.approx(66_500, abs=.01)
    # 10% of 12,400 + 12% of 38,000. The rest of spending and the tax follow
    # the order (the all-basis brokerage account).
    assert row.federal_tax == pytest.approx(5_800, abs=.05)
    assert _drawn(row, "broker") == pytest.approx(80_000 - 66_500 + 5_800, abs=.1)
    assert row.unfunded_expenses == 0

    baseline = run_simulation(_plan(blend=False)).yearly_snapshots[0]
    assert _drawn(baseline, "ira") == 0
    assert baseline.federal_tax == 0
    assert baseline.tax_target_blended_withdrawals == 0


def test_blending_takes_only_the_need_when_it_is_below_the_room():
    row = run_simulation(_plan(expenses=[ExpenseData("living", "Living", 40_000)])).yearly_snapshots[0]
    assert _drawn(row, "ira") == pytest.approx(40_000, abs=.05)
    # 10% of 12,400 + 12% of 11,500; paid from the brokerage account.
    assert row.federal_tax == pytest.approx(2_620, abs=.05)
    assert _drawn(row, "broker") == pytest.approx(2_620, abs=.05)


def test_taxable_gain_counts_against_the_room():
    accounts = {"broker": AccountInfo(500_000, "taxable_brokerage", cost_basis=250_000),
                "ira": AccountInfo(500_000, "traditional_ira"), "roth": AccountInfo(0, "roth_ira")}
    row = run_simulation(_plan(accounts=accounts,
                               expenses=[ExpenseData("living", "Living", 150_000)])).yearly_snapshots[0]
    # Half of each sale is gain: 0.5 * 133,000 - 16,100 = 50,400 taxable.
    assert row.tax_target_blended_withdrawals == pytest.approx(133_000, abs=.1)
    # The room is used, so the IRA is not drawn; the remainder follows the order.
    assert _drawn(row, "ira") == 0
    assert _drawn(row, "broker") > 150_000


def test_remainder_follows_the_saved_order():
    accounts = {"cash": AccountInfo(200_000, "checking"), "ira": AccountInfo(500_000, "traditional_ira"),
                "savings": AccountInfo(100_000, "savings"), "roth": AccountInfo(100_000, "roth_ira")}
    order = [DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "roth"), DrawdownEntryData(3, "ira"),
             DrawdownEntryData(4, "savings")]
    row = run_simulation(_plan(accounts=accounts, drawdown_order=order)).yearly_snapshots[0]
    assert _drawn(row, "ira") == pytest.approx(66_500, abs=.05)
    # Cash and Roth are skipped by the first pass; the remainder and the tax
    # come from cash, first in the order.
    assert _drawn(row, "cash") == pytest.approx(80_000 - 66_500 + 5_800, abs=.1)
    assert _drawn(row, "roth") == 0
    assert _drawn(row, "savings") == 0


def test_early_withdrawal_penalty_accounts_are_skipped():
    plan = _plan(birth_year=1976, life_expectancy=51)
    row = run_simulation(plan).yearly_snapshots[0]
    assert row.tax_target_blended_withdrawals == 0
    assert _drawn(row, "ira") == 0
    baseline = run_simulation(_plan(blend=False, birth_year=1976, life_expectancy=51)).yearly_snapshots[0]
    assert row.net_worth == baseline.net_worth


def test_locked_accounts_are_skipped():
    accounts = {"broker": AccountInfo(500_000, "taxable_brokerage", cost_basis=500_000),
                "ira": AccountInfo(500_000, "traditional_ira",
                                   withdrawal_lock={"unlock": "year", "year": 2030}),
                "roth": AccountInfo(0, "roth_ira")}
    row = run_simulation(_plan(accounts=accounts)).yearly_snapshots[0]
    assert row.tax_target_blended_withdrawals == 0
    assert _drawn(row, "ira") == 0


def test_niit_ceiling_caps_blended_withdrawals():
    target = {"kind": "taxable_income", "amount": 1_000_000, "avoid_niit": True}
    row = run_simulation(_plan(target=target,
                               expenses=[ExpenseData("living", "Living", 300_000)])).yearly_snapshots[0]
    assert row.tax_target_room == pytest.approx(200_000, abs=.01)
    assert _drawn(row, "ira") == pytest.approx(200_000, abs=.05)


def test_irmaa_ceiling_uses_thresholds_for_the_premium_year():
    inflating = AssumptionData(inflation_rate=.03, stock_growth_rate=0, bond_return_rate=0,
                               stock_dividend_yield=0)
    plan = _plan(target={"kind": "irmaa_tier", "irmaa_tier": 1}, birth_year=1963, life_expectancy=64,
                 expenses=[], assumptions=inflating)
    row = run_simulation(plan).yearly_snapshots[0]
    # 2026 income sets 2028 premiums: the 2028 boundary is two years indexed,
    # 109,000 * 1.03 ** 2 = 115,638.10, so the last whole dollar in the lower
    # tier is 115,638.
    assert row.tax_target_room == pytest.approx(115_638 - FIT_TOLERANCE, abs=1e-6)
    # Nobody reaches Medicare age by the premium year: no IRMAA limit applies.
    young = run_simulation(replace(plan, birth_year=1970, life_expectancy=57)).yearly_snapshots[0]
    assert young.tax_target_room is None


def test_irmaa_tier_threshold_for_higher_tiers_and_frozen_top():
    target = parse_tax_target({"tax_target": {"kind": "irmaa_tier", "irmaa_tier": 5}})
    limits = year_tax_target(target, filing_status="single", year=2025, flat_tax=False,
                             federal_brackets=[], inflation_factor=1.0, irmaa_inflation_factor=1.1,
                             irmaa_applies=True)
    # The top boundary ($500,000) is frozen through 2027 (premium year 2027).
    # MAGI at the boundary is already in the top tier, so the most that fits
    # (the limit plus the fit tolerance) is the last whole dollar below it.
    assert limits.limits == {"irmaa_magi": 499_999 - FIT_TOLERANCE}
    limits = year_tax_target(target, filing_status="single", year=2026, flat_tax=False,
                             federal_brackets=[], inflation_factor=1.0, irmaa_inflation_factor=1.1,
                             irmaa_applies=True)
    # 500,000 * 1.1 is 550,000.0000000001 in floating point; 550,000 is still top tier.
    assert limits.limits["irmaa_magi"] == pytest.approx(549_999 - FIT_TOLERANCE, abs=1e-6)


@pytest.mark.parametrize(("tier", "status", "lived_apart", "expected"), [
    # CMS 2026 Part B fact sheet: lower ranges are "less than or equal to"
    # their bound; the top range is "greater than or equal to" its bound.
    (1, "single", False, 109_000), (4, "single", False, 205_000), (5, "single", False, 499_999),
    (1, "married_filing_jointly", False, 218_000), (5, "married_filing_jointly", False, 749_999),
    (1, "married_filing_separately", False, 109_000), (2, "married_filing_separately", False, 390_999),
    (5, "married_filing_separately", True, 499_999),
])
def test_irmaa_threshold_is_the_last_whole_dollar_in_the_lower_tier(tier, status, lived_apart, expected):
    # Form 1040 lets figures round to whole dollars: $499,999.99 can be
    # reported as $500,000, so target boundaries are whole dollars.
    highest = irmaa_threshold(tier, status, 2027, 1.0, lived_apart)
    assert highest == expected
    below = _irmaa_tier(highest, status, 2027, 1.0, lived_apart)[0]
    above = _irmaa_tier(highest + 1, status, 2027, 1.0, lived_apart)[0]
    assert below < above
    # Indexed boundaries keep the same inclusivity, in whole dollars.
    indexed = irmaa_threshold(tier, status, 2029, 1.0312, lived_apart)
    assert indexed == int(indexed)
    assert _irmaa_tier(indexed, status, 2029, 1.0312, lived_apart)[0] < _irmaa_tier(
        indexed + 1, status, 2029, 1.0312, lived_apart)[0]


def test_irmaa_threshold_ignores_float_noise_in_an_indexed_bound():
    # 500,000 * 1.04 ** 2 is 540,800 exactly but computes as 540,800.0000000001;
    # $540,800 is in the top tier, so the last whole dollar below it is 540,799.
    factor = 1.04 ** 2
    assert 500_000 * factor > 540_800
    assert irmaa_threshold(5, "single", 2030, factor) == 540_799
    # An inclusive bound of 112,400.80 (109,000 x 1.0312) keeps 112,400.
    assert irmaa_threshold(1, "single", 2030, 1.0312) == 112_400
    # An inclusive bound that is exactly whole stays whole: 109,000 x 1.05 = 114,450.
    assert irmaa_threshold(1, "single", 2030, 1.05) == 114_450


def test_irmaa_top_tier_target_keeps_magi_below_the_inclusive_boundary():
    medicare = {"enabled": True, "medicare_enabled": True, "medicare_part_b": True, "medicare_part_d": True}
    plan = _plan(target={"kind": "irmaa_tier", "irmaa_tier": 5}, blend=False, birth_year=1956,
                 life_expectancy=74, expenses=[], healthcare_settings=medicare,
                 priorities=[PriorityData(1, priority_type="roth_conversion", source_account_id="ira",
                                          target_account_id="roth", conversion_mode="fixed",
                                          use_plan_tax_target=True, max_annual_amount=1_000_000)])
    rows = {row.year: row for row in run_simulation(plan).yearly_snapshots}
    assert 499_998.99 <= roth_converted(rows[2026]) <= 499_999
    # 2026 MAGI sets 2028 premiums: tier 4 ($446.30 Part B, $83.30 Part D a
    # month in 2026 dollars), not the top tier.
    health = rows[2028].healthcare
    assert health.medicare_tier == 4
    assert health.medicare_irmaa_part_b == pytest.approx(446.30 * 12, abs=.01)
    assert health.medicare_irmaa_part_d == pytest.approx(83.30 * 12, abs=.01)


def test_aca_poverty_line_ceiling_applies_only_in_aca_years():
    target = {"kind": "magi", "amount": 500_000, "aca_cap_fpl_percent": 200}
    aca = {"enabled": True, "aca_enabled": True, "medicare_enabled": False,
           "aca_benchmark_premium_annual": 9_000, "aca_plan_premium_annual": 9_000,
           "magi_prior_year": 30_000, "aca_apply_age_curve": False}
    covered = run_simulation(_plan(target=target, expenses=[], healthcare_settings=aca)).yearly_snapshots[0]
    assert covered.tax_target_room == pytest.approx(2 * 15_650, abs=.01)
    uncovered = run_simulation(_plan(target=target, expenses=[])).yearly_snapshots[0]
    assert uncovered.tax_target_room == pytest.approx(500_000, abs=.01)
    # A poverty-line target alone has nothing to bound outside ACA years.
    fpl_only = run_simulation(_plan(target={"kind": "aca_fpl_percent", "aca_fpl_percent": 400},
                                    expenses=[])).yearly_snapshots[0]
    assert fpl_only.tax_target_room is None


def _conversion(**changes):
    return PriorityData(1, priority_type="roth_conversion", source_account_id="ira", target_account_id="roth",
                        conversion_mode="fill_bracket", **changes)


@pytest.mark.parametrize("accounts,order", [
    ({"ira": AccountInfo(100_000, "traditional_ira"), "roth": AccountInfo(0, "roth_ira"),
      "broker": AccountInfo(100_000, "taxable_brokerage", cost_basis=100_000)},
     [DrawdownEntryData(1, "broker")]),
    ({"ira": AccountInfo(100_000, "traditional_ira"), "roth": AccountInfo(0, "roth_ira")},
     [DrawdownEntryData(1, "ira")]),
])
def test_conversion_with_plan_target_equals_the_bracket_rule(accounts, order):
    common = dict(accounts=accounts, drawdown_order=order, expenses=[], birth_year=1966, life_expectancy=61)
    by_rule = run_simulation(_plan(target=None, blend=False, priorities=[_conversion(bracket_ceiling_rate=.12)],
                                   **common)).yearly_snapshots[0]
    by_target = run_simulation(_plan(blend=False, priorities=[_conversion(use_plan_tax_target=True)],
                                     **common)).yearly_snapshots[0]
    assert roth_converted(by_rule) > 0
    assert roth_converted(by_target) == pytest.approx(roth_converted(by_rule), abs=.05)
    assert by_target.federal_tax == pytest.approx(by_rule.federal_tax, abs=.05)
    assert by_target.net_worth == pytest.approx(by_rule.net_worth, abs=.05)


def test_conversion_with_plan_target_and_no_target_converts_nothing():
    plan = _plan(target=None, blend=False, expenses=[],
                 priorities=[_conversion(use_plan_tax_target=True)])
    assert roth_converted(run_simulation(plan).yearly_snapshots[0]) == 0


def test_harvest_conversion_and_drawdown_share_the_room():
    accounts = {"cash": AccountInfo(100_000, "checking"),
                "broker": AccountInfo(100_000, "taxable_brokerage", cost_basis=80_000),
                "ira": AccountInfo(500_000, "traditional_ira"), "roth": AccountInfo(0, "roth_ira")}
    harvest = PriorityData(1, priority_type="gain_harvest", source_account_id="broker",
                           conversion_mode="fill_bracket", use_plan_tax_target=True)
    conversion = replace(_conversion(use_plan_tax_target=True), priority_rank=2)
    plan = _plan(accounts=accounts, drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "ira")],
                 expenses=[ExpenseData("living", "Living", 30_000)], priorities=[harvest, conversion])
    row = run_simulation(plan).yearly_snapshots[0]
    # Order of operations: the harvest (20,000 gain), then the blended IRA
    # draw for spending (30,000), then the conversion takes what is left:
    # 20,000 + 30,000 + x - 16,100 = 50,400 total taxable income.
    assert row.harvested_gains == pytest.approx(20_000, abs=.01)
    assert _drawn(row, "ira") == pytest.approx(30_000, abs=.05)
    assert roth_converted(row) == pytest.approx(16_500, abs=.05)


def test_flag_off_or_no_target_matches_baseline():
    baseline = run_simulation(_plan(target=None, blend=False))
    for plan in (_plan(blend=False), _plan(target=None, blend=True)):
        result = run_simulation(plan)
        for row, base in zip(result.yearly_snapshots, baseline.yearly_snapshots, strict=True):
            assert row.net_worth == base.net_worth
            assert row.taxes == base.taxes
            assert row.accounts == base.accounts
            assert row.tax_target_blended_withdrawals == 0


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

TARGET = {"kind": "federal_bracket", "bracket_rate": .12, "amount": None, "irmaa_tier": None,
          "aca_fpl_percent": None, "avoid_niit": True, "avoid_irmaa": False, "aca_cap_fpl_percent": None}


@pytest.mark.anyio
async def test_tax_target_and_rule_flag_round_trip(client):
    created = await client.post("/api/plans", json={
        "name": "Target", "birth_year": 1964,
        "tax_settings": {"tax_target": {"kind": "federal_bracket", "bracket_rate": .12, "avoid_niit": True},
                         "blend_drawdown_to_tax_target": True}})
    assert created.status_code == 201, created.text
    plan = created.json()
    url = f"/api/plans/{plan['id']}"
    read = (await client.get(url)).json()["tax_settings"]
    assert read["tax_target"] == TARGET and read["blend_drawdown_to_tax_target"] is True

    ira = (await client.post("/api/accounts", json={"name": "IRA", "account_type": "traditional_ira",
                                                     "balance": 100_000})).json()
    roth = (await client.post("/api/accounts", json={"name": "Roth", "account_type": "roth_ira",
                                                      "balance": 0})).json()
    revision = (await client.get(f"{url}/priorities")).json()["revision"]
    rule = {"priority_rank": 1, "priority_type": "roth_conversion", "source_account_id": ira["id"],
            "target_account_id": roth["id"], "conversion_mode": "fill_bracket", "use_plan_tax_target": True}
    saved = await client.put(f"{url}/priorities", json={"expected_revision": revision, "items": [rule]})
    assert saved.status_code == 200, saved.text
    item = (await client.get(f"{url}/priorities")).json()["items"][0]
    assert item["use_plan_tax_target"] is True and item["bracket_ceiling_rate"] is None

    snapshots = (await client.post(f"{url}/simulate")).json()["yearly_snapshots"]
    assert snapshots[0]["tax_target_room"] > 0

    updated = await client.put(url, json={"tax_settings": {**read, "tax_target": None,
                                                           "blend_drawdown_to_tax_target": False}})
    assert updated.status_code == 200, updated.text
    cleared = (await client.get(url)).json()["tax_settings"]
    assert "tax_target" not in cleared and "blend_drawdown_to_tax_target" not in cleared
    snapshot = (await client.post(f"{url}/simulate")).json()["yearly_snapshots"][0]
    assert snapshot["tax_target_room"] is None and snapshot["tax_target_blended_withdrawals"] == 0


@pytest.mark.anyio
async def test_plans_without_a_target_read_unchanged(client):
    created = await client.post("/api/plans", json={"name": "Plain", "birth_year": 1980,
                                                    "tax_settings": {"settlement_lag_years": 0}})
    assert created.status_code == 201
    settings = created.json()["tax_settings"]
    assert "tax_target" not in settings and "blend_drawdown_to_tax_target" not in settings


@pytest.mark.anyio
async def test_stateless_request_accepts_the_target(client):
    body = engine_request(_plan()).model_dump(mode="json")
    response = await client.post("/api/simulate/stateless", json=body)
    assert response.status_code == 200, response.text
    row = response.json()["yearly_snapshots"][0]
    assert row["tax_target_blended_withdrawals"] == pytest.approx(66_500, abs=.05)


@pytest.mark.anyio
@pytest.mark.parametrize("bad", [
    {"kind": "federal_bracket"},
    {"kind": "federal_bracket", "bracket_rate": .13},
    {"kind": "magi"},
    {"kind": "irmaa_tier", "irmaa_tier": 0},
    {"kind": "aca_fpl_percent", "aca_fpl_percent": -1},
    {"kind": "surprise"},
    {"kind": "magi", "amount": 1, "extra": True},
])
async def test_invalid_target_uses_the_shared_error_envelope(client, bad):
    response = await client.post("/api/plans", json={"name": "Bad", "birth_year": 1980,
                                                     "tax_settings": {"tax_target": bad}})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR" and error["details"]


def test_rule_flag_validation():
    source = "00000000-0000-0000-0000-000000000009"
    harvest = CashFlowPriorityCreate(priority_rank=1, priority_type="gain_harvest", source_account_id=source,
                                     conversion_mode="fill_bracket", use_plan_tax_target=True)
    assert harvest.bracket_ceiling_rate is None
    with pytest.raises(ValidationError):
        CashFlowPriorityCreate(priority_rank=1, priority_type="roth_conversion", source_account_id=source,
                               conversion_mode="fixed", use_plan_tax_target=True)
    with pytest.raises(ValidationError):
        CashFlowPriorityCreate(priority_rank=1, priority_type="contribution", use_plan_tax_target=True)


def test_aca_poverty_line_caps_are_whole_dollars_at_or_below_the_cliff():
    # 26 U.S.C. 36B(c)(1)(A): household income that "does not exceed 400
    # percent" of the poverty line qualifies. 15,650 x 1.0312 x 4 = 64,553.12,
    # and a whole-dollar MAGI rounded up past it would lose the whole credit.
    line = poverty_line(1, "contiguous", 1.0312)
    for target in ({"kind": "aca_fpl_percent", "aca_fpl_percent": 400},
                   {"kind": "magi", "amount": 1_000_000, "aca_cap_fpl_percent": 400}):
        limits = year_tax_target(parse_tax_target({"tax_target": target}), filing_status="single", year=2026,
                                 flat_tax=False, federal_brackets=[], inflation_factor=1.0,
                                 irmaa_inflation_factor=1.0, irmaa_applies=False, aca_poverty_line=line)
        assert limits.limits["aca_magi"] == pytest.approx(64_553 - FIT_TOLERANCE, abs=1e-9)
        # The most a fit allows keeps the credit.
        assert applicable_percentage((limits.limits["aca_magi"] + FIT_TOLERANCE) / line) is not None
    # A cap that is already a whole dollar stays put: 15,650 x 2 = 31,300.
    limits = year_tax_target(parse_tax_target({"tax_target": {"kind": "aca_fpl_percent", "aca_fpl_percent": 200}}),
                             filing_status="single", year=2026, flat_tax=False, federal_brackets=[],
                             inflation_factor=1.0, irmaa_inflation_factor=1.0, irmaa_applies=False,
                             aca_poverty_line=15_650)
    assert limits.limits["aca_magi"] == 31_300 - FIT_TOLERANCE


def test_niit_ceiling_is_the_statutory_threshold():
    # NIIT applies only to MAGI in excess of the threshold (26 U.S.C.
    # 1411(a)(1)), so MAGI at $200,000 owes none: no cliff, no whole-dollar step.
    limits = year_tax_target(parse_tax_target({"tax_target": {"kind": "magi", "amount": 1_000_000,
                                                               "avoid_niit": True}}),
                             filing_status="single", year=2026, flat_tax=False, federal_brackets=[],
                             inflation_factor=1.0, irmaa_inflation_factor=1.0, irmaa_applies=False)
    assert limits.limits["niit_magi"] == 200_000

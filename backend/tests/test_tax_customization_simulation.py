"""Tax adjustments and scheduled tax changes in the projection loop.

Independent 2026 single-filer figures (IRS Rev. Proc. 2025-32): $16,100
standard deduction and $50,400 top of the 12% bracket, so a 12% bracket fill
with no other income converts $66,500; each extra dollar of deduction adds one
dollar of conversion room.
"""
from copy import deepcopy

import pytest

from coastmath.engine.monte_carlo import run_monte_carlo
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
)
from tests.engine_support import roth_converted


def _credit(amount, **changes):
    return {"id": "c1", "kind": "credit", "scope": "federal", "amount": amount, "amount_basis": "nominal",
            "frequency": "annual", **changes}


def _worker(**changes) -> PlanData:
    options = dict(
        plan_id="00000000-0000-0000-0000-0000000000a1", birth_year=1970, start_year=2026,
        life_expectancy=66, filing_status="single", state_code="GA",
        income_streams=[IncomeData("salary", "Salary", 100_000, growth_rate=0.0, withholding_percent=.2)],
        accounts={"cash": AccountInfo(50_000, "checking")},
        milestones=[MilestoneData("retire", "Retire", "age", trigger_value=60)],
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
                                   stock_dividend_yield=0),
        tax_settings={"cash_flow_frequency": "annual"},
    )
    options.update(changes)
    return PlanData(**options)


def _rows(plan):
    return {row.year: row for row in run_simulation(plan).yearly_snapshots}


def test_empty_customization_keeps_results_identical():
    base = run_simulation(_worker()).model_dump()
    empty = run_simulation(_worker(tax_settings={"cash_flow_frequency": "annual", "adjustments": [],
                                                 "scheduled_changes": [], "state_deduction_rules": False}))
    assert empty.model_dump() == base


def test_refundable_credit_is_paid_through_settlement_as_cash():
    base = _rows(_worker())
    credited = _rows(_worker(tax_settings={"cash_flow_frequency": "annual", "adjustments": [
        _credit(1_000, refundable=True, frequency="once", start_year=2027)]}))
    assert credited[2027].tax_adjustment_credits == pytest.approx(1_000)
    assert credited[2027].taxes == pytest.approx(base[2027].taxes - 1_000, abs=.01)
    assert credited[2027].net_worth == pytest.approx(base[2027].net_worth + 1_000, abs=.01)
    # A one-time credit applies once; later years match except the carried cash.
    assert credited[2028].tax_adjustment_credits == 0
    assert credited[2028].taxes == pytest.approx(base[2028].taxes, abs=.01)
    assert credited[2026].taxes == pytest.approx(base[2026].taxes, abs=.01)


def test_todays_dollars_follow_plan_inflation():
    plan = _worker(assumptions=AssumptionData(inflation_rate=.03, stock_growth_rate=0, bond_return_rate=0,
                                              stock_dividend_yield=0),
                   tax_settings={"cash_flow_frequency": "annual", "adjustments": [
                       _credit(1_000, amount_basis="today", end_year=2028)]})
    rows = _rows(plan)
    assert rows[2026].tax_adjustment_credits == pytest.approx(1_000)
    assert rows[2028].tax_adjustment_credits == pytest.approx(1_000 * 1.03 ** 2)
    assert rows[2029].tax_adjustment_credits == 0


def test_milestone_schedule_switches_to_flat_tax_from_the_milestone_year():
    schedule = {"cash_flow_frequency": "annual", "scheduled_changes": [
        {"milestone_id": "retire", "settings": {"mode": "flat", "ordinary_income_tax_rate": .1}}]}
    base = _rows(_worker())
    rows = _rows(_worker(tax_settings=schedule))
    assert rows[2029].taxes == pytest.approx(base[2029].taxes)
    assert rows[2029].state_tax > 0
    assert rows[2030].state_tax == 0
    assert rows[2030].taxes == pytest.approx(.1 * 100_000, abs=.01)
    assert rows[2031].taxes == pytest.approx(.1 * 100_000, abs=.01)
    # A schedule keyed to a milestone missing from the plan never applies.
    missing = deepcopy(schedule)
    missing["scheduled_changes"][0]["milestone_id"] = "not-in-plan"
    assert run_simulation(_worker(tax_settings=missing)).yearly_snapshots == \
        run_simulation(_worker()).yearly_snapshots


def test_schedule_and_adjustments_never_mutate_plan_input_and_replay_deterministically():
    settings = {"cash_flow_frequency": "annual", "adjustments": [_credit(500)], "scheduled_changes": [
        {"year": 2028, "settings": {"adjustments": [_credit(900, id="c2")], "state_brackets": [[999_999_999, .01]]}},
        {"milestone_id": "retire", "settings": {"state_brackets": []}}]}
    plan = _worker(tax_settings=settings)
    before = deepcopy(settings)
    first = run_simulation(plan)
    second = run_simulation(plan)
    assert plan.tax_settings == before
    assert first.yearly_snapshots == second.yearly_snapshots
    rows = {row.year: row for row in first.yearly_snapshots}
    assert rows[2027].tax_adjustment_credits == pytest.approx(500)
    assert rows[2028].tax_adjustment_credits == pytest.approx(900)
    # Custom brackets keep Georgia's $15,000 single standard deduction.
    assert rows[2028].state_tax == pytest.approx(.01 * (100_000 - 15_000), abs=.01)
    assert rows[2030].state_tax == pytest.approx(base_state := _rows(_worker())[2030].state_tax) and base_state > 1_000


def test_monte_carlo_trials_do_not_leak_settings():
    settings = {"cash_flow_frequency": "annual", "adjustments": [_credit(500)], "scheduled_changes": [
        {"milestone_id": "retire", "settings": {"mode": "flat", "ordinary_income_tax_rate": .1}}]}
    plan = _worker(tax_settings=settings, accounts={"cash": AccountInfo(50_000, "checking"),
                                                    "broker": AccountInfo(200_000, "taxable_brokerage",
                                                                          cost_basis=200_000)})
    before = deepcopy(settings)
    one = run_monte_carlo(plan, n_trials=6, seed=7, max_workers=1)
    two = run_monte_carlo(plan, n_trials=6, seed=7, max_workers=1)
    assert plan.tax_settings == before
    assert one.model_dump() == two.model_dump()


def test_spouse_item_ends_after_the_spouse_death_year():
    plan = _worker(filing_status="married_filing_jointly", spouse_birth_year=1970, spouse_life_expectancy=60,
                   tax_settings={"cash_flow_frequency": "annual", "adjustments": [
                       _credit(700, owner="spouse"), _credit(300, id="c2", owner="self")]})
    rows = _rows(plan)
    assert rows[2030].tax_adjustment_credits == pytest.approx(1_000)
    assert rows[2031].tax_adjustment_credits == pytest.approx(300)


def _conversion_plan(**changes) -> PlanData:
    options = dict(
        plan_id="00000000-0000-0000-0000-0000000000a2", birth_year=1966, start_year=2026,
        life_expectancy=61, filing_status="single", state_code="FL",
        accounts={"ira": AccountInfo(100_000, "traditional_ira"), "roth": AccountInfo(0, "roth_ira"),
                  "broker": AccountInfo(100_000, "taxable_brokerage", cost_basis=100_000)},
        priorities=[PriorityData(1, priority_type="roth_conversion", source_account_id="ira",
                                 target_account_id="roth", conversion_mode="fill_bracket",
                                 bracket_ceiling_rate=.12)],
        drawdown_order=[DrawdownEntryData(1, "broker"), DrawdownEntryData(2, "ira"), DrawdownEntryData(3, "roth")],
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0),
        tax_settings={"cash_flow_frequency": "annual"},
    )
    options.update(changes)
    return PlanData(**options)


@pytest.mark.parametrize("deduction_type, amount, room", [
    ("above_the_line", 10_000, 10_000),
    # Itemizing replaces the $16,100 standard deduction.
    ("itemized", 30_000, 30_000 - 16_100),
])
def test_bracket_fill_conversion_sizes_on_the_same_adjusted_tax(deduction_type, amount, room):
    base = run_simulation(_conversion_plan()).yearly_snapshots[0]
    assert roth_converted(base) == pytest.approx(66_500, abs=.01)
    adjusted = run_simulation(_conversion_plan(tax_settings={"cash_flow_frequency": "annual", "adjustments": [{
        "id": "d", "kind": "deduction", "deduction_type": deduction_type, "scope": "both", "amount": amount,
        "amount_basis": "nominal", "frequency": "once"}]})).yearly_snapshots[0]
    assert roth_converted(adjusted) == pytest.approx(66_500 + room, abs=.05)
    # The final settled federal tax is the full 10%/12% bracket stack.
    assert adjusted.federal_tax == pytest.approx(base.federal_tax, abs=.05)


def test_plan_tax_target_conversion_uses_the_same_adjusted_tax():
    target = {"kind": "federal_bracket", "bracket_rate": .12}
    rule = PriorityData(1, priority_type="roth_conversion", source_account_id="ira", target_account_id="roth",
                        conversion_mode="fixed", use_plan_tax_target=True, max_annual_amount=1_000_000)
    base = run_simulation(_conversion_plan(priorities=[rule], tax_settings={
        "cash_flow_frequency": "annual", "tax_target": target})).yearly_snapshots[0]
    adjusted = run_simulation(_conversion_plan(priorities=[rule], tax_settings={
        "cash_flow_frequency": "annual", "tax_target": target, "adjustments": [{
            "id": "d", "kind": "deduction", "deduction_type": "above_the_line", "scope": "federal",
            "amount": 8_000, "amount_basis": "nominal", "frequency": "annual"}]})).yearly_snapshots[0]
    assert roth_converted(adjusted) == pytest.approx(roth_converted(base) + 8_000, abs=1)


def test_withholding_and_previews_share_the_scheduled_year_settings():
    # A flat rate scheduled from 2027 with a year key: the conversion context,
    # settlement and the snapshot all switch in the same year.
    plan = _conversion_plan(life_expectancy=63, tax_settings={"cash_flow_frequency": "annual", "scheduled_changes": [
        {"year": 2027, "settings": {"mode": "flat", "ordinary_income_tax_rate": .2}}]})
    rows = {row.year: row for row in run_simulation(plan).yearly_snapshots}
    base = {row.year: row for row in run_simulation(_conversion_plan(life_expectancy=63)).yearly_snapshots}
    assert roth_converted(rows[2026]) == pytest.approx(roth_converted(base[2026]))
    assert rows[2026].taxes == pytest.approx(base[2026].taxes)
    assert rows[2027].state_tax == 0
    assert rows[2027].taxes == pytest.approx(.2 * roth_converted(rows[2027]), abs=1)

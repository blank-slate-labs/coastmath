"""Strategy candidates are credited only with what they add to the plan's own rules."""

from coastmath.engine.tax_strategy import build_candidates, compare_strategies
from coastmath.engine.types import (
    AccountInfo,
    DrawdownEntryData,
    ExpenseData,
    PlanData,
    PriorityData,
)


def _plan(priorities) -> PlanData:
    return PlanData(
        plan_id="00000000-0000-0000-0000-0000000000b3", birth_year=1980, filing_status="single",
        life_expectancy=90, start_year=2026,
        accounts={"cash": AccountInfo(100_000, "checking"), "k": AccountInfo(700_000, "traditional_401k"),
                  "roth": AccountInfo(90_000, "roth_ira")},
        expenses=[ExpenseData("living", "Living", 40_000)],
        drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "k")],
        priorities=priorities,
    )


def _compare(plan, magi_cap=None):
    candidates = build_candidates(plan, source_account_id="k", target_account_id="roth",
                                  bracket_ceilings=[0.12, 0.22, 0.24], magi_cap=magi_cap,
                                  start_milestone_id=None, end_milestone_id=None)
    return {m.key: m for m in compare_strategies(plan, candidates, "net_legacy").candidates}


def test_existing_conversion_rule_is_not_credited_to_candidates():
    existing = PriorityData(priority_rank=1, priority_type="roth_conversion", source_account_id="k",
                            target_account_id="roth", conversion_mode="fill_bracket", bracket_ceiling_rate=0.22)
    with_rule = _compare(_plan([existing]), magi_cap=30_000)
    # The saved rule already fills the 22% bracket; a $30,000-capped candidate adds nothing.
    for key in ("fill_1200", "fill_2200", "fill_2400"):
        assert with_rule[key].total_converted == 0
        assert with_rule[key].conversion_years == 0
        assert with_rule[key].notes

    uncapped = _compare(_plan([existing]))
    assert uncapped["fill_2200"].total_converted == 0
    assert uncapped["fill_2400"].total_converted > 0


def test_candidates_without_existing_rule_report_their_own_moves():
    plain = _compare(_plan([]))
    capped = _compare(_plan([]), magi_cap=30_000)
    assert 0 < plain["fill_1200"].total_converted < plain["fill_2200"].total_converted
    assert 0 < capped["fill_1200"].total_converted < plain["fill_1200"].total_converted

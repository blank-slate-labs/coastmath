"""Bounded staged strategy search: measures, candidate construction, staging and ranking."""

import copy
import itertools
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from coastmath.engine import tax_strategy_search as search
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_strategy import (
    OBJECTIVES,
    build_candidates,
    compare_strategies,
    measure_result,
    objective_direction,
    pre_tax_discount,
)
from coastmath.engine.tax_strategy_search import (
    SearchSpace,
    SearchWindow,
    StrategySpec,
    materialize,
    normalize,
    rank_key,
    reorder_drawdown,
    run_search,
)
from coastmath.engine.types import (
    AccountInfo,
    DrawdownEntryData,
    ExpenseData,
    MilestoneData,
    PlanData,
    PriorityData,
)


def _plan(order=None, **overrides) -> PlanData:
    """Pre-tax-heavy single filer: drawing the IRA first leaves bracket headroom to use."""
    data = dict(
        plan_id="00000000-0000-0000-0000-0000000000b2", birth_year=1966, filing_status="single",
        life_expectancy=90, start_year=2026,
        milestones=[MilestoneData("m65", "Age 65", "age", 65), MilestoneData("m70", "Age 70", "age", 70)],
        accounts={
            "cash": AccountInfo(100_000, "checking", name="Cash"),
            "ira": AccountInfo(1_500_000, "traditional_ira", name="IRA"),
            "roth": AccountInfo(50_000, "roth_ira", name="Roth"),
            "brk": AccountInfo(600_000, "taxable_brokerage", cost_basis=200_000, name="Brokerage"),
        },
        expenses=[ExpenseData("living", "Living", 90_000)],
        drawdown_order=order or [DrawdownEntryData(1, "ira"), DrawdownEntryData(2, "cash"),
                                 DrawdownEntryData(3, "brk"), DrawdownEntryData(4, "roth")],
    )
    data.update(overrides)
    return PlanData(**data)


CONVERT = dict(conversion_source_id="ira", conversion_target_id="roth")
HARVEST = dict(harvest_source_id="brk")
WINDOW = SearchWindow("Age 65 to 70", "m65", "m70")


def _space(**overrides) -> SearchSpace:
    base = dict(objective="net_legacy", bracket_rates=(0.12, 0.22), max_simulations=128)
    base.update(overrides)
    return SearchSpace(**base)


def _snap(taxes=0.0, rate=0.0, gross=0.0, calendar=None, healthcare=None, rmd=None):
    flow = None
    if rmd is not None:
        flow = SimpleNamespace(income_sources=[SimpleNamespace(source="rmd", amount=rmd),
                                               SimpleNamespace(source="salary", amount=999.0)])
    return SimpleNamespace(taxes=taxes, effective_rate=rate, gross_income=gross, calendar_year_gross_income=calendar,
                           healthcare=healthcare, cash_flow=flow, net_worth=1_000.0)


def _health(aca=0.0, part_b=0.0, part_d=0.0, total=0.0):
    return SimpleNamespace(aca_credit=aca, medicare_irmaa_part_b=part_b, medicare_irmaa_part_d=part_d, total=total)


def _result(snaps, legacy=None):
    return SimpleNamespace(yearly_snapshots=snaps, metadata=SimpleNamespace(net_legacy=legacy))


# --- objectives ---------------------------------------------------------------

def test_objective_measures_are_dollar_sums_not_year_counts():
    snaps = [
        _snap(taxes=10, rate=0.10, healthcare=_health(aca=1_200, part_b=300, part_d=50, total=5), rmd=7_000),
        _snap(taxes=90, rate=0.30, healthcare=_health(aca=800, part_b=0, part_d=25, total=7), rmd=11_000),
        _snap(taxes=0, healthcare=None, rmd=None),
    ]
    m = measure_result(_result(snaps), 0.24)
    assert m.lifetime_taxes == 100
    assert m.lifetime_healthcare == 12
    assert m.total_aca_subsidies == 2_000
    assert m.total_irmaa_surcharge == 375
    assert m.total_rmd_distributions == 18_000
    values = m.objective_values()
    assert values["total_aca_subsidies"] == 2_000 and values["total_irmaa_surcharge"] == 375
    assert values["total_rmd_distributions"] == 18_000 and values["lifetime_taxes"] == 100
    assert values["lifetime_taxes_and_healthcare"] == 112
    assert set(values) == set(OBJECTIVES)


def test_lifetime_effective_rate_weights_each_year_by_its_income():
    # 10 tax at 10% (income 100) and 90 tax at 30% (income 300): 100 / 400, not the 20% mean of rates.
    m = measure_result(_result([_snap(taxes=10, rate=0.10), _snap(taxes=90, rate=0.30)]), 0.24)
    assert m.lifetime_income == pytest.approx(400)
    assert m.lifetime_effective_tax_rate == pytest.approx(0.25)


def test_lifetime_effective_rate_falls_back_to_gross_income_and_is_zero_without_income():
    fallback = measure_result(_result([_snap(taxes=0, gross=0, calendar=50_000), _snap(taxes=5_000, gross=100_000)]), 0.24)
    assert fallback.lifetime_effective_tax_rate == pytest.approx(5_000 / 150_000)
    none = measure_result(_result([_snap(taxes=0), _snap(taxes=0)]), 0.24)
    assert none.lifetime_income == 0 and none.lifetime_effective_tax_rate == 0.0
    assert measure_result(_result([]), 0.24).lifetime_effective_tax_rate == 0.0


def test_objective_direction_covers_every_objective():
    assert {o for o in OBJECTIVES if objective_direction(o) == "higher"} == {
        "net_legacy", "final_net_worth", "total_aca_subsidies"}
    assert objective_direction("total_rmd_distributions") == "lower"
    with pytest.raises(ValueError):
        objective_direction("vibes")


def test_measures_match_a_real_projection():
    plan = _plan()
    result = run_simulation(copy.deepcopy(plan))
    m = measure_result(result, 0.24)
    assert m.lifetime_taxes == pytest.approx(sum(s.taxes for s in result.yearly_snapshots))
    rmds = sum(i.amount for s in result.yearly_snapshots if s.cash_flow for i in s.cash_flow.income_sources if i.source == "rmd")
    assert rmds > 0 and m.total_rmd_distributions == pytest.approx(rmds)
    assert 0 < m.lifetime_effective_tax_rate < 1
    assert m.objective_values()["net_legacy"] == pytest.approx(
        result.metadata.net_legacy.net_legacy - pre_tax_discount(result, 0.24))


# --- drawdown presets ---------------------------------------------------------

def test_reorder_groups_accounts_keeps_ranks_and_saved_order_within_groups():
    plan = _plan(order=[DrawdownEntryData(2, "ira"), DrawdownEntryData(5, "roth"), DrawdownEntryData(7, "brk"),
                        DrawdownEntryData(9, "cash")])
    ids = lambda preset: [(e.rank, e.source_account_id) for e in reorder_drawdown(plan, preset)]  # noqa: E731
    assert ids("saved") == [(2, "ira"), (5, "roth"), (7, "brk"), (9, "cash")]
    # Cash and taxable keep their saved relative order (brokerage before cash).
    assert ids("taxable_first") == [(2, "brk"), (5, "cash"), (7, "ira"), (9, "roth")]
    assert ids("pretax_first") == [(2, "ira"), (5, "brk"), (7, "cash"), (9, "roth")]
    assert ids("roth_before_pretax") == [(2, "brk"), (5, "cash"), (7, "roth"), (9, "ira")]


def test_reorder_leaves_the_saved_entries_untouched_and_unknown_accounts_last():
    plan = _plan(order=[DrawdownEntryData(1, "ghost"), DrawdownEntryData(2, "roth"), DrawdownEntryData(3, "ira")])
    before = copy.deepcopy(plan.drawdown_order)
    reordered = reorder_drawdown(plan, "pretax_first")
    assert plan.drawdown_order == before
    assert [e.source_account_id for e in reordered] == ["ira", "roth", "ghost"]


# --- candidate construction ---------------------------------------------------

def test_materialize_adds_rules_after_existing_ones_and_discloses_each_change():
    existing = PriorityData(priority_rank=3, priority_type="transfer", source_account_id="cash", target_account_id="roth",
                            max_annual_amount=1_000.0)
    plan = _plan(priorities=[existing], tax_settings={"tax_target": {"kind": "magi", "amount": 90_000.0},
                                                       "other": 1})
    space = _space(**CONVERT, **HARVEST, allow_blend=True, windows=(WINDOW,))
    before = asdict(plan)
    scenario = materialize(plan, space, StrategySpec(actions=("conversion", "harvest", "blend"), rate=0.22,
                                                     order="pretax_first", window=0))
    assert asdict(plan) == before  # the input plan is a value, never edited
    priorities = scenario.plan.priorities
    assert priorities[0] == existing  # saved rules stay, in place
    assert [p.priority_rank for p in priorities] == [3, 4, 5]
    convert, harvest = priorities[1:]
    assert (convert.priority_type, convert.source_account_id, convert.target_account_id) == ("roth_conversion", "ira", "roth")
    assert (harvest.priority_type, harvest.source_account_id, harvest.target_account_id) == ("gain_harvest", "brk", None)
    for rule in (convert, harvest):
        assert rule.conversion_mode == "fill_bracket" and rule.use_plan_tax_target
        assert (rule.start_milestone_id, rule.end_milestone_id) == ("m65", "m70")
    settings = scenario.plan.tax_settings
    assert settings["tax_target"] == {"kind": "federal_bracket", "bracket_rate": 0.22}
    assert settings["blend_drawdown_to_tax_target"] is True and settings["other"] == 1
    assert [(c.kind, c.target) for c in scenario.changes] == [
        ("add", "priority"), ("add", "priority"), ("replace", "tax_target"), ("replace", "blend_drawdown"),
        ("replace", "drawdown_order")]
    replaced = next(c for c in scenario.changes if c.target == "tax_target")
    assert replaced.before == {"kind": "magi", "amount": 90_000.0} and "replaces the saved target" in replaced.summary
    assert scenario.proposal["tax_settings"] == {"tax_target": settings["tax_target"], "blend_drawdown_to_tax_target": True}
    assert [e["source_account_id"] for e in scenario.proposal["drawdown_order"]] == ["ira", "cash", "brk", "roth"]
    assert len(scenario.proposal["priorities_to_add"]) == 2


def test_year_window_adds_its_milestones_and_matches_the_same_milestone_window():
    # Born January 1966: age 65 and 70 fall in 2031 and 2036, so ages 65 through
    # 69 and the years 2031 through 2035 are the same window.
    years = SearchWindow("2031 through 2035", "strategy-window-1-start", "strategy-window-1-end", milestones=(
        MilestoneData("strategy-window-1-start", "Start of 2031", "date", trigger_date="2031-01-01"),
        MilestoneData("strategy-window-1-end", "Start of 2036", "date", trigger_date="2036-01-01"),
    ))
    plan = _plan(birth_month=1)
    space = _space(**CONVERT, windows=(WINDOW, years))
    scenario = materialize(plan, space, StrategySpec(actions=("conversion",), rate=0.22, window=1))
    assert [m.id for m in scenario.plan.milestones] == ["m65", "m70", "strategy-window-1-start", "strategy-window-1-end"]
    assert [m.id for m in plan.milestones] == ["m65", "m70"]
    assert [(c.kind, c.target) for c in scenario.changes][:2] == [("add", "milestone"), ("add", "milestone")]
    assert scenario.proposal["milestones_to_add"] == [
        {"id": "strategy-window-1-start", "name": "Start of 2031", "trigger_type": "date",
         "trigger_value": None, "trigger_date": "2031-01-01"},
        {"id": "strategy-window-1-end", "name": "Start of 2036", "trigger_type": "date",
         "trigger_value": None, "trigger_date": "2036-01-01"},
    ]
    rule = scenario.proposal["priorities_to_add"][0]
    assert (rule["start_milestone_id"], rule["end_milestone_id"]) == ("strategy-window-1-start", "strategy-window-1-end")
    # A spec without an action ignores the window and adds no milestone.
    assert materialize(plan, space, StrategySpec(order="pretax_first")).proposal["milestones_to_add"] == []
    out = run_search(plan, _space(**CONVERT, bracket_rates=(0.22,), windows=(WINDOW, years)))
    by_key = {c.key: c for c in out.candidates}
    assert by_key["conversion@2200/saved/w2"].total_converted > 0
    assert by_key["conversion@2200/saved/w2"].total_converted == pytest.approx(
        by_key["conversion@2200/saved/w1"].total_converted)


def test_materialize_keeps_saved_extra_ceilings_and_skips_unchanged_settings():
    target = {"kind": "federal_bracket", "bracket_rate": 0.22, "avoid_niit": True, "amount": None}
    plan = _plan(tax_settings={"tax_target": target, "blend_drawdown_to_tax_target": True})
    space = _space(allow_blend=True)
    same = materialize(plan, space, StrategySpec(actions=("blend",), rate=0.22))
    assert same.changes == [] and same.proposal["tax_settings"] is None
    other = materialize(plan, space, StrategySpec(actions=("blend",), rate=0.12))
    assert other.plan.tax_settings["tax_target"] == {"kind": "federal_bracket", "bracket_rate": 0.12, "avoid_niit": True}
    assert [c.target for c in other.changes] == ["tax_target"]


def test_materialize_handles_a_plan_without_tax_settings():
    plan = _plan(tax_settings=None)
    scenario = materialize(plan, _space(**CONVERT), StrategySpec(actions=("conversion",), rate=0.12))
    assert plan.tax_settings is None
    assert scenario.plan.tax_settings == {"tax_target": {"kind": "federal_bracket", "bracket_rate": 0.12}}
    assert scenario.changes[1].kind == "add"


def test_normalize_drops_settings_that_cannot_change_the_run():
    plan = _plan()
    space = _space(**CONVERT, allow_blend=True, windows=(WINDOW,))
    assert normalize(plan, space, StrategySpec(rate=0.22, window=0)) == StrategySpec()
    assert normalize(plan, space, StrategySpec(actions=("blend",), rate=0.22, window=0)).window is None
    assert normalize(plan, space, StrategySpec(actions=("conversion",), rate=0.22, window=0)).window == 0
    # A preset that reproduces the saved order is the saved order.
    saved_like = _plan(order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "brk"), DrawdownEntryData(3, "ira")])
    assert normalize(saved_like, space, StrategySpec(order="taxable_first")).order == "saved"
    assert normalize(saved_like, space, StrategySpec(order="pretax_first")).order == "pretax_first"


# --- the search ---------------------------------------------------------------

def _objective(plan: PlanData) -> float:
    result = run_simulation(plan)
    return result.metadata.net_legacy.net_legacy - 0.24 * result.metadata.net_legacy.pretax_balance


_ORDERS = {
    "saved": ["ira", "cash", "brk", "roth"],
    "taxable_first": ["cash", "brk", "ira", "roth"],
    "pretax_first": ["ira", "cash", "brk", "roth"],
    "roth_before_pretax": ["cash", "brk", "roth", "ira"],
}


def _independent_value(plan, actions, rate, order_ids, window=None):
    """Build the scenario by hand, without the search module's materializer."""
    priorities = list(plan.priorities)
    start, end = window or (None, None)
    if "conversion" in actions:
        priorities.append(PriorityData(priority_rank=len(priorities) + 1, priority_type="roth_conversion",
                                       source_account_id="ira", target_account_id="roth", conversion_mode="fill_bracket",
                                       use_plan_tax_target=True, start_milestone_id=start, end_milestone_id=end))
    if "harvest" in actions:
        priorities.append(PriorityData(priority_rank=len(priorities) + 1, priority_type="gain_harvest",
                                       source_account_id="brk", conversion_mode="fill_bracket",
                                       use_plan_tax_target=True, start_milestone_id=start, end_milestone_id=end))
    settings = dict(plan.tax_settings or {})
    if actions:
        settings["tax_target"] = {"kind": "federal_bracket", "bracket_rate": rate}
    if "blend" in actions:
        settings["blend_drawdown_to_tax_target"] = True
    order = [DrawdownEntryData(i + 1, account) for i, account in enumerate(order_ids)]
    return _objective(replace(copy.deepcopy(plan), priorities=priorities, tax_settings=settings or None, drawdown_order=order))


def test_two_rate_staged_search_matches_an_independent_exhaustive_grid():
    plan = _plan()
    space = _space(**CONVERT, **HARVEST, allow_blend=True, order_presets=("pretax_first", "roth_before_pretax"))
    out = run_search(plan, space)
    # Two rates: the best rate's neighbours are the other rate, so nothing is left out.
    assert out.survivor_rates == [0.12, 0.22] and not out.counts.budget_exhausted
    assert out.counts.skipped_by_budget == 0 and out.counts.screened_out == 0
    assert out.counts.simulated == out.counts.grid_size
    grid = {}
    subsets = [c for n in range(1, 4) for c in itertools.combinations(("conversion", "harvest", "blend"), n)]
    for rate in (0.12, 0.22):
        for subset in subsets:
            for preset in ("saved", "pretax_first", "roth_before_pretax"):
                grid[(subset, rate, preset)] = _independent_value(plan, subset, rate, _ORDERS[preset])
    for preset in ("pretax_first", "roth_before_pretax"):
        grid[((), None, preset)] = _independent_value(plan, (), None, _ORDERS[preset])
    grid[((), None, "saved")] = _objective(copy.deepcopy(plan))
    by_spec = {(c.spec.actions, c.spec.rate, c.spec.order): c for c in out.candidates if c.spec.window is None}
    for spec, value in grid.items():
        if spec in by_spec:  # only distinct, simulated candidates are listed
            assert by_spec[spec].objective_value == pytest.approx(value, rel=1e-9)
    best_independent = max(grid.values())
    best = next(c for c in out.candidates if c.key == out.best_key)
    assert best.objective_value == pytest.approx(best_independent, rel=1e-9)
    assert best.objective_value >= max(c.objective_value for c in out.candidates) - 0.005


def test_best_is_the_best_evaluated_not_a_better_unsearched_candidate():
    """With a tiny budget the best result may sit below an unsearched grid point."""
    plan = _plan()
    space = _space(**CONVERT, **HARVEST, allow_blend=True, order_presets=("pretax_first", "roth_before_pretax"),
                   max_simulations=5)
    out = run_search(plan, space)
    assert out.counts.simulated == 5 and out.counts.budget_exhausted and out.counts.skipped_by_budget > 0
    assert len(out.candidates) == 5
    assert out.best_key == out.candidates[0].key
    assert max(c.objective_value for c in out.candidates if c.success) == out.candidates[0].objective_value
    assert any("not simulated" in c for c in out.caveats)
    assert any("not a global optimum" in c for c in out.caveats)


def test_survivors_are_the_best_rate_and_its_neighbours_and_go_first():
    plan = _plan()
    rates = (0.10, 0.12, 0.22, 0.24, 0.32)
    space = _space(**CONVERT, bracket_rates=rates, order_presets=("pretax_first",), windows=(WINDOW,))
    out = run_search(plan, space)
    scan = [c for c in out.candidates if c.stage == "rate_scan"]
    assert sorted(c.spec.rate for c in scan) == sorted(rates)
    values = {c.spec.rate: round(c.objective_value, 2) for c in scan}
    tied = [r for r in rates if values[r] == max(values.values())]
    expected = {r for t in tied for r in rates[max(0, rates.index(t) - 1): rates.index(t) + 2]}
    assert out.survivor_rates == sorted(expected)
    # With budget to spare the other rates are searched too.
    combos = [c for c in out.candidates if c.stage == "combination" and c.spec.actions]
    assert {c.spec.rate for c in combos} == set(rates)
    assert not out.counts.budget_exhausted and out.counts.simulated == out.counts.grid_size
    assert out.counts.skipped_by_budget == out.counts.screened_out == 0

    # A budget that ends among the survivors' simpler candidates leaves the other rates out, counted.
    small = run_search(plan, replace(space, max_simulations=out.counts.stage1_simulated + 3))
    combos = [c for c in small.candidates if c.stage == "combination" and c.spec.actions]
    assert combos and {c.spec.rate for c in combos} <= set(small.survivor_rates)
    assert small.counts.budget_exhausted and small.counts.screened_out > 0
    assert small.counts.grid_size == small.counts.simulated + small.counts.skipped_by_budget + small.counts.screened_out


def test_rates_outside_the_survivors_are_searched_while_budget_remains():
    """The scan ranks rates with every action on, but one action alone can do
    best at another rate: here conversions alone win at 22%, two steps above
    the surviving 10% and 12%."""
    space = _space(objective="lifetime_effective_tax_rate", **CONVERT, **HARVEST,
                   bracket_rates=(0.10, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37), order_presets=("pretax_first",),
                   windows=(WINDOW,))
    out = run_search(_plan(), space)
    assert out.survivor_rates == [0.10, 0.12]
    assert out.counts.simulated == out.counts.grid_size and not out.counts.budget_exhausted
    best = next(c for c in out.candidates if c.key == out.best_key)
    assert (best.spec.actions, best.spec.rate) == (("conversion",), 0.22)


def test_a_tie_for_best_rate_keeps_every_tied_rate_and_their_neighbours():
    plan = _plan()
    # Rates this high add no headroom for this plan's income: the scan values tie exactly.
    out = run_search(plan, _space(**CONVERT, bracket_rates=(0.24, 0.32, 0.35, 0.37)))
    values = {c.spec.rate: round(c.objective_value, 2) for c in out.candidates if c.stage == "rate_scan"}
    top = max(values.values())
    tied = [r for r, v in values.items() if v == top]
    expected = set()
    rates = sorted(values)
    for r in tied:
        i = rates.index(r)
        expected.update(rates[max(0, i - 1): i + 2])
    assert out.survivor_rates == sorted(expected)


def test_baseline_is_always_simulated_listed_and_wins_ties_over_no_op_changes():
    plan = _plan()
    out = run_search(plan, _space(objective="lifetime_taxes", **CONVERT, bracket_rates=(0.12,)))
    baseline = next(c for c in out.candidates if c.is_baseline)
    assert baseline.key == "baseline" and baseline.stage == "baseline" and baseline.changes == []
    assert baseline.delta_vs_baseline == 0 and not baseline.improves_baseline
    # A conversion that finds no headroom matches the baseline to the cent and ranks after it.
    noop = next(c for c in out.candidates if c.key.startswith("conversion@1200"))
    assert round(noop.objective_value, 2) == round(baseline.objective_value, 2)
    assert baseline.rank < noop.rank and not noop.improves_baseline
    assert any("did nothing" in n for n in noop.notes)


def test_rank_is_deterministic_and_independent_of_request_order():
    plan = _plan()
    first = run_search(plan, _space(**CONVERT, **HARVEST, bracket_rates=(0.12, 0.22, 0.24),
                                    order_presets=("pretax_first", "roth_before_pretax")))
    shuffled = run_search(plan, _space(**HARVEST, **CONVERT, bracket_rates=(0.24, 0.12, 0.22),
                                       order_presets=("roth_before_pretax", "pretax_first")))
    again = run_search(copy.deepcopy(plan), _space(**CONVERT, **HARVEST, bracket_rates=(0.12, 0.22, 0.24),
                                                   order_presets=("pretax_first", "roth_before_pretax")))
    ranking = lambda out: [(c.rank, c.key, c.objective_value) for c in out.candidates]  # noqa: E731
    assert ranking(first) == ranking(shuffled) == ranking(again)
    assert [c.rank for c in first.candidates] == list(range(1, len(first.candidates) + 1))
    assert first.best_key == shuffled.best_key


def _fake(key, value, success=True, changes=0, rate=None):
    return SimpleNamespace(key=key, objective_value=value, success=success, changes=[None] * changes,
                           spec=StrategySpec(rate=rate))


def test_rank_key_ties_within_a_cent_then_prefers_fewer_changes_then_key():
    ranked = sorted([_fake("c", 100.004, changes=2), _fake("a", 100.0, changes=3), _fake("b", 100.0, changes=2),
                     _fake("z", 100.004, changes=2)], key=lambda c: rank_key("lifetime_taxes", c))
    assert [c.key for c in ranked] == ["b", "c", "z", "a"]
    # Higher-is-better objectives order the other way round; tiny rates tie only at 1e-8.
    ranked = sorted([_fake("lo", 5.0), _fake("hi", 9.0)], key=lambda c: rank_key("net_legacy", c))
    assert [c.key for c in ranked] == ["hi", "lo"]
    ranked = sorted([_fake("x", 0.10000000004), _fake("y", 0.1, changes=1)], key=lambda c: rank_key("lifetime_effective_tax_rate", c))
    assert [c.key for c in ranked] == ["x", "y"]
    ranked = sorted([_fake("x", 0.1001), _fake("y", 0.1, changes=1)], key=lambda c: rank_key("lifetime_effective_tax_rate", c))
    assert [c.key for c in ranked] == ["y", "x"]


def test_infeasible_outcomes_rank_after_feasible_ones_whatever_their_objective():
    ranked = sorted([_fake("bad", 1e9, success=False), _fake("ok", 1.0)], key=lambda c: rank_key("net_legacy", c))
    assert [c.key for c in ranked] == ["ok", "bad"]
    ranked = sorted([_fake("bad", -1e9, success=False), _fake("ok", 1.0)], key=lambda c: rank_key("lifetime_taxes", c))
    assert [c.key for c in ranked] == ["ok", "bad"]


def test_a_plan_that_fails_everywhere_has_no_best_candidate():
    broke = _plan(accounts={"cash": AccountInfo(10_000, "checking", name="Cash"),
                            "ira": AccountInfo(60_000, "traditional_ira", name="IRA"),
                            "roth": AccountInfo(0, "roth_ira", name="Roth")},
                  drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "ira")],
                  expenses=[ExpenseData("living", "Living", 90_000)])
    out = run_search(broke, _space(**CONVERT, bracket_rates=(0.12, 0.22)))
    assert all(not c.success and c.failure_year for c in out.candidates)
    assert out.best_key is None
    assert any(f"fails in {c.failure_year}" in n for c in out.candidates for n in c.notes)


def test_each_dimension_changes_the_simulation():
    plan = _plan()
    out = run_search(plan, _space(objective="lifetime_taxes", **CONVERT, **HARVEST, allow_blend=True,
                                  bracket_rates=(0.12, 0.22), order_presets=("roth_before_pretax",), windows=(WINDOW,)))
    by_key = {c.key: c for c in out.candidates}
    base = by_key["baseline"]
    # Conversion toggle: money actually moves.
    assert by_key["conversion@2200/saved/all"].total_converted > 0
    # Harvest toggle: gains are realised.
    assert by_key["harvest@2200/saved/all"].total_harvested > 0
    # Blend toggle: the same plan with only withdrawal blending differs from the baseline.
    assert by_key["blend@1200/saved/all"].measures.lifetime_taxes != pytest.approx(base.measures.lifetime_taxes)
    # Order: only the withdrawal order differs.
    order_only = by_key["order@-/roth_before_pretax/all"]
    assert order_only.total_converted == 0 and order_only.measures.lifetime_taxes != pytest.approx(base.measures.lifetime_taxes)
    # Timing: the same rule inside a window converts a different amount.
    assert by_key["conversion@2200/saved/w1"].total_converted != pytest.approx(by_key["conversion@2200/saved/all"].total_converted)


def test_input_plan_is_never_mutated_and_baseline_matches_a_plain_run():
    plan = _plan(priorities=[PriorityData(priority_rank=1, priority_type="transfer", source_account_id="cash",
                                          target_account_id="brk", max_annual_amount=500.0)])
    before = copy.deepcopy(asdict(plan))
    out = run_search(plan, _space(**CONVERT, **HARVEST, allow_blend=True, order_presets=("pretax_first",), windows=(WINDOW,)))
    assert asdict(plan) == before
    baseline = next(c for c in out.candidates if c.is_baseline)
    plain = run_simulation(copy.deepcopy(plan))
    assert baseline.measures.lifetime_taxes == pytest.approx(sum(s.taxes for s in plain.yearly_snapshots))
    assert baseline.measures.net_legacy == pytest.approx(plain.metadata.net_legacy.net_legacy)
    # Every candidate keeps the user's saved rule, ahead of anything added.
    assert all(c.proposal["priorities_to_add"] == [] or c.proposal["priorities_to_add"][0]["priority_rank"] == 2
               for c in out.candidates)


def test_duplicate_candidates_are_merged_and_simulated_once(monkeypatch):
    calls = []
    real = search.run_simulation
    monkeypatch.setattr(search, "run_simulation", lambda plan: calls.append(plan) or real(plan))
    # taxable_first reproduces this saved order, and a blend-only rule on a plan that already blends at the same
    # rate is the baseline again: both collapse onto candidates that exist.
    plan = _plan(order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "brk"), DrawdownEntryData(3, "ira"),
                        DrawdownEntryData(4, "roth")],
                 tax_settings={"tax_target": {"kind": "federal_bracket", "bracket_rate": 0.12},
                               "blend_drawdown_to_tax_target": True})
    out = run_search(plan, _space(allow_blend=True, bracket_rates=(0.12, 0.22), order_presets=("taxable_first", "pretax_first")))
    assert out.counts.simulated == len(calls) == len(out.candidates)
    assert out.counts.grid_requested > out.counts.grid_size
    assert out.counts.cache_hits > 0
    keys = [c.key for c in out.candidates]
    assert len(keys) == len(set(keys))
    assert "blend@1200/saved/all" not in keys and not any("taxable_first" in k for k in keys)


def test_simulation_count_never_exceeds_the_budget(monkeypatch):
    calls = []
    real = search.run_simulation
    monkeypatch.setattr(search, "run_simulation", lambda plan: calls.append(1) or real(plan))
    big = _space(**CONVERT, **HARVEST, allow_blend=True, bracket_rates=(0.10, 0.12, 0.22),
                 order_presets=("taxable_first", "pretax_first", "roth_before_pretax"), windows=(WINDOW,), max_simulations=9)
    out = run_search(_plan(), big)
    assert len(calls) == out.counts.simulated == 9
    assert out.counts.budget_exhausted and out.counts.skipped_by_budget > 0
    assert out.counts.stage1_simulated + out.counts.stage2_simulated + 1 == 9
    assert out.counts.grid_size > 9


def test_search_dimensions_and_budget_are_enforced():
    plan = _plan()
    with pytest.raises(ValueError, match="between 2 and 128"):
        run_search(plan, _space(**CONVERT, max_simulations=129))
    with pytest.raises(ValueError, match="between 2 and 128"):
        run_search(plan, _space(**CONVERT, max_simulations=1))
    with pytest.raises(ValueError, match="Too many"):
        run_search(plan, _space(**CONVERT, bracket_rates=(0.10, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37, 0.4)))
    with pytest.raises(ValueError, match="Too many"):
        run_search(plan, _space(**CONVERT, windows=(WINDOW,) * 5))
    with pytest.raises(ValueError, match="rate scan"):
        run_search(plan, _space(**CONVERT, bracket_rates=(0.12, 0.22, 0.24), max_simulations=3))
    with pytest.raises(ValueError, match="required"):
        run_search(plan, _space(**CONVERT, bracket_rates=()))
    with pytest.raises(ValueError, match="need at least one action"):
        run_search(plan, _space())
    with pytest.raises(ValueError, match="Unknown objective"):
        run_search(plan, _space(objective="vibes", **CONVERT))
    with pytest.raises(ValueError, match="presets"):
        run_search(plan, _space(**CONVERT, order_presets=("alphabetical",)))


def test_order_only_search_runs_without_rates_or_a_scan():
    out = run_search(_plan(), _space(bracket_rates=(), order_presets=("taxable_first", "roth_before_pretax")))
    assert out.survivor_rates == [] and out.counts.stage1_simulated == 0
    assert {c.key for c in out.candidates} >= {"baseline", "order@-/taxable_first/all", "order@-/roth_before_pretax/all"}
    changed = next(c for c in out.candidates if c.key == "order@-/taxable_first/all")
    assert [(ch.kind, ch.target) for ch in changed.changes] == [("replace", "drawdown_order")]
    assert changed.proposal["drawdown_order"] and changed.proposal["priorities_to_add"] == []


def test_every_objective_ranks_by_its_own_direction():
    plan = _plan()
    for objective in OBJECTIVES:
        out = run_search(plan, _space(objective=objective, **CONVERT, bracket_rates=(0.12, 0.22)))
        values = [c.objective_value for c in out.candidates if c.success]
        top = out.candidates[0].objective_value
        assert out.direction == objective_direction(objective)
        assert top == (max(values) if out.direction == "higher" else min(values)) or abs(top - (max(values) if out.direction == "higher" else min(values))) < 0.005
        assert all(c.delta_vs_baseline == pytest.approx(c.objective_value - out.candidates[[x.key for x in out.candidates].index("baseline")].objective_value)
                   for c in out.candidates)


def test_existing_comparison_still_reports_the_new_measures():
    plan = _plan()
    cands = build_candidates(plan, source_account_id="ira", target_account_id="roth", bracket_ceilings=[0.22],
                             magi_cap=None, start_milestone_id=None, end_milestone_id=None)
    for objective in OBJECTIVES:
        comparison = compare_strategies(plan, cands, objective)
        assert comparison.best_key and comparison.objective == objective
    metrics = comparison.candidates[0]
    assert metrics.total_rmd_distributions > 0 and 0 < metrics.lifetime_effective_tax_rate < 1

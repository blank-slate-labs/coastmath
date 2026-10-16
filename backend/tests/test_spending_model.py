"""Spending model overlay: covered set, first-year phase, scaling, income and comparison."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from coastmath.engine import spending_model as sm
from coastmath.engine.simulator import run_simulation
from coastmath.engine.spending_model import (
    ADDED_EXPENSES,
    CAVEAT_NO_EARNED,
    CAVEAT_RATIO,
    CAVEAT_UNRESOLVED,
    SpendingModel,
    SpendingModelError,
    compare_spending_models,
    covered_expense_ids,
    expense_fingerprint,
    first_year_take_home,
    is_living_expense,
    is_scalable_earned_income,
    overlay_spending_model,
    scale_income_to_take_home,
    spending_baseline,
)
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
    SpendingRulesData,
)

START = 2026
ASSUMPTIONS = AssumptionData(inflation_rate=0.03, stock_growth_rate=0.06, bond_return_rate=0.04,
                             stock_dividend_yield=0.0, cash_yield_rate=0.0)


def _plan(**overrides) -> PlanData:
    values = dict(
        plan_id="00000000-0000-4000-8000-000000000201",
        birth_year=1981, birth_month=4, life_expectancy=88, start_year=START, filing_status="single",
        milestones=[MilestoneData(id="retire", name="Retire", trigger_type="age", trigger_value=58)],
        income_streams=[IncomeData(id="salary", name="Salary", annual_amount=120_000, growth_rate=0.0,
                                   end_milestone_id="retire", withholding_percent=0.2)],
        expenses=[
            ExpenseData(id="living", name="Living", annual_amount=36_000, category="essential"),
            ExpenseData(id="fun", name="Fun", annual_amount=12_000, discretionary_fraction=0.75),
            ExpenseData(id="travel", name="Travel", annual_amount=6_000, category="discretionary",
                        end_milestone_id="retire"),
            ExpenseData(id="later", name="Later life", annual_amount=10_000, category="essential",
                        start_milestone_id="retire"),
            ExpenseData(id="benefits", name="Benefits", annual_amount=4_000, is_payroll_deduction=True,
                        tied_income_id="salary"),
            ExpenseData(id="tuition", name="Tuition", annual_amount=9_000, qualified_education=True),
            ExpenseData(id="roof", name="Roof", annual_amount=15_000, recurrence_years=10),
            ExpenseData(id="paid", name="Paid from cash", annual_amount=2_000, specific_funding_source_id="cash"),
        ],
        accounts={"cash": AccountInfo(30_000, "checking"), "roth": AccountInfo(250_000, "roth_ira"),
                  "brokerage": AccountInfo(150_000, "taxable_brokerage", cost_basis=100_000)},
        assumptions=ASSUMPTIONS,
    )
    values.update(overrides)
    return PlanData(**values)


def _couple() -> PlanData:
    plan = _plan(filing_status="married_filing_jointly", spouse_birth_year=1983, spouse_life_expectancy=90)
    spouse_pay = IncomeData(id="spouse_pay", name="Spouse pay", annual_amount=70_000, owner="spouse", growth_rate=0.01)
    return replace(plan, income_streams=[*plan.income_streams, spouse_pay])


def _retired() -> PlanData:
    return _plan(
        birth_year=1955, life_expectancy=92, milestones=[],
        income_streams=[IncomeData(id="ss", name="Social Security", annual_amount=30_000,
                                   tax_category="social_security", claiming_age=67)],
        expenses=[ExpenseData(id="living", name="Living", annual_amount=50_000, category="essential"),
                  ExpenseData(id="travel", name="Travel", annual_amount=8_000, category="discretionary")],
        accounts={"ira": AccountInfo(900_000, "traditional_ira"), "cash": AccountInfo(40_000, "checking")},
    )


def _phased() -> PlanData:
    """An expense ending mid first year, one starting mid first year, one after retirement."""
    milestones = [
        MilestoneData(id="move", name="Move", trigger_type="date", trigger_date=f"{START}-07-01"),
        MilestoneData(id="retire", name="Retire", trigger_type="age", trigger_value=58),
        MilestoneData(id="before", name="Before", trigger_type="relative", relative_to_id="retire", offset_years=-2),
        MilestoneData(id="past", name="Past", trigger_type="date", trigger_date="2020-03-01"),
    ]
    return _plan(milestones=milestones, expenses=[
        ExpenseData(id="old_rent", name="Old rent", annual_amount=24_000, category="essential", end_milestone_id="move"),
        ExpenseData(id="new_rent", name="New rent", annual_amount=30_000, category="essential", start_milestone_id="move"),
        ExpenseData(id="since", name="Since 2020", annual_amount=5_000, discretionary_fraction=0.5,
                    start_milestone_id="past"),
        ExpenseData(id="kids", name="Kids", annual_amount=8_000, category="essential", end_milestone_id="before"),
        ExpenseData(id="golf", name="Golf", annual_amount=4_000, category="discretionary", start_milestone_id="retire"),
        ExpenseData(id="season", name="Season", annual_amount=3_000, category="discretionary", start_month=5, end_month=9),
    ])


def _flex() -> PlanData:
    return _plan(spending_rules=SpendingRulesData(flex_threshold=-0.1, flex_reduction=0.2))


def _partial() -> PlanData:
    return _plan(first_year_fraction=0.25)


PLANS = {"single": _plan, "couple": _couple, "retired": _retired, "phased": _phased, "flex": _flex,
         "partial": _partial}


def _year_one_buckets(plan: PlanData, ids: set[str]) -> tuple[float, float]:
    """First-year essential and discretionary spending of ``ids``, from the projection."""
    names = {exp.name: exp for exp in plan.expenses if exp.id in ids}
    snap = run_simulation(plan).yearly_snapshots[0]
    essential = discretionary = 0.0
    for row in snap.cash_flow.expenses:
        exp = names.get(row.name)
        if exp is None:
            continue
        if row.discretionary_amount is not None:
            part = row.discretionary_amount
        else:
            part = row.amount if row.category == "discretionary" else 0.0
        discretionary += part
        essential += row.amount - part
    return essential / plan.first_year_fraction, discretionary / plan.first_year_fraction


def _tolerance(plan: PlanData) -> float:
    """Cents rounding per expense, plus the two-decimal discretionary percent."""
    return 0.02 * len(plan.expenses) / plan.first_year_fraction + 2.0


# ── covered set ──────────────────────────────────────────────────

def test_covered_expenses_are_living_expenses_only():
    plan = _plan()
    assert covered_expense_ids(plan) == ["living", "fun", "travel", "later"]
    excluded = {exp.id: is_living_expense(exp) for exp in plan.expenses}
    assert not any(excluded[i] for i in ("benefits", "tuition", "roof", "paid"))
    multi = ExpenseData(id="m", name="M", annual_amount=1, specific_funding_source_ids=["cash"])
    tied = ExpenseData(id="t", name="T", annual_amount=1, tied_income_id="salary")
    assert not is_living_expense(multi) and not is_living_expense(tied)


def test_an_explicit_covered_set_replaces_the_rule_and_ignores_unknown_ids():
    plan = _plan()
    assert covered_expense_ids(plan, ["paid", "living", "missing"]) == ["living", "paid"]
    overlay = overlay_spending_model(plan, SpendingModel("x", 72_000, 0), covered_ids={"living"})
    by_id = {exp.id: exp for exp in overlay.plan_data.expenses}
    assert by_id["living"].annual_amount == 72_000
    assert by_id["fun"].annual_amount == 12_000  # outside the explicit set
    assert overlay.covered_expense_ids == ["living"]


# ── first-year phase ─────────────────────────────────────────────

def test_baseline_counts_the_current_phase_and_splits_discretionary_shares():
    base = spending_baseline(_plan())
    assert base.current_ids == ["living", "fun", "travel"]
    assert base.later_ids == ["later"]
    assert base.essential == pytest.approx(36_000 + 12_000 * 0.25)
    assert base.discretionary == pytest.approx(12_000 * 0.75 + 6_000)
    assert base.unresolved is False


def test_phased_first_year_follows_simulator_timing():
    base = spending_baseline(_phased())
    # Old rent runs January-June, new rent July-December: each half a year.
    assert set(base.current_ids) == {"old_rent", "new_rent", "since", "kids", "season"}
    assert base.later_ids == ["golf"]
    assert base.essential == pytest.approx(12_000 + 15_000 + 2_500 + 8_000)
    # Months bound an event only in its milestone years, so "season" runs all year.
    assert base.discretionary == pytest.approx(2_500 + 3_000)


def test_unresolved_milestones_count_as_not_reached_with_a_caveat():
    plan = _plan(milestones=[
        MilestoneData(id="rich", name="Rich", trigger_type="net_worth", trigger_value=1.0),
        MilestoneData(id="after", name="After", trigger_type="relative", relative_to_id="rich", offset_years=1),
        MilestoneData(id="off", name="Off", trigger_type="age", trigger_value=30, is_active=False),
    ], expenses=[
        ExpenseData(id="a", name="A", annual_amount=10_000, category="essential", start_milestone_id="rich"),
        ExpenseData(id="b", name="B", annual_amount=20_000, category="essential", end_milestone_id="after"),
        ExpenseData(id="c", name="C", annual_amount=5_000, category="essential", start_milestone_id="off"),
        ExpenseData(id="d", name="D", annual_amount=1_000, category="essential", start_milestone_id="nowhere"),
    ])
    base = spending_baseline(plan)
    assert base.current_ids == ["b"] and base.later_ids == ["a", "c", "d"]
    assert base.unresolved is True
    overlay = overlay_spending_model(plan, SpendingModel("x", 40_000, 0))
    assert overlay.caveats == [CAVEAT_UNRESOLVED]
    comparison = compare_spending_models(plan, [])
    assert comparison.plan.caveats == [CAVEAT_UNRESOLVED]


def test_future_phases_scale_or_stay_as_planned():
    plan = _plan()
    model = SpendingModel("double", 78_000, 30_000)
    scaled = {e.id: e for e in overlay_spending_model(plan, model).plan_data.expenses}
    planned = {e.id: e for e in overlay_spending_model(plan, model, future_phases="as_planned").plan_data.expenses}
    assert scaled["later"].annual_amount == pytest.approx(10_000 * 2)
    assert planned["later"].annual_amount == 10_000
    assert scaled["living"].annual_amount == planned["living"].annual_amount == 72_000
    with pytest.raises(SpendingModelError):
        overlay_spending_model(plan, model, future_phases="sometimes")


# ── scaling ──────────────────────────────────────────────────────

def test_mixed_expense_scales_each_part_and_restates_its_share():
    plan = _plan()
    overlay = overlay_spending_model(plan, SpendingModel("x", 39_000 * 1.5, 15_000 * 0.5))
    fun = next(e for e in overlay.plan_data.expenses if e.id == "fun")
    assert overlay.essential_ratio == pytest.approx(1.5) and overlay.discretionary_ratio == pytest.approx(0.5)
    # 3,000 essential × 1.5 + 9,000 discretionary × 0.5
    assert fun.annual_amount == pytest.approx(4_500 + 4_500)
    assert fun.discretionary_fraction == 0.5 and fun.category == "discretionary"
    change = next(c for c in overlay.changes if c.expense_id == "fun")
    assert change.discretionary_percent == 50.0 and change.annual_amount == 9_000


def test_equal_ratios_keep_shares_and_unchanged_expenses_report_no_change():
    plan = _plan()
    base = spending_baseline(plan)
    same = overlay_spending_model(plan, SpendingModel("same", base.essential, base.discretionary))
    assert same.changes == [] and same.added == []
    assert same.plan_data.expenses == plan.expenses
    double = overlay_spending_model(plan, SpendingModel("double", base.essential * 2, base.discretionary * 2))
    fun = next(e for e in double.plan_data.expenses if e.id == "fun")
    assert fun.discretionary_fraction == 0.75
    assert all(c.discretionary_percent is None for c in double.changes)


def test_growth_cap_scales_with_the_amount_and_inflation_links_survive():
    plan = _plan(expenses=[ExpenseData(id="capped", name="Capped", annual_amount=20_000, category="essential",
                                       growth_rate=0.05, growth_cap=25_000, inflation_linked=False)])
    out = overlay_spending_model(plan, SpendingModel("x", 30_000, 0)).plan_data.expenses[0]
    assert (out.annual_amount, out.growth_cap, out.growth_rate, out.inflation_linked) == (30_000, 37_500, 0.05, False)


def test_amounts_round_to_cents():
    plan = _plan(expenses=[ExpenseData(id="a", name="A", annual_amount=10_000, category="essential")])
    out = overlay_spending_model(plan, SpendingModel("x", 12_345.6789, 0)).plan_data.expenses[0]
    assert out.annual_amount == 12_345.68


def test_missing_bucket_becomes_a_lifetime_inflation_linked_expense():
    plan = _plan(expenses=[ExpenseData(id="living", name="Living", annual_amount=40_000, category="essential")])
    overlay = overlay_spending_model(plan, SpendingModel("x", 44_000, 9_000.004))
    assert overlay.discretionary_ratio is None
    added = overlay.added[0]
    assert (added.id, added.name) == ADDED_EXPENSES["discretionary"]
    assert added.annual_amount == 9_000 and added.category == "discretionary" and added.inflation_linked
    assert added.start_milestone_id is None and added.end_milestone_id is None
    # A zero model for a missing bucket adds nothing.
    assert overlay_spending_model(plan, SpendingModel("x", 44_000, 0)).added == []


def test_a_plan_without_covered_spending_gains_both_buckets():
    plan = _plan(expenses=[])
    overlay = overlay_spending_model(plan, SpendingModel("x", 30_000, 10_000))
    assert [e.id for e in overlay.added] == [ADDED_EXPENSES["essential"][0], ADDED_EXPENSES["discretionary"][0]]
    assert _year_one_buckets(overlay.plan_data, {e.id for e in overlay.added}) == pytest.approx((30_000, 10_000))


def test_zero_model_zeroes_the_current_phase():
    overlay = overlay_spending_model(_plan(), SpendingModel("x", 0, 0))
    by_id = {e.id: e for e in overlay.plan_data.expenses}
    assert by_id["living"].annual_amount == 0 and by_id["fun"].annual_amount == 0
    assert by_id["fun"].discretionary_fraction == 0.75  # nothing to split


@pytest.mark.parametrize("name", sorted(PLANS))
def test_invariant_year_one_spending_matches_the_model_and_nothing_else_changes(name):
    plan = PLANS[name]()
    model = SpendingModel("model", 61_234.56, 17_890.12)
    overlay = overlay_spending_model(plan, model)
    covered = set(overlay.covered_expense_ids) | {e.id for e in overlay.added}
    essential, discretionary = _year_one_buckets(overlay.plan_data, covered)
    assert essential == pytest.approx(model.essential, abs=_tolerance(overlay.plan_data))
    assert discretionary == pytest.approx(model.discretionary, abs=_tolerance(overlay.plan_data))
    original = {e.id: e for e in plan.expenses}
    for exp in overlay.plan_data.expenses:
        if exp.id not in covered:
            assert exp == original[exp.id]
    assert replace(overlay.plan_data, expenses=plan.expenses) == plan


def test_partial_first_year_annualizes_the_baseline():
    base = spending_baseline(_partial())
    assert base.essential == pytest.approx(36_000 + 3_000)


# ── income ───────────────────────────────────────────────────────

def test_scalable_earned_income_excludes_benefits_pensions_and_one_offs():
    assert is_scalable_earned_income(IncomeData(id="w", name="W", annual_amount=1))
    for income in (
        IncomeData(id="s", name="S", annual_amount=1, tax_category="social_security"),
        IncomeData(id="p", name="P", annual_amount=1, tax_category="qualified_pension"),
        IncomeData(id="f", name="F", annual_amount=1, pension_formula={"kind": "x"}),
        IncomeData(id="o", name="O", annual_amount=1, frequency="once"),
        IncomeData(id="i", name="I", annual_amount=1, is_active=False),
        IncomeData(id="n", name="N", annual_amount=1, is_earned_income=False),
    ):
        assert not is_scalable_earned_income(income), income.id


@pytest.mark.parametrize("name", ["single", "couple", "partial"])
def test_income_scaling_converges_on_take_home(name):
    plan = PLANS[name]()
    base = first_year_take_home(run_simulation(plan), plan)
    target = round(base * 0.8, 2)
    scaling = scale_income_to_take_home(plan, target)
    assert scaling.caveats == [] and scaling.ratio is not None
    assert first_year_take_home(scaling.result, scaling.plan_data) == pytest.approx(target, abs=1.0)
    assert first_year_take_home(run_simulation(scaling.plan_data), scaling.plan_data) == pytest.approx(target, abs=1.0)
    # Only year-one earned streams change; everything else is as planned.
    assert scaling.plan_data.expenses == plan.expenses
    assert replace(scaling.plan_data, income_streams=plan.income_streams) == plan


def test_income_scaling_keeps_relative_growth_and_scales_dollar_steps():
    schedule = [
        {"start_year": START + 1, "end_year": START + 1, "kind": "percent", "value": 5},
        {"start_year": START + 2, "end_year": START + 2, "kind": "dollar_change", "value": 2_000, "dollars": "nominal"},
        {"start_year": START + 3, "end_year": None, "kind": "set_amount", "value": 150_000, "dollars": "nominal"},
    ]
    salary = IncomeData(id="salary", name="Salary", annual_amount=100_000, growth_rate=0.0, growth_cap=200_000,
                        growth_schedule=schedule)
    plan = _plan(income_streams=[salary], expenses=[])
    target = first_year_take_home(run_simulation(plan), plan) * 1.25
    scaled = scale_income_to_take_home(plan, target)
    out = scaled.plan_data.income_streams[0]
    k = scaled.ratio
    assert out.annual_amount == pytest.approx(100_000 * k) and out.growth_cap == pytest.approx(200_000 * k)
    assert out.growth_schedule[0] == schedule[0]
    assert out.growth_schedule[1]["value"] == pytest.approx(2_000 * k)
    assert out.growth_schedule[2]["value"] == pytest.approx(150_000 * k)
    assert plan.income_streams[0].growth_schedule[1]["value"] == 2_000  # input untouched
    pay = {s.year: sum(i.amount for i in s.cash_flow.income_sources if i.name == "Salary")
           for s in scaled.result.yearly_snapshots[:4]}
    base = {s.year: sum(i.amount for i in s.cash_flow.income_sources if i.name == "Salary")
            for s in run_simulation(plan).yearly_snapshots[:4]}
    for year in pay:
        assert pay[year] == pytest.approx(base[year] * k)


def test_income_scaling_refuses_without_earned_income_in_year_one():
    scaling = scale_income_to_take_home(_retired(), 5_000)
    assert (scaling.ratio, scaling.caveats, scaling.result) == (None, [CAVEAT_NO_EARNED], None)
    later = _plan(income_streams=[IncomeData(id="w", name="W", annual_amount=50_000, start_milestone_id="retire")])
    assert scale_income_to_take_home(later, 5_000).caveats == [CAVEAT_NO_EARNED]


@pytest.mark.parametrize("target", [50.0, 1_000_000.0])
def test_income_scaling_refuses_out_of_range_ratios(target):
    plan = _plan()
    scaling = scale_income_to_take_home(plan, target)
    assert scaling.ratio is None and scaling.caveats == [CAVEAT_RATIO]
    assert scaling.plan_data is plan


def test_income_scaling_refuses_when_year_one_net_pay_is_not_positive():
    plan = _plan(income_streams=[IncomeData(id="w", name="W", annual_amount=1_000, growth_rate=0.0)],
                 expenses=[ExpenseData(id="ded", name="Deduction", annual_amount=5_000, is_payroll_deduction=True,
                                       tied_income_id="w", payroll_tax_treatment="after_tax")])
    assert scale_income_to_take_home(plan, 3_000).caveats == [CAVEAT_RATIO]


def test_income_refinement_stops_after_the_limit(monkeypatch):
    monkeypatch.setattr(sm, "TAKE_HOME_TOLERANCE", -1.0)  # never close enough
    calls = []
    real = sm.run_simulation
    monkeypatch.setattr(sm, "run_simulation", lambda plan: calls.append(plan) or real(plan))
    plan = _plan()
    target = first_year_take_home(real(plan), plan) * 0.9
    scaling = scale_income_to_take_home(plan, target)
    assert len(calls) == 1 + sm.INCOME_REFINEMENTS
    assert scaling.ratio is not None


def test_first_year_take_home_handles_empty_results():
    plan = _plan()
    assert first_year_take_home(SimpleNamespace(yearly_snapshots=[]), plan) == 0.0
    assert first_year_take_home(SimpleNamespace(yearly_snapshots=[SimpleNamespace(cash_flow=None)]), plan) == 0.0
    snap = SimpleNamespace(cash_flow=SimpleNamespace(net_pay=1200.0))
    assert first_year_take_home(SimpleNamespace(yearly_snapshots=[snap]), replace(plan, first_year_fraction=0.0)) == 0.0


# ── fingerprint ──────────────────────────────────────────────────

def test_fingerprint_tracks_expense_and_timing_inputs_but_not_order():
    plan = _plan()
    fingerprint = expense_fingerprint(plan)
    assert len(fingerprint) == 64
    assert expense_fingerprint(replace(plan, expenses=list(reversed(plan.expenses)))) == fingerprint
    assert expense_fingerprint(replace(plan, income_streams=[])) == fingerprint
    changed_expense = replace(plan, expenses=[replace(plan.expenses[0], annual_amount=36_001), *plan.expenses[1:]])
    changed_milestone = replace(plan, milestones=[replace(plan.milestones[0], trigger_value=59)])
    for other in (changed_expense, changed_milestone, replace(plan, first_year_fraction=0.5)):
        assert expense_fingerprint(other) != fingerprint
    assert expense_fingerprint(plan, ["living"]) != fingerprint


# ── comparison ───────────────────────────────────────────────────

def test_plan_variant_equals_a_normal_projection():
    plan = _plan()
    comparison = compare_spending_models(plan, [SpendingModel("a", 50_000, 10_000)])
    result = run_simulation(plan)
    out = comparison.plan
    assert out.final_net_worth == result.yearly_snapshots[-1].net_worth
    assert [p["net_worth"] for p in out.net_worth_path] == [s.net_worth for s in result.yearly_snapshots]
    assert out.success == result.metadata.success and out.fi_year == result.metadata.fi_estimate.year
    assert out.essential_ratio == 1.0 and out.discretionary_ratio == 1.0 and out.income_ratio is None
    assert out.net_worth_path[0]["inflation_factor"] == 1.0
    assert comparison.fingerprint == expense_fingerprint(plan)
    assert comparison.covered_expense_ids == ["living", "fun", "travel", "later"]
    assert comparison.seed is None


def test_identical_models_give_identical_outcomes_and_cheaper_spending_retires_earlier():
    plan = _plan()
    lean = SpendingModel("lean", 30_000, 5_000)
    comparison = compare_spending_models(plan, [lean, replace(lean, label="lean again"),
                                                SpendingModel("rich", 70_000, 30_000)])
    first, second, rich = comparison.models
    assert replace(second, label="lean") == first
    assert first.final_net_worth > comparison.plan.final_net_worth > rich.final_net_worth
    assert first.fi_year is not None and first.fi_age == first.fi_year - plan.birth_year
    assert rich.fi_year is None or rich.fi_year > first.fi_year


def test_comparison_scales_take_home_only_when_asked():
    plan = _plan()
    base = first_year_take_home(run_simulation(plan), plan)
    model = SpendingModel("pay cut", 40_000, 10_000, take_home_monthly=round(base * 0.7, 2))
    planned = compare_spending_models(plan, [model]).models[0]
    scaled = compare_spending_models(plan, [model, SpendingModel("no target", 40_000, 10_000)],
                                     income="scale_to_take_home").models
    assert planned.income_ratio is None
    assert planned.projected_take_home_monthly == pytest.approx(base)
    assert scaled[0].income_ratio == pytest.approx(0.7, abs=0.05)
    assert scaled[0].projected_take_home_monthly == pytest.approx(model.take_home_monthly, abs=1.0)
    assert scaled[1].income_ratio is None
    retired = compare_spending_models(_retired(), [replace(model, take_home_monthly=4_000)],
                                      income="scale_to_take_home").models[0]
    assert retired.caveats == [CAVEAT_NO_EARNED] and retired.income_ratio is None


def test_monte_carlo_variants_share_one_seed(monkeypatch):
    seeds = []

    def fake_monte_carlo(plan, n_trials, seed, max_workers, deadline):
        seeds.append((n_trials, seed, max_workers))
        return SimpleNamespace(success_rate=0.5)

    monkeypatch.setattr(sm, "run_monte_carlo", fake_monte_carlo)
    models = [SpendingModel("a", 30_000, 5_000), SpendingModel("b", 60_000, 20_000)]
    comparison = compare_spending_models(_plan(), models, mc_trials=25, max_workers=2)
    assert len(seeds) == 3 and len(set(seeds)) == 1 and seeds[0][0] == 25 and seeds[0][2] == 2
    assert comparison.seed == seeds[0][1] is not None
    assert all(o.monte_carlo_success_rate == 0.5 for o in [comparison.plan, *comparison.models])
    seeds.clear()
    assert compare_spending_models(_plan(), models, mc_trials=5, seed=42).seed == 42
    assert {s[1] for s in seeds} == {42}


def test_monte_carlo_runs_for_real_with_a_fixed_seed():
    plan = _plan(life_expectancy=60)
    comparison = compare_spending_models(plan, [SpendingModel("a", 30_000, 5_000)], mc_trials=4, seed=7,
                                         max_workers=1)
    assert 0.0 <= comparison.models[0].monte_carlo_success_rate <= 1.0


def test_comparison_validates_its_options():
    plan = _plan()
    with pytest.raises(SpendingModelError):
        compare_spending_models(plan, [SpendingModel("x", 1, 1)] * 7)
    with pytest.raises(SpendingModelError):
        compare_spending_models(plan, [], future_phases="never")
    with pytest.raises(SpendingModelError):
        compare_spending_models(plan, [], income="double")
    explicit = compare_spending_models(plan, [], covered_ids=["living"])
    assert explicit.caveats == ["Only the selected spending expenses change."]


@pytest.mark.parametrize("kwargs", [
    {"essential": -1, "discretionary": 0},
    {"essential": float("nan"), "discretionary": 0},
    {"essential": 0, "discretionary": float("inf")},
    {"essential": 0, "discretionary": 0, "take_home_monthly": 0},
    {"essential": 0, "discretionary": 0, "take_home_monthly": float("nan")},
])
def test_model_amounts_are_validated(kwargs):
    with pytest.raises(SpendingModelError):
        SpendingModel("bad", **kwargs)

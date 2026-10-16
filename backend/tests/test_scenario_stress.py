"""Hypothetical stress presets: each overlay changes only its own inputs and years."""

import copy

import pytest

from coastmath.engine.historical_data import DIVIDEND_YIELD_PROVENANCE
from coastmath.engine.scenario_stress import (
    ScenarioInputError,
    ScenarioParams,
    crash_returns,
    downturn_path,
    downturn_returns,
    run_scenario_stress_test,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    IncomeData,
    PlanData,
)
from coastmath.schemas.simulation import SimulationResult


def _plan(**overrides) -> PlanData:
    values = dict(
        plan_id="00000000-0000-4000-8000-000000000101",
        birth_year=1980, life_expectancy=70, start_year=2026, filing_status="single",
        income_streams=[IncomeData(id="salary", name="Salary", annual_amount=100_000, growth_rate=0.0)],
        accounts={
            "roth": AccountInfo(500_000, "roth_ira"),
            "cash": AccountInfo(20_000, "checking"),
        },
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.07, bond_return_rate=0.04,
                                   stock_dividend_yield=0.0, cash_yield_rate=0.0),
    )
    values.update(overrides)
    return PlanData(**values)


def _income(result, name="Salary"):
    return {
        s.year: sum(i.amount for i in s.cash_flow.income_sources if i.name == name)
        for s in result.yearly_snapshots
    }


def _by_year(result, field):
    return {s.year: getattr(s, field) for s in result.yearly_snapshots}


# ── job_loss ──────────────────────────────────────────────────────

def test_job_loss_pauses_then_resumes_at_reduced_pay():
    plan = _plan()
    base = _income(run_simulation(plan))
    stressed = _income(run_scenario_stress_test(
        plan, "job_loss", ScenarioParams(start_year=2028, months_without_pay=6, resume_percent=80),
    )["simulation_result"])
    assert stressed[2026] == base[2026] == pytest.approx(100_000)
    assert stressed[2027] == base[2027]
    assert stressed[2028] == pytest.approx(100_000 * 0.5 * 0.8)
    assert stressed[2029] == pytest.approx(80_000)
    assert stressed[2035] == pytest.approx(80_000)


def test_job_loss_longer_than_a_year_spans_two_years():
    stressed = _income(run_scenario_stress_test(
        _plan(), "job_loss", ScenarioParams(start_year=2027, months_without_pay=15, resume_percent=100),
    )["simulation_result"])
    assert stressed[2027] == 0
    assert stressed[2028] == pytest.approx(100_000 * 9 / 12)
    assert stressed[2029] == pytest.approx(100_000)


def test_job_loss_in_partial_opening_year_starts_at_plan_start():
    # Plan opens October 1; the 6-month gap runs October through March.
    plan = _plan(first_year_fraction=0.25)
    stressed = _income(run_scenario_stress_test(
        plan, "job_loss", ScenarioParams(start_year=2026, months_without_pay=6, resume_percent=50),
    )["simulation_result"])
    assert stressed[2026] == 0
    assert stressed[2027] == pytest.approx(100_000 * (9 / 12) * 0.5)


def test_job_loss_only_touches_the_selected_persons_earned_income():
    plan = _plan(
        spouse_birth_year=1982, spouse_life_expectancy=90, filing_status="married_filing_jointly",
        income_streams=[
            IncomeData(id="salary", name="Salary", annual_amount=100_000, growth_rate=0.0),
            IncomeData(id="partner", name="Partner salary", annual_amount=60_000, growth_rate=0.0, owner="spouse"),
            IncomeData(id="rent", name="Rent", annual_amount=12_000, growth_rate=0.0, tax_category="other_ordinary"),
        ],
    )
    result = run_scenario_stress_test(
        plan, "job_loss", ScenarioParams(start_year=2027, person="spouse", resume_percent=50),
    )["simulation_result"]
    assert _income(result)[2028] == pytest.approx(100_000)
    assert _income(result, "Rent")[2028] == pytest.approx(12_000)
    assert _income(result, "Partner salary")[2028] == pytest.approx(30_000)
    # The caller's plan is never mutated.
    assert all(i.pay_interruption is None for i in plan.income_streams)


def test_job_loss_requires_earned_income_and_a_partner():
    with pytest.raises(ScenarioInputError, match="partner"):
        run_scenario_stress_test(_plan(), "job_loss", ScenarioParams(start_year=2027, person="spouse"))
    with pytest.raises(ScenarioInputError, match="earned income"):
        run_scenario_stress_test(_plan(income_streams=[]), "job_loss", ScenarioParams(start_year=2027))


# ── market_crash ──────────────────────────────────────────────────

def test_crash_overrides_only_the_start_year_with_plan_assumptions():
    curves = [AssumptionCurveData(curve_type="inflation", mode="fixed", fixed_rate=0.025),
              AssumptionCurveData(curve_type="dividend_yield", mode="fixed", fixed_rate=0.015)]
    plan = _plan(assumption_curves=curves)
    override = crash_returns(plan, ScenarioParams(start_year=2030, stock_drop_percent=35))
    assert override == {2030: (pytest.approx(-0.35), pytest.approx(0.04), pytest.approx(0.025), pytest.approx(0.015))}


def test_crash_changes_only_the_crash_year_growth():
    plan = _plan(income_streams=[])
    base = {s.year: s.accounts["roth"] for s in run_simulation(plan).yearly_snapshots}
    raw = run_scenario_stress_test(plan, "market_crash", ScenarioParams(start_year=2029, stock_drop_percent=35))
    stressed = {s.year: s.accounts["roth"] for s in raw["simulation_result"].yearly_snapshots}
    for year in (2026, 2027, 2028):
        assert stressed[year] == pytest.approx(base[year])
    assert stressed[2029] / stressed[2028] == pytest.approx(0.65)
    for year in (2030, 2031, 2040):
        assert stressed[year] / stressed[year - 1] == pytest.approx(base[year] / base[year - 1])
    assert DIVIDEND_YIELD_PROVENANCE not in raw["simulation_result"].metadata.warnings
    assert raw["metadata"] == {"preset": "market_crash", "start_year": 2029, "stock_drop_percent": 35}


# ── tech_bust ─────────────────────────────────────────────────────

def test_tech_bust_combines_job_loss_and_crash_in_one_year():
    plan = _plan()
    params = ScenarioParams(start_year=2028, months_without_pay=6, resume_percent=80, stock_drop_percent=40)
    bust = run_scenario_stress_test(plan, "tech_bust", params)
    loss = run_scenario_stress_test(plan, "job_loss", params)["simulation_result"]
    crash = run_scenario_stress_test(plan, "market_crash", params)["simulation_result"]
    result = bust["simulation_result"]
    assert _income(result) == pytest.approx(_income(loss))
    roth = {s.year: s.accounts["roth"] for s in result.yearly_snapshots}
    crash_roth = {s.year: s.accounts["roth"] for s in crash.yearly_snapshots}
    assert roth[2028] / roth[2027] == pytest.approx(crash_roth[2028] / crash_roth[2027]) == pytest.approx(0.6)
    assert bust["metadata"]["preset"] == "tech_bust"
    assert {"months_without_pay", "resume_percent", "stock_drop_percent"} <= set(bust["metadata"])


# ── downturn ──────────────────────────────────────────────────────

def _dump(result) -> str:
    return SimulationResult.model_validate(result, from_attributes=True).model_dump_json()


def _curves():
    return [AssumptionCurveData(curve_type="inflation", mode="fixed", fixed_rate=0.025),
            AssumptionCurveData(curve_type="dividend_yield", mode="fixed", fixed_rate=0.015)]


@pytest.mark.parametrize("fraction", [1.0, 0.25])
@pytest.mark.parametrize("start_year", [2026, 2031])
def test_one_year_downturn_without_recovery_matches_market_crash_exactly(fraction, start_year):
    plan = _plan(first_year_fraction=fraction, assumption_curves=_curves())
    crash = run_scenario_stress_test(
        plan, "market_crash", ScenarioParams(start_year=start_year, stock_drop_percent=35))
    downturn = run_scenario_stress_test(plan, "downturn", ScenarioParams(
        start_year=start_year, stock_drop_percent=35, downturn_years=1, recovery_years=0))
    assert downturn_returns(plan, downturn["metadata"]["downturn_path"]) == crash_returns(
        plan, ScenarioParams(start_year=start_year, stock_drop_percent=35))
    assert _dump(downturn["simulation_result"]) == _dump(crash["simulation_result"])


def test_downturn_path_is_geometric_and_recovers_to_the_pre_downturn_level():
    plan = _plan(assumption_curves=_curves())
    path = downturn_path(plan, ScenarioParams(
        start_year=2030, stock_drop_percent=45, downturn_years=3, recovery_years=4))
    assert [e["year"] for e in path] == list(range(2030, 2037))
    assert [e["phase"] for e in path] == ["downturn"] * 3 + ["recovery"] * 4
    decline = [1 + e["stock_return"] for e in path[:3]]
    assert decline[0] == decline[1] == decline[2]
    assert decline[0] ** 3 == pytest.approx(0.55, rel=1e-12)
    index = 1.0
    for entry in path:
        index *= 1 + entry["stock_return"]
    assert index == pytest.approx(1.0, rel=1e-12)
    recovery = {e["stock_return"] for e in path[3:]}
    assert len(recovery) == 1 and recovery.pop() == pytest.approx(0.55 ** -0.25 - 1)


def test_bond_and_inflation_overrides_apply_only_in_downturn_years():
    plan = _plan(assumption_curves=_curves())
    params = ScenarioParams(start_year=2030, stock_drop_percent=25, downturn_years=2, recovery_years=2,
                            bond_return_percent=-3, inflation_percent=8)
    path = downturn_path(plan, params)
    assert [(e["bond_return"], e["inflation"]) for e in path] == [
        (pytest.approx(-0.03), pytest.approx(0.08))] * 2 + [(pytest.approx(0.04), pytest.approx(0.025))] * 2
    override = downturn_returns(plan, path)
    assert set(override) == {2030, 2031, 2032, 2033}
    assert override[2030][1:] == (pytest.approx(-0.03), pytest.approx(0.08), pytest.approx(0.015))
    assert override[2032][1:] == (pytest.approx(0.04), pytest.approx(0.025), pytest.approx(0.015))
    # Blank overrides keep the plan's own assumption in downturn years too.
    blank = downturn_path(plan, ScenarioParams(start_year=2030, downturn_years=2))
    assert [(e["bond_return"], e["inflation"]) for e in blank] == [(pytest.approx(0.04), pytest.approx(0.025))] * 2


def test_downturn_drives_account_growth_and_reverts_after_recovery():
    plan = _plan(income_streams=[])
    base = {s.year: s.accounts["roth"] for s in run_simulation(plan).yearly_snapshots}
    raw = run_scenario_stress_test(plan, "downturn", ScenarioParams(
        start_year=2029, stock_drop_percent=45, downturn_years=3, recovery_years=3))
    roth = {s.year: s.accounts["roth"] for s in raw["simulation_result"].yearly_snapshots}
    for year in (2026, 2027, 2028):
        assert roth[year] == pytest.approx(base[year])
    assert roth[2031] / roth[2028] == pytest.approx(0.55)
    assert roth[2034] == pytest.approx(roth[2028])
    for year in (2035, 2040):
        assert roth[year] / roth[year - 1] == pytest.approx(base[year] / base[year - 1])
    assert DIVIDEND_YIELD_PROVENANCE not in raw["simulation_result"].metadata.warnings
    meta = raw["metadata"]
    assert meta["preset"] == "downturn" and meta["downturn_years"] == 3 and meta["recovery_years"] == 3
    assert meta["bond_return_percent"] is None and meta["inflation_percent"] is None
    assert meta["stock_drop_percent"] == 45 and len(meta["downturn_path"]) == 6


def test_downturn_years_past_the_plan_end_are_dropped():
    path = downturn_path(_plan(), ScenarioParams(start_year=2047, downturn_years=3, recovery_years=3))
    assert [(e["year"], e["phase"]) for e in path] == [(2047, "downturn"), (2048, "downturn"), (2049, "downturn")]


def test_downturn_in_partial_opening_year_loses_the_yearly_factor_in_the_months_modeled():
    plan = _plan(income_streams=[], first_year_fraction=0.25)
    params = ScenarioParams(start_year=2026, stock_drop_percent=45, downturn_years=3)
    path = downturn_path(plan, params)
    factor = 0.55 ** (1 / 3)
    assert path[0]["stock_return"] == pytest.approx(factor - 1)
    override = downturn_returns(plan, path)
    assert override[2026][0] == pytest.approx(factor ** 4 - 1)
    assert override[2027][0] == pytest.approx(factor - 1)
    roth = {s.year: s.accounts["roth"] for s in run_scenario_stress_test(
        plan, "downturn", params)["simulation_result"].yearly_snapshots}
    assert roth[2026] == pytest.approx(500_000 * factor)
    assert roth[2028] == pytest.approx(500_000 * 0.55)


@pytest.mark.parametrize("params", [
    ScenarioParams(start_year=2030, downturn_years=0),
    ScenarioParams(start_year=2030, recovery_years=-1),
    ScenarioParams(start_year=2030, stock_drop_percent=100),
])
def test_downturn_rejects_impossible_parameters(params):
    with pytest.raises(ScenarioInputError, match="Downturn"):
        downturn_path(_plan(), params)


# ── new_child ─────────────────────────────────────────────────────

def test_new_child_adds_eighteen_years_of_cost_and_a_ctc_dependent():
    plan = _plan()
    original = copy.deepcopy(plan)
    base = run_simulation(plan)
    raw = run_scenario_stress_test(plan, "new_child", ScenarioParams(start_year=2028, child_annual_cost=18_000))
    result = raw["simulation_result"]
    base_exp, exp = _by_year(base, "expenses"), _by_year(result, "expenses")
    for year in exp:
        expected = 18_000 if 2028 <= year <= 2045 else 0
        assert exp[year] - base_exp[year] == pytest.approx(expected), year
    base_fed, fed = _by_year(base, "federal_tax"), _by_year(result, "federal_tax")
    for year in fed:
        # Under 17 at year end: ages 0-16 are 2028-2044.
        expected = 2_200 if 2028 <= year <= 2044 else 0
        assert base_fed[year] - fed[year] == pytest.approx(expected), year
    assert plan == original
    assert raw["metadata"]["child_cost_years"] == 18


def test_start_year_must_fall_inside_the_plan():
    with pytest.raises(ScenarioInputError, match="start_year"):
        run_scenario_stress_test(_plan(), "market_crash", ScenarioParams(start_year=2025))
    with pytest.raises(ScenarioInputError, match="start_year"):
        run_scenario_stress_test(_plan(), "market_crash", ScenarioParams(start_year=2050))
    with pytest.raises(ScenarioInputError, match="Unknown"):
        run_scenario_stress_test(_plan(), "asteroid", ScenarioParams(start_year=2030))

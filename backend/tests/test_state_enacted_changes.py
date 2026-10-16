"""Enacted state income tax law for tax years after the 2026 tables.

Expected amounts are independent arithmetic from the statutes and official
schedules in `_sources` in `state_tax_enacted_changes.json`, not engine
output. ``taxable`` arguments add back the state's standard deduction so each
case starts from a known taxable income.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

import coastmath.engine.simulator as simulator
from coastmath.engine import state_enacted_changes as enacted
from coastmath.engine import state_rules_bridge
from coastmath.engine.simulator import run_simulation
from coastmath.engine.state_retirement_exclusion import RetirementIncome
from coastmath.engine.tax_engine import (
    _TAX_DATA,
    _salt_cap_for_year,
    _senior_deduction,
    _state_tax_details,
    calculate,
)
from coastmath.engine.tax_schedule import effective_tax_settings
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
    ResidencyPeriodData,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "coastmath" / "data"
DATA = json.loads((DATA_DIR / "state_tax_enacted_changes.json").read_text())
SOURCED = {(row["state"], row["year"]) for section in DATA["_sources"] for row in section["content"]
           if isinstance(row, dict) and "year" in row}


def state_tax(state: str, year: int, agi: float, status: str = "single", **kwargs) -> float:
    return _state_tax_details(agi, state, filing_status=status, tax_year=year, **kwargs).tax


def progressive(taxable: float, rows: list[tuple[float | None, float]]) -> float:
    tax, lower = 0.0, 0.0
    for upper, rate in rows:
        top = taxable if upper is None else min(taxable, upper)
        if top > lower:
            tax += (top - lower) * rate
        lower = upper if upper is not None else lower
    return tax


# -- Data integrity -----------------------------------------------------------


def test_every_change_is_sourced_dated_and_contiguous():
    assert DATA["base_tax_year"] == 2026
    for state, entry in DATA["states"].items():
        assert state in _TAX_DATA["state"], state
        assert entry["indexing"], state
        years = [int(change["year"]) for change in entry["changes"]]
        assert years == sorted(years) and len(set(years)) == len(years), state
        for change in entry["changes"]:
            assert change["year"] > 2026, (state, change["year"])
            assert 2026 <= change["dollar_year"] <= change["year"]
            assert change["source"].strip() and change["summary"].strip()
            assert change["set"], (state, change["year"])
            # Every change has a cited row in the file's _sources.
            assert (state, str(change["year"])) in SOURCED, (state, change["year"])

            def tables(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key in ("brackets", "joint_brackets"):
                            yield item
                        else:
                            yield from tables(item)
            for brackets in tables(change["set"]):
                assert brackets[0]["min"] == 0
                for previous, row in pairwise(brackets):
                    assert row["min"] == previous["max"] and row["max"] > row["min"]
                assert brackets[-1]["max"] == 999_999_999
                assert all(0 <= row["rate"] < 0.2 for row in brackets)


def test_years_before_any_change_return_the_2026_entry_itself():
    factor = enacted.calendar_factor_for(1.0, 2026)
    for state, base in _TAX_DATA["state"].items():
        assert enacted.state_data_for_year(base, state, 2026, factor) is base
    assert enacted.state_data_for_year(_TAX_DATA["state"]["TX"], "TX", 2040, factor) is _TAX_DATA["state"]["TX"]
    # The base tables are never mutated by resolving later years.
    before = json.dumps(_TAX_DATA["state"], sort_keys=True)
    for state in DATA["states"]:
        enacted.state_data_for_year(_TAX_DATA["state"][state], state, 2040, enacted.calendar_factor_for(1.5, 2040))
    assert json.dumps(_TAX_DATA["state"], sort_keys=True) == before


# -- Per-state schedules ------------------------------------------------------


def test_nebraska_top_rate_falls_to_3_99_in_2027():
    agi = 100_000 + 8_600
    assert state_tax("NE", 2026, agi) == pytest.approx(progressive(100_000, [(4030, .0246), (24120, .0351), (None, .0455)]))
    expected = progressive(100_000, [(4030, .0246), (24120, .0351), (None, .0399)])
    assert expected == pytest.approx(3831.909)
    assert state_tax("NE", 2027, agi) == pytest.approx(expected)
    assert state_tax("NE", 2040, agi) == pytest.approx(expected)
    hoh = state_tax("NE", 2027, 100_000 + 12_600, "head_of_household")
    assert hoh == pytest.approx(progressive(100_000, [(7510, .0246), (38590, .0351), (None, .0399)]))


@pytest.mark.parametrize("year, rate", [(2026, .04), (2027, .0375), (2028, .035), (2029, .0325), (2030, .03), (2035, .03)])
def test_mississippi_phase_down_applies_year_by_year(year, rate):
    assert state_tax("MS", year, 60_000 + 2_300) == pytest.approx(50_000 * rate)


def test_montana_2027_bands_are_exact_in_2027_and_indexed_after():
    # Montana taxes federal taxable income: AGI less the federal standard deduction.
    deduction = 16_100
    assert state_tax("MT", 2026, 100_000 + deduction) == pytest.approx(47_500 * .047 + 52_500 * .0565)
    calendar = {2026: 1.0, 2027: 1.03, 2028: 1.03 * 1.05}
    in_2027 = state_tax("MT", 2027, 100_000 + deduction * 1.03, inflation_factor=1.03, calendar_inflation=calendar)
    assert in_2027 == pytest.approx(65_000 * .047 + 35_000 * .054)
    band_2028 = 65_000 * 1.05  # grown by 2028's inflation only, not 2027's
    in_2028 = state_tax("MT", 2028, 100_000 + deduction * calendar[2028],
                        inflation_factor=calendar[2028], calendar_inflation=calendar)
    assert in_2028 == pytest.approx(band_2028 * .047 + (100_000 - band_2028) * .054)
    joint = state_tax("MT", 2027, 200_000 + 32_200, "married_filing_jointly")
    assert joint == pytest.approx(130_000 * .047 + 70_000 * .054)


def test_montana_capital_gain_band_moves_in_2027():
    tax = _state_tax_details(100_000 + 16_100, "MT", filing_status="single", tax_year=2027,
                             net_long_term_capital_gains=80_000).tax
    # 20,000 ordinary at 4.7%; gains fill the $65,000 band less ordinary income.
    assert tax == pytest.approx(20_000 * .047 + 45_000 * .03 + 35_000 * .041)


def test_without_calendar_factors_constant_inflation_is_assumed():
    exact = {2026: 1.0, 2027: 1.03, 2028: 1.03 ** 2, 2029: 1.03 ** 3}
    for state in ("MT", "HI", "VA"):
        assert state_tax(state, 2029, 150_000, inflation_factor=1.03 ** 3) == pytest.approx(
            state_tax(state, 2029, 150_000, inflation_factor=1.03 ** 3, calendar_inflation=exact))


def test_new_york_rate_cuts_in_2027_and_high_income_rates_expire_after_2032():
    ups = [8500, 11700, 13900, 80650, 215400, 1077550, 5000000, 25000000, None]
    agi = 2_000_000 + 8_000
    assert state_tax("NY", 2026, agi) == pytest.approx(
        progressive(2_000_000, list(zip(ups, [.039, .044, .0515, .054, .059, .0685, .0965, .103, .109], strict=True))))
    cut = progressive(2_000_000, list(zip(ups, [.038, .043, .0505, .053, .058, .0685, .0965, .103, .109], strict=True)))
    assert state_tax("NY", 2027, agi) == pytest.approx(cut)
    assert state_tax("NY", 2032, agi) == pytest.approx(cut)
    # Tax Law 601(c)(1)(B)(ix): $70,983 plus 8.82% over $1,077,550.
    assert state_tax("NY", 2033, agi) == pytest.approx(70_983 + .0882 * (2_000_000 - 1_077_550), abs=1)
    joint = state_tax("NY", 2033, 3_000_000 + 16_050, "married_filing_jointly")
    assert joint == pytest.approx(143_107 + .0882 * (3_000_000 - 2_155_350), abs=1)


def test_hawaii_act_46_steps():
    single_2027 = [(14400, .014), (19200, .032), (24000, .055), (36000, .064), (48000, .068), (125000, .072),
                   (175000, .076), (225000, .079), (275000, .0825), (325000, .09), (400000, .10), (None, .11)]
    single_2029 = [(19200, .014), (24000, .032), (36000, .055), (48000, .064), (125000, .068), (175000, .072),
                   (225000, .076), (275000, .079), (325000, .0825), (400000, .09), (475000, .10), (None, .11)]
    agi = 100_000
    # DOTAX Announcement 2024-03: $2,203 plus 7.2% over $48,000 at $92,000 (2027 schedule).
    assert state_tax("HI", 2027, 92_000 + 8_000) == pytest.approx(2203 + .072 * 44_000, abs=1)
    assert state_tax("HI", 2027, agi) == pytest.approx(progressive(agi - 8_000, single_2027))
    assert state_tax("HI", 2028, agi) == pytest.approx(progressive(agi - 9_000, single_2027))
    assert state_tax("HI", 2029, agi) == pytest.approx(progressive(agi - 9_000, single_2029))
    assert state_tax("HI", 2030, agi) == pytest.approx(progressive(agi - 10_000, single_2029))
    assert state_tax("HI", 2031, agi) == pytest.approx(progressive(agi - 12_000, single_2029))
    # Joint: doubled bands and deduction; head of household has its own schedule.
    assert state_tax("HI", 2031, 2 * agi, "married_filing_jointly") == pytest.approx(
        progressive(2 * (agi - 12_000), [(None if u is None else 2 * u, r) for u, r in single_2029]))
    assert state_tax("HI", 2031, 130_000, "head_of_household") == pytest.approx(
        2776 + .068 * (130_000 - 18_000 - 72_000), abs=1)


@pytest.mark.parametrize("year, deduction", [(2026, 8750), (2027, 9200), (2028, 9300), (2029, 9300), (2030, 3000)])
def test_virginia_standard_deduction_schedule(year, deduction):
    agi = 60_000
    rows = [(3000, .02), (5000, .03), (17000, .05), (None, .0575)]
    assert state_tax("VA", year, agi) == pytest.approx(progressive(agi - deduction, rows))
    assert state_tax("VA", year, 2 * agi, "married_filing_jointly") == pytest.approx(
        progressive(2 * (agi - deduction), rows))


def test_indiana_rate_falls_to_2_9_in_2027():
    assert state_tax("IN", 2026, 100_000) == pytest.approx(2950)
    assert state_tax("IN", 2027, 100_000) == pytest.approx(2900)


def test_georgia_retirement_exclusion_rises_to_70000_in_2027():
    income = [RetirementIncome(age=70, amounts={"pension": 90_000})]

    def ga(year: int) -> float:
        return calculate(gross_income=90_000, deductions=0, filing_status="single", state_code="GA",
                         tax_year=year, holder_age=70, retirement_income=income).state
    assert ga(2026) == pytest.approx(.0499 * (90_000 - 65_000 - 15_000))
    assert ga(2027) == pytest.approx(.0499 * (90_000 - 70_000 - 15_000))


def test_washington_income_tax_from_2028():
    def wa(year: int, status: str = "married_filing_jointly", **kwargs):
        return calculate(gross_income=3_000_000, deductions=0, filing_status=status, state_code="WA",
                         tax_year=year, **kwargs)
    assert wa(2027).state == 0
    assert wa(2028).state == pytest.approx(.099 * 2_000_000)
    assert wa(2028, "married_filing_separately").state == pytest.approx(.099 * 2_500_000)
    # Real property gains are outside the base; the excise on the other gains
    # is credited against the income tax on them.
    result = wa(2028, capital_gains=500_000, real_estate_capital_gains=100_000)
    excise = .07 * (400_000 - 278_000)
    assert result.state_capital_gains_excise == pytest.approx(excise)
    assert result.state == pytest.approx(.099 * (3_400_000 - 1_000_000))
    below = calculate(gross_income=900_000, deductions=0, filing_status="single", state_code="WA", tax_year=2030)
    assert below.state == 0


# -- Precedence ---------------------------------------------------------------


def test_user_scheduled_brackets_override_enacted_law():
    base = {"scheduled_changes": [{"year": 2027, "settings": {"state_brackets": [[1e12, 0.05]]}}]}
    settings = effective_tax_settings(base, 2027, {})
    taxed = calculate(gross_income=108_600, deductions=0, filing_status="single", state_code="NE",
                      tax_year=2027, settings=settings)
    assert taxed.state == pytest.approx(.05 * 100_000)
    # Before the change takes effect the built-in 2026 law applies.
    assert calculate(gross_income=108_600, deductions=0, filing_status="single", state_code="NE",
                     tax_year=2026, settings=effective_tax_settings(base, 2026, {})).state == pytest.approx(
        progressive(100_000, [(4030, .0246), (24120, .0351), (None, .0455)]))


def test_custom_brackets_keep_the_2026_deduction_and_ignore_enacted_changes():
    custom = [[1e12, 0.05]]
    tax = state_tax("VA", 2030, 60_000, custom_brackets=custom)
    assert tax == pytest.approx(.05 * (60_000 - 8_750))
    assert calculate(gross_income=3_000_000, deductions=0, filing_status="single", state_code="WA",
                     tax_year=2028, settings={"state_brackets": [[1e12, 0.0]]}).state == 0


def test_statutory_deduction_rules_keep_enacted_brackets_and_own_their_deductions():
    """Enacted changes to a figure the rules replace are in the rules by year."""
    rules_data = json.loads((Path(__file__).resolve().parents[1] / "coastmath" / "data"
                             / "state_deduction_rules_2026.json").read_text())
    supported = {state for state in _TAX_DATA["state"] if state_rules_bridge.coverage(state) == "supported"}
    for state in supported & set(DATA["states"]):
        for change in DATA["states"][state]["changes"]:
            schedules = change["set"].get("filing_status_schedules", {})
            if "standard_deduction" in change["set"] or any(
                    "standard_deduction" in schedule for schedule in schedules.values()):
                by_year = rules_data["states"][state]["standard_deduction"]["by_year"]
                assert int(change["year"]) in {int(item["from_year"]) for item in by_year}, state
    # Brackets still follow the enacted tables with the flag on; Nebraska's
    # rules apply their 2026 $8,850 deduction and $176 exemption credit
    # (indexed, with no inflation in this calculation).
    flagged = calculate(gross_income=108_600, deductions=0, filing_status="single", state_code="NE",
                        tax_year=2027, settings={"state_deduction_rules": True})
    assert flagged.state == pytest.approx(
        progressive(99_750, [(4030, .0246), (24120, .0351), (None, .0399)]) - 176)


def _wage_plan(initial: str, destination: str, move: str, inflation: float = 0.0) -> PlanData:
    return PlanData(
        plan_id=str(uuid5(NAMESPACE_URL, f"enacted-{initial}-{destination}-{move}-{inflation}")),
        birth_year=1980, birth_month=1, filing_status="single", life_expectancy=60, start_year=2026,
        milestones=[MilestoneData(id="move", name="Move", trigger_type="date", trigger_date=move)],
        income_streams=[IncomeData(id="salary", name="Wages", annual_amount=120_000, growth_rate=0)],
        expenses=[], priorities=[PriorityData(priority_rank=1, target_account_id="cash")],
        drawdown_order=["cash"],
        assumptions=AssumptionData(inflation_rate=inflation, stock_growth_rate=0, bond_return_rate=0),
        accounts={"cash": AccountInfo(balance=100_000, account_type="checking")}, tax_settings={},
        state_code=initial,
        residency_periods=[ResidencyPeriodData(state_code=destination, start_milestone_id="move")],
    )


def test_residency_move_in_the_change_year_uses_that_years_tables():
    snapshots = run_simulation(_wage_plan("TX", "NE", "2027-07-01")).yearly_snapshots
    by_year = {snap.year: snap.state_tax for snap in snapshots}
    assert by_year[2026] == 0
    assert by_year[2027] == pytest.approx(progressive(120_000 - 8_600, [(4030, .0246), (24120, .0351), (None, .0399)]))
    leaving = {snap.year: snap.state_tax for snap in run_simulation(_wage_plan("NE", "TX", "2027-07-01")).yearly_snapshots}
    assert leaving[2026] == pytest.approx(progressive(120_000 - 8_600, [(4030, .0246), (24120, .0351), (None, .0455)]))


def test_simulation_passes_its_calendar_factors(monkeypatch):
    seen: dict[int, dict] = {}
    original = simulator.calculate_tax

    def spy(*args, **kwargs):
        if kwargs.get("state_code") == "MT":
            seen[kwargs["tax_year"]] = dict(kwargs["calendar_inflation"])
        return original(*args, **kwargs)
    monkeypatch.setattr(simulator, "calculate_tax", spy)
    run_simulation(_wage_plan("MT", "MT", "2026-01-01", inflation=0.03))
    assert seen[2028][2026] == 1.0
    assert seen[2028][2027] == pytest.approx(1.03)
    assert seen[2028][2028] == pytest.approx(1.03 ** 2)


def test_simulation_places_fixed_dollar_amounts_with_its_calendar_factors():
    snapshots = run_simulation(_wage_plan("MT", "MT", "2026-01-01", inflation=0.03)).yearly_snapshots
    snap = next(s for s in snapshots if s.year == 2028)
    # The simulator's own state tax must match the engine fed the exact calendar path.
    calendar = {2026: 1.0, 2027: 1.03, 2028: 1.03 ** 2}
    direct = calculate(gross_income=snap.gross_income, deductions=0, filing_status="single", state_code="MT",
                       tax_year=2028, inflation_factor=calendar[2028], federal_inflation_factor=calendar[2028],
                       earned_income=snap.gross_income, holder_age=48, calendar_inflation=calendar)
    assert snap.state_tax == pytest.approx(direct.state, rel=1e-6)


# -- Federal dated provisions -------------------------------------------------


def test_federal_obbba_dates():
    # SALT cap: $40,400 in 2026, +1% a year through 2029, $10,000 from 2030.
    assert _salt_cap_for_year(2029, "single", 0) == pytest.approx(40_400 * 1.01 ** 3)
    assert _salt_cap_for_year(2030, "single", 0) == 10_000
    assert _salt_cap_for_year(2030, "married_filing_separately", 0) == 5_000
    # Senior deduction for 2025-2028 only.
    assert _senior_deduction(1, "single", 2028, 50_000) == 6_000
    assert _senior_deduction(1, "single", 2029, 50_000) == 0
    # 2026 charity rules: non-itemizer cash deduction from 2026, not 2025.
    def taxable(year):
        return calculate(gross_income=100_000, deductions=0, filing_status="single", tax_year=year,
                         charitable_direct_cash=5_000).taxable_income
    assert taxable(2026) == pytest.approx(100_000 - 16_100 - 1_000)
    assert taxable(2025) == pytest.approx(100_000 - 15_750)

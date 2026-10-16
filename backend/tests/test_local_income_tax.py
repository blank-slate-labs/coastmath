"""Local income tax calculations against hand-computed 2026 amounts.

Expected values come from the published schedules recorded in
`_sources` in `local_income_tax_2026.json`, computed independently here.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from coastmath.engine.local_tax import (
    LocalIncome,
    LocalTaxContext,
    calculate_local_tax,
    get_jurisdiction,
    list_jurisdictions,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import calculate
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    MilestoneData,
    PlanData,
    ResidencyPeriodData,
)


def _context(**overrides) -> LocalTaxContext:
    values = dict(state_code="NY", filing_status="single", tax_year=2026,
                  state_taxable_income=0.0, state_income_tax=0.0, federal_agi=0.0)
    values.update(overrides)
    return LocalTaxContext(**values)


def _tax(jurisdiction: str, income: LocalIncome | None = None, **context) -> float:
    return calculate_local_tax({"jurisdiction": jurisdiction}, income or LocalIncome(), _context(**context)).amount


class TestCatalog:
    def test_every_entry_is_well_formed(self):
        bases = {"state_taxable_income", "state_income_tax", "earned_income", "taxable_earned_income",
                 "gross_wages", "self_employment", "federal_agi", "michigan_city_income",
                 "philadelphia_unearned_income"}
        entries = list_jurisdictions()
        assert len(entries) == 171
        for entry in entries:
            assert entry["id"].startswith(entry["state_code"].lower() + "_")
            assert entry["components"]
            for component in entry["components"]:
                assert component["base"] in bases
                assert sum(key in component for key in ("rate", "brackets", "amount")) == 1
        counts = {}
        for entry in entries:
            counts[entry["state_code"]] = counts.get(entry["state_code"], 0) + 1
        assert counts == {"DE": 1, "IN": 92, "MD": 24, "MI": 24, "MO": 2, "NY": 2, "OH": 10, "OR": 4, "PA": 12}

    def test_flat_rates_stay_within_published_ranges(self):
        data = json.loads((Path(__file__).parents[1] / "coastmath" / "data" / "local_income_tax_2026.json").read_text())
        for identifier, entry in data["jurisdictions"].items():
            for component in entry["components"]:
                rate = component.get("rate")
                if isinstance(rate, float) and component["base"] != "state_income_tax":
                    assert 0.005 <= rate <= 0.038, identifier


class TestNewYork:
    def test_new_york_city_single_with_school_credits(self):
        # Tax: 12,000 * 3.078% + 13,000 * 3.762% + 25,000 * 3.819% + 50,000 * 3.876%
        tax = 369.36 + 489.06 + 954.75 + 1938.0
        # Rate-reduction credit: 12,000 * 0.171% + 88,000 * 0.228%; fixed credit $63.
        credits = 20.52 + 200.64 + 63
        assert _tax("ny_new_york_city", state_taxable_income=100_000, federal_agi=120_000) == pytest.approx(tax - credits)

    def test_new_york_city_joint_brackets_are_not_doubled_single(self):
        tax = 21_600 * .03078 + 23_400 * .03762 + 45_000 * .03819 + 110_000 * .03876
        credits = 21_600 * .00171 + 178_400 * .00228 + 125
        assert _tax("ny_new_york_city", filing_status="married_filing_jointly",
                    state_taxable_income=200_000, federal_agi=230_000) == pytest.approx(tax - credits)

    def test_new_york_city_credits_stop_at_income_limits(self):
        tax = 14_400 * .03078 + 15_600 * .03762 + 30_000 * .03819 + 540_000 * .03876
        assert _tax("ny_new_york_city", filing_status="head_of_household",
                    state_taxable_income=600_000, federal_agi=650_000) == pytest.approx(tax)

    def test_yonkers_surcharges_state_tax(self):
        assert _tax("ny_yonkers", state_income_tax=4_000) == pytest.approx(670)


class TestPennsylvania:
    def test_philadelphia_wages_profits_and_school_income_tax(self):
        income = LocalIncome(wages=100_000, medicare_wages=95_000, self_employment=20_000,
                             dividends=3_000, investment_income=1_000,
                             retirement_distributions=40_000, pension_income=30_000)
        expected = 100_000 * .037375 + 20_000 * .03735 + 4_000 * .03735
        assert _tax("pa_philadelphia", income, state_code="PA") == pytest.approx(expected)

    def test_philadelphia_follows_enacted_rate_schedule(self):
        income = LocalIncome(wages=100_000)
        assert _tax("pa_philadelphia", income, state_code="PA", tax_year=2027) == pytest.approx(3_732.5)
        assert _tax("pa_philadelphia", income, state_code="PA", tax_year=2045) == pytest.approx(3_700)

    def test_earned_income_tax_ignores_business_losses_and_retirement_income(self):
        income = LocalIncome(wages=80_000, medicare_wages=78_000, self_employment=-5_000,
                             retirement_distributions=30_000, dividends=9_000)
        assert _tax("pa_pittsburgh", income, state_code="PA") == pytest.approx(78_000 * .03)


class TestMaryland:
    def test_flat_county_rate_on_state_taxable_income(self):
        assert _tax("md_montgomery_county", state_code="MD", state_taxable_income=90_000) == pytest.approx(2_880)

    def test_anne_arundel_is_marginal(self):
        expected = 75_000 * .027 + 405_000 * .0294 + 20_000 * .032
        assert _tax("md_anne_arundel_county", state_code="MD", filing_status="married_filing_jointly",
                    state_taxable_income=500_000) == pytest.approx(expected)

    @pytest.mark.parametrize("taxable, expected", [(25_000, 562.5), (50_000, 1_375), (50_001, 50_001 * .0296)])
    def test_frederick_applies_one_tier_rate_to_all_income(self, taxable, expected):
        assert _tax("md_frederick_county", state_code="MD", state_taxable_income=taxable) == pytest.approx(expected)


class TestIndiana:
    def test_county_rate_on_state_taxable_income(self):
        assert _tax("in_marion_county", state_code="IN", state_taxable_income=60_000) == pytest.approx(1_212)


class TestMichigan:
    def test_detroit_excludes_retirement_income_and_allows_exemptions(self):
        income = LocalIncome(pension_income=20_000, annuity_income=5_000, retirement_distributions=30_000)
        # AGI 150,000 includes 12,000 taxable Social Security.
        base = 150_000 - 12_000 - 20_000 - 5_000 - 30_000 - 600 * (2 + 1)
        assert _tax("mi_detroit", income, state_code="MI", filing_status="married_filing_jointly",
                    federal_agi=150_000, taxable_social_security=12_000, persons=2,
                    aged_persons=1) == pytest.approx(base * .024)

    def test_exemptions_cannot_make_tax_negative(self):
        assert _tax("mi_grayling", state_code="MI", federal_agi=2_000) == 0


class TestOregon:
    def test_portland_combines_metro_county_and_arts_taxes(self):
        taxable = 300_000
        shs = (taxable - 128_000) * .01
        pfa = (taxable - 125_000) * .015 + (taxable - 250_000) * .015
        assert _tax("or_portland", state_code="OR", state_taxable_income=taxable) == pytest.approx(shs + pfa + 50)

    def test_head_of_household_uses_joint_thresholds_and_single_arts_amount(self):
        # Below every regional threshold; above the $40,000 arts threshold.
        assert _tax("or_portland", state_code="OR", filing_status="head_of_household",
                    state_taxable_income=190_000) == pytest.approx(50)

    def test_arts_tax_needs_income_above_threshold(self):
        assert _tax("or_portland", state_code="OR", state_taxable_income=20_000) == 0
        assert _tax("or_portland", state_code="OR", filing_status="married_filing_jointly",
                    state_taxable_income=40_001) == pytest.approx(100)

    def test_scheduled_changes_sunset_and_indexing(self):
        taxable = 300_000
        assert _tax("or_multnomah_county_outside_metro", state_code="OR", tax_year=2028,
                    state_taxable_income=taxable) == pytest.approx(125_000 * .023 + 50_000 * .038)
        assert _tax("or_metro_clackamas_washington", state_code="OR", tax_year=2031,
                    state_taxable_income=taxable) == 0
        # Indexed thresholds follow the calendar index; unindexed ones do not.
        assert _tax("or_metro_clackamas_washington", state_code="OR", tax_year=2030, index_factor=1.1,
                    state_taxable_income=taxable) == pytest.approx((taxable - 140_800) * .01)


class TestEarnedIncomeCities:
    def test_ohio_uses_medicare_wages(self):
        income = LocalIncome(wages=100_000, medicare_wages=97_000, taxable_wages=80_000, self_employment=10_000)
        assert _tax("oh_columbus", income, state_code="OH") == pytest.approx(107_000 * .025)

    def test_missouri_uses_box_one_wages(self):
        income = LocalIncome(wages=100_000, medicare_wages=97_000, taxable_wages=80_000, self_employment=10_000)
        assert _tax("mo_kansas_city", income, state_code="MO") == pytest.approx(900)

    def test_wilmington_taxes_gross_wages_and_profits(self):
        income = LocalIncome(wages=100_000, medicare_wages=97_000, self_employment=10_000)
        assert _tax("de_wilmington", income, state_code="DE") == pytest.approx(1_375)


class TestSelectionHandling:
    def test_custom_rates_apply_to_each_base(self):
        income = LocalIncome(wages=50_000, self_employment=10_000)
        selection = {"jurisdiction": "custom", "earned_income_rate": .02,
                     "taxable_income_rate": .01, "state_tax_surcharge_rate": .1}
        result = calculate_local_tax(selection, income, _context(
            state_code="OH", state_taxable_income=40_000, state_income_tax=1_000))
        assert result.amount == pytest.approx(1_200 + 400 + 100)

    def test_catalog_locality_outside_resident_state_is_not_taxed(self):
        result = calculate_local_tax({"jurisdiction": "ny_new_york_city"}, LocalIncome(),
                                     _context(state_code="FL", state_taxable_income=100_000))
        assert result.amount == 0 and "applies only to NY residents" in result.diagnostics[0]

    def test_no_selection_is_no_tax(self):
        assert calculate_local_tax(None, LocalIncome(wages=1e6), _context()).amount == 0
        assert get_jurisdiction("atlantis") is None


class TestTaxEngineIntegration:
    def test_local_tax_is_part_of_total_tax(self):
        without = calculate(120_000, 0, "single", state_code="NY", tax_year=2026)
        with_nyc = calculate(120_000, 0, "single", state_code="NY", tax_year=2026,
                             local_tax={"jurisdiction": "ny_new_york_city"})
        # NY taxable income: 120,000 less the $8,000 NY standard deduction.
        taxable = 112_000
        nyc = (12_000 * .03078 + 13_000 * .03762 + 25_000 * .03819 + (taxable - 50_000) * .03876
               - 12_000 * .00171 - (taxable - 12_000) * .00228 - 63)
        assert with_nyc.local == pytest.approx(nyc)
        assert with_nyc.state == pytest.approx(without.state)
        assert with_nyc.total_tax == pytest.approx(without.total_tax + nyc)

    def test_yonkers_uses_final_state_tax(self):
        result = calculate(90_000, 0, "single", state_code="NY", tax_year=2026, local_tax={"jurisdiction": "ny_yonkers"})
        assert result.local == pytest.approx(result.state * .1675)

    def test_flat_mode_has_no_local_tax(self):
        result = calculate(120_000, 0, "single", state_code="NY", tax_year=2026,
                           settings={"mode": "flat", "ordinary_income_tax_rate": .2},
                           local_tax={"jurisdiction": "ny_new_york_city"})
        assert result.local == 0 and result.total_tax == pytest.approx(24_000)

    def test_ny_standard_deduction_is_new_yorks(self):
        # 2026 NY single standard deduction is $8,000 (IT-2105-I 2026).
        result = calculate(8_000, 0, "single", state_code="NY", tax_year=2026)
        assert result.state == 0
        assert calculate(9_000, 0, "single", state_code="NY", tax_year=2026).state == pytest.approx(39)


def _nyc_plan(**overrides) -> PlanData:
    values = dict(
        plan_id=str(uuid.uuid4()), birth_year=1980, filing_status="single", life_expectancy=50, start_year=2026,
        income_streams=[IncomeData("pay", "Salary", 150_000, growth_rate=0, tax_category="employment")],
        accounts={"cash": AccountInfo(10_000, "savings")},
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0),
        state_code="NY", local_tax={"jurisdiction": "ny_new_york_city"},
    )
    values.update(overrides)
    return PlanData(**values)


class TestSimulation:
    def test_snapshot_reports_local_tax_inside_total_taxes(self):
        snapshots = run_simulation(_nyc_plan()).yearly_snapshots
        without = run_simulation(_nyc_plan(local_tax=None)).yearly_snapshots
        first = snapshots[0]
        assert first.local_tax > 4_000
        assert first.taxes == pytest.approx(first.federal_tax + first.state_tax + first.local_tax
            + first.capital_gains_tax + first.fica_tax + first.niit_tax + first.early_withdrawal_penalty)
        assert first.taxes == pytest.approx(without[0].taxes + first.local_tax)
        assert first.net_worth == pytest.approx(without[0].net_worth - first.local_tax, abs=.01)

    def test_local_income_tax_is_itemized_salt(self):
        # A large mortgage-interest deduction makes the household itemize; the
        # NYC tax then enlarges SALT and lowers federal tax.
        plan = _nyc_plan(tax_settings={"year_to_date": {"tax_year": 2026, "mortgage_interest": 30_000}})
        with_nyc = run_simulation(plan).yearly_snapshots[0]
        without = run_simulation(replace(plan, local_tax=None)).yearly_snapshots[0]
        assert with_nyc.deduction_used == "itemized"
        assert with_nyc.deduction_amount == pytest.approx(without.deduction_amount + with_nyc.local_tax, abs=.01)
        assert with_nyc.federal_tax < without.federal_tax

    def test_move_ends_local_tax_and_warns_in_the_move_year(self):
        plan = _nyc_plan(
            milestones=[MilestoneData(id="move", name="Move", trigger_type="date", trigger_date="2028-07-01")],
            residency_periods=[ResidencyPeriodData(state_code="FL", start_milestone_id="move")],
        )
        result = run_simulation(plan)
        by_year = {s.year: s for s in result.yearly_snapshots}
        assert by_year[2027].local_tax > 0
        assert by_year[2028].local_tax == 0 and by_year[2029].local_tax == 0
        assert any(w.startswith("2028: Local income tax uses the residence") for w in result.metadata.warnings)

    def test_statewide_prompt_when_maryland_has_no_county(self):
        warnings = run_simulation(_nyc_plan(state_code="MD", local_tax=None)).metadata.warnings
        assert "Maryland county income tax is not included. Select a county or Baltimore City." in warnings

    def test_pennsylvania_prompt_needs_earned_income(self):
        prompt = "Pennsylvania local earned income tax is not included. Select a locality or enter its rate."
        working = run_simulation(_nyc_plan(state_code="PA", local_tax=None)).metadata.warnings
        retired = run_simulation(_nyc_plan(state_code="PA", local_tax=None, income_streams=[
            IncomeData("pension", "Pension", 40_000, growth_rate=0, tax_category="qualified_pension")])).metadata.warnings
        assert prompt in working and prompt not in retired

    def test_jurisdiction_limitations_are_reported_once(self):
        warnings = run_simulation(_nyc_plan()).metadata.warnings
        assert sum("New York City tax uses New York taxable income" in w for w in warnings) == 1

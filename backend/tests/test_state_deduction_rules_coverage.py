"""Worked examples for the spec-driven state deduction rules.

Each expected value is worked by hand from the forms and statutes listed in
`_sources` in `state_deduction_rules_2026.json` (two or more per state), not from
the evaluator. Amounts are the published table year of each state.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from coastmath.engine.state_deduction_rules import (
    ItemizedCategories,
    StateDeductionContext,
    evaluate_state_deductions,
)

DATA = Path(__file__).resolve().parents[1] / "coastmath" / "data"
RULES = json.loads((DATA / "state_deduction_rules_2026.json").read_text())
ENACTED = json.loads((DATA / "state_tax_enacted_changes.json").read_text())

S, MFJ, MFS, HOH = "single", "married_filing_jointly", "married_filing_separately", "head_of_household"


def ctx(state, **overrides):
    base = dict(
        state_code=state, tax_year=2026, inflation_factor=1.0, filing_status=S,
        holder_age=45, spouse_age=None, dependent_count=0, federal_agi=50_000.0,
        state_agi=50_000.0, itemized=ItemizedCategories(), federal_itemized_elected=False,
        federal_itemized_total=0.0, federal_standard_deduction=16_100.0,
        federal_income_tax_liability=0.0, payroll_taxes_withheld=0.0,
    )
    if overrides.get("filing_status") == MFJ and "spouse_age" not in overrides:
        base["spouse_age"] = 45
    base.update(overrides)
    return StateDeductionContext(**base)


def run(state, **overrides):
    result = evaluate_state_deductions(ctx(state, **overrides))
    assert result.supported and result.coverage == "supported", state
    return result


# --- Arkansas (AR1000F instructions, AR3) -----------------------------------

def test_arkansas_standard_deduction_and_personal_credit():
    result = run("AR")
    assert (result.deduction, result.exemption_deduction, result.nonrefundable_credit) == (2_470, 0, 29)


def test_arkansas_itemized_excludes_state_income_tax_and_counts_aged_credits():
    cats = ItemizedCategories(medical_expenses=12_000, real_estate_tax=5_000,
                              state_local_income_tax=4_000, local_income_tax=500,
                              mortgage_interest=6_000, charitable_cash=2_000)
    result = run("AR", filing_status=MFJ, holder_age=66, spouse_age=67, dependent_count=2,
                 state_agi=80_000, federal_agi=80_000, itemized=cats)
    # Medical over 10% of AR AGI 4,000 + real estate 5,000 + city tax 500
    # + mortgage 6,000 + charity 2,000.
    assert result.use_itemized and result.deduction == 17_500
    # Two filers, two aged and two dependent credits of $29.
    assert result.nonrefundable_credit == 6 * 29


# --- Arizona (Form 140 instructions) ------------------------------------------

def test_arizona_dependent_credit_phases_down_by_five_percent_bands():
    result = run("AZ", dependent_count=2, children_under_17=1, federal_agi=210_500)
    # $100 + $25, reduced 5% for each $1,000 (or part) over $200,000: 11 bands.
    assert result.nonrefundable_credit == pytest.approx(125 * 0.45)
    assert result.deduction == 16_100


def test_arizona_charitable_standard_deduction_increase_and_aged_exemption():
    result = run("AZ", filing_status=MFJ, holder_age=66, spouse_age=70, federal_agi=100_000,
                 itemized=ItemizedCategories(charitable_cash=3_000))
    assert not result.use_itemized
    # ARS 43-1041(I)(2): from 2026 all gifts are added, at most $2,000 joint.
    assert result.deduction == 32_200 + 2_000
    assert result.exemption_deduction == 2 * 2_100


def test_arizona_charitable_increase_below_the_single_cap():
    result = run("AZ", itemized=ItemizedCategories(charitable_cash=600, charitable_property=300))
    assert result.deduction == 16_100 + 900
    capped = run("AZ", filing_status=HOH, itemized=ItemizedCategories(charitable_cash=5_000))
    assert capped.deduction == 24_150 + 1_000


# --- Delaware (PIT-RES instructions) ----------------------------------------

def test_delaware_additional_standard_deduction_and_personal_credits():
    result = run("DE", filing_status=MFJ, holder_age=61, spouse_age=66, dependent_count=1)
    assert result.deduction == 6_500 + 2_500
    # $110 for each spouse and dependent, $110 more for each spouse 60 or older.
    assert result.nonrefundable_credit == 3 * 110 + 2 * 110


def test_delaware_itemized_excludes_delaware_income_tax_and_drops_age_amount():
    cats = ItemizedCategories(state_local_income_tax=6_000, local_income_tax=1_000,
                              real_estate_tax=9_000, mortgage_interest=10_000)
    result = run("DE", holder_age=70, federal_agi=100_000, state_agi=100_000, itemized=cats)
    assert result.use_itemized and result.deduction == 1_000 + 9_000 + 10_000


# --- Georgia (IT-511 booklet; DOR 2026 changes) ------------------------------

def test_georgia_2026_standard_deduction_and_dependent_exemption():
    result = run("GA", dependent_count=2)
    assert (result.deduction, result.exemption_deduction) == (15_000, 8_000)


@pytest.mark.parametrize("federal_total", [35_000, 25_000])
def test_georgia_federal_itemizers_must_itemize(federal_total):
    result = run("GA", filing_status=MFJ, federal_itemized_elected=True,
                 federal_itemized_total=federal_total)
    assert result.use_itemized and result.deduction == federal_total


# --- Hawaii (N-11 instructions; Act 46 SLH 2024) ------------------------------

@pytest.mark.parametrize("year,expected", [(2026, 8_000), (2027, 8_000), (2028, 9_000),
                                           (2030, 10_000), (2031, 12_000)])
def test_hawaii_standard_deduction_follows_act_46_by_year(year, expected):
    result = run("HI", tax_year=year, holder_age=66, dependent_count=1)
    assert result.deduction == expected
    assert result.exemption_deduction == 3 * 1_144  # self, age and dependent


def test_hawaii_itemized_overall_limitation_and_income_tax_cutoff():
    cats = ItemizedCategories(real_estate_tax=10_000, state_local_income_tax=15_000,
                              mortgage_interest=20_000, charitable_cash=5_000)
    result = run("HI", filing_status=MFJ, federal_agi=250_000, state_agi=250_000, itemized=cats)
    # Income taxes are not deductible at federal AGI $200,000 or more (joint).
    # 35,000 less the smaller of 3% x (250,000 - 166,800) or 80% of 35,000.
    assert result.use_itemized
    assert result.deduction == pytest.approx(35_000 - 0.03 * 83_200)


# --- Illinois (IL-1040 instructions; 35 ILCS 5/204) ---------------------------

def test_illinois_exemption_allowance_with_age_additions():
    result = run("IL", filing_status=MFJ, holder_age=66, spouse_age=67, dependent_count=1,
                 federal_agi=100_000)
    assert result.exemption_deduction == 3 * 2_925 + 2 * 1_000


def test_illinois_income_cliff_and_basic_amount_sunset():
    assert run("IL", federal_agi=250_000).exemption_deduction == 2_925
    assert run("IL", federal_agi=250_001).exemption_deduction == 0
    late = run("IL", tax_year=2029, holder_age=70)
    assert late.exemption_deduction == 1_000
    assert any("after 2028" in note for note in late.diagnostics)


# --- Indiana (IT-40 booklet Schedule 3) ---------------------------------------

def test_indiana_exemptions_for_a_low_income_older_couple_with_children():
    result = run("IN", filing_status=MFJ, holder_age=66, spouse_age=70, dependent_count=2,
                 federal_agi=39_000)
    # 2 x 1,000 + 2 x 1,000 dependents + 2 x 1,500 child extras + 2 x 1,000
    # age + 2 x 500 low-income age.
    assert result.exemption_deduction == 10_000


def test_indiana_low_income_age_exemption_stops_at_40000():
    assert run("IN", holder_age=70, federal_agi=40_000).exemption_deduction == 2_000


# --- Kansas (K-40 instructions) -----------------------------------------------

def test_kansas_aged_standard_deduction_matches_worksheet():
    result = run("KS", filing_status=MFJ, holder_age=66, spouse_age=67, dependent_count=2)
    assert result.deduction == 9_640  # worksheet: joint, 2 boxes
    assert result.exemption_deduction == 18_320 + 2 * 2_320


def test_kansas_itemized_and_head_of_household_exemption():
    cats = ItemizedCategories(medical_expenses=10_000, real_estate_tax=4_000,
                              state_local_income_tax=3_000, mortgage_interest=3_000)
    result = run("KS", filing_status=HOH, dependent_count=1, federal_agi=60_000,
                 state_agi=60_000, itemized=cats)
    assert result.use_itemized and result.deduction == 5_500 + 4_000 + 3_000
    assert result.exemption_deduction == 9_160 + 2_320 + 2_320


# --- Kentucky (740 instructions, Schedule ITC) --------------------------------

def test_kentucky_one_standard_deduction_per_joint_return_and_age_credits():
    result = run("KY", filing_status=MFJ, holder_age=66, spouse_age=67)
    assert (result.deduction, result.nonrefundable_credit) == (3_360, 80)


def test_kentucky_itemized_is_mortgage_interest_and_charity_only():
    cats = ItemizedCategories(mortgage_interest=5_000, charitable_cash=1_000,
                              real_estate_tax=4_000, medical_expenses=20_000)
    result = run("KY", itemized=cats)
    assert result.use_itemized and result.deduction == 6_000


# --- Massachusetts (M.G.L. c.62 s.3(B)(b)) ------------------------------------

def test_massachusetts_head_of_household_exemptions():
    result = run("MA", filing_status=HOH, holder_age=66, dependent_count=2)
    assert result.exemption_deduction == 6_800 + 2 * 1_000 + 700


def test_massachusetts_medical_deduction_needs_federal_itemizing():
    cats = ItemizedCategories(medical_expenses=20_000)
    itemizer = run("MA", filing_status=MFJ, federal_agi=100_000, itemized=cats,
                   federal_itemized_elected=True)
    assert (itemizer.deduction, itemizer.exemption_deduction) == (12_500, 8_800)
    assert run("MA", filing_status=MFJ, federal_agi=100_000, itemized=cats).deduction == 0


# --- Maryland (2025 resident booklet; 2026 withholding) -----------------------

def test_maryland_joint_standard_deduction_is_indexed():
    # 6,700 + 2.42% of 6,700 ($162) rounded down to $50.
    assert run("MD", filing_status=MFJ, federal_agi=300_000).deduction == 6_850
    assert run("MD", filing_status=HOH, federal_agi=300_000).deduction == 6_850


def test_maryland_exemption_chart_and_age_exemption():
    result = run("MD", federal_agi=120_000, state_agi=120_000, dependent_count=1, holder_age=66)
    assert result.exemption_deduction == 2 * 1_600 + 1_000
    assert result.deduction == 3_400


def test_maryland_itemized_removes_capped_income_tax_and_phases_out():
    cats = ItemizedCategories(state_local_income_tax=30_000, real_estate_tax=15_000)
    result = run("MD", filing_status=MFJ, federal_agi=250_000, state_agi=250_000, itemized=cats,
                 federal_itemized_elected=True, federal_itemized_total=40_000)
    # 40,400 SALT allowed x 30,000 / 45,000 income tax share; 7.5% of AGI over $200,000.
    assert result.use_itemized
    assert result.deduction == pytest.approx(40_000 - 40_400 * 30 / 45 - 3_750)
    assert result.exemption_deduction == 0


# --- Michigan (2026 Form 446; MCL 206.30) -------------------------------------

def test_michigan_exemptions_per_person():
    assert run("MI", filing_status=MFJ, dependent_count=2).exemption_deduction == 4 * 5_900


def test_michigan_indexed_exemption_rounds_to_100():
    result = run("MI", tax_year=2027, inflation_factor=1.03)
    assert result.exemption_deduction == 6_100  # 5,900 x 1.03 = 6,077


# --- Mississippi (DOR exemptions and deductions) ------------------------------

def test_mississippi_head_of_family_amounts():
    result = run("MS", filing_status=HOH, dependent_count=1, holder_age=66)
    assert (result.deduction, result.exemption_deduction) == (3_400, 8_000 + 1_500 + 1_500)


def test_mississippi_itemized_excludes_state_income_tax():
    cats = ItemizedCategories(state_local_income_tax=5_000, real_estate_tax=3_000,
                              mortgage_interest=8_000, charitable_cash=1_000)
    result = run("MS", filing_status=MFJ, itemized=cats)
    assert result.use_itemized and result.deduction == 12_000


# --- North Carolina (G.S. 105-153.5) ------------------------------------------

def test_north_carolina_child_deduction_by_federal_agi():
    result = run("NC", filing_status=MFJ, dependent_count=3, children_under_17=2, federal_agi=70_000)
    assert result.exemption_deduction == 2 * 2_000
    assert result.deduction == 25_500


def test_north_carolina_mortgage_and_property_tax_cap():
    cats = ItemizedCategories(mortgage_interest=15_000, real_estate_tax=8_000,
                              charitable_cash=2_000, state_local_income_tax=6_000)
    result = run("NC", itemized=cats)
    assert result.use_itemized and result.deduction == 20_000 + 2_000


# --- Nebraska (2026 Form 1040N-ES; 2025 booklet) ------------------------------

def test_nebraska_aged_standard_deduction_and_exemption_credit():
    result = run("NE", holder_age=66)
    assert (result.deduction, result.nonrefundable_credit) == (8_850 + 2_050, 176)


def test_nebraska_itemized_removes_all_income_tax_reported():
    cats = ItemizedCategories(state_local_income_tax=12_000)
    result = run("NE", filing_status=MFJ, dependent_count=1, itemized=cats,
                 federal_itemized_elected=True, federal_itemized_total=30_000)
    assert result.use_itemized and result.deduction == 18_000
    assert result.nonrefundable_credit == 3 * 176
    # Below the 2026 joint standard deduction the larger amount is used.
    smaller = run("NE", filing_status=MFJ, itemized=cats, federal_itemized_elected=True,
                  federal_itemized_total=28_000)
    assert not smaller.use_itemized and smaller.deduction == 17_700


# --- New Jersey (NJ-1040 instructions) ----------------------------------------

def test_new_jersey_exemptions_medical_and_property_tax_deductions():
    cats = ItemizedCategories(medical_expenses=5_000, real_estate_tax=18_000)
    result = run("NJ", filing_status=MFJ, holder_age=66, spouse_age=67, dependent_count=2,
                 state_agi=100_000, itemized=cats)
    assert result.exemption_deduction == 2_000 + 2_000 + 3_000
    assert result.deduction == 3_000 + 15_000


def test_new_jersey_separate_property_tax_limit():
    result = run("NJ", filing_status=MFS, itemized=ItemizedCategories(real_estate_tax=10_000))
    assert result.deduction == 7_500


# --- New York (IT-201-I, IT-196-I) --------------------------------------------

def test_new_york_standard_deduction_and_dependent_exemption():
    result = run("NY", dependent_count=1)
    assert (result.deduction, result.exemption_deduction) == (8_000, 1_000)


def test_new_york_itemized_excludes_income_tax_without_the_federal_cap():
    cats = ItemizedCategories(real_estate_tax=42_000, state_local_income_tax=9_000,
                              mortgage_interest=15_000, charitable_cash=3_000)
    result = run("NY", filing_status=MFJ, federal_agi=150_000, state_agi=150_000, itemized=cats)
    assert result.use_itemized and result.deduction == 60_000


@pytest.mark.parametrize("income,expected", [
    (125_000, 30_000 - 0.25 * 30_000 * 0.5),       # Worksheet 3
    (500_000, 30_000 - 0.25 * 30_000 * 1.5),       # Worksheet 4
    (600_000, 15_000),                             # 50% of line 45
    (2_000_000, 1_500),                            # 50% of charity
    (12_000_000, 750),                             # 25% of charity
])
def test_new_york_high_income_itemized_adjustment(income, expected):
    cats = ItemizedCategories(real_estate_tax=12_000, mortgage_interest=15_000, charitable_cash=3_000)
    # Federal AGI kept below the overall limitation threshold to isolate line 46.
    result = run("NY", federal_agi=300_000, state_agi=income, itemized=cats)
    assert result.deduction == pytest.approx(max(expected, 8_000))


# --- Oklahoma (Form 511 packet, Schedule 511-D) -------------------------------

def test_oklahoma_exemptions_with_low_income_age_exemption():
    result = run("OK", filing_status=MFJ, holder_age=66, spouse_age=67, dependent_count=1,
                 federal_agi=25_000)
    assert result.deduction == 12_700
    assert result.exemption_deduction == 3 * 1_000 + 2 * 1_000
    assert run("OK", holder_age=66, federal_agi=15_001).exemption_deduction == 1_000


def test_oklahoma_itemized_cap_excludes_medical_and_charity():
    cats = ItemizedCategories(state_local_income_tax=15_000, real_estate_tax=10_000,
                              medical_expenses=10_000, charitable_cash=4_000)
    result = run("OK", federal_agi=100_000, itemized=cats, federal_itemized_elected=True,
                 federal_itemized_total=40_000)
    # 40,000 - 15,000 income tax = 25,000; 25,000 - (2,500 medical + 4,000 charity)
    # = 18,500 is over the $17,000 limit.
    assert result.use_itemized and result.deduction == 17_000 + 6_500


# --- Rhode Island (ADV 2025-22; R.I. Gen. Laws 44-30-2.6) ---------------------

def test_rhode_island_standard_deduction_and_exemptions():
    result = run("RI", state_agi=100_000, dependent_count=1)
    assert (result.deduction, result.exemption_deduction) == (11_200, 2 * 5_250)


@pytest.mark.parametrize("income,share", [(261_000, 1.0), (275_000, 0.6), (290_800, 0.2), (290_801, 0.0)])
def test_rhode_island_twenty_percent_steps(income, share):
    result = run("RI", filing_status=MFJ, state_agi=income)
    assert result.deduction == pytest.approx(22_400 * share)
    assert result.exemption_deduction == pytest.approx(2 * 5_250 * share)


# --- Utah (2026 TC-40 lines 9-18) ---------------------------------------------

def test_utah_taxpayer_credit_on_the_federal_standard_deduction():
    result = run("UT", federal_agi=50_000, state_agi=50_000, federal_standard_deduction=16_100)
    assert result.nonrefundable_credit == pytest.approx(0.06 * 16_100 - 0.013 * (50_000 - 18_696))
    assert (result.deduction, result.exemption_deduction) == (0, 0)


def test_utah_taxpayer_credit_for_itemizers_with_dependents():
    cats = ItemizedCategories(state_local_income_tax=8_000, real_estate_tax=6_000)
    result = run("UT", filing_status=MFJ, dependent_count=2, federal_agi=100_000, state_agi=100_000,
                 itemized=cats, federal_itemized_elected=True, federal_itemized_total=40_000)
    # Line 14: SALT 14,000 less property taxes 6,000.
    initial = 0.06 * (2 * 2_167 + 40_000 - 8_000)
    assert result.nonrefundable_credit == pytest.approx(initial - 0.013 * (100_000 - 37_392))


# --- Virginia (Va. Code 58.1-322.03; 2025 Schedule A instructions) ------------

@pytest.mark.parametrize("year,expected", [(2026, 8_750), (2027, 9_200), (2029, 9_300), (2030, 3_000)])
def test_virginia_standard_deduction_by_year(year, expected):
    result = run("VA", tax_year=year, holder_age=66, dependent_count=1)
    assert result.deduction == expected
    assert result.exemption_deduction == 2 * 930 + 800


def test_virginia_itemizers_follow_the_federal_choice_without_the_salt_cap():
    cats = ItemizedCategories(medical_expenses=15_000, real_estate_tax=50_000,
                              state_local_income_tax=10_000, mortgage_interest=10_000,
                              charitable_cash=2_000)
    result = run("VA", filing_status=MFJ, federal_agi=100_000, state_agi=100_000, itemized=cats,
                 federal_itemized_elected=True, federal_itemized_total=60_000)
    # Medical over 10% of federal AGI 5,000; property taxes uncapped.
    assert result.use_itemized and result.deduction == 5_000 + 50_000 + 10_000 + 2_000


def test_virginia_overall_limitation():
    cats = ItemizedCategories(real_estate_tax=30_000, mortgage_interest=20_000)
    result = run("VA", federal_agi=432_700, state_agi=432_700, itemized=cats,
                 federal_itemized_elected=True, federal_itemized_total=50_000)
    assert result.deduction == pytest.approx(50_000 - 0.03 * 100_000)


# --- West Virginia (W. Va. Code 11-21-16) -------------------------------------

@pytest.mark.parametrize("status,dependents,expected", [(S, 0, 2_000), (MFJ, 2, 8_000), (HOH, 1, 4_000)])
def test_west_virginia_exemptions(status, dependents, expected):
    assert run("WV", filing_status=status, dependent_count=dependents).exemption_deduction == expected


# --- Connecticut tax schedule (CT-1040 Tables C, D, E) ------------------------

@pytest.mark.parametrize("status,agi,addition,rate", [
    (S, 25_000, 0, 0.35), (S, 40_000, 0, 0.10), (S, 64_500, 50, 0.01), (S, 64_501, 50, 0.0),
    # Table C capped at 250 and Table D 105,000-120,000: 3 steps of 25.
    (S, 120_000, 250 + 75, 0.0),
    (MFJ, 400_001, 500 + 680, 0.0), (MFJ, 1_080_001, 500 + 6_800, 0.0),
    (HOH, 320_001, 400 + 540, 0.0), (MFS, 52_000, 25, 0.02),
])
def test_connecticut_add_back_recapture_and_personal_credit(status, agi, addition, rate):
    result = run("CT", filing_status=status, state_agi=agi)
    assert result.tax_addition == pytest.approx(addition)
    assert result.tax_credit_rate == pytest.approx(rate)


# --- Built-in enacted law ------------------------------------------------------

@pytest.mark.parametrize("state", ["HI", "VA"])
def test_by_year_standard_deductions_match_enacted_changes(state):
    """The rules' later-year standard deductions are the enacted changes."""
    enacted = {int(change["year"]): change["set"] for change in ENACTED["states"][state]["changes"]
               if "standard_deduction" in change["set"]}
    rules = {int(item["from_year"]): item["amount"]
             for item in RULES["states"][state]["standard_deduction"]["by_year"]}
    assert set(rules) == set(enacted)
    for year, amounts in rules.items():
        assert amounts[S] == enacted[year]["standard_deduction"]
        hoh = enacted[year].get("filing_status_schedules", {}).get(HOH, {}).get("standard_deduction")
        assert amounts[HOH] == (hoh if hoh is not None else enacted[year]["standard_deduction"])


def test_spec_states_report_no_federal_tax_subtraction():
    for code, rule in RULES["states"].items():
        if "federal_tax_deduction" in rule:
            continue
        result = run(code, federal_income_tax_liability=20_000, state_agi=80_000, federal_agi=80_000)
        assert result.federal_tax_subtraction == 0, code


# --- District of Columbia (D.C. Law 26-89; 2025 D-40 booklet) ---------------

def test_dc_decoupled_standard_deduction_with_age_amounts():
    assert run("DC").deduction == 15_000
    both_aged = run("DC", filing_status=MFJ, holder_age=66, spouse_age=70)
    assert both_aged.deduction == 30_000 + 2 * 1_650
    assert run("DC", filing_status=HOH, holder_age=65).deduction == 22_500 + 2_050
    assert both_aged.exemption_deduction == 0


def test_dc_itemized_follows_federal_choice_without_salt_cap_and_phases_down():
    cats = ItemizedCategories(state_local_income_tax=20_000, real_estate_tax=15_000,
                              mortgage_interest=12_000, charitable_cash=5_000)
    high = dict(filing_status=MFJ, federal_agi=300_000, state_agi=300_000, itemized=cats)
    result = run("DC", federal_itemized_elected=True, **high)
    # Real estate 15,000 + mortgage 12,000 + charity 5,000, less 5% of DC AGI over $200,000.
    assert result.use_itemized and result.deduction == 32_000 - 5_000
    assert run("DC", **high).deduction == 30_000  # federal standard deduction taken
    with_medical = run("DC", federal_itemized_elected=True,
                       **{**high, "itemized": dataclasses.replace(cats, medical_expenses=30_000)})
    # Medical over 7.5% of AGI (7,500) is outside the 5% reduction.
    assert with_medical.deduction == 7_500 + 32_000 - 5_000


# --- Maine (36 M.R.S. 5124-C, 5125, 5126-A; 2026 rate schedule) -------------

def test_maine_standard_deduction_and_exemptions():
    result = run("ME")
    assert (result.deduction, result.exemption_deduction) == (15_700, 5_300)
    joint = run("ME", filing_status=MFJ, holder_age=66, spouse_age=67, federal_agi=100_000,
                state_agi=100_000)
    assert (joint.deduction, joint.exemption_deduction) == (31_400 + 2 * 1_650, 2 * 5_300)


def test_maine_standard_deduction_phases_out_by_fraction():
    result = run("ME", state_agi=140_000, federal_agi=140_000)
    assert result.deduction == pytest.approx(15_700 * (1 - 37_750 / 75_000))
    assert run("ME", state_agi=177_250, federal_agi=177_250).deduction == 0


def test_maine_itemized_limit_excludes_medical():
    cats = ItemizedCategories(real_estate_tax=12_000, state_local_income_tax=6_000,
                              mortgage_interest=20_000, charitable_cash=10_000, medical_expenses=8_000)
    result = run("ME", federal_agi=60_000, state_agi=60_000, itemized=cats,
                 federal_itemized_elected=True)
    # Medical 8,000 - 4,500; the other 42,000 is limited to $36,300.
    assert result.use_itemized and result.deduction == 3_500 + 36_300
    assert run("ME", federal_agi=60_000, state_agi=60_000, itemized=cats).deduction == 15_700


def test_maine_exemption_phase_out_and_2027_federal_deduction():
    high = run("ME", filing_status=MFJ, federal_agi=471_600, state_agi=471_600)
    assert high.exemption_deduction == pytest.approx(10_600 * 0.5)  # 62,500 / 125,000
    assert high.deduction == 0
    later = run("ME", tax_year=2027, inflation_factor=1.03, federal_standard_deduction=16_500)
    assert later.deduction == 16_500
    assert later.exemption_deduction == pytest.approx(5_300 * 1.03)


# --- Minnesota (Minn. Stat. 290.0121-.0123; 2026 inflation-adjusted amounts) --

def test_minnesota_standard_deduction_and_dependent_exemptions():
    assert run("MN").deduction == 15_300
    joint = run("MN", filing_status=MFJ, holder_age=66, spouse_age=68, dependent_count=2,
                federal_agi=100_000, state_agi=100_000)
    assert (joint.deduction, joint.exemption_deduction) == (30_600 + 2 * 1_600, 2 * 5_300)


def test_minnesota_deduction_limitation_bands():
    result = run("MN", federal_agi=400_000, state_agi=400_000)
    # 3% of 337,800 - 244,400 plus 10% of 400,000 - 337,800.
    assert result.deduction == pytest.approx(15_300 - (2_802 + 6_220))
    assert run("MN", federal_agi=1_200_000, state_agi=1_200_000).deduction == pytest.approx(15_300 * 0.2)


def test_minnesota_dependent_exemption_steps():
    result = run("MN", filing_status=MFJ, dependent_count=2, federal_agi=380_000, state_agi=380_000)
    # 13,300 over $366,700: six $2,500 steps of 2 points.
    assert result.exemption_deduction == pytest.approx(10_600 * 0.88)


def test_minnesota_itemized_with_property_tax_cap_and_limitation():
    cats = ItemizedCategories(real_estate_tax=14_000, state_local_income_tax=7_000,
                              mortgage_interest=9_000, charitable_cash=2_000, medical_expenses=15_000)
    result = run("MN", federal_agi=100_000, state_agi=100_000, itemized=cats)
    # Independent of the federal choice: medical 5,000 + taxes 10,000 + 9,000 + 2,000.
    assert result.use_itemized and result.deduction == 26_000
    high = run("MN", federal_agi=400_000, state_agi=400_000, itemized=cats)
    assert high.use_itemized and high.deduction == pytest.approx(21_000 - 9_022)


# --- New Mexico (2025 PIT-1 and PIT-ADJ instructions) -------------------------

def test_new_mexico_low_and_middle_income_exemption():
    result = run("NM", federal_agi=30_000, state_agi=30_000)
    assert result.deduction == 16_100
    assert result.exemption_deduction == pytest.approx(2_500 - 0.15 * 10_000)
    assert run("NM", federal_agi=36_667, state_agi=36_667).exemption_deduction == pytest.approx(0, abs=0.1)


def test_new_mexico_joint_dependents_and_age_exemptions():
    result = run("NM", filing_status=MFJ, holder_age=66, spouse_age=67, dependent_count=2,
                 federal_agi=40_000, state_agi=40_000, federal_standard_deduction=35_500)
    assert result.deduction == 35_500
    # Four exemptions of 2,500 - 1,000, one dependent after the first, two $4,000 age amounts.
    assert result.exemption_deduction == pytest.approx(4 * 1_500 + 4_000 + 2 * 4_000)


def test_new_mexico_itemized_adds_back_income_tax_up_to_excess_over_standard():
    cats = ItemizedCategories(state_local_income_tax=9_000, real_estate_tax=6_000)
    base = dict(federal_agi=120_000, state_agi=120_000, itemized=cats, federal_itemized_elected=True)
    assert run("NM", federal_itemized_total=30_000, **base).deduction == 30_000 - 9_000
    limited = run("NM", federal_itemized_total=20_000, **base)
    assert limited.use_itemized and limited.deduction == 16_100
    assert run("NM", **{**base, "federal_itemized_elected": False}).deduction == 16_100

"""Statutory examples for coastmath.engine.state_deduction_rules.

Expected values are worked by hand from the state forms and statutes listed in
`_sources` in `state_deduction_rules_2026.json`, not from the evaluator.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from coastmath.engine.state_deduction_rules import (
    COVERAGE_VALUES,
    FederalTaxComponents,
    ItemizedCategories,
    StateDeductionContext,
    evaluate_state_deductions,
    state_rule_coverage,
    uses_federal_tax_deduction,
)

DATA = Path(__file__).resolve().parents[1] / "coastmath" / "data"
RULES = json.loads((DATA / "state_deduction_rules_2026.json").read_text())
BRACKETS = json.loads((DATA / "tax_brackets_2026.json").read_text())

S, MFJ, MFS, HOH = "single", "married_filing_jointly", "married_filing_separately", "head_of_household"


def ctx(state, **overrides):
    base = dict(
        state_code=state, tax_year=2026, inflation_factor=1.0, filing_status=S,
        holder_age=45, spouse_age=None, dependent_count=0, federal_agi=50_000.0,
        state_agi=50_000.0, itemized=ItemizedCategories(), federal_itemized_elected=False,
        federal_itemized_total=0.0, federal_standard_deduction=16_100.0,
        federal_income_tax_liability=0.0, payroll_taxes_withheld=0.0,
    )
    base.update(overrides)
    return StateDeductionContext(**base)


# --- Alabama ---------------------------------------------------------------

@pytest.mark.parametrize("status,agi,expected", [
    # 2025 Form 40 booklet p.9 chart rows.
    (S, 25_999, 3_000), (S, 26_000, 2_975), (S, 30_000, 2_775), (S, 35_499, 2_525),
    (S, 35_500, 2_500), (S, 90_000, 2_500),
    (MFJ, 25_999, 8_500), (MFJ, 26_000, 8_325), (MFJ, 35_499, 5_175), (MFJ, 35_500, 5_000),
    (HOH, 30_250, 3_985), (HOH, 35_500, 2_500),
    (MFS, 12_999, 4_250), (MFS, 13_000, 4_162), (MFS, 17_749, 2_578), (MFS, 17_750, 2_500),
])
def test_alabama_standard_deduction_chart(status, agi, expected):
    result = evaluate_state_deductions(ctx("AL", filing_status=status, state_agi=agi))
    assert result.supported and not result.use_itemized
    assert result.deduction == expected
    assert result.source_year == 2025


@pytest.mark.parametrize("status,agi,dependents,expected", [
    (S, 40_000, 0, 1_500), (MFS, 40_000, 1, 2_500), (MFJ, 50_000, 2, 5_000),
    (MFJ, 50_001, 2, 4_000), (HOH, 100_000, 1, 3_500), (HOH, 100_001, 3, 3_900),
])
def test_alabama_personal_and_dependent_exemptions(status, agi, dependents, expected):
    result = evaluate_state_deductions(
        ctx("AL", filing_status=status, state_agi=agi, dependent_count=dependents))
    assert result.exemption_deduction == expected


def test_alabama_itemized_excludes_state_income_tax_and_adds_payroll():
    cats = ItemizedCategories(
        state_local_income_tax=5_000, local_income_tax=1_000, real_estate_tax=6_000,
        mortgage_interest=8_000, charitable_cash=2_000, medical_expenses=10_000)
    result = evaluate_state_deductions(ctx(
        "AL", state_agi=100_000, federal_agi=110_000, itemized=cats,
        payroll_taxes_withheld=7_650))
    # Medical 10,000 - 4% x 100,000 = 6,000; local occupational tax 1,000;
    # real estate 6,000; FICA 7,650; mortgage 8,000; charity 2,000.
    assert result.use_itemized
    assert result.deduction == pytest.approx(30_650)


def test_alabama_property_taxes_capped_on_alabama_agi():
    cats = ItemizedCategories(real_estate_tax=50_000)
    result = evaluate_state_deductions(ctx("AL", state_agi=700_000, itemized=cats))
    # 2026 cap 40,400 - 30% x (700,000 - 505,000) < 10,000 floor.
    assert result.deduction == pytest.approx(10_000)


def test_alabama_missing_payroll_is_reported():
    cats = ItemizedCategories(mortgage_interest=20_000)
    result = evaluate_state_deductions(ctx("AL", itemized=cats, payroll_taxes_withheld=None))
    assert result.deduction == 20_000
    assert any("payroll" in note for note in result.diagnostics)


def test_alabama_federal_tax_deduction_worksheet():
    parts = FederalTaxComponents(net_investment_income_tax=500, additional_child_tax_credit=1_000,
                                 excess_advance_premium_tax_credit_repayment=300)
    result = evaluate_state_deductions(ctx(
        "AL", federal_income_tax_liability=12_000, federal_components=parts))
    # Worksheet lines 1-6: 12,300 + 500 - 1,000; no cap.
    assert result.federal_tax_subtraction == pytest.approx(11_800)
    refund_heavy = FederalTaxComponents(earned_income_credit=3_000)
    result = evaluate_state_deductions(ctx(
        "AL", federal_income_tax_liability=1_000, federal_components=refund_heavy))
    assert result.federal_tax_subtraction == 0.0


# --- Missouri --------------------------------------------------------------

@pytest.mark.parametrize("mo_agi,rate", [
    (22_450, 0.35), (25_000, 0.35), (25_001, 0.25), (50_000, 0.25), (58_750, 0.15),
    (100_000, 0.15), (100_001, 0.05), (125_000, 0.05), (125_001, 0.0),
])
def test_missouri_federal_tax_percentage(mo_agi, rate):
    result = evaluate_state_deductions(ctx(
        "MO", state_agi=mo_agi - 6_000, state_agi_before_retirement_exclusions=mo_agi,
        federal_income_tax_liability=4_000))
    assert result.federal_tax_subtraction == pytest.approx(4_000 * rate)
    assert not result.diagnostics


@pytest.mark.parametrize("status,cap", [(S, 5_000), (MFS, 5_000), (HOH, 5_000), (MFJ, 10_000)])
def test_missouri_federal_tax_cap(status, cap):
    result = evaluate_state_deductions(ctx(
        "MO", filing_status=status, state_agi=20_000,
        state_agi_before_retirement_exclusions=20_000, federal_income_tax_liability=80_000))
    assert result.federal_tax_subtraction == cap


def test_missouri_liability_definition():
    parts = FederalTaxComponents(early_distribution_additional_tax=1_000, earned_income_credit=500,
                                 net_premium_tax_credit=200, additional_child_tax_credit=1_000)
    result = evaluate_state_deductions(ctx(
        "MO", state_agi=40_000, state_agi_before_retirement_exclusions=40_000,
        federal_income_tax_liability=5_000, federal_components=parts))
    # (5,000 + 1,000 - 500 - 200) x 25%; the additional child tax credit is
    # not on the MO-1040 line 9 list.
    assert result.federal_tax_subtraction == pytest.approx(5_300 * 0.25)


def test_missouri_percentage_falls_back_to_state_agi_with_note():
    result = evaluate_state_deductions(ctx(
        "MO", state_agi=24_000, federal_income_tax_liability=1_000))
    assert result.federal_tax_subtraction == pytest.approx(350)
    assert any("Missouri AGI" in note for note in result.diagnostics)


def test_missouri_standard_is_federal_and_hoh_exemption():
    result = evaluate_state_deductions(ctx(
        "MO", filing_status=HOH, federal_standard_deduction=24_150))
    assert (result.deduction, result.exemption_deduction) == (24_150, 1_400)
    big = ItemizedCategories(mortgage_interest=50_000)
    result = evaluate_state_deductions(ctx("MO", itemized=big, federal_itemized_total=50_000))
    # Missouri itemizes only when the federal return itemizes.
    assert not result.use_itemized and result.deduction == 16_100


def test_missouri_itemized_adds_payroll_and_removes_state_income_tax():
    cats = ItemizedCategories(state_local_income_tax=8_000, local_income_tax=1_000,
                              real_estate_tax=4_000, mortgage_interest=18_000)
    result = evaluate_state_deductions(ctx(
        "MO", itemized=cats, federal_itemized_elected=True, federal_itemized_total=30_000,
        payroll_taxes_withheld=7_650, federal_agi=100_000))
    # MO-A Part 2: 30,000 + 7,650 - (8,000 - 1,000 earnings tax).
    assert result.use_itemized
    assert result.deduction == pytest.approx(30_650)


def test_missouri_capped_salt_uses_proportional_state_income_tax():
    cats = ItemizedCategories(state_local_income_tax=50_000, real_estate_tax=10_000)
    result = evaluate_state_deductions(ctx(
        "MO", filing_status=MFJ, itemized=cats, federal_itemized_elected=True,
        federal_itemized_total=70_400, federal_agi=200_000, federal_standard_deduction=32_200))
    # Worksheet: 40,400 allowed x 50,000 / 60,000 = 33,666.67 removed.
    assert result.deduction == pytest.approx(70_400 - 40_400 * 50_000 / 60_000)


# --- Oregon ----------------------------------------------------------------

@pytest.mark.parametrize("status,holder,spouse,expected", [
    (S, 40, None, 2_910), (S, 65, None, 4_110), (MFJ, 66, 70, 7_820),
    (MFJ, 66, 50, 6_820), (MFS, 66, 70, 3_910), (HOH, 67, None, 5_885),
])
def test_oregon_standard_deduction(status, holder, spouse, expected):
    result = evaluate_state_deductions(ctx(
        "OR", filing_status=status, holder_age=holder, spouse_age=spouse))
    assert result.deduction == expected and result.source_year == 2026


def test_oregon_head_of_household_uses_the_final_2026_figure():
    # 2026 Combined Payroll Tax Report instructions: $4,685 head of household.
    result = evaluate_state_deductions(ctx("OR", filing_status=HOH))
    assert result.deduction == 4_685
    assert not any("estimate" in note for note in result.diagnostics)


@pytest.mark.parametrize("status,agi,expected", [
    # OR-17 Table 9 steps at the 2026 cap of 8,750.
    (S, 124_999, 8_750), (S, 125_000, 7_000), (S, 129_999, 7_000), (S, 130_000, 5_250),
    (S, 140_000, 1_750), (S, 144_999, 1_750), (S, 145_000, 0),
    (MFS, 124_999, 4_375), (MFS, 125_000, 3_500),
    (MFJ, 249_999, 8_750), (MFJ, 250_000, 7_000), (HOH, 289_999, 1_750), (MFJ, 290_000, 0),
])
def test_oregon_federal_tax_subtraction_steps(status, agi, expected):
    result = evaluate_state_deductions(ctx(
        "OR", filing_status=status, federal_agi=agi, state_agi=agi,
        federal_income_tax_liability=40_000))
    assert result.federal_tax_subtraction == pytest.approx(expected)


def test_oregon_liability_definition():
    parts = FederalTaxComponents(
        early_distribution_additional_tax=400, refundable_american_opportunity_credit=1_000,
        premium_tax_credit_allowed=500, earned_income_credit=2_000,
        excess_advance_premium_tax_credit_repayment=900)
    result = evaluate_state_deductions(ctx(
        "OR", federal_income_tax_liability=6_000, federal_components=parts))
    # Federal tax worksheet: 6,000 + 400 - 1,000 - 500; EITC and excess advance
    # premium credit repayment are left out.
    assert result.federal_tax_subtraction == pytest.approx(4_900)


@pytest.mark.parametrize("status,agi,dependents,expected", [
    (S, 100_000, 0, 263), (S, 100_001, 0, 0), (MFS, 100_001, 0, 0),
    (MFJ, 200_000, 2, 1_052), (MFJ, 200_001, 2, 0), (HOH, 150_000, 1, 526),
])
def test_oregon_exemption_credit_cliff(status, agi, dependents, expected):
    result = evaluate_state_deductions(ctx(
        "OR", filing_status=status, federal_agi=agi, state_agi=agi, dependent_count=dependents))
    assert result.nonrefundable_credit == expected
    assert result.exemption_deduction == 0


def test_oregon_itemized_excludes_oregon_income_tax_and_payroll():
    cats = ItemizedCategories(
        state_local_income_tax=7_000, local_income_tax=500, real_estate_tax=5_000,
        mortgage_interest=6_000, charitable_cash=1_000, medical_expenses=9_000)
    result = evaluate_state_deductions(ctx(
        "OR", federal_agi=100_000, state_agi=95_000, itemized=cats,
        payroll_taxes_withheld=7_650))
    # 1,500 medical (over 7.5% of federal AGI) + 500 local + 5,000 + 6,000 + 1,000.
    assert result.use_itemized
    assert result.deduction == pytest.approx(14_000)


def test_oregon_itemization_does_not_require_federal_itemizing():
    cats = ItemizedCategories(mortgage_interest=10_000)
    result = evaluate_state_deductions(ctx("OR", itemized=cats, federal_itemized_elected=False))
    assert result.use_itemized and result.deduction == 10_000


def test_oregon_later_year_indexing_keeps_thresholds():
    result = evaluate_state_deductions(ctx(
        "OR", tax_year=2027, inflation_factor=1.03, federal_agi=125_000,
        federal_income_tax_liability=40_000))
    assert result.deduction == pytest.approx(2_910 * 1.03)
    assert result.federal_tax_subtraction == pytest.approx(8_750 * 1.03 * 0.8)
    assert result.diagnostics


def test_oregon_before_published_year_is_not_supported():
    result = evaluate_state_deductions(ctx("OR", tax_year=2025))
    assert not result.supported and result.deduction == 0


# --- Connecticut -----------------------------------------------------------

@pytest.mark.parametrize("status,agi,expected", [
    (S, 30_000, 15_000), (S, 30_000.01, 14_000), (S, 31_000, 14_000), (S, 31_001, 13_000),
    (S, 44_000, 1_000), (S, 44_001, 0), (MFS, 30_000, 6_000), (HOH, 38_000, 19_000),
    (HOH, 40_500, 16_000), (MFJ, 48_000, 24_000), (MFJ, 60_500, 11_000), (MFJ, 80_000, 0),
])
def test_connecticut_exemption_phaseout(status, agi, expected):
    result = evaluate_state_deductions(ctx("CT", filing_status=status, state_agi=agi))
    assert result.exemption_deduction == expected
    assert result.deduction == 0 and not result.use_itemized


# --- Wisconsin -------------------------------------------------------------

@pytest.mark.parametrize("status,income,expected", [
    # 2026 Form 1-ES instructions, standard deduction schedules.
    (S, 15_000, 13_960), (S, 20_120, 13_960), (S, 50_000, 13_960 - 0.12 * 29_880),
    (MFJ, 60_000, 25_840 - 0.19778 * 30_960), (MFS, 20_000, 12_280 - 0.19778 * 6_220),
    (HOH, 40_000, 18_030 - 0.22515 * 19_880),
    # Above $58,827 the head-of-household schedule switches to the single one.
    (HOH, 80_000, 13_960 - 0.12 * 59_880),
])
def test_wisconsin_sliding_standard_deduction_2026(status, income, expected):
    result = evaluate_state_deductions(ctx("WI", filing_status=status, state_agi=income))
    assert result.deduction == pytest.approx(expected, abs=0.01)
    assert not result.use_itemized and result.source_year == 2026


def test_wisconsin_standard_deduction_reaches_zero():
    # The single schedule ends at $136,453.
    assert evaluate_state_deductions(ctx("WI", state_agi=136_454)).deduction == 0


@pytest.mark.parametrize("status,holder,spouse,dependents,expected", [
    (S, 40, None, 0, 700), (S, 70, None, 1, 1_650), (MFJ, 67, 68, 2, 3_300),
    (HOH, 66, 70, 1, 1_650), (MFS, 50, 70, 0, 700),
])
def test_wisconsin_exemptions(status, holder, spouse, dependents, expected):
    result = evaluate_state_deductions(ctx(
        "WI", filing_status=status, holder_age=holder, spouse_age=spouse,
        dependent_count=dependents))
    assert result.exemption_deduction == expected


def test_wisconsin_itemized_amounts_are_a_credit_not_a_deduction():
    cats = ItemizedCategories(medical_expenses=10_000, mortgage_interest=9_000,
                              charitable_cash=2_000, real_estate_tax=8_000,
                              state_local_income_tax=5_000)
    result = evaluate_state_deductions(ctx(
        "WI", federal_agi=80_000, state_agi=80_000, itemized=cats))
    standard = 13_960 - 0.12 * (80_000 - 20_120)
    # Schedule 1: (4,000 medical + 9,000 interest + 2,000 charity) - standard; taxes excluded.
    assert not result.use_itemized
    assert result.deduction == pytest.approx(standard)
    assert result.nonrefundable_credit == pytest.approx(0.05 * (15_000 - standard))


def test_wisconsin_future_indexing_rounds_to_ten_dollars():
    result = evaluate_state_deductions(ctx(
        "WI", tax_year=2027, inflation_factor=1.03, state_agi=10_000))
    assert result.deduction == 14_380  # 13,960 x 1.03 = 14,378.8


# --- Coverage, repeal guards and baseline behaviour -------------------------

def test_every_state_has_a_coverage_row():
    assert set(RULES["coverage"]) == set(BRACKETS["state"])
    assert set(RULES["coverage"].values()) <= set(COVERAGE_VALUES)
    supported = {code for code, value in RULES["coverage"].items() if value == "supported"}
    assert supported == set(RULES["states"])
    for code, data in BRACKETS["state"].items():
        if not data.get("brackets"):
            assert RULES["coverage"][code] == "not_applicable", code


def test_cited_coverage_matrix_matches_data():
    matrix = next(section for section in RULES["_sources"] if section["section"] == "All-state coverage matrix")
    rows = {row["state"]: row["coverage"] for row in matrix["content"] if isinstance(row, dict) and "coverage" in row}
    assert rows == RULES["coverage"]


@pytest.mark.parametrize("state", ["CA", "OH", "SC", "TX", "IA", "LA", "MT", "ZZ"])
def test_unsupported_states_keep_the_existing_path(state):
    result = evaluate_state_deductions(ctx(state, federal_income_tax_liability=10_000))
    assert not result.supported
    assert (result.deduction, result.exemption_deduction, result.federal_tax_subtraction,
            result.nonrefundable_credit) == (0, 0, 0, 0)
    assert result.coverage == state_rule_coverage(state)


@pytest.mark.parametrize("state,year,expected", [
    ("AL", 2026, True), ("MO", 2026, True), ("OR", 2030, True), ("CT", 2026, False),
    ("IA", 2022, True), ("IA", 2023, False), ("LA", 2021, True), ("LA", 2022, False),
    ("MT", 2023, True), ("MT", 2024, False), ("MT", 2026, False), ("CA", 2026, False),
])
def test_federal_tax_deduction_repeal_guards(state, year, expected):
    assert uses_federal_tax_deduction(state, year) is expected


def test_paid_and_refund_inputs_do_not_change_liability_states():
    base = ctx("OR", federal_income_tax_liability=5_000)
    with_cash = dataclasses.replace(base, federal_income_tax_paid=9_000,
                                    federal_income_tax_refund_received=2_000)
    plain, cash = evaluate_state_deductions(base), evaluate_state_deductions(with_cash)
    assert plain.federal_tax_subtraction == cash.federal_tax_subtraction == 5_000
    assert any("liability" in note for note in cash.diagnostics)


def test_unknown_filing_status_is_not_supported():
    result = evaluate_state_deductions(ctx("AL", filing_status="qualifying_surviving_spouse"))
    assert not result.supported


def test_data_tables_cover_every_filing_status():
    statuses = {S, MFJ, MFS, HOH}
    for code, rule in RULES["states"].items():
        for key in ("standard_deduction", "personal_exemption"):
            table = rule.get(key)
            if isinstance(table, dict) and "amount" in table:
                table = table["amount"]
            if isinstance(table, dict):
                assert set(table) == statuses, (code, key)
        fed = rule.get("federal_tax_deduction")
        if fed and isinstance(fed.get("cap"), dict):
            assert set(fed["cap"]) == statuses, code
        if fed:
            names = {f.name for f in dataclasses.fields(FederalTaxComponents)}
            assert set(fed["adds"]) | set(fed["subtracts"]) <= names, code

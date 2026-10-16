"""State treatment of federally taxable Social Security benefits.

Rules are data (``social_security_subtraction`` in tax_brackets_2026.json);
sources are in the "State Social Security treatment" section of
`_sources` in `tax_brackets_2026.json`. Expected values are worked from the statutes.
"""

import json
from pathlib import Path

import pytest

from coastmath.engine.state_retirement_exclusion import RetirementIncome
from coastmath.engine.state_social_security import (
    SocialSecurityContext,
    state_social_security_subtraction,
)
from coastmath.engine.tax_engine import _calculate_state_tax, calculate

_DATA = json.loads((Path(__file__).resolve().parents[1] / "coastmath" / "data" / "tax_brackets_2026.json").read_text())
_RULES = {code: state.get("social_security_subtraction") for code, state in _DATA["state"].items()}


def _context(agi, taxable=20_000.0, gross=30_000.0, status="single", **kwargs):
    return SocialSecurityContext(
        filing_status=status, taxable_social_security=taxable, social_security_income=gross,
        federal_agi=agi, modified_agi_86=kwargs.pop("modified_agi_86", agi - taxable),
        provisional_excess=kwargs.pop("provisional_excess", 0.0), **kwargs)


def test_every_broad_income_tax_state_has_a_rule():
    taxing = {code for code, state in _DATA["state"].items() if state.get("brackets")}
    assert taxing == {code for code, rule in _RULES.items() if rule}


def test_states_taxing_benefits_in_2026_are_the_expected_set():
    taxing = {code for code, rule in _RULES.items() if rule and rule["type"] != "full"}
    assert taxing == {"CO", "CT", "MN", "MT", "NM", "RI", "UT", "VT"}
    # Colorado's subtraction stays in its retirement-income rule (one source of truth).
    assert _RULES["CO"]["type"] == "retirement_exclusion"
    assert _DATA["state"]["CO"]["retirement_income_exclusion"]["components"][0]["social_security"] == "colorado"


@pytest.mark.parametrize(("state", "rate"), [("IL", 0.0495), ("PA", 0.0307), ("GA", 0.0499)])
def test_flat_rate_states_fully_subtract_taxable_benefits(state, rate):
    result = calculate(gross_income=40_000, deductions=0, filing_status="single",
                       state_code=state, social_security_income=30_000)
    assert result.taxable_social_security > 0
    assert result.state_social_security_subtraction == pytest.approx(result.taxable_social_security)
    deduction = float(_DATA["state"][state]["standard_deduction"])
    # Only the $40,000 of other income remains in the state base.
    assert result.state == pytest.approx(rate * max(0.0, 40_000 - deduction), abs=0.01)


def test_new_york_taxes_the_same_base_as_without_benefits():
    with_ss = calculate(gross_income=60_000, deductions=0, filing_status="single",
                        state_code="NY", social_security_income=30_000)
    without = _calculate_state_tax(60_000, "NY")
    assert with_ss.state_social_security_subtraction == pytest.approx(with_ss.taxable_social_security)
    assert with_ss.state == pytest.approx(without, abs=0.01)


def test_california_and_ohio_outputs_do_not_change():
    # Schedule CA line 6b and the Ohio subtraction already removed taxable SS.
    assert _calculate_state_tax(104_000, "CA", taxable_social_security=34_000) == pytest.approx(
        _calculate_state_tax(70_000, "CA"))
    assert _calculate_state_tax(104_000, "OH", taxable_social_security=34_000) == pytest.approx(
        _calculate_state_tax(70_000, "OH"))


def test_custom_brackets_keep_their_semantics():
    custom = [[999_999_999, 0.05]]
    # California custom brackets still subtract taxable benefits; others do not.
    assert _calculate_state_tax(100_000, "CA", custom, taxable_social_security=20_000) == pytest.approx(
        _calculate_state_tax(80_000, "CA", custom))
    for state in ("OH", "NY", "IL", "VT"):
        assert _calculate_state_tax(100_000, state, custom, taxable_social_security=20_000) == pytest.approx(
            _calculate_state_tax(100_000, state, custom))
    result = calculate(gross_income=40_000, deductions=0, filing_status="single", state_code="IL",
                       social_security_income=30_000, settings={"state_brackets": custom})
    assert result.state_social_security_subtraction == 0.0


def test_montana_taxes_benefits_as_the_federal_return_does():
    assert state_social_security_subtraction(_RULES["MT"], _context(60_000)) == 0.0


@pytest.mark.parametrize(("status", "agi", "expected"), [
    # 32 V.S.A. 5830e(a)(1): full at or below $55,000, none at $65,000.
    ("single", 55_000, 20_000), ("single", 60_000, 10_000), ("single", 62_500, 5_000),
    ("single", 65_000, 0), ("head_of_household", 58_000, 14_000),
    # (a)(2): joint $70,000 to $80,000.
    ("married_filing_jointly", 70_000, 20_000), ("married_filing_jointly", 72_500, 15_000),
    ("married_filing_jointly", 80_000, 0),
])
def test_vermont_phases_out_over_ten_thousand(status, agi, expected):
    assert state_social_security_subtraction(_RULES["VT"], _context(agi, status=status)) == pytest.approx(expected)


@pytest.mark.parametrize(("status", "agi", "expected"), [
    # NMSA 7-2-5.14: full exemption up to $100,000 single, $150,000 joint
    # and head of household, $75,000 separate; nothing above.
    ("single", 100_000, 20_000), ("single", 100_001, 0),
    ("married_filing_jointly", 150_000, 20_000), ("married_filing_jointly", 150_001, 0),
    ("head_of_household", 149_000, 20_000), ("married_filing_separately", 75_001, 0),
])
def test_new_mexico_income_cliff(status, agi, expected):
    assert state_social_security_subtraction(_RULES["NM"], _context(agi, status=status)) == pytest.approx(expected)


def test_new_mexico_thresholds_are_unindexed():
    later = _context(120_000, inflation_factor=1.5)
    assert state_social_security_subtraction(_RULES["NM"], later) == 0.0


def test_minnesota_simplified_subtraction_steps_down():
    rule = _RULES["MN"]
    # 2026 joint threshold $110,780; 10% per $4,000 or fraction above it.
    assert state_social_security_subtraction(rule, _context(110_780, status="married_filing_jointly",
                                                            modified_agi_86=200_000)) == pytest.approx(20_000)
    # $4,001 above: two steps (a fraction counts), 80% remains.
    assert state_social_security_subtraction(rule, _context(114_781, status="married_filing_jointly",
                                                            modified_agi_86=200_000)) == pytest.approx(16_000)
    # Married filing separately: $2,000 steps above $55,390.
    assert state_social_security_subtraction(rule, _context(59_390, status="married_filing_separately",
                                                            modified_agi_86=200_000)) == pytest.approx(16_000)
    # Fully phased out after ten steps.
    assert state_social_security_subtraction(rule, _context(150_780, status="married_filing_jointly",
                                                            modified_agi_86=200_000)) == 0.0
    # The indexed threshold rises with the state factor.
    assert state_social_security_subtraction(rule, _context(114_781, status="married_filing_jointly",
                                                            modified_agi_86=200_000,
                                                            inflation_factor=1.1)) == pytest.approx(20_000)


def test_minnesota_alternate_subtraction_when_larger():
    rule = _RULES["MN"]
    # Single, AGI far above the simplified range; provisional income
    # $70,000 + $10,000 = $80,000: $4,560 - 20% x ($80,000 - $69,250) = $2,410.
    context = _context(200_000, modified_agi_86=70_000)
    assert state_social_security_subtraction(rule, context) == pytest.approx(2_410)
    # Never more than the taxable benefits.
    small = _context(200_000, taxable=1_000, modified_agi_86=10_000)
    assert state_social_security_subtraction(rule, small) == pytest.approx(1_000)


def test_connecticut_threshold_and_twenty_five_percent_rule():
    rule = _RULES["CT"]
    # CGS 12-701(a)(20)(B)(x)(III): below $75,000 single the taxable benefits are subtracted.
    assert state_social_security_subtraction(rule, _context(74_999)) == pytest.approx(20_000)
    # (IV): at or above it, taxable less min(25% of benefits, 25% of the 86(b)(1) excess).
    assert state_social_security_subtraction(rule, _context(75_000, provisional_excess=60_000)) == pytest.approx(
        20_000 - 7_500)
    assert state_social_security_subtraction(rule, _context(75_000, provisional_excess=20_000)) == pytest.approx(
        20_000 - 5_000)
    # Joint and head of household use $100,000.
    assert state_social_security_subtraction(rule, _context(99_999, status="married_filing_jointly")) == 20_000


def test_connecticut_end_to_end_excess():
    # Single: $90,000 pension plus $30,000 SS. Modified AGI $90,000; excess =
    # $90,000 + $15,000 - $25,000 = $80,000. Taxable SS is 85% = $25,500;
    # CT keeps min(25% x 30,000, 25% x 80,000) = $7,500 taxable.
    result = calculate(gross_income=90_000, deductions=0, filing_status="single",
                       state_code="CT", social_security_income=30_000)
    assert result.taxable_social_security == pytest.approx(25_500)
    assert result.state_social_security_subtraction == pytest.approx(18_000)


def test_rhode_island_requires_full_retirement_age_per_person():
    rule = _RULES["RI"]
    persons = (RetirementIncome(age=68, social_security=20_000), RetirementIncome(age=63, social_security=10_000))
    context = _context(90_000, status="married_filing_jointly", persons=persons)
    # Two thirds of the benefits belong to the person at 67+.
    assert state_social_security_subtraction(rule, context) == pytest.approx(20_000 * 2 / 3)
    over = _context(133_751, status="married_filing_jointly", persons=persons)
    assert state_social_security_subtraction(rule, over) == 0.0


def test_utah_credit_is_modeled_as_the_equivalent_subtraction():
    rule = _RULES["UT"]
    rate = 0.0445
    # Utah Code 59-10-1042: credit = rate x taxable benefits, less 2.5 cents per
    # dollar of modified AGI above $54,000 single.
    assert state_social_security_subtraction(rule, _context(50_000, state_rate=rate)) == pytest.approx(20_000)
    reduced = state_social_security_subtraction(rule, _context(64_000, state_rate=rate))
    assert reduced * rate == pytest.approx(rate * 20_000 - 0.025 * 10_000)
    assert state_social_security_subtraction(rule, _context(200_000, state_rate=rate)) == 0.0
    # Tax-exempt interest counts in modified AGI.
    with_interest = state_social_security_subtraction(rule, _context(54_000, state_rate=rate,
                                                                     tax_exempt_interest=10_000))
    assert with_interest == pytest.approx(reduced)


def test_maryland_subtracts_benefits_alongside_the_pension_cap_reduction():
    persons = [RetirementIncome(age=70, amounts={"401k": 30_000}, social_security=30_000)]
    result = calculate(gross_income=0, deductions=0, filing_status="single", state_code="MD",
                       rmd_income=30_000, social_security_income=30_000, holder_age=70,
                       retirement_income=persons)
    # Maryland exempts all taxable benefits and still reduces the pension cap by them.
    assert result.state_social_security_subtraction == pytest.approx(result.taxable_social_security)
    cap = 41_200 - 30_000
    assert result.state_retirement_exclusion == pytest.approx(cap, rel=0.01)


def test_colorado_subtraction_is_not_doubled():
    persons = [RetirementIncome(age=70, amounts={}, social_security=30_000)]
    result = calculate(gross_income=40_000, deductions=0, filing_status="single", state_code="CO",
                       social_security_income=30_000, holder_age=70, retirement_income=persons)
    assert result.state_social_security_subtraction == 0.0
    assert result.state_retirement_exclusion == pytest.approx(result.taxable_social_security)

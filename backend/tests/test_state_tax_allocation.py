"""Independent arithmetic controls for the bounded 540NR-style estimate.

FTB Publication 1100 section B and Form 540NR lines 36–39 distinguish the
all-source rate, AGI deduction ratio, and taxable-income credit ratio:
https://www.ftb.ca.gov/forms/misc/1100.html
https://www.ftb.ca.gov/forms/2025/2025-540nr-booklet.html
These assert continuous native projection arithmetic, not rounded return parity.
"""

from dataclasses import asdict, replace

import pytest

from coastmath.engine.state_tax_allocation import (
    CAPartYearWageContext,
    allocate_ca_part_year_tax,
)
from coastmath.engine.tax_engine import calculate


def context(total=100_000, ca=25_000, *, destination="CA", **kwargs):
    return CAPartYearWageContext(
        total_w2_wages=total,
        ca_w2_wages=ca,
        residency_state_codes=("TX", "CA") if destination == "CA" else ("CA", destination),
        legacy_residual_in_ca=destination == "CA",
        **kwargs,
    )


def synthetic_allocation(ctx=None, **kwargs):
    # Independent toy schedule: 10% on the first $10k, 20% above.
    # $100k AGI minus $10k deduction -> $1k + $80k * .20 = $17k gross.
    inputs = dict(
        context=ctx or context(),
        all_source_agi=100_000,
        standard_deduction=10_000,
        gross_tax_on_total_taxable=17_000,
        all_source_exemption_credit=200,
        residual_components=(),
        surcharge_threshold=1_000_000,
    )
    inputs.update(kwargs)
    return allocate_ca_part_year_tax(**inputs)


@pytest.mark.parametrize("share", [0, .25, 1])
def test_zero_some_and_all_wages_use_income_ratios(share):
    result = synthetic_allocation(context(ca=100_000 * share))
    assert result.deduction_ratio == pytest.approx(share)
    assert result.allocated_deduction == pytest.approx(10_000 * share)
    assert result.ca_taxable_income == pytest.approx(90_000 * share)
    assert result.effective_rate == pytest.approx(17_000 / 90_000)
    assert result.exemption_credit_ratio == pytest.approx(share)
    assert result.allocated_exemption_credit == pytest.approx(200 * share)
    assert result.state_tax == pytest.approx(16_800 * share)
    assert any("residence" in warning for warning in result.diagnostics)
    assert any("four-decimal" in warning for warning in result.diagnostics)


def test_extra_non_ca_wages_increase_rate_without_increasing_ca_wages():
    # Same $25k CA wages; all-source actual wages rise from $50k to $100k.
    lower = synthetic_allocation(
        context(total=50_000), all_source_agi=50_000,
        gross_tax_on_total_taxable=7_000,
    )
    higher = synthetic_allocation()
    assert lower.ca_agi == higher.ca_agi == 25_000
    assert lower.state_tax == pytest.approx((7_000 - 200) * .5)
    assert higher.state_tax == pytest.approx((17_000 - 200) * .25)
    assert higher.effective_rate > lower.effective_rate
    assert higher.state_tax > lower.state_tax


def test_associated_deductions_follow_their_own_attribution_not_wage_ratio():
    # $100k wages/$30k CA, but $20k demonstrated deductions/$2k CA.
    # A=$80k, CA_AGI=$28k, ratio=.35 (neither wage ratio .30 nor deduction .10).
    result = synthetic_allocation(
        context(ca=30_000, conforming_wage_deductions=20_000,
                ca_conforming_wage_deductions=2_000),
        all_source_agi=80_000, gross_tax_on_total_taxable=13_000,
    )
    assert result.ca_agi == 28_000
    assert result.allocated_deduction == pytest.approx(3_500)
    assert result.ca_taxable_income == pytest.approx(24_500)
    assert result.exemption_credit_ratio == pytest.approx(24_500 / 70_000)
    assert result.allocated_exemption_credit == pytest.approx(70)
    assert result.state_tax == pytest.approx(4_480)


@pytest.mark.parametrize("all_source,deduction", [(0, 10_000), (5_000, 10_000), (10_000, 10_000)])
def test_zero_taxable_denominators_and_nonrefundable_credit(all_source, deduction):
    result = synthetic_allocation(
        context(total=all_source, ca=all_source / 2),
        all_source_agi=all_source, standard_deduction=deduction,
        gross_tax_on_total_taxable=0,
    )
    assert result.state_tax == 0
    assert result.exemption_credit_ratio == 0
    assert result.allocated_exemption_credit == 0
    assert result.effective_rate == 0


def test_credit_cannot_make_state_tax_negative():
    result = synthetic_allocation(all_source_exemption_credit=20_000)
    assert result.state_tax == 0


@pytest.mark.parametrize("destination,ca_agi", [("CA", 45_000), ("NV", 25_000)])
def test_positive_residual_enters_one_annual_rate_and_disclosed_legacy_base(destination, ca_agi):
    result = synthetic_allocation(
        context(destination=destination), all_source_agi=120_000,
        gross_tax_on_total_taxable=21_000,
        residual_components=(("pension", 12_000), ("gains", 8_000)),
    )
    assert result.ca_agi == ca_agi
    assert result.state_tax == pytest.approx((21_000 - 200) * ca_agi / 120_000)
    assert any("pension $12,000.00" in warning for warning in result.diagnostics)
    assert any("gains $8,000.00" in warning for warning in result.diagnostics)
    assert all("unresolved" in warning for warning in result.diagnostics[:2])


@pytest.mark.parametrize("changes,expected", [
    ({"ca_w2_wages": 100_001}, "attribution does not reconcile"),
    ({"total_w2_wages": float("nan")}, "invalid total W2 wages"),
    ({"ca_w2_wages": -1}, "invalid CA-attributed"),
    ({"conforming_wage_deductions": -1}, "invalid conforming"),
    ({"ca_conforming_wage_deductions": 1}, "attribution does not reconcile"),
    ({"residency_state_codes": ("CA", "NY")}, "counterpart"),
    ({"residency_state_codes": ("CA", "WA")}, "counterpart"),
    ({"residency_state_codes": ("CA", "TX", "NV")}, "counterpart"),
    ({"residency_state_codes": ("CA",)}, "counterpart"),
    ({"unsupported_reason": "unknown YTD state attribution"}, "unknown YTD state attribution"),
])
def test_invalid_context_returns_explicit_legacy_fallback(changes, expected):
    result = synthetic_allocation(replace(context(), **changes))
    assert result.state_tax is None
    assert expected in " ".join(result.diagnostics)
    assert "legacy annual selected-state tax estimate" in result.diagnostics[-1]


def test_offsetting_residual_components_cannot_cancel_into_valid_zero():
    result = synthetic_allocation(residual_components=(("pension", 10_000), ("loss", -10_000)))
    assert result.state_tax is None
    assert any("pension $10,000.00" in warning for warning in result.diagnostics)
    assert any("loss $-10,000.00" in warning for warning in result.diagnostics)
    assert "negative or nonfinite residual" in result.diagnostics[-1]


def test_missing_residual_component_is_not_silently_assigned():
    result = synthetic_allocation(all_source_agi=110_000)
    assert result.state_tax is None
    assert "residual components do not reconcile" in result.diagnostics[-1]


def ca_gross_tax_2025_single(taxable):
    # Independent literal oracle: FTB 2025 Schedule X (ordinary tax, <= $1M).
    # Test fixture values are intentional authority controls, not engine data.
    slices = [(11_079, .01), (26_264, .02), (41_452, .04), (57_542, .06),
              (72_724, .08), (371_479, .093), (445_771, .103),
              (742_953, .113), (1_000_000, .123)]
    lower = 0
    tax = 0
    for upper, rate in slices:
        if taxable > lower:
            tax += (min(taxable, upper) - lower) * rate
        lower = upper
    return tax


def test_native_ca_standard_deduction_and_exemption_are_each_allocated_once():
    result = calculate(
        100_000, 0, "single", state_code="CA",
        settings={"ca_exemption_eligible_owners": ["self"]},
        ca_part_year_context=context(),
    )
    expected = (ca_gross_tax_2025_single(100_000 - 5_706) - 153) / 4
    assert result.state == pytest.approx(expected)


def test_social_security_excluded_from_ca_rate_but_retained_for_credit_phaseout():
    # CA-law AGI $250k is below single $252,203 credit phaseout.
    # Federal AGI includes .85*$30k SS -> $275,500: ceil(23,297/2500)=10
    # steps of $6 reduce the $153 credit to $93. CA base excludes that SS.
    result = calculate(
        250_000, 0, "single", state_code="CA", social_security_income=30_000,
        settings={"ca_exemption_eligible_owners": ["self"]},
        ca_part_year_context=context(total=250_000, ca=125_000),
    )
    control = calculate(250_000, 0, "single", state_code="NV", social_security_income=30_000)
    assert result.taxable_social_security == 25_500
    assert result.modified_agi == 275_500
    assert result.state == pytest.approx((ca_gross_tax_2025_single(250_000 - 5_706) - 93) / 2)
    assert result.federal == control.federal
    assert result.agi == control.agi
    assert result.fica_tax == control.fica_tax


@pytest.mark.parametrize("year,annual_factor", [(2025, 1.4), (2026, 1.4), (2028, 1.1)])
def test_ca_to_nv_uses_ca_table_anchor_even_with_non_ca_destination(year, annual_factor):
    # All-source income is all CA-attributed: the new branch equals the native
    # full-CA control despite destination NV and unrelated economic inflation.
    kwargs = dict(
        gross_income=50_000, deductions=0, filing_status="single",
        tax_year=year, federal_inflation_factor=annual_factor, inflation_factor=1.8,
        settings={"ca_exemption_eligible_owners": ["self"]},
    )
    moved = calculate(**kwargs, state_code="NV", ca_part_year_context=context(50_000, 50_000, destination="NV"))
    full_ca = calculate(**kwargs, state_code="CA")
    assert moved.state == pytest.approx(full_ca.state)
    assert moved.state_allocation_diagnostics


@pytest.mark.parametrize("kwargs,expected", [
    ({"deductions": 1_000}, "unallocated or nonconforming deductions"),
    ({"capital_gains": -1_000, "rmd_income": 10_000}, "capital losses"),
    ({"capital_loss_carryforward": 1_000, "capital_gains": 10_000}, "loss carryforwards"),
    ({"qualified_dividends": -100}, "capital losses"),
    ({"is_self_employed": True}, "self-employment"),
    ({"self_employment_income": 1_000}, "self-employment"),
    ({"settings": {"state_brackets": [{"min": 0, "max": 999999999, "rate": .04}]}}, "custom state brackets"),
    ({"gross_income": 90_000, "rmd_income": 10_000}, "negative or nonfinite residual"),
    ({"state_code": "NY"}, "selected state conflicts"),
    ({"tax_year": 2024}, "before the supported 2025 anchor"),
])
def test_unsupported_tax_inputs_keep_identical_legacy_liability(kwargs, expected):
    inputs = dict(gross_income=100_000, deductions=0, filing_status="single", state_code="CA")
    inputs.update(kwargs)
    legacy = calculate(**inputs)
    candidate = calculate(**inputs, ca_part_year_context=context())
    assert candidate.state == legacy.state
    assert candidate.total_tax == legacy.total_tax
    assert expected in " ".join(candidate.state_allocation_diagnostics)
    assert "Retained the legacy" in candidate.state_allocation_diagnostics[-1]


@pytest.mark.parametrize("filing_status", ["single", "married_filing_jointly"])
def test_partial_high_income_guard_uses_undoubled_unindexed_surcharge_threshold(filing_status):
    kwargs = dict(
        gross_income=1_500_000, deductions=0, filing_status=filing_status,
        state_code="CA", tax_year=2028, federal_inflation_factor=1.2,
    )
    result = calculate(**kwargs, ca_part_year_context=context(1_500_000, 750_000))
    assert result.state == calculate(**kwargs).state
    assert "Behavioral Health surcharge" in result.state_allocation_diagnostics[-1]


def test_high_pre_move_only_wages_still_have_safe_zero_ca_base():
    result = calculate(
        1_500_000, 0, "single", state_code="CA",
        ca_part_year_context=context(1_500_000, 0),
    )
    assert result.state == 0
    assert not any("unsupported" in warning for warning in result.state_allocation_diagnostics)


def test_flat_mode_retains_explicit_blended_rate_and_diagnostic():
    kwargs = dict(
        gross_income=100_000, deductions=0, filing_status="single", state_code="CA",
        settings={"mode": "flat", "ordinary_income_tax_rate": .2},
    )
    legacy = calculate(**kwargs)
    moved = calculate(**kwargs, ca_part_year_context=context())
    assert moved.total_tax == legacy.total_tax == 20_000
    assert moved.state == 0
    assert "flat tax mode" in moved.state_allocation_diagnostics[0]


def test_omitted_and_explicit_none_context_are_identical():
    kwargs = dict(
        gross_income=100_000, deductions=5_000, filing_status="single", state_code="CA",
        social_security_income=12_000, capital_gains=5_000, rmd_income=10_000,
    )
    assert asdict(calculate(**kwargs)) == asdict(calculate(**kwargs, ca_part_year_context=None))
    assert calculate(**kwargs).state_allocation_diagnostics == ()

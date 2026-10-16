"""Tests for the tax engine inflation_factor threading (29.1.1)."""

import pytest

from coastmath.engine.tax_engine import (
    _calculate_taxable_social_security,
    _salt_cap_for_year,
    apply_progressive_brackets,
    calculate,
    calculate_amt,
    get_federal_brackets,
    get_standard_deduction,
)


class TestInflationFactorScalingInvariance:
    """Scaling invariance: for pure ordinary income with standard deduction,
    doubling both income and inflation_factor should double total_tax.

    This holds because all bracket bounds and the standard deduction scale
    linearly with inflation_factor, keeping the taxpayer in the same
    real bracket position.
    """

    @pytest.mark.parametrize("filing_status", [
        "single",
        "married_filing_jointly",
        "married_filing_separately",
        "head_of_household",
    ])
    def test_scaling_invariance_ordinary_income(self, filing_status: str) -> None:
        """Tax at 2X income + 2X inflation_factor == 2 * tax at 1X income."""
        base_income = 80_000.0

        result_1x = calculate(
            gross_income=base_income,
            deductions=0,
            filing_status=filing_status,
            inflation_factor=1.0,
        )

        result_2x = calculate(
            gross_income=base_income * 2,
            deductions=0,
            filing_status=filing_status,
            inflation_factor=2.0,
        )

        # Total tax should scale linearly (within float tolerance).
        # We compare only the components that are purely bracket-driven
        # (federal + standard deduction). FICA is zero because earned_income
        # defaults to 0 and NIIT is zero because net_investment_income is 0.
        assert result_2x.total_tax == pytest.approx(
            2 * result_1x.total_tax, rel=1e-9,
        ), (
            f"Expected 2 * {result_1x.total_tax} = {2 * result_1x.total_tax}, "
            f"got {result_2x.total_tax}"
        )

    def test_scaling_invariance_with_earned_income(self) -> None:
        """Scaling invariance also holds for FICA SS component (wage base scales)."""
        base_income = 100_000.0

        result_1x = calculate(
            gross_income=base_income,
            deductions=0,
            filing_status="single",
            earned_income=base_income,
            inflation_factor=1.0,
        )

        result_2x = calculate(
            gross_income=base_income * 2,
            deductions=0,
            filing_status="single",
            earned_income=base_income * 2,
            inflation_factor=2.0,
        )

        assert result_2x.total_tax == pytest.approx(
            2 * result_1x.total_tax, rel=1e-9,
        )

    def test_scaling_invariance_with_capital_gains(self) -> None:
        """LTCG bracket bounds also scale, so CG tax should scale linearly."""
        base_income = 50_000.0
        base_cg = 30_000.0

        result_1x = calculate(
            gross_income=base_income,
            deductions=0,
            filing_status="single",
            capital_gains=base_cg,
            inflation_factor=1.0,
        )

        result_2x = calculate(
            gross_income=base_income * 2,
            deductions=0,
            filing_status="single",
            capital_gains=base_cg * 2,
            inflation_factor=2.0,
        )

        assert result_2x.total_tax == pytest.approx(
            2 * result_1x.total_tax, rel=1e-9,
        )


class TestNIITFixedThresholds:
    """NIIT thresholds are statutorily unindexed -- they must NOT scale
    with inflation_factor.  A MAGI just under the threshold at factor=1.0
    should owe NIIT when the same *real* income is expressed in 2X
    nominal dollars (because the threshold stays at 200k nominal).
    """

    def test_niit_triggers_under_inflation(self) -> None:
        """Single filer: 190k NII + MAGI at factor=1.0 -> no NIIT.
        Same real income at factor=2.0 (380k nominal) -> NIIT owed."""
        # At factor=1.0: MAGI ~190k < 200k threshold -> zero NIIT
        result_no_inflation = calculate(
            gross_income=190_000.0,
            deductions=0,
            filing_status="single",
            net_investment_income=190_000.0,
            inflation_factor=1.0,
        )
        assert result_no_inflation.niit == 0.0, (
            f"Expected zero NIIT at MAGI ~190k, got {result_no_inflation.niit}"
        )

        # At factor=2.0: same real income = 380k nominal > 200k threshold
        result_with_inflation = calculate(
            gross_income=380_000.0,
            deductions=0,
            filing_status="single",
            net_investment_income=380_000.0,
            inflation_factor=2.0,
        )
        assert result_with_inflation.niit > 0.0, (
            "Expected NIIT > 0 when nominal MAGI 380k exceeds unscaled 200k threshold"
        )

    def test_niit_mfj_threshold_fixed(self) -> None:
        """MFJ: 240k at factor=1.0 -> no NIIT. 480k at factor=2.0 -> NIIT owed."""
        result_1x = calculate(
            gross_income=240_000.0,
            deductions=0,
            filing_status="married_filing_jointly",
            net_investment_income=240_000.0,
            inflation_factor=1.0,
        )
        assert result_1x.niit == 0.0

        result_2x = calculate(
            gross_income=480_000.0,
            deductions=0,
            filing_status="married_filing_jointly",
            net_investment_income=480_000.0,
            inflation_factor=2.0,
        )
        assert result_2x.niit > 0.0


class TestSocialSecurityThresholdsFixed:
    """SS provisional-income thresholds are statutorily unindexed.
    Under inflation, more SS becomes taxable even at constant real income.
    """

    def test_ss_taxable_fraction_increases_with_inflation(self) -> None:
        """At factor=1.0, SS may be partially taxable. At factor=2.0 with
        doubled nominal income, a larger fraction should be taxable because
        the provisional-income thresholds don't move."""
        # Use a moderate income level where SS is partially taxable
        result_1x = calculate(
            gross_income=20_000.0,
            deductions=0,
            filing_status="single",
            social_security_income=20_000.0,
            inflation_factor=1.0,
        )

        result_2x = calculate(
            gross_income=40_000.0,
            deductions=0,
            filing_status="single",
            social_security_income=40_000.0,
            inflation_factor=2.0,
        )

        # The taxable SS fraction should be higher at 2x because thresholds
        # are fixed while income doubled. We check via AGI which includes
        # taxable SS.
        # At 2x: AGI should be MORE than 2 * AGI_at_1x (bracket creep on SS).
        assert result_2x.agi > 2 * result_1x.agi, (
            f"Expected AGI at 2x ({result_2x.agi}) > 2 * AGI at 1x "
            f"({2 * result_1x.agi}) due to fixed SS thresholds"
        )


class TestInflationFactorDefault:
    """Verify that inflation_factor=1.0 (default) produces identical results
    to calls that omit the parameter, ensuring backward compatibility.
    """

    def test_default_matches_explicit_1x(self) -> None:
        result_default = calculate(
            gross_income=100_000.0,
            deductions=0,
            filing_status="single",
        )
        result_explicit = calculate(
            gross_income=100_000.0,
            deductions=0,
            filing_status="single",
            inflation_factor=1.0,
        )
        assert result_default.total_tax == result_explicit.total_tax
        assert result_default.federal == result_explicit.federal
        assert result_default.fica_tax == result_explicit.fica_tax
        assert result_default.niit == result_explicit.niit
        assert result_default.amt == result_explicit.amt
        assert result_default.standard_deduction == result_explicit.standard_deduction


class TestStandardDeductionScales:
    """Standard deduction should scale with inflation_factor."""

    def test_standard_deduction_doubled(self) -> None:
        result_1x = calculate(
            gross_income=50_000.0,
            deductions=0,
            filing_status="single",
            inflation_factor=1.0,
        )
        result_2x = calculate(
            gross_income=100_000.0,
            deductions=0,
            filing_status="single",
            inflation_factor=2.0,
        )
        assert result_2x.standard_deduction == pytest.approx(
            2 * result_1x.standard_deduction, rel=1e-9,
        )


class TestSSTaxabilityTier2Base:
    """31.1.4 — _calculate_taxable_social_security tier-2 base must be
    capped at 0.5 * SS per IRS Pub. 915 worksheet."""

    def test_small_ss_tier2_base_capped(self) -> None:
        """Single, SS=$8k, provisional=$35k (t2 + $1k).
        Correct: min(0.85*8000, min(0.5*8000, 4500) + 0.85*1000)
               = min(6800, 4000 + 850) = 4850.
        Before fix the code returned 5350 (used uncapped tier2_base=4500)."""
        result = _calculate_taxable_social_security(
            ss_income=8_000.0,
            other_income=31_000.0,   # provisional = 31000 + 0.5*8000 = 35000
            filing_status="single",
        )
        assert result == pytest.approx(4_850.0), (
            f"Expected 4850 for small-SS tier-2 case, got {result}"
        )

    def test_large_ss_085_cap_unchanged(self) -> None:
        """SS=$40k, high provisional — the 0.85*SS cap path must be unchanged.
        min(0.5*40000, 4500) = 4500 (same as before), so the fix is neutral
        for large SS. Result should be 0.85 * 40000 = 34000."""
        # other_income high enough that 0.85*SS is the binding cap
        result = _calculate_taxable_social_security(
            ss_income=40_000.0,
            other_income=80_000.0,   # provisional = 80000 + 20000 = 100000
            filing_status="single",
        )
        assert result == pytest.approx(0.85 * 40_000.0), (
            f"Expected 0.85 * 40000 = 34000 for large-SS cap path, got {result}"
        )


class TestAMTAddBackLogic:
    """31.1.1 — AMT add-back must reflect the deduction actually taken,
    not the state tax liability.

    Standard deduction filers: add back the full standard deduction (AMT
    disallows it entirely per IRC §56(b)(1)(E)).
    Itemizers: add back only the capped SALT component (IRC §56(b)(1)(A)).
    QBI deduction is allowed under AMT — no add-back needed.
    """

    def test_standard_deduction_filer_no_spurious_amt(self) -> None:
        """Single, $150k wages, CA, standard deduction.

        AMTI ≈ AGI (taxable_income + std_deduction ≈ 150k).
        At this income, regular tax should exceed tentative AMT, so
        federal == regular tax (no spurious AMT bump).
        Before the fix, state_tax was passed as the add-back, producing
        spurious AMT for high-tax-state standard-deduction filers.
        """
        result = calculate(
            gross_income=150_000.0,
            deductions=0,
            filing_status="single",
            state_code="CA",
        )

        assert result.deduction_used == "standard"

        # AMT tentative should use std deduction as addback
        std_ded = get_standard_deduction("single")
        expected_amt = calculate_amt(result.taxable_income, std_ded, "single")
        assert result.amt == pytest.approx(expected_amt, rel=1e-9), (
            f"AMT should use standard deduction ({std_ded}) as addback, "
            f"expected {expected_amt}, got {result.amt}"
        )

        # Regular tax must exceed tentative AMT at $150k — no spurious AMT
        brackets = get_federal_brackets("single")
        regular_tax = apply_progressive_brackets(result.taxable_income, brackets)
        assert regular_tax > result.amt, (
            f"Regular tax ({regular_tax}) should exceed AMT ({result.amt}) "
            f"at $150k — no spurious AMT expected"
        )
        assert result.federal == pytest.approx(regular_tax, rel=1e-9)

    def test_itemizer_addback_equals_capped_salt(self) -> None:
        """MFJ, $300k, itemizing with $40k SALT + $20k charitable.

        Addback should equal the capped SALT (not the full itemized amount
        and not the state tax liability).
        """
        result = calculate(
            gross_income=300_000.0,
            deductions=0,
            filing_status="married_filing_jointly",
            state_code="CA",
            itemized_deductions={"salt": 40_000, "property_tax": 0},
            charitable_deduction=20_000.0,
        )

        assert result.deduction_used == "itemized"

        # The SALT cap for 2026 MFJ at this income is $40,400, so capped_salt = 40k.
        salt_cap = _salt_cap_for_year(2026, "married_filing_jointly", 300_000.0)
        capped_salt = min(40_000.0, salt_cap)

        expected_amt = calculate_amt(
            result.taxable_income, capped_salt, "married_filing_jointly",
        )
        assert result.amt == pytest.approx(expected_amt, rel=1e-9), (
            f"AMT addback should be capped SALT ({capped_salt}), "
            f"expected amt={expected_amt}, got {result.amt}"
        )

    def test_high_earner_amt_exemption_phaseout(self) -> None:
        """Single, $1.5M — AMT exemption fully phases out.

        At this income, AMTI = 1.5M (taxable + std deduction addback).
        OBBBA 2026: phaseout at 50% above $500k.
        Phaseout: (1.5M - 500000) * 0.50 = 500000 > 90100 exemption → 0.
        AMT base = AMTI, two-rate: 244500 * 0.26 + remainder * 0.28.
        """
        result = calculate(
            gross_income=1_500_000.0,
            deductions=0,
            filing_status="single",
        )

        # Exemption must be fully phased out → AMT computed on full AMTI
        expected_amt = 244_500 * 0.26 + (1_500_000 - 244_500) * 0.28
        assert result.amt == pytest.approx(expected_amt, rel=1e-9), (
            f"At $1.5M, exemption is fully phased out. "
            f"Expected AMT={expected_amt}, got {result.amt}"
        )

        # AMT > 0 but regular tax is higher at this income
        assert result.amt > 0
        assert result.federal >= result.amt

    def test_amt_owed_is_zero_when_regular_tax_is_higher(self):
        """A $180,000 salary has a tentative minimum tax but owes no AMT; the
        snapshot's amt_tax reports the amount owed, which federal tax already includes."""
        result = calculate(gross_income=180_000.0, deductions=0, filing_status="single")
        assert result.amt > 20_000
        assert result.amt_excess == 0.0


class TestQBIDeductionWiring:
    """31.1.2 — QBI deduction is wired up for self-employment income."""

    def test_se_filer_gets_qbi_deduction(self) -> None:
        """$100k SE income, no W-2 → QBI deduction ~20% of (SE - se_fica_deduction)."""
        se_income = 100_000.0
        result = calculate(
            gross_income=se_income,
            deductions=0,
            filing_status="single",
            earned_income=se_income,
            is_self_employed=True,
            self_employment_income=se_income,
            w2_income=0.0,
            qualified_business_income=se_income,
        )

        assert result.qbi_deduction > 0, "SE filer must get a QBI deduction"

        # Schedule SE: $100,000 profit -> $92,350 earnings -> $14,129.55 tax.
        se_fica_deduction = 7064.775
        qbi_net = se_income - se_fica_deduction
        qbi_20pct = 0.20 * qbi_net
        # QBI is also capped at 20% of taxable income before QBI.
        std_ded = get_standard_deduction("single")
        taxable_before_qbi = se_income - se_fica_deduction - std_ded
        expected_qbi = min(qbi_20pct, 0.20 * taxable_before_qbi)

        assert result.qbi_deduction == pytest.approx(expected_qbi, rel=1e-6), (
            f"Expected QBI ~{expected_qbi:.2f}, got {result.qbi_deduction:.2f}"
        )

    def test_w2_only_filer_zero_qbi(self) -> None:
        """$100k W-2 income, no SE → QBI deduction must be zero."""
        result = calculate(
            gross_income=100_000.0,
            deductions=0,
            filing_status="single",
            earned_income=100_000.0,
            is_self_employed=False,
            w2_income=100_000.0,
            self_employment_income=0.0,
            qualified_business_income=0.0,
        )

        assert result.qbi_deduction == 0.0, (
            f"W-2-only filer should have zero QBI, got {result.qbi_deduction}"
        )


class TestSEFicaDeductionSharedBase:
    """31.1.3 — SE FICA deduction must share the SS wage base with W-2 wages.

    When W-2 income exhausts (or partially consumes) the SS wage base,
    the SE deduction must reflect only the remaining room, not a standalone
    calculation that ignores W-2 wages.
    """

    def test_base_exhausted_w2_200k_se_50k(self) -> None:
        """W-2 $200k (> $184.5k base) + SE $50k: no SS room for SE.

        Deduction = SE Medicare employer half on $46,175 earnings = $669.5375.
        """
        result = calculate(
            gross_income=250_000.0,  # W-2 + SE
            deductions=0,
            filing_status="single",
            earned_income=250_000.0,
            w2_income=200_000.0,
            self_employment_income=50_000.0,
        )

        # Only regular Medicare on $46,175 adjusted SE earnings is deductible.
        expected_deduction = 669.5375
        # Verify AGI reflects the correct deduction
        expected_agi = 250_000.0 - expected_deduction
        assert result.agi == pytest.approx(expected_agi, rel=1e-9), (
            f"AGI should be 250k - {expected_deduction}, got {result.agi}"
        )

    def test_full_room_w2_100k_se_50k(self) -> None:
        """W-2 $100k + SE $50k: full SS room remains for SE.

        SE SS room = 184500 - 100000 = 84500 > 50000, so full SE is taxed.
        Deduction = half of $46,175 * 15.3% = $3,532.3875.
        """
        result = calculate(
            gross_income=150_000.0,  # W-2 + SE
            deductions=0,
            filing_status="single",
            earned_income=150_000.0,
            w2_income=100_000.0,
            self_employment_income=50_000.0,
        )

        # $50,000 profit -> $46,175 earnings; half of $7,064.775 regular SE tax.
        expected_deduction = 3532.3875
        expected_agi = 150_000.0 - expected_deduction
        assert result.agi == pytest.approx(expected_agi, rel=1e-9), (
            f"AGI should be 150k - {expected_deduction}, got {result.agi}"
        )

    def test_se_only_adjusted_earnings(self) -> None:
        """SE-only $100k profit: employer half uses adjusted $92,350 earnings."""
        result = calculate(
            gross_income=100_000.0,
            deductions=0,
            filing_status="single",
            earned_income=100_000.0,
            is_self_employed=True,
            w2_income=0.0,
            self_employment_income=100_000.0,
        )

        expected_deduction = 7064.775
        expected_agi = 100_000.0 - expected_deduction
        assert result.agi == pytest.approx(expected_agi, rel=1e-9), (
            f"AGI should be 100k - {expected_deduction}, got {result.agi}"
        )


class TestFlatTaxMode:
    """Fixed blended-rate plans bypass the automatic US tax stack."""

    def test_flat_tax_2026_taxable_income_components(self) -> None:
        result = calculate(
            gross_income=285_030.0,
            deductions=25_400.0,
            filing_status="married_filing_jointly",
            capital_gains=2_375.0,
            earned_income=285_000.0,
            state_code="AL",
            settings={
                "mode": "flat",
                "ordinary_income_tax_rate": 0.30,
                "capital_gains_tax_rate": 0.15,
            },
        )

        assert result.taxable_income == pytest.approx(259_630.0)
        assert result.federal == pytest.approx(77_889.0)
        assert result.capital_gains_tax == pytest.approx(356.25)
        assert result.total_tax == pytest.approx(78_245.25)
        assert result.state == 0.0
        assert result.fica_tax == 0.0
        assert result.amt == 0.0
        assert result.niit == 0.0
        assert result.deduction_used == "custom_flat"

    @pytest.mark.parametrize(
        "field,value",
        [
            ("ordinary_income_tax_rate", -0.01),
            ("ordinary_income_tax_rate", 1.01),
            ("capital_gains_tax_rate", -0.01),
            ("capital_gains_tax_rate", 1.01),
        ],
    )
    def test_flat_rates_must_be_decimal_fractions(self, field: str, value: float) -> None:
        settings = {
            "mode": "flat",
            "ordinary_income_tax_rate": 0.30,
            "capital_gains_tax_rate": 0.15,
        }
        settings[field] = value

        with pytest.raises(ValueError, match="must be between 0 and 1"):
            calculate(
                gross_income=100_000.0,
                deductions=0.0,
                filing_status="single",
                settings=settings,
            )

"""Unit tests for ACA premium tax credits and Medicare IRMAA."""

from itertools import pairwise

import pytest

from coastmath.engine.healthcare import (
    HealthcareSettingsData,
    age_curve_factor,
    applicable_percentage,
    calculate_medicare_premiums,
    calculate_premium_tax_credit,
    parse_healthcare_settings,
    poverty_line,
)
from coastmath.schemas.healthcare_settings import HealthcareSettings


class TestPovertyLine:
    def test_2025_guidelines_by_household_size(self):
        assert poverty_line(1) == 15_650
        assert poverty_line(2) == 21_150
        assert poverty_line(4) == 32_150
        assert poverty_line(2, "alaska") == 26_430
        assert poverty_line(1, "hawaii") == 17_990

    def test_indexes_with_inflation(self):
        assert poverty_line(1, inflation_factor=1.10) == pytest.approx(15_650 * 1.10)


class TestApplicablePercentage:
    def test_bands_from_rev_proc_2025_25(self):
        assert applicable_percentage(1.00) == pytest.approx(0.0210)
        assert applicable_percentage(1.32) == pytest.approx(0.0210)
        assert applicable_percentage(1.33) == pytest.approx(0.0314)
        # Linear interpolation inside a band: midpoint of 150-200% -> midpoint of 4.19%-6.60%
        assert applicable_percentage(1.75) == pytest.approx((0.0419 + 0.0660) / 2)
        assert applicable_percentage(2.50) == pytest.approx(0.0844)
        assert applicable_percentage(3.00) == pytest.approx(0.0996)
        assert applicable_percentage(3.99) == pytest.approx(0.0996)
        assert applicable_percentage(4.00) == pytest.approx(0.0996)

    def test_no_credit_outside_100_to_400_percent(self):
        assert applicable_percentage(0.99) is None
        assert applicable_percentage(4.01) is None  # 2026 cliff returns


class TestPremiumTaxCredit:
    def test_credit_is_benchmark_minus_expected_contribution(self):
        # Couple, MAGI $60k -> 283.7% FPL ($21,150) -> pct interpolated in 250-300% band
        r = calculate_premium_tax_credit(60_000, 2, benchmark_premium=24_000, gross_premium=22_000, covered_adults=2)
        assert r.eligible is True
        assert r.fpl_ratio == pytest.approx(60_000 / 21_150)
        expected_pct = 0.0844 + ((r.fpl_ratio - 2.5) / 0.5) * (0.0996 - 0.0844)
        assert r.applicable_percentage == pytest.approx(expected_pct)
        assert r.expected_contribution == pytest.approx(expected_pct * 60_000)
        assert r.credit == pytest.approx(24_000 - expected_pct * 60_000)
        assert r.net_premium == pytest.approx(22_000 - r.credit)

    def test_credit_capped_at_plan_premium(self):
        r = calculate_premium_tax_credit(25_000, 2, benchmark_premium=24_000, gross_premium=12_000, covered_adults=2)
        assert r.credit == pytest.approx(12_000)
        assert r.net_premium == 0

    def test_cliff_and_floor(self):
        above = calculate_premium_tax_credit(90_000, 2, 24_000, 24_000, covered_adults=2)
        assert above.eligible is False and above.credit == 0 and above.net_premium == 24_000
        assert "400%" in (above.reason or "")
        below = calculate_premium_tax_credit(10_000, 1, 8_000, 8_000, covered_adults=1)
        assert below.eligible is False and "100%" in (below.reason or "")

    def test_no_adults_means_no_premium(self):
        r = calculate_premium_tax_credit(50_000, 2, 24_000, 24_000, covered_adults=0)
        assert r.gross_premium == 24_000 and r.credit == 0 and r.eligible is False


    def test_married_filing_separately_gets_no_credit(self):
        # IRC 36B(c)(1)(C): a married taxpayer qualifies only on a joint return.
        # Joint control at the same inputs: 60,000 / 21,150 = 2.83688 FPL;
        # 8.44% + 0.67376 x 1.52% = 9.4641%; 24,000 - 5,678.47 = 18,321.53.
        joint = calculate_premium_tax_credit(60_000, 2, 24_000, 22_000, covered_adults=2,
                                             filing_status="married_filing_jointly")
        assert joint.credit == pytest.approx(18_321.53, abs=0.01)
        mfs = calculate_premium_tax_credit(60_000, 2, 24_000, 22_000, covered_adults=2,
                                           filing_status="married_filing_separately")
        assert mfs.eligible is False and mfs.credit == 0 and mfs.net_premium == 22_000
        assert "36B(c)(1)(C)" in (mfs.reason or "")
        # Partial-year coverage periods aggregate premiums but still allow no credit.
        part = calculate_premium_tax_credit(60_000, 2, 24_000, 22_000, covered_adults=2,
                                            filing_status="married_filing_separately",
                                            coverage_periods=[(24_000, 22_000, 0.5)])
        assert part.credit == 0 and part.gross_premium == pytest.approx(11_000)
        assert part.net_premium == pytest.approx(11_000) and part.benchmark_premium == pytest.approx(12_000)


class TestAgeCurve:
    def test_federal_default_curve_anchor_points(self):
        assert age_curve_factor(10) == 0.765
        assert age_curve_factor(21) == 1.0
        assert age_curve_factor(50) == 1.786
        assert age_curve_factor(64) == 3.0
        assert age_curve_factor(70) == 3.0
        ages = list(range(15, 65))
        assert all(age_curve_factor(a) <= age_curve_factor(b) for a, b in pairwise(ages))


class TestMedicare:
    settings = HealthcareSettingsData(enabled=True, medicare_part_d_plan_premium_monthly=40, medicare_supplement_premium_monthly=150)

    def test_standard_premium_below_first_threshold(self):
        r = calculate_medicare_premiums(100_000, "single", 1, self.settings, year=2026, inflation_factor=1.0, medical_factor=1.0)
        assert r.tier_index == 0
        assert r.part_b_standard == pytest.approx(202.90 * 12)
        assert r.part_b_irmaa == 0 and r.part_d_irmaa == 0
        assert r.part_d_plan == pytest.approx(480) and r.supplement == pytest.approx(1_800)
        assert r.total == pytest.approx(202.90 * 12 + 480 + 1_800)

    def test_irmaa_tiers_single_and_joint(self):
        single = calculate_medicare_premiums(150_000, "single", 1, self.settings, year=2026, inflation_factor=1.0, medical_factor=1.0)
        assert single.tier_index == 2
        assert single.part_b_irmaa == pytest.approx(202.90 * 12)
        assert single.part_d_irmaa == pytest.approx(37.50 * 12)
        joint = calculate_medicare_premiums(300_000, "married_filing_jointly", 2, self.settings, year=2026, inflation_factor=1.0, medical_factor=1.0)
        assert joint.tier_index == 2
        assert joint.part_b_irmaa == pytest.approx(202.90 * 24)  # both spouses pay the surcharge
        top = calculate_medicare_premiums(800_000, "married_filing_jointly", 2, self.settings, year=2026, inflation_factor=1.0, medical_factor=1.0)
        assert top.tier_index == 5 and top.part_b_irmaa == pytest.approx(487.00 * 24)
        boundary = calculate_medicare_premiums(109_000, "single", 1, self.settings, year=2026, inflation_factor=1.0, medical_factor=1.0)
        assert boundary.tier_index == 0  # "more than" $109,000 starts the surcharge
        separate = calculate_medicare_premiums(200_000, "married_filing_separately", 1, self.settings, year=2026, inflation_factor=1.0, medical_factor=1.0)
        assert separate.part_b_irmaa == pytest.approx(446.30 * 12)

    def test_thresholds_index_except_frozen_top_tier(self):
        # 10% indexation: $137,000 tier boundary moves to $150,700 but the $500,000 top stays frozen through 2027.
        r = calculate_medicare_premiums(145_000, "single", 1, self.settings, year=2027, inflation_factor=1.10, medical_factor=1.0)
        assert r.tier_index == 1
        frozen = calculate_medicare_premiums(520_000, "single", 1, self.settings, year=2027, inflation_factor=1.10, medical_factor=1.0)
        assert frozen.tier_index == 5
        indexed = calculate_medicare_premiums(520_000, "single", 1, self.settings, year=2028, inflation_factor=1.10, medical_factor=1.0)
        assert indexed.tier_index == 4

    def test_medical_inflation_and_proration(self):
        r = calculate_medicare_premiums(50_000, "single", 0.5, self.settings, year=2030, inflation_factor=1.1, medical_factor=1.3)
        assert r.part_b_standard == pytest.approx(202.90 * 1.3 * 6)
        off = calculate_medicare_premiums(150_000, "single", 1, HealthcareSettingsData(medicare_apply_irmaa=False), year=2026, inflation_factor=1.0, medical_factor=1.0)
        assert off.part_b_irmaa == 0 and off.part_d_irmaa == 0


def test_parse_settings_ignores_unknown_keys_and_casts():
    s = parse_healthcare_settings({"enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": "18000", "aca_dependents": "2", "bogus": 1})
    assert s.enabled and s.aca_enabled and s.aca_benchmark_premium_annual == 18_000 and s.aca_dependents == 2
    assert s.aca_advance_credit_fraction == 1.0
    assert parse_healthcare_settings({"aca_advance_credit_fraction": "0.5"}).aca_advance_credit_fraction == 0.5
    assert parse_healthcare_settings(None).enabled is False


def test_aca_advance_credit_fraction_schema_is_bounded():
    assert HealthcareSettings.model_validate({}).aca_advance_credit_fraction == 1.0
    assert HealthcareSettings.model_validate({"aca_advance_credit_fraction": 0}).aca_advance_credit_fraction == 0
    with pytest.raises(ValueError):
        HealthcareSettings.model_validate({"aca_advance_credit_fraction": 1.01})
    with pytest.raises(ValueError):
        HealthcareSettings.model_validate({"aca_advance_credit_fraction": -0.01})
    with pytest.raises(ValueError):
        parse_healthcare_settings({"aca_advance_credit_fraction": 1.01})



# ---------------------------------------------------------------------------
# Simulator integration
# ---------------------------------------------------------------------------

import uuid  # noqa: E402

from coastmath.engine.simulator import run_simulation  # noqa: E402
from coastmath.engine.types import (  # noqa: E402
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
)


def _plan(**overrides) -> PlanData:
    defaults = dict(
        plan_id=str(uuid.uuid4()), birth_year=1966, filing_status="married_filing_jointly",
        life_expectancy=70, start_year=2026, milestones=[], income_streams=[], expenses=[],
        priorities=[], drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash")],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        accounts={"cash": AccountInfo(balance=3_000_000, account_type="checking")},
        spouse_birth_year=1968, spouse_life_expectancy=95, birth_month=None,
    )
    defaults.update(overrides)
    return PlanData(**defaults)


class TestSimulatorIntegration:
    def test_aca_credit_reduces_premium_and_enters_expenses_once(self):
        # Age 60/58 couple with $60k pension income, ACA premiums $24k benchmark / $22k plan.
        plan = _plan(
            income_streams=[IncomeData(id="p", name="Pension", annual_amount=60_000, is_earned_income=False)],
            healthcare_settings={
                "enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 24_000,
                "aca_plan_premium_annual": 22_000, "aca_apply_age_curve": False, "medicare_enabled": False,
            },
        )
        base = run_simulation(_plan(income_streams=plan.income_streams)).yearly_snapshots
        snaps = run_simulation(plan).yearly_snapshots
        hc = snaps[0].healthcare
        assert hc is not None and hc.aca_eligible and hc.aca_covered_adults == 2 and hc.aca_household_size == 2
        assert hc.aca_gross_premium == pytest.approx(22_000)
        assert hc.aca_credit > 0 and hc.aca_net_premium == pytest.approx(22_000 - hc.aca_credit)
        assert hc.medicare_part_b == 0
        # No withdrawals create income here, so the advance and final credit agree.
        assert hc.aca_credit_advanced == pytest.approx(hc.aca_credit) and hc.aca_reconciliation == 0
        # Expenses rise by exactly the net premium; the credit is not income.
        assert snaps[0].expenses - base[0].expenses == pytest.approx(hc.aca_net_premium)
        assert snaps[0].gross_income == pytest.approx(base[0].gross_income)
        assert any(e.name == "Health coverage" and e.amount == pytest.approx(hc.total) for e in snaps[0].cash_flow.expenses)
        # Balance falls by the net premium (no taxes on the pension under this deduction).
        assert base[0].accounts["cash"] - snaps[0].accounts["cash"] == pytest.approx(hc.aca_net_premium)

    @pytest.mark.parametrize("tax_settings", [{}, {"mfs_lived_apart_all_year": True}])
    def test_married_filing_separately_pays_full_aca_premium(self, tax_settings):
        # IRC 36B(c)(1)(C); Treas. Reg. 1.36B-2(b)(2)(i). Living apart does not
        # restore the credit for a married separate filer. The joint control
        # gets 24,000 - 9.4641% x 60,000 = 18,321.53.
        kw = dict(
            income_streams=[IncomeData(id="p", name="Pension", annual_amount=60_000, is_earned_income=False)],
            healthcare_settings={
                "enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 24_000,
                "aca_plan_premium_annual": 22_000, "aca_apply_age_curve": False, "medicare_enabled": False,
                "magi_prior_year": 60_000,
            },
        )
        joint = run_simulation(_plan(**kw)).yearly_snapshots[0].healthcare
        assert joint.aca_credit == pytest.approx(18_321.53, abs=0.01)
        hc = run_simulation(_plan(filing_status="married_filing_separately", tax_settings=tax_settings,
                                  **kw)).yearly_snapshots[0].healthcare
        assert hc.aca_eligible is False and "36B(c)(1)(C)" in (hc.aca_reason or "")
        assert hc.aca_credit == 0 and hc.aca_credit_advanced == 0 and hc.aca_reconciliation == 0
        assert hc.aca_cash_premium == pytest.approx(22_000) and hc.aca_net_premium == pytest.approx(22_000)

    def test_advance_credit_is_reconciled_on_post_withdrawal_income(self):
        """A retiree funding spending from a traditional IRA has no income until
        withdrawals happen. The advance credit uses the prior-year MAGI seed
        (then the prior projected year); the final credit uses the actual
        post-withdrawal MAGI and the difference settles with taxes."""
        plan = _plan(
            birth_year=1968, spouse_birth_year=None, filing_status="single", life_expectancy=62,
            expenses=[ExpenseData(id="living", name="Living", annual_amount=50_000, inflation_linked=False)],
            accounts={"ira": AccountInfo(balance=2_000_000, account_type="traditional_ira")},
            drawdown_order=[DrawdownEntryData(rank=1, source_account_id="ira")],
            healthcare_settings={
                "enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 12_000,
                "aca_plan_premium_annual": 11_000, "aca_apply_age_curve": False, "medicare_enabled": False,
                "magi_prior_year": 55_000,
            },
        )
        snaps = run_simulation(plan).yearly_snapshots
        first, second = snaps[0].healthcare, snaps[1].healthcare
        assert first.aca_magi_estimate == pytest.approx(55_000)
        assert first.aca_credit_advanced > 0
        # Final MAGI comes from the IRA withdrawals that funded spending, premiums and tax.
        assert first.aca_magi > 0 and first.aca_magi != pytest.approx(55_000)
        assert first.aca_reconciliation == pytest.approx(first.aca_credit - first.aca_credit_advanced)
        assert first.aca_reconciliation != 0
        # The reconciliation is settled through the tax refund/bill, not by changing "taxes".
        snap = snaps[0]
        assert snap.cash_flow.tax_delta == pytest.approx(
            snap.cash_flow.tax_withheld - (snap.taxes - snap.early_withdrawal_penalty) + first.aca_reconciliation, abs=1.0)
        # Year two estimates from year one's final MAGI.
        assert second.aca_magi_estimate == pytest.approx(first.aca_magi)

    @pytest.mark.parametrize("fraction", [0.0, 0.5, 1.0])
    def test_aca_advance_fraction_controls_cash_premium(self, fraction):
        plan = _plan(
            birth_year=1968, spouse_birth_year=None, filing_status="single", life_expectancy=62,
            income_streams=[IncomeData(id="p", name="Pension", annual_amount=60_000, is_earned_income=False)],
            healthcare_settings={
                "enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 12_000,
                "aca_plan_premium_annual": 11_000, "aca_apply_age_curve": False, "medicare_enabled": False,
                "magi_prior_year": 30_000, "aca_advance_credit_fraction": fraction,
            },
        )
        snap = run_simulation(plan).yearly_snapshots[0]
        hc = snap.healthcare
        assert hc is not None
        estimated = calculate_premium_tax_credit(
            30_000, 1, 12_000, 11_000, covered_adults=1,
        ).credit
        assert hc.aca_credit_advanced == pytest.approx(fraction * estimated)
        assert hc.aca_cash_premium == pytest.approx(hc.aca_gross_premium - fraction * estimated)
        assert hc.aca_net_premium == pytest.approx(hc.aca_gross_premium - hc.aca_credit)
        assert next(e.amount for e in snap.cash_flow.expenses if e.name == "Health coverage") == pytest.approx(hc.aca_cash_premium)

    @pytest.mark.parametrize(
        ("income", "prior_magi", "fraction", "reconciliation_sign"),
        [(30_000, 55_000, 0.5, 1), (60_000, 30_000, 1.0, -1)],
    )
    def test_aca_advance_fraction_preserves_positive_and_negative_reconciliation(
        self, income, prior_magi, fraction, reconciliation_sign,
    ):
        plan = _plan(
            birth_year=1968, spouse_birth_year=None, filing_status="single", life_expectancy=62,
            income_streams=[IncomeData(id="p", name="Pension", annual_amount=income, is_earned_income=False)],
            healthcare_settings={
                "enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 12_000,
                "aca_plan_premium_annual": 11_000, "aca_apply_age_curve": False, "medicare_enabled": False,
                "magi_prior_year": prior_magi, "aca_advance_credit_fraction": fraction,
            },
        )
        hc = run_simulation(plan).yearly_snapshots[0].healthcare
        assert hc is not None and hc.aca_reconciliation * reconciliation_sign > 0
        assert hc.aca_reconciliation == pytest.approx(hc.aca_credit - hc.aca_credit_advanced)

    def test_aca_advance_fraction_prorates_partial_year_coverage(self):
        plan = _plan(
            birth_year=1968, spouse_birth_year=None, filing_status="single", life_expectancy=62,
            first_year_fraction=0.5,
            healthcare_settings={
                "enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 12_000,
                "aca_plan_premium_annual": 11_000, "aca_apply_age_curve": False, "medicare_enabled": False,
                "magi_prior_year": 55_000, "aca_advance_credit_fraction": 0.5,
            },
        )
        hc = run_simulation(plan).yearly_snapshots[0].healthcare
        assert hc is not None
        annual_estimated = calculate_premium_tax_credit(
            55_000, 1, 12_000, 11_000, covered_adults=1,
        ).credit
        assert hc.aca_gross_premium == pytest.approx(11_000 * 0.5)
        assert hc.aca_credit_advanced == pytest.approx(annual_estimated * 0.5 * 0.5)
        assert hc.aca_cash_premium == pytest.approx(hc.aca_gross_premium - hc.aca_credit_advanced)

    def test_aca_reconciliation_keeps_one_year_settlement_lag(self):
        plan = _plan(
            birth_year=1968, spouse_birth_year=None, filing_status="single", life_expectancy=62,
            income_streams=[IncomeData(id="p", name="Pension", annual_amount=30_000, is_earned_income=False)],
            expenses=[ExpenseData(id="living", name="Living", annual_amount=10_000, inflation_linked=False)],
            tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0, "settlement_lag_years": 1},
            healthcare_settings={
                "enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 12_000,
                "aca_plan_premium_annual": 11_000, "aca_apply_age_curve": False, "medicare_enabled": False,
                "magi_prior_year": 55_000, "aca_advance_credit_fraction": 0.5,
            },
        )
        first, second = run_simulation(plan).yearly_snapshots[:2]
        assert first.healthcare is not None and first.healthcare.aca_reconciliation > 0
        assert first.tax_balance == pytest.approx(-first.healthcare.aca_reconciliation)
        assert second.accounts["cash"] - first.accounts["cash"] == pytest.approx(
            30_000 - second.expenses + first.healthcare.aca_reconciliation,
        )

    def test_aca_ends_when_each_adult_reaches_medicare(self):
        plan = _plan(
            birth_year=1963,  # 63 in 2026 -> Medicare in 2028
            income_streams=[IncomeData(id="p", name="Pension", annual_amount=60_000, is_earned_income=False)],
            healthcare_settings={
                "enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 24_000,
                "aca_plan_premium_annual": 22_000, "medicare_enabled": True,
                "magi_prior_year": 60_000, "magi_two_years_prior": 60_000,
            },
        )
        by_year = {s.year: s.healthcare for s in run_simulation(plan).yearly_snapshots}
        assert by_year[2027].aca_covered_adults == 2 and by_year[2027].medicare_persons == 0
        assert by_year[2028].aca_covered_adults == 1  # spouse (60) still on the marketplace
        assert by_year[2028].medicare_persons == pytest.approx(1.0)
        assert by_year[2028].medicare_part_b == pytest.approx(202.90 * 12)
        assert by_year[2028].medicare_lookback_year == 2026 and by_year[2028].medicare_lookback_source == "history"
        # Age curve: a single covered adult at 60 costs less than the couple at 63/58.
        assert by_year[2028].aca_gross_premium < by_year[2027].aca_gross_premium

    def test_irmaa_uses_two_year_lookback_and_seeds(self):
        plan = _plan(
            birth_year=1958, spouse_birth_year=1958, filing_status="married_filing_jointly", life_expectancy=75,
            income_streams=[IncomeData(id="p", name="Pension", annual_amount=300_000, is_earned_income=False,
                                       end_milestone_id="stop")],
            milestones=[MilestoneData(id="stop", name="Stop", trigger_type="date", trigger_date="2028-01-01")],
            healthcare_settings={
                "enabled": True, "medicare_enabled": True, "medicare_apply_irmaa": True,
                "magi_prior_year": 100_000, "magi_two_years_prior": 100_000,
            },
        )
        by_year = {s.year: s.healthcare for s in run_simulation(plan).yearly_snapshots}
        assert by_year[2026].medicare_lookback_source == "seed" and by_year[2026].medicare_tier == 0
        assert by_year[2028].medicare_lookback_year == 2026 and by_year[2028].medicare_tier == 2  # $300k joint -> tier 2
        assert by_year[2028].medicare_irmaa_part_b == pytest.approx(202.90 * 24)
        # Income stops in 2028, so 2030 falls back to the base premium.
        assert by_year[2030].medicare_tier == 0 and by_year[2030].medicare_irmaa_part_b == 0

    def test_disabled_settings_change_nothing(self):
        plan = _plan(healthcare_settings={"enabled": False, "aca_enabled": True, "aca_plan_premium_annual": 20_000, "aca_benchmark_premium_annual": 20_000})
        snaps = run_simulation(plan).yearly_snapshots
        assert snaps[0].healthcare is None
        assert snaps[0].expenses == 0

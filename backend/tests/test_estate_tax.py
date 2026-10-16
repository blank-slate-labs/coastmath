"""Tests for estate tax calculation (task 5.3.3)."""

import pytest

from coastmath.engine.estate_tax import (
    _DEFAULT_INFLATION,
    _FEDERAL_RATE,
    _federal_estate_exemption,
    calculate_estate_breakdown,
    calculate_estate_tax,
    calculate_net_legacy,
)
from coastmath.engine.types import EstateSettingsData


def _settings(**overrides) -> EstateSettingsData:
    return EstateSettingsData(**overrides)


# ---------------------------------------------------------------------------
# calculate_estate_tax
# ---------------------------------------------------------------------------


def test_estate_tax_below_exemption():
    """$5M estate in 2025 → $0 tax (below $13.6M exemption)."""
    tax = calculate_estate_tax(5_000_000, _settings(), year=2025)
    assert tax == 0.0


def test_estate_tax_above_exemption():
    """$20M estate in 2025 → ($20M - $13.99M) * 0.40 = $2.404M."""
    tax = calculate_estate_tax(20_000_000, _settings(), year=2025)
    expected = (20_000_000 - 13_990_000) * 0.40
    assert abs(tax - expected) < 0.01


def test_estate_tax_zero_estate():
    """Zero or negative estate → $0 tax."""
    assert calculate_estate_tax(0, _settings(), year=2025) == 0.0
    assert calculate_estate_tax(-100_000, _settings(), year=2025) == 0.0


def test_estate_tax_marital_deduction():
    """With marital deduction, federal tax is $0 regardless of estate size."""
    tax = calculate_estate_tax(
        50_000_000, _settings(), year=2025, marital_deduction=True,
    )
    assert tax == 0.0


def test_inflation_adjusted_exemption():
    """Future years should have a higher exemption due to inflation adjustment."""
    future_year = 2035
    adjusted_exemption = _federal_estate_exemption(future_year)

    # 2035: $15M base (2026) inflated 9 years at 3% = 19,571,597.70.
    assert _DEFAULT_INFLATION == 0.03
    # IRC 2010(c)(3)(B) rounds to the nearest $10,000: 19,571,597.70 -> 19,570,000.
    expected_exemption = 19_570_000.0
    assert abs(adjusted_exemption - expected_exemption) < 0.01

    # Estate below the inflated exemption → $0
    estate_value = 16_000_000.0
    assert estate_value < adjusted_exemption  # sanity check
    tax = calculate_estate_tax(estate_value, _settings(), year=future_year)
    assert tax == 0.0

    # Estate well above the inflated exemption → positive tax
    big_estate = 25_000_000.0
    tax = calculate_estate_tax(big_estate, _settings(), year=future_year)
    expected = (big_estate - adjusted_exemption) * _FEDERAL_RATE
    assert abs(tax - expected) < 0.01


def test_state_estate_tax():
    """State estate tax applies flat rate above state exemption."""
    settings = _settings(
        state_estate_tax_enabled=True,
        state_estate_exemption=5_000_000,
        state_estate_tax_rate=0.16,
    )
    estate = 10_000_000.0
    tax = calculate_estate_tax(estate, settings, year=2025)

    # Federal: ($10M - $13.99M) → $0 (below exemption)
    # State: ($10M - $5M) * 0.16 = $800k
    assert abs(tax - 800_000.0) < 0.01


def test_state_and_federal_estate_tax():
    """Both federal and state tax applied when estate exceeds both exemptions."""
    settings = _settings(
        state_estate_tax_enabled=True,
        state_estate_exemption=5_000_000,
        state_estate_tax_rate=0.16,
    )
    estate = 20_000_000.0
    tax = calculate_estate_tax(estate, settings, year=2025)

    state = (20_000_000 - 5_000_000) * 0.16
    # IRC 2058: the state tax is deducted from the federal taxable estate.
    federal = (20_000_000 - state - 13_990_000) * 0.40
    assert abs(tax - (federal + state)) < 0.01


def test_marital_deduction_defers_state_tax_too():
    """State estate taxes start from the federal taxable estate, which already
    reflects the unlimited marital deduction (e.g. RCW 83.100.020, M.G.L. c.65C
    s.1), so a spouse-survives transfer owes no state estate tax either."""
    settings = _settings(
        state_estate_tax_enabled=True,
        state_estate_exemption=1_000_000,
        state_estate_tax_rate=0.10,
    )
    breakdown = calculate_estate_breakdown(
        5_000_000.0, 0.0, settings, year=2025, marital_deduction=True,
    )
    assert breakdown.marital_deduction_applied is True
    assert breakdown.federal_estate_tax == 0.0
    assert breakdown.state_estate_tax == 0.0
    assert breakdown.net_legacy == 5_000_000.0
    assert any("surviving spouse" in note for note in breakdown.exclusions)


def test_breakdown_reports_federal_and_state_separately():
    settings = _settings(
        state_estate_tax_enabled=True,
        state_estate_exemption=2_000_000,
        state_estate_tax_rate=0.16,
    )
    b = calculate_estate_breakdown(20_000_000.0, 1_000_000.0, settings, year=2025)
    assert b.gross_estate == 19_000_000.0
    assert b.federal_exemption == 13_990_000.0
    # IRC 2058: the 2.72M state tax is deducted from the federal taxable estate.
    assert b.federal_taxable_estate == pytest.approx(19_000_000 - 17_000_000 * 0.16 - 13_990_000)
    assert b.federal_estate_tax == pytest.approx((19_000_000 - 17_000_000 * 0.16 - 13_990_000) * 0.40)
    assert b.state_taxable_estate == pytest.approx(17_000_000)
    assert b.state_estate_tax == pytest.approx(17_000_000 * 0.16)
    assert b.estate_tax == pytest.approx(b.federal_estate_tax + b.state_estate_tax)
    assert b.net_legacy == pytest.approx(b.gross_estate - b.estate_tax)
    assert b.dsue_amount == 0.0
    # Dict form keeps the legacy keys used by existing consumers.
    d = calculate_net_legacy(20_000_000.0, 1_000_000.0, settings, 2025)
    assert d["gross_estate"] == b.gross_estate and d["estate_tax"] == b.estate_tax


def test_custom_federal_exemption_only_applies_when_enabled():
    ignored = _settings(federal_estate_exemption=5_000_000.0)
    assert calculate_estate_breakdown(10_000_000.0, 0.0, ignored, year=2026).federal_estate_tax == 0.0
    custom = _settings(federal_estate_exemption=5_000_000.0, custom_federal_exemption_enabled=True)
    b = calculate_estate_breakdown(10_000_000.0, 0.0, custom, year=2026)
    assert b.custom_federal_exemption is True
    assert b.federal_exemption == 5_000_000.0
    assert b.federal_estate_tax == pytest.approx(5_000_000 * 0.40)


def test_portability_adds_partner_dsue_at_first_death_amount():
    """Partner died in 2026 (exclusion $15M, unused); holder dies in 2036.
    DSUE is fixed at the 2026 amount and is not indexed."""
    settings = _settings()
    with_port = calculate_estate_breakdown(
        45_000_000.0, 0.0, settings, year=2036, partner_death_year=2026,
    )
    assert with_port.dsue_amount == 15_000_000.0
    holder_only = _federal_estate_exemption(2036)
    assert with_port.federal_taxable_estate == pytest.approx(
        45_000_000 - holder_only - 15_000_000
    )
    without = calculate_estate_breakdown(
        45_000_000.0, 0.0, _settings(portability_election=False), year=2036, partner_death_year=2026,
    )
    assert without.dsue_amount == 0.0
    assert without.federal_estate_tax > with_port.federal_estate_tax
    # No DSUE when there was no earlier partner death.
    assert calculate_estate_breakdown(45_000_000.0, 0.0, settings, year=2036).dsue_amount == 0.0


def test_indexed_exclusion_rounds_to_nearest_10000():
    """IRC 2010(c)(3)(B): an indexed amount that is not a multiple of $10,000
    is rounded to the nearest multiple, not down."""
    # 15,000,000 x 1.0257 = 15,385,500 -> 15,390,000 (remainder 5,500 rounds up).
    assert _federal_estate_exemption(2027, 1.0257) == 15_390_000.0
    # 15,000,000 x 1.0253 = 15,379,500 -> 15,380,000 (remainder 9,500 rounds up).
    assert _federal_estate_exemption(2027, 1.0253) == 15_380_000.0
    # 15,000,000 x 1.0252 = 15,378,000 -> 15,380,000.
    assert _federal_estate_exemption(2027, 1.0252) == 15_380_000.0
    # 15,000,000 x 1.025 = 15,375,000: an exact half rounds up to 15,380,000.
    assert _federal_estate_exemption(2027, 1.025) == 15_380_000.0
    # 15,000,000 x 1.0249 = 15,373,500 -> 15,370,000 (remainder 3,500 rounds down).
    assert _federal_estate_exemption(2027, 1.0249) == 15_370_000.0
    # Tax on a $20M estate in 2027: 40% x (20,000,000 - 15,390,000) = 1,844,000.
    breakdown = calculate_estate_breakdown(
        20_000_000.0, 0.0, _settings(), year=2027, calendar_inflation={2027: 1.0257},
    )
    assert breakdown.federal_exemption == 15_390_000.0
    assert breakdown.federal_estate_tax == pytest.approx(1_844_000.0)


def test_federal_parameters_come_from_data_file():
    assert _federal_estate_exemption(2024) == 13_610_000.0
    assert _federal_estate_exemption(2026) == 15_000_000.0
    assert _federal_estate_exemption(2020) == 12_920_000.0
    assert _FEDERAL_RATE == 0.40


# ---------------------------------------------------------------------------
# calculate_net_legacy
# ---------------------------------------------------------------------------


def test_net_legacy_calculation():
    """Verify gross - tax = net."""
    result = calculate_net_legacy(
        total_assets=25_000_000,
        total_liabilities=5_000_000,
        estate_settings=_settings(),
        final_year=2025,
    )
    gross = 25_000_000 - 5_000_000  # $20M
    federal_tax = (gross - 13_990_000) * 0.40
    assert abs(result["gross_estate"] - gross) < 0.01
    assert abs(result["estate_tax"] - federal_tax) < 0.01
    assert abs(result["net_legacy"] - (gross - federal_tax)) < 0.01


def test_net_legacy_no_tax():
    """Small estate → no tax, net_legacy == gross_estate."""
    result = calculate_net_legacy(
        total_assets=3_000_000,
        total_liabilities=500_000,
        estate_settings=_settings(),
        final_year=2025,
    )
    gross = 2_500_000.0
    assert result["estate_tax"] == 0.0
    assert abs(result["net_legacy"] - gross) < 0.01


def test_net_legacy_with_marital_deduction():
    """Marital deduction → no federal tax even on large estate."""
    result = calculate_net_legacy(
        total_assets=30_000_000,
        total_liabilities=0,
        estate_settings=_settings(),
        final_year=2025,
        marital_deduction=True,
    )
    assert result["estate_tax"] == 0.0
    assert abs(result["net_legacy"] - 30_000_000) < 0.01



def test_settlement_costs_are_deducted_before_estate_tax_and_reported_separately():
    settings = _settings(settlement_cost_fixed=20_000, settlement_cost_rate=0.03)
    b = calculate_estate_breakdown(20_000_000.0, 500_000.0, settings, year=2026, accrued_taxes=100_000.0)
    assert b.debts == pytest.approx(400_000) and b.accrued_taxes == pytest.approx(100_000)
    assert b.gross_estate == pytest.approx(19_500_000)
    assert b.settlement_costs == pytest.approx(20_000 + 0.03 * 19_500_000)
    assert b.taxable_estate_before_exemptions == pytest.approx(19_500_000 - b.settlement_costs)
    assert b.federal_taxable_estate == pytest.approx(b.taxable_estate_before_exemptions - 15_000_000)
    assert b.net_legacy == pytest.approx(b.gross_estate - b.settlement_costs - b.estate_tax)


def test_heir_income_tax_applies_to_pretax_balances_net_of_691c_and_not_to_a_spouse():
    settings = _settings(heir_income_tax_rate=0.24)
    # Below the exemption: no estate tax, so no 691(c) deduction; full pre-tax balance taxed to heirs.
    small = calculate_estate_breakdown(5_000_000.0, 0.0, settings, year=2026, pretax_balance=2_000_000.0)
    assert small.estate_tax == 0 and small.heir_income_tax_deduction_691c == 0
    assert small.heir_income_tax == pytest.approx(0.24 * 2_000_000)
    assert small.net_to_heirs_after_income_tax == pytest.approx(small.net_legacy - small.heir_income_tax)
    # Above the exemption: estate tax attributable to the pre-tax share is deductible first.
    big = calculate_estate_breakdown(25_000_000.0, 0.0, settings, year=2026, pretax_balance=5_000_000.0)
    assert big.estate_tax > 0
    without_ird = calculate_estate_breakdown(20_000_000.0, 0.0, settings, year=2026)
    expected_691c = big.federal_estate_tax - without_ird.federal_estate_tax
    assert big.heir_income_tax_deduction_691c == pytest.approx(expected_691c)
    assert big.heir_income_tax == pytest.approx(0.24 * (5_000_000 - expected_691c))
    # Spouse inherits: rollover, nothing due now.
    spouse = calculate_estate_breakdown(25_000_000.0, 0.0, settings, year=2026, pretax_balance=5_000_000.0, marital_deduction=True)
    assert spouse.heir_income_tax == 0 and spouse.settlement_costs == 0
    # Pre-tax balance cannot exceed total assets; no rate means no heir tax.
    none = calculate_estate_breakdown(1_000_000.0, 0.0, _settings(), year=2026, pretax_balance=5_000_000.0)
    assert none.pretax_balance == 1_000_000 and none.heir_income_tax == 0

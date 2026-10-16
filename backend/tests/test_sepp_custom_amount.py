"""A custom SEPP annual amount keeps the 72(t) exemption only when an approved method yields it."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.sepp_settings import SEPPSettings
from coastmath.engine.sepp import (
    calculate_sepp,
    custom_amount_qualifies,
    first_distribution_month,
    sepp_rate_ceiling,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    PlanData,
    SEPPSettingsData,
)

IRA = "ira"


def _plan(sepp: SEPPSettingsData) -> PlanData:
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000073", birth_year=1970, birth_month=1,
        filing_status="single", life_expectancy=65, start_year=2020, state_code="FL",
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0,
                                   stock_dividend_yield=0.0),
        accounts={IRA: AccountInfo(500_000.0, "traditional_ira")}, sepp_settings=sepp,
    )


def _sepp(**changes) -> SEPPSettingsData:
    options = dict(enabled=True, source_account_id=IRA, method="fixed_amortization", start_age=50.0, interest_rate=0.05)
    options.update(changes)
    return SEPPSettingsData(**options)


def _rows(plan):
    result = run_simulation(plan)
    return {row.year: row for row in result.yearly_snapshots}, result


APPROVED = calculate_sepp(500_000.0, 50, "fixed_amortization", 0.05)


def test_default_series_is_unchanged_without_a_custom_amount():
    rows, result = _rows(_plan(_sepp()))
    assert rows[2020].early_withdrawal_penalty == 0
    assert not any("custom SEPP" in warning for warning in result.metadata.warnings)


def test_matching_amount_keeps_the_exemption():
    assert custom_amount_qualifies(round(APPROVED), 500_000.0, 50, "fixed_amortization", 0.05)
    rows, result = _rows(_plan(_sepp(annual_amount=round(APPROVED))))
    assert rows[2020].early_withdrawal_penalty == 0
    assert rows[2020].accounts[IRA] == pytest.approx(500_000.0 - round(APPROVED))
    assert any("matches an approved method" in warning for warning in result.metadata.warnings)


def test_other_amount_is_an_ordinary_early_withdrawal_with_the_penalty():
    amount = 30_000.0
    assert not custom_amount_qualifies(amount, 500_000.0, 50, "fixed_amortization", 0.05)
    rows, result = _rows(_plan(_sepp(annual_amount=amount)))
    assert rows[2020].accounts[IRA] == pytest.approx(500_000.0 - amount)
    assert rows[2020].early_withdrawal_penalty == pytest.approx(amount * 0.10)
    assert rows[2021].early_withdrawal_penalty == pytest.approx(amount * 0.10)
    assert any("ordinary early withdrawal" in warning for warning in result.metadata.warnings)


def test_penalty_leaves_the_household_instead_of_being_conjured():
    rows, _ = _rows(_plan(_sepp(annual_amount=30_000.0)))
    # No growth or spending: money in accounts equals the start less all taxes and the penalty.
    assert sum(rows[2020].accounts.values()) == pytest.approx(500_000.0 - rows[2020].taxes, abs=0.01)
    assert rows[2020].early_withdrawal_penalty == pytest.approx(3_000.0)


def test_amount_matches_only_the_fixed_amortization_method_and_a_validated_rate():
    assert not custom_amount_qualifies(round(APPROVED), 500_000.0, 50, "rmd_method", 0.05)
    higher = calculate_sepp(500_000.0, 50, "fixed_amortization", 0.07)
    assert not custom_amount_qualifies(round(higher), 500_000.0, 50, "fixed_amortization", 0.07)


def test_duration_runs_to_the_later_of_five_years_or_59_5_and_stops_after():
    rows, _ = _rows(_plan(_sepp(annual_amount=round(APPROVED))))
    # Start age 50: payments through age 59 (2029); age 59.5 is the later bound.
    assert rows[2029].accounts[IRA] < rows[2028].accounts[IRA]
    assert rows[2030].accounts[IRA] == pytest.approx(rows[2029].accounts[IRA])


def test_underfunded_series_warns_about_modification():
    plan = _plan(_sepp(annual_amount=round(APPROVED)))
    plan.accounts[IRA] = AccountInfo(round(APPROVED) * 2.5, "traditional_ira")
    _, result = _rows(plan)
    assert any("modifies the series" in warning for warning in result.metadata.warnings)


def test_schema_accepts_amount_and_omits_it_when_unset():
    assert "annual_amount" not in SEPPSettings(start_age=50).model_dump(mode="json")
    assert SEPPSettings(start_age=50, annual_amount=24_000).annual_amount == 24_000
    with pytest.raises(ValidationError):
        SEPPSettings(start_age=50, annual_amount=0)


def test_rate_ceiling_is_the_greater_of_5_percent_and_120_percent_mid_term():
    # Rev. Rul. 2026-17 (September 2026) 5.40%, Rev. Rul. 2026-19 (October 2026) 5.54%.
    assert sepp_rate_ceiling(2026, 11) == pytest.approx(0.0554)
    assert sepp_rate_ceiling(2026, 10) == pytest.approx(0.0540)
    # October and November 2024 were 4.45%: the 5% floor applies.
    assert sepp_rate_ceiling(2024, 12) == pytest.approx(0.05)
    # Unknown months (before the bundled data or not yet published) keep the floor.
    assert sepp_rate_ceiling(2020, 1) == pytest.approx(0.05)
    assert sepp_rate_ceiling(2030, 1) == pytest.approx(0.05)
    assert sepp_rate_ceiling(None, None) == pytest.approx(0.05)
    # June 2024 (5.61%) counts for August 2024 as one of the two prior months.
    assert sepp_rate_ceiling(2024, 8) == pytest.approx(0.0561)
    assert first_distribution_month(1976, 11, 50.0) == (2026, 11)
    assert first_distribution_month(1976, 1, 50.25) == (2026, 4)


def test_custom_amount_above_5_percent_qualifies_within_the_mid_term_ceiling():
    at_55 = calculate_sepp(500_000.0, 50, "fixed_amortization", 0.055)
    assert custom_amount_qualifies(round(at_55), 500_000.0, 50, "fixed_amortization", 0.055, 0.0554)
    assert not custom_amount_qualifies(round(at_55), 500_000.0, 50, "fixed_amortization", 0.055)
    at_56 = calculate_sepp(500_000.0, 50, "fixed_amortization", 0.056)
    assert not custom_amount_qualifies(round(at_56), 500_000.0, 50, "fixed_amortization", 0.056, 0.0554)
    # The projection uses the owner's first distribution month: November 2026.
    plan = PlanData(
        plan_id="00000000-0000-4000-8000-000000000074", birth_year=1976, birth_month=11,
        filing_status="single", life_expectancy=65, start_year=2026, state_code="FL",
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0,
                                   stock_dividend_yield=0.0),
        accounts={IRA: AccountInfo(500_000.0, "traditional_ira")},
        sepp_settings=_sepp(interest_rate=0.055, annual_amount=round(at_55)),
    )
    rows, result = _rows(plan)
    assert rows[2027].early_withdrawal_penalty == 0
    assert any("matches an approved method" in warning for warning in result.metadata.warnings)

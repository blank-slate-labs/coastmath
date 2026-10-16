"""Independent budget/accounting checks for asymmetric household coverage."""
import uuid
from dataclasses import asdict

import pytest
from pydantic import ValidationError

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    EstateSettingsData,
    IncomeData,
    PlanData,
)
from coastmath.schemas.healthcare_settings import HealthcareSettings


def plan(settings=None, **changes):
    values = dict(plan_id=str(uuid.uuid4()), start_year=2026, birth_year=1961,
        birth_month=1, life_expectancy=70, spouse_birth_year=1961, spouse_birth_month=1,
        spouse_life_expectancy=72, filing_status="married_filing_jointly",
        milestones=[], income_streams=[], expenses=[], priorities=[],
        drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash")],
        accounts={"cash": AccountInfo(balance=2_000_000, account_type="checking")},
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0),
        healthcare_settings=settings)
    values.update(changes)
    return PlanData(**values)


def settings(*people, **changes):
    return {"enabled": True, "persons": list(people), **changes}


def test_spouse_premiums_and_budget_replace_shared_medical_costs_once():
    p = plan(settings(
        {"owner": "self", "mode": "itemized", "itemized_annual_amount": 0},
        {"owner": "spouse", "mode": "coverage", "medicare_part_d": False,
         "medicare_apply_irmaa": False, "out_of_pocket_annual": 500}))
    first = run_simulation(p).yearly_snapshots[0]
    expected = 202.90 * 12 + 500
    assert first.healthcare.medicare_persons == 1
    assert first.healthcare.medicare_part_b == pytest.approx(202.90 * 12)
    assert first.healthcare.out_of_pocket == 500
    assert first.healthcare.total == pytest.approx(expected)
    assert first.expenses == pytest.approx(expected)
    assert first.accounts["cash"] == pytest.approx(2_000_000 - expected)
    assert sum(e.amount for e in first.cash_flow.expenses) == pytest.approx(expected)
    assert sum(p["total_excluding_aca"] for p in first.healthcare.person_costs) == pytest.approx(expected)


def test_itemized_zero_is_distinct_from_unentered_out_of_pocket_budget():
    result = run_simulation(plan(settings(
        {"owner": "self", "mode": "itemized", "itemized_annual_amount": 0},
        {"owner": "spouse", "mode": "coverage", "medicare_part_d": False})))
    hc = result.yearly_snapshots[0].healthcare
    assert hc.person_costs[0]["itemized_medical"] == 0
    assert hc.person_costs[1]["out_of_pocket_assumption"] == "unknown"
    assert any("out-of-pocket costs were not supplied" in w for w in result.metadata.warnings)


def test_spouse_only_aca_preserves_tax_household_and_full_entered_policy_premium():
    result = run_simulation(plan(settings(
        {"owner": "self", "mode": "off"},
        {"owner": "spouse", "mode": "coverage", "medicare_enabled": False},
        aca_enabled=True, aca_benchmark_premium_annual=12_000,
        aca_plan_premium_annual=12_000, aca_apply_age_curve=False),
        birth_year=1966, spouse_birth_year=1966))
    hc = result.yearly_snapshots[0].healthcare
    assert hc.aca_covered_adults == 1
    assert hc.aca_household_size == 2
    assert hc.aca_gross_premium == 12_000
    assert hc.total == 12_000  # No credit: zero MAGI, below the modeled PTC floor.


def test_separate_premiums_inflation_and_enrollment_month():
    first = run_simulation(plan(settings(
        {"owner": "self", "mode": "off"},
        {"owner": "spouse", "mode": "coverage", "medicare_start_age": 65,
         "medicare_part_b": False, "medicare_part_d": False,
         "medicare_part_a_premium_monthly": 100, "medicare_supplement_premium_monthly": 150,
         "out_of_pocket_annual": 1200}), spouse_birth_month=7)).yearly_snapshots[0]
    assert first.healthcare.medicare_persons == .5
    assert first.healthcare.medicare_part_a == 600
    assert first.healthcare.medicare_supplement == 900
    assert first.healthcare.out_of_pocket == 1200  # Annual budget also covers pre-Medicare months.
    assert first.expenses == 2700


def test_itemized_medical_stops_before_legacy_spouse_death_month():
    snaps = run_simulation(plan(settings(
        {"owner": "self", "mode": "off"},
        {"owner": "spouse", "mode": "itemized", "itemized_annual_amount": 12_000}),
        spouse_birth_year=1956, spouse_life_expectancy=71, spouse_birth_month=6)).yearly_snapshots
    assert snaps[0].expenses == 12_000
    assert snaps[1].expenses == 5_000
    assert snaps[2].expenses == 0


def test_ltc_budget_has_bounded_months_net_coverage_and_no_duplicate_income():
    p = plan(settings({"owner": "self", "mode": "off", "long_term_care": {
        "monthly_cost": 10_000, "duration_months": 6, "start_year": 2026,
        "start_month": 11, "covered_fraction": .8, "inflation_rate": .1}},
        {"owner": "spouse", "mode": "off"}))
    snaps = run_simulation(p).yearly_snapshots
    assert snaps[0].healthcare.long_term_care_gross == 20_000
    assert snaps[0].healthcare.long_term_care_covered == 16_000
    assert snaps[0].expenses == pytest.approx(4_000)
    assert snaps[1].expenses == pytest.approx(4 * 11_000 * .2)
    assert snaps[2].expenses == 0
    assert all(s.gross_income == 0 for s in snaps)
    assert snaps[1].accounts["cash"] == pytest.approx(2_000_000 - 4_000 - 8_800)


def test_ltc_relative_endpoint_and_midyear_overlap_are_not_full_year_costs():
    first = run_simulation(plan(settings(
        {"owner": "self", "mode": "off"},
        {"owner": "spouse", "mode": "off", "long_term_care": {
            "monthly_cost": 1000, "duration_months": 28, "months_before_longevity": 28}}),
        spouse_birth_year=1956, spouse_life_expectancy=71, spouse_birth_month=1,
        first_year_fraction=114/365)).yearly_snapshots[0]
    assert first.expenses == pytest.approx(12_000 * 114/365)


def test_aca_reconciliation_retains_itemized_and_care_totals():
    hc = run_simulation(plan(settings(
        {"owner": "self", "mode": "itemized", "itemized_annual_amount": 6_000},
        {"owner": "spouse", "mode": "coverage", "medicare_enabled": False,
         "long_term_care": {"monthly_cost": 1000, "duration_months": 12, "start_year": 2026}},
        aca_enabled=True, aca_benchmark_premium_annual=12_000,
        aca_plan_premium_annual=12_000, aca_apply_age_curve=False),
        birth_year=1966, spouse_birth_year=1966)).yearly_snapshots[0].healthcare
    assert hc.total == pytest.approx(hc.aca_net_premium + 6_000 + 12_000)


@pytest.mark.parametrize("people", [
    [{"owner": "self", "mode": "itemized"}],
    [{"owner": "self", "mode": "off"}, {"owner": "self", "mode": "coverage"}],
    [{"owner": "joint", "mode": "off"}],
    [{"owner": "self", "mode": "itemized", "itemized_annual_amount": float("nan")}],
    [{"owner": "self", "mode": "off", "long_term_care": {"monthly_cost": 1000,
       "duration_months": 12, "start_year": 2026, "months_before_longevity": 28}}],
    [{"owner": "self", "mode": "coverage", "medicaid_eligible": True}],
])
def test_invalid_or_invented_cost_assumptions_rejected(people):
    with pytest.raises(ValidationError):
        HealthcareSettings.model_validate(settings(*people))


def test_spouse_cost_requires_spouse_identity():
    with pytest.raises(ValueError, match="spouse.*birth date"):
        run_simulation(plan(settings({"owner": "spouse", "mode": "off"}), spouse_birth_year=None))


def test_irmaa_preserves_joint_lookback_return_after_spouse_death():
    p = plan(settings({"owner": "self", "mode": "coverage", "out_of_pocket_annual": 0},
                      {"owner": "spouse", "mode": "off"}),
        spouse_birth_year=1956, spouse_life_expectancy=70, spouse_birth_month=7,
        income_streams=[IncomeData(id="pension", name="Pension", annual_amount=150_000,
                                   is_earned_income=False, growth_rate=0)])
    by_year = {s.year: s.healthcare for s in run_simulation(p).yearly_snapshots}
    assert by_year[2028].medicare_lookback_filing_status == "married_filing_jointly"
    assert by_year[2028].medicare_irmaa_part_b == 0
    assert by_year[2029].medicare_lookback_filing_status == "single"
    assert by_year[2029].medicare_irmaa_part_b > 0


def test_irmaa_seed_filing_status_is_independent_of_current_return():
    p = plan(settings({"owner": "self", "mode": "coverage", "out_of_pocket_annual": 0},
        magi_two_years_prior=150_000, magi_two_years_prior_filing_status="married_filing_jointly"),
        filing_status="single", spouse_birth_year=None)
    hc = run_simulation(p).yearly_snapshots[0].healthcare
    assert hc.medicare_lookback_source == "seed"
    assert hc.medicare_lookback_filing_status == "married_filing_jointly"
    assert hc.medicare_irmaa_part_b == 0


@pytest.mark.anyio
async def test_persisted_and_stateless_person_settings_roundtrip(client):
    supplied = settings({"owner": "self", "mode": "off"},
        {"owner": "spouse", "mode": "itemized", "itemized_annual_amount": 1200,
         "long_term_care": {"monthly_cost": 1000, "duration_months": 3,
             "start_year": 2026, "start_month": 1, "covered_fraction": .5}})
    cash_id = str(uuid.uuid4())
    created = await client.post("/api/plans", json={"name": "Person coverage contract",
        "plan_type": "FIXED_DATE", "start_date": "2026-01-01", "birth_year": 1961,
        "life_expectancy": 70, "filing_status": "married_filing_jointly",
        "snapshot_conditions": {cash_id: {"name": "Cash", "account_type": "checking", "balance": 2_000_000}}})
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    updated = await client.put(f"/api/plans/{pid}", json={"healthcare_settings": supplied,
        "spouse": {"name": "Spouse", "birth_year": 1961, "birth_month": 1, "life_expectancy": 72}})
    assert updated.status_code == 200, updated.text
    reread = await client.get(f"/api/plans/{pid}")
    expected = HealthcareSettings.model_validate(supplied).model_dump(mode="json")
    assert reread.json()["healthcare_settings"] == expected
    simulated = await client.post(f"/api/plans/{pid}/simulate")
    assert simulated.status_code == 200, simulated.text
    native = simulated.json()["yearly_snapshots"][0]["healthcare"]
    stateless = await client.post("/api/simulate/stateless", json=asdict(plan(supplied)))
    assert stateless.status_code == 200, stateless.text
    assert stateless.json()["yearly_snapshots"][0]["healthcare"] == native
    assert native["itemized_medical"] == 1200
    assert native["long_term_care"] == 1500
    assert native["total"] == 2700


@pytest.mark.anyio
async def test_stateless_missing_spouse_and_unknown_budget_return_validation_error(client):
    body = asdict(plan(settings({"owner": "spouse", "mode": "itemized",
                                "itemized_annual_amount": 0}), spouse_birth_year=None))
    response = await client.post("/api/simulate/stateless", json=body)
    assert response.status_code == 422
    assert "spouse" in response.text.lower()


@pytest.mark.parametrize("deceased", ["self", "spouse"])
def test_household_health_costs_follow_both_death_orders(deceased):
    p = plan(settings(
        {"owner": "self", "mode": "itemized", "itemized_annual_amount": 1000},
        {"owner": "spouse", "mode": "itemized", "itemized_annual_amount": 2000}),
        life_expectancy=65 if deceased == "self" else 67,
        spouse_life_expectancy=67 if deceased == "self" else 65,
        estate_settings=EstateSettingsData(household_lifecycle="last_survivor_calendar_year_end"))
    snaps = run_simulation(p).yearly_snapshots
    assert [s.year for s in snaps] == [2026, 2027, 2028]
    assert snaps[0].expenses == 3000
    assert snaps[1].expenses == (2000 if deceased == "self" else 1000)
    assert snaps[2].expenses == snaps[1].expenses
    assert snaps[-1].accounts["cash"] == 2_000_000 - sum(s.expenses for s in snaps)


def test_last_survivor_ltc_relative_months_include_final_longevity_year():
    p = plan(settings({"owner": "self", "mode": "off"},
        {"owner": "spouse", "mode": "off", "long_term_care": {
            "monthly_cost": 1000, "duration_months": 28, "months_before_longevity": 28}}),
        life_expectancy=65, spouse_life_expectancy=67,
        estate_settings=EstateSettingsData(household_lifecycle="last_survivor_calendar_year_end"))
    snaps = run_simulation(p).yearly_snapshots
    assert [s.expenses for s in snaps] == [4000, 12_000, 12_000]
    assert sum(s.healthcare.long_term_care for s in snaps) == 28_000


def test_shared_aca_cost_and_tax_household_reduce_after_primary_death():
    p = plan({"enabled": True, "aca_enabled": True,
        "aca_benchmark_premium_annual": 24_000, "aca_plan_premium_annual": 24_000,
        "aca_apply_age_curve": False, "medicare_enabled": False},
        birth_year=1976, life_expectancy=50, spouse_birth_year=1966, spouse_life_expectancy=65,
        estate_settings=EstateSettingsData(household_lifecycle="last_survivor_calendar_year_end"))
    snaps = run_simulation(p).yearly_snapshots
    assert snaps[0].healthcare.aca_household_size == 2
    assert snaps[0].healthcare.aca_gross_premium == 24_000
    assert snaps[1].healthcare.aca_household_size == 1
    assert snaps[1].healthcare.aca_covered_adults == 1
    assert snaps[1].healthcare.aca_gross_premium == 12_000


def test_shared_medicare_stops_primary_premium_after_calendar_death():
    p = plan({"enabled": True, "medicare_enabled": True, "medicare_part_d": False},
        life_expectancy=65, spouse_life_expectancy=67,
        estate_settings=EstateSettingsData(household_lifecycle="last_survivor_calendar_year_end"))
    snaps = run_simulation(p).yearly_snapshots
    assert snaps[0].healthcare.medicare_persons == 2
    assert snaps[1].healthcare.medicare_persons == 1
    assert snaps[1].expenses == pytest.approx(202.90 * 12)

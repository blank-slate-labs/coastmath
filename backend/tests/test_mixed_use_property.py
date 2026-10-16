"""Mixed-use property: a rental with a personal-use share (IRC 280A(e), 121(b)(5), 121(d)(6))."""
import uuid
from dataclasses import replace

import pytest

from coastmath.engine import real_estate
from coastmath.engine.amortization import calculate_fixed_payment
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import calculate
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    IncomeData,
    LiabilityData,
    PlanData,
    RealAssetData,
)
from coastmath.schemas.plan_data_request import RealAssetRequest
from tests.engine_support import by_year


def plan(*assets, liabilities=(), **kwargs):
    return PlanData(
        plan_id=str(uuid.uuid4()), birth_year=1980, start_year=2026, life_expectancy=55,
        filing_status="single", assumptions=AssumptionData(0, 0, 0),
        accounts={"cash": AccountInfo(1_000_000.0, "checking", name="Checking")},
        drawdown_order=[DrawdownEntryData(1, "cash")],
        real_assets=list(assets), liabilities=list(liabilities), **kwargs,
    )


def duplex(**overrides):
    values = dict(id="d", name="Duplex", current_value=500_000, annual_appreciation_rate=0.0,
                  adjusted_basis=500_000, tax_treatment="rental", rental_income=30_000,
                  rental_expenses=4_000, annual_property_tax=6_000, building_basis=275_000,
                  is_primary_residence=True, rental_use_rate=0.6)
    values.update(overrides)
    return RealAssetData(**values)


LOAN = LiabilityData(id="m", name="Mortgage", principal_balance=600_000, interest_rate=0.06,
                     term_months=360, monthly_payment=calculate_fixed_payment(600_000, 0.06, 360),
                     linked_asset_id="d")


def test_share_lookup_and_schedule_steps():
    asset = duplex(rental_use_schedule=((2028, 0.0), (2030, 1.0)))
    assert [real_estate.rental_use_share(asset, y) for y in (2026, 2027, 2028, 2029, 2030)] == [
        0.6, 0.6, 0.0, 0.0, 1.0]
    assert real_estate.is_mixed_use(asset)
    assert not real_estate.is_mixed_use(duplex(rental_use_rate=None, is_primary_residence=False))
    assert real_estate.rental_use_share(duplex(tax_treatment="personal_use"), 2026) == 0.0
    assert real_estate.depreciation_for_year(275_000, 27.5, 0, 0, 12, 0.6) == pytest.approx(6_000)


def test_sixty_forty_year_splits_rent_expenses_depreciation_and_deductions():
    full = by_year(run_simulation(plan(duplex(rental_use_rate=None, is_primary_residence=False,
                                              annual_property_tax=12_000), liabilities=[LOAN])))[2026]
    mixed = by_year(run_simulation(plan(duplex(annual_property_tax=12_000), liabilities=[LOAN])))[2026]
    assert mixed.rental_income == pytest.approx(0.6 * 30_000)
    assert mixed.rental_depreciation == pytest.approx(0.6 * 10_000)
    # Fixed rental expenses, property tax and loan interest follow the share.
    assert mixed.rental_expenses == pytest.approx(0.6 * full.rental_expenses)
    interest = full.rental_expenses - 4_000 - 12_000
    assert interest == pytest.approx(600_000 * 0.06, rel=0.02)
    # The personal 40% of property tax and mortgage interest is itemized.
    assert mixed.deduction_used == "itemized"
    assert mixed.deduction_amount == pytest.approx(0.4 * 12_000 + 0.4 * interest, abs=1)
    assert full.deduction_used == "standard"
    # Cash still pays the whole property tax and loan payment.
    assert mixed.rental_taxable_income == pytest.approx(
        0.6 * (30_000 - 4_000 - 12_000 - interest) - 6_000, abs=1)


def test_fully_rented_share_is_byte_identical_to_a_plain_rental():
    plain = duplex(rental_use_rate=None, is_primary_residence=False, sale_year=2029, sale_month=4)
    explicit = replace(plain, rental_use_rate=1.0, rental_use_schedule=((2027, 1.0),))
    a, b = run_simulation(plan(plain, liabilities=[LOAN])), run_simulation(plan(explicit, liabilities=[LOAN]))
    assert [s.model_dump() for s in a.yearly_snapshots] == [s.model_dump() for s in b.yearly_snapshots]


def test_sale_recapture_always_taxed_and_exclusion_only_on_qualified_personal_gain():
    # No depreciation in the plan (no land split) isolates the opening history:
    # $20,000 of prior depreciation, a $200,000 gain and 40% rental use since 2016.
    asset = duplex(current_value=600_000, adjusted_basis=400_000, building_basis=None,
                   prior_depreciation=20_000, rental_income=0, rental_expenses=0,
                   annual_property_tax=0, rental_use_rate=0.4, owned_since_year=2016,
                   owned_since_month=1, sale_year=2026, sale_month=7)
    sale = by_year(run_simulation(plan(asset)))[2026]
    assert sale.unrecaptured_section_1250_gain == pytest.approx(20_000)
    # Excluded: the personal 60% of the gain above recapture.
    taxable = 200_000 - 0.6 * (200_000 - 20_000)
    expected = calculate(gross_income=0, deductions=0, filing_status="single", capital_gains=taxable,
                         unrecaptured_section_1250_gain=20_000, tax_year=2026)
    assert sale.capital_gains_tax == pytest.approx(expected.capital_gains_tax, abs=0.5)
    # Failing the ownership and use test taxes the whole gain.
    short = by_year(run_simulation(plan(replace(asset, owned_since_year=2025))))[2026]
    assert short.capital_gains_tax == pytest.approx(calculate(
        gross_income=0, deductions=0, filing_status="single", capital_gains=200_000,
        unrecaptured_section_1250_gain=20_000, tax_year=2026).capital_gains_tax, abs=0.5)


def test_nonqualified_use_ratio_ignores_pre_2009_rental_on_a_home_only():
    asset = duplex(rental_use_rate=0.5)
    # 2004-01 to 2026-01: 264 months; 204 after 2008 at 50% rental.
    assert real_estate.sale_rental_share(asset, 2026, 1, (2004, 1)) == pytest.approx(102 / 264)
    vacation = replace(asset, is_primary_residence=False)
    assert real_estate.sale_rental_share(vacation, 2026, 1, (2004, 1)) == pytest.approx(0.5)
    stepped = duplex(rental_use_rate=0.0, rental_use_schedule=((2024, 1.0),))
    assert real_estate.sale_rental_share(stepped, 2026, 1, (2022, 1)) == pytest.approx(0.5)


def test_mixed_use_loss_is_ordinary_only_for_the_rental_share():
    def loss_year(share):
        asset = duplex(current_value=300_000, adjusted_basis=400_000, building_basis=None,
                       rental_income=0, rental_expenses=0, annual_property_tax=0,
                       is_primary_residence=False, rental_use_rate=share, sale_year=2027, sale_month=1)
        return by_year(run_simulation(plan(asset, income_streams=[])))[2027]
    wages = [IncomeData("w", "Wages", 200_000)]

    def taxes(share):
        asset = duplex(current_value=300_000, adjusted_basis=400_000, building_basis=None,
                       rental_income=0, rental_expenses=0, annual_property_tax=0,
                       is_primary_residence=False, rental_use_rate=share, sale_year=2027, sale_month=1)
        return by_year(run_simulation(plan(asset, income_streams=wages)))[2027].federal_tax

    full, half, none = taxes(1.0), taxes(0.5), taxes(0.0)
    assert full < half < none
    assert none - half == pytest.approx(half - full, rel=0.05)
    assert loss_year(0.5).unrecaptured_section_1250_gain == 0


def test_mixed_use_warns_that_the_deduction_cap_is_not_applied():
    result = run_simulation(plan(duplex()))
    assert any("caps rental deductions" in w for w in result.metadata.warnings)
    plain = run_simulation(plan(duplex(rental_use_rate=None, is_primary_residence=False)))
    assert not any("caps rental deductions" in w for w in plain.metadata.warnings)


@pytest.mark.anyio
async def test_api_round_trip_validation_and_stateless(client):
    p = (await client.post("/api/plans", json={
        "name": "Mixed use", "birth_year": 1980, "plan_type": "FIXED_DATE",
        "start_date": "2026-01-01", "filing_status": "single", "life_expectancy": 60,
    })).json()
    url = f"/api/plans/{p['id']}/real-assets"
    base = {"name": "Duplex", "current_value": 500000, "tax_treatment": "rental",
            "is_primary_residence": True, "rental_income": 30000, "land_value_rate": 0.2}
    rejected = await client.post(url, json=base)
    assert rejected.status_code == 422 and "rental-use share" in rejected.text
    schedule = [{"year": 2030, "rate": 1.0}, {"year": 2028, "rate": 0.0}]
    created = await client.post(url, json={**base, "rental_use_rate": 0.6, "rental_use_schedule": schedule})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["rental_use_rate"] == 0.6
    assert body["rental_use_schedule"] == sorted(schedule, key=lambda step: step["year"])
    for bad in ({"rental_use_rate": 1.5}, {"rental_use_schedule": [{"year": 2030, "rate": 0.5}] * 2},
                {"rental_use_rate": None, "rental_use_schedule": None}):
        response = await client.put(f"{url}/{body['id']}", json=bad)
        assert response.status_code == 422, (bad, response.text)
    renamed = await client.put(f"{url}/{body['id']}", json={"name": "Two-family"})
    assert renamed.json()["rental_use_rate"] == 0.6
    simulated = await client.post(f"/api/plans/{p['id']}/simulate")
    assert simulated.status_code == 200, simulated.text
    rows = {s["year"]: s for s in simulated.json()["yearly_snapshots"]}
    assert rows[2026]["rental_income"] == pytest.approx(18000)
    assert rows[2028]["rental_income"] == 0
    assert rows[2029]["rental_income"] == 0 and rows[2030]["rental_income"] > 30000
    # The stateless request takes the same fields.
    request = RealAssetRequest.model_validate({**base, "id": "d", "rental_use_rate": 0.6,
                                               "rental_use_schedule": schedule})
    engine = real_estate.engine_fields(request)
    assert engine["rental_use_rate"] == 0.6
    assert engine["rental_use_schedule"] == ((2028, 0.0), (2030, 1.0))
    assert "rental_use_rate" not in RealAssetRequest.model_validate(
        {**base, "id": "d", "is_primary_residence": False}).model_dump(exclude_unset=True)

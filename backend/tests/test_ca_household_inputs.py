"""FTB Form 540 line 10, worksheet, and Schedule Z; explicit annual inputs."""

import pytest
from pydantic import ValidationError

from app.schemas.plan import TaxSettings
from coastmath.engine.ca_exemption_credits import ca_exemption_credit
from coastmath.engine.tax_engine import calculate
from coastmath.schemas.plan_data_request import TaxSettingsRequest
from tests.corrected_fixture_support import (
    corrected_fixture,
    engine_request,
    persist_fixture,
)


@pytest.mark.parametrize("year", [2025, 2026])
def test_head_of_household_uses_schedule_z_and_11412_deduction(year):
    # Taxable $168,588; Schedule Z starts this bracket at $98,990 + $3,616.45.
    result = calculate(180000, 0, "head_of_household", state_code="CA", tax_year=year)
    assert result.state == pytest.approx(3616.45 + (180000 - 11412 - 98990) * 0.093)


@pytest.mark.parametrize("count", [0, 1, 3])
@pytest.mark.parametrize(
    "agi,reduction",
    [(100000, 0), (252203, 0), (252204, 6), (254703, 6), (254704, 12), (1000000, 475)],
)
def test_dependent_worksheet_separate_floor_from_personal_credit(count, agi, reduction):
    assert ca_exemption_credit(agi, "single", [], dependent_count=count) == count * (
        475 - reduction
    )
    base = ca_exemption_credit(agi, "single", ["self"])
    assert ca_exemption_credit(
        agi, "single", ["self"], dependent_count=count
    ) == base + count * (475 - reduction)


def test_dependent_credit_does_not_infer_future_years_or_other_states():
    settings = {"ca_dependents_by_year": {"2026": 2}}
    for year, code, expected in [(2026, "CA", 950), (2027, "CA", 0), (2026, "WA", 0)]:
        before = calculate(180000, 0, "single", state_code=code, tax_year=year)
        after = calculate(
            180000, 0, "single", settings=settings, state_code=code, tax_year=year
        )
        assert before.state - after.state == expected
    assert calculate(0, 0, "single", settings=settings, state_code="CA").state == 0


@pytest.mark.parametrize("model", [TaxSettings, TaxSettingsRequest])
@pytest.mark.parametrize(
    "values", [{"2026": -1}, {"2026": 1.5}, {"2024": 1}, {"2301": 0}]
)
def test_invalid_dependent_counts(model, values):
    with pytest.raises(ValidationError):
        model(ca_dependents_by_year=values)


@pytest.mark.anyio
async def test_dependent_settings_saved_and_simulated_both_routes(
    db_session, test_user, client
):
    raw = corrected_fixture("fire_persona")
    raw["life_expectancy"] = 50
    raw["tax_settings"] = {"ca_dependents_by_year": {"2026": 2, "2027": 0}}
    p = persist_fixture(raw, db_session, test_user)
    saved = (await client.get(f"/api/plans/{p.plan_id}")).json()["tax_settings"][
        "ca_dependents_by_year"
    ]
    assert saved == {"2026": 2, "2027": 0}
    a = await client.post(f"/api/plans/{p.plan_id}/simulate")
    b = await client.post(
        "/api/simulate/stateless", json=engine_request(p).model_dump(mode="json")
    )
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()

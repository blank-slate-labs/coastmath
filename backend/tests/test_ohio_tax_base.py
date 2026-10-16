"""Literal Ohio worksheet checks; no engine-derived expectations.

Ohio DOR 2025 booklet pp.17,20,40; ORC5747.01(A)(5),5747.025;
HB96 section757.120(A) freezes published exemption amounts through2026.
"""

from copy import deepcopy
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.schemas.plan import TaxSettings
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate
from coastmath.engine.types import IncomeData
from coastmath.schemas.plan_data_request import TaxSettingsRequest
from tests.corrected_fixture_support import (
    corrected_fixture,
    engine_request,
    persist_fixture,
)
from tests.engine_support import lifecycle_household


@pytest.mark.parametrize("magi,amount", [
    (40_000, 2_400), (40_000.01, 2_150), (80_000, 2_150),
    (80_000.01, 1_900), (499_999.99, 1_900), (500_000, 0), (600_000, 0),
])
def test_published_exemption_tiers_and_strict_2026_cap(magi, amount):
    tax, taxable = _state_tax_and_taxable_income(
        magi, "OH", oh_exemption_eligible_owners=["self"])
    assert taxable == pytest.approx(magi - amount)
    assert tax == pytest.approx(332 + (magi - amount - 26_050) * .0275)


@pytest.mark.parametrize("owners,status,count", [
    (None, "single", 0), ([], "single", 0), (["self"], "single", 1),
    (["spouse"], "single", 0), (["self", "spouse"], "single", 1),
    (["self", "spouse"], "head_of_household", 1),
    (["self", "spouse"], "married_filing_separately", 1),
    (["self", "spouse"], "married_filing_jointly", 2),
    (["spouse"], "married_filing_jointly", 1),
])
def test_only_explicit_eligible_people_are_counted(owners, status, count):
    _, taxable = _state_tax_and_taxable_income(
        100_000, "OH", filing_status=status, oh_exemption_eligible_owners=owners)
    assert taxable == 100_000 - 1_900 * count


def test_social_security_subtracts_taxable_part_and_changes_magi_tier():
    # Federal AGI104k contains34k taxable SS: Ohio MAGI70k =>$2150.
    tax, taxable = _state_tax_and_taxable_income(
        104_000, "OH", taxable_social_security=34_000,
        oh_exemption_eligible_owners=["self"])
    assert taxable == 67_850
    assert tax == pytest.approx(1_481.5)
    result = calculate(70_000, 0, "single", state_code="OH",
                       social_security_income=40_000,
                       settings={"oh_exemption_eligible_owners": ["self"]})
    assert result.state == pytest.approx(1_481.5)


def test_magi_cap_is_after_social_security_and_explicit_state_adjustments():
    _, taxable = _state_tax_and_taxable_income(
        525_000, "OH", taxable_social_security=34_000,
        oh_exemption_eligible_owners=["self"], state_income_adjustment=8_999)
    assert taxable == 498_099  # MAGI499999 minus1900.
    _, taxable_at_cap = _state_tax_and_taxable_income(
        525_000, "OH", taxable_social_security=34_000,
        oh_exemption_eligible_owners=["self"], state_income_adjustment=9_000)
    assert taxable_at_cap == 500_000


@pytest.mark.parametrize("year,factor,amount", [
    (2026, 2, 1_900), (2027, 1.03, 2_000), (2027, .9, 1_900),
    (2027, 2, 3_800),
])
def test_only_future_exemption_amounts_are_forecast_and_round_up_fifty(year, factor, amount):
    _, taxable = _state_tax_and_taxable_income(
        100_000, "OH", tax_year=year, inflation_factor=factor,
        oh_exemption_eligible_owners=["self"])
    assert taxable == 100_000 - amount
    # Tier thresholds and statutory cap do not double with factor.
    _, cap_taxable = _state_tax_and_taxable_income(
        500_000, "OH", tax_year=year, inflation_factor=factor,
        oh_exemption_eligible_owners=["self"])
    assert cap_taxable == 500_000


def test_dependent_claim_does_not_extend_or_follow_child_birth_year():
    settings = {"oh_exemption_eligible_owners": ["self"],
                "oh_dependents_by_year": {"2026": 1}, "dependent_birth_years": [2016]}
    for year, amount in [(2026, 3_800), (2027, 1_900)]:
        after = calculate(100_000, 0, "head_of_household", settings=settings,
                          state_code="OH", tax_year=year)
        assert after.state == pytest.approx(332 + (100_000 - amount - 26_050) * .0275)
    assert calculate(100_000, 0, "single", state_code="OH",
                     settings={"dependent_birth_years": [2016]}).state == pytest.approx(2_365.625)
    integer_year = calculate(100_000, 0, "single", state_code="OH",
                             settings={"oh_dependents_by_year": {2026: 1}})
    assert integer_year.state == pytest.approx(2_313.375)


def test_exemption_is_deduction_not_refundable_credit():
    assert _state_tax_and_taxable_income(
        2_000, "OH", oh_exemption_eligible_owners=["self"], oh_dependent_count=2) == (0, 0)
    # Deduction crossing zero-tax threshold also removes conditional332 base.
    assert _state_tax_and_taxable_income(
        28_000, "OH", oh_exemption_eligible_owners=["self"]) == (0, 25_600)


def test_custom_brackets_other_states_and_2025_selector_are_preserved():
    custom = [{"min": 0, "max": 999_999_999, "rate": .01}]
    assert _state_tax_and_taxable_income(
        100_000, "OH", custom_brackets=custom, taxable_social_security=34_000,
        oh_exemption_eligible_owners=["self"], oh_dependent_count=1) == (1_000, 100_000)
    for code in ("MI", "CA"):
        before = _state_tax_and_taxable_income(100_000, code)
        after = _state_tax_and_taxable_income(100_000, code,
            oh_exemption_eligible_owners=["self"], oh_dependent_count=1)
        assert after == before
    assert _state_tax_and_taxable_income(100_000, "OH", tax_year=2025,
        oh_exemption_eligible_owners=["self"], oh_dependent_count=1) == (2_365.625, 100_000)
    assert _state_tax_and_taxable_income(100_000, "OH", tax_year=2025,
        taxable_social_security=34_000)[1] == 66_000


@pytest.mark.parametrize("model", [TaxSettings, TaxSettingsRequest])
@pytest.mark.parametrize("bad", [
    {"oh_exemption_eligible_owners": ["self", "self"]},
    {"oh_exemption_eligible_owners": ["joint"]},
    {"oh_dependents_by_year": {"2026": -1}},
    {"oh_dependents_by_year": {"2026": 1.5}},
    {"oh_dependents_by_year": {"2024": 1}},
    {"oh_dependents_by_year": {"2301": 1}},
    {"oh_dependents_by_year": {"2026": 31}},
])
def test_invalid_eligibility_is_rejected_by_both_contracts(model, bad):
    with pytest.raises(ValidationError):
        model(**bad)


@pytest.mark.parametrize("model", [TaxSettings, TaxSettingsRequest])
def test_unknown_and_explicit_zero_are_distinct_preserved_inputs(model):
    assert model().oh_exemption_eligible_owners is None
    assert model().oh_dependents_by_year == {}
    explicit = model(oh_exemption_eligible_owners=[], oh_dependents_by_year={"2026": 0})
    assert explicit.oh_exemption_eligible_owners == []
    assert explicit.oh_dependents_by_year == {2026: 0}


@pytest.mark.parametrize("deceased", ["self", "spouse"])
@pytest.mark.parametrize("eligible", [["self"], ["spouse"], ["self", "spouse"]])
def test_survivor_keeps_only_the_original_persons_explicit_claim(deceased, eligible):
    survivor = "spouse" if deceased == "self" else "self"
    p = lifecycle_household(state_code="OH", tax_settings={"oh_exemption_eligible_owners": eligible},
        income_streams=[IncomeData(id="pay", name="survivor wages", annual_amount=100_000,
                                  owner=survivor)])
    if deceased == "spouse":
        p.birth_year, p.spouse_birth_year = p.spouse_birth_year, p.birth_year
        p.life_expectancy, p.spouse_life_expectancy = p.spouse_life_expectancy, p.life_expectancy
    original = deepcopy(p)
    rows = run_simulation(p).yearly_snapshots
    before = run_simulation(replace(p, tax_settings={"oh_exemption_eligible_owners": []})).yearly_snapshots
    assert rows[0].state_tax == pytest.approx(2_365.625 - len(eligible) * 52.25)
    expected_survivor_saving = 52.25 if survivor in eligible else 0
    assert rows[1].state_tax == pytest.approx(2_365.625 - expected_survivor_saving)
    assert rows[1].net_worth - before[1].net_worth == pytest.approx(
        len(eligible) * 52.25 + expected_survivor_saving)
    assert p == original


@pytest.mark.anyio
async def test_ohio_eligibility_saved_and_stateless_routes_match_literal_first_year(
    db_session, test_user, client,
):
    raw = corrected_fixture("fire_persona")
    raw["life_expectancy"] = 50
    raw["state_code"] = "OH"
    raw["residency_periods"] = []
    raw["tax_settings"] = {"oh_exemption_eligible_owners": ["self"],
                           "oh_dependents_by_year": {"2026": 1, "2027": 0}}
    p = persist_fixture(raw, db_session, test_user)
    saved = (await client.get(f"/api/plans/{p.plan_id}")).json()["tax_settings"]
    assert saved["oh_exemption_eligible_owners"] == ["self"]
    assert saved["oh_dependents_by_year"] == {"2026": 1, "2027": 0}
    # Old clients editing another field retain both additive settings. A
    # rejected claim must also leave the previously saved assertions intact.
    assert (await client.put(f"/api/plans/{p.plan_id}", json={"name": "Ohio verified"})).status_code == 200
    rejected = await client.put(f"/api/plans/{p.plan_id}", json={"tax_settings": {
        "oh_exemption_eligible_owners": ["self", "self"]}})
    assert rejected.status_code == 422
    reloaded = (await client.get(f"/api/plans/{p.plan_id}")).json()["tax_settings"]
    assert reloaded == saved
    a = await client.post(f"/api/plans/{p.plan_id}/simulate",
                         headers={"X-Client-Date": "2026-09-08"})
    b = await client.post("/api/simulate/stateless", json=engine_request(p).model_dump(mode="json"))
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    row = a.json()["yearly_snapshots"][0]
    # Frozen source wages180k, zero payroll deductions: Ohio base176200.
    assert row["state_tax"] == pytest.approx(4_461.125)


def test_single_owner_final_calendar_year_retains_eligible_taxpayer_exemption():
    # A single owner reaches longevity in2026. The explicit convention
    # includes that whole final return; no2027 income/claim is manufactured.
    p = lifecycle_household(spouse_birth_year=None, spouse_life_expectancy=None,
        spouse_birth_month=None, filing_status="single", state_code="OH",
        tax_settings={"oh_exemption_eligible_owners": ["self"]},
        income_streams=[IncomeData(id="pay", name="final wages", annual_amount=100_000)])
    rows = run_simulation(p).yearly_snapshots
    assert [row.year for row in rows] == [2026]
    assert rows[0].gross_income == 100_000
    assert rows[0].state_tax == pytest.approx(2_313.375)

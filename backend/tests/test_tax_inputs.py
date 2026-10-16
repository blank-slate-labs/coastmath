"""Custom federal brackets, payroll wage-base elections, the statutory Medicare
Part A premium and an assumed RMD start age."""
from __future__ import annotations

import uuid
from dataclasses import asdict, replace

import pytest
from pydantic import ValidationError

from app.schemas.expense import ExpenseCreate, ExpenseRead, PayrollTaxElections
from app.schemas.plan import TaxSettings
from coastmath.engine.healthcare import part_a_premium_monthly
from coastmath.engine.payroll_elections import payroll_wage_reductions
from coastmath.engine.rmd import calculate_rmd, is_rmd_required, rmd_start_age_override
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import (
    calculate,
    federal_ordinary_brackets,
    get_federal_brackets,
)
from coastmath.engine.tax_schedule import effective_tax_settings
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PlanData,
)
from coastmath.schemas.person_healthcare import PersonHealthcareSettings
from coastmath.schemas.plan_data_request import (
    ExpenseRequest,
    PlanDataRequest,
    request_to_engine_data,
)

FLAT_10 = [[1_000_000_000, 0.10]]


def _wage_plan(**changes) -> PlanData:
    values = dict(
        plan_id=str(uuid.uuid4()), birth_year=1980, filing_status="single", life_expectancy=90,
        start_year=2026,
        income_streams=[IncomeData(id="salary", name="Wages", annual_amount=100_000)],
        accounts={"cash": AccountInfo(balance=0, account_type="checking")},
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0),
    )
    values.update(changes)
    return PlanData(**values)


# ---------------------------------------------------------------------------
# Custom federal brackets and standard deduction
# ---------------------------------------------------------------------------

def test_default_settings_keep_built_in_federal_tax():
    base = calculate(100_000, 0, "single")
    assert calculate(100_000, 0, "single", settings={}) == base
    assert calculate(100_000, 0, "single", settings={"federal_brackets": []}) == base
    assert federal_ordinary_brackets(None, "single", 2026, 1.0, 1.0) == get_federal_brackets("single", 2026)


def test_custom_federal_schedule_and_standard_deduction_replace_ordinary_tax():
    settings = {"federal_brackets": [[50_000, 0.10], [1_000_000_000, 0.30]], "federal_standard_deduction": 10_000}
    result = calculate(100_000, 0, "single", settings=settings)
    assert result.standard_deduction == pytest.approx(10_000)
    assert result.taxable_income == pytest.approx(90_000)
    assert result.federal == pytest.approx(50_000 * 0.10 + 40_000 * 0.30)
    assert result.marginal_rate == pytest.approx(0.30)


def test_custom_brackets_leave_capital_gains_tax_unchanged():
    base = calculate(80_000, 0, "single", capital_gains=30_000)
    custom = calculate(80_000, 0, "single", capital_gains=30_000, settings={"federal_brackets": FLAT_10})
    assert custom.capital_gains_tax == pytest.approx(base.capital_gains_tax)
    assert custom.federal != pytest.approx(base.federal)


def test_custom_amounts_index_with_plan_inflation_unless_unindexed():
    settings = {"federal_brackets": [[50_000, 0.10], [1_000_000_000, 0.30]], "federal_standard_deduction": 10_000}
    indexed = calculate(200_000, 0, "single", settings=settings, inflation_factor=2.0, federal_inflation_factor=1.5)
    assert indexed.standard_deduction == pytest.approx(20_000)
    assert indexed.federal == pytest.approx(100_000 * 0.10 + 80_000 * 0.30)
    nominal = calculate(200_000, 0, "single", settings={**settings, "federal_overrides_indexed": False},
                        inflation_factor=2.0, federal_inflation_factor=1.5)
    assert nominal.standard_deduction == pytest.approx(10_000)
    assert nominal.federal == pytest.approx(50_000 * 0.10 + 140_000 * 0.30)


def test_custom_federal_brackets_in_a_projection_and_a_scheduled_change():
    settings = {"federal_brackets": FLAT_10, "federal_standard_deduction": 0,
                "scheduled_changes": [
                    {"year": 2028, "settings": {"federal_brackets": [[1_000_000_000, 0.20]]}},
                    {"year": 2030, "settings": {"federal_brackets": []}}]}
    TaxSettings.model_validate(settings)
    snaps = run_simulation(_wage_plan(tax_settings=settings)).yearly_snapshots
    by_year = {snap.year: snap for snap in snaps}
    assert by_year[2026].federal_tax == pytest.approx(10_000)
    assert by_year[2028].federal_tax == pytest.approx(20_000)
    # An empty schedule returns to the built-in brackets; the deduction override stays.
    built_in = calculate(100_000, 0, "single", settings={"federal_standard_deduction": 0}, tax_year=2030)
    assert by_year[2030].federal_tax == pytest.approx(built_in.federal)
    assert effective_tax_settings(settings, 2031, {}).get("federal_brackets") is None


def test_federal_override_schema_validation_and_byte_identical_dumps():
    assert TaxSettings().model_dump() == TaxSettings.model_validate(TaxSettings().model_dump()).model_dump()
    dumped = TaxSettings().model_dump()
    for key in ("federal_brackets", "federal_standard_deduction", "federal_overrides_indexed", "rmd_start_ages"):
        assert key not in dumped
    assert TaxSettings(federal_overrides_indexed=False).model_dump()["federal_overrides_indexed"] is False
    with pytest.raises(ValidationError, match="Federal bracket upper bounds"):
        TaxSettings(federal_brackets=[[50_000, 0.1], [40_000, 0.2]])
    with pytest.raises(ValidationError):
        TaxSettings(federal_standard_deduction=-1)


# ---------------------------------------------------------------------------
# Payroll deduction wage-base elections
# ---------------------------------------------------------------------------

def _payroll_plan(treatment="pre_tax", elections=None, state_code="IL"):
    return _wage_plan(state_code=state_code, expenses=[ExpenseData(
        id="deduction", name="Deduction", annual_amount=12_000, inflation_linked=False,
        is_payroll_deduction=True, payroll_tax_treatment=treatment, tied_income_id="salary",
        payroll_tax_elections=elections)])


def test_election_defaults_follow_the_treatment():
    assert asdict(payroll_wage_reductions("pre_tax", None)) == {
        "federal": True, "state": True, "local": True, "fica": False}
    assert asdict(payroll_wage_reductions("after_tax", None)) == {
        "federal": False, "state": False, "local": False, "fica": False}
    assert asdict(payroll_wage_reductions(None, {"fica": True, "state": None})) == {
        "federal": True, "state": True, "local": True, "fica": True}


@pytest.mark.parametrize("treatment", ["pre_tax", "after_tax"])
def test_explicit_default_elections_match_saved_expenses(treatment):
    defaults = asdict(payroll_wage_reductions(treatment, None))
    plain = run_simulation(_payroll_plan(treatment)).yearly_snapshots
    explicit = run_simulation(_payroll_plan(treatment, defaults)).yearly_snapshots
    assert [s.model_dump() for s in plain] == [s.model_dump() for s in explicit]


def test_section_125_premium_reduces_fica_wages_but_a_401k_style_deferral_does_not():
    deferral = run_simulation(_payroll_plan("pre_tax")).yearly_snapshots[0]
    after_tax = run_simulation(_payroll_plan("after_tax")).yearly_snapshots[0]
    cafeteria = run_simulation(_payroll_plan("pre_tax", {"fica": True})).yearly_snapshots[0]
    # Deferral: FICA on full wages, like an after-tax deduction.
    assert deferral.fica_tax == pytest.approx(after_tax.fica_tax)
    assert deferral.fica_tax == pytest.approx(100_000 * 0.0765)
    # Section 125: 6.2% + 1.45% less on the premium; income tax unchanged.
    assert cafeteria.fica_tax == pytest.approx(88_000 * 0.0765)
    assert cafeteria.federal_tax == pytest.approx(deferral.federal_tax)
    assert cafeteria.state_tax == pytest.approx(deferral.state_tax)
    # Cash is charged once either way.
    assert cafeteria.cash_flow.payroll_deductions == pytest.approx(12_000)


def test_state_only_and_federal_only_elections():
    pre_tax = run_simulation(_payroll_plan("pre_tax")).yearly_snapshots[0]
    after_tax = run_simulation(_payroll_plan("after_tax")).yearly_snapshots[0]
    state_only = run_simulation(_payroll_plan("pre_tax", {"federal": False})).yearly_snapshots[0]
    federal_only = run_simulation(_payroll_plan("pre_tax", {"state": False})).yearly_snapshots[0]
    assert state_only.federal_tax == pytest.approx(after_tax.federal_tax)
    assert state_only.state_tax == pytest.approx(pre_tax.state_tax)
    assert federal_only.federal_tax == pytest.approx(pre_tax.federal_tax)
    assert federal_only.state_tax == pytest.approx(after_tax.state_tax)
    assert pre_tax.state_tax < after_tax.state_tax


def test_elections_schema_and_stateless_request():
    assert "payroll_tax_elections" not in ExpenseCreate(name="x").model_dump()
    with pytest.raises(ValidationError):
        PayrollTaxElections(medicare=True)
    assert PayrollTaxElections(fica=True).model_dump() == {"fica": True}
    request = PlanDataRequest(
        plan_id=uuid.uuid4(), birth_year=1980, start_year=2026,
        income_streams=[{"id": "salary", "name": "Wages", "annual_amount": 100_000}],
        expenses=[ExpenseRequest(id="d", name="Premium", annual_amount=1_000, is_payroll_deduction=True,
                                 tied_income_id="salary", payroll_tax_elections={"fica": True})])
    assert request_to_engine_data(request).expenses[0].payroll_tax_elections == {"fica": True}
    plain = ExpenseRequest(id="d", name="Premium", annual_amount=1_000)
    assert "payroll_tax_elections" not in plain.model_dump(exclude_unset=False)


# ---------------------------------------------------------------------------
# Medicare Part A premium
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("quarters,monthly", [(None, 0.0), (40, 0.0), (55, 0.0), (39, 311.0), (30, 311.0),
                                              (29, 565.0), (0, 565.0)])
def test_part_a_premium_tiers(quarters, monthly):
    assert part_a_premium_monthly(quarters) == monthly


def _medicare_plan(person: dict, rate: float | None = None) -> PlanData:
    settings = {"enabled": True, "persons": [{"owner": "self", "mode": "coverage", "medicare_part_d": False,
                                              "medicare_apply_irmaa": False, **person}]}
    if rate is not None:
        settings["medical_inflation_rate"] = rate
    return PlanData(
        plan_id=str(uuid.uuid4()), start_year=2026, birth_year=1960, birth_month=1, life_expectancy=70,
        filing_status="single", drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash")],
        accounts={"cash": AccountInfo(balance=2_000_000, account_type="checking")},
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0),
        healthcare_settings=settings)


def test_part_a_quarters_add_the_published_premium_and_default_adds_none():
    unset = run_simulation(_medicare_plan({})).yearly_snapshots[0].healthcare
    assert unset.medicare_part_a == 0
    full_quarters = run_simulation(_medicare_plan({"medicare_part_a_quarters": 40})).yearly_snapshots
    assert [s.model_dump() for s in full_quarters] == [s.model_dump() for s in run_simulation(_medicare_plan({})).yearly_snapshots]
    reduced = run_simulation(_medicare_plan({"medicare_part_a_quarters": 32})).yearly_snapshots[0]
    assert reduced.healthcare.medicare_part_a == pytest.approx(311 * 12)
    assert reduced.healthcare.total == pytest.approx(unset.total + 311 * 12)
    full = run_simulation(_medicare_plan({"medicare_part_a_quarters": 10,
                                          "medicare_part_a_premium_monthly": 5})).yearly_snapshots[0]
    # An entered premium is added on top of the statutory one.
    assert full.healthcare.medicare_part_a == pytest.approx((565 + 5) * 12)


def test_part_a_premium_indexes_like_part_b():
    snaps = run_simulation(_medicare_plan({"medicare_part_a_quarters": 0}, rate=0.05)).yearly_snapshots
    later = snaps[2].healthcare
    assert later.medicare_part_a / (565 * 12) == pytest.approx(later.medicare_part_b / (202.90 * 12))
    assert later.medicare_part_a == pytest.approx(565 * 12 * 1.05 ** 2)
    with pytest.raises(ValidationError):
        PersonHealthcareSettings(owner="self", mode="coverage", medicare_part_a_quarters=-1)


# ---------------------------------------------------------------------------
# Assumed RMD start age
# ---------------------------------------------------------------------------

def test_rmd_start_age_override_unit_rules():
    assert rmd_start_age_override(None, "self") is None
    assert rmd_start_age_override({"rmd_start_ages": {"spouse": 77}}, "self") is None
    assert rmd_start_age_override({"rmd_start_ages": {"spouse": 77}}, "spouse") == 77
    assert is_rmd_required(73, 1953) and not is_rmd_required(73, 1953, start_age=75)
    assert calculate_rmd(100_000, 74, 1953, start_age=75) == 0
    assert calculate_rmd(100_000, 73, 1965, start_age=73) > 0
    with pytest.raises(ValidationError):
        TaxSettings(rmd_start_ages={"self": 69})
    with pytest.raises(ValidationError):
        TaxSettings(rmd_start_ages={"partner": 75})


def _rmd_plan(tax_settings=None) -> PlanData:
    return PlanData(
        plan_id=str(uuid.uuid4()), birth_year=1951, birth_month=1, filing_status="married_filing_jointly",
        life_expectancy=90, start_year=2026, spouse_birth_year=1952, spouse_birth_month=1,
        spouse_life_expectancy=90, state_code="FL",
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0),
        accounts={"ira": AccountInfo(1_000_000, "traditional_ira", owner="self"),
                  "spouse_ira": AccountInfo(500_000, "traditional_ira", owner="spouse")},
        tax_settings=tax_settings)


def _rmds(result, year):
    snap = next(s for s in result.yearly_snapshots if s.year == year)
    return sum(item.amount for item in snap.cash_flow.income_sources if item.name == "RMD")


def test_rmd_start_age_override_delays_only_that_owner():
    default = run_simulation(_rmd_plan())
    assert default.metadata.rmd_start_age == 73
    assert _rmds(default, 2026) > 0
    delayed = run_simulation(_rmd_plan({"rmd_start_ages": {"self": 77}}))
    assert delayed.metadata.rmd_start_age == 77
    # 2026: owner is 75, below 77; the spouse (74, statute 73) still takes theirs.
    spouse_only = calculate_rmd(500_000, 74, 1952)
    assert _rmds(delayed, 2026) == pytest.approx(spouse_only)
    assert _rmds(delayed, 2028) > spouse_only  # owner reaches 77


def test_plan_without_rmd_override_is_unchanged():
    base = run_simulation(_rmd_plan()).yearly_snapshots
    explicit_none = run_simulation(_rmd_plan({})).yearly_snapshots
    assert [s.model_dump() for s in base] == [s.model_dump() for s in explicit_none]


def test_expense_read_omits_unset_elections():
    row = replace(ExpenseData(id="x", name="x", annual_amount=0))  # engine row is unaffected
    assert row.payroll_tax_elections is None
    read = ExpenseRead.model_validate({
        "id": uuid.uuid4(), "plan_id": uuid.uuid4(), "name": "x", "annual_amount": 0,
        "inflation_linked": True, "is_payroll_deduction": False})
    assert "payroll_tax_elections" not in read.model_dump()


# ---------------------------------------------------------------------------
# Persistence (SQLite fixtures)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_expense_elections_persist_clear_and_guard_stale_edits(client):
    plan = (await client.post("/api/plans", json={"name": "Elections", "birth_year": 1980})).json()
    income = (await client.post(f"/api/plans/{plan['id']}/incomes",
                                json={"name": "Wages", "annual_amount": 100_000})).json()
    base = f"/api/plans/{plan['id']}/expenses"
    plain = (await client.post(base, json={"name": "Rent", "annual_amount": 1_000})).json()
    assert "payroll_tax_elections" not in plain
    created = await client.post(base, json={
        "name": "Medical premium", "annual_amount": 3_000, "is_payroll_deduction": True,
        "tied_income_id": income["id"], "payroll_tax_elections": {"fica": True}})
    assert created.status_code == 201, created.text
    expense = created.json()
    assert expense["payroll_tax_elections"] == {"fica": True}
    path = f"{base}/{expense['id']}"
    stale = await client.put(path, json={"payroll_tax_elections": {"fica": False},
                                         "expected_values": {"payroll_tax_elections": None}})
    assert stale.status_code == 409
    updated = await client.put(path, json={"payroll_tax_elections": {"state": False},
                                           "expected_values": {"payroll_tax_elections": {"fica": True}}})
    assert updated.status_code == 200 and updated.json()["payroll_tax_elections"] == {"state": False}
    cleared = await client.put(path, json={"payroll_tax_elections": None})
    assert cleared.status_code == 200 and "payroll_tax_elections" not in cleared.json()
    rejected = await client.put(path, json={"payroll_tax_elections": {"medicare": True}})
    assert rejected.status_code == 422


@pytest.mark.anyio
async def test_federal_overrides_and_rmd_start_ages_persist_in_tax_settings(client):
    plan = (await client.post("/api/plans", json={"name": "Law change", "birth_year": 1960})).json()
    settings = {"federal_brackets": [[50_000, 0.1], [1_000_000_000, 0.25]], "federal_standard_deduction": 20_000,
                "federal_overrides_indexed": False, "rmd_start_ages": {"self": 77},
                "scheduled_changes": [{"year": 2030, "settings": {"federal_brackets": []}}]}
    saved = await client.put(f"/api/plans/{plan['id']}", json={"tax_settings": settings})
    assert saved.status_code == 200, saved.text
    stored = (await client.get(f"/api/plans/{plan['id']}")).json()["tax_settings"]
    for key, value in settings.items():
        assert stored[key] == value
    bad = await client.put(f"/api/plans/{plan['id']}", json={"tax_settings": {"rmd_start_ages": {"self": 90}}})
    assert bad.status_code == 422

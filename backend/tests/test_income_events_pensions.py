"""Cash timing, tax classification and salary-service pension regressions."""
import uuid

import pytest
from pydantic import ValidationError

import coastmath.engine.simulator as engine
from app.schemas.income import PensionFormula
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    MilestoneData,
    PlanData,
)
from coastmath.schemas.plan_data_request import (
    PlanDataRequest,
    request_to_engine_data,
)


def plan(**kwargs):
    def uid(value):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, value)) if value else None
    for inc in kwargs.get("income_streams", []):
        # Engine stream identities are opaque; milestones become UUID response identities.
        inc.start_milestone_id = uid(inc.start_milestone_id)
        inc.end_milestone_id = uid(inc.end_milestone_id)
    for ms in kwargs.get("milestones", []):
        ms.id = uid(ms.id)
    for change in kwargs.get("filing_status_changes", []):
        if change.get("milestone_id"):
            change["milestone_id"] = uid(change["milestone_id"])
    return PlanData(plan_id=str(uuid.uuid4()), birth_year=1976, life_expectancy=56, start_year=2026,
                    filing_status="single", assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0),
                    accounts={"cash": AccountInfo(balance=0, account_type="savings", name="Cash")}, **kwargs)


def date_ms(identity, date):
    return MilestoneData(identity, identity, "date", trigger_date=date)


def test_once_full_payment_grows_to_start_and_never_repeats():
    rows = run_simulation(plan(milestones=[date_ms("pay", "2028-09-01")], income_streams=[
        IncomeData("bonus", "Bonus", 10000, frequency="once", start_milestone_id="pay", tax_category="employment", growth_rate=.1),
    ])).yearly_snapshots
    assert [s.gross_income for s in rows] == pytest.approx([0, 0, 12100, 0, 0, 0])
    assert rows[2].taxes > 0


@pytest.mark.parametrize("month, cash, calendar", [(3, 0, 10000), (9, 10000, 10000)])
def test_once_midyear_start(month, cash, calendar):
    rows = run_simulation(plan(first_year_fraction=.5, milestones=[date_ms("pay", f"2026-{month:02}-01")], income_streams=[
        IncomeData("bonus", "Bonus", 10000, frequency="once", start_milestone_id="pay", tax_category="employment"),
    ])).yearly_snapshots
    assert rows[0].gross_income == cash
    assert rows[0].calendar_year_gross_income == calendar


def test_nontaxable_cash_excluded_from_tax_bases():
    first = run_simulation(plan(income_streams=[IncomeData("gift", "Gift", 100000, tax_category="nontaxable")])).yearly_snapshots[0]
    assert first.gross_income == first.cash_flow.gross_income == 100000
    assert first.fica_tax == first.taxes == 0
    assert first.net_worth == 100000


@pytest.mark.parametrize("kind,expected", [("final_average", (110000 + 121000) / 2 * 13 * .015),
                                         ("career_average", (100000 * 11 + 110000 + 121000) * .015)])
def test_salary_pension_with_prior_service(kind, expected):
    rows = run_simulation(plan(milestones=[date_ms("retire", "2029-01-01")], income_streams=[
        IncomeData("salary", "Salary", 100000, tax_category="employment", growth_rate=.1, end_milestone_id="retire"),
        IncomeData("pension", "Pension", 0, tax_category="qualified_pension", start_milestone_id="retire",
            pension_formula={"kind": kind, "linked_income_id": "salary", "benefit_percent_per_year": 1.5,
                             "years_of_service_before_plan": 10, "final_average_years": 2, "cola_percent": 2}),
    ])).yearly_snapshots
    assert rows[3].gross_income == pytest.approx(expected)
    assert rows[4].gross_income == pytest.approx(expected * 1.02)


def test_flat_pension_and_cola():
    data = plan(milestones=[date_ms("retire", "2028-07-01")], income_streams=[
        IncomeData("pension", "Pension", 0, tax_category="qualified_pension", start_milestone_id="retire",
                   pension_formula={"kind": "flat", "flat_annual_amount": 20000, "cola_percent": 2}),
    ])
    data.assumptions.inflation_rate = .03
    rows = run_simulation(data).yearly_snapshots
    assert rows[2].gross_income == pytest.approx(20000 * 1.03**2 * .5)
    assert rows[3].gross_income == pytest.approx(20000 * 1.03**2 * 1.02)


def test_income_every_three_years():
    rows = run_simulation(plan(income_streams=[IncomeData("pay", "Pay", 10000, tax_category="nontaxable", recurrence_years=3)])).yearly_snapshots
    assert [s.gross_income for s in rows] == [10000, 0, 0, 10000, 0, 0]


def test_marriage_uses_joint_status_in_event_year():
    wages = [IncomeData("pay", "Pay", 100000, tax_category="employment")]
    original = run_simulation(plan(income_streams=wages)).yearly_snapshots
    updated = run_simulation(plan(income_streams=wages, milestones=[date_ms("marry", "2027-12-01")],
        filing_status_changes=[{"milestone_id": "marry", "filing_status": "married_filing_jointly"}])).yearly_snapshots
    assert updated[0].taxes == original[0].taxes
    assert updated[1].taxes < original[1].taxes


@pytest.mark.anyio
async def test_income_formula_status_api_roundtrip_and_validation(client):
    response = await client.post("/api/plans", json={"name": "Events", "birth_year": 1976,
        "filing_status_changes": [{"year": 2028, "filing_status": "married_filing_jointly"}]})
    assert response.status_code == 201, response.text
    pid = response.json()["id"]
    salary = await client.post(f"/api/plans/{pid}/incomes", json={"name": "Salary", "annual_amount": 100000, "tax_category": "employment"})
    sid = salary.json()["id"]
    body = {"name": "Pension", "annual_amount": 0, "tax_category": "qualified_pension", "recurrence_years": 3,
            "pension_formula": {"kind": "final_average", "linked_income_id": sid, "benefit_percent_per_year": 1.5}}
    pension = await client.post(f"/api/plans/{pid}/incomes", json=body)
    assert pension.status_code == 201, pension.text
    assert pension.json()["pension_formula"]["linked_income_id"] == sid
    assert pension.json()["recurrence_years"] == 3
    assert (await client.put(f"/api/plans/{pid}/incomes/{sid}", json={"owner": "spouse"})).status_code == 422
    assert (await client.delete(f"/api/plans/{pid}/incomes/{sid}")).status_code == 422
    body["owner"] = "spouse"
    assert (await client.post(f"/api/plans/{pid}/incomes", json=body)).status_code == 422
    gift = await client.post(f"/api/plans/{pid}/incomes", json={"name": "Gift", "frequency": "once", "annual_amount": 50000, "tax_category": "nontaxable"})
    assert gift.status_code == 201
    saved = (await client.get(f"/api/plans/{pid}")).json()
    assert saved["filing_status_changes"][0]["year"] == 2028
    assert any(i["frequency"] == "once" for i in saved["income_streams"])
    duplicate = await client.post(f"/api/plans/{pid}/duplicate")
    assert duplicate.status_code == 201, duplicate.text
    copy = duplicate.json()
    copied_salary = next(i for i in copy["income_streams"] if i["name"] == "Salary")
    copied_pension = next(i for i in copy["income_streams"] if i["name"] == "Pension")
    assert copied_pension["pension_formula"]["linked_income_id"] == copied_salary["id"]
    assert copied_salary["id"] != sid


@pytest.mark.parametrize("earned,withholding", [(True, .4), (False, .25), (True, 0)])
def test_nontaxable_ignores_stale_wage_flags_and_withholding(monkeypatch, earned, withholding):
    original = engine.calculate_tax
    bases = []

    def capture(**kwargs):
        result = original(**kwargs)
        bases.append((kwargs["gross_income"], kwargs.get("earned_income", 0), result.agi, result.modified_agi))
        return result

    monkeypatch.setattr(engine, "calculate_tax", capture)
    rows = run_simulation(plan(income_streams=[IncomeData("gift", "Gift", 100000, tax_category="nontaxable",
        is_earned_income=earned, is_self_employed=True, withholding_percent=withholding)])).yearly_snapshots
    assert all(all(value == 0 for value in base) for base in bases)
    assert rows[0].taxes == rows[0].fica_tax == 0
    assert rows[0].cash_flow.net_pay == 100000


@pytest.mark.parametrize("active", [True, False])
def test_pension_partial_service_and_inactive_salary(active):
    rows = run_simulation(plan(first_year_fraction=.5, milestones=[date_ms("retire", "2027-01-01")], income_streams=[
        IncomeData("salary", "Salary", 100000, tax_category="employment", is_active=active, end_milestone_id="retire"),
        IncomeData("pension", "Pension", 0, tax_category="qualified_pension", start_milestone_id="retire",
            pension_formula={"kind": "career_average", "linked_income_id": "salary", "benefit_percent_per_year": 2}),
    ])).yearly_snapshots
    assert rows[1].gross_income == (1000 if active else 0)


def test_schedule_cannot_override_status_after_death():
    data = plan(spouse_birth_year=1976, spouse_life_expectancy=52,
                filing_status_changes=[{"year": 2027, "filing_status": "married_filing_jointly"},
                                       {"year": 2030, "filing_status": "married_filing_jointly"}],
                income_streams=[IncomeData("salary", "Salary", 100000, tax_category="employment")])
    rows = run_simulation(data).yearly_snapshots
    single = run_simulation(plan(income_streams=[IncomeData("salary", "Salary", 100000, tax_category="employment")])).yearly_snapshots
    assert rows[1].taxes < single[1].taxes
    assert rows[4].taxes == single[4].taxes


def test_stateless_formula_validation_and_conversion():
    payload = {"plan_id": str(uuid.uuid4()), "birth_year": 1976, "start_year": 2026, "income_streams": [
        {"id": "salary", "name": "Salary", "annual_amount": 100000, "tax_category": "employment"},
        {"id": "pension", "name": "Pension", "annual_amount": 0, "tax_category": "qualified_pension",
         "pension_formula": {"kind": "career_average", "linked_income_id": "salary", "benefit_percent_per_year": 2}},
    ], "filing_status_changes": [{"year": 2028, "filing_status": "married_filing_jointly"}]}
    request = PlanDataRequest(**payload)
    data = request_to_engine_data(request)
    assert data.income_streams[1].pension_formula["linked_income_id"] == "salary"
    assert data.filing_status_changes[0]["year"] == 2028
    payload["income_streams"][1]["pension_formula"]["linked_income_id"] = "missing"
    with pytest.raises(ValidationError, match="same owner"):
        PlanDataRequest(**payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_pension_formula_rejects_nonfinite_values(value):
    with pytest.raises(ValidationError):
        PensionFormula(kind="flat", flat_annual_amount=value)


@pytest.mark.anyio
async def test_schedule_milestone_ownership_and_delete_guard(client):
    response = await client.post("/api/plans", json={"name": "Schedule", "birth_year": 1976})
    pid = response.json()["id"]
    created = await client.post(f"/api/plans/{pid}/milestones", json={"name": "Marriage", "trigger_type": "date", "trigger_date": "2030-12-01"})
    mid = created.json()["id"]
    changes = [{"milestone_id": mid, "filing_status": "married_filing_jointly"}]
    updated = await client.put(f"/api/plans/{pid}", json={"filing_status_changes": changes})
    assert updated.status_code == 200, updated.text
    assert (await client.delete(f"/api/plans/{pid}/milestones/{mid}")).status_code == 409
    bad = [{"milestone_id": str(uuid.uuid4()), "filing_status": "single"}]
    assert (await client.put(f"/api/plans/{pid}", json={"filing_status_changes": bad})).status_code == 422
    assert (await client.put(f"/api/plans/{pid}", json={"filing_status_changes": []})).status_code == 200
    assert (await client.delete(f"/api/plans/{pid}/milestones/{mid}")).status_code == 204


@pytest.mark.parametrize("kind", ["career_average", "final_average"])
def test_pension_rejects_one_time_salary_in_direct_and_stateless_inputs(kind):
    salary = IncomeData("award", "Award", 120000, tax_category="employment", frequency="once", start_month=7)
    formula = {"kind": kind, "linked_income_id": "award", "benefit_percent_per_year": 2}
    pension = IncomeData("pension", "Pension", 0, tax_category="qualified_pension", pension_formula=formula)
    with pytest.raises(ValueError, match="recurring earned income stream"):
        run_simulation(plan(income_streams=[salary, pension]))
    with pytest.raises(ValidationError, match="recurring earned income stream"):
        PlanDataRequest(plan_id=str(uuid.uuid4()), birth_year=1976, start_year=2026, income_streams=[
            {"id": "award", "name": "Award", "annual_amount": 120000, "tax_category": "employment", "frequency": "once"},
            {"id": "pension", "name": "Pension", "annual_amount": 0, "tax_category": "qualified_pension", "pension_formula": formula},
        ])


@pytest.mark.anyio
async def test_api_pension_requires_recurring_salary_and_retains_valid_link(client):
    created = await client.post("/api/plans", json={"name": "Pension eligibility", "birth_year": 1976})
    base = f"/api/plans/{created.json()['id']}/incomes"
    award = await client.post(base, json={"name": "Award", "annual_amount": 120000, "frequency": "once", "tax_category": "employment"})
    salary = await client.post(base, json={"name": "Salary", "annual_amount": 120000, "tax_category": "employment"})
    aid, sid = award.json()["id"], salary.json()["id"]
    formula = {"kind": "career_average", "linked_income_id": aid, "benefit_percent_per_year": 2}
    rejected = await client.post(base, json={"name": "Pension", "tax_category": "qualified_pension", "pension_formula": formula})
    assert rejected.status_code == 422
    assert "recurring earned income stream" in rejected.json()["error"]["message"]
    formula["linked_income_id"] = sid
    pension = await client.post(base, json={"name": "Pension", "tax_category": "qualified_pension", "pension_formula": formula})
    assert pension.status_code == 201
    pid = pension.json()["id"]
    assert (await client.put(f"{base}/{sid}", json={"frequency": "once"})).status_code == 422
    formula["linked_income_id"] = aid
    assert (await client.put(f"{base}/{pid}", json={"pension_formula": formula})).status_code == 422
    saved = (await client.get(base)).json()
    assert next(i for i in saved if i["id"] == sid)["frequency"] == "recurring"
    assert next(i for i in saved if i["id"] == pid)["pension_formula"]["linked_income_id"] == sid

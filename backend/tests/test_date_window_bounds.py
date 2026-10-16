"""Date validation and bounded cash flows."""
import uuid
from datetime import date

import pytest

from app.models.plan import Plan
from coastmath.engine.milestones import prorate_for_year
from coastmath.engine.types import MilestoneData


@pytest.mark.parametrize("kind", ["date", "age", "relative"])
@pytest.mark.parametrize("same", [True, False])
def test_same_year_proration_preserves_start_and_end(kind, same):
    start = MilestoneData(id="start", name="Start", trigger_type=kind, trigger_date="2027-07-01", trigger_value=37)
    end = start if same else MilestoneData(id="end", name="End", trigger_type=kind, trigger_date="2027-12-01", trigger_value=37)
    fired = {start.id, end.id}
    assert prorate_for_year(start, end, 7, 12, set(), [], 2026) == 0
    assert prorate_for_year(start, end, 7, 12, fired, list(fired), 2027) == pytest.approx(.5)
    assert prorate_for_year(start, end, 7, 12, fired, list(fired), 2027, simulation_fraction=.25) == pytest.approx(.25)
    assert prorate_for_year(start, end, 7, 12, fired, [], 2028) == 0


def test_date_month_precedence_and_default_end_exclusion():
    ms = MilestoneData(id="m", name="July", trigger_type="date", trigger_date="2027-07-01")
    assert prorate_for_year(ms, ms, None, 12, {"m"}, ["m"], 2027) == .5
    assert prorate_for_year(ms, ms, 1, None, {"m"}, ["m"], 2027) == .5
    # Without overrides the same boundary starts in July and ends before July.
    assert prorate_for_year(ms, ms, None, None, {"m"}, ["m"], 2027) == 0


@pytest.mark.anyio
@pytest.mark.parametrize("entity", ["incomes", "expenses"])
@pytest.mark.parametrize("same", [True, False])
@pytest.mark.parametrize("kind", ["date", "age", "relative"])
async def test_db_and_stateless_bounded_cash_flow(client, entity, same, kind):
    response = await client.post("/api/plans", json={"name": "Dates", "birth_year": 1990, "plan_type": "FIXED_DATE", "start_date": "2026-01-01"})
    assert response.status_code == 201
    pid = response.json()["id"]
    milestones = []
    base_id = None
    if kind == "relative":
        base = await client.post(f"/api/plans/{pid}/milestones", json={"name": "Base", "trigger_type": "date", "trigger_date": "2027-07-01"})
        assert base.status_code == 201
        base_id = base.json()["id"]
    for name in (["Window"] if same else ["Start", "End"]):
        r = await client.post(f"/api/plans/{pid}/milestones", json={"name": name, "trigger_type": kind, "trigger_date": "2027-07-01", "trigger_value": 37, "relative_to_id": base_id, "offset_years": 0})
        assert r.status_code == 201
        milestones.append(r.json())
    event = {"name": "Temporary", "annual_amount": 24000, "start_milestone_id": milestones[0]["id"], "end_milestone_id": milestones[-1]["id"], "start_month": 7, "end_month": 12}
    event.update({"growth_rate": 0} if entity == "incomes" else {"inflation_linked": False})
    bad = await client.post(f"/api/plans/{pid}/{entity}", json=event | {"start_month": 12, "end_month": 1})
    assert bad.status_code == 422
    saved = await client.post(f"/api/plans/{pid}/{entity}", json=event)
    assert saved.status_code == 201
    eid = saved.json()["id"]
    bad_update = await client.put(f"/api/plans/{pid}/{entity}/{eid}", json={"end_month": 1})
    assert bad_update.status_code == 422
    persisted = (await client.get(f"/api/plans/{pid}/{entity}")).json()
    assert persisted[0]["end_month"] == 12
    db_result = await client.post(f"/api/plans/{pid}/simulate")
    assert db_result.status_code == 200
    stateless = {"plan_id": pid, "birth_year": 1990, "start_year": 2026, "milestones": milestones,
                 "income_streams" if entity == "incomes" else "expenses": [event | {"id": eid}]}
    if base_id:
        stateless["milestones"] = [base.json(), *milestones]
    result = await client.post("/api/simulate/stateless", json=stateless)
    assert result.status_code == 200
    field = "gross_income" if entity == "incomes" else "expenses"
    for data in [db_result.json(), result.json()]:
        rows = data["yearly_snapshots"]
        assert [r[field] for r in rows[:3]] == pytest.approx([0, 12000, 0])
    stateless["income_streams" if entity == "incomes" else "expenses"][0]["end_month"] = 1
    assert (await client.post("/api/simulate/stateless", json=stateless)).status_code == 422


@pytest.mark.anyio
async def test_before_birth_create_update_and_legacy_simulation(client, db_session):
    body = {"name": "Dates", "birth_year": 1990, "plan_type": "FIXED_DATE", "start_date": "1980-01-01"}
    assert (await client.post("/api/plans", json=body)).status_code == 422
    body["start_date"] = "2000-01-01"
    saved = await client.post("/api/plans", json=body)
    assert saved.status_code == 201
    pid = saved.json()["id"]
    for edit in [{"start_date": "1980-01-01"}, {"birth_year": 2001}]:
        assert (await client.put(f"/api/plans/{pid}", json=edit)).status_code == 422
    assert (await client.get(f"/api/plans/{pid}")).json()["start_date"] == "2000-01-01"
    legacy = db_session.get(Plan, uuid.UUID(pid))
    legacy.start_date = date(1980, 1, 1)
    db_session.commit()
    assert (await client.post(f"/api/plans/{pid}/simulate")).status_code == 422
    assert (await client.post("/api/simulate/stateless", json={"plan_id": pid, "birth_year": 1990, "start_year": 1980})).status_code == 422
    assert (await client.put(f"/api/plans/{pid}", json={"plan_type": "NOW", "start_date": None})).status_code == 200

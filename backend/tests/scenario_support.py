"""Shared builders for plan scenario tests (SQLite API fixtures)."""
from sqlalchemy import text

from app.models.planning_client import PlanningClient


async def post(client, path, payload=None, status=201):
    response = await client.post("/api" + path, json=payload if payload is not None else {})
    assert response.status_code == status, response.text
    return response.json()


async def put(client, path, payload, status=200):
    response = await client.put("/api" + path, json=payload)
    assert response.status_code == status, response.text
    return response.json()


async def get(client, path):
    response = await client.get("/api" + path)
    assert response.status_code == 200, response.text
    return response.json()


def extra_workspace(db_session, user_id, name: str) -> dict:
    """A workspace besides the personal one. Without a hosting plug-in the API
    creates only the personal workspace, so this one is made directly."""
    row = PlanningClient(user_id=user_id, name=name)
    db_session.add(row)
    db_session.commit()
    return {"id": str(row.id), "name": name}


async def build_main(client, db_session) -> dict:
    """A client-workspace plan with every inherited kind, cross-referenced."""
    # Production enforces foreign keys; the default SQLite fixture does not.
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    household = await post(client, "/clients/personal", status=200)
    plan = await post(client, "/plans", {"name": "Main", "birth_year": 1985, "client_id": household["id"]})
    pid = plan["id"]
    retire = await post(client, f"/plans/{pid}/milestones", {"name": "Retire", "trigger_type": "age", "trigger_value": 60})
    before = await post(client, f"/plans/{pid}/milestones", {
        "name": "Before retiring", "trigger_type": "relative", "relative_to_id": retire["id"], "offset_years": -2})
    cash = await post(client, f"/plans/{pid}/accounts", {"name": "Cash", "account_type": "savings", "balance": 20000})
    brokerage = await post(client, f"/plans/{pid}/accounts", {
        "name": "Brokerage", "account_type": "taxable_brokerage", "balance": 150000.10, "cost_basis": 90000})
    salary = await post(client, f"/plans/{pid}/incomes", {
        "name": "Salary", "annual_amount": 120000, "end_milestone_id": retire["id"]})
    spending = await post(client, f"/plans/{pid}/expenses", {
        "name": "Spending", "annual_amount": 48000.50, "end_milestone_id": before["id"],
        "specific_funding_source_id": cash["id"]})
    home = await post(client, f"/plans/{pid}/real-assets", {"name": "Home", "current_value": 400000})
    mortgage = await post(client, f"/plans/{pid}/liabilities", {
        "name": "Mortgage", "principal_balance": 200000, "interest_rate": 5, "term_months": 300,
        "linked_asset_id": home["id"], "payoff_milestone_id": retire["id"]})
    curve = await post(client, f"/plans/{pid}/assumptions", {"curve_type": "inflation", "fixed_rate": 0.025})
    gift = await post(client, f"/plans/{pid}/charities", {
        "name": "Food bank", "entity_type": "direct", "annual_amount": 1000, "start_milestone_id": retire["id"]})
    await put(client, f"/plans/{pid}/priorities", {"expected_revision": 0, "items": [
        {"priority_rank": 1, "priority_type": "contribution", "target_account_id": brokerage["id"],
         "allocation_mode": "amount", "allocation_value": 5000}]})
    await put(client, f"/plans/{pid}/drawdown-order", {"items": [
        {"rank": 1, "source_account_id": cash["id"]}, {"rank": 2, "source_account_id": brokerage["id"]}]})
    await put(client, f"/plans/{pid}", {
        "life_expectancy": 92, "spouse": {"name": "Sam", "birth_year": 1987},
        "residency_periods": [{"state_code": "CA", "rank": 0, "end_milestone_id": retire["id"]},
                              {"state_code": "TX", "rank": 1, "start_milestone_id": retire["id"]}]})
    return {"plan": pid, "client": household["id"], "retire": retire["id"], "before": before["id"],
            "cash": cash["id"], "brokerage": brokerage["id"], "salary": salary["id"],
            "spending": spending["id"], "home": home["id"], "mortgage": mortgage["id"],
            "curve": curve["id"], "gift": gift["id"]}


async def create_scenario(client, main_id, name=None) -> dict:
    payload = {"as_scenario": True}
    if name:
        payload["name"] = name
    return await post(client, f"/plans/{main_id}/duplicate", payload)


def by_name(rows, name):
    return next(row for row in rows if row.get("name") == name)


def item(inheritance, kind, name=None):
    return next(row for row in inheritance["items"] if row["kind"] == kind and (name is None or row["name"] == name))

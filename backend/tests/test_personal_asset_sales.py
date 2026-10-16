"""IRS Pub 550 personal-use loss exclusion, not a gain exclusion."""
import uuid
from dataclasses import asdict, replace

import pytest

from app.engine.plan_converter import plan_to_engine_data
from app.models.plan import Plan
from coastmath.engine.simulator import (
    inherited_history_note,
    property_sale_note,
    run_simulation,
)
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    LiabilityData,
    PlanData,
    RealAssetData,
)


def sale_plan(treatment="personal_use", basis=24000, auto=False):
    return PlanData(
        plan_id=str(uuid.uuid4()), birth_year=1970, start_year=2026,
        life_expectancy=60, filing_status="married_filing_jointly", spouse_birth_year=1972,
        assumptions=AssumptionData(0, 0, 0),
        accounts={"cash": AccountInfo(100000, "checking")},
        income_streams=[IncomeData("w", "Wages", 160000)],
        drawdown_order=[DrawdownEntryData(1, "cash")],
        real_assets=[RealAssetData(
            "car", "Personal car", 24000, annual_appreciation_rate=-.1,
            adjusted_basis=basis, tax_treatment=treatment,
            sale_year=None if auto else 2028,
            auto_liquidate_on_depletion=auto, liquidation_target_account_id="cash",
        )],
        liabilities=[LiabilityData(
            "loan", "Car loan", 12000, interest_rate=0, term_months=48,
            monthly_payment=250, extra_payment=1200, linked_asset_id="car",
        )],
    )


@pytest.mark.parametrize("basis", [None, 24000])
@pytest.mark.parametrize("treatment", ["personal_use", "unspecified", "investment"])
def test_scheduled_sale_loss_tax_and_carryforward(treatment, basis):
    p = sale_plan(treatment, basis)
    actual = run_simulation(p)
    control = run_simulation(sale_plan(treatment, 19440))
    a, b = actual.yearly_snapshots, control.yearly_snapshots
    assert a[:2] == b[:2]
    for i, benefit in ((2, 660), (3, 343.2)):
        expected = benefit if treatment == "investment" else 0
        assert b[i].federal_tax - a[i].federal_tax == pytest.approx(expected)
    assert a[2].real_assets_value == a[2].liabilities_balance == 0
    assert a[0].liabilities_balance == 7800 and a[1].liabilities_balance == 3600
    if treatment != "investment":
        assert a == b  # income denominator, cash proceeds, balances, later taxes
    review = [w for w in actual.metadata.warnings if "isn't deducted without investment treatment" in w]
    assert bool(review) == (treatment == "unspecified")


def test_personal_gain_is_taxable_and_primary_residence_still_has_exclusion():
    personal = sale_plan(basis=10000)
    investment = sale_plan("investment", 10000)
    a = run_simulation(personal).yearly_snapshots
    assert a == run_simulation(investment).yearly_snapshots
    assert a[2].capital_gains_tax == pytest.approx(9440 * .15)
    personal.real_assets[0].is_primary_residence = True
    assert run_simulation(personal).yearly_snapshots[2].capital_gains_tax == 0


@pytest.mark.parametrize("treatment", ["personal_use", "investment"])
def test_auto_liquidation_uses_same_loss_treatment_and_preserves_cash(treatment):
    p = sale_plan(treatment, auto=True)
    p.accounts["cash"].balance = 0
    p.expenses = [ExpenseData("e", "Expenses", 160000)]
    control = replace(p, real_assets=[replace(p.real_assets[0], adjusted_basis=21600)])
    a = run_simulation(p).yearly_snapshots[0]
    b = run_simulation(control).yearly_snapshots[0]
    assert a.real_assets_value == a.liabilities_balance == 0
    benefit = 2400 * .22 if treatment == "investment" else 0
    assert b.federal_tax - a.federal_tax == pytest.approx(benefit)
    assert a.net_worth - b.net_worth == pytest.approx(benefit)


@pytest.mark.anyio
@pytest.mark.parametrize("treatment", ["personal_use", "investment", "unspecified"])
async def test_db_and_stateless_sale_tax_contract(client, db_session, treatment):
    p = (await client.post("/api/plans", json={
        "name": "Synthetic sale", "birth_year": 1970, "plan_type": "FIXED_DATE",
        "start_date": "2026-01-01", "filing_status": "single", "life_expectancy": 60,
    })).json()
    url = f"/api/plans/{p['id']}"
    await client.post(f"{url}/incomes", json={"name": "Wages", "annual_amount": 100000})
    response = await client.post(f"{url}/real-assets", json={
        "name": "Car", "current_value": 24000, "annual_appreciation_rate": -.1,
        "adjusted_basis": 24000, "sale_year": 2028, "tax_treatment": treatment,
    })
    assert response.status_code == 201, response.text
    asset_url = f"{url}/real-assets/{response.json()['id']}"
    # Unrelated edits must not reset the classification; reload proves persistence.
    assert (await client.put(asset_url, json={"name": "Renamed car"})).json()["tax_treatment"] == treatment
    assert (await client.get(url)).json()["real_assets"][0]["tax_treatment"] == treatment
    db_session.expire_all()
    saved = db_session.get(Plan, uuid.UUID(p["id"]))
    engine = plan_to_engine_data(saved, [])
    assert engine.real_assets[0].tax_treatment == treatment
    db_result = await client.post(f"{url}/simulate")
    assert db_result.status_code == 200, db_result.text
    stateless = await client.post("/api/simulate/stateless", json=asdict(engine))
    assert stateless.status_code == 200, stateless.text
    assert db_result.json()["yearly_snapshots"] == stateless.json()["yearly_snapshots"]
    await client.put(asset_url, json={"adjusted_basis": 19440})
    control = (await client.post(f"{url}/simulate")).json()["yearly_snapshots"]
    loss = db_result.json()["yearly_snapshots"]
    for i, benefit in ((2, 660), (3, 343.2)):
        assert control[i]["federal_tax"] - loss[i]["federal_tax"] == pytest.approx(
            benefit if treatment == "investment" else 0)
    for bad in (None, "business", "bogus"):
        assert (await client.put(asset_url, json={"tax_treatment": bad})).status_code == 422


def test_property_and_inherited_notes_are_one_sentence_each():
    """One short note per sold property and per inherited account."""
    plan = sale_plan()
    asset = plan.real_assets[0]
    asset.adjusted_basis = None
    note = property_sale_note(asset, purchased=False)
    assert note.count(".") == 1 and note.startswith(f"{asset.name} sale:") and "basis" in note
    warnings = run_simulation(plan).metadata.warnings
    assert sum(asset.name in w for w in warnings) == 1
    assert inherited_history_note("Inh IRA", {}) == (
        "Inh IRA: inherited RMDs assume death before the required beginning date and no original-owner birth year.")
    assert inherited_history_note("Inh IRA", {"decedent_died_after_rbd": True}).endswith("no original-owner birth year.")

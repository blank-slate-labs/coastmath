"""Independent applicable-law tests for married-household federal tax cases.

Expected amounts come from IRS rules, never from another planner's output or
regenerated persona baselines. See `_sources` in `tax_brackets_2025.json` for sources.
"""
from dataclasses import asdict
from uuid import UUID, uuid4

import pytest

from app.engine.plan_converter import plan_to_engine_data
from app.models.plan import Plan
from coastmath.engine.simulator import _handle_partner_death, run_simulation
from coastmath.engine.tax_engine import calculate, calculate_amt, get_federal_brackets
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    EstateSettingsData,
    IncomeData,
    PlanData,
    SimState,
)


def minimal(year=2025, **overrides):
    values = dict(
        plan_id=str(uuid4()), birth_year=year - 50, start_year=year,
        life_expectancy=54, filing_status="married_filing_jointly",
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0),
        accounts={"cash": AccountInfo(balance=100_000, account_type="checking")},
        income_streams=[IncomeData(id="salary", name="Salary", annual_amount=100_000, growth_rate=0)],
    )
    return PlanData(**(values | overrides))


@pytest.mark.parametrize("year,expected", [(2025, 7743), (2026, 7640)])
def test_applicable_year_mfj_tax(year, expected):
    snapshot = run_simulation(minimal(year)).yearly_snapshots[0]
    assert snapshot.federal_tax == pytest.approx(expected, abs=.01)


@pytest.mark.parametrize("status,deduction,first_bound", [
    ("single", 15_750, 11_925),
    ("married_filing_jointly", 31_500, 23_850),
    ("married_filing_separately", 15_750, 11_925),
    ("head_of_household", 23_625, 17_000),
])
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_2025_federal_first_bracket_boundary(status, deduction, first_bound, offset):
    result = calculate(deduction + first_bound + offset, 0, status, tax_year=2025)
    expected = (first_bound + min(offset, 0)) * .10 + max(offset, 0) * .12
    assert result.standard_deduction == deduction
    assert result.federal == pytest.approx(expected)


def test_published_2026_table_replaces_2025_before_future_indexing():
    plan = minimal(2025, assumptions=AssumptionData(inflation_rate=.1, stock_growth_rate=0, bond_return_rate=0))
    rows = run_simulation(plan).yearly_snapshots
    assert [r.standard_deduction for r in rows] == pytest.approx([31_500, 32_200, 35_420, 38_962])
    assert rows[1].federal_tax == pytest.approx(7_640)
    # Known federal indexing does not reset the independent expense/income
    # inflation trajectory or change the 2026 helper's backward default.
    assert get_federal_brackets("single")[0] == (12_400, .1)


def test_2025_ltcg_zero_rate_boundary_uses_historical_threshold():
    a = calculate(31_500, 0, "married_filing_jointly", tax_year=2025, capital_gains=96_700)
    b = calculate(31_500, 0, "married_filing_jointly", tax_year=2025, capital_gains=96_701)
    assert a.capital_gains_tax == 0
    assert b.capital_gains_tax == pytest.approx(.15)


@pytest.mark.parametrize("start,fraction", [(2025, 1), (2026, 1), (2026, .5), (2027, 1), (2030, 1)])
def test_projected_federal_tables_are_calendar_anchored(start, fraction):
    plan = minimal(start, first_year_fraction=fraction,
                   assumptions=AssumptionData(inflation_rate=.03, stock_growth_rate=0, bond_return_rate=0))
    rows = run_simulation(plan).yearly_snapshots
    for row in rows:
        expected = 31_500 if row.year == 2025 else 32_200 * 1.03 ** (row.year - 2026)
        assert row.standard_deduction == pytest.approx(expected)


def test_future_start_indexing_resolves_prior_calendar_year_assumption_curve():
    plan = minimal(2030, assumption_curves=[AssumptionCurveData(
        curve_type="inflation", mode="fixed", fixed_rate=.05)])
    assert run_simulation(plan).yearly_snapshots[0].standard_deduction == pytest.approx(32_200 * 1.05 ** 4)


@pytest.mark.parametrize("start,fraction", [(2025, 1), (2026, 1), (2026, .5), (2027, 1), (2030, 1)])
def test_ca_estimate_tables_and_credits_are_calendar_anchored(start, fraction):
    plan = minimal(start, first_year_fraction=fraction, filing_status="single", state_code="CA",
                   tax_settings={"ca_exemption_eligible_owners": ["self"]},
                   assumptions=AssumptionData(inflation_rate=.03, stock_growth_rate=0, bond_return_rate=0))
    for row in run_simulation(plan).yearly_snapshots:
        if row.year == start and fraction < 1:
            continue  # Opening partial wages intentionally differ.
        factor = 1.03 ** max(0, row.year - 2026)
        # FTB2025 schedule: tax through $72,724 is $3,201.97, then9.3%.
        # Standard deduction$5,706; eligible personal exemption credit$153.
        credit = int(153 * factor + .5)
        expected = 3_201.97 * factor + .093 * (100_000 - (5_706 + 72_724) * factor) - credit
        assert row.state_tax == pytest.approx(expected)


def test_ca_calendar_anchor_preserves_custom_table_multiplier():
    result = calculate(100_000, 0, "single", state_code="CA", tax_year=2026,
                       inflation_factor=2, federal_inflation_factor=1,
                       settings={"state_brackets": [{"min": 0, "max": 999999999, "rate": .10}],
                                 "ca_exemption_eligible_owners": ["self"]})
    assert result.state == pytest.approx((100_000 - 5_706 * 2) * .10)


@pytest.mark.parametrize("year,exemption,phaseout,rate,threshold", [
    (2025, 137_000, 1_252_700, .25, 239_100),
    (2026, 140_200, 1_000_000, .50, 244_500),
])
def test_amt_uses_year_specific_exemption_and_phaseout(year, exemption, phaseout, rate, threshold):
    amti = phaseout + 10_000
    base = amti - (exemption - 10_000 * rate)
    expected = threshold * .26 + (base - threshold) * .28
    assert calculate_amt(amti, filing_status="married_filing_jointly", tax_year=year) == pytest.approx(expected)
    assert calculate_amt(exemption, filing_status="married_filing_jointly", tax_year=year) == 0


def test_death_year_joint_then_single_not_indefinite_joint():
    plan = minimal(2026, spouse_birth_year=1976, spouse_life_expectancy=51)
    rows = run_simulation(plan).yearly_snapshots
    assert [r.federal_tax for r in rows] == pytest.approx([7640, 7640, 13170, 13170])
    assert [r.standard_deduction for r in rows] == [32200, 32200, 16100, 16100]


def test_spouse_aged_deduction_remains_on_final_joint_return_only():
    plan = minimal(2026, spouse_birth_year=1961, spouse_life_expectancy=65)
    rows = run_simulation(plan).yearly_snapshots
    assert rows[0].standard_deduction == 32_200 + 1_650
    assert rows[0].deduction_amount == 32_200 + 1_650 + 6_000
    assert rows[1].standard_deduction == 16_100
    assert rows[1].deduction_amount == 16_100
    historical = calculate(100_000, 0, "married_filing_jointly", tax_year=2025, holder_age=65, spouse_age=65)
    assert historical.standard_deduction == 31_500 + 3_200


def test_death_before_projection_does_not_create_another_joint_year():
    plan = minimal(2026, spouse_birth_year=1975, spouse_life_expectancy=50)
    rows = run_simulation(plan).yearly_snapshots
    assert rows[0].federal_tax == 13_170
    assert rows[1].federal_tax == 13_170


def test_single_and_separate_filers_do_not_gain_joint_death_year():
    for status in ["single", "married_filing_separately"]:
        plan = minimal(2026, filing_status=status, spouse_birth_year=1976, spouse_life_expectancy=50)
        assert run_simulation(plan).yearly_snapshots[0].federal_tax == 13_170


@pytest.mark.parametrize("step_up", [True, False])
def test_filing_delay_preserves_immediate_inheritance_and_optional_step_up(step_up):
    plan = minimal(2026, estate_settings=EstateSettingsData(step_up_basis_on_death=step_up))
    state = SimState(year=2026, accounts={
        "spouse": AccountInfo(balance=100_000, cost_basis=30_000, account_type="taxable_brokerage", owner="spouse"),
        "self": AccountInfo(balance=90_000, cost_basis=20_000, account_type="taxable_brokerage", owner="self"),
    })
    _handle_partner_death(state, plan, 2026)
    assert state.partner_deceased and state.partner_death_year == 2026
    assert state.current_filing_status is None
    assert state.accounts["spouse"].owner == "self"
    assert state.accounts["spouse"].cost_basis == (100_000 if step_up else 30_000)
    assert state.accounts["self"].cost_basis == 20_000
    assert sum(a.balance for a in state.accounts.values()) == 190_000


def test_minimal_years_independently_reconcile_cash_taxes_and_balances():
    rows = run_simulation(minimal()).yearly_snapshots
    opening = 100_000
    for row in rows:
        assert row.taxes == pytest.approx(row.federal_tax + 100_000 * .0765)
        assert row.net_worth == pytest.approx(opening + 100_000 - row.taxes)
        assert sum(row.accounts.values()) == pytest.approx(row.net_worth)
        opening = row.net_worth


@pytest.mark.anyio
@pytest.mark.parametrize("year,death,expected", [(2025, False, 7743), (2026, True, 7640)])
async def test_persisted_and_stateless_routes_use_correct_tax_rules(client, db_session, year, death, expected):
    response = await client.post("/api/plans", json={
        "name": "Independent tax regression", "birth_year": year - 50,
        "plan_type": "FIXED_DATE", "start_date": f"{year}-01-01",
        "filing_status": "married_filing_jointly", "life_expectancy": 52,
    })
    assert response.status_code == 201, response.text
    pid = response.json()["id"]
    if death:
        spouse = await client.put(f"/api/plans/{pid}", json={"spouse": {"name": "Partner", "birth_year": year - 50, "life_expectancy": 50}})
        assert spouse.status_code == 200, spouse.text
    income = await client.post(f"/api/plans/{pid}/incomes", json={"name": "Salary", "annual_amount": 100_000, "growth_rate": 0})
    assert income.status_code == 201, income.text
    db_session.expire_all()
    engine = plan_to_engine_data(db_session.get(Plan, UUID(pid)), [])
    persisted = await client.post(f"/api/plans/{pid}/simulate")
    stateless = await client.post("/api/simulate/stateless", json=asdict(engine))
    for response in [persisted, stateless]:
        assert response.status_code == 200, response.text
        rows = response.json()["yearly_snapshots"]
        assert rows[0]["federal_tax"] == pytest.approx(expected)
        if death:
            assert rows[1]["standard_deduction"] < rows[0]["standard_deduction"]
    assert persisted.json() == stateless.json()

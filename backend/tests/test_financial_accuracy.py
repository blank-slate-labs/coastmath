"""Independent ledger, tax-year, ownership and funding regression cases."""
import pytest
from pydantic import ValidationError

from app.engine.plan_converter import plan_to_engine_data
from app.models.income import IncomeStream
from app.models.plan import Plan
from app.models.real_asset import RealAsset
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import calculate, calculate_household_fica_tax
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    LiabilityData,
    MilestoneData,
    PriorityData,
    RealAssetData,
    SimState,
)
from coastmath.engine.waterfall import (
    allocate_surplus,
    contribution_room,
    execute_drawdown,
)
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data
from coastmath.schemas.year_to_date import YearToDateTax
from tests import financial_probes as _probes
from tests.financial_probes import plan


@pytest.mark.parametrize("row", _probes.run_probes(), ids=lambda row: row["name"])
def test_independent_audit_oracles(row):
    assert row["status"] == "MATCH", row


@pytest.mark.parametrize("rate", [0, .05, .2, .35])
@pytest.mark.parametrize("withholding", [0, .1, .2, .4])
def test_withholding_credit_and_tax_on_tax_conserve_dollars(rate, withholding):
    p = plan(accounts={"ira": AccountInfo(100000, "traditional_ira"),
                       "cash": AccountInfo(0, "checking")},
             drawdown_order=[DrawdownEntryData(1, "ira")],
             expenses=[ExpenseData("e", "Spending", 8000)],
             tax_settings={"mode": "flat", "ordinary_income_tax_rate": rate,
                           "tax_deferred_withholding_rate": withholding})
    r = run_simulation(p)
    s = r.yearly_snapshots[0]
    # Overwithholding may require an unnecessarily large distribution and
    # a refund into cash; every dollar must still have a destination.
    gross = sum(x.amount for x in s.cash_flow.drawdowns)
    assert s.taxes == pytest.approx(gross * rate, abs=.02)
    assert s.net_worth == pytest.approx(100000 - 8000 - s.taxes, abs=.02)
    assert r.metadata.success
    assert s.unfunded_expenses == 0


def test_multiple_liquidations_and_failure_preserve_remaining_debt():
    p = plan(accounts={"cash": AccountInfo(0, "checking")},
             expenses=[ExpenseData("e", "Spending", 25000)],
             real_assets=[RealAssetData(str(i), "Asset", 10000, 0,
                 auto_liquidate_on_depletion=True, liquidation_target_account_id="cash") for i in range(2)])
    r = run_simulation(p)
    s = r.yearly_snapshots[0]
    assert s.accounts["cash"] == 0
    assert s.unfunded_expenses == pytest.approx(5000)
    assert s.net_worth == pytest.approx(-5000)
    assert not r.metadata.success


def test_tax_bill_without_drawdown_order_is_not_forgiven():
    p = plan(accounts={"t": AccountInfo(100000, "traditional_ira"),
                       "r": AccountInfo(0, "roth_ira")}, drawdown_order=[],
             priorities=[PriorityData(1, "r", 10000, "roth_conversion", "t")])
    r = run_simulation(p)
    assert not r.metadata.success
    assert r.yearly_snapshots[0].unfunded_expenses == pytest.approx(2000)


def test_separate_spouses_keep_separate_ira_limits_and_ages():
    state = SimState(2026, accounts={"a": AccountInfo(0, "roth_ira", owner="self"),
                                    "b": AccountInfo(0, "roth_ira", owner="spouse")},
                     owner_ages={"self": 35, "spouse": 52},
                     compensation_by_owner={"self": 100000, "spouse": 0})
    result = allocate_surplus(30000, [PriorityData(1, "a"), PriorityData(2, "b")],
                              state, age=35, filing_status="married_filing_jointly", modified_agi=100000)
    assert result == {"a": 7500, "b": 8600}


def test_no_compensation_prevents_ira_contributions():
    p = plan(accounts={"cash": AccountInfo(0, "checking"), "r": AccountInfo(0, "roth_ira")},
             income_streams=[IncomeData("i", "Investment income", 10000, is_earned_income=False)],
             priorities=[PriorityData(1, "r")])
    assert run_simulation(p).yearly_snapshots[0].accounts["r"] == 0


def test_existing_ytd_deferrals_share_limit_with_roth_payroll():
    p = plan(accounts={"cash": AccountInfo(0, "checking"),
                       "t": AccountInfo(0, "traditional_401k"), "r": AccountInfo(0, "roth_401k")},
             birth_year=1990, life_expectancy=37, first_year_fraction=.5,
             income_streams=[IncomeData("pay", "Pay", 100000)],
             priorities=[PriorityData(1, "r", priority_type="income_percent", source_income_id="pay", employee_rate=.5)],
             tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0,
                           "year_to_date": {"tax_year": 2026, "contributions_by_account": {"t": 24000}}})
    assert run_simulation(p).yearly_snapshots[0].accounts["r"] == pytest.approx(500)


def test_household_additional_medicare_is_not_per_worker():
    fica = calculate_household_fica_tax({"self": 150000, "spouse": 150000}, {}, "married_filing_jointly")
    assert fica["social_security_tax"] == 300000 * .062
    assert fica["additional_medicare_tax"] == 50000 * .009


def test_ytd_cash_and_tax_are_separate_and_history_used_once():
    p = plan(first_year_fraction=.5, life_expectancy=62, income_streams=[IncomeData("pay", "Pay", 120000)],
             tax_settings={"year_to_date": {"tax_year": 2026, "gross_income": 60000,
                "w2_income_by_owner": {"self": 60000}, "tax_paid": 9610}})
    a, b = run_simulation(p).yearly_snapshots
    assert a.taxes == pytest.approx(26750)
    assert a.net_worth == pytest.approx(100000 + 60000 - (26750 - 9610))
    assert b.taxes == pytest.approx(26750)
    assert b.net_worth - a.net_worth == pytest.approx(120000 - 26750)


def test_ytd_wrong_tax_year_is_rejected():
    with pytest.raises(ValueError, match="tax_year"):
        run_simulation(plan(tax_settings={"year_to_date": {"tax_year": 2025}}))


def test_sale_date_controls_growth_costs_and_adjusted_basis():
    p = plan(real_assets=[RealAssetData("a", "Asset", 100000, .21,
        annual_property_tax=12000, sale_year=2026, sale_month=7,
        adjusted_basis=80000, liquidation_target_account_id="cash")])
    s = run_simulation(p).yearly_snapshots[0]
    assert s.expenses == pytest.approx(6000)
    assert s.taxes == pytest.approx((110000 - 80000) * .2)
    assert s.net_worth == pytest.approx(100000 + 110000 - 6000 - 6000)


def test_deferred_tax_debt_is_settled_once_and_in_legacy():
    p = plan(life_expectancy=62, income_streams=[IncomeData("pay", "Pay", 100000)],
             tax_settings={"mode": "flat", "ordinary_income_tax_rate": .2, "settlement_lag_years": 1})
    r = run_simulation(p)
    a, b = r.yearly_snapshots
    assert a.tax_balance == b.tax_balance == 20000
    assert a.net_worth == 180000
    assert b.net_worth == 260000
    assert r.metadata.net_legacy.net_legacy == pytest.approx(260000)


def test_losses_carry_and_do_not_offset_qualified_dividends_without_limit():
    tax = calculate(50000, 0, "single", capital_gains=-10000, qualified_dividends=2000)
    assert tax.capital_loss_carryforward == 7000
    later = calculate(50000, 0, "single", capital_gains=6000, capital_loss_carryforward=7000)
    assert later.capital_loss_carryforward == 0
    assert later.agi == 49000
    no_income = calculate(0, 0, "single", capital_gains=-10000)
    assert no_income.capital_loss_carryforward == 10000


def test_mortgage_and_property_tax_reach_itemized_calculation():
    p = plan(tax_settings=None, income_streams=[IncomeData("p", "Pay", 200000)],
        real_assets=[RealAssetData("home", "Home", 500000, 0, annual_property_tax=10000, is_primary_residence=True)],
        liabilities=[LiabilityData("loan", "Mortgage", 500000, .06, monthly_payment=2500, linked_asset_id="home")])
    s = run_simulation(p).yearly_snapshots[0]
    assert s.deduction_used == "itemized"
    assert s.deduction_amount == pytest.approx(40000)


def test_surplus_without_user_cash_account_is_retained_next_year():
    p = plan(life_expectancy=62, accounts={"r": AccountInfo(0, "roth_ira")},
             income_streams=[IncomeData("i", "Pay", 10000)])
    a, b = run_simulation(p).yearly_snapshots
    assert a.accounts["unallocated_cash"] == 8000
    assert b.accounts["unallocated_cash"] == 16000


def test_stateless_request_preserves_new_inputs():
    req = PlanDataRequest(plan_id="00000000-0000-0000-0000-000000000001", birth_year=1966,
        filing_status="single", life_expectancy=61, start_year=2026,
        income_streams=[{"id": "i", "name": "Pay", "annual_amount": 100000, "owner": "spouse"}],
        real_assets=[{"id": "a", "name": "Asset", "current_value": 100000, "adjusted_basis": 50000}],
        tax_settings={"year_to_date": {"tax_year": 2026, "gross_income": 50000,
                                     "w2_income_by_owner": {"spouse": 50000}, "tax_paid": 10000}})
    converted = request_to_engine_data(req)
    assert converted.income_streams[0].owner == "spouse"
    assert converted.real_assets[0].adjusted_basis == 50000
    assert converted.tax_settings["year_to_date"]["tax_paid"] == 10000


def test_roth_phaseout_and_shared_ira_room_are_separate_limits():
    state = SimState(2026, accounts={"t": AccountInfo(5000, "traditional_ira"),
                                    "r": AccountInfo(0, "roth_ira")},
                     ytd_contributions={"t": 5000}, compensation_by_owner={"self": 160000})
    # 2026 single MAGI halfway through phaseout: $3,750 Roth limit,
    # $2,500 combined IRA room after $5,000 traditional contributions.
    assert contribution_room("r", state, 35, "single", 160500) == 2500


@pytest.mark.parametrize("start,end", [(1, 1), (7, 12), (12, 12)])
def test_payroll_growth_uses_actual_active_months(start, end):
    p = plan(accounts={"r": AccountInfo(0, "roth_401k"), "cash": AccountInfo(0, "checking")},
        milestones=[MilestoneData("s", "Start", "date", trigger_date=f"2026-{start:02}-01"),
                    MilestoneData("e", "End", "date", trigger_date=f"2026-{end:02}-01")],
        income_streams=[IncomeData("i", "Pay", 12000, start_milestone_id="s", end_milestone_id="e",
                                   start_month=start, end_month=end)],
        priorities=[PriorityData(1, "r", priority_type="income_percent", source_income_id="i", employee_rate=.5)],
        assumptions=AssumptionData(stock_growth_rate=.12, inflation_rate=0),
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0, "cash_flow_frequency": "monthly"})
    snapshot = run_simulation(p).yearly_snapshots[0]
    expected = sum(500 * 1.12 ** ((12 - month) / 12) for month in range(start, end + 1))
    assert snapshot.accounts["r"] == pytest.approx(expected)


@pytest.mark.parametrize("rate", [-.4, 0, .12])
@pytest.mark.parametrize("fraction", [.5, 1])
def test_monthly_depletion_matches_independent_recurrence(rate, fraction):
    months = round(12 * fraction)
    q = (1 + rate) ** (1 / 12)
    affordable = 10000 * q ** months / sum(q ** m for m in range(months)) * months
    p = plan(first_year_fraction=fraction, accounts={"r": AccountInfo(10000, "roth_ira")},
        drawdown_order=[DrawdownEntryData(1, "r")],
        expenses=[ExpenseData("e", "Spending", (affordable + 100) / fraction)],
        assumptions=AssumptionData(stock_growth_rate=rate, inflation_rate=0),
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0, "cash_flow_frequency": "monthly"})
    result = run_simulation(p)
    assert not result.metadata.success
    assert result.yearly_snapshots[0].unfunded_expenses == pytest.approx(100)


@pytest.mark.parametrize("month", [1, 7, 12])
def test_specific_expense_growth_uses_its_scheduled_month(month):
    p = plan(accounts={"r": AccountInfo(10000, "roth_ira")},
        milestones=[MilestoneData("s", "Start", "date", trigger_date=f"2026-{month:02}-01"),
                    MilestoneData("e", "End", "date", trigger_date=f"2026-{month:02}-01")],
        expenses=[ExpenseData("e", "Bill", 12000, start_milestone_id="s", end_milestone_id="e",
                              start_month=month, end_month=month, specific_funding_source_id="r")],
        assumptions=AssumptionData(stock_growth_rate=.12, inflation_rate=0),
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0, "cash_flow_frequency": "monthly"})
    s = run_simulation(p).yearly_snapshots[0]
    assert s.accounts["r"] == pytest.approx(11200 - 1000 * 1.12 ** ((12 - month) / 12))


def test_saved_inputs_survive_database_and_converter(db_session, test_user):
    saved = Plan(user_id=test_user.id, name="Audit inputs", birth_year=1966,
                 filing_status="married_filing_jointly", plan_type="NOW",
                 tax_settings={"year_to_date": {"tax_year": 2026, "gross_income": 50000}})
    db_session.add(saved)
    db_session.flush()
    db_session.add_all([
        IncomeStream(plan_id=saved.id, name="Spouse wages", annual_amount=100000, owner="spouse"),
        RealAsset(plan_id=saved.id, name="Property", current_value=100000, adjusted_basis=40000),
    ])
    db_session.commit()
    db_session.expire_all()
    restored = plan_to_engine_data(saved, [])
    assert restored.income_streams[0].owner == "spouse"
    assert restored.real_assets[0].adjusted_basis == 40000
    assert restored.tax_settings["year_to_date"]["gross_income"] == 50000


@pytest.mark.parametrize("history", [
    {"gross_income": 0, "w2_income_by_owner": {"self": 50000}},
    {"tax_paid": 1000, "state_tax_paid": 2000},
    {"gross_income": float("inf")},
    {"contributions_by_account": {"r": -1}},
])
def test_inconsistent_tax_history_is_rejected(history):
    with pytest.raises(ValidationError):
        YearToDateTax(tax_year=2026, **history)


@pytest.mark.parametrize("growth_factor", [-.2, .25])
def test_timing_adjusted_full_taxable_sale_consumes_all_basis(growth_factor):
    state = SimState(2026, accounts={"b": AccountInfo(10000, "taxable_brokerage", cost_basis=9000)},
                     withdrawal_growth_factors={"b": growth_factor})
    proceeds = 10000 / (1 + growth_factor)
    execute_drawdown(proceeds, [DrawdownEntryData(1, "b")], state, age=60)
    assert state.accounts["b"].balance == pytest.approx(0)
    assert state.accounts["b"].cost_basis == pytest.approx(0)
    assert state.capital_gains_this_year == pytest.approx(proceeds - 9000)

"""Independent boundary cases for charitable gifts, QCDs and related tax rules.

Most cases pin charitable rules: QCD amounts above the RMD, carryover order and
expiry, the cash sources that fund gifts and the AGI limit base. The rest cover
neighbouring calculation rules: California's Social Security exclusion,
Medicare premium indexing for a future start, crypto price returns and
inherited basis, a refund-funded Roth contribution and model-gap warnings.
"""

import pytest

from coastmath.engine import household_lifecycle
from coastmath.engine.simulator import (
    _handle_partner_death,
    _process_charitable_contributions,
    _process_qcds,
    run_simulation,
)
from coastmath.engine.tax_engine import (
    _calculate_state_tax,
    ca_exemption_credit,
    calculate,
)
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    CharityData,
    DrawdownEntryData,
    EstateSettingsData,
    ExpenseData,
    IncomeData,
    LiabilityData,
    PlanData,
    PriorityData,
    RealAssetData,
    SimState,
    account_investment_rates,
)


def plan(**changes):
    values = dict(plan_id="00000000-0000-4000-8000-000000000001", birth_year=1986, birth_month=1,
        life_expectancy=41, start_year=2026, filing_status="single",
        accounts={"cash": AccountInfo(500_000, "checking")},
        drawdown_order=[DrawdownEntryData(1, "cash")],
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0,
            bond_return_rate=0, stock_dividend_yield=0, cash_yield_rate=0))
    values.update(changes)
    return PlanData(**values)


@pytest.mark.parametrize("rmd,available,requested,expected,ending", [
    (30_000, 100_000, 50_000, 50_000, 80_000),
    (30_000, 10_000, 50_000, 40_000, 0),
    (30_000, 0, 50_000, 30_000, 0),
    (0, 100_000, 50_000, 50_000, 50_000),
    (30_000, 200_000, 200_000, 111_000, 119_000),
])
def test_qcd_above_rmd_debits_only_additional_ira_funds(rmd, available, requested, expected, ending):
    state = SimState(2026, accounts={"ira": AccountInfo(available, "traditional_ira")})
    gift = CharityData("gift", "Gift", "qcd", requested)
    assert _process_qcds(state, [gift], rmd, set(), age=74) == expected
    assert state.accounts["ira"].balance == ending


@pytest.mark.parametrize("age", [71, 74])
def test_direct_qcd_does_not_exclude_inherited_401k_rmd(age):
    p = plan(birth_year=2026-age, life_expectancy=age+1,
        accounts={"cash": AccountInfo(500_000, "checking"),
            "ira": AccountInfo(255_000, "traditional_ira"),
            "401k": AccountInfo(100_000, "traditional_401k", inherited_year=2026,
                inheritance_settings={"year_of_death_rmd_remaining": 100_000})})
    before = run_simulation(p).yearly_snapshots[0]
    p.charity_entities = [CharityData("gift", "Gift", "qcd", 20_000)]
    after = run_simulation(p).yearly_snapshots[0]
    # At 74 the 255,000 IRA RMD is 10,000 (divisor 25.5); at 71 it is zero.
    ira_rmd = 10_000 if age == 74 else 0
    expected = calculate(0, 0, "single", rmd_income=100_000 + ira_rmd,
        qcd_offset=ira_rmd, holder_age=age, tax_year=2026)
    assert after.federal_tax == pytest.approx(expected.federal)
    assert after.expenses == 20_000
    assert after.accounts["ira"] == 235_000
    assert before.net_worth - after.net_worth == pytest.approx(
        20_000 - (before.taxes - after.taxes), abs=.01)
    assert sum(x.amount for x in after.cash_flow.expenses) == 20_000


def test_ca_full_year_excludes_social_security_from_tax_base():
    with_ss = calculate(50_000, 0, "single", state_code="CA", social_security_income=30_000)
    without_ss = calculate(50_000, 0, "single", state_code="CA")
    assert with_ss.state == pytest.approx(without_ss.state)
    assert with_ss.state == pytest.approx(1192.53)
    assert with_ss.federal > without_ss.federal


def test_ca_ss_still_counts_for_exemption_credit_phaseout():
    # Force the credit threshold boundary while holding the state base constant.
    base = 250_000
    agi = base + 25_500
    without = _calculate_state_tax(base, "CA", ca_exemption_eligible_owners=["self"])
    with_ss = _calculate_state_tax(agi, "CA", taxable_social_security=25_500, ca_exemption_eligible_owners=["self"])
    expected_credit_loss = ca_exemption_credit(base, "single", ["self"], None, None, 2026, 1) - ca_exemption_credit(agi, "single", ["self"], None, None, 2026, 1)
    assert expected_credit_loss > 0
    assert with_ss - without == pytest.approx(expected_credit_loss)


def test_current_gifts_do_not_renew_old_carryover():
    state = SimState(2026, accounts={"cash": AccountInfo(100_000, "checking")},
        daf_carryforward=[(2022, 30_000)])
    p = plan(charity_entities=[CharityData("gift", "Gift", "daf", 60_000)])
    result = _process_charitable_contributions(state, p, 100_000, set())
    assert result.allowable_deduction == 60_000
    assert result.committed_carryforward == [(2022, 30_000)]
    assert state.daf_carryforward == [(2022, 30_000)]  # provisional calculation is pure
    state.daf_carryforward = result.committed_carryforward
    state.year = 2028
    assert _process_charitable_contributions(state, plan(), 100_000, set()).allowable_deduction == 0


def test_carryover_consumes_oldest_after_current_even_if_input_unsorted():
    state = SimState(2026, accounts={"cash": AccountInfo(10_000, "checking")},
        daf_carryforward=[(2025, 15_000), (2022, 20_000)])
    result = _process_charitable_contributions(state,
        plan(charity_entities=[CharityData("gift", "Gift", "daf", 10_000)]), 50_000, set())
    assert result.allowable_deduction == 30_000
    assert result.committed_carryforward == [(2025, 15_000)]


def test_charity_uses_savings_before_realizing_brokerage_gains():
    state = SimState(2026, accounts={
        "broker": AccountInfo(100_000, "taxable_brokerage", cost_basis=0),
        "savings": AccountInfo(8_000, "savings"), "cash": AccountInfo(2_000, "checking")})
    result = _process_charitable_contributions(state,
        plan(charity_entities=[CharityData("gift", "Gift", "direct", 10_000)]), 50_000, set())
    assert result.account_withdrawals == {"cash": 2_000, "savings": 8_000}
    assert state.capital_gains_this_year == 0


def test_unfunded_charity_is_reported_with_actual_amount():
    p = plan(accounts={"cash": AccountInfo(3_000, "savings")},
        charity_entities=[CharityData("gift", "Food bank", "direct", 10_000)])
    result = run_simulation(p)
    assert result.yearly_snapshots[0].expenses == 3_000
    assert any("Food bank" in w and "$3,000.00 of $10,000.00" in w for w in result.metadata.warnings)


def test_charity_limit_includes_realized_gains_and_conversions():
    p = plan(accounts={"cash": AccountInfo(500_000, "checking"),
        "broker": AccountInfo(100_000, "taxable_brokerage", cost_basis=0),
        "ira": AccountInfo(100_000, "traditional_ira"), "roth": AccountInfo(0, "roth_ira")},
        charity_entities=[CharityData("gift", "Gift", "daf", 50_000)],
        expenses=[ExpenseData("expense", "Purchase", 40_000, specific_funding_source_id="broker")],
        priorities=[PriorityData(1, "roth", 60_000, "roth_conversion", "ira")])
    snap = run_simulation(p).yearly_snapshots[0]
    # Final AGI = 60k conversion + 40k realized gain. All 50k gift fits the
    # 60% limit; the 2026 itemized floor removes 500.
    assert snap.deduction_used == "itemized"
    assert snap.deduction_amount == pytest.approx(49_500)
    assert snap.expenses == 90_000


def test_charity_limit_excludes_nontaxable_ss_and_qcd():
    p = plan(birth_year=1952, life_expectancy=75,
        accounts={"cash": AccountInfo(500_000, "checking"), "ira": AccountInfo(255_000, "traditional_ira")},
        income_streams=[IncomeData("pension", "Pension", 50_000, tax_category="pension"),
            IncomeData("ss", "SS", 30_000, is_social_security=True)],
        charity_entities=[CharityData("qcd", "QCD", "qcd", 10_000),
            CharityData("daf", "DAF", "daf", 60_000)])
    snap = run_simulation(p).yearly_snapshots[0]
    # 50k pension + 25,500 taxable SS; IRA RMD is entirely QCD-excluded.
    assert snap.deduction_amount == pytest.approx(75_500 * (.6 - .005) + 5_970)


@pytest.mark.parametrize("persons,medical_rate", [(False, None), (False, .05), (True, None), (True, .05)])
def test_future_start_indexes_statutory_medicare_but_not_entered_premiums(persons, medical_rate):
    hc = {"enabled": True, "medicare_enabled": True, "medicare_apply_irmaa": False,
        "medical_inflation_rate": medical_rate, "medicare_part_d_plan_premium_monthly": 40,
        "medicare_supplement_premium_monthly": 150}
    if persons:
        hc["persons"] = [{"owner": "self", "mode": "coverage", "medical_inflation_rate": medical_rate,
            "medicare_apply_irmaa": False, "medicare_part_d_plan_premium_monthly": 40,
            "medicare_supplement_premium_monthly": 150, "out_of_pocket_annual": 1200}]
    p = plan(start_year=2028, birth_year=1958, life_expectancy=72, healthcare_settings=hc,
        assumptions=AssumptionData(inflation_rate=.03, stock_growth_rate=0, bond_return_rate=0))
    snapshots = run_simulation(p).yearly_snapshots
    rate = .03 if medical_rate is None else medical_rate
    assert snapshots[0].healthcare.medicare_part_b == pytest.approx(202.90 * 12 * (1+rate)**2)
    assert snapshots[0].healthcare.medicare_part_d_plan == 480
    assert snapshots[0].healthcare.medicare_supplement == 1800
    assert snapshots[1].healthcare.medicare_part_b == pytest.approx(202.90 * 12 * (1+rate)**3)
    if persons:
        assert snapshots[0].healthcare.out_of_pocket == 1200


def test_crypto_uses_price_return_even_with_bond_override():
    crypto = AccountInfo(100_000, "cryptocurrency", cost_basis=40_000,
        investment_settings={"bond_allocation": 1.0, "dividend_yield": .5})
    assert account_investment_rates(crypto, .1, -.2, .8, .03) == (.1, -.2, 0, 0)
    state = SimState(2026, accounts={"coin": crypto})
    assert state.apply_growth(.1, -.2, 1, .5) == (0, 0)
    assert crypto.balance == pytest.approx(110_000)
    assert crypto.cost_basis == 40_000


@pytest.mark.parametrize("lifecycle", [False, True])
def test_crypto_inheritance_steps_basis_up_or_down(lifecycle):
    p = plan(birth_year=1960, life_expectancy=90, spouse_birth_year=1950,
        spouse_life_expectancy=76, filing_status="married_filing_jointly",
        estate_settings=EstateSettingsData(step_up_basis_on_death=True,
            household_lifecycle="last_survivor_calendar_year_end" if lifecycle else "legacy_primary_endpoint"))
    state = SimState(2027, accounts={
        "gain": AccountInfo(100_000, "cryptocurrency", cost_basis=10_000, owner="spouse"),
        "loss": AccountInfo(10_000, "cryptocurrency", cost_basis=100_000, owner="spouse"),
        "own": AccountInfo(100_000, "cryptocurrency", cost_basis=10_000)})
    if lifecycle:
        household_lifecycle.apply_transitions(p, state, 2027)
    else:
        _handle_partner_death(state, p, 2026)
    assert state.accounts["gain"].cost_basis == 100_000
    assert state.accounts["loss"].cost_basis == 10_000
    assert state.accounts["own"].cost_basis == 10_000
    state.withdraw_from("gain", 50_000)
    assert state.capital_gains_this_year == 0


def test_refund_can_fund_roth_when_conversion_puts_total_agi_over_limit():
    salary = 173_000
    initial_tax = calculate(salary, 0, "single", earned_income=salary,
        w2_income_by_owner={"self": salary}, holder_age=40).total_tax
    p = plan(accounts={"cash": AccountInfo(500_000, "checking"),
        "401k": AccountInfo(0, "traditional_401k"), "ira": AccountInfo(100_000, "traditional_ira"),
        "roth": AccountInfo(0, "roth_ira")},
        income_streams=[IncomeData("salary", "Salary", salary)],
        expenses=[ExpenseData("living", "Living", salary - initial_tax - 24_000)],
        priorities=[PriorityData(1, "401k", 24_000), PriorityData(2, "roth", 7_500),
            PriorityData(3, "roth", 20_000, "roth_conversion", "ira")])
    snap = run_simulation(p).yearly_snapshots[0]
    # 173k -24k deductible contributions +20k conversion =169k total AGI,
    # but Roth MAGI is149k. The net4k deduction refunds960 at24%.
    assert snap.accounts["401k"] == pytest.approx(24_000)
    assert snap.accounts["roth"] == pytest.approx(20_960, abs=.01)


def test_model_gaps_warn_only_for_affected_projections():
    p = plan(accounts={"cash": AccountInfo(500_000, "checking"),
        "broker": AccountInfo(100_000, "taxable_brokerage")},
        assumption_curves=[AssumptionCurveData("bond_allocation", fixed_rate=.4)],
        real_assets=[RealAssetData("home", "Home", 2_000_000, is_primary_residence=True)],
        liabilities=[LiabilityData("loan", "Mortgage", 1_500_000, .06,
            monthly_payment=10_000, linked_asset_id="home")])
    result = run_simulation(p)
    assert any("Mortgage interest is deducted without" in w for w in result.metadata.warnings)
    assert any("Taxable bond interest is not modeled" in w for w in result.metadata.warnings)
    plain = run_simulation(plan()).metadata.warnings
    assert not any("Mortgage interest is deducted without" in w or "Taxable bond interest is not modeled" in w for w in plain)

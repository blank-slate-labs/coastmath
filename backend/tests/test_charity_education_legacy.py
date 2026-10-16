"""529 accounts, gifts of appreciated shares, medical deductions and legacy detail."""

import uuid

import pytest

from coastmath.engine.education_savings import state_contribution_deduction
from coastmath.engine.estate_tax import (
    calculate_estate_breakdown,
    step_up_joint_accounts,
)
from coastmath.engine.simulator import (
    _handle_partner_death,
    _limit_charitable_deduction,
    _process_charitable_contributions,
    run_simulation,
)
from coastmath.engine.tax_engine import calculate as calculate_tax
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    CharityData,
    DrawdownEntryData,
    EstateSettingsData,
    ExpenseData,
    IncomeData,
    PlanData,
    PriorityData,
    SimState,
)

ZERO_GROWTH = AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
                             stock_dividend_yield=0, cash_yield_rate=0)


def plan(**changes) -> PlanData:
    values = dict(
        plan_id=str(uuid.uuid4()), birth_year=1976, birth_month=6, filing_status="single",
        life_expectancy=51, start_year=2026, milestones=[], income_streams=[], expenses=[],
        priorities=[], drawdown_order=[], assumptions=ZERO_GROWTH, accounts={},
    )
    values.update(changes)
    return PlanData(**values)


def first_year(p: PlanData):
    return run_simulation(p).yearly_snapshots[0]


# ---------------------------------------------------------------------------
# 529 withdrawals
# ---------------------------------------------------------------------------

def education_plan(*, qualified: bool = False, specific: bool = False) -> PlanData:
    return plan(
        accounts={"edu": AccountInfo(100_000, "five_twenty_nine", cost_basis=40_000)},
        drawdown_order=[DrawdownEntryData(1, "edu")],
        income_streams=[IncomeData("job", "Job", 60_000, growth_rate=0)],
        expenses=[ExpenseData("living", "Living", 50_000, inflation_linked=False),
                  ExpenseData("tuition", "Tuition", 10_000, inflation_linked=False,
                              qualified_education=qualified,
                              specific_funding_source_ids=["edu"] if specific else None)],
    )


def test_nonqualified_529_withdrawal_taxes_earnings_plus_10_percent():
    # No surplus account: income pays taxes; the expense is drawn from the 529.
    nonqualified = first_year(education_plan())
    qualified = first_year(education_plan(qualified=True))
    # 60% of each dollar is earnings; the 10% additional tax is paid from it.
    rate = 0.10 * 0.6
    assert qualified.early_withdrawal_penalty == pytest.approx(0.0)
    assert nonqualified.early_withdrawal_penalty > 0
    withdrawn = 100_000 - nonqualified.accounts["edu"]
    assert nonqualified.early_withdrawal_penalty == pytest.approx(rate * withdrawn, rel=1e-6)
    # The earnings share is ordinary income.
    def federal(gross):
        return calculate_tax(gross_income=gross, deductions=0, filing_status="single", tax_year=2026,
                             earned_income=60_000, w2_income_by_owner={"self": 60_000}).federal
    assert qualified.federal_tax == pytest.approx(federal(60_000), abs=0.01)
    assert nonqualified.federal_tax == pytest.approx(federal(60_000 + 0.6 * withdrawn), abs=0.01)


def test_529_funded_expense_is_qualified_without_the_flag():
    funded = first_year(education_plan(specific=True))
    assert funded.early_withdrawal_penalty == pytest.approx(0.0)
    assert funded.federal_tax == pytest.approx(first_year(education_plan(qualified=True)).federal_tax)


def test_529_basis_recovered_pro_rata_and_unknown_basis_is_all_basis():
    state = SimState(year=2026, accounts={"edu": AccountInfo(100_000, "five_twenty_nine", cost_basis=40_000)})
    state.withdraw_from("edu", 50_000)
    assert state.accounts["edu"].cost_basis == pytest.approx(20_000)
    assert state.capital_gains_this_year == 0
    state.deposit_to("edu", 5_000)
    assert state.accounts["edu"].cost_basis == pytest.approx(25_000)
    assert state.education_contributions_this_year == pytest.approx(5_000)
    # An opening 529 without a basis is treated as all contributions.
    legacy = education_plan()
    legacy.accounts["edu"] = AccountInfo(100_000, "five_twenty_nine")
    assert first_year(legacy).early_withdrawal_penalty == pytest.approx(0.0)


def test_state_contribution_deduction_caps():
    assert state_contribution_deduction("NY", "single", 20_000) == 5_000
    assert state_contribution_deduction("NY", "married_filing_jointly", 20_000) == 10_000
    assert state_contribution_deduction("SC", "single", 50_000) == 50_000
    assert state_contribution_deduction("MI", "single", 8_000, qualified_withdrawals=6_000) == 2_000
    assert state_contribution_deduction("CA", "single", 20_000) == 0


def contribution_plan(amount: float, deduction: bool) -> PlanData:
    return plan(
        state_code="NY",
        accounts={"cash": AccountInfo(0, "checking"), "edu": AccountInfo(0, "five_twenty_nine")},
        income_streams=[IncomeData("job", "Job", 150_000, growth_rate=0)],
        priorities=[PriorityData(priority_rank=1, target_account_id="edu", allocation_mode="amount",
                                 allocation_value=amount)],
        tax_settings={"state_529_deduction": True} if deduction else None,
    )


def test_state_deduction_reduces_state_tax_up_to_the_cap():
    off = first_year(contribution_plan(20_000, False))
    on_large = first_year(contribution_plan(20_000, True))
    on_at_cap = first_year(contribution_plan(5_000, True))
    on_small = first_year(contribution_plan(2_000, True))
    assert on_large.state_tax < off.state_tax
    # Above the $5,000 single cap more contributions save nothing more.
    assert on_large.state_tax == pytest.approx(on_at_cap.state_tax, abs=0.01)
    assert on_small.state_tax > on_at_cap.state_tax
    # Federal tax is unaffected by 529 contributions.
    assert on_large.federal_tax == pytest.approx(off.federal_tax, abs=0.01)


def test_529_balance_is_outside_the_gross_estate_but_reaches_heirs():
    estate = EstateSettingsData(custom_federal_exemption_enabled=True, federal_estate_exemption=0.0)
    result = run_simulation(plan(
        accounts={"cash": AccountInfo(500_000, "checking"), "edu": AccountInfo(300_000, "five_twenty_nine")},
        estate_settings=estate,
    )).metadata.net_legacy
    assert result.education_savings_outside_estate == pytest.approx(300_000)
    assert result.gross_estate == pytest.approx(500_000)
    assert result.estate_tax == pytest.approx(0.40 * 500_000)
    assert result.net_legacy == pytest.approx(800_000 - 0.40 * 500_000)


# ---------------------------------------------------------------------------
# Gifts of appreciated shares
# ---------------------------------------------------------------------------

def share_state() -> SimState:
    return SimState(year=2026, accounts={
        "cash": AccountInfo(200_000, "checking"),
        "brokerage": AccountInfo(100_000, "taxable_brokerage", cost_basis=20_000),
    })


def gift_plan(*gifts: CharityData) -> PlanData:
    return plan(charity_entities=list(gifts))


def test_share_gift_leaves_with_basis_and_realizes_no_gain():
    state = share_state()
    result = _process_charitable_contributions(state, gift_plan(
        CharityData("daf", "DAF", "daf", 40_000, source_account_id="brokerage", funding="appreciated_shares"),
    ), 0.0, set())
    brokerage = state.accounts["brokerage"]
    assert brokerage.balance == pytest.approx(60_000)
    assert brokerage.cost_basis == pytest.approx(12_000)
    assert state.capital_gains_this_year == 0
    assert state.accounts["cash"].balance == pytest.approx(200_000)
    assert result.property_contributions == pytest.approx(40_000)
    assert result.total_contributions == 0
    assert result.account_withdrawals == {"brokerage": pytest.approx(40_000)}


def test_share_gift_30_percent_limit_carryforward_and_cash_within_60_percent():
    state = share_state()
    result = _process_charitable_contributions(state, gift_plan(
        CharityData("shares", "DAF shares", "daf", 40_000, source_account_id="brokerage",
                    funding="appreciated_shares"),
        CharityData("cash", "DAF cash", "daf", 50_000),
    ), 0.0, set())
    limited = _limit_charitable_deduction(result, 100_000, 2026)
    # Shares first: 30% of AGI; cash: 60% of AGI less the shares allowed.
    assert limited.allowable_deduction == pytest.approx(60_000)
    assert limited.committed_property_carryforward == [(2026, pytest.approx(10_000))]
    assert limited.committed_carryforward == [(2026, pytest.approx(20_000))]

    # Next year the share carryover uses the 30% room after current gifts.
    state.year = 2027
    state.capital_gain_gift_carryforward = limited.committed_property_carryforward
    state.daf_carryforward = []
    later = _limit_charitable_deduction(
        _process_charitable_contributions(state, gift_plan(), 0.0, set()), 100_000, 2027)
    assert later.allowable_deduction == pytest.approx(10_000)
    assert later.committed_property_carryforward == []

    # Expired after five years.
    state.year = 2032
    expired = _process_charitable_contributions(state, gift_plan(), 0.0, set())
    assert expired.prior_property_carryforward == []


def test_tax_engine_limits_property_gifts_and_orders_cash_after():
    base = dict(gross_income=100_000, deductions=0, filing_status="single", tax_year=2026,
                itemized_deductions={})
    shares = calculate_tax(**base, charitable_capital_gain_property=40_000)
    floor = 0.005 * 100_000
    assert shares.deduction_used == "itemized"
    assert shares.deduction_amount == pytest.approx(30_000 - floor)
    both = calculate_tax(**base, charitable_capital_gain_property=40_000, charitable_deduction=50_000)
    assert both.deduction_amount == pytest.approx(60_000 - floor)


def test_share_gift_shortfall_is_paid_in_cash():
    state = share_state()
    state.accounts["brokerage"].balance = 10_000
    state.accounts["brokerage"].cost_basis = 5_000
    result = _process_charitable_contributions(state, gift_plan(
        CharityData("daf", "DAF", "direct", 25_000, source_account_id="brokerage", funding="appreciated_shares"),
    ), 0.0, set())
    assert result.property_contributions == pytest.approx(10_000)
    assert result.total_contributions == pytest.approx(15_000)
    assert result.direct_cash_contributions == pytest.approx(15_000)
    assert state.accounts["cash"].balance == pytest.approx(185_000)
    assert result.warnings


# ---------------------------------------------------------------------------
# Medical deductions
# ---------------------------------------------------------------------------

def test_medical_expenses_above_7_5_percent_of_agi_itemize_only_when_larger():
    base = dict(gross_income=100_000, deductions=0, filing_status="single", tax_year=2026)
    alone = calculate_tax(**base, itemized_deductions={}, medical_expenses=20_000)
    # 20,000 - 7,500 = 12,500 is below the 16,100 standard deduction.
    assert alone.deduction_used == "standard"
    with_interest = calculate_tax(**base, itemized_deductions={"mortgage_interest": 10_000},
                                  medical_expenses=20_000)
    assert with_interest.deduction_used == "itemized"
    assert with_interest.deduction_amount == pytest.approx(10_000 + 12_500)
    assert calculate_tax(**base, itemized_deductions={}).deduction_amount == alone.deduction_amount


def medical_plan(enabled: bool, **changes) -> PlanData:
    values = dict(
        accounts={"cash": AccountInfo(500_000, "checking")},
        drawdown_order=[DrawdownEntryData(1, "cash")],
        income_streams=[IncomeData("job", "Job", 60_000, growth_rate=0)],
        healthcare_settings={"enabled": True, "persons": [
            {"owner": "self", "mode": "itemized", "itemized_annual_amount": 30_000}]},
        tax_settings={"medical_expense_deductions": True} if enabled else None,
    )
    values.update(changes)
    return plan(**values)


def test_medical_deduction_is_opt_in_and_itemizes_large_costs():
    off = first_year(medical_plan(False))
    on = first_year(medical_plan(True))
    assert off.deduction_used == "standard"
    assert on.deduction_used == "itemized"
    assert on.deduction_amount == pytest.approx(30_000 - 0.075 * 60_000)
    assert on.federal_tax < off.federal_tax


def se_plan(enabled: bool, profit: float) -> PlanData:
    return plan(
        birth_year=1956, life_expectancy=71,
        accounts={"cash": AccountInfo(500_000, "checking")},
        drawdown_order=[DrawdownEntryData(1, "cash")],
        income_streams=[
            IncomeData("job", "Job", 100_000, growth_rate=0),
            IncomeData("biz", "Consulting", profit, growth_rate=0, tax_category="self_employment"),
        ],
        healthcare_settings={"enabled": True, "persons": [
            {"owner": "self", "mode": "coverage", "medicare_part_d": False,
             "medicare_apply_irmaa": False, "out_of_pocket_annual": 0}]},
        tax_settings={"medical_expense_deductions": True} if enabled else None,
    )


def test_self_employed_health_insurance_deduction_limited_by_profit():
    premiums = first_year(se_plan(False, 1_000)).healthcare.medicare_part_b
    limited_off = first_year(se_plan(False, 1_000))
    limited_on = first_year(se_plan(True, 1_000))
    se_tax_half = 1_000 * 0.9235 * 0.153 / 2
    assert 1_000 - se_tax_half < premiums
    # Lower AGI also restores 6% of the deduction in the senior deduction
    # phase-down (IRC 151(d)(5)), so each deducted dollar saves 22% x 1.06.
    assert limited_off.federal_tax - limited_on.federal_tax == pytest.approx(
        0.22 * 1.06 * (1_000 - se_tax_half), abs=1.0)
    # With ample profit the whole premium is deducted above the line.
    full_off = first_year(se_plan(False, 50_000))
    full_on = first_year(se_plan(True, 50_000))
    assert full_off.federal_tax - full_on.federal_tax == pytest.approx(
        full_off.marginal_rate * 1.06 * premiums, rel=0.01)


# ---------------------------------------------------------------------------
# Legacy detail
# ---------------------------------------------------------------------------

def breakdown(estate: EstateSettingsData, **kwargs):
    return calculate_estate_breakdown(1_000_000, 0.0, estate, 2050, **kwargs)


def test_heir_capital_gains_apply_only_without_step_up():
    stepped = breakdown(EstateSettingsData(heir_capital_gains_rate=0.15), unrealized_gains=200_000)
    assert stepped.heir_capital_gains_tax == 0
    carryover = breakdown(EstateSettingsData(step_up_basis_on_death=False, heir_capital_gains_rate=0.15),
                          unrealized_gains=200_000)
    assert carryover.heir_capital_gains_tax == pytest.approx(30_000)
    assert carryover.net_to_heirs_after_income_tax == pytest.approx(carryover.net_legacy - 30_000)
    spouse = breakdown(EstateSettingsData(step_up_basis_on_death=False, heir_capital_gains_rate=0.15),
                       unrealized_gains=200_000, marital_deduction=True)
    assert spouse.heir_capital_gains_tax == 0


def test_selling_costs_and_charitable_bequest_reduce_net_legacy():
    estate = EstateSettingsData(custom_federal_exemption_enabled=True, federal_estate_exemption=500_000,
                                estate_selling_cost_rate=0.06, charitable_bequest_rate=0.10)
    result = breakdown(estate, real_asset_value=400_000)
    assert result.charitable_bequest == pytest.approx(100_000)
    # IRC 2055: the bequest is deducted before estate tax.
    assert result.taxable_estate_before_exemptions == pytest.approx(900_000)
    assert result.estate_tax == pytest.approx(0.40 * 400_000)
    assert result.selling_costs == pytest.approx(24_000)
    assert result.net_legacy == pytest.approx(1_000_000 - 100_000 - 160_000 - 24_000)


def test_defaults_leave_the_breakdown_unchanged():
    result = breakdown(EstateSettingsData(), pretax_balance=100_000)
    assert result.net_legacy == pytest.approx(result.gross_estate - result.settlement_costs - result.estate_tax)
    for key in ("education_savings_outside_estate", "charitable_bequest", "selling_costs",
                "heir_capital_gains_tax"):
        assert getattr(result, key) == 0


def joint_state() -> SimState:
    return SimState(year=2040, accounts={
        "joint": AccountInfo(200_000, "taxable_brokerage", cost_basis=100_000, owner="joint"),
        "own": AccountInfo(50_000, "taxable_brokerage", cost_basis=10_000, owner="self"),
    })


def test_joint_accounts_step_up_half_or_fully_in_community_property_states():
    estate = EstateSettingsData(joint_account_step_up=True)
    half = joint_state()
    step_up_joint_accounts(half, estate, "NY")
    assert half.accounts["joint"].cost_basis == pytest.approx(150_000)
    assert half.accounts["own"].cost_basis == pytest.approx(10_000)
    full = joint_state()
    step_up_joint_accounts(full, estate, "TX")
    assert full.accounts["joint"].cost_basis == pytest.approx(200_000)
    unchanged = joint_state()
    step_up_joint_accounts(unchanged, EstateSettingsData(), "TX")
    assert unchanged.accounts["joint"].cost_basis == pytest.approx(100_000)
    no_step_up = joint_state()
    step_up_joint_accounts(no_step_up, EstateSettingsData(step_up_basis_on_death=False,
                                                          joint_account_step_up=True), "TX")
    assert no_step_up.accounts["joint"].cost_basis == pytest.approx(100_000)


def test_partner_death_steps_up_joint_account_with_residence_state():
    state = joint_state()
    p = plan(state_code="CA", spouse_birth_year=1976, spouse_life_expectancy=60,
             filing_status="married_filing_jointly",
             estate_settings=EstateSettingsData(joint_account_step_up=True))
    _handle_partner_death(state, p, 2036)
    assert state.accounts["joint"].cost_basis == pytest.approx(200_000)

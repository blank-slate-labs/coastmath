"""Cash-flow inputs: loan interest methods and repeats, monthly transfers,
the cash-reserve sweep, the liquid net worth override and hourly pay."""

from __future__ import annotations

import math

import pytest

from coastmath.engine.amortization import (
    calculate_fixed_payment,
    calculate_year,
    generate_full_schedule,
)
from coastmath.engine.monte_carlo import _metric_value, _TrialSnapshot
from coastmath.engine.simulator import (
    _active_months,
    _end_of_month_growth_factor,
    _loan_occurrence,
    _sweep_excess_reserve_cash,
    run_simulation,
)
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    CashReserveData,
    DrawdownEntryData,
    LiabilityData,
    MilestoneData,
    PlanData,
    PriorityData,
    SimState,
)
from coastmath.engine.waterfall import execute_transfers
from tests.api_support import create_plan

ZERO = AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0)


# ---------------------------------------------------------------------------
# Interest methods (hand-computed)
# ---------------------------------------------------------------------------

def test_simple_interest_never_compounds_unpaid_interest():
    # 10,000 at 12%: 100 of interest a month on principal. A 50 payment
    # leaves 50 a month accrued, which earns nothing.
    simple = calculate_year(10_000, 0.12, 50, interest_method="simple")
    assert simple.remaining_balance == pytest.approx(10_000)
    assert simple.accrued_interest == pytest.approx(600)
    assert simple.interest_paid == pytest.approx(600)
    assert simple.principal_paid == 0 and simple.interest_capitalized == 0
    # Monthly amortization capitalizes it instead: 10,000 x 1.01^12 - 50 x s(12).
    monthly = calculate_year(10_000, 0.12, 50)
    expected = 10_000 * 1.01 ** 12 - 50 * (1.01 ** 12 - 1) / 0.01
    assert monthly.remaining_balance == pytest.approx(expected)
    # Next year the accrued interest is paid before principal.
    later = calculate_year(simple.remaining_balance, 0.12, 1_000, months=1, interest_method="simple",
                           accrued_interest=simple.accrued_interest)
    assert later.interest_paid == pytest.approx(700)
    assert later.principal_paid == pytest.approx(300)
    assert later.accrued_interest == 0 and later.remaining_balance == pytest.approx(9_700)


def test_simple_matches_monthly_when_payments_cover_interest():
    simple = calculate_year(10_000, 0.12, 200, interest_method="simple")
    monthly = calculate_year(10_000, 0.12, 200)
    assert simple.remaining_balance == pytest.approx(monthly.remaining_balance)
    assert simple.interest_paid == pytest.approx(monthly.interest_paid)


def test_daily_accrual_compounds_over_actual_days():
    # 3.65% a year is 0.01% a day. January has 31 days.
    january = calculate_year(10_000, 0.0365, 1_000, months=1, interest_method="daily", year=2025)
    interest = 10_000 * (1.0001 ** 31 - 1)
    assert january.interest_paid == pytest.approx(interest)
    assert january.principal_paid == pytest.approx(1_000 - interest)
    # A leap-year February has 29 days, a common one 28.
    leap = calculate_year(10_000, 0.0365, 1_000, months=1, interest_method="daily", year=2024, first_month=2)
    common = calculate_year(10_000, 0.0365, 1_000, months=1, interest_method="daily", year=2025, first_month=2)
    assert leap.interest_paid == pytest.approx(10_000 * (1.0001 ** 29 - 1))
    assert common.interest_paid == pytest.approx(10_000 * (1.0001 ** 28 - 1))
    # With no payment a year of daily compounding is 365 days in 2025, 366 in 2024.
    assert calculate_year(10_000, 0.0365, 0, interest_method="daily", year=2025).remaining_balance == \
        pytest.approx(10_000 * 1.0001 ** 365)
    assert calculate_year(10_000, 0.0365, 0, interest_method="daily", year=2024).remaining_balance == \
        pytest.approx(10_000 * 1.0001 ** 366)


def test_daily_payment_pays_off_within_the_term():
    rate = 0.06
    payment = calculate_fixed_payment(12_000, rate, 12, "daily")
    monthly_rate = (1 + rate / 365) ** (365 / 12) - 1
    assert payment == pytest.approx(12_000 * monthly_rate / (1 - (1 + monthly_rate) ** -12))
    assert payment > calculate_fixed_payment(12_000, rate, 12)
    schedule = generate_full_schedule(12_000, rate, 12, payment, interest_method="daily", start_year=2025)
    # Actual month lengths differ from the average month by a few dollars at most.
    assert schedule[0].remaining_balance < 5
    total_paid = sum(row.principal_paid + row.interest_paid for row in schedule)
    assert total_paid == pytest.approx(12 * payment, abs=5)


def test_default_method_is_unchanged():
    assert calculate_year(10_000, 0.06, 300) == calculate_year(10_000, 0.06, 300, interest_method="monthly")


# ---------------------------------------------------------------------------
# Repeating loans
# ---------------------------------------------------------------------------

def _loan_plan(loan: LiabilityData, inflation: float = 0.0, milestones=()):
    return PlanData(
        plan_id='00000000-0000-4000-8000-000000000101', birth_year=1980, birth_month=1,
        filing_status='single', life_expectancy=60, start_year=2026, state_code='FL',
        assumptions=AssumptionData(inflation_rate=inflation, stock_growth_rate=0, bond_return_rate=0,
                                   stock_dividend_yield=0),
        accounts={'cash': AccountInfo(500_000, 'checking')},
        drawdown_order=[DrawdownEntryData(1, 'cash')],
        liabilities=[loan], milestones=list(milestones),
        tax_settings={'cash_flow_frequency': 'annual'})


def _loan_payments(result, name='Car'):
    return {row.year: sum(item.amount for item in row.cash_flow.expenses if item.name == name)
            for row in result.yearly_snapshots}


def test_loan_repeats_on_its_original_terms_until_the_end_year():
    loan = LiabilityData(id='car', name='Car', principal_balance=12_000, interest_rate=0.0, term_months=12,
                         monthly_payment=1_000, recurrence_years=3, recurrence_end_year=2032)
    paid = _loan_payments(run_simulation(_loan_plan(loan)))
    assert paid[2026] == pytest.approx(12_000)
    assert paid[2027] == 0 and paid[2028] == 0
    assert paid[2029] == pytest.approx(12_000) and paid[2032] == pytest.approx(12_000)
    assert paid[2035] == 0


def test_without_a_repeat_the_loan_is_taken_once():
    loan = LiabilityData(id='car', name='Car', principal_balance=12_000, interest_rate=0.0, term_months=12,
                         monthly_payment=1_000)
    paid = _loan_payments(run_simulation(_loan_plan(loan)))
    assert paid[2026] == pytest.approx(12_000) and sum(paid.values()) == pytest.approx(12_000)


def test_repeated_loan_terms_are_in_start_year_dollars():
    loan = LiabilityData(id='car', name='Car', principal_balance=12_000, interest_rate=0.0, term_months=12,
                         monthly_payment=1_000, recurrence_years=2, recurrence_end_year=2028)
    result = run_simulation(_loan_plan(loan, inflation=0.03))
    paid = _loan_payments(result)
    assert paid[2028] == pytest.approx(12_000 * 1.03 ** 2)
    # Each occurrence is paid off within its own term.
    assert {row.year: row.liabilities_balance for row in result.yearly_snapshots}[2028] == pytest.approx(0, abs=0.01)


def test_overlapping_occurrences_are_separate_loans():
    loan = LiabilityData(id='car', name='Car', principal_balance=24_000, interest_rate=0.0, term_months=24,
                         monthly_payment=1_000, recurrence_years=1, recurrence_end_year=2027)
    result = run_simulation(_loan_plan(loan))
    paid = _loan_payments(result)
    # 2027 pays the original's second year and the repeat's first year.
    assert paid[2027] == pytest.approx(24_000)
    assert {row.year: row.liabilities_balance for row in result.yearly_snapshots}[2027] == pytest.approx(12_000)


def test_end_milestone_stops_later_occurrences():
    milestone = MilestoneData(id='m', name='Stop', trigger_type='date', trigger_date='2030-06-01')
    loan = LiabilityData(id='car', name='Car', principal_balance=12_000, interest_rate=0.0, term_months=12,
                         monthly_payment=1_000, recurrence_years=2, recurrence_end_milestone_id='m')
    state = SimState(2030, accounts={})
    milestones = {'m': milestone}
    assert _loan_occurrence(loan, 2028, 2026, milestones, state, [], 1) == 1
    state.triggered_milestones = {'m'}
    # Reached in June 2030: January's 2030 occurrence still happens.
    assert _loan_occurrence(loan, 2030, 2026, milestones, state, ['m'], 1) == 2
    assert _loan_occurrence(loan, 2032, 2026, milestones, state, [], 1) is None
    paid = _loan_payments(run_simulation(_loan_plan(loan, milestones=[milestone])))
    assert paid[2030] == pytest.approx(12_000) and paid[2032] == 0


# ---------------------------------------------------------------------------
# Monthly transfers
# ---------------------------------------------------------------------------

def _transfer_state():
    return SimState(2026, accounts={
        'savings': AccountInfo(12_000, 'savings'),
        'brokerage': AccountInfo(0, 'taxable_brokerage', cost_basis=0),
    })


def _transfer(**extra):
    return PriorityData(priority_rank=1, priority_type='transfer', source_account_id='savings',
                        target_account_id='brokerage', max_annual_amount=1_200, transfer_frequency='monthly', **extra)


def test_monthly_transfer_moves_a_twelfth_per_active_month():
    state = _transfer_state()
    execute_transfers([_transfer()], state, active_months=lambda p: list(range(7, 13)),
                      month_growth=lambda aid, months: 0.0)
    assert state.get_balance('brokerage') == pytest.approx(600)
    assert state.get_balance('savings') == pytest.approx(11_400)


def test_monthly_transfer_shifts_growth_from_source_to_target():
    state = _transfer_state()
    factors = {'savings': 0.10, 'brokerage': 0.05}
    execute_transfers([_transfer()], state, active_months=lambda p: list(range(7, 13)),
                      month_growth=lambda aid, months: factors[aid])
    # 600 moved; the source gives up 60 of growth, the target earns 30.
    assert state.get_balance('savings') == pytest.approx(12_000 - 600 - 60)
    assert state.get_balance('brokerage') == pytest.approx(630)
    assert state.withdrawal_growth_adjustment == pytest.approx(-30)


def test_monthly_without_active_months_moves_nothing_and_annual_is_unchanged():
    state = _transfer_state()
    execute_transfers([_transfer()], state, active_months=lambda p: [], month_growth=lambda aid, months: 0.0)
    assert state.get_balance('brokerage') == 0
    annual = _transfer_state()
    execute_transfers([_transfer()], annual)  # direct callers keep annual semantics
    assert annual.get_balance('brokerage') == pytest.approx(1_200)


def test_active_months_follow_milestone_months_and_partial_years():
    start = MilestoneData(id='s', name='Start', trigger_type='date', trigger_date='2026-07-01', resolved_month=7)
    assert _active_months(start, None, {'s'}, ['s'], 2026, 1, 1.0) == list(range(7, 13))
    assert _active_months(start, None, {'s'}, [], 2027, 1, 1.0) == list(range(1, 13))
    assert _active_months(None, None, set(), [], 2026, 1, 0.25) == [10, 11, 12]
    assert _active_months(start, None, set(), [], 2026, 1, 1.0) == []


def test_end_of_month_growth_factor():
    assert _end_of_month_growth_factor(0.12, [12]) == 0
    assert _end_of_month_growth_factor(0.12, [6]) == pytest.approx(1.12 ** 0.5 - 1)
    assert _end_of_month_growth_factor(0.0, [1, 2]) == 0


def test_monthly_transfer_in_a_simulation_earns_less_source_growth():
    def plan(frequency):
        return PlanData(
            plan_id='00000000-0000-4000-8000-000000000102', birth_year=1980, birth_month=1,
            filing_status='single', life_expectancy=48, start_year=2026, state_code='FL',
            assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0.10, bond_return_rate=0,
                                       stock_dividend_yield=0),
            accounts={'cash': AccountInfo(12_000, 'checking'),
                      'brokerage': AccountInfo(0, 'taxable_brokerage', cost_basis=0)},
            drawdown_order=[DrawdownEntryData(1, 'cash')],
            priorities=[PriorityData(priority_rank=1, priority_type='transfer', source_account_id='cash',
                                     target_account_id='brokerage', max_annual_amount=12_000,
                                     transfer_frequency=frequency)],
            tax_settings={'cash_flow_frequency': 'annual'})
    annual = run_simulation(plan('annual')).yearly_snapshots[0].accounts
    monthly = run_simulation(plan('monthly')).yearly_snapshots[0].accounts
    assert annual['brokerage'] == pytest.approx(12_000)
    # 1,000 at the end of each month grows at 10% a year until December.
    expected = sum(1_000 * 1.10 ** ((12 - month) / 12) for month in range(1, 13))
    assert monthly['brokerage'] == pytest.approx(expected)
    assert monthly['cash'] == pytest.approx(0, abs=0.01)


def _loss_year_plan(source, target, accounts, cap=None):
    return PlanData(
        plan_id='00000000-0000-4000-8000-000000000104', birth_year=1960, birth_month=1,
        filing_status='single', life_expectancy=67, start_year=2026, state_code='FL',
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=-0.5, bond_return_rate=0,
                                   stock_dividend_yield=0),
        accounts=accounts, drawdown_order=[DrawdownEntryData(1, 'cash')],
        priorities=[PriorityData(priority_rank=1, priority_type='transfer', source_account_id=source,
                                 target_account_id=target, max_annual_amount=cap, transfer_frequency='monthly')],
        tax_settings={'mode': 'flat', 'ordinary_income_tax_rate': 0, 'capital_gains_tax_rate': 0})


def _stocks(balance):
    return AccountInfo(balance, 'taxable_brokerage', cost_basis=balance, investment_settings={'bond_allocation': 0})


MONTH_LOSS = 0.5 ** (1 / 12)  # one month of a -50% year


def test_uncapped_monthly_transfer_leaves_the_loss_after_the_move_behind():
    accounts = {'cash': AccountInfo(0, 'checking'), 'b': _stocks(12_000)}
    s = run_simulation(_loss_year_plan('b', 'cash', accounts)).yearly_snapshots[0].accounts
    # Everything moves at the end of January, after one month of the loss.
    assert s['cash'] == pytest.approx(12_000 * MONTH_LOSS, abs=0.01)
    assert s['cash'] == pytest.approx(11_326.49, abs=0.01)
    assert s['b'] == pytest.approx(0, abs=0.01)


def test_capped_monthly_transfer_from_a_losing_source():
    accounts = {'cash': AccountInfo(0, 'checking'), 'b': _stocks(12_000)}
    s = run_simulation(_loss_year_plan('b', 'cash', accounts, cap=6_000)).yearly_snapshots[0].accounts
    # $500 leaves at the end of each month; what stays loses 50% over the year.
    assert s['cash'] == pytest.approx(6_000, abs=0.01)
    expected = 12_000 * 0.5 - sum(500 * MONTH_LOSS ** (12 - month) for month in range(1, 13))
    assert s['b'] == pytest.approx(expected, abs=0.01)


def test_capped_monthly_transfer_into_a_losing_target():
    accounts = {'cash': AccountInfo(12_000, 'checking'), 'b': _stocks(0)}
    s = run_simulation(_loss_year_plan('cash', 'b', accounts, cap=12_000)).yearly_snapshots[0].accounts
    # $1,000 arrives at the end of each month and loses from then to December.
    assert s['b'] == pytest.approx(sum(1_000 * MONTH_LOSS ** (12 - month) for month in range(1, 13)), abs=0.01)
    assert s['cash'] == pytest.approx(0, abs=0.01)


def test_monthly_transfer_from_a_source_that_lost_everything_moves_the_balance_as_is():
    state = _transfer_state()
    rule = PriorityData(priority_rank=1, priority_type='transfer', source_account_id='savings',
                        target_account_id='brokerage', transfer_frequency='monthly')
    execute_transfers([rule], state, active_months=lambda p: [1],
                      month_growth=lambda aid, months: -1.0 if aid == 'savings' else 0.0)
    assert state.get_balance('brokerage') == pytest.approx(12_000)
    assert state.get_balance('savings') == pytest.approx(0)


# ---------------------------------------------------------------------------
# Cash-reserve sweep
# ---------------------------------------------------------------------------

def _sweep_plan(reserve, priorities, accounts=None):
    return PlanData(
        plan_id='00000000-0000-4000-8000-000000000103', birth_year=1980, birth_month=1,
        filing_status='single', life_expectancy=48, start_year=2026, state_code='FL',
        assumptions=ZERO,
        accounts=accounts or {'cash': AccountInfo(50_000, 'checking'),
                              'brokerage': AccountInfo(0, 'taxable_brokerage', cost_basis=0)},
        drawdown_order=[DrawdownEntryData(1, 'cash'), DrawdownEntryData(2, 'brokerage')],
        priorities=priorities, cash_reserve=reserve, tax_settings={'cash_flow_frequency': 'annual'})


INVEST = [PriorityData(priority_rank=1, priority_type='contribution', target_account_id='brokerage')]


def test_sweep_moves_cash_above_the_reserve_into_the_rules():
    swept = run_simulation(_sweep_plan(CashReserveData(('cash',), 10_000, sweep_excess=True), INVEST))
    first = swept.yearly_snapshots[0]
    assert first.accounts['cash'] == pytest.approx(10_000)
    assert first.accounts['brokerage'] == pytest.approx(40_000)
    assert [(t.source_account_id, t.target_account_id, round(t.amount, 2)) for t in first.transfers] == \
        [('cash', 'brokerage', 40_000)]
    # Moving cash is not taxable.
    held = run_simulation(_sweep_plan(CashReserveData(('cash',), 10_000), INVEST)).yearly_snapshots[0]
    assert held.accounts['cash'] == pytest.approx(50_000)
    assert first.taxes == pytest.approx(held.taxes)


def test_sweep_respects_annual_caps_and_skips_reserve_targets():
    capped = [PriorityData(priority_rank=1, priority_type='contribution', target_account_id='cash'),
              PriorityData(priority_rank=2, priority_type='contribution', target_account_id='brokerage',
                           max_annual_amount=5_000)]
    first = run_simulation(_sweep_plan(CashReserveData(('cash',), 10_000, sweep_excess=True), capped)).yearly_snapshots[0]
    assert first.accounts['brokerage'] == pytest.approx(5_000)
    assert first.accounts['cash'] == pytest.approx(45_000)


def test_sweep_never_draws_a_locked_reserve_account():
    state = SimState(2026, accounts={'cash': AccountInfo(50_000, 'checking'),
                                     'brokerage': AccountInfo(0, 'taxable_brokerage', cost_basis=0)})
    state.cash_reserve_accounts = ('cash',)
    state.cash_reserve_target = 10_000
    state.locked_account_ids = {'cash'}
    plan = _sweep_plan(CashReserveData(('cash',), 10_000, sweep_excess=True), INVEST)
    assert _sweep_excess_reserve_cash(plan, state, [], 1.0, lambda amount, rules: pytest.fail("allocated")) == {}
    assert state.get_balance('cash') == 50_000


# ---------------------------------------------------------------------------
# Liquid net worth override
# ---------------------------------------------------------------------------

def test_liquid_override_and_default_classification():
    state = SimState(2026, accounts={
        'cash': AccountInfo(1_000, 'checking'),
        'locked': AccountInfo(2_000, 'roth_ira'),
        'forced_in': AccountInfo(4_000, 'roth_ira', include_in_liquid=True),
        'out': AccountInfo(8_000, 'taxable_brokerage', include_in_liquid=False),
    })
    state.locked_account_ids = {'locked', 'forced_in'}
    assert state.illiquid_account_ids() == frozenset({'locked', 'out'})
    assert state.liquid_account_balance() == 5_000
    state.locked_account_ids = set()
    assert state.liquid_account_balance() == 7_000


def test_excluded_account_leaves_liquid_metrics():
    def plan(flag):
        return PlanData(
            plan_id='00000000-0000-4000-8000-000000000104', birth_year=1980, birth_month=1,
            filing_status='single', life_expectancy=48, start_year=2026, state_code='FL', assumptions=ZERO,
            accounts={'cash': AccountInfo(10_000, 'checking'),
                      'collectibles': AccountInfo(5_000, 'other', include_in_liquid=flag)},
            drawdown_order=[DrawdownEntryData(1, 'cash')], tax_settings={'cash_flow_frequency': 'annual'})
    default = run_simulation(plan(None)).yearly_snapshots[0]
    excluded = run_simulation(plan(False)).yearly_snapshots[0]
    assert default.liquid_account_total() == pytest.approx(15_000)
    assert excluded.liquid_account_total() == pytest.approx(10_000)
    assert excluded.net_worth == pytest.approx(default.net_worth)
    assert _metric_value(excluded, 'liquid_net_worth') == pytest.approx(10_000)
    assert _metric_value(default, 'liquid_net_worth') == pytest.approx(15_000)
    trial = _TrialSnapshot(2026, 46, 15_000, {'cash': 10_000, 'collectibles': 5_000}, 0.0, 10_000,
                           liquid_excluded=5_000)
    assert _metric_value(trial, 'liquid_net_worth') == pytest.approx(10_000)


# ---------------------------------------------------------------------------
# API persistence
# ---------------------------------------------------------------------------

async def _plan_id(client, name="Cash-flow inputs"):
    return (await create_plan(client, name=name, birth_year=1980))["id"]


@pytest.mark.anyio
async def test_loan_options_round_trip_and_defaults_stay_omitted(client):
    pid = await _plan_id(client)
    base = {"name": "Car", "principal_balance": 20000, "interest_rate": 6, "term_months": 60}
    plain = await client.post(f"/api/plans/{pid}/liabilities", json=base)
    assert plain.status_code == 201, plain.text
    for key in ("interest_method", "recurrence_years", "recurrence_end_year", "recurrence_end_milestone_id"):
        assert key not in plain.json()
    milestone = (await client.post(f"/api/plans/{pid}/milestones", json={
        "name": "Stop", "trigger_type": "date", "trigger_date": "2040-01-01"})).json()
    created = await client.post(f"/api/plans/{pid}/liabilities", json={
        **base, "interest_method": "daily", "recurrence_years": 7, "recurrence_end_milestone_id": milestone["id"]})
    assert created.status_code == 201, created.text
    loan = created.json()
    assert (loan["interest_method"], loan["recurrence_years"], loan["recurrence_end_milestone_id"]) == \
        ("daily", 7, milestone["id"])
    url = f"/api/plans/{pid}/liabilities/{loan['id']}"
    updated = await client.put(url, json={"interest_method": "simple", "recurrence_end_year": 2045})
    assert updated.status_code == 200, updated.text
    assert (updated.json()["interest_method"], updated.json()["recurrence_end_year"]) == ("simple", 2045)
    # An end without a repeat is refused, also after merging with the saved row.
    assert (await client.put(url, json={"recurrence_years": None})).status_code == 422
    assert (await client.post(f"/api/plans/{pid}/liabilities", json={**base, "recurrence_end_year": 2040})).status_code == 422
    assert (await client.post(f"/api/plans/{pid}/liabilities", json={**base, "interest_method": "weekly"})).status_code == 422
    other = await _plan_id(client, "Other")
    foreign = (await client.post(f"/api/plans/{other}/milestones", json={
        "name": "Elsewhere", "trigger_type": "date", "trigger_date": "2040-01-01"})).json()
    refused = await client.put(url, json={"recurrence_end_milestone_id": foreign["id"]})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "VALIDATION_ERROR"
    schedule = await client.get(f"{url}/amortization")
    assert schedule.status_code == 200 and schedule.json()["schedule"]
    simulated = await client.post(f"/api/plans/{pid}/simulate")
    assert simulated.status_code == 200, simulated.text

    copied = await client.post(f"/api/plans/{pid}/duplicate")
    assert copied.status_code == 201, copied.text
    new_pid = copied.json()["id"]
    new_loans = {row["name"]: row for row in (await client.get(f"/api/plans/{new_pid}/liabilities")).json()
                 if "recurrence_years" in row}
    new_milestone = (await client.get(f"/api/plans/{new_pid}/milestones")).json()[0]
    assert new_loans["Car"]["recurrence_end_milestone_id"] == new_milestone["id"]
    assert new_loans["Car"]["interest_method"] == "simple"


@pytest.mark.anyio
async def test_monthly_transfer_rule_round_trips(client):
    pid = await _plan_id(client)
    savings = (await client.post("/api/accounts", json={"name": "Savings", "account_type": "savings", "balance": 10000})).json()
    brokerage = (await client.post("/api/accounts", json={"name": "Brokerage", "account_type": "taxable_brokerage",
                                                         "balance": 0})).json()
    url = f"/api/plans/{pid}/priorities"

    async def save(items):
        revision = (await client.get(url)).json()["revision"]
        return await client.put(url, json={"expected_revision": revision, "items": items})

    rule = {"priority_rank": 1, "priority_type": "transfer", "source_account_id": savings["id"],
            "target_account_id": brokerage["id"], "max_annual_amount": 1200}
    annual = await save([rule])
    assert annual.status_code == 200, annual.text
    assert "transfer_frequency" not in annual.json()["items"][0]
    monthly = await save([{**rule, "transfer_frequency": "monthly"}])
    assert monthly.status_code == 200, monthly.text
    assert (await client.get(url)).json()["items"][0]["transfer_frequency"] == "monthly"
    contribution = await save([{"priority_rank": 1, "target_account_id": brokerage["id"], "transfer_frequency": "monthly"}])
    assert contribution.status_code == 422


@pytest.mark.anyio
async def test_liquid_override_and_sweep_settings_persist(client):
    created = await client.post("/api/accounts", json={"name": "Art", "account_type": "other", "balance": 5000,
                                                       "include_in_liquid": False})
    assert created.status_code == 201, created.text
    assert created.json()["include_in_liquid"] is False
    url = f"/api/accounts/{created.json()['id']}"
    assert (await client.put(url, json={"name": "Art collection"})).json()["include_in_liquid"] is False
    cleared = await client.put(url, json={"include_in_liquid": None})
    assert "include_in_liquid" not in cleared.json()

    pid = await _plan_id(client)
    cash = (await client.post("/api/accounts", json={"name": "Checking", "account_type": "checking", "balance": 50000})).json()
    saved = await client.put(f"/api/plans/{pid}", json={"cash_reserve_settings": {
        "enabled": True, "account_ids": [cash["id"]], "reserve_amount": 10000, "sweep_excess": True}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["cash_reserve_settings"]["sweep_excess"] is True
    plain = await client.put(f"/api/plans/{pid}", json={"cash_reserve_settings": {
        "enabled": True, "account_ids": [cash["id"]], "reserve_amount": 10000}})
    assert "sweep_excess" not in plain.json()["cash_reserve_settings"]


@pytest.mark.anyio
async def test_hourly_pay_sets_the_annual_amount(client):
    pid = await _plan_id(client)
    base = f"/api/plans/{pid}/incomes"
    created = await client.post(base, json={"name": "Shifts", "amount_frequency": "hourly", "hourly_rate": 25.5,
                                            "hours_per_week": 30, "annual_amount": 1, "tax_category": "employment"})
    assert created.status_code == 201, created.text
    row = created.json()
    assert (row["amount_frequency"], row["hourly_rate"], row["hours_per_week"]) == ("hourly", 25.5, 30)
    assert row["annual_amount"] == pytest.approx(25.5 * 30 * 52)
    url = f"{base}/{row['id']}"
    raised = await client.put(url, json={"hourly_rate": 30})
    assert raised.status_code == 200, raised.text
    assert raised.json()["annual_amount"] == pytest.approx(30 * 30 * 52)
    # A client that edits only the annual amount switches the income to annual.
    edited = await client.put(url, json={"annual_amount": 50000})
    assert edited.json()["amount_frequency"] == "annual" and edited.json()["annual_amount"] == 50000
    assert "hourly_rate" not in edited.json() and "hours_per_week" not in edited.json()
    missing = await client.post(base, json={"name": "Half", "amount_frequency": "hourly", "hourly_rate": 20})
    assert missing.status_code == 422
    plain = await client.post(base, json={"name": "Salary", "annual_amount": 60000, "amount_frequency": "monthly"})
    assert "hourly_rate" not in plain.json()
    assert math.isclose(plain.json()["annual_amount"], 60000)

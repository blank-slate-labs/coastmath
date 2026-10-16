"""Roth distribution ordering checked against independent examples and reconciled with cash and tax."""
from dataclasses import replace
from uuid import uuid4

import pytest

from coastmath.engine.roth import ledger
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PriorityData,
    SimState,
)
from coastmath.engine.waterfall import execute_drawdown, execute_roth_conversions
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data
from coastmath.schemas.roth_settings import RothSettings
from tests.engine_support import audit_plan


def account(balance=100_000, basis=60_000, first=2010, kind='roth_ira', **kwargs):
    return AccountInfo(balance, kind, roth_settings={'contribution_basis': basis,
        'first_contribution_year': first, 'conversions': []}, **kwargs)


def draw(state, amount, age=46, aid='roth', **kwargs):
    return execute_drawdown(amount, [DrawdownEntryData(1, aid)], state, age=age, birth_month=1, **kwargs)


def test_contribution_basis_is_tax_and_penalty_free_then_earnings_are_taxable():
    state = SimState(2026, {'roth': account()})
    assert draw(state, 60_000) == ({'roth': 60_000}, 0)
    assert ledger(state).totals() == (0, 0)
    withdrawals, penalty = draw(state, 9_000)
    assert withdrawals['roth'] == pytest.approx(10_000)
    assert penalty == pytest.approx(1_000)
    assert ledger(state).totals() == pytest.approx((10_000, 1_000))


def test_recorded_conversion_establishes_five_year_clock_when_first_year_is_unknown():
    a = account(20000, 0, None)
    a.roth_settings['conversions'] = [{'year': 2020, 'taxable_basis': 10000, 'nontaxable_basis': 0}]
    p = replace(audit_plan(expenses=[ExpenseData('e', 'Living', 15000)],
        drawdown_order=[DrawdownEntryData(1, 'roth')],
        tax_settings={'mode': 'flat', 'ordinary_income_tax_rate': .2}),
        birth_year=1966, life_expectancy=61, accounts={'roth': a})
    row = run_simulation(p).yearly_snapshots[0]
    assert row.taxes == 0
    assert row.net_worth == 5000
    assert a.roth_settings['first_contribution_year'] is None  # input not mutated


def test_account_named_self_does_not_share_designated_basis_with_own_ira():
    state = SimState(2026, {'roth': account(20000, 0), 'self': account(50000, 50000, kind='roth_401k')})
    assert draw(state, 9000)[1] == pytest.approx(1000)
    assert ledger(state).totals() == pytest.approx((10000, 1000))


def test_conversion_cannot_precede_reported_first_roth_year():
    with pytest.raises(ValueError, match='cannot be later than a recorded conversion'):
        RothSettings(first_contribution_year=2024, conversions=[{'year': 2020, 'taxable_basis': 1000}])


def test_basis_aggregates_across_own_iras_but_not_spouse_or_inherited_ira():
    state = SimState(2026, {'roth': account(50_000, 0), 'other': account(50_000, 20_000),
        'spouse': account(50_000, 50_000, owner='spouse'),
        'inherit': account(50_000, 50_000, inherited_year=2020)})
    assert draw(state, 20_000)[1] == 0
    assert draw(state, 9_000)[1] == pytest.approx(1_000)


def test_conversion_fifo_taxable_then_nontaxable_and_separate_five_year_clocks():
    a = account(100_000, 10_000)
    a.roth_settings['conversions'] = [
        {'year': 2024, 'taxable_basis': 10_000, 'nontaxable_basis': 5_000},
        {'year': 2020, 'taxable_basis': 20_000, 'nontaxable_basis': 0},
        {'year': 2024, 'taxable_basis': 5_000, 'nontaxable_basis': 0}]
    state = SimState(2026, {'roth': a})
    #30k contribution/seasoned conversion +15ktaxable conversion +5knontaxable.
    assert draw(state, 48_500)[0]['roth'] == pytest.approx(50_000)
    assert ledger(state).totals() == pytest.approx((0, 1_500), abs=.0001)
    ledger(state).finish(state.accounts)
    assert state.accounts['roth'].roth_settings['contribution_basis'] == 0
    assert sum(c['taxable_basis']+c['nontaxable_basis'] for c in state.accounts['roth'].roth_settings['conversions']) == pytest.approx(0)


@pytest.mark.parametrize('first,expected_income', [(2021, 0), (2022, 10_000)])
def test_age_sixty_still_requires_five_tax_years_for_earnings(first, expected_income):
    state = SimState(2026, {'roth': account(20_000, 0, first)})
    assert draw(state, 10_000, age=60)[1] == 0
    assert ledger(state).totals() == (expected_income, 0)


def test_designated_roth_prorates_each_distribution_and_preserves_remaining_basis():
    state = SimState(2026, {'roth': account(kind='roth_401k')})
    #10k =6kbasis+4kearnings;400penalty leaves9600cash.
    assert draw(state, 9_600)[0]['roth'] == pytest.approx(10_000)
    assert ledger(state).totals() == pytest.approx((4_000, 400))
    ledger(state).finish(state.accounts)
    assert state.accounts['roth'].roth_settings['contribution_basis'] == pytest.approx(54_000)


def test_in_plan_rollover_recapture_applies_after_regular_basis():
    a = account(100_000, 20_000, kind='roth_401k')
    a.roth_settings['conversions'] = [{'year': 2024, 'taxable_basis': 30_000, 'nontaxable_basis': 10_000}]
    state = SimState(2026, {'roth': a})
    #50k distribution=30kbasis+20kearnings;10k ofbasis isrecenttaxableconversion.
    assert draw(state, 47_000)[0]['roth'] == pytest.approx(50_000)
    assert ledger(state).totals() == pytest.approx((20_000, 3_000))


def test_inherited_roth_earnings_before_five_years_taxable_without_penalty():
    state = SimState(2026, {'roth': account(20_000, 5_000, 2024, inherited_year=2025)})
    assert draw(state, 10_000)[1] == 0
    assert ledger(state).totals() == (5_000, 0)


def test_new_conversions_are_recorded_and_not_taxed_twice_when_distributed():
    state = SimState(2026, {'ira': AccountInfo(20_000, 'traditional_ira'), 'roth': account(0, 0, None)})
    execute_roth_conversions([PriorityData(1, target_account_id='roth', source_account_id='ira',
        priority_type='roth_conversion')], state)
    assert state.roth_conversions_this_year == 20_000
    assert draw(state, 9_000)[0]['roth'] == pytest.approx(10_000)
    assert ledger(state).totals() == pytest.approx((0, 1_000))


def test_later_regular_contribution_reclassifies_earlier_ira_earnings():
    state = SimState(2026, {'roth': account(20_000, 0)})
    draw(state, 9_000)
    state.deposit_to('roth', 6_000)
    assert ledger(state).totals() == pytest.approx((4_000, 400))


def test_roth_income_tax_penalty_and_net_worth_reconcile_in_simulation():
    p = replace(audit_plan(expenses=[ExpenseData('e', 'Living', 69_000)],
        drawdown_order=[DrawdownEntryData(1, 'roth')], tax_settings={'mode': 'flat', 'ordinary_income_tax_rate': .2}),
        accounts={'roth': account()}, life_expectancy=47)
    first = run_simulation(p).yearly_snapshots[0]
    #60kbasis +9knet fromearnings /(.7 after20%tax and10%penalty).
    earnings = 9_000/.7
    assert first.gross_income == pytest.approx(earnings, abs=.01)
    assert first.early_withdrawal_penalty == pytest.approx(earnings*.1, abs=.01)
    assert first.net_worth == pytest.approx(100_000-60_000-earnings, abs=.01)
    assert first.taxes == pytest.approx(earnings*.3, abs=.01)
    assert first.net_worth + first.expenses + first.taxes == pytest.approx(100_000, abs=.01)


def test_stateless_roth_history_survives_conversion():
    data = {'contribution_basis': 7_000, 'first_contribution_year': 2020,
        'conversions': [{'year': 2024, 'taxable_basis': 1000, 'nontaxable_basis': 2000}]}
    request = PlanDataRequest(plan_id=uuid4(), birth_year=1980, start_year=2026, life_expectancy=50,
        accounts={'roth': {'balance': 20_000, 'account_type': 'roth_ira', 'roth_settings': data}})
    assert request_to_engine_data(request).accounts['roth'].roth_settings == data


@pytest.mark.anyio
async def test_roth_history_persistence_partial_save_and_type_change(client):
    saved = await client.post('/api/accounts', json={'name':'Roth', 'account_type':'roth_ira',
        'balance':100_000, 'roth_settings': {'contribution_basis':60_000, 'first_contribution_year':2010}})
    assert saved.status_code == 201, saved.text
    url = f"/api/accounts/{saved.json()['id']}"
    assert (await client.put(url, json={'balance':110_000})).json()['roth_settings']['contribution_basis'] == 60_000
    invalid = await client.put(url, json={'roth_settings': {'contribution_basis': -1}})
    assert invalid.status_code == 422
    assert (await client.get('/api/accounts')).json()[0]['roth_settings']['contribution_basis'] == 60_000
    assert (await client.put(url, json={'account_type':'checking'})).json()['roth_settings'] is None


def test_later_contribution_reconciles_earlier_penalty_and_tax_without_losing_cash():
    p = replace(audit_plan(income_streams=[IncomeData('w', 'Salary', 10_000)],
        expenses=[ExpenseData('e', 'Living', 9_000, specific_funding_source_id='roth')],
        priorities=[PriorityData(1, target_account_id='roth', max_annual_amount=7_500)],
        drawdown_order=[DrawdownEntryData(1, 'cash'), DrawdownEntryData(2, 'roth')],
        tax_settings={'mode':'flat', 'ordinary_income_tax_rate':.2}),
        accounts={'roth':account(20_000, 0), 'cash':AccountInfo(0, 'checking')}, life_expectancy=47)
    row = run_simulation(p).yearly_snapshots[0]
    #10k withdrawal then7.5k regularcontribution ->2.5k earnings,250penalty.
    assert row.gross_income == pytest.approx(12_500, abs=.01)
    assert row.early_withdrawal_penalty == pytest.approx(250, abs=.01)
    assert row.taxes == pytest.approx(2_750, abs=.01)
    assert row.net_worth == pytest.approx(18_250, abs=.01)
    assert row.net_worth + row.expenses + row.taxes == pytest.approx(30_000, abs=.01)

"""Independent seam regressions: amounts, closed employers, budget coverage."""
import uuid
from copy import deepcopy
from dataclasses import asdict

import pytest

from app.routers import (
    monte_carlo,
    monte_carlo_stateless,
    simulation,
    simulation_stateless,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PriorityData,
    SEPPSettingsData,
)
from tests.engine_support import lifecycle_household


@pytest.mark.parametrize('deceased', ['self','spouse'])
def test_survivor_wages_cannot_fund_deceased_employer_plan(deceased):
    survivor='spouse' if deceased=='self' else 'self'
    p=lifecycle_household(accounts={'old_employer':AccountInfo(balance=10000,account_type='traditional_401k',owner=deceased),
        'cash':AccountInfo(balance=100000,account_type='checking',owner=survivor)},
        income_streams=[IncomeData(id='wages',name='survivor wages',owner=survivor,annual_amount=100000)],
        priorities=[PriorityData(priority_rank=1,target_account_id='old_employer',allocation_mode='amount',allocation_value=10000),
                    PriorityData(priority_rank=2,target_account_id='cash',allocation_mode='remaining',allocation_value=100)])
    if deceased=='spouse':
        p.birth_year,p.spouse_birth_year=p.spouse_birth_year,p.birth_year
        p.life_expectancy,p.spouse_life_expectancy=p.spouse_life_expectancy,p.life_expectancy
    after=next(r for r in run_simulation(p).yearly_snapshots if r.year==2027)
    assert not any(c.account_id=='old_employer' and c.amount>0 for c in after.cash_flow.contributions)


def test_explicit_pre_medicare_out_of_pocket_budget_is_counted_once():
    p=lifecycle_household(birth_year=1970,life_expectancy=60,spouse_birth_year=1972,spouse_life_expectancy=60,
        healthcare_settings={'enabled':True,'aca_enabled':False,'medicare_enabled':False,'persons':[
            {'owner':'self','mode':'coverage','aca_enabled':False,'medicare_enabled':False,'out_of_pocket_annual':2400},
            {'owner':'spouse','mode':'off'}]})
    row=run_simulation(p).yearly_snapshots[0]
    assert row.healthcare.out_of_pocket==2400
    assert row.healthcare.total==row.expenses==2400
    assert row.net_worth==pytest.approx(97600)


def test_inherited_account_successor_needs_explicit_contract():
    p=lifecycle_household(accounts={'inherited':AccountInfo(balance=100000,account_type='traditional_ira',owner='self',inherited_year=2023)})
    with pytest.raises(ValueError,match='successor'):
        run_simulation(p)


def test_survivor_claimed_amount_is_not_adjusted_again_for_claim_age():
    p=lifecycle_household(income_streams=[IncomeData(id='ss',name='Actual claimed benefit',owner='self',annual_amount=42000,is_social_security=True,is_earned_income=False,claiming_age=70,growth_rate=0)])
    p.estate_settings.survivor_social_security_policy='claimed_benefit_at_survivor_fra'
    p.estate_settings.survivor_social_security_eligibility_confirmed=True
    p.estate_settings.survivor_social_security_eligibility_source='Synthetic already-claimed award and eligibility'
    original=deepcopy(p)
    row=next(r for r in run_simulation(p).yearly_snapshots if r.year==2027)
    assert sum(i.amount for i in row.cash_flow.income_sources if i.name=='Social Security survivor top-up')==42000
    assert p==original


@pytest.mark.parametrize("deceased", ["self", "spouse"])
def test_deceased_employer_plan_rejects_employer_match_too(deceased):
    survivor = "spouse" if deceased == "self" else "self"
    p = lifecycle_household(accounts={
        "old": AccountInfo(balance=10000, account_type="roth_401k", owner=deceased),
        "cash": AccountInfo(balance=100000, account_type="checking", owner=survivor)},
        income_streams=[IncomeData(id="pay", name="Survivor pay", annual_amount=100000, owner=survivor)],
        priorities=[PriorityData(priority_rank=1, priority_type="income_percent",
            target_account_id="old", source_income_id="pay", employee_rate=.1, employer_match_rate=.05)])
    if deceased == "spouse":
        p.birth_year, p.spouse_birth_year = p.spouse_birth_year, p.birth_year
        p.life_expectancy, p.spouse_life_expectancy = p.spouse_life_expectancy, p.life_expectancy
    row = next(r for r in run_simulation(p).yearly_snapshots if r.year == 2027)
    assert row.cash_flow.payroll_deductions == 0
    assert not any(c.account_id == "old" and c.amount > 0 for c in row.cash_flow.contributions)


@pytest.mark.parametrize("budget, assumption", [(None, "unknown"), (0, "explicit"), (2400, "explicit")])
def test_oop_budget_partial_year_and_lifetime_are_independent_of_enrollment(budget, assumption):
    p = lifecycle_household(first_year_fraction=.25, healthcare_settings={"enabled": True,
        "aca_enabled": False, "medicare_enabled": False, "persons": [
        {"owner": "self", "mode": "coverage", "medicare_enabled": False,
         "out_of_pocket_annual": budget}, {"owner": "spouse", "mode": "off"}]})
    rows = run_simulation(p).yearly_snapshots
    assert rows[0].healthcare.out_of_pocket == (budget or 0) * .25
    assert rows[0].healthcare.person_costs[0]["out_of_pocket_assumption"] == assumption
    assert all(r.healthcare.out_of_pocket == 0 for r in rows[1:])


def test_inherited_account_legacy_behavior_remains_available():
    p = lifecycle_household(life_expectancy=78, accounts={"inherited": AccountInfo(
        balance=100000, account_type="traditional_ira", owner="self", inherited_year=2023)})
    p.estate_settings.household_lifecycle = "legacy_primary_endpoint"
    assert run_simulation(p).yearly_snapshots


@pytest.mark.anyio
async def test_stateless_rejects_unsupported_inherited_successor(client):
    p = lifecycle_household(accounts={'inherited': AccountInfo(balance=100000,
        account_type='traditional_ira', owner='self', inherited_year=2023)})
    response = await client.post('/api/simulate/stateless', json=asdict(p))
    assert response.status_code == 422
    assert 'successor' in response.text


async def saved_lifecycle_plan(client, p):
    created = await client.post('/api/plans', json={
        'name': 'Inherited successor contract', 'plan_type': 'FIXED_DATE',
        'start_date': f'{p.start_year}-01-01', 'birth_year': p.birth_year,
        'birth_month': p.birth_month, 'life_expectancy': p.life_expectancy,
        'filing_status': p.filing_status, 'tax_settings': p.tax_settings,
        'snapshot_conditions': {aid: asdict(account) for aid, account in p.accounts.items()},
        'estate_settings': asdict(p.estate_settings),
        'spouse': {'name': 'Survivor', 'birth_year': p.spouse_birth_year,
                   'birth_month': p.spouse_birth_month, 'life_expectancy': p.spouse_life_expectancy},
    })
    assert created.status_code == 201, created.text
    return created.json()['id']


@pytest.mark.anyio
@pytest.mark.parametrize('persisted', [False, True])
@pytest.mark.parametrize('historical', [False, True])
@pytest.mark.parametrize('inherited_year, status', [(2023, 422), (2016, 200)])
async def test_late_successor_validation_preserves_depleted_account_success(client, persisted, historical, inherited_year, status):
    account_id = str(uuid.uuid4())
    p = lifecycle_household(accounts={account_id: AccountInfo(balance=100000,
        account_type='traditional_ira', owner='self', inherited_year=inherited_year,
        inheritance_settings={'distribution_method': 'ten_year', 'decedent_died_after_rbd': False})})
    if persisted:
        pid = await saved_lifecycle_plan(client, p)
        endpoint, body = f'/api/plans/{pid}/simulate', None
    else:
        endpoint, body = '/api/simulate/stateless', asdict(p)
    if historical:
        endpoint += '?historical_start_year=2000'
    response = await client.post(endpoint, json=body)
    assert response.status_code == status, response.text
    if status == 422:
        error = response.json()['error']
        assert error['code'] == 'VALIDATION_ERROR'
        assert 'successor beneficiary' in error['message']
        assert error['details'] == [{'field': 'estate_settings.household_lifecycle', 'reason': error['message']}]
    else:
        result = response.json()
        if historical:
            result = result['simulation_result']
        rows = result['yearly_snapshots']
        assert [row['year'] for row in rows] == list(range(2026, 2031))
        assert all(row['accounts'][account_id] == 0 for row in rows)


@pytest.mark.anyio
@pytest.mark.parametrize('persisted', [False, True])
async def test_unexpected_engine_value_error_remains_500(client, monkeypatch, persisted):
    p = lifecycle_household(accounts={})
    if persisted:
        pid = await saved_lifecycle_plan(client, p)
        endpoint, body, module = f'/api/plans/{pid}/simulate', None, simulation
    else:
        endpoint, body, module = '/api/simulate/stateless', asdict(p), simulation_stateless

    def engine_bug(_plan):
        raise ValueError('Synthetic engine defect must not be reclassified as authored input')

    monkeypatch.setattr(module, 'run_simulation', engine_bug)
    response = await client.post(endpoint, json=body)
    assert response.status_code == 500
    assert response.json()['error']['code'] == 'SIMULATION_FAILED'
    assert 'Synthetic engine' not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize('persisted', [False, True])
@pytest.mark.parametrize('inherited_year, status', [(2023, 422), (2016, 200)])
async def test_monte_carlo_propagates_late_successor_input_error_from_worker(client, persisted, inherited_year, status):
    account_id = str(uuid.uuid4())
    p = lifecycle_household(accounts={account_id: AccountInfo(balance=100000,
        account_type='traditional_ira', owner='self', inherited_year=inherited_year,
        inheritance_settings={'distribution_method': 'ten_year', 'decedent_died_after_rbd': False})})
    if persisted:
        pid = await saved_lifecycle_plan(client, p)
        endpoint, body = f'/api/plans/{pid}/monte-carlo', {'n_trials': 1, 'seed': 3}
    else:
        endpoint, body = '/api/monte-carlo/stateless', {'plan': asdict(p), 'num_simulations': 1, 'seed': 3}
    response = await client.post(endpoint, json=body)
    assert response.status_code == status, response.text
    if status == 422:
        error = response.json()['error']
        assert error['code'] == 'VALIDATION_ERROR'
        assert 'successor beneficiary' in error['message']
        assert error['details'][0]['field'] == 'estate_settings.household_lifecycle'
    else:
        assert response.json()['n_trials'] == 1
        assert response.json()['percentile_curves']['years'] == list(range(2026, 2031))


@pytest.mark.anyio
@pytest.mark.parametrize('persisted', [False, True])
async def test_unexpected_monte_carlo_value_error_remains_500(client, monkeypatch, persisted):
    p = lifecycle_household(accounts={})
    if persisted:
        pid = await saved_lifecycle_plan(client, p)
        endpoint, body, module = f'/api/plans/{pid}/monte-carlo', {'n_trials': 1}, monte_carlo
    else:
        endpoint, body, module = '/api/monte-carlo/stateless', {'plan': asdict(p), 'num_simulations': 1}, monte_carlo_stateless

    def engine_bug(*args, **kwargs):
        raise ValueError('Synthetic Monte Carlo defect')

    monkeypatch.setattr(module, 'run_monte_carlo', engine_bug)
    response = await client.post(endpoint, json=body)
    assert response.status_code == 500
    assert response.json()['error']['code'] == 'SIMULATION_FAILED'
    assert 'Synthetic Monte Carlo' not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize('route', ['tax-strategies/compare', 'tax-strategies/search', 'withdrawal-strategies/compare', 'tax-suggestions'])
async def test_strategy_routes_preserve_unsupported_successor_validation(client, route):
    p = lifecycle_household(accounts={})
    pid = await saved_lifecycle_plan(client, p)
    inherited = await client.post('/api/accounts', json={'name': 'Inherited IRA', 'account_type': 'traditional_ira',
        'owner': 'self', 'balance': 100000, 'inherited_year': 2023,
        'inheritance_settings': {'distribution_method': 'ten_year', 'decedent_died_after_rbd': False}})
    assert inherited.status_code == 201, inherited.text
    source = await client.post('/api/accounts', json={'name': 'Own IRA', 'account_type': 'traditional_ira', 'balance': 10000})
    target = await client.post('/api/accounts', json={'name': 'Own Roth', 'account_type': 'roth_ira', 'balance': 0})
    assert source.status_code == target.status_code == 201
    body = ({'source_account_id': source.json()['id'], 'target_account_id': target.json()['id'], 'bracket_ceilings': [.12]}
            if route == 'tax-strategies/compare' else
            {'conversion': {'source_account_id': source.json()['id'], 'target_account_id': target.json()['id']},
             'bracket_rates': [.12]}
            if route == 'tax-strategies/search' else {'methods': ['constant_dollar'], 'monte_carlo_trials': 0}
            if route == 'withdrawal-strategies/compare' else None)
    response = await client.post(f'/api/plans/{pid}/{route}', json=body)
    assert response.status_code == 422, response.text
    error = response.json()['error']
    assert error['code'] == 'VALIDATION_ERROR'
    assert 'successor beneficiary' in error['message']
    assert error['details'][0]['field'] == 'estate_settings.household_lifecycle'


@pytest.mark.anyio
async def test_persisted_pre_medicare_oop_matches_stateless_and_preserves_null(client):
    health = {'enabled': True, 'aca_enabled': False, 'medicare_enabled': False,
        'persons': [{'owner': 'self', 'mode': 'coverage', 'medicare_enabled': False,
                     'out_of_pocket_annual': 2400},
                    {'owner': 'spouse', 'mode': 'coverage', 'medicare_enabled': False,
                     'out_of_pocket_annual': None}]}
    p = lifecycle_household(birth_year=1970, life_expectancy=60, spouse_birth_year=1972,
        spouse_life_expectancy=60, healthcare_settings=health)
    created = await client.post('/api/plans', json={'name': 'Annual OOP contract',
        'plan_type': 'FIXED_DATE', 'start_date': '2026-01-01', 'birth_year': 1970,
        'life_expectancy': 60, 'filing_status': 'married_filing_jointly'})
    assert created.status_code == 201, created.text
    pid = created.json()['id']
    response = await client.put(f'/api/plans/{pid}', json={'healthcare_settings': health,
        'spouse': {'name': 'Spouse', 'birth_year': 1972, 'birth_month': 1, 'life_expectancy': 60}})
    assert response.status_code == 200, response.text
    reread = (await client.get(f'/api/plans/{pid}')).json()
    assert reread['healthcare_settings']['persons'][1]['out_of_pocket_annual'] is None
    native = await client.post(f'/api/plans/{pid}/simulate')
    stateless = await client.post('/api/simulate/stateless', json=asdict(p))
    assert native.status_code == stateless.status_code == 200
    for result in [native.json(), stateless.json()]:
        hc = result['yearly_snapshots'][0]['healthcare']
        assert hc['out_of_pocket'] == hc['total'] == 2400
        assert hc['person_costs'][1]['out_of_pocket_assumption'] == 'unknown'


def test_primary_sepp_exemption_does_not_follow_spousal_owner_transfer():
    p = lifecycle_household(birth_year=1971, life_expectancy=55, spouse_birth_year=1980, spouse_life_expectancy=50,
        accounts={'ira': AccountInfo(balance=100000, account_type='traditional_ira', owner='self')},
        # The $6,361 SEPP payment banks only $361 of generated cash, so 2027
        # spending must reach the transferred IRA.
        expenses=[ExpenseData(id='living', name='Living', annual_amount=6000, inflation_linked=False)],
        drawdown_order=[DrawdownEntryData(source_account_id='ira', rank=1)],
        sepp_settings=SEPPSettingsData(enabled=True, source_account_id='ira', start_age=50))
    row = next(r for r in run_simulation(p).yearly_snapshots if r.year == 2027)
    assert row.early_withdrawal_penalty > 0

"""Inherited accounts: beneficiary elections, annual inherited RMDs and a complete divisor table."""
from dataclasses import replace
from datetime import date

import pytest

from app.schemas.account import AccountCreate
from coastmath.engine.rmd import calculate_inherited_ira_rmd as rmd
from coastmath.engine.simulator import run_simulation
from coastmath.engine.single_life import SINGLE_LIFE_TABLE, single_life_divisor
from coastmath.engine.types import AccountInfo
from tests.engine_support import audit_plan


def test_complete_single_life_table_and_tail():
    assert set(SINGLE_LIFE_TABLE)==set(range(121))
    assert single_life_divisor(0)==84.6
    assert single_life_divisor(19)==66
    assert single_life_divisor(101)==2.6
    assert single_life_divisor(121)==1
    with pytest.raises(ValueError):
        single_life_divisor(-1)


def test_edb_uses_initial_divisor_minus_elapsed_years_and_no_ten_year_deadline():
    # Age50 in first distribution year2025 ->36.2; year2034 uses27.2.
    assert rmd(100_000,2024,2034,beneficiary_age=59,beneficiary_type='edb')==pytest.approx(100_000/27.2)
    assert rmd(100_000,2024,2035,beneficiary_age=60,beneficiary_type='edb')==pytest.approx(100_000/26.2)


def test_spouse_recalculates_annually_or_elects_own_account():
    assert rmd(100_000,2020,2031,65,'spouse')==pytest.approx(100_000/22.9)
    assert rmd(100_000,2020,2031,65,'spouse',distribution_method='spousal_rollover')==0
    assert rmd(100_000,2020,2031,75,'spouse',distribution_method='spousal_rollover')==pytest.approx(100_000/24.6)


def test_spouse_can_delay_to_decedents_rmd_year_or_elect_ten_year_rule():
    # IRS Pub590-B example: spouse died2022 age65, would turn73 in2030.
    assert rmd(100_000,2022,2029,65,'spouse',decedent_birth_year=1957,decedent_died_after_rbd=False)==0
    assert rmd(100_000,2022,2030,66,'spouse',decedent_birth_year=1957,decedent_died_after_rbd=False)==pytest.approx(100_000/22)
    assert rmd(100_000,2022,2032,68,'spouse',distribution_method='ten_year')==100_000


def test_non_edb_after_rbd_annuals_use_prior_balance_then_deadline_uses_current():
    assert rmd(120_000,2024,2025,50,prior_year_balance=100_000,decedent_died_after_rbd=True)==pytest.approx(100_000/36.2)
    assert rmd(120_000,2024,2026,51,prior_year_balance=100_000,decedent_died_after_rbd=True)==pytest.approx(100_000/35.2)
    assert rmd(120_000,2024,2034,59,prior_year_balance=100_000,decedent_died_after_rbd=True)==120_000
    assert rmd(120_000,2024,2025,50,decedent_died_after_rbd=False)==0
    assert rmd(120_000,2024,2025,50,decedent_died_after_rbd=True,is_roth=True)==0


def test_after_rbd_uses_longer_decedent_life_and_applies_relief():
    # Decedent80 in2024 has11.2 less1; older beneficiary90 has5.7.
    assert rmd(102_000,2024,2025,90,decedent_died_after_rbd=True,decedent_birth_year=1944)==10_000
    assert rmd(100_000,2020,2024,50,decedent_died_after_rbd=True)==0


def test_minor_child_deadline_begins_at_age_twenty_one():
    assert rmd(100_000,2024,2035,25,'edb',beneficiary_is_minor_child=True)<100_000
    assert rmd(100_000,2024,2041,31,'edb',beneficiary_is_minor_child=True)==100_000


def test_actual_inherited_distribution_reaches_tax_and_cash():
    p=replace(audit_plan(),birth_year=1976,life_expectancy=52,accounts={
        'ira':AccountInfo(100_000,'traditional_ira',inherited_year=2025,
            inheritance_settings={'decedent_died_after_rbd':True,'decedent_birth_year':1940})})
    first=run_simulation(p).yearly_snapshots[0]
    assert first.gross_income==pytest.approx(100_000/36.2)
    assert first.accounts['ira']==pytest.approx(100_000-100_000/36.2)
    assert first.early_withdrawal_penalty==0


def test_nonretirement_inheritance_and_invalid_elections():
    assert AccountCreate(name='Brokerage',account_type='taxable_brokerage',inherited_year=2020).inherited_year is None
    with pytest.raises(ValueError,match='spouse'):
        AccountCreate(name='IRA',account_type='traditional_ira',inherited_year=2024,
            inheritance_settings={'distribution_method':'spousal_rollover'})


@pytest.mark.anyio
async def test_inheritance_settings_persist_and_partial_updates_validate_saved_context(client):
    response=await client.post('/api/accounts',json={'name':'Inherited IRA','account_type':'traditional_ira',
        'balance':100_000,'inherited_year':2024,'beneficiary_type':'spouse',
        'inheritance_settings':{'distribution_method':'life_expectancy','decedent_birth_year':1940,'decedent_died_after_rbd':True}})
    assert response.status_code==201,response.text
    url=f"/api/accounts/{response.json()['id']}"
    assert (await client.put(url,json={'balance':110_000})).json()['inheritance_settings']['decedent_birth_year']==1940
    rejected=await client.put(url,json={'inheritance_settings':{'distribution_method':'life_expectancy'},'beneficiary_type':'non_edb'})
    assert rejected.status_code==422
    assert (await client.get('/api/accounts')).json()[0]['beneficiary_type']=='spouse'
    changed=await client.put(url,json={'account_type':'taxable_brokerage'})
    assert changed.json()['inherited_year'] is None and changed.json()['inheritance_settings'] is None


@pytest.mark.anyio
async def test_original_owner_death_year_cannot_be_in_the_future(client):
    """An inherited account's original owner has already died."""
    future = date.today().year + 1
    created = await client.post('/api/accounts', json={'name': 'Inh IRA', 'account_type': 'traditional_ira',
                                                       'balance': 50_000, 'inherited_year': future})
    assert created.status_code == 422, created.text
    assert "Year original owner died can't be after" in created.text, created.text
    saved = await client.post('/api/accounts', json={'name': 'Inh IRA', 'account_type': 'traditional_ira',
                                                     'balance': 50_000, 'inherited_year': date.today().year})
    assert saved.status_code == 201, saved.text
    updated = await client.put(f"/api/accounts/{saved.json()['id']}", json={'inherited_year': 2090})
    assert updated.status_code == 422, updated.text

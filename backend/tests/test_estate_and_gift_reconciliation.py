"""Estate tax, inherited distributions and charitable gifts reconciled against independent calculations."""
from dataclasses import replace

import pytest

from coastmath.engine.estate_tax import calculate_estate_breakdown
from coastmath.engine.simulator import _process_charitable_contributions, run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    CharityData,
    EstateSettingsData,
    PlanData,
    SimState,
)


def plan(**kwargs):
    return PlanData(plan_id='00000000-0000-0000-0000-000000000001',birth_year=1980,
        start_year=2029,filing_status='single',life_expectancy=52,
        assumptions=AssumptionData(inflation_rate=0,stock_growth_rate=0),**kwargs)


@pytest.mark.parametrize('estate,ird,expected', [(20_000_000,2_000_000,800_000),(16_000_000,2_000_000,400_000)])
def test_691c_marginal_tax_with_and_without_ird(estate,ird,expected):
    settings=EstateSettingsData(heir_income_tax_rate=.24)
    result=calculate_estate_breakdown(estate,0,settings,year=2026,pretax_balance=ird)
    assert result.heir_income_tax_deduction_691c == pytest.approx(expected)
    assert result.heir_income_tax == pytest.approx((ird-expected)*.24)


def test_taxable_inheritance_has_no_retirement_distribution_deadline():
    p=plan(accounts={'brokerage':AccountInfo(500_000,'taxable_brokerage',cost_basis=200_000,inherited_year=2020)})
    inherited=run_simulation(p).yearly_snapshots
    ordinary=run_simulation(replace(p,accounts={'brokerage':AccountInfo(500_000,'taxable_brokerage',cost_basis=200_000)})).yearly_snapshots
    assert [s.net_worth for s in inherited] == [s.net_worth for s in ordinary]
    assert all(s.capital_gains_tax == 0 for s in inherited)


def test_daf_carryforward_cannot_exceed_funded_gift():
    p=plan(charity_entities=[CharityData('direct','Direct','direct',50_000),CharityData('daf','DAF','daf',50_000)])
    state=SimState(year=2029,accounts={'cash':AccountInfo(60_000,'checking')})
    result=_process_charitable_contributions(state,p,0,[])
    assert result.entity_outflows == [('Direct',50_000),('DAF',10_000)]
    assert result.preserved_carryforward == [(2029,10_000)]
    assert result.committed_carryforward == [(2029,10_000)]


def test_hsa_is_income_to_nonspouse_heir_and_remains_hsa_for_spouse():
    p=plan(accounts={'hsa':AccountInfo(100_000,'hsa')},estate_settings=EstateSettingsData(heir_income_tax_rate=.24))
    estate=run_simulation(p).metadata.net_legacy
    assert estate.pretax_balance == 100_000
    assert estate.heir_income_tax == 24_000
    spouse=run_simulation(replace(p,spouse_birth_year=1980,spouse_life_expectancy=90)).metadata.net_legacy
    assert spouse.heir_income_tax == 0


def test_estate_exemption_uses_calendar_sampled_inflation_and_rounding():
    p=replace(plan(accounts={'cash':AccountInfo(20_000_000,'checking')}),start_year=2026,life_expectancy=49)
    # Death at end2028: inflation2026=.0123 then2027=.0234; final year's
    # inflation must not be applied to this year's exemption.
    result=run_simulation(p,override_returns={2026:(0,0,.0123),2027:(0,0,.0234),2028:(0,0,.5)})
    # 15,000,000*1.0123*1.0234 = 15,539,817.30; IRC 2010(c)(3)(B) rounds to
    # the nearest $10,000, not down.
    expected=15_540_000
    assert result.metadata.net_legacy.federal_exemption == expected


def test_partner_dsue_keeps_first_death_exemption():
    result=calculate_estate_breakdown(40_000_000,0,EstateSettingsData(),2030,
        partner_death_year=2028,calendar_inflation={2028:1.1,2030:1.3})
    assert result.dsue_amount == 16_500_000
    assert result.federal_exemption == 19_500_000

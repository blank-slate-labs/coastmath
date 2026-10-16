"""Calendar-year earnings tests respect paid versus imputed opening history."""
from dataclasses import replace

import pytest

from coastmath.engine.household_lifecycle import LAST_SURVIVOR
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import EstateSettingsData, IncomeData
from tests.engine_support import source, ytd_household
from tests.ss_household_support import couple, pia_ss, plan


def benefits():
    return [IncomeData(id='salary', name='Salary', annual_amount=34480, growth_rate=0),
            IncomeData(id='ss', name='Social Security', annual_amount=24000, growth_rate=0,
                       claiming_age=62, is_social_security=True, is_earned_income=False,
                       tax_category='social_security')]


@pytest.mark.parametrize('fraction', [.75, .5, .25])
def test_imputed_lower_test_uses_full_year_earnings_and_payable_history(fraction):
    common = dict(birth_year=1963, life_expectancy=75, income_streams=benefits())
    partial = run_simulation(ytd_household(**common, first_year_fraction=fraction)).yearly_snapshots[0]
    full = run_simulation(ytd_household(**common, first_year_fraction=1)).yearly_snapshots[0]
    assert full.ss_earnings_test_withheld == pytest.approx(5000)
    assert partial.ss_earnings_test_withheld == pytest.approx(5000 * fraction)
    assert partial.gross_income == pytest.approx((34480 + 19000) * fraction)
    assert partial.calendar_year_gross_income == pytest.approx(53480)
    assert partial.federal_tax == pytest.approx(full.federal_tax)
    assert partial.fica_tax == pytest.approx(full.fica_tax)
    assert partial.accounts['cash'] == pytest.approx(100000 + partial.cash_flow.gross_income + partial.cash_flow.tax_delta)


@pytest.mark.parametrize(('fraction', 'post_ss', 'post_withheld'), [(.75, 14142.35294117647, 4140), (.25, 6141.176470588235, 0)])
def test_fra_year_imputed_openings_before_and_after_fra(fraction, post_ss, post_withheld):
    streams = benefits()
    streams[0].annual_amount = 180000
    # September 1959 birth: retirement FRA 66y10m is July 2026.
    common = dict(birth_year=1959, birth_month=9, life_expectancy=75, income_streams=streams)
    partial = run_simulation(ytd_household(**common, first_year_fraction=fraction)).yearly_snapshots[0]
    full = run_simulation(ytd_household(**common, first_year_fraction=1)).yearly_snapshots[0]
    assert full.ss_earnings_test_withheld == pytest.approx(8280)
    assert partial.ss_earnings_test_withheld == pytest.approx(post_withheld)
    # Four fully withheld months raise the factor .708333... to .725 at FRA.
    assert partial.gross_income == pytest.approx(180000 * fraction + post_ss)
    assert partial.calendar_year_gross_income == pytest.approx(196002.35294117647)
    assert partial.federal_tax == pytest.approx(full.federal_tax)
    assert partial.fica_tax == pytest.approx(full.fica_tax)
    assert partial.accounts['cash'] == pytest.approx(100000 + partial.cash_flow.gross_income + partial.cash_flow.tax_delta)


def test_explicit_paid_ytd_is_not_rewritten_after_fra():
    streams = benefits()
    streams[0].annual_amount = 180000
    partial = run_simulation(ytd_household(birth_year=1959, birth_month=9, life_expectancy=75,
        income_streams=streams, first_year_fraction=.25,
        tax_settings={'year_to_date':{'tax_year':2026, 'gross_income':135000,
            'w2_income_by_owner':{'self':135000}, 'social_security_income':1000, 'tax_paid':0}})).yearly_snapshots[0]
    assert partial.ss_earnings_test_withheld == 0
    assert partial.gross_income == pytest.approx(51000)
    assert partial.calendar_year_gross_income == pytest.approx(187000)
    assert partial.warnings == []
    assert partial.accounts['cash'] == pytest.approx(100000 + partial.cash_flow.gross_income + partial.cash_flow.tax_delta)


def test_explicit_ytd_wages_count_toward_annual_exempt_amount():
    partial = run_simulation(ytd_household(birth_year=1963, life_expectancy=75,
        income_streams=benefits(), first_year_fraction=.5,
        tax_settings={'year_to_date':{'tax_year':2026, 'gross_income':17240,
            'w2_income_by_owner':{'self':17240}, 'social_security_income':12000, 'tax_paid':0}})).yearly_snapshots[0]
    assert partial.ss_earnings_test_withheld == pytest.approx(5000)
    assert partial.gross_income == pytest.approx(24240)
    assert partial.calendar_year_gross_income == pytest.approx(53480)
    assert partial.warnings == []


@pytest.mark.parametrize('fraction', [.75, .25])
@pytest.mark.parametrize('survivor_birth', [1959, 1960])
def test_survivor_only_imputed_calendar_year_matches_full(fraction, survivor_birth):
    deceased = IncomeData(id='deceased', name='Deceased', annual_amount=24000,
        growth_rate=0, tax_category='social_security', owner='self', claiming_age=67)
    salary = IncomeData(id='salary', name='Salary', annual_amount=240000,
        growth_rate=0, tax_category='employment', owner='spouse')
    p = couple(start_year=2026, birth_year=1954, life_expectancy=71,
        spouse_birth_year=survivor_birth, spouse_birth_month=9, spouse_life_expectancy=75,
        estate_settings=EstateSettingsData(household_lifecycle=LAST_SURVIVOR,
            survivor_social_security_policy='claimed_benefit_at_survivor_fra',
            survivor_social_security_eligibility_confirmed=True,
            survivor_social_security_eligibility_source='Synthetic eligibility confirmation'),
        income_streams=[deceased, salary])
    full = run_simulation(replace(p, first_year_fraction=1)).yearly_snapshots[0]
    partial = run_simulation(replace(p, first_year_fraction=fraction)).yearly_snapshots[0]
    assert partial.calendar_year_gross_income == pytest.approx(full.calendar_year_gross_income)
    assert partial.federal_tax == pytest.approx(full.federal_tax)
    if survivor_birth == 1960:
        assert partial.gross_income == pytest.approx(full.gross_income * fraction)
    actual = run_simulation(replace(p, first_year_fraction=fraction, tax_settings={
        'year_to_date': {'tax_year':2026, 'gross_income':240000 * (1-fraction),
            'w2_income_by_owner':{'spouse':240000 * (1-fraction)},
            'social_security_income':1234, 'tax_paid':0}})).yearly_snapshots[0]
    assert actual.calendar_year_gross_income == pytest.approx(actual.gross_income + 240000 * (1-fraction) + 1234)
    assert actual.warnings == []


@pytest.mark.parametrize('explicit', [False, True])
def test_first_completed_covered_year_includes_opening_earnings(explicit):
    salary = IncomeData(id='salary', name='Salary', annual_amount=100000,
        growth_rate=0, tax_category='employment')
    p = plan(birth_year=1963, income_streams=[salary,
        pia_ss('self', 1000, 67, pia_reflects='current_record', covered_years_to_date=20)])
    settings = {'year_to_date': {'tax_year':2026, 'gross_income':50000,
        'w2_income_by_owner':{'self':50000}, 'tax_paid':0}} if explicit else p.tax_settings
    full = run_simulation(replace(p, first_year_fraction=1))
    partial = run_simulation(replace(p, first_year_fraction=.5, tax_settings=settings))
    assert source(partial, 2030, 'self SS') == pytest.approx(source(full, 2030, 'self SS'))

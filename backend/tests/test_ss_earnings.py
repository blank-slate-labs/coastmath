"""Independent retirement earnings-test and covered-record checks."""
from dataclasses import replace

import pytest

from coastmath.engine.household_lifecycle import LAST_SURVIVOR
from coastmath.engine.simulator import run_simulation
from coastmath.engine.ss_earnings import (
    CoveredRecords,
    aime_from_pia,
    earnings_test_due,
    pia_from_aime,
)
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    EstateSettingsData,
    IncomeData,
    MilestoneData,
    PlanData,
)
from tests.engine_support import source
from tests.ss_household_support import couple, pia_ss, plan


def wage(amount=100_000, **kw):
    return IncomeData(id='work', name='Work', annual_amount=amount, growth_rate=0, tax_category='employment', **kw)


def row(result, year):
    return next(s for s in result.yearly_snapshots if s.year == year)


@pytest.mark.parametrize('aime', [0, 500, 1286, 4000, 7749, 12000])
def test_aime_inversion(aime):
    assert aime_from_pia(pia_from_aime(aime, (1286, 7749)), (1286, 7749)) == pytest.approx(aime)


@pytest.mark.parametrize(('earned', 'withheld'), [(24480, 0), (34480, 5000)])
def test_lower_limit(earned, withheld):
    result = run_simulation(plan(birth_year=1963, income_streams=[pia_ss('self', 2000, 62), wage(earned)]))
    assert row(result, 2026).ss_earnings_test_withheld == pytest.approx(withheld)
    assert row(result, 2026).cash_flow.gross_income == pytest.approx(earned + 16800 - withheld)


def test_fra_year_and_after():
    benefit = pia_ss('self', 2000, 62)
    p = plan(birth_year=1959, birth_month=9, income_streams=[benefit, wage(120_000)])
    assert row(run_simulation(p), 2026).ss_earnings_test_withheld == 0
    result = run_simulation(replace(p, income_streams=[benefit, wage(180_000)]))
    assert row(result, 2026).ss_earnings_test_withheld == pytest.approx((90000 - 65160) / 3)
    assert row(result, 2027).ss_earnings_test_withheld == 0


def test_arf_credit():
    result = run_simulation(plan(birth_year=1964, income_streams=[pia_ss('self', 2000, 62), wage()]))
    assert source(result, 2031, 'self SS') == pytest.approx(24000)
    assert row(result, 2031).ss_earnings_test_withheld == 0


def test_grace_year():
    end = MilestoneData(id='end', name='Retire', trigger_type='date', trigger_date='2026-06-01')
    result = run_simulation(plan(birth_year=1964, birth_month=7, milestones=[end], income_streams=[pia_ss('self', 2000, 62), wage(200_000, end_milestone_id='end')]))
    assert row(result, 2026).ss_earnings_test_withheld == 0
    assert source(result, 2026, 'self SS') == pytest.approx(8400)


@pytest.mark.parametrize('years', [1, 20, 35])
def test_no_future_earnings_preserves_pia(years):
    p = plan(income_streams=[pia_ss('self', 2000, 67, pia_reflects='current_record', covered_years_to_date=years)])
    records = CoveredRecords(p, lambda y: 1)
    records.add_year(2026, {}, {})
    assert records.adjusted_plan().income_streams[0].pia_monthly == pytest.approx(2000)


@pytest.mark.parametrize('years', [20, 35])
def test_high_future_year(years):
    p = plan(income_streams=[pia_ss('self', 1000, 67, pia_reflects='current_record', covered_years_to_date=years)])
    records = CoveredRecords(p, lambda y: 1)
    records.add_year(2026, {'self':184500}, {})
    assert records.adjusted_plan().income_streams[0].pia_monthly > 1000


def test_future_year_uses_entered_pia_wage_level():
    # Born 1996, plan start 2026: the entered PIA is at the 2024 wage level
    # (2026 bend points). AIME = 1,000 / 0.9 = 1,111.11; 2026 wages of 40,000
    # are 40,000 / 1.03^2 = 37,703.84 at that level, adding 89.77, so AIME =
    # 1,200.88 (below 1,286) and PIA = 0.9 x 1,200.88 = 1,080.79.
    p = plan(birth_year=1996, income_streams=[pia_ss('self', 1000, 67, pia_reflects='current_record', covered_years_to_date=8)])
    records = CoveredRecords(p, lambda y: 1.03 ** (y - 2024))
    records.add_year(2026, {'self': 40_000}, {})
    assert records.adjusted_plan().income_streams[0].pia_monthly == pytest.approx(0.9 * (1000 / 0.9 + 40_000 / 1.03 ** 2 / 420))


def test_spousal_recomputation():
    streams = [pia_ss('self', 3000, 67, pia_reflects='current_record', covered_years_to_date=20), pia_ss('spouse', 500, 67), wage(184500)]
    result = run_simulation(couple(income_streams=streams))
    baseline = run_simulation(couple(income_streams=[replace(i, pia_reflects='continued_work') for i in streams]))
    assert source(result, 2033, 'spouse SS (spousal)') > source(baseline, 2033, 'spouse SS (spousal)')


def test_wage_indexed_limit():
    assert earnings_test_due(2027, 2040*12, 30000, lambda y: 1.1 ** (y-2024)) == pytest.approx((30000-26880)/2)


def test_survivor_without_own_stream_is_subject_to_earnings_test():
    deceased = IncomeData(id='deceased', name='Deceased', annual_amount=24000, growth_rate=0, tax_category='social_security', owner='self', claiming_age=67)
    p = couple(start_year=2022, birth_year=1950, life_expectancy=71,
        spouse_birth_year=1956, spouse_birth_month=1, spouse_life_expectancy=70,
        estate_settings=EstateSettingsData(household_lifecycle=LAST_SURVIVOR,
            survivor_social_security_policy='claimed_benefit_at_survivor_fra',
            survivor_social_security_eligibility_confirmed=True,
            survivor_social_security_eligibility_source='Synthetic eligibility confirmation'),
        income_streams=[deceased, wage(240000, owner='spouse')])
    result = run_simulation(p)
    # Survivor FRA is 66; retirement earnings-test FRA is 66y4m.
    assert row(result, 2022).ss_earnings_test_withheld == pytest.approx(8000)
    assert source(result, 2022, 'Social Security survivor top-up') == pytest.approx(16000)
    assert row(result, 2023).ss_earnings_test_withheld == 0


def test_fra_month_credit_does_not_increase_pre_fra_withholding_cap():
    p = plan(birth_year=1960, birth_month=7, income_streams=[pia_ss('self', 2000, 62), wage(240000)])
    result = run_simulation(p)
    assert row(result, 2026).ss_earnings_test_withheld == pytest.approx(16800)
    assert row(result, 2027).ss_earnings_test_withheld == pytest.approx(8400)
    # 18 credited months: effective claim at 63y6m, 77.5% of PIA.
    assert source(result, 2027, 'self SS') == pytest.approx(9300)
    assert source(result, 2028, 'self SS') == pytest.approx(18600)


def test_covered_earnings_cap_and_self_employment_factor():
    p = plan(income_streams=[pia_ss('self', 1000, 67, pia_reflects='current_record', covered_years_to_date=20)])
    capped = CoveredRecords(p, lambda y: 1)
    huge = CoveredRecords(p, lambda y: 1)
    capped.add_year(2026, {'self':184500}, {})
    huge.add_year(2026, {'self':1_000_000}, {})
    assert huge.adjusted_plan().income_streams[0].pia_monthly == capped.adjusted_plan().income_streams[0].pia_monthly
    se = CoveredRecords(p, lambda y: 1)
    wages = CoveredRecords(p, lambda y: 1)
    se.add_year(2026, {}, {'self':100000})
    wages.add_year(2026, {'self':92350}, {})
    assert se.adjusted_plan().income_streams[0].pia_monthly == wages.adjusted_plan().income_streams[0].pia_monthly


def test_auxiliary_withholding_is_proportional_to_worker_record():
    p = couple(birth_year=1963, spouse_birth_year=1963, income_streams=[pia_ss('self', 3000, 62), pia_ss('spouse', 500, 62), wage(34480)])
    result = run_simulation(p)
    assert row(result, 2026).ss_earnings_test_withheld == pytest.approx(5000)
    own = source(result, 2026, 'self SS')
    auxiliary = source(result, 2026, 'spouse SS (spousal)')
    assert own / auxiliary == pytest.approx(25200 / 7800)


@pytest.mark.parametrize(('worker_claim', 'annual_survivor'), [(66, 48000), (62, 39600)])
def test_survivor_arf_and_own_offset_preserve_household_entitlement(worker_claim, annual_survivor):
    p = couple(birth_year=1945, life_expectancy=80,
        spouse_birth_year=1960, spouse_birth_month=1, spouse_life_expectancy=75,
        estate_settings=EstateSettingsData(household_lifecycle=LAST_SURVIVOR,
            survivor_social_security_policy='claimed_benefit_at_survivor_fra',
            survivor_social_security_eligibility_confirmed=True,
            survivor_social_security_eligibility_source='Synthetic eligibility confirmation'),
        income_streams=[pia_ss('self', 4000, worker_claim), pia_ss('spouse', 2000, 62), wage(244480, owner='spouse')])
    result = run_simulation(p)
    assert source(result, 2026, 'spouse SS') == 0
    assert source(result, 2026, 'Social Security survivor top-up') == 0
    assert source(result, 2027, 'spouse SS') == pytest.approx(18000)
    total = source(result, 2027, 'spouse SS') + source(result, 2027, 'Social Security survivor top-up')
    # A deceased early claim retains the statutory 82.5% worker-PIA cap.
    assert total == pytest.approx(annual_survivor)


def test_same_year_survivor_and_own_arf_do_not_overpay_after_retirement_fra():
    p = couple(birth_year=1945, life_expectancy=80,
        spouse_birth_year=1960, spouse_birth_month=7, spouse_life_expectancy=75,
        estate_settings=EstateSettingsData(household_lifecycle=LAST_SURVIVOR,
            survivor_social_security_policy='claimed_benefit_at_survivor_fra',
            survivor_social_security_eligibility_confirmed=True,
            survivor_social_security_eligibility_source='Synthetic eligibility confirmation'),
        income_streams=[pia_ss('self', 4000, 66), pia_ss('spouse', 2000, 62), wage(1000000, owner='spouse')])
    result = run_simulation(p)
    assert source(result, 2027, 'spouse SS') == pytest.approx(9300)
    assert source(result, 2027, 'Social Security survivor top-up') == pytest.approx(14700)


@pytest.mark.parametrize('kind', ['age', 'date'])
def test_grace_year_after_claim_year_protects_non_service_months(kind):
    """20 CFR 404.435: the grace year is the first year with a non-service month.

    Born July 1966 (FRA July 2033), claims at 62 (Aug 2028) while earning
    $200,000, retires July 2030. 2028-2029 have no non-service month, so all
    benefits are withheld. 2030 is the grace year: Jan-Jun benefits ($12,000)
    are withheld, Jul-Dec are paid. Withheld months 5 + 12 + 6 = 23, so after
    FRA 24,000 * (1 - 36 * 5/900) / 0.70 = 27,428.57.
    """
    ret = (MilestoneData('ret', 'Retirement', 'age', trigger_value=64) if kind == 'age'
           else MilestoneData('ret', 'Retirement', 'date', trigger_date='2030-07-01'))
    result = run_simulation(PlanData(plan_id='00000000-0000-4000-8000-000000000002', birth_year=1966,
        birth_month=7, filing_status='single', life_expectancy=70, start_year=2026, state_code='FL',
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0),
        accounts={'chk': AccountInfo(500000, 'checking', name='chk')},
        drawdown_order=[DrawdownEntryData(1, 'chk')], milestones=[ret],
        income_streams=[
            IncomeData(id='job', name='Salary', annual_amount=200000, end_milestone_id='ret', is_earned_income=True),
            IncomeData(id='ss', name='Social Security', annual_amount=24000, is_social_security=True,
                       is_earned_income=False, tax_category='social_security', claiming_age=62)],
        expenses=[], tax_settings={'cash_flow_frequency': 'annual'}))
    assert source(result, 2029, 'Social Security') == pytest.approx(0)
    assert row(result, 2030).ss_earnings_test_withheld == pytest.approx(12000)
    assert source(result, 2030, 'Social Security') == pytest.approx(12000)
    assert source(result, 2034, 'Social Security') == pytest.approx(24000 * 0.8 / 0.7, abs=0.01)

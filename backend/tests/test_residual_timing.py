"""Independent regressions for the verified residual timing findings."""
from datetime import date

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    DrawdownEntryData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
)


def plan(**changes):
    values = dict(plan_id='00000000-0000-0000-0000-000000000001', birth_year=1951, start_year=2026,
        life_expectancy=76, filing_status='single', milestones=[], income_streams=[],
        expenses=[], priorities=[], accounts={}, drawdown_order=[],
        assumptions=AssumptionData(stock_growth_rate=0, inflation_rate=0),
        tax_settings={'mode': 'flat', 'ordinary_income_tax_rate': 0})
    values.update(changes)
    return PlanData(**values)


@pytest.mark.parametrize('rate', [-.10, 0, .06])
@pytest.mark.parametrize('fraction', [1, 114 / 365])
@pytest.mark.parametrize('frequency', ['monthly', 'annual'])
def test_rmd_forfeits_only_growth_after_distribution(rate, fraction, frequency):
    opening = 246000
    rmd = opening / 24.6  # IRS Uniform Lifetime Table, age 75; prior Dec 31.
    row = run_simulation(plan(first_year_fraction=fraction,
        accounts={'401k': AccountInfo(opening, 'traditional_401k')},
        assumptions=AssumptionData(stock_growth_rate=rate, inflation_rate=0),
        tax_settings={'mode': 'flat', 'ordinary_income_tax_rate': 0,
                      'withdrawal_cash_flow_frequency': frequency})).yearly_snapshots[0]
    months = max(1, round(12 * fraction))
    factor = sum((1 + rate) ** (k / 12) for k in range(months)) / months - 1 if frequency == 'monthly' else 0
    expected = opening * (1 + rate) ** fraction - rmd * (1 + factor)
    assert row.accounts['401k'] == pytest.approx(expected, abs=.01)
    assert row.accounts['unallocated_cash'] == pytest.approx(rmd, abs=.01)
    assert row.net_worth == pytest.approx(expected + rmd, abs=.01)
    assert row.net_worth == pytest.approx(sum(row.accounts.values()), abs=.01)


def test_default_social_security_takes_31_full_january_steps():
    fraction = (date(2027, 1, 1) - date(2026, 9, 9)).days / 365
    data = plan(birth_year=1990, life_expectancy=68, first_year_fraction=fraction,
        milestones=[MilestoneData('claim', 'Claim', 'date', trigger_date='2057-01-01')],
        income_streams=[IncomeData('ss', 'Social Security', 36000,
            start_milestone_id='claim', is_social_security=True, is_earned_income=False)],
        assumption_curves=[AssumptionCurveData('social_security_cola', fixed_rate=.024)])
    row = next(s for s in run_simulation(data).yearly_snapshots if s.year == 2057)
    benefit = next(x.amount for x in row.cash_flow.income_sources if x.name == 'Social Security')
    assert benefit == pytest.approx(36000 * 1.024 ** 31, abs=.005)
    assert round(benefit, 2) == 75093.29


def test_refund_fills_unfunded_amount_priorities_before_remaining():
    # A pretax contribution creates a $2,000 refund after the first waterfall.
    # Fixed cash goals have first call on that refund, in their existing rank.
    data = plan(birth_year=1960, life_expectancy=67,
        accounts={'401k': AccountInfo(0, 'traditional_401k'),
                  'cash': AccountInfo(0, 'checking'),
                  'reserve': AccountInfo(0, 'savings'),
                  'broker': AccountInfo(0, 'taxable_brokerage', cost_basis=0)},
        income_streams=[IncomeData('pay', 'Pay', 20000, growth_rate=0)],
        priorities=[PriorityData(1, '401k', allocation_mode='amount', allocation_value=10000),
                    PriorityData(2, 'cash', max_annual_amount=6500, allocation_mode='amount', allocation_value=7000),
                    PriorityData(3, 'reserve', allocation_mode='amount', allocation_value=500),
                    PriorityData(4, 'broker')],
        drawdown_order=[DrawdownEntryData(1, 'cash')],
        tax_settings={'mode': 'flat', 'ordinary_income_tax_rate': .2})
    row = run_simulation(data).yearly_snapshots[0]
    assert row.accounts['401k'] == pytest.approx(10000, abs=.01)
    assert row.accounts['cash'] == pytest.approx(6500, abs=.01)
    assert row.accounts['reserve'] == pytest.approx(500, abs=.01)
    assert row.accounts['broker'] == pytest.approx(1000, abs=.01)
    assert row.net_worth == pytest.approx(18000, abs=.01)
    assert row.taxes == pytest.approx(2000, abs=.01)
    goals = {f.priority_rank: f for f in row.cash_flow.contributions if f.source == 'priority'}
    assert goals[2].requested_amount == 7000


@pytest.mark.parametrize('rate', [-.10, .06])
@pytest.mark.parametrize('kind', ['traditional_ira', 'roth_ira'])
def test_final_inherited_distribution_empties_account_under_monthly_cadence(rate, kind):
    data = plan(start_year=2030, birth_year=1960, life_expectancy=71,
        accounts={'inherited': AccountInfo(100000, kind, inherited_year=2020)},
        assumptions=AssumptionData(stock_growth_rate=rate, inflation_rate=0))
    row = run_simulation(data).yearly_snapshots[0]
    factor = sum((1 + rate) ** (k / 12) for k in range(12)) / 12 - 1
    distribution = 100000 * (1 + rate) / (1 + factor)
    assert row.accounts['inherited'] == pytest.approx(0, abs=.01)
    assert row.accounts['unallocated_cash'] == pytest.approx(distribution, abs=.01)


@pytest.mark.parametrize('fraction', [1, .5])
def test_refund_pretax_feedback_respects_prorated_request(fraction):
    data = plan(birth_year=1960, life_expectancy=67, first_year_fraction=fraction,
        accounts={'401k': AccountInfo(0, 'traditional_401k'), 'cash': AccountInfo(0, 'checking')},
        income_streams=[IncomeData('pay', 'Pay', 20000, growth_rate=0)],
        priorities=[PriorityData(1, '401k', allocation_mode='amount', allocation_value=19000),
                    PriorityData(2, 'cash')],
        # This regression isolates prorated contribution requests from the
        # separate midyear missing-history default.
        tax_settings={'mode': 'flat', 'ordinary_income_tax_rate': .2,
                      'year_to_date': {'tax_year': 2026}})
    row = run_simulation(data).yearly_snapshots[0]
    assert row.accounts['401k'] == pytest.approx(19000 * fraction, abs=.01)
    assert row.accounts['cash'] == pytest.approx(800 * fraction, abs=.01)
    assert row.taxes == pytest.approx(200 * fraction, abs=.01)

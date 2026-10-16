"""Ordinary Schedule SE, independently calculated expectations.

IRS Schedule SE lines 4a-4c, 8-13 and Form 8959. Profit is before SE tax.
"""
import uuid

import pytest

from coastmath.engine.tax_engine import (
    calculate,
    calculate_fica_tax,
    calculate_household_fica_tax,
    calculate_mixed_fica_tax,
)


@pytest.mark.parametrize('profit,expected', [(0, 0), (-100, 0), (400, 0), (433, 0), (434, 61.322247), (12000, 1695.546)])
def test_ordinary_se_profit_adjustment_and_floor(profit, expected):
    single = calculate_fica_tax(profit, 'single', is_self_employed=True)
    mixed = calculate_mixed_fica_tax(0, profit, 'single')
    assert single['total_fica'] == pytest.approx(expected)
    assert mixed['total_fica'] == pytest.approx(expected)
    assert mixed['se_employer_half'] == pytest.approx(expected / 2)


@pytest.mark.parametrize('wages,ss', [(0, 1374.168), (180000, 11718), (200000, 11439)])
def test_per_worker_shared_base_and_adjusted_medicare(wages, ss):
    tax = calculate_mixed_fica_tax(wages, 12000, 'single')
    assert tax['social_security_tax'] == pytest.approx(ss)
    assert tax['medicare_tax'] == pytest.approx(wages * .0145 + 321.378)
    assert tax['additional_medicare_tax'] == pytest.approx(max(0, wages + 11082 - 200000) * .009)
    result = calculate(gross_income=wages + 12000, deductions=0, filing_status='single',
                       w2_income=wages, self_employment_income=12000)
    assert result.agi == pytest.approx(wages + 12000 - tax['se_employer_half'])


def test_household_caps_and_additional_medicare():
    tax = calculate_household_fica_tax({'self': 180000, 'spouse': 100000}, {'self': 12000, 'spouse': 12000}, 'married_filing_jointly')
    assert tax['social_security_tax'] == pytest.approx(19292.168)
    assert tax['medicare_tax'] == pytest.approx(4702.756)
    assert tax['additional_medicare_tax'] == pytest.approx(469.476)
    assert tax['se_employer_half'] == pytest.approx(1287.462)
    # Two small businesses held by different spouses do not cross the SE floor together.
    small = calculate_household_fica_tax({'self': 260000}, {'self': 300, 'spouse': 300}, 'married_filing_jointly')
    assert small['se_employer_half'] == 0
    assert small['additional_medicare_tax'] == 90


@pytest.mark.parametrize('path', ['db', 'stateless'])
@pytest.mark.parametrize('partial', [False, True])
@pytest.mark.anyio
async def test_report_payroll_through_both_request_paths(client, path, partial):
    fraction = 116 / 365 if partial else 1
    incomes = [
        {'name': 'Salary', 'annual_amount': 100000, 'growth_rate': 3, 'owner': 'self'},
        {'name': 'Spouse Salary', 'annual_amount': 60000, 'growth_rate': 3, 'owner': 'spouse'},
        {'name': 'Consulting', 'annual_amount': 12000, 'growth_rate': 0, 'owner': 'self', 'is_self_employed': True},
    ]
    if path == 'db':
        created = await client.post('/api/plans', json={'name': 'SE audit', 'birth_year': 1990,
            'filing_status': 'married_filing_jointly', 'plan_type': 'FIXED_DATE',
            'start_date': '2026-09-07' if partial else '2026-01-01', 'life_expectancy': 50})
        assert created.status_code == 201
        pid = created.json()['id']
        for income in incomes:
            assert (await client.post(f'/api/plans/{pid}/incomes', json=income)).status_code == 201
        response = await client.post(f'/api/plans/{pid}/simulate')
    else:
        response = await client.post('/api/simulate/stateless', json={
            'plan_id': str(uuid.uuid4()), 'birth_year': 1990, 'life_expectancy': 50,
            'filing_status': 'married_filing_jointly', 'start_year': 2026,
            'first_year_fraction': fraction,
            'income_streams': [dict(i, id=str(uuid.uuid4())) for i in incomes],
        })
    assert response.status_code == 200, response.text
    first, second = response.json()['yearly_snapshots'][:2]
    assert first['gross_income'] == pytest.approx(172000 * fraction)
    # Missing midyear history is estimated from the active streams, so the
    # tax line remains a full-calendar-year liability.
    assert first['fica_tax'] == pytest.approx(13935.546)
    assert second['fica_tax'] == pytest.approx(14302.746)

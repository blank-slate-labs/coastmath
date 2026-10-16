"""IRS Pub 590-B: the tenth-year payout is the entire remaining account.

Independent expectations: $1,000 grows to $900/$1,000/$1,100, then all is
paid out. A flat 20% tax leaves $720/$800/$880 in cash for a traditional IRA;
a Roth distribution leaves $900/$1,000/$1,100. No expense or other cash flow.
"""
import uuid

import pytest

from coastmath.engine.rmd import calculate_inherited_ira_rmd
from coastmath.engine.simulator import run_simulation
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data


@pytest.mark.parametrize('growth,gross', [(-.1, 900), (0, 1000), (.1, 1100)])
@pytest.mark.parametrize('kind,tax_rate', [('traditional_ira', .2), ('roth_ira', 0)])
@pytest.mark.parametrize('inherited_year', [2020, 2021])
def test_deadline_distribution_conserves_cash_and_clears_growth(growth, gross, kind, tax_rate, inherited_year):
    request = PlanDataRequest(plan_id=uuid.uuid4(), birth_year=1971, start_year=2031, life_expectancy=62,
        accounts={'ira': {'account_type': kind, 'balance': 1000, 'inherited_year': inherited_year, 'roth_settings': {'contribution_basis':1000, 'first_contribution_year':2010}}, 'cash': {'account_type': 'checking', 'balance': 0}},
        assumptions={'stock_growth_rate': growth, 'inflation_rate': 0},
        tax_settings={'mode': 'flat', 'ordinary_income_tax_rate': .2, 'capital_gains_tax_rate': 0, 'cash_flow_frequency': 'annual'})
    result = run_simulation(request_to_engine_data(request))
    first, second = result.yearly_snapshots
    assert first.accounts['ira'] == pytest.approx(0, abs=1e-9)
    assert first.taxes == pytest.approx(gross * tax_rate)
    assert first.accounts['cash'] == pytest.approx(gross * (1 - tax_rate))
    assert first.net_worth == pytest.approx(gross - first.taxes)
    assert second.accounts['ira'] == 0
    assert second.net_worth == pytest.approx(first.net_worth)
    assert second.taxes == 0


@pytest.mark.parametrize('beneficiary,prior_balance', [('spouse', 22900), ('edb', 22100)])
def test_annual_lifetime_amount_uses_prior_december_balance(beneficiary, prior_balance):
    # Spouse recalculates at65:22.9. EDB initially60:27.1 less5years=22.1.
    assert calculate_inherited_ira_rmd(25190, 2020, 2026, 65, beneficiary,
        prior_year_balance=prior_balance) == pytest.approx(1000)
    with pytest.raises(ValueError, match='age'):
        calculate_inherited_ira_rmd(25190, 2020, 2026, beneficiary_type=beneficiary,
            prior_year_balance=prior_balance)

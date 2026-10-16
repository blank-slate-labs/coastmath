"""Percent-of-balance debt payments match an independent month-by-month reconciliation."""
from types import SimpleNamespace

import pytest

from app.routers.liabilities import _compute_amortization
from coastmath.engine.amortization import calculate_year, generate_full_schedule


@pytest.mark.parametrize('fraction', [0.03, 0.01])
def test_percent_balance_matches_monthly_reconciliation(fraction):
    balance, cash, interest_paid = 10_000.0, 0.0, 0.0
    for _ in range(12):
        interest = balance * 0.18 / 12
        payment = balance * fraction
        cash += payment
        interest_paid += min(payment, interest)
        balance += interest - payment
    actual = calculate_year(10_000, 0.18, fraction, payment_type='percent_of_balance')
    schedule = generate_full_schedule(10_000, 0.18, 120, fraction, payment_type='percent_of_balance')
    api = _compute_amortization(SimpleNamespace(principal_balance=10_000, interest_rate=18,
        monthly_payment=fraction, payment_type='percent_of_balance', extra_payment=0, term_months=120))
    assert actual.remaining_balance == pytest.approx(balance)
    assert actual.interest_paid == pytest.approx(interest_paid)
    assert actual.principal_paid + actual.interest_paid == pytest.approx(cash)
    assert schedule[0].remaining_balance == pytest.approx(balance)
    assert api[0]['remaining_balance'] == pytest.approx(balance, abs=0.01)
    assert api[0]['interest_paid'] == pytest.approx(interest_paid, abs=0.01)
    assert api[0]['principal_paid'] == pytest.approx(actual.principal_paid, abs=0.01)

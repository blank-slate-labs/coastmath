"""Independent closed-form debt expectations and bounded generated invariants."""
import random

import pytest

from coastmath.engine.amortization import (
    calculate_fixed_payment,
    calculate_year,
    generate_full_schedule,
)


@pytest.mark.parametrize('payment', [0, 1, 5])
def test_underpaid_interest_is_capitalized_in_both_schedule_and_simulation(payment):
    # Loan starts at $1,000; 12% APR = 1% monthly. Closed-form future value:
    # P*(1+r)^n - payment*((1+r)^n-1)/r. No principal is repaid here.
    expected = 1000 * 1.01 ** 12 - payment * (1.01 ** 12 - 1) / .01
    year = calculate_year(1000, .12, payment)
    assert year.remaining_balance == pytest.approx(expected)
    assert year.interest_paid == pytest.approx(payment * 12)
    assert year.principal_paid == 0
    assert year.interest_capitalized == pytest.approx(expected - 1000)
    schedule = generate_full_schedule(1000, .12, 12, payment)
    assert schedule[0].remaining_balance == pytest.approx(expected)
    assert schedule[0].interest_paid == pytest.approx(payment * 12)
    assert schedule[0].principal_paid == 0
    assert len(schedule) == 50  # Explicit safety cap, not an invented payoff.
    second = expected * 1.01 ** 12 - payment * (1.01 ** 12 - 1) / .01
    assert schedule[1].remaining_balance == pytest.approx(second)


def test_generated_debt_cases_conserve_principal_cash_and_capitalized_interest():
    rng = random.Random(20260907)
    for _ in range(100):
        principal = rng.uniform(10000, 1000000)
        apr = rng.uniform(0, .3)
        payment = rng.uniform(0, 500)
        offset = rng.uniform(0, principal * 1.5)
        months = rng.choice([0, .5, 1, 1.5, 6, 12])
        result = calculate_year(principal, apr, payment, offset_balance=offset, months=months)
        assert result.remaining_balance == pytest.approx(principal - result.principal_paid + result.interest_capitalized)
        assert result.interest_paid + result.principal_paid == pytest.approx(payment * months)
        assert min(result.interest_paid, result.principal_paid, result.interest_capitalized) >= 0
        # An offset can reduce interest but cannot repay principal itself.
        without_offset = calculate_year(principal, apr, payment, months=months)
        assert result.remaining_balance <= without_offset.remaining_balance + 1e-8
        assert result.interest_paid <= without_offset.interest_paid + 1e-8


def test_final_fractional_month_prorates_interest_and_cash_independently():
    result = calculate_year(1000, .12, 100, months=1.5)
    # Month 1: $10 interest and $90 principal -> $910.
    # Half month: $4.55 interest and $45.45 principal -> $864.55.
    assert result.remaining_balance == pytest.approx(864.55)
    assert result.interest_paid == pytest.approx(14.55)
    assert result.principal_paid == pytest.approx(135.45)
    assert calculate_fixed_payment(12000, 0, 12) == 1000
    assert calculate_fixed_payment(12000, .1, 0) == 0

"""One liability rate contract across preview, schedule and simulation.

The loan editor labels the field "Interest Rate (%)" and the API stores that
percentage. The engine works in decimals. A $290,000 loan at 5.5% over 312
months must amortize identically everywhere: the standalone schedule, the
deterministic simulation, and the stateless request path.
"""

import datetime
from itertools import pairwise
from types import SimpleNamespace

import pytest

from app.engine.plan_converter import plan_to_engine_data
from app.routers.liabilities import _compute_amortization
from coastmath.engine.amortization import (
    calculate_fixed_payment,
    liability_rate_to_decimal,
)
from coastmath.engine.simulator import run_simulation
from coastmath.schemas.plan_data_request import LiabilityRequest

PRINCIPAL = 290_000.0
RATE_PERCENT = 5.5
TERM = 312
PAYMENT = 1749.12


def _plan_with_mortgage(rate_percent: float):
    liability = SimpleNamespace(
        id="loan", name="Mortgage", principal_balance=PRINCIPAL, interest_rate=rate_percent,
        term_months=TERM, monthly_payment=PAYMENT, payment_type="fixed", extra_payment=0,
        offset_account_id=None, linked_asset_id=None,
        payoff_milestone_id=None, forgiveness=None, interest_method=None, recurrence_years=None,
        recurrence_end_year=None, recurrence_end_milestone_id=None,
    )
    return SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111", birth_year=1992, birth_month=None, filing_status="single", life_expectancy=90,
        plan_type="FIXED_DATE", start_date=datetime.date(2027, 1, 1), snapshot_conditions=None,
        state_code=None, milestones=[], income_streams=[], expenses=[], priorities=[],
        drawdown_order=[], assumption_curves=[], real_assets=[], liabilities=[liability],
        residency_periods=[], spouse=None, charity_entities=[], sepp_settings=None,
        estate_settings=None, spending_settings=None, tax_settings=None, health_settings=None,
        year_to_date=None, filing_status_changes=None, spending_rules=None, healthcare_settings=None,
        cash_reserve_settings=None, local_tax=None, withdrawal_strategy=None, tax_country=None,
        tax_region=None, currency=None, intl_settings=None,
    )


def test_rate_helper_converts_percent_to_decimal():
    assert liability_rate_to_decimal(5.5) == pytest.approx(0.055)
    assert liability_rate_to_decimal(0) == 0.0


def test_payment_preview_matches_percent_contract():
    monthly = calculate_fixed_payment(PRINCIPAL, liability_rate_to_decimal(RATE_PERCENT), TERM)
    assert monthly == pytest.approx(PAYMENT, abs=0.01)


def test_plan_converter_feeds_engine_a_decimal_rate():
    data = plan_to_engine_data(_plan_with_mortgage(RATE_PERCENT), [])
    assert data.liabilities[0].interest_rate == pytest.approx(0.055)


def test_stateless_request_uses_the_same_contract():
    req = LiabilityRequest(id="loan", name="Mortgage", principal_balance=PRINCIPAL,
                           interest_rate=RATE_PERCENT, term_months=TERM, monthly_payment=PAYMENT)
    assert liability_rate_to_decimal(req.interest_rate) == pytest.approx(0.055)
    with pytest.raises(ValueError):
        LiabilityRequest(id="loan", name="Mortgage", principal_balance=PRINCIPAL, interest_rate=550)


def test_simulation_and_standalone_schedule_agree_on_year_one():
    plan = _plan_with_mortgage(RATE_PERCENT)
    data = plan_to_engine_data(plan, [])
    result = run_simulation(data)
    first_full_year = result.yearly_snapshots[0]
    schedule = _compute_amortization(plan.liabilities[0])

    assert first_full_year.liabilities_balance == pytest.approx(284_831.56, abs=1.0)
    assert schedule[0]["remaining_balance"] == pytest.approx(first_full_year.liabilities_balance, abs=1.0)
    # A 5.5% loan with a $1,749 payment pays off in year 26, never grows.
    assert len(schedule) == 26
    balances = [s.liabilities_balance for s in result.yearly_snapshots]
    assert all(b2 <= b1 + 1e-6 for b1, b2 in pairwise(balances))
    assert balances[-1] == pytest.approx(0.0, abs=1.0)

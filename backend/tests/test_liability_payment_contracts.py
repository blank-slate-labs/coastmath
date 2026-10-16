"""Liability payment inputs reach the engine with one contract.

Saved and stateless liabilities both reject a zero percent-of-balance payment
and pass an omitted one to the engine as None. A stateless fixed loan given
only a term derives the same amortized payment as a saved plan; the expected
payment and balance come from the standard amortization formula.
"""

import datetime
import uuid
from types import SimpleNamespace

import pytest

from app.engine.plan_converter import plan_to_engine_data
from app.schemas.liability import LiabilityCreate
from coastmath.engine.simulator import run_simulation
from coastmath.schemas.plan_data_request import (
    LiabilityRequest,
    PlanDataRequest,
    request_to_engine_data,
)


def test_persisted_liability_contract_rejects_zero_percent_payment():
    with pytest.raises(ValueError):
        LiabilityCreate(
            name="Loan",
            principal_balance=10_000,
            interest_rate=6,
            payment_type="percent_of_balance",
            monthly_payment=0,
        )


def test_stateless_liability_contract_matches_persisted_zero_payment_boundary():
    with pytest.raises(ValueError):
        LiabilityRequest(
            id="loan",
            name="Loan",
            principal_balance=10_000,
            interest_rate=6,
            payment_type="percent_of_balance",
            monthly_payment=0,
        )


def test_stateless_omitted_percent_payment_reaches_engine_as_none():
    request = PlanDataRequest(
        plan_id=uuid.uuid4(),
        birth_year=1990,
        start_year=2026,
        liabilities=[LiabilityRequest(
            id="loan",
            name="Loan",
            principal_balance=10_000,
            interest_rate=6,
            payment_type="percent_of_balance",
            monthly_payment=None,
        )],
    )

    engine_data = request_to_engine_data(request)

    assert engine_data.liabilities[0].monthly_payment is None


def test_persisted_omitted_percent_payment_reaches_engine_as_none():
    liability = SimpleNamespace(
        id="loan", name="Loan", principal_balance=10_000, interest_rate=6,
        term_months=None, monthly_payment=None, payment_type="percent_of_balance",
        extra_payment=0, offset_account_id=None, linked_asset_id=None,
        payoff_milestone_id=None, forgiveness=None, interest_method=None, recurrence_years=None,
        recurrence_end_year=None, recurrence_end_milestone_id=None,
    )
    plan = SimpleNamespace(
        id=str(uuid.uuid4()), birth_year=1990, birth_month=None,
        filing_status="single", life_expectancy=95, plan_type="FIXED_DATE",
        start_date=datetime.date(2026, 1, 1), snapshot_conditions=None,
        state_code=None, milestones=[], income_streams=[], expenses=[], priorities=[],
        drawdown_order=[], assumption_curves=[], real_assets=[], liabilities=[liability],
        residency_periods=[], spouse=None, charity_entities=[], sepp_settings=None,
        estate_settings=None, spending_settings=None, tax_settings=None,
        health_settings=None, year_to_date=None, filing_status_changes=None, spending_rules=None,
        healthcare_settings=None, cash_reserve_settings=None, local_tax=None, withdrawal_strategy=None,
        tax_country=None, tax_region=None, currency=None, intl_settings=None,
    )

    engine_data = plan_to_engine_data(plan, [])

    assert engine_data.liabilities[0].monthly_payment is None


# ---------------------------------------------------------------------------
# Stateless fixed loans derive their payment from the term
# ---------------------------------------------------------------------------


def test_stateless_term_only_fixed_loan_amortizes_like_a_saved_plan():
    request = PlanDataRequest.model_validate({
        "plan_id": str(uuid.uuid4()), "birth_year": 1986, "life_expectancy": 90, "start_year": 2026,
        "assumptions": {"inflation_rate": 0, "stock_growth_rate": 0, "bond_return_rate": 0},
        "accounts": {"cash": {"balance": 1_000_000, "account_type": "checking"}},
        "liabilities": [{"id": "m", "name": "Mortgage", "principal_balance": 300_000,
                         "interest_rate": 6.0, "term_months": 360, "payment_type": "fixed"}],
        "drawdown_order": [{"rank": 1, "source_account_id": "cash"}],
    })
    plan = request_to_engine_data(request)
    monthly = 0.005
    growth = (1 + monthly) ** 360
    payment = 300_000 * monthly * growth / (growth - 1)
    assert plan.liabilities[0].monthly_payment == pytest.approx(payment)
    year = run_simulation(plan).yearly_snapshots[0]
    one_year = (1 + monthly) ** 12
    assert year.liabilities_balance == pytest.approx(300_000 * one_year - payment * (one_year - 1) / monthly)

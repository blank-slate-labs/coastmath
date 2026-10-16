"""
The sample plan ("Sample plan") as ORM objects.

No request handler calls this. ``POST /api/auth/session`` stopped seeding it
into new sessions: signed-out web visitors see a static read-only copy with no
database rows. The function remains the plan's single definition for a
hosting package's exporters and for test fixtures (``tests/e2e_server.py``
among them).

Maintenance — stale anonymous user cleanup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Sessions created before seeding stopped hold anonymous users and seeded plans,
and native clients still create anonymous users. Run periodically to purge
rows older than 30 days that have no recently-modified plans::

    DELETE FROM users
     WHERE is_anonymous = true
       AND created_at < NOW() - INTERVAL '30 days'
       AND id NOT IN (
           SELECT DISTINCT user_id FROM plans
            WHERE updated_at > NOW() - INTERVAL '30 days'
       );
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.account import CurrentAccount
from app.models.assumption_curve import AssumptionCurve
from app.models.cash_flow_priority import CashFlowPriority
from app.models.drawdown_order import DrawdownOrder
from app.models.expense import Expense
from app.models.income import IncomeStream
from app.models.milestone import Milestone
from app.models.plan import Plan
from app.models.planning_client import PlanningClient
from app.models.spouse import Spouse


def seed_demo_plan(user_id: uuid.UUID, db: Session, client_id: uuid.UUID | None = None) -> Plan:
    """Create a complete demo plan with all sub-entities in a single transaction.

    Args:
        user_id: The owning user's UUID.
        db: An active SQLAlchemy session (caller controls commit/rollback).

    Returns:
        The newly created :class:`Plan` instance (already flushed).
    """
    now = datetime.now(UTC)

    # Generate fresh UUIDs for every seed invocation so multiple anonymous
    # users don't collide on primary keys.
    plan_id = uuid.uuid4()
    acct_emergency = uuid.uuid4()
    acct_brokerage = uuid.uuid4()
    acct_401k = uuid.uuid4()
    acct_roth_ira = uuid.uuid4()
    ms_retirement = uuid.uuid4()
    ms_spouse_retire = uuid.uuid4()
    ms_ss_start = uuid.uuid4()
    ms_mortgage_paid = uuid.uuid4()

    # -- Plan ---------------------------------------------------------------
    plan = Plan(
        id=plan_id,
        user_id=user_id,
        client_id=client_id,
        name="Sample plan",
        plan_type="NOW",
        start_date=None,
        snapshot_conditions={},
        birth_year=1990,
        filing_status="married_filing_jointly",
        state_code=None,
        life_expectancy=90,
        sepp_settings=None,
        spending_rules={},
        estate_settings={},
        created_at=now,
    )
    db.add(plan)
    db.flush()

    # -- Accounts (user-level, not plan-level) ------------------------------
    accounts = [
        CurrentAccount(
            id=acct_emergency,
            user_id=user_id,
            name="Emergency Fund",
            account_type="savings",
            balance=20000,
            owner="self",
        ),
        CurrentAccount(
            id=acct_brokerage,
            user_id=user_id,
            name="Brokerage",
            account_type="taxable_brokerage",
            balance=50000,
            owner="self",
        ),
        CurrentAccount(
            id=acct_401k,
            user_id=user_id,
            name="401k",
            account_type="traditional_401k",
            balance=150000,
            owner="self",
        ),
        CurrentAccount(
            id=acct_roth_ira,
            user_id=user_id,
            name="Roth IRA (partner)",
            account_type="roth_ira",
            balance=40000,
            owner="spouse",
        ),
    ]
    if client_id:
        for account in accounts:
            account.plan_id = plan_id
    db.add_all(accounts)

    # -- Milestones ---------------------------------------------------------
    milestones = [
        Milestone(
            id=ms_retirement,
            plan_id=plan_id,
            name="Retirement",
            trigger_type="age",
            trigger_value=65,
            trigger_date=None,
            sort_order=0,
        ),
        Milestone(
            id=ms_spouse_retire,
            plan_id=plan_id,
            name="Partner retirement",
            trigger_type="age",
            trigger_value=63,
            trigger_date=None,
            sort_order=1,
        ),
        Milestone(
            id=ms_ss_start,
            plan_id=plan_id,
            name="Social Security Begins",
            trigger_type="age",
            trigger_value=67,
            trigger_date=None,
            sort_order=2,
        ),
        Milestone(
            id=ms_mortgage_paid,
            plan_id=plan_id,
            name="Mortgage Paid Off",
            trigger_type="age",
            trigger_value=60,
            trigger_date=None,
            sort_order=3,
        ),
    ]
    db.add_all(milestones)

    # Flush so milestone FKs are available for income streams / spouse
    db.flush()

    # -- Income Streams -----------------------------------------------------
    income_streams = [
        IncomeStream(
            id=uuid.uuid4(),
            plan_id=plan_id,
            name="Salary",
            annual_amount=100000,
            start_milestone_id=None,
            end_milestone_id=ms_retirement,
            growth_rate=3.0,  # percent per year (storage convention)
            is_active=True,
        ),
        IncomeStream(
            id=uuid.uuid4(),
            plan_id=plan_id,
            name="Partner salary",
            owner="spouse",
            annual_amount=60000,
            start_milestone_id=None,
            end_milestone_id=ms_spouse_retire,
            growth_rate=3.0,  # percent per year (storage convention)
            is_active=True,
        ),
        IncomeStream(
            id=uuid.uuid4(),
            plan_id=plan_id,
            name="Social Security (Self)",
            annual_amount=28000,
            start_milestone_id=ms_ss_start,
            end_milestone_id=None,
            growth_rate=2.0,  # percent per year (storage convention)
            is_active=True,
            is_social_security=True,
            is_earned_income=False,
        ),
        IncomeStream(
            id=uuid.uuid4(),
            plan_id=plan_id,
            name="Social Security (Partner)",
            owner="spouse",
            annual_amount=20000,
            start_milestone_id=ms_ss_start,
            end_milestone_id=None,
            growth_rate=2.0,  # percent per year (storage convention)
            is_active=True,
            is_social_security=True,
            is_earned_income=False,
        ),
    ]
    db.add_all(income_streams)
    # Payroll priorities reference these IDs. With scalar FK assignments,
    # SQLAlchemy does not guarantee that income rows flush before priorities.
    db.flush()

    # -- Expenses -----------------------------------------------------------
    # Spending changes over the plan so it reads as a real household: the
    # fixed-rate mortgage payment is nominal (it shrinks in real terms) and
    # stops at 60, healthcare outpaces 3% inflation, and everyday living
    # costs step down 20% at retirement.
    expenses = [
        Expense(
            id=uuid.uuid4(),
            plan_id=plan_id,
            name="Mortgage",
            annual_amount=18000,
            end_milestone_id=ms_mortgage_paid,
            inflation_linked=False,
            is_payroll_deduction=False,
            category="essential",
        ),
        Expense(
            id=uuid.uuid4(),
            plan_id=plan_id,
            name="Housing",
            annual_amount=6000,
            inflation_linked=True,
            is_payroll_deduction=False,
            category="essential",
        ),
        Expense(
            id=uuid.uuid4(),
            plan_id=plan_id,
            name="Living",
            annual_amount=36000,
            end_milestone_id=ms_retirement,
            inflation_linked=True,
            is_payroll_deduction=False,
            category="discretionary",
        ),
        Expense(
            id=uuid.uuid4(),
            plan_id=plan_id,
            name="Retirement Living",
            annual_amount=28800,
            start_milestone_id=ms_retirement,
            inflation_linked=True,
            is_payroll_deduction=False,
            category="discretionary",
        ),
        Expense(
            id=uuid.uuid4(),
            plan_id=plan_id,
            name="Healthcare",
            annual_amount=6000,
            inflation_linked=True,
            growth_rate=5.0,  # percent per year (storage convention)
            is_payroll_deduction=False,
            category="essential",
        ),
    ]
    db.add_all(expenses)

    # -- Cash Flow Priorities -----------------------------------------------
    priorities = [
        CashFlowPriority(
            id=uuid.uuid4(),
            plan_id=plan_id,
            priority_rank=1,
            target_account_id=acct_emergency,
            max_annual_amount=20000,
        ),
        CashFlowPriority(
            id=uuid.uuid4(),
            plan_id=plan_id,
            priority_rank=2,
            target_account_id=acct_401k,
            max_annual_amount=24500,
            priority_type="pre_tax_contribution",
            source_income_id=income_streams[0].id,
        ),
        CashFlowPriority(
            id=uuid.uuid4(),
            plan_id=plan_id,
            priority_rank=3,
            target_account_id=acct_roth_ira,
            max_annual_amount=7500,
        ),
        CashFlowPriority(
            id=uuid.uuid4(),
            plan_id=plan_id,
            priority_rank=4,
            target_account_id=acct_brokerage,
            max_annual_amount=None,
        ),
    ]
    db.add_all(priorities)

    # -- Drawdown Order -----------------------------------------------------
    drawdown_entries = [
        DrawdownOrder(
            id=uuid.uuid4(),
            plan_id=plan_id,
            rank=1,
            source_account_id=acct_emergency,
        ),
        DrawdownOrder(
            id=uuid.uuid4(),
            plan_id=plan_id,
            rank=2,
            source_account_id=acct_brokerage,
        ),
        DrawdownOrder(
            id=uuid.uuid4(),
            plan_id=plan_id,
            rank=3,
            source_account_id=acct_401k,
        ),
        DrawdownOrder(
            id=uuid.uuid4(),
            plan_id=plan_id,
            rank=4,
            source_account_id=acct_roth_ira,
        ),
    ]
    db.add_all(drawdown_entries)

    # -- Assumption Curves --------------------------------------------------
    curves = [
        AssumptionCurve(
            id=uuid.uuid4(),
            plan_id=plan_id,
            curve_type="inflation",
            mode="fixed",
            fixed_rate=0.03,
            control_points=[],
        ),
        AssumptionCurve(
            id=uuid.uuid4(),
            plan_id=plan_id,
            curve_type="market_return",
            mode="fixed",
            fixed_rate=0.07,
            control_points=[],
        ),
        AssumptionCurve(
            id=uuid.uuid4(),
            plan_id=plan_id,
            curve_type="bond_return",
            mode="fixed",
            fixed_rate=0.04,
            control_points=[],
        ),
    ]
    db.add_all(curves)

    # -- Spouse -------------------------------------------------------------
    spouse = Spouse(
        id=uuid.uuid4(),
        plan_id=plan_id,
        name="Partner",
        birth_year=1992,
        life_expectancy=90,
        income_streams=[],
        retirement_milestone_id=ms_spouse_retire,
    )
    db.add(spouse)

    # Commit the whole transaction
    db.commit()
    db.refresh(plan)
    return plan


def seed_sample_household(user_id: uuid.UUID, db: Session) -> Plan:
    """The sample in its own "Sample household" client workspace, with plan-scoped
    accounts, as ``POST /api/auth/session {"client_workspace": true}`` created it
    for web and native samples before sessions stopped seeding."""
    client = PlanningClient(user_id=user_id, name="Sample household")
    db.add(client)
    db.flush()
    return seed_demo_plan(user_id, db, client_id=client.id)

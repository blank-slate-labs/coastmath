"""Tests for the server-side demo plan seeder."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text

from app.models.account import CurrentAccount
from app.models.user import User
from app.seed import seed_demo_plan


def _create_test_user(db) -> uuid.UUID:
    """Create a throwaway user and return its ID."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=None,
        is_anonymous=True,
        display_name="Test Anon User",
        settings={},
        created_at=datetime.now(UTC),
    )
    db.add(user)
    db.commit()
    return user_id


def test_seed_demo_plan_creates_plan(db_session):
    user_id = _create_test_user(db_session)
    plan = seed_demo_plan(user_id, db_session)

    assert isinstance(plan.id, uuid.UUID)
    assert plan.user_id == user_id
    assert plan.name == "Sample plan"
    assert plan.plan_type == "NOW"
    assert plan.birth_year == 1990
    assert plan.filing_status == "married_filing_jointly"
    assert plan.state_code is None
    assert plan.life_expectancy == 90
    assert plan.start_date is None


def test_seed_demo_plan_creates_accounts(db_session):
    user_id = _create_test_user(db_session)
    seed_demo_plan(user_id, db_session)

    accounts = db_session.query(CurrentAccount).filter_by(user_id=user_id).all()
    assert len(accounts) == 4

    by_name = {a.name: a for a in accounts}

    em = by_name["Emergency Fund"]
    assert em.account_type == "savings"
    assert Decimal(str(em.balance)) == Decimal("20000")

    brok = by_name["Brokerage"]
    assert brok.account_type == "taxable_brokerage"
    assert Decimal(str(brok.balance)) == Decimal("50000")

    k401 = by_name["401k"]
    assert k401.account_type == "traditional_401k"
    assert Decimal(str(k401.balance)) == Decimal("150000")

    roth = by_name["Roth IRA (partner)"]
    assert roth.account_type == "roth_ira"
    assert roth.owner == "spouse"


def test_seed_demo_plan_creates_milestones(db_session):
    user_id = _create_test_user(db_session)
    plan = seed_demo_plan(user_id, db_session)

    ms = plan.milestones
    assert len(ms) == 4

    by_name = {m.name: m for m in ms}

    ret = by_name["Retirement"]
    assert ret.trigger_type == "age"
    assert int(ret.trigger_value) == 65

    sp = by_name["Partner retirement"]
    assert int(sp.trigger_value) == 63

    ss = by_name["Social Security Begins"]
    assert ss.trigger_type == "age"
    assert int(ss.trigger_value) == 67

    paid = by_name["Mortgage Paid Off"]
    assert paid.trigger_type == "age"
    assert int(paid.trigger_value) == 60


def test_seed_demo_plan_creates_income_streams(db_session):
    user_id = _create_test_user(db_session)
    plan = seed_demo_plan(user_id, db_session)

    ms_by_name = {m.name: m for m in plan.milestones}
    incomes = plan.income_streams
    assert len(incomes) == 4

    by_name = {i.name: i for i in incomes}

    salary = by_name["Salary"]
    assert Decimal(str(salary.annual_amount)) == Decimal("100000")
    assert salary.end_milestone_id == ms_by_name["Retirement"].id
    assert salary.start_milestone_id is None

    spouse_sal = by_name["Partner salary"]
    assert spouse_sal.owner == "spouse"
    assert Decimal(str(spouse_sal.annual_amount)) == Decimal("60000")
    assert spouse_sal.end_milestone_id == ms_by_name["Partner retirement"].id

    ss_self = by_name["Social Security (Self)"]
    assert Decimal(str(ss_self.annual_amount)) == Decimal("28000")
    assert ss_self.start_milestone_id == ms_by_name["Social Security Begins"].id
    assert ss_self.end_milestone_id is None
    assert ss_self.is_social_security is True
    assert ss_self.is_earned_income is False

    ss_spouse = by_name["Social Security (Partner)"]
    assert ss_spouse.owner == "spouse"
    assert Decimal(str(ss_spouse.annual_amount)) == Decimal("20000")
    assert ss_spouse.start_milestone_id == ms_by_name["Social Security Begins"].id
    assert ss_spouse.is_social_security is True


def test_seed_demo_plan_creates_expenses(db_session):
    user_id = _create_test_user(db_session)
    plan = seed_demo_plan(user_id, db_session)

    ms_by_name = {m.name: m for m in plan.milestones}
    expenses = plan.expenses
    assert len(expenses) == 5

    by_name = {e.name: e for e in expenses}

    mortgage = by_name["Mortgage"]
    assert Decimal(str(mortgage.annual_amount)) == Decimal("18000")
    assert mortgage.inflation_linked is False
    assert mortgage.end_milestone_id == ms_by_name["Mortgage Paid Off"].id

    housing = by_name["Housing"]
    assert Decimal(str(housing.annual_amount)) == Decimal("6000")
    assert housing.category == "essential"
    assert housing.inflation_linked is True

    living = by_name["Living"]
    assert Decimal(str(living.annual_amount)) == Decimal("36000")
    assert living.category == "discretionary"
    assert living.end_milestone_id == ms_by_name["Retirement"].id

    retired = by_name["Retirement Living"]
    assert Decimal(str(retired.annual_amount)) == Decimal("28800")
    assert retired.start_milestone_id == ms_by_name["Retirement"].id

    health = by_name["Healthcare"]
    assert Decimal(str(health.annual_amount)) == Decimal("6000")
    assert health.category == "essential"
    assert Decimal(str(health.growth_rate)) == Decimal("5")


def test_seed_demo_plan_creates_priorities(db_session):
    user_id = _create_test_user(db_session)
    plan = seed_demo_plan(user_id, db_session)

    accounts = db_session.query(CurrentAccount).filter_by(user_id=user_id).all()
    acct_by_name = {a.name: a for a in accounts}

    priorities = sorted(plan.priorities, key=lambda p: p.priority_rank)
    assert len(priorities) == 4

    assert priorities[0].target_account_id == acct_by_name["Emergency Fund"].id
    assert Decimal(str(priorities[0].max_annual_amount)) == Decimal("20000")

    assert priorities[1].target_account_id == acct_by_name["401k"].id
    assert Decimal(str(priorities[1].max_annual_amount)) == Decimal("24500")

    assert priorities[2].target_account_id == acct_by_name["Roth IRA (partner)"].id
    assert Decimal(str(priorities[2].max_annual_amount)) == Decimal("7500")

    assert priorities[3].target_account_id == acct_by_name["Brokerage"].id
    assert priorities[3].max_annual_amount is None


def test_seed_demo_plan_creates_drawdown_order(db_session):
    user_id = _create_test_user(db_session)
    plan = seed_demo_plan(user_id, db_session)

    accounts = db_session.query(CurrentAccount).filter_by(user_id=user_id).all()
    acct_by_name = {a.name: a for a in accounts}

    dd = sorted(plan.drawdown_order, key=lambda d: d.rank)
    assert len(dd) == 4

    assert dd[0].source_account_id == acct_by_name["Emergency Fund"].id
    assert dd[1].source_account_id == acct_by_name["Brokerage"].id
    assert dd[2].source_account_id == acct_by_name["401k"].id
    assert dd[3].source_account_id == acct_by_name["Roth IRA (partner)"].id


def test_seed_demo_plan_creates_assumption_curves(db_session):
    user_id = _create_test_user(db_session)
    plan = seed_demo_plan(user_id, db_session)

    curves = plan.assumption_curves
    assert len(curves) == 3

    by_type = {c.curve_type: c for c in curves}

    inf = by_type["inflation"]
    assert inf.mode == "fixed"
    assert float(inf.fixed_rate) == 0.03

    mkt = by_type["market_return"]
    assert float(mkt.fixed_rate) == 0.07

    bond = by_type["bond_return"]
    assert float(bond.fixed_rate) == 0.04


def test_seed_demo_plan_creates_spouse(db_session):
    user_id = _create_test_user(db_session)
    plan = seed_demo_plan(user_id, db_session)

    ms_by_name = {m.name: m for m in plan.milestones}
    spouse = plan.spouse
    assert spouse is not None
    assert spouse.name == "Partner"
    assert spouse.birth_year == 1992
    assert spouse.life_expectancy == 90
    assert spouse.retirement_milestone_id == ms_by_name["Partner retirement"].id
    assert spouse.income_streams == []


def test_seed_demo_plan_income_growth_uses_percent_units(db_session):
    """Storage convention is percent per year (3.0 = 3%); the engine divides by
    100. A decimal 0.03 would simulate as 0.03% growth and disable the Social
    Security COLA path."""
    user_id = _create_test_user(db_session)
    plan = seed_demo_plan(user_id, db_session)
    rates = {i.name: float(i.growth_rate) for i in plan.income_streams}
    assert rates["Salary"] == 3.0
    assert rates["Social Security (Self)"] == 2.0


def test_seed_demo_plan_with_foreign_keys_enforced(db_session):
    # Production PostgreSQL always enforces FKs; the default SQLite fixture
    # otherwise misses ordering failures during first-visit sample creation.
    db_session.commit()
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    try:
        assert db_session.execute(text("PRAGMA foreign_keys")).scalar() == 1
        plan = seed_demo_plan(_create_test_user(db_session), db_session)
        payroll = next(p for p in plan.priorities if p.priority_type == "pre_tax_contribution")
        assert payroll.source_income_id in {income.id for income in plan.income_streams}
    finally:
        db_session.rollback()
        db_session.execute(text("PRAGMA foreign_keys=OFF"))

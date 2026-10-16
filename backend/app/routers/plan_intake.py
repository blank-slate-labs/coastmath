import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.access import present_plans
from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import validation_error
from app.ledger.feeds import guard_connected_expense
from app.models.charity import CharityEntity
from app.models.expense import Expense
from app.models.milestone import Milestone
from app.models.plan import Plan
from app.models.user import User
from app.routers.helpers import get_plan_or_404, validate_milestone_window
from app.schemas.plan import PlanRead
from app.schemas.plan_intake import (
    CHARITY_ENTITY,
    RETIREMENT_MILESTONE,
    RETIREMENT_SPENDING_EXPENSE,
    TRAVEL_END_MILESTONE,
    TRAVEL_EXPENSE,
    PlanIntake,
)

# Mounted with the plan write guard: archived plans and closed editing windows refuse it.
router = APIRouter(prefix="/plans/{plan_id}/intake", tags=["plans"])


def _named(rows, name: str):
    return next((row for row in rows if row.name == name), None)


def _age_milestone(plan: Plan, name: str, age: int) -> Milestone:
    """Create or update the plan's milestone with this name to trigger at ``age``."""
    milestone = _named(plan.milestones, name)
    if milestone is None:
        milestone = Milestone(name=name, sort_order=max((m.sort_order for m in plan.milestones), default=-1) + 1)
        plan.milestones.append(milestone)
    milestone.trigger_type, milestone.trigger_value = "age", age
    milestone.trigger_date = milestone.metric = milestone.expense_multiple = milestone.relative_to_id = None
    milestone.offset_years = 0
    return milestone


def _expense(plan: Plan, name: str, db: Session, **values) -> None:
    expense = _named(plan.expenses, name)
    if expense is None:
        # Intake asks for yearly amounts. A later submission changes only the
        # amount, so a unit the customer picked since then is kept.
        plan.expenses.append(Expense(name=name, inflation_linked=True, amount_frequency="annual", **values))
        return
    guard_connected_expense(db, expense, values)
    if expense.discretionary_percent is not None:
        # The customer has since split this expense; its percent and the
        # category that mirrors it are theirs, not the intake default's.
        values.pop("category", None)
    for field, value in values.items():
        setattr(expense, field, value)


def _apply(plan: Plan, body: PlanIntake, db: Session) -> None:
    if body.legacy_target is not None:
        # Reassign so SQLAlchemy sees the JSONB change; other estate keys stay.
        plan.estate_settings = {**(plan.estate_settings or {}), "legacy_target": body.legacy_target}
    if body.retirement_age is not None:
        _age_milestone(plan, RETIREMENT_MILESTONE, body.retirement_age)
    needs_retirement = any(v is not None for v in (body.retirement_spending, body.travel_budget, body.charitable_giving))
    if not needs_retirement:
        return
    retirement = _named(plan.milestones, RETIREMENT_MILESTONE)
    if retirement is None:
        raise validation_error(
            "Enter a retirement age.", "retirement_age", "required for retirement spending, travel and giving",
        )
    db.flush()  # New milestones need IDs before items refer to them.

    if body.retirement_spending is not None:
        _expense(plan, RETIREMENT_SPENDING_EXPENSE, db, annual_amount=body.retirement_spending,
                 category="essential", start_milestone_id=retirement.id)
    if body.travel_budget is not None:
        travel_end = (_age_milestone(plan, TRAVEL_END_MILESTONE, body.travel_until_age)
                      if body.travel_until_age is not None else None)
        db.flush()
        end_id = travel_end.id if travel_end is not None else None
        validate_milestone_window(plan, retirement.id, end_id, db)
        _expense(plan, TRAVEL_EXPENSE, db, annual_amount=body.travel_budget,
                 category="discretionary", start_milestone_id=retirement.id, end_milestone_id=end_id)
    if body.charitable_giving is not None:
        charity = _named(plan.charity_entities, CHARITY_ENTITY)
        if charity is None:
            plan.charity_entities.append(CharityEntity(
                name=CHARITY_ENTITY, entity_type="direct", annual_amount=body.charitable_giving,
                start_milestone_id=retirement.id))
        else:
            charity.annual_amount, charity.start_milestone_id = body.charitable_giving, retirement.id


@router.post("", response_model=PlanRead)
def apply_plan_intake(
    plan_id: uuid.UUID,
    body: PlanIntake,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Plan:
    """Turn the new-plan goals into plan items in one transaction.

    Blank answers change nothing. Items are matched by the names the intake gives
    them, so submitting again updates those items rather than adding more.
    """
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    if not body.is_empty():
        try:
            _apply(plan, body, db)
        except HTTPException:
            db.rollback()
            raise
        db.commit()
        db.refresh(plan)
    return present_plans([plan], current_user, db)[0]

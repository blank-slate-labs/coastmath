import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error, validation_error
from app.models.account import CurrentAccount
from app.models.cash_flow_priority import CashFlowPriority
from app.models.charity import CharityEntity
from app.models.expense import Expense
from app.models.income import IncomeStream
from app.models.liability import Liability
from app.models.milestone import Milestone
from app.models.plan import Plan
from app.models.residency_period import ResidencyPeriod
from app.models.user import User
from app.routers.helpers import (
    ensure_row_capacity,
    get_plan_or_404,
    lock_priority_revision,
    plan_account_filter,
)
from app.schemas.milestone import (
    MilestoneCreate,
    MilestoneRead,
    MilestoneUpdate,
    condition_references,
)
from coastmath.schemas.tax_adjustments import referenced_milestone_ids

router = APIRouter(prefix="/plans/{plan_id}/milestones", tags=["milestones"])


def _get_milestone_or_404(
    milestone_id: uuid.UUID, plan_id: uuid.UUID, db: Session
) -> Milestone:
    milestone = (
        db.query(Milestone)
        .filter(Milestone.id == milestone_id, Milestone.plan_id == plan_id)
        .first()
    )
    if not milestone:
        raise api_error(404, "NOT_FOUND", "Milestone not found")
    return milestone


def _validate_conditions(plan_id: uuid.UUID, milestone_id: uuid.UUID | None,
                         values: dict, db: Session) -> None:
    conditions = values.get("conditions")
    if values.get("trigger_type") == "conditions" and not conditions:
        raise validation_error("Conditions are required", "conditions", "required for conditions milestones")
    rows = db.query(Milestone).filter(Milestone.plan_id == plan_id).all()
    ids = {str(row.id) for row in rows}
    references, accounts = condition_references(conditions)
    if references - ids:
        raise validation_error("Condition milestones must belong to this plan", "conditions", "milestone not found in plan")
    # Snapshot plans own account identity in their frozen balance settings.
    plan = db.get(Plan, plan_id)
    account_ids = {str(row.id) for row in db.query(CurrentAccount).filter(
        CurrentAccount.user_id == plan.user_id, plan_account_filter(plan_id, plan.user_id, db)).all()}
    if plan.plan_type == "FIXED_DATE":
        account_ids.update((plan.snapshot_conditions or {}).keys())
    if accounts - account_ids:
        raise validation_error("Condition accounts must belong to this plan", "conditions", "account not found in plan")
    if milestone_id is None:
        return
    graph = {}
    for row in rows:
        refs, _ = condition_references(row.conditions if row.trigger_type == "conditions" else None)
        if row.trigger_type == "relative" and row.relative_to_id:
            refs.add(str(row.relative_to_id))
        graph[str(row.id)] = refs
    active_refs = references if values.get("trigger_type") == "conditions" else set()
    if values.get("trigger_type") == "relative" and values.get("relative_to_id"):
        active_refs.add(str(values["relative_to_id"]))
    graph[str(milestone_id)] = active_refs
    visiting, visited = set(), set()

    def visit(mid):
        if mid in visiting:
            raise validation_error("Relative milestones form a cycle" if values.get("trigger_type") == "relative" else "Milestones form a cycle",
                                   "relative_to_id" if values.get("trigger_type") == "relative" else "conditions", "circular reference")
        if mid in visited:
            return
        visiting.add(mid)
        for parent in graph.get(mid, set()):
            visit(parent)
        visiting.remove(mid)
        visited.add(mid)
    visit(str(milestone_id))


def _validate_milestone(
    plan_id: uuid.UUID,
    milestone_id: uuid.UUID | None,
    values: dict,
    db: Session,
) -> None:
    """Enforce trigger-type requirements and reject circular relative chains.

    ``values`` is the merged post-update state of the milestone.
    """
    _validate_conditions(plan_id, milestone_id, values, db)
    trigger_type = values.get("trigger_type")
    if trigger_type in ("age", "net_worth") and values.get("trigger_value") is None:
        raise validation_error("Trigger value is required", "trigger_value", f"required for {trigger_type} milestones")
    if trigger_type == "date" and values.get("trigger_date") is None:
        raise validation_error("Trigger date is required", "trigger_date", "required for date milestones")
    if trigger_type == "expense_multiple":
        multiple = values.get("expense_multiple")
        if multiple is None:
            multiple = values.get("trigger_value")
        if multiple is None or multiple <= 0:
            raise validation_error("Expense multiple must be positive", "expense_multiple", "required for expense_multiple milestones")
    relative_to = values.get("relative_to_id")
    if trigger_type == "relative" and relative_to is None:
        raise validation_error("Relative milestones need a reference", "relative_to_id", "required for relative milestones")
    if relative_to is None:
        return
    if milestone_id is not None and relative_to == milestone_id:
        raise validation_error("A milestone cannot be relative to itself", "relative_to_id", "self-reference")
    rows = db.query(Milestone.id, Milestone.relative_to_id).filter(Milestone.plan_id == plan_id).all()
    parents = {row.id: row.relative_to_id for row in rows}
    if relative_to not in parents:
        raise validation_error("Referenced milestone not found in this plan", "relative_to_id", f"{relative_to} not found")
    # Walk the reference chain from the target; if it reaches the milestone
    # being saved (or repeats) the chain would never resolve.
    seen: set[uuid.UUID] = set()
    cursor: uuid.UUID | None = relative_to
    while cursor is not None:
        if cursor == milestone_id or cursor in seen:
            raise validation_error(
                "Relative milestones form a cycle", "relative_to_id", "circular reference",
            )
        seen.add(cursor)
        cursor = parents.get(cursor)


@router.post("", response_model=MilestoneRead, status_code=201)
def create_milestone(
    plan_id: uuid.UUID,
    body: MilestoneCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Milestone:
    get_plan_or_404(plan_id, current_user.id, db)
    ensure_row_capacity(db.query(Milestone.id).filter(Milestone.plan_id == plan_id), "a milestone")
    _validate_milestone(plan_id, None, body.model_dump(), db)
    milestone = Milestone(plan_id=plan_id, **body.model_dump())
    db.add(milestone)
    db.commit()
    db.refresh(milestone)
    return milestone


@router.get("", response_model=list[MilestoneRead])
def list_milestones(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Milestone]:
    get_plan_or_404(plan_id, current_user.id, db)
    return (
        db.query(Milestone)
        .filter(Milestone.plan_id == plan_id)
        .order_by(Milestone.sort_order)
        .all()
    )


@router.put("/{milestone_id}", response_model=MilestoneRead)
def update_milestone(
    plan_id: uuid.UUID,
    milestone_id: uuid.UUID,
    body: MilestoneUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Milestone:
    get_plan_or_404(plan_id, current_user.id, db)
    milestone = _get_milestone_or_404(milestone_id, plan_id, db)
    changes = body.model_dump(exclude_unset=True)
    merged = {
        "trigger_type": milestone.trigger_type,
        "trigger_value": milestone.trigger_value,
        "trigger_date": milestone.trigger_date,
        "metric": milestone.metric,
        "expense_multiple": milestone.expense_multiple,
        "relative_to_id": milestone.relative_to_id,
        "conditions": milestone.conditions,
        **changes,
    }
    _validate_milestone(plan_id, milestone_id, merged, db)
    for field, value in changes.items():
        setattr(milestone, field, value)
    db.commit()
    db.refresh(milestone)
    return milestone


def _blocking_reference(plan, milestone_id: uuid.UUID, user_id: uuid.UUID, db: Session) -> str | None:
    """Name the first saved setting that still uses this milestone, if any.

    Settings stored as JSON (and charitable gifts, whose foreign keys do not
    clear) would keep a dangling id after the delete and silently stop
    firing, so each one blocks the delete instead. Rows whose foreign keys
    would clear block it too (``_foreign_key_dependents``).
    """
    mid = str(milestone_id)
    if any(change.get("milestone_id") == mid for change in plan.filing_status_changes or []):
        return "This milestone schedules a filing status change. Update that schedule before deleting it."
    rules = plan.spending_rules or {}
    if mid in (rules.get("start_milestone_id"), rules.get("end_milestone_id")):
        return "This milestone bounds flexible spending. Update that rule before deleting it."
    if mid in referenced_milestone_ids(plan.tax_settings):
        return "This milestone times a tax adjustment or scheduled tax change. Update those tax settings before deleting it."
    if (plan.withdrawal_strategy or {}).get("start_milestone_id") == mid:
        return "This milestone starts the withdrawal strategy. Update that strategy before deleting it."
    healthcare = plan.healthcare_settings or {}
    if mid in (str(healthcare.get("aca_start_milestone_id")), str(healthcare.get("aca_end_milestone_id"))):
        return "This milestone bounds marketplace coverage. Update the healthcare settings before deleting it."
    if any(str(benefit.get("start_milestone_id")) == mid for benefit in (plan.intl_settings or {}).get("benefits") or []):
        return "This milestone starts a country benefit. Update that benefit before deleting it."
    forgiveness = db.query(Liability.forgiveness).filter(
        Liability.plan_id == plan.id, Liability.forgiveness.is_not(None)).all()
    if any(str((terms or {}).get("milestone_id")) == mid for (terms,) in forgiveness):
        return "This milestone forgives a loan. Update that loan before deleting it."
    if db.query(CharityEntity.id).filter(
            CharityEntity.plan_id == plan.id,
            or_(CharityEntity.start_milestone_id == milestone_id, CharityEntity.end_milestone_id == milestone_id),
    ).first() is not None:
        return "This milestone times a charitable gift. Update that gift before deleting it."
    dependents = db.query(Milestone).filter(Milestone.plan_id == plan.id).all()
    if any(mid in condition_references(row.conditions)[0] for row in dependents):
        return "Another milestone uses this milestone in its conditions. Update it before deleting."
    # Like the flexible-spending window, a JSON reference blocks the delete:
    # clearing it would silently make a locked account available.
    locked = db.query(CurrentAccount.withdrawal_lock).filter(
        CurrentAccount.user_id == user_id, plan_account_filter(plan.id, user_id, db),
        CurrentAccount.withdrawal_lock.is_not(None)).all()
    if any((lock or {}).get("milestone_id") == mid for (lock,) in locked):
        return "This milestone unlocks withdrawals from an account. Update that account before deleting it."
    return _foreign_key_dependents(plan.id, milestone_id, user_id, db)


def _foreign_key_dependents(plan_id: uuid.UUID, milestone_id: uuid.UUID, user_id: uuid.UUID,
                            db: Session) -> str | None:
    """Name the rows whose milestone foreign keys would clear on delete.

    Those keys are ``ON DELETE SET NULL`` as a database safety net, but
    clearing them silently rewires the plan (a salary that ends at retirement
    would run for life), so the user re-points them first. The partner's
    ``retirement_milestone_id`` is left out: the engine does not read it and
    no client can change it, so blocking on it could never be resolved.
    """
    names: list[str] = []
    for model in (IncomeStream, Expense):
        names += [name for (name,) in db.query(model.name).filter(
            model.plan_id == plan_id,
            or_(model.start_milestone_id == milestone_id, model.end_milestone_id == milestone_id),
        ).order_by(model.name).all()]
    rules = db.query(CashFlowPriority).filter(
        CashFlowPriority.plan_id == plan_id,
        or_(CashFlowPriority.start_milestone_id == milestone_id, CashFlowPriority.end_milestone_id == milestone_id),
    ).order_by(CashFlowPriority.priority_rank).all()
    if rules:
        account_names = dict(db.query(CurrentAccount.id, CurrentAccount.name).filter(
            CurrentAccount.user_id == user_id, plan_account_filter(plan_id, user_id, db),
            CurrentAccount.id.in_([rule.target_account_id for rule in rules if rule.target_account_id]),
        ).all())
        loan_names = dict(db.query(Liability.id, Liability.name).filter(
            Liability.plan_id == plan_id,
            Liability.id.in_([rule.target_liability_id for rule in rules if rule.target_liability_id]),
        ).all())
        for rule in rules:
            target = account_names.get(rule.target_account_id) or loan_names.get(rule.target_liability_id)
            names.append(f"{target} allocation" if target else "Allocation rule")
    names += [name for (name,) in db.query(Liability.name).filter(
        Liability.plan_id == plan_id,
        or_(Liability.payoff_milestone_id == milestone_id, Liability.recurrence_end_milestone_id == milestone_id),
    ).order_by(Liability.name).all()]
    for period in db.query(ResidencyPeriod).filter(
            ResidencyPeriod.plan_id == plan_id,
            or_(ResidencyPeriod.start_milestone_id == milestone_id, ResidencyPeriod.end_milestone_id == milestone_id),
    ).order_by(ResidencyPeriod.rank).all():
        place = period.state_code or period.region or period.country
        names.append(f"Residence in {place}" if place else "Residence change")
    names += [name for (name,) in db.query(Milestone.name).filter(
        Milestone.plan_id == plan_id, Milestone.trigger_type == "relative",
        Milestone.relative_to_id == milestone_id, Milestone.id != milestone_id,
    ).order_by(Milestone.sort_order).all()]
    if not names:
        return None
    if len(names) == 1:
        return f"{names[0]} uses this milestone. Point it at another milestone before deleting this one."
    subject = (f"{names[0]} and {names[1]}" if len(names) == 2
               else f"{names[0]}, {names[1]} and {names[2]}" if len(names) == 3
               else f"{names[0]}, {names[1]} and {len(names) - 2} more")
    return f"{subject} use this milestone. Point them at another milestone before deleting this one."


@router.delete("/{milestone_id}", status_code=204)
def delete_milestone(
    plan_id: uuid.UUID,
    milestone_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    milestone = _get_milestone_or_404(milestone_id, plan_id, db)
    message = _blocking_reference(plan, milestone_id, current_user.id, db)
    if message is not None:
        raise api_error(409, "CONFLICT", message)
    lock_priority_revision(plan_id, db)
    db.delete(milestone)
    db.commit()
    return Response(status_code=204)

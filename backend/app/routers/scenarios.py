"""A scenario's inheritance from its Main plan (app.scenarios).

Mounted behind the plan guard: reads need an openable plan, writes an
editable one. Scenarios are created by ``POST /plans/{id}/duplicate`` with
``as_scenario``.
"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.access import present_plans
from app.auth.dependencies import get_current_user
from app.db import get_db
from app.models.plan import Plan
from app.models.user import User
from app.routers.helpers import get_plan_or_404
from app.scenarios import sync as scenarios
from app.schemas.plan import PlanRead
from app.schemas.scenario import InheritanceRead, InheritanceReset, InheritanceRestore

router = APIRouter(prefix="/plans/{plan_id}", tags=["scenarios"])


def _locked_scenario(plan_id: uuid.UUID, user: User, db: Session) -> Plan:
    """The scenario, locked; Main is only read, never locked, by scenario writes."""
    plan = get_plan_or_404(plan_id, user.id, db, for_update=True)
    if plan.parent_plan_id is None:
        raise scenarios.validation_error("This plan is not a scenario.", "plan_id")
    return plan


def _respond(plan: Plan, db: Session) -> dict:
    db.commit()
    return scenarios.inheritance(db, db.get(Plan, plan.id))


@router.get("/inheritance", response_model=InheritanceRead)
def read_inheritance(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return scenarios.inheritance(db, get_plan_or_404(plan_id, current_user.id, db))


@router.post("/inheritance/reset", response_model=InheritanceRead)
def reset_inheritance(
    plan_id: uuid.UUID,
    body: InheritanceReset,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    plan = _locked_scenario(plan_id, current_user, db)
    scenarios.reset(db, plan, body.kind, body.row_id, body.fields, body.expected_revision)
    return _respond(plan, db)


@router.post("/inheritance/restore", response_model=InheritanceRead)
def restore_inheritance(
    plan_id: uuid.UUID,
    body: InheritanceRestore,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    plan = _locked_scenario(plan_id, current_user, db)
    scenarios.restore(db, plan, body.kind, body.parent_row_id)
    return _respond(plan, db)


@router.post("/inheritance/sync", response_model=InheritanceRead)
def sync_inheritance(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    plan = _locked_scenario(plan_id, current_user, db)
    scenarios.sync_scenario(db, scenarios.require_main(db, plan), plan, recheck=True)
    return _respond(plan, db)


@router.post("/detach", response_model=PlanRead)
def detach_scenario(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Plan:
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    if plan.parent_plan_id is not None:
        scenarios.detach(db, plan)
        db.commit()
        db.refresh(plan)
    return present_plans([plan], current_user, db)[0]

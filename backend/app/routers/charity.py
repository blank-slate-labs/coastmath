import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import validation_error
from app.ledger.balances import lock_user
from app.models.account import CurrentAccount
from app.models.charity import CharityEntity
from app.models.milestone import Milestone
from app.models.plan import Plan
from app.models.user import User
from app.routers.helpers import (
    ensure_row_capacity,
    get_charity_or_404,
    get_plan_or_404,
    plan_account_filter,
    resolve_milestone_year,
    validate_milestone_window,
)
from app.schemas.charity import (
    CharityEntityCreate,
    CharityEntityRead,
    CharityEntityUpdate,
)

router = APIRouter(prefix="/plans/{plan_id}/charities", tags=["charities"])


def _validate_source(plan: Plan, entity_type: str, account_id: uuid.UUID | None, db: Session,
                     funding: str = "cash") -> None:
    if funding == "appreciated_shares" and (entity_type == "qcd" or account_id is None):
        raise validation_error(
            "A gift of shares must be a donor-advised fund or direct gift with a taxable brokerage source account.",
            "funding" if entity_type == "qcd" else "source_account_id",
            "shares need a DAF or direct gift and a source account",
        )
    if account_id is None:
        return
    if plan.plan_type == "FIXED_DATE" and plan.snapshot_conditions:
        account = plan.snapshot_conditions.get(str(account_id))
        account_type = account.get("account_type") if account else None
        owner = account.get("owner", "self") if account else None
    else:
        account = db.query(CurrentAccount).filter(
            CurrentAccount.id == account_id,
            CurrentAccount.user_id == plan.user_id,
            plan_account_filter(plan.id, plan.user_id, db),
        ).first()
        account_type = account.account_type if account else None
        owner = account.owner if account else None
    if funding == "appreciated_shares":
        if account_type != "taxable_brokerage":
            raise validation_error(
                "Shares must come from a taxable brokerage account in this plan.", "source_account_id",
                "not a taxable brokerage account in plan",
            )
        return
    if entity_type != "qcd" or account_type != "traditional_ira" or owner not in {"self", "spouse"}:
        raise validation_error(
            "QCD source must be a traditional IRA in this plan.", "source_account_id", "not an eligible IRA in plan",
        )


def _validate_window(plan: Plan, start_id: uuid.UUID | None, end_id: uuid.UUID | None, db: Session) -> None:
    milestones = {m.id: m for m in db.query(Milestone).filter(Milestone.plan_id == plan.id).all()}
    for field, mid in (("start_milestone_id", start_id), ("end_milestone_id", end_id)):
        if mid is not None and mid not in milestones:
            raise validation_error("Milestone does not belong to this plan.", field, "not found in plan")
    validate_milestone_window(plan, start_id, end_id, db)
    if start_id is None or end_id is None:
        return
    start = resolve_milestone_year(milestones[start_id], milestones, plan.birth_year)
    end = resolve_milestone_year(milestones[end_id], milestones, plan.birth_year)
    if start_id == end_id or (start is not None and start == end):
        raise validation_error(
            "Giving must end in a later year than it starts; the end year is excluded.", "end_milestone_id",
            "must be in a later year",
        )


@router.post("", response_model=CharityEntityRead, status_code=201)
def create_charity(
    plan_id: uuid.UUID,
    body: CharityEntityCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharityEntity:
    lock_user(db, current_user.id)
    plan = get_plan_or_404(plan_id, current_user.id, db)
    ensure_row_capacity(db.query(CharityEntity.id).filter(CharityEntity.plan_id == plan_id), "a charity")
    _validate_window(plan, body.start_milestone_id, body.end_milestone_id, db)
    _validate_source(plan, body.entity_type, body.source_account_id, db, body.funding)
    charity = CharityEntity(plan_id=plan_id, **body.model_dump())
    db.add(charity)
    db.commit()
    db.refresh(charity)
    return charity


@router.get("", response_model=list[CharityEntityRead])
def list_charities(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CharityEntity]:
    get_plan_or_404(plan_id, current_user.id, db)
    return db.query(CharityEntity).filter(CharityEntity.plan_id == plan_id).all()


@router.get("/{charity_id}", response_model=CharityEntityRead)
def get_charity(
    plan_id: uuid.UUID,
    charity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharityEntity:
    get_plan_or_404(plan_id, current_user.id, db)
    return get_charity_or_404(charity_id, plan_id, db)


@router.patch("/{charity_id}", response_model=CharityEntityRead)
def update_charity(
    plan_id: uuid.UUID,
    charity_id: uuid.UUID,
    body: CharityEntityUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharityEntity:
    lock_user(db, current_user.id)
    plan = get_plan_or_404(plan_id, current_user.id, db)
    charity = get_charity_or_404(charity_id, plan_id, db)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("funding", "") is None:
        changes.pop("funding")
    _validate_source(plan, changes.get("entity_type", charity.entity_type), changes.get("source_account_id", charity.source_account_id), db,
                     changes.get("funding", charity.funding or "cash"))
    _validate_window(plan, changes.get("start_milestone_id", charity.start_milestone_id), changes.get("end_milestone_id", charity.end_milestone_id), db)
    for field, value in changes.items():
        setattr(charity, field, value)
    db.commit()
    db.refresh(charity)
    return charity


@router.delete("/{charity_id}", status_code=204)
def delete_charity(
    plan_id: uuid.UUID,
    charity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    get_plan_or_404(plan_id, current_user.id, db)
    charity = get_charity_or_404(charity_id, plan_id, db)
    db.delete(charity)
    db.commit()
    return Response(status_code=204)

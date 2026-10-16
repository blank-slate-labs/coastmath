import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error, validation_error
from app.models.account import CurrentAccount
from app.models.drawdown_order import DrawdownOrder
from app.models.user import User
from app.routers.helpers import get_plan_or_404, plan_account_filter
from app.scenarios.hooks import mark_plan_changed
from app.schemas.drawdown_order import (
    DrawdownOrderBulkUpdate,
    DrawdownOrderRead,
)

router = APIRouter(prefix="/plans/{plan_id}/drawdown-order", tags=["drawdown-order"])


@router.get("", response_model=list[DrawdownOrderRead])
def list_drawdown_order(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DrawdownOrder]:
    get_plan_or_404(plan_id, current_user.id, db)
    return (
        db.query(DrawdownOrder)
        .filter(DrawdownOrder.plan_id == plan_id)
        .order_by(DrawdownOrder.rank)
        .all()
    )


@router.put("", response_model=list[DrawdownOrderRead])
def bulk_update_drawdown_order(
    plan_id: uuid.UUID,
    body: DrawdownOrderBulkUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DrawdownOrder]:
    get_plan_or_404(plan_id, current_user.id, db)

    # Validate rank uniqueness
    ranks = [item.rank for item in body.items]
    if len(ranks) != len(set(ranks)):
        raise validation_error("Duplicate rank values", "rank", "must be unique")

    # Validate source_account_id references
    account_ids = [
        item.source_account_id for item in body.items if item.source_account_id
    ]
    if account_ids:
        existing = (
            db.query(CurrentAccount.id)
            .filter(
                CurrentAccount.id.in_(account_ids),
                CurrentAccount.user_id == current_user.id,
                plan_account_filter(plan_id, current_user.id, db),
            )
            .all()
        )
        existing_ids = {row.id for row in existing}
        missing = set(account_ids) - existing_ids
        if missing:
            raise api_error(
                422, "VALIDATION_ERROR", "Invalid source_account_id references",
                [{"field": "source_account_id", "reason": f"{aid} not found"} for aid in missing],
            )

    # Delete existing, insert new. The bulk delete bypasses flush tracking,
    # so report it for scenario sync.
    db.query(DrawdownOrder).filter(
        DrawdownOrder.plan_id == plan_id
    ).delete()
    mark_plan_changed(db, plan_id, "drawdown")

    new_items = [
        DrawdownOrder(plan_id=plan_id, **item.model_dump())
        for item in body.items
    ]
    db.add_all(new_items)
    db.commit()

    return (
        db.query(DrawdownOrder)
        .filter(DrawdownOrder.plan_id == plan_id)
        .order_by(DrawdownOrder.rank)
        .all()
    )

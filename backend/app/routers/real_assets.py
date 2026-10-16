import datetime
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error, validation_error
from app.models.account import CurrentAccount
from app.models.plan import Plan
from app.models.real_asset import RealAsset
from app.models.user import User
from app.routers.helpers import (
    client_today,
    ensure_row_capacity,
    get_plan_or_404,
    get_real_asset_or_404,
    plan_scope_filter,
)
from app.schemas.real_asset import (
    RealAssetCreate,
    RealAssetRead,
    RealAssetUpdate,
    real_estate_errors,
)

router = APIRouter(prefix="/plans/{plan_id}/real-assets", tags=["real-assets"])


def _validate_liquidation_target(
    liquidation_target_account_id: uuid.UUID | None,
    user_id: uuid.UUID,
    db: Session,
    plan: Plan,
    field: str = "liquidation_target_account_id",
) -> None:
    if liquidation_target_account_id is None:
        return
    account = (
        db.query(CurrentAccount)
        .filter(
            CurrentAccount.id == liquidation_target_account_id,
            CurrentAccount.user_id == user_id,
            plan_scope_filter(plan),
        )
        .first()
    )
    if not account:
        raise validation_error(f"{field} does not reference a valid account", field, "account not found")


def _validate_sale_year(sale_year: int | None, plan: Plan, today: datetime.date) -> None:
    """A planned sale is in the plan's future: an asset sold before the plan starts is not held.

    A "Now" plan starts on ``today``, the user's local date (``client_today``).
    """
    if sale_year is None:
        return
    start = plan.start_date if plan.plan_type == "FIXED_DATE" and plan.start_date else today
    if sale_year < start.year:
        raise validation_error(
            f"Planned sale year can't be before the plan starts ({start.year}). Remove an asset already sold.",
            "sale_year", f"must be {start.year} or later",
        )


@router.post("", response_model=RealAssetRead, status_code=201)
def create_real_asset(
    plan_id: uuid.UUID,
    body: RealAssetCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> RealAsset:
    plan = get_plan_or_404(plan_id, current_user.id, db)
    ensure_row_capacity(db.query(RealAsset.id).filter(RealAsset.plan_id == plan_id), "a property")
    _validate_sale_year(body.sale_year, plan, today)
    _validate_liquidation_target(body.liquidation_target_account_id, current_user.id, db, plan)
    _validate_liquidation_target(body.purchase_funding_account_id, current_user.id, db, plan,
                                 field="purchase_funding_account_id")
    asset = RealAsset(plan_id=plan_id, **body.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.get("", response_model=list[RealAssetRead])
def list_real_assets(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RealAsset]:
    get_plan_or_404(plan_id, current_user.id, db)
    return db.query(RealAsset).filter(RealAsset.plan_id == plan_id).all()


@router.get("/{real_asset_id}", response_model=RealAssetRead)
def get_real_asset(
    plan_id: uuid.UUID,
    real_asset_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RealAsset:
    get_plan_or_404(plan_id, current_user.id, db)
    return get_real_asset_or_404(real_asset_id, plan_id, db)


@router.put("/{real_asset_id}", response_model=RealAssetRead)
def update_real_asset(
    plan_id: uuid.UUID,
    real_asset_id: uuid.UUID,
    body: RealAssetUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> RealAsset:
    plan = get_plan_or_404(plan_id, current_user.id, db)
    asset = get_real_asset_or_404(real_asset_id, plan_id, db)
    # Only a changed sale year: an older saved one never blocks unrelated edits.
    if "sale_year" in body.model_fields_set and body.sale_year != asset.sale_year:
        _validate_sale_year(body.sale_year, plan, today)
    _validate_liquidation_target(
        body.liquidation_target_account_id, current_user.id, db, plan
    )
    _validate_liquidation_target(body.purchase_funding_account_id, current_user.id, db, plan,
                                 field="purchase_funding_account_id")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(asset, field, value)
    merged = {column.key: getattr(asset, column.key) for column in RealAsset.__table__.columns}
    errors = real_estate_errors({key: float(value) if isinstance(value, Decimal) else value
                                 for key, value in merged.items()})
    if errors:
        db.rollback()
        raise api_error(
            422, "VALIDATION_ERROR", "; ".join(errors), [{"field": "real_asset", "reason": error} for error in errors],
        )
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{real_asset_id}", status_code=204)
def delete_real_asset(
    plan_id: uuid.UUID,
    real_asset_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    get_plan_or_404(plan_id, current_user.id, db)
    asset = get_real_asset_or_404(real_asset_id, plan_id, db)
    db.delete(asset)
    db.commit()
    return Response(status_code=204)

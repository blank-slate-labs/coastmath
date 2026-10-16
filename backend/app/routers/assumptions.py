import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error, validation_error
from app.models.assumption_curve import AssumptionCurve
from app.models.user import User
from app.routers.helpers import get_plan_or_404
from app.schemas.assumption_curve import (
    AssumptionCurveCreate,
    AssumptionCurveRead,
    AssumptionCurveUpdate,
)

router = APIRouter(prefix="/plans/{plan_id}/assumptions", tags=["assumptions"])


def _get_curve_or_404(
    curve_id: uuid.UUID, plan_id: uuid.UUID, db: Session
) -> AssumptionCurve:
    curve = (
        db.query(AssumptionCurve)
        .filter(AssumptionCurve.id == curve_id, AssumptionCurve.plan_id == plan_id)
        .first()
    )
    if not curve:
        raise api_error(404, "NOT_FOUND", "Assumption curve not found")
    return curve


@router.post("", response_model=AssumptionCurveRead, status_code=201)
def create_assumption(
    plan_id: uuid.UUID,
    body: AssumptionCurveCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssumptionCurve:
    get_plan_or_404(plan_id, current_user.id, db)
    existing = (
        db.query(AssumptionCurve)
        .filter(
            AssumptionCurve.plan_id == plan_id,
            AssumptionCurve.curve_type == body.curve_type,
        )
        .first()
    )
    if existing:
        raise api_error(
            409, "VALIDATION_ERROR", f"Assumption curve for '{body.curve_type}' already exists on this plan",
        )
    curve = AssumptionCurve(plan_id=plan_id, **body.model_dump())
    db.add(curve)
    db.commit()
    db.refresh(curve)
    return curve


@router.get("", response_model=list[AssumptionCurveRead])
def list_assumptions(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AssumptionCurve]:
    get_plan_or_404(plan_id, current_user.id, db)
    return (
        db.query(AssumptionCurve)
        .filter(AssumptionCurve.plan_id == plan_id)
        .all()
    )


@router.put("/{curve_id}", response_model=AssumptionCurveRead)
def update_assumption(
    plan_id: uuid.UUID,
    curve_id: uuid.UUID,
    body: AssumptionCurveUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssumptionCurve:
    get_plan_or_404(plan_id, current_user.id, db)
    curve = _get_curve_or_404(curve_id, plan_id, db)

    updates = body.model_dump(exclude_unset=True)

    # Determine the effective mode after applying updates
    effective_mode = updates.get("mode", curve.mode)

    if effective_mode == "curve":
        effective_points = updates.get("control_points", curve.control_points)
        if not effective_points:
            raise validation_error(
                "control_points required when mode is 'curve'", "control_points", "required for curve mode",
            )
    elif effective_mode == "fixed":
        effective_rate = updates.get("fixed_rate", curve.fixed_rate)
        if effective_rate is None:
            raise validation_error("fixed_rate required when mode is 'fixed'", "fixed_rate", "required for fixed mode")

    for field, value in updates.items():
        setattr(curve, field, value)
    db.commit()
    db.refresh(curve)
    return curve


@router.delete("/{curve_id}", status_code=204)
def delete_assumption(
    plan_id: uuid.UUID,
    curve_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    get_plan_or_404(plan_id, current_user.id, db)
    curve = _get_curve_or_404(curve_id, plan_id, db)
    db.delete(curve)
    db.commit()
    return Response(status_code=204)

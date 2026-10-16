import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error
from app.models.progress_point import ProgressPoint
from app.models.user import User
from app.schemas.progress_point import ProgressPointCreate, ProgressPointRead

router = APIRouter(prefix="/progress-points", tags=["progress-points"])

#: Points an account may keep: over 80 years of monthly records. The list is
#: read whole, so the cap also bounds that response.
MAX_POINTS = 1_000


def _get_progress_point_or_404(
    point_id: uuid.UUID, user_id: uuid.UUID, db: Session
) -> ProgressPoint:
    point = (
        db.query(ProgressPoint)
        .filter(ProgressPoint.id == point_id, ProgressPoint.user_id == user_id)
        .first()
    )
    if not point:
        raise api_error(404, "NOT_FOUND", "Progress point not found")
    return point


@router.post("", response_model=ProgressPointRead, status_code=201)
def create_progress_point(
    body: ProgressPointCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProgressPoint:
    existing = db.query(ProgressPoint.id).filter(ProgressPoint.user_id == current_user.id)
    if existing.limit(MAX_POINTS).count() >= MAX_POINTS:
        raise api_error(422, "VALIDATION_ERROR", "Delete an older progress entry before recording another.")
    point = ProgressPoint(user_id=current_user.id, **body.model_dump())
    db.add(point)
    db.commit()
    db.refresh(point)
    return point


@router.get("", response_model=list[ProgressPointRead])
def list_progress_points(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    since: date | None = Query(default=None),
) -> list[ProgressPoint]:
    query = db.query(ProgressPoint).filter(
        ProgressPoint.user_id == current_user.id
    )
    if since is not None:
        query = query.filter(ProgressPoint.recorded_date >= since)
    return query.order_by(ProgressPoint.recorded_date.desc()).all()


@router.delete("/{point_id}", status_code=204)
def delete_progress_point(
    point_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    point = _get_progress_point_or_404(point_id, current_user.id, db)
    db.delete(point)
    db.commit()
    return Response(status_code=204)

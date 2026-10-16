import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.models.tax_jurisdiction import TaxJurisdiction
from app.models.user import User
from app.routers.helpers import get_tax_jurisdiction_or_404
from app.schemas.tax_jurisdiction import (
    TaxJurisdictionCreate,
    TaxJurisdictionRead,
    TaxJurisdictionUpdate,
)

router = APIRouter(prefix="/tax-jurisdictions", tags=["tax-jurisdictions"])


@router.post("", response_model=TaxJurisdictionRead, status_code=201)
def create_tax_jurisdiction(
    body: TaxJurisdictionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaxJurisdiction:
    jurisdiction = TaxJurisdiction(user_id=current_user.id, **body.model_dump())
    db.add(jurisdiction)
    db.commit()
    db.refresh(jurisdiction)
    return jurisdiction


@router.get("", response_model=list[TaxJurisdictionRead])
def list_tax_jurisdictions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TaxJurisdiction]:
    return (
        db.query(TaxJurisdiction)
        .filter(TaxJurisdiction.user_id == current_user.id)
        .all()
    )


@router.get("/{jurisdiction_id}", response_model=TaxJurisdictionRead)
def get_tax_jurisdiction(
    jurisdiction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaxJurisdiction:
    return get_tax_jurisdiction_or_404(jurisdiction_id, current_user.id, db)


@router.put("/{jurisdiction_id}", response_model=TaxJurisdictionRead)
def update_tax_jurisdiction(
    jurisdiction_id: uuid.UUID,
    body: TaxJurisdictionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaxJurisdiction:
    jurisdiction = get_tax_jurisdiction_or_404(jurisdiction_id, current_user.id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(jurisdiction, field, value)
    db.commit()
    db.refresh(jurisdiction)
    return jurisdiction


@router.delete("/{jurisdiction_id}", status_code=204)
def delete_tax_jurisdiction(
    jurisdiction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    jurisdiction = get_tax_jurisdiction_or_404(jurisdiction_id, current_user.id, db)
    db.delete(jurisdiction)
    db.commit()
    return Response(status_code=204)

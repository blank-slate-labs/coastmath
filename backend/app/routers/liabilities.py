import uuid
from datetime import date

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error, validation_error
from app.ledger.balances import guard_linked_edit, lock_user
from app.models.cash_flow_priority import CashFlowPriority
from app.models.liability import Liability
from app.models.user import User
from app.routers.helpers import (
    client_today,
    ensure_row_capacity,
    get_plan_or_404,
    validate_liability_fks,
)
from app.schemas.liability import (
    LiabilityCreate,
    LiabilityRead,
    LiabilityRecurrenceFields,
    LiabilityUpdate,
)
from coastmath.engine.amortization import (
    calculate_fixed_payment,
    generate_full_schedule,
    liability_rate_to_decimal,
)

router = APIRouter(prefix="/plans/{plan_id}/liabilities", tags=["liabilities"])


def _get_liability_or_404(
    liability_id: uuid.UUID, plan_id: uuid.UUID, db: Session
) -> Liability:
    liability = (
        db.query(Liability)
        .filter(Liability.id == liability_id, Liability.plan_id == plan_id)
        .first()
    )
    if not liability:
        raise api_error(404, "NOT_FOUND", "Liability not found")
    return liability


@router.post("", response_model=LiabilityRead, status_code=201)
def create_liability(
    plan_id: uuid.UUID,
    body: LiabilityCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Liability:
    get_plan_or_404(plan_id, current_user.id, db)
    ensure_row_capacity(db.query(Liability.id).filter(Liability.plan_id == plan_id), "a debt")
    validate_liability_fks(plan_id, current_user.id, body, db)
    liability = Liability(plan_id=plan_id, **body.model_dump())
    db.add(liability)
    db.commit()
    db.refresh(liability)
    return liability


@router.get("", response_model=list[LiabilityRead])
def list_liabilities(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Liability]:
    get_plan_or_404(plan_id, current_user.id, db)
    return db.query(Liability).filter(Liability.plan_id == plan_id).all()


@router.get("/{liability_id}", response_model=LiabilityRead)
def get_liability(
    plan_id: uuid.UUID,
    liability_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Liability:
    get_plan_or_404(plan_id, current_user.id, db)
    return _get_liability_or_404(liability_id, plan_id, db)


@router.put("/{liability_id}", response_model=LiabilityRead)
def update_liability(
    plan_id: uuid.UUID,
    liability_id: uuid.UUID,
    body: LiabilityUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Liability:
    lock_user(db, current_user.id)
    get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    liability = _get_liability_or_404(liability_id, plan_id, db)
    guard_linked_edit(db, liability.id, set(body.model_fields_set), debt=True, values=body.model_dump(exclude_unset=True))
    validate_liability_fks(plan_id, current_user.id, body, db)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("interest_method", "") is None:
        # The method is required; an explicit null keeps the saved one.
        del changes["interest_method"]
    merged = {key: changes.get(key, getattr(liability, key))
              for key in ("recurrence_years", "recurrence_end_year", "recurrence_end_milestone_id")}
    try:
        LiabilityRecurrenceFields(**merged)
    except ValidationError as exc:
        message = exc.errors()[0]["msg"].removeprefix("Value error, ")
        raise validation_error(message, "recurrence_years") from exc
    for field, value in changes.items():
        setattr(liability, field, value)
    db.commit()
    db.refresh(liability)
    return liability


@router.delete("/{liability_id}", status_code=204)
def delete_liability(
    plan_id: uuid.UUID,
    liability_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    lock_user(db, current_user.id)
    get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    liability = _get_liability_or_404(liability_id, plan_id, db)
    guard_linked_edit(db, liability.id, {"principal_balance"}, debt=True)
    if db.query(CashFlowPriority.id).filter(
        CashFlowPriority.plan_id == plan_id, CashFlowPriority.target_liability_id == liability.id,
    ).first():
        raise api_error(
            409, "CONFLICT",
            "This loan receives surplus through an allocation rule. In Income allocation, remove the debt payment rule and save before deleting the loan.",
            [{"field": "target_liability_id", "reason": "referenced by allocation rules"}],
        )
    db.delete(liability)
    db.commit()
    return Response(status_code=204)


# --- Amortization schedule ---

class AmortizationRow(BaseModel):
    year: int
    principal_paid: float
    interest_paid: float
    remaining_balance: float
    cumulative_interest: float


class AmortizationResponse(BaseModel):
    schedule: list[AmortizationRow]


def _compute_amortization(liability: Liability, start_year: int | None = None) -> list[dict]:
    balance = float(liability.principal_balance)
    rate = liability_rate_to_decimal(liability.interest_rate)
    interest_method = getattr(liability, "interest_method", None) or "monthly"
    if liability.payment_type == "percent_of_balance":
        payment = float(liability.monthly_payment or 0.02)
    elif liability.monthly_payment is not None:
        payment = float(liability.monthly_payment)
    elif liability.term_months:
        payment = calculate_fixed_payment(balance, rate, liability.term_months, interest_method)
    else:
        return []
    return [
        {
            "year": row.year,
            "principal_paid": round(row.principal_paid, 2),
            "interest_paid": round(row.interest_paid, 2),
            "remaining_balance": round(row.remaining_balance, 2),
            "cumulative_interest": round(row.cumulative_interest, 2),
        }
        for row in generate_full_schedule(
            balance, rate, liability.term_months or 600, payment,
            payment_type=liability.payment_type,
            extra_payment=float(liability.extra_payment or 0),
            interest_method=interest_method,
            start_year=start_year if interest_method == "daily" else None,
        )
    ]


@router.get(
    "/{liability_id}/amortization",
    response_model=AmortizationResponse,
)
def get_amortization_schedule(
    plan_id: uuid.UUID,
    liability_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: date = Depends(client_today),
) -> dict:
    get_plan_or_404(plan_id, current_user.id, db)
    liability = _get_liability_or_404(liability_id, plan_id, db)
    # Daily accrual counts each calendar month's days from the user's current year on.
    schedule = _compute_amortization(liability, today.year)
    return {"schedule": schedule}

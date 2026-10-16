import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error, validation_error
from app.ledger.feeds import guard_connected_expense
from app.models.expense import Expense
from app.models.income import IncomeStream
from app.models.user import User
from app.routers.helpers import (
    ensure_row_capacity,
    get_plan_or_404,
    validate_account_references,
    validate_milestone_fks,
    validate_milestone_window,
)
from app.schemas.expense import (
    ExpenseCreate,
    ExpenseRead,
    ExpenseUpdate,
    sync_expense_category,
)

router = APIRouter(prefix="/plans/{plan_id}/expenses", tags=["expenses"])


def _selected_funding_ids(body: ExpenseCreate | ExpenseUpdate) -> list[uuid.UUID] | None:
    """Return the new ordered selection, falling back to the legacy scalar."""
    if body.specific_funding_source_ids is not None:
        return body.specific_funding_source_ids
    if body.specific_funding_source_id is not None:
        return [body.specific_funding_source_id]
    return None


def _normalize_funding_payload(payload: dict) -> dict:
    """Mirror the first list entry into the legacy field for old clients."""
    ids = payload.get("specific_funding_source_ids")
    if ids is not None:
        payload["specific_funding_source_ids"] = [str(account_id) for account_id in ids]
        payload["specific_funding_source_id"] = ids[0] if ids else None
    elif "specific_funding_source_id" in payload:
        # A scalar-only edit from an older client must replace the selection;
        # otherwise a saved list would silently override its new primary ID.
        payload["specific_funding_source_ids"] = None
    return payload


def _validate_payroll_deduction(
    plan_id: uuid.UUID, body: ExpenseCreate | ExpenseUpdate, db: Session
) -> None:
    is_payroll = getattr(body, "is_payroll_deduction", None)
    tied_id = getattr(body, "tied_income_id", None)

    if is_payroll and tied_id is None:
        raise validation_error(
            "Payroll deduction requires a tied_income_id", "tied_income_id",
            "required when is_payroll_deduction is true",
        )
    if tied_id is None:
        return

    # Any tied income, payroll or not, must belong to this plan.
    exists = (
        db.query(IncomeStream.id)
        .filter(IncomeStream.id == tied_id, IncomeStream.plan_id == plan_id)
        .first()
    )
    if not exists:
        raise validation_error(f"Income {tied_id} does not belong to this plan", "tied_income_id", "not found in plan")


@router.post("", response_model=ExpenseRead, status_code=201)
def create_expense(
    plan_id: uuid.UUID,
    body: ExpenseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Expense:
    plan = get_plan_or_404(plan_id, current_user.id, db)
    ensure_row_capacity(db.query(Expense.id).filter(Expense.plan_id == plan_id), "an expense")
    validate_milestone_fks(plan_id, body, db)
    validate_account_references(
        plan_id,
        _selected_funding_ids(body),
        current_user.id,
        db,
        "specific_funding_source_ids",
    )
    validate_milestone_window(plan, body.start_milestone_id, body.end_milestone_id, db, body.start_month, body.end_month, reject_empty=True)
    _validate_payroll_deduction(plan_id, body, db)
    expense = Expense(plan_id=plan_id, **_normalize_funding_payload(body.model_dump()))
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.get("", response_model=list[ExpenseRead])
def list_expenses(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Expense]:
    get_plan_or_404(plan_id, current_user.id, db)
    return db.query(Expense).filter(Expense.plan_id == plan_id).all()


@router.put("/{expense_id}", response_model=ExpenseRead)
def update_expense(
    plan_id: uuid.UUID,
    expense_id: uuid.UUID,
    body: ExpenseUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Expense:
    plan = get_plan_or_404(plan_id, current_user.id, db)
    expense = (
        db.query(Expense)
        .filter(Expense.id == expense_id, Expense.plan_id == plan_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if not expense:
        raise api_error(404, "NOT_FOUND", "Expense not found")
    changes = body.model_dump(exclude_unset=True, exclude={"expected_values"})
    guard_connected_expense(db, expense, changes)
    if body.expected_values is not None:
        expected = body.expected_values.model_dump(exclude_unset=True)
        if set(expected) != set(changes):
            raise validation_error(
                "Provide the opening value for every changed expense field.", "expected_values",
                "must match the changed fields",
            )
        # Normalize database Numeric values through the same public schema.
        # The row lock makes comparison and update one atomic operation.
        current = ExpenseRead.model_validate(expense).model_dump()
        conflicts = [field for field, value in expected.items() if current.get(field) != value]
        if conflicts:
            raise api_error(
                409, "CONFLICT",
                "This expense changed after you opened it. Your draft was not saved. Review latest saved values in this editor before retrying.",
                [{"field": field, "reason": "changed since this editor opened"} for field in conflicts],
            )
    validate_milestone_fks(plan_id, body, db)
    validate_account_references(
        plan_id,
        _selected_funding_ids(body),
        current_user.id,
        db,
        "specific_funding_source_ids",
    )
    _normalize_funding_payload(changes)
    validate_milestone_window(
        plan,
        body.start_milestone_id if "start_milestone_id" in body.model_fields_set else expense.start_milestone_id,
        body.end_milestone_id if "end_milestone_id" in body.model_fields_set else expense.end_milestone_id,
        db,
        body.start_month if "start_month" in body.model_fields_set else expense.start_month,
        body.end_month if "end_month" in body.model_fields_set else expense.end_month,
        reject_empty=bool({"start_milestone_id", "end_milestone_id", "start_month", "end_month"} & body.model_fields_set),
    )
    # For update, check payroll deduction using merged state
    is_payroll = body.is_payroll_deduction if body.is_payroll_deduction is not None else expense.is_payroll_deduction
    tied_id = body.tied_income_id if body.tied_income_id is not None else expense.tied_income_id
    if is_payroll and tied_id is None:
        raise validation_error(
            "Payroll deduction requires a tied_income_id", "tied_income_id",
            "required when is_payroll_deduction is true",
        )
    if tied_id is not None:  # Payroll or not, a tied income must belong to this plan.
        exists = (
            db.query(IncomeStream.id)
            .filter(IncomeStream.id == tied_id, IncomeStream.plan_id == plan_id)
            .first()
        )
        if not exists:
            raise validation_error(
                f"Income {tied_id} does not belong to this plan", "tied_income_id", "not found in plan",
            )
    # After the stale-write check, which compares only the fields the client sent.
    sync_expense_category(changes, expense.discretionary_percent)
    for field, value in changes.items():
        setattr(expense, field, value)
    db.commit()
    db.refresh(expense)
    return expense


@router.delete("/{expense_id}", status_code=204)
def delete_expense(
    plan_id: uuid.UUID,
    expense_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    get_plan_or_404(plan_id, current_user.id, db)
    expense = (
        db.query(Expense)
        .filter(Expense.id == expense_id, Expense.plan_id == plan_id)
        .first()
    )
    if not expense:
        raise api_error(404, "NOT_FOUND", "Expense not found")
    guard_connected_expense(db, expense)
    db.delete(expense)
    db.commit()
    return Response(status_code=204)

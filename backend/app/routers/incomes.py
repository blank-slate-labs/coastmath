import uuid
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error, validation_error
from app.models.cash_flow_priority import CashFlowPriority
from app.models.income import IncomeStream
from app.models.user import User
from app.routers.helpers import (
    ensure_row_capacity,
    get_plan_or_404,
    validate_milestone_fks,
    validate_milestone_window,
)
from app.schemas.income import (
    IncomeCreate,
    IncomeRead,
    IncomeUpdate,
    validate_income_extensions,
    validate_ss_benefit_basis,
)
from coastmath.engine.income_events import validate_income_formulas
from coastmath.schemas.amount_frequency import check_hourly_fields, hourly_annual_amount

router = APIRouter(prefix="/plans/{plan_id}/incomes", tags=["incomes"])


def _validate_formulas(plan_id, db, candidate=None, removed=None):
    rows = db.query(IncomeStream).filter(IncomeStream.plan_id == plan_id).all()
    rows = [row for row in rows if row.id != removed and (candidate is None or row.id != candidate.id)]
    if candidate is not None:
        rows.append(candidate)
    try:
        validate_income_formulas(rows)
    except ValueError as exc:
        raise validation_error(str(exc), "pension_formula") from exc


_HOURLY_FIELDS = ("hourly_rate", "hours_per_week")


def _merge_hourly_pay(income: IncomeStream, changes: dict) -> None:
    """Keep hourly pay and ``annual_amount`` consistent for a partial update.

    An hourly income's annual amount is always its rate x hours x 52. A
    client that changes only the annual amount of an hourly income (one that
    does not know hourly pay) switches it to an annual amount; any other
    unit clears the hourly fields.
    """
    frequency = changes.get("amount_frequency", income.amount_frequency)
    if (frequency == "hourly" and "annual_amount" in changes and "amount_frequency" not in changes
            and not any(key in changes for key in _HOURLY_FIELDS)
            and income.hourly_rate is not None and income.hours_per_week is not None
            and changes["annual_amount"] != hourly_annual_amount(income.hourly_rate, income.hours_per_week)):
        frequency = changes["amount_frequency"] = "annual"
    if frequency == "hourly":
        rate = changes.get("hourly_rate", income.hourly_rate)
        hours = changes.get("hours_per_week", income.hours_per_week)
        try:
            check_hourly_fields(frequency, rate, hours)
        except ValueError as exc:
            raise validation_error(str(exc), "hourly_rate") from exc
        changes["annual_amount"] = hourly_annual_amount(rate, hours)
        return
    for key in _HOURLY_FIELDS:
        if getattr(income, key) is not None or changes.get(key) is not None:
            changes[key] = None


@router.post("", response_model=IncomeRead, status_code=201)
def create_income(
    plan_id: uuid.UUID,
    body: IncomeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IncomeStream:
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    ensure_row_capacity(db.query(IncomeStream.id).filter(IncomeStream.plan_id == plan_id), "an income")
    validate_milestone_fks(plan_id, body, db)
    validate_milestone_window(plan, body.start_milestone_id, body.end_milestone_id, db, body.start_month, body.end_month, reject_empty=True)
    income = IncomeStream(id=uuid.uuid4(), plan_id=plan_id, **body.model_dump())
    _validate_formulas(plan_id, db, income)
    db.add(income)
    db.commit()
    db.refresh(income)
    return income


@router.get("", response_model=list[IncomeRead])
def list_incomes(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[IncomeStream]:
    get_plan_or_404(plan_id, current_user.id, db)
    return db.query(IncomeStream).filter(IncomeStream.plan_id == plan_id).all()


@router.put("/{income_id}", response_model=IncomeRead)
def update_income(
    plan_id: uuid.UUID,
    income_id: uuid.UUID,
    body: IncomeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IncomeStream:
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    income = (
        db.query(IncomeStream)
        .filter(IncomeStream.id == income_id, IncomeStream.plan_id == plan_id)
        .first()
    )
    if not income:
        raise api_error(404, "NOT_FOUND", "Income not found")
    validate_milestone_fks(plan_id, body, db)
    validate_milestone_window(
        plan,
        body.start_milestone_id if "start_milestone_id" in body.model_fields_set else income.start_milestone_id,
        body.end_milestone_id if "end_milestone_id" in body.model_fields_set else income.end_milestone_id,
        db,
        body.start_month if "start_month" in body.model_fields_set else income.start_month,
        body.end_month if "end_month" in body.model_fields_set else income.end_month,
        reject_empty=bool({"start_milestone_id", "end_milestone_id", "start_month", "end_month"} & body.model_fields_set),
    )
    changes = body.model_dump(exclude_unset=True)
    if "tax_category" not in changes and any(key in changes and changes[key] != getattr(income,key)
            for key in ("is_earned_income", "is_self_employed", "is_social_security")):
        # Older clients can still change the legacy flags deliberately.
        changes["tax_category"] = None
    merged = {key: changes[key] if key in changes else getattr(income, key)
              for key in ("ss_benefit_basis", "pia_monthly", "claiming_age", "tax_category")}
    try:
        validate_ss_benefit_basis(
            merged["ss_benefit_basis"],
            None if merged["pia_monthly"] is None else float(merged["pia_monthly"]),
            merged["claiming_age"], merged["tax_category"],
        )
    except ValueError as exc:
        raise validation_error(str(exc), "ss_benefit_basis") from exc
    extension = {key: changes[key] if key in changes else getattr(income, key)
                 for key in ("growth_schedule", "ex_spouse", "is_social_security", "pension_formula")}
    try:
        validate_income_extensions(
            growth_schedule=extension["growth_schedule"], ex_spouse=extension["ex_spouse"],
            ss_benefit_basis=merged["ss_benefit_basis"], tax_category=merged["tax_category"],
            is_social_security=extension["is_social_security"], pension_formula=extension["pension_formula"],
        )
    except ValueError as exc:
        field = "ex_spouse" if "former spouse" in str(exc) else "growth_schedule"
        raise validation_error(str(exc), field) from exc
    _merge_hourly_pay(income, changes)
    merged_income = SimpleNamespace(**{column.key: changes.get(column.key, getattr(income, column.key))
                                       for column in IncomeStream.__table__.columns})
    _validate_formulas(plan_id, db, merged_income)
    for field, value in changes.items():
        setattr(income, field, value)
    db.commit()
    db.refresh(income)
    return income


@router.delete("/{income_id}", status_code=204)
def delete_income(
    plan_id: uuid.UUID,
    income_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    # Serialize dependency checks with allocation replacements.
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    income = (
        db.query(IncomeStream)
        .filter(IncomeStream.id == income_id, IncomeStream.plan_id == plan_id)
        .first()
    )
    if not income:
        raise api_error(404, "NOT_FOUND", "Income not found")
    referenced = db.query(CashFlowPriority.id).filter(
        CashFlowPriority.plan_id == plan_id,
        CashFlowPriority.source_income_id == income_id,
    ).first()
    if referenced:
        raise api_error(
            409, "CONFLICT",
            "This income funds an allocation rule. In Income allocation, remove the rule or choose another source income and save before deleting this income.",
            [{"field": "source_income_id", "reason": "referenced by allocation rules"}],
        )
    _validate_formulas(plan_id, db, removed=income_id)
    plan.priorities_revision += 1
    db.delete(income)
    db.commit()
    return Response(status_code=204)

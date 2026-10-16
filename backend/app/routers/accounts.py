import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error, validation_error
from app.ledger.balances import guard_linked_edit, lock_user
from app.models.account import CurrentAccount
from app.models.cash_flow_priority import CashFlowPriority
from app.models.charity import CharityEntity
from app.models.drawdown_order import DrawdownOrder
from app.models.expense import Expense
from app.models.liability import Liability
from app.models.milestone import Milestone
from app.models.plan import Plan
from app.models.real_asset import RealAsset
from app.models.user import User
from app.routers.helpers import (
    ensure_row_capacity,
    get_account_or_404,
    get_plan_or_404,
    insert_into_drawdown_orders,
    plan_account_filter,
    reject_joint_individual_account,
    validate_withdrawal_lock,
)
from app.schemas.account import AccountCreate, AccountRead, AccountUpdate
from app.schemas.milestone import condition_references
from coastmath.schemas.intl_settings import check_account_kind, plan_countries

router = APIRouter(prefix="/accounts", tags=["accounts"])
plan_router = APIRouter(prefix="/plans/{plan_id}/accounts", tags=["plan accounts"])


def validate_account_kind(kind_ref: str | None, plan: Plan | None, user_id: uuid.UUID, db: Session) -> None:
    """A country account kind must belong to a country the plan uses.

    A legacy shared account (no plan) may use a country of any of the
    user's shared plans.
    """
    if kind_ref is None:
        return
    plans = [plan] if plan is not None else db.query(Plan).filter(
        Plan.user_id == user_id, Plan.client_id.is_(None)).all()
    countries = set().union(*(plan_countries(p.tax_country or "US", p.residency_periods) for p in plans)) if plans else {"US"}
    try:
        check_account_kind(kind_ref, countries)
    except ValueError as exc:
        raise validation_error(f"Account was not saved: {exc}", "intl_account_kind", str(exc)) from None


#: Compatibility name for the importers; new code imports
#: ``app.routers.helpers.insert_into_drawdown_orders``.
_insert_into_drawdown_orders = insert_into_drawdown_orders


@router.post("", response_model=AccountRead, status_code=201)
def create_account(
    body: AccountCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    plan_id: uuid.UUID | None = None,
) -> CurrentAccount:
    reject_joint_individual_account(body.account_type, body.owner)
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True) if plan_id else None
    pool_plan_id = plan.id if plan and plan.client_id else None
    pool = CurrentAccount.plan_id == pool_plan_id if pool_plan_id else CurrentAccount.plan_id.is_(None)
    ensure_row_capacity(db.query(CurrentAccount.id).filter(CurrentAccount.user_id == current_user.id, pool), "an account")
    values = body.model_dump()
    validate_withdrawal_lock(values["withdrawal_lock"], current_user.id, db, plan.id if plan else None)
    validate_account_kind(values["intl_account_kind"], plan, current_user.id, db)
    account = CurrentAccount(user_id=current_user.id, plan_id=pool_plan_id, **values)
    db.add(account)
    db.flush()
    insert_into_drawdown_orders(account, current_user.id, db)
    db.commit()
    db.refresh(account)
    return account


@router.get("", response_model=list[AccountRead])
def list_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    plan_id: uuid.UUID | None = None,
) -> list[CurrentAccount]:
    return (
        db.query(CurrentAccount)
        .filter(CurrentAccount.user_id == current_user.id)
        .filter(plan_account_filter(plan_id, current_user.id, db) if plan_id else CurrentAccount.plan_id.is_(None))
        .order_by(CurrentAccount.id)
        .all()
    )


@router.put("/{account_id}", response_model=AccountRead)
def update_account(
    account_id: uuid.UUID,
    body: AccountUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    plan_id: uuid.UUID | None = None,
) -> CurrentAccount:
    lock_user(db, current_user.id)
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True) if plan_id else None
    account = get_account_or_404(account_id, current_user.id, db, plan_id)
    guard_linked_edit(db, account.id, set(body.model_fields_set), values=body.model_dump(exclude_unset=True))
    # Validate against the complete saved record for partial updates, then
    # persist the normalized account atomically (including type changes).
    values = {key:getattr(account,key) for key in AccountCreate.model_fields}
    values.update(body.model_dump(exclude_unset=True))
    if body.investment_settings is not None and account.investment_settings:
        # Shipped native clients rebuild investment_settings from the keys
        # they know. Keep stored keys a request omits; an explicit null still
        # clears one, and a null object still clears them all.
        values["investment_settings"] = {**account.investment_settings, **values["investment_settings"]}
    try:
        values = AccountCreate.model_validate(values).model_dump()
    except ValidationError as error:
        raise api_error(
            422, "VALIDATION_ERROR", "Account was not saved: review the inheritance settings",
            [{"field": ".".join(str(part) for part in e["loc"]) or "inheritance_settings", "reason": e["msg"]}
             for e in error.errors()],
        ) from error
    # Check a changed milestone lock only, so a lock whose milestone was later
    # removed with its plan never blocks unrelated edits.
    if values["withdrawal_lock"] != account.withdrawal_lock:
        validate_withdrawal_lock(values["withdrawal_lock"], current_user.id, db, account.plan_id or plan_id)
    if values["intl_account_kind"] != account.intl_account_kind:
        validate_account_kind(values["intl_account_kind"], plan, current_user.id, db)
    # A legacy joint IRA, 401(k) or HSA still saves edits to other fields; only
    # changing its owner or type into that combination is rejected.
    if values["owner"] != account.owner or values["account_type"] != account.account_type:
        reject_joint_individual_account(values["account_type"], values["owner"])
    payer = db.query(CharityEntity.funding).filter(CharityEntity.source_account_id == account.id).first()
    if payer is not None and payer.funding == "appreciated_shares":
        if values["account_type"] != "taxable_brokerage":
            raise api_error(
                409, "CONFLICT", "This account funds a gift of shares. Update that gift before changing its type.",
            )
    elif payer is not None and values["account_type"] != "traditional_ira":
        raise api_error(
            409, "CONFLICT", "This IRA is used by charitable giving. Update that payer before changing its type.",
        )
    for field, value in values.items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=204)
def delete_account(
    account_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    plan_id: uuid.UUID | None = None,
) -> Response:
    lock_user(db, current_user.id)
    if plan_id:
        get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    account = get_account_or_404(account_id, current_user.id, db, plan_id)
    guard_linked_edit(db, account.id, {"balance"})

    payer = db.query(CharityEntity.funding).filter(CharityEntity.source_account_id == account.id).first()
    if payer is not None:
        message = ("This account funds a gift of shares. Update that gift before deleting it."
                   if payer.funding == "appreciated_shares"
                   else "This IRA is used by charitable giving. Update that payer before deleting it.")
        raise api_error(409, "CONFLICT", message)

    condition_rows = db.query(Milestone).join(Plan).filter(Plan.user_id == current_user.id).all()
    if any(str(account.id) in condition_references(row.conditions)[1] for row in condition_rows):
        raise api_error(
            409, "CONFLICT",
            "This account is used by milestone conditions. Update those conditions before deleting it.",
        )

    # Waterfall priorities are user-configured allocations — block delete.
    priority_ref = (
        db.query(CashFlowPriority)
        .filter((CashFlowPriority.target_account_id == account.id) | (CashFlowPriority.source_account_id == account.id))
        .first()
    )
    if priority_ref:
        raise api_error(
            409, "CONFLICT", "This account is used by Income allocation. Remove those rules before deleting it.",
        )

    expense_refs = db.query(Expense).filter(Expense.specific_funding_source_id == account.id).first()
    if expense_refs is None:
        expense_refs = next(
            (
                expense
                for expense in db.query(Expense).filter(Expense.specific_funding_source_ids.is_not(None)).all()
                if str(account.id) in {str(value) for value in (expense.specific_funding_source_ids or [])}
            ),
            None,
        )
    if expense_refs is not None:
        raise api_error(
            409, "CONFLICT",
            "This account is used by an expense, debt, or property. Remove that reference before deleting it.",
        )
    for model, field in [(Liability, Liability.offset_account_id), (RealAsset, RealAsset.liquidation_target_account_id),
                         (RealAsset, RealAsset.purchase_funding_account_id)]:
        if db.query(model.id).filter(field == account.id).first():
            raise api_error(
                409, "CONFLICT",
                "This account is used by an expense, debt, or property. Remove that reference before deleting it.",
            )
    linked_plans = db.query(Plan).filter(Plan.user_id == current_user.id).all()
    if any(str((p.sepp_settings or {}).get("source_account_id", "")) == str(account.id) or
           str(account.id) in (p.snapshot_conditions or {}) or
           str(account.id) in {str(value) for value in (p.cash_reserve_settings or {}).get("account_ids", [])}
           for p in linked_plans):
        raise api_error(
            409, "CONFLICT",
            "This account is used by a withdrawal strategy or opening snapshot. Update that reference before deleting it.",
        )

    # Drawdown entries are meaningless without the account — remove them
    # and compact the remaining ranks in each affected plan.
    drawdown_refs = (
        db.query(DrawdownOrder)
        .filter(DrawdownOrder.source_account_id == account.id)
        .all()
    )
    affected_plan_ids = {ref.plan_id for ref in drawdown_refs}
    for ref in drawdown_refs:
        db.delete(ref)
    db.flush()
    for affected_plan_id in affected_plan_ids:
        remaining = (
            db.query(DrawdownOrder)
            .filter(DrawdownOrder.plan_id == affected_plan_id)
            .order_by(DrawdownOrder.rank)
            .all()
        )
        for i, entry in enumerate(remaining):
            entry.rank = i + 1

    db.delete(account)
    db.commit()
    return Response(status_code=204)


# Same implementation and validation, with an explicit plan-scoped URL.
plan_router.add_api_route("", list_accounts, methods=["GET"], response_model=list[AccountRead])
plan_router.add_api_route("", create_account, methods=["POST"], response_model=AccountRead, status_code=201)
plan_router.add_api_route("/{account_id}", update_account, methods=["PUT"], response_model=AccountRead)
plan_router.add_api_route("/{account_id}", delete_account, methods=["DELETE"], status_code=204)

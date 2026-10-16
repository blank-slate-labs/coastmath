"""Reviewed balance links from any provider's account into planning records.

Provider-neutral: a link pushes a ledger account's current balance into one
plan account or debt the customer chose. Lock order is user, plan, target.
Unavailable data and fixed-date plans keep their last saved inputs; a link
never changes assumptions, basis or payment rules. Provider-specific code
(which accounts exist and whether their connection is live) passes its own
lookups in.
"""
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.clock import aware, utcnow
from app.errors import api_error
from app.ledger.accounts import UNCONFIRMED_TYPE
from app.models.account import CurrentAccount
from app.models.financial_connection import (
    FinancialBalanceLink,
    FinancialConnection,
    FinancialSource,
    FinancialSyncEvent,
)
from app.models.liability import Liability
from app.models.user import User
from app.routers.helpers import (
    get_account_or_404,
    get_plan_or_404,
    insert_into_drawdown_orders,
    reject_joint_individual_account,
    validate_liability_fks,
    validate_withdrawal_lock,
)

MAX_BALANCE = Decimal("9999999999999.99")
DEBT_TYPES = frozenset({"CREDIT", "LOAN"})
#: Providers that report a raw balance sign; the ledger stores the amount owed
#: for CREDIT and LOAN accounts once the customer confirms the type.
RAW_SIGN_PROVIDERS = frozenset({"simplefin"})
CENT = Decimal("0.01")
SUGGESTED_TYPES = {
    "CHECKING": "checking", "SAVINGS": "savings", "CASH_MANAGEMENT": "checking",
    "MONEY_MARKET": "savings", "CD": "savings", "IRA": "traditional_ira",
    "ROTH": "roth_ira", "ROTH_401K": "roth_401k", "PLAN_401K": "traditional_401k",
    "BROKERAGE": "taxable_brokerage", "TAXABLE": "taxable_brokerage",
    "HSA": "hsa", "PLAN_529": "five_twenty_nine",
    # Same engine treatment as the suggested type. Suggestions apply only to
    # newly linked accounts. Subtypes whose rules the aggregator cannot settle
    # (457(b), which may be nongovernmental, TSP, pensions, generic
    # "RETIREMENT") stay unmapped so the customer chooses their tax treatment.
    "PLAN_403B": "traditional_403b", "PLAN_401A": "traditional_401a", "ROTH_403B": "roth_403b",
    "SEP_IRA": "traditional_ira", "SIMPLE_IRA": "traditional_ira", "SPOUSAL_IRA": "traditional_ira",
    "ROLLOVER": "traditional_ira", "SPOUSAL_ROTH_IRA": "roth_ira",
    "INDIVIDUAL": "taxable_brokerage", "JTWROS": "taxable_brokerage", "JTIC": "taxable_brokerage",
    "JOINT_TENANTS_COMMUNITY_PROPERTY": "taxable_brokerage", "JOINT_TENANTS_TENANTS_BY_ENTIRETY": "taxable_brokerage",
}


def fail(message: str, status: int = 409, code: str = "CONFLICT") -> None:
    raise api_error(status, code, message)


def lock_user(db: Session, user_id: UUID) -> User:
    user = db.query(User).filter(User.id == user_id).with_for_update().populate_existing().first()
    if not user:
        fail("Account no longer exists.", 401, "AUTH_REQUIRED")
    return user


def signed_balance(raw: Decimal | None, account_type: str | None) -> Decimal | None:
    """A raw provider balance in the ledger convention: amount owed for debts, held otherwise."""
    if raw is None or not raw.is_finite() or abs(raw) > MAX_BALANCE:
        return None
    return (-raw if account_type in DEBT_TYPES else raw).quantize(CENT)


def save_source(db: Session, source: FinancialSource, connection: FinancialConnection, values: dict,
                stamp: datetime, balance: Decimal | None, now: datetime) -> FinancialSource:
    """Write one provider read into ``source``; any change bumps its revision.

    ``values`` are the provider's fields for the account. A late read can never
    regress a newer balance: ``balance`` is written only when ``stamp`` is not
    older than the stored balance time.
    """
    if connection.provider_connection_id not in (source.connection_ids or []):
        source.connection_ids = [*(source.connection_ids or []), connection.provider_connection_id]
    if source.balance_updated_at is None or aware(stamp) >= aware(source.balance_updated_at):
        values = {**values, "balance": balance, "balance_updated_at": stamp}
    changed = source.revision == 0 or any(_differs(getattr(source, key), value) for key, value in values.items())
    for key, value in values.items():
        setattr(source, key, value)
    if changed:
        source.revision += 1
    source.fetched_at = now
    db.flush()
    return source


def _differs(saved, value) -> bool:
    if isinstance(saved, datetime) and isinstance(value, datetime):
        return aware(saved) != aware(value)
    return saved != value


def retype_balance(source: FinancialSource, previous_type: str | None) -> None:
    """Recompute a raw-sign provider's stored balance after the customer changes the type."""
    if source.provider not in RAW_SIGN_PROVIDERS or source.balance is None:
        return
    if (previous_type in DEBT_TYPES) != (source.account_type in DEBT_TYPES):
        source.balance = -source.balance


def source_problem(source: FinancialSource, now: datetime | None = None) -> str | None:
    """Why this account's balance cannot update a plan now, or None."""
    if source.account_type == UNCONFIRMED_TYPE:
        return "Confirm this account's type before using its balance."
    if source.status != "ACTIVE":
        return "This account is inactive. Reconnect the institution before using new balances."
    if source.currency != "USD":
        return "Only USD balances can be used in the current calculation engine. No currency conversion is applied."
    if source.balance is None:
        return "The institution did not supply a valid current balance. The saved plan balance is unchanged."
    if source.balance < 0:
        return "Negative balances require review; overdrafts, credits and margin debt are not converted automatically."
    if source.account_type not in {"DEPOSITORY", "INVESTMENT", "CREDIT", "LOAN"} or source.subtype == "BROKERAGE_MARGIN":
        return "This account requires manual modeling; its value is not imported automatically."
    if not source.balance_updated_at:
        return "The institution did not supply a balance date. The saved plan balance is unchanged."
    age = (now or utcnow()) - aware(source.balance_updated_at)
    if age < timedelta(minutes=-5):
        return "The provider reported a future balance date. The saved plan balance is unchanged."
    if age > timedelta(days=7):
        return "The reported balance date is more than seven days old. Reconnect or update the account manually."
    return None


def write_balance(db: Session, link: FinancialBalanceLink, source: FinancialSource, target, field: str) -> bool:
    old = Decimal(str(getattr(target, field)))
    new = source.balance
    if new is None:
        return False
    if old != new or link.source_revision != source.revision:
        db.add(FinancialSyncEvent(user_id=link.user_id, link_id=link.id, target_id=target.id,
                                 target_kind="account" if link.account_id else "liability", source_id=source.id,
                                 source_revision=source.revision, old_balance=old, new_balance=new))
    setattr(target, field, new)
    link.last_applied_balance = new
    link.source_revision = source.revision
    link.error = None
    return old != new


def apply_links(db: Session, source: FinancialSource, now: datetime | None = None) -> int:
    """Push this account's balance through every reviewed link; problems pause the link."""
    changed = 0
    links = db.query(FinancialBalanceLink).filter_by(source_id=source.id).order_by(FinancialBalanceLink.plan_id).all()
    for link in links:
        plan = get_plan_or_404(link.plan_id, source.user_id, db, for_update=True)
        problem = source_problem(source, now)
        if plan.plan_type != "NOW":
            problem = "Sync is paused for this fixed-date plan. Its historical inputs are preserved."
        if link.source_type != source.account_type or link.source_subtype != source.subtype:
            problem = "The institution changed the account classification. Unlink and review the account again."
        target = db.get(CurrentAccount, link.account_id) if link.account_id else db.get(Liability, link.liability_id)
        if not target:
            problem = "The planning record was removed. Unlink this account."
        field = "balance" if link.account_id else "principal_balance"
        if target and Decimal(str(getattr(target, field))) != link.last_applied_balance:
            problem = "The saved balance changed outside sync. Unlink and review it before syncing again."
        if problem:
            link.error = problem
            continue
        changed += write_balance(db, link, source, target, field)
    return changed


def link_source(db: Session, user_id: UUID, body, find_source: Callable[[], FinancialSource | None],
                is_connected: Callable[[FinancialSource], bool], now: datetime | None = None) -> FinancialBalanceLink:
    """Create a reviewed link from ``body`` (a ``LinkBalanceRequest``).

    ``find_source`` returns the customer's account or None; ``is_connected``
    says whether its provider connection can still refresh the balance.
    """
    lock_user(db, user_id)
    plan = get_plan_or_404(body.plan_id, user_id, db, for_update=True)
    source = find_source()
    if not source:
        fail("Connected account not found.", 404, "NOT_FOUND")
    if plan.plan_type != "NOW":
        fail("Use a Now plan for live balances. Fixed-date snapshots stay unchanged.")
    if not is_connected(source):
        fail("Reconnect this institution before linking balances.")
    if body.source_revision != source.revision:
        fail("The institution balance changed while you were reviewing it. Reload and review the latest value.")
    if problem := source_problem(source, now):
        fail(problem, 422, "VALIDATION_ERROR")
    source_id = source.id
    debt = source.account_type in DEBT_TYPES
    if debt != bool(body.liability_id or body.new_liability):
        fail("Credit cards and loans must be linked to a debt; assets must be linked to an account.", 422, "VALIDATION_ERROR")
    if not debt and not plan.client_id and not body.acknowledge_shared_accounts:
        fail("These household accounts are shared across legacy plans. Confirm the shared balance change.")
    if db.query(FinancialBalanceLink.id).filter_by(source_id=source_id, plan_id=plan.id).first():
        fail("This institution account is already linked to this plan. Unlink it before changing the mapping.")
    if not debt and not plan.client_id and db.query(FinancialBalanceLink.id).join(
        CurrentAccount, CurrentAccount.id == FinancialBalanceLink.account_id).filter(
            FinancialBalanceLink.source_id == source_id, CurrentAccount.plan_id.is_(None)).first():
        fail("This institution account already updates a shared household account. Use that existing record across your plans.")
    if body.new_account or body.new_liability:
        # Matching masks/names are clues, never proof of identity. User must review duplicates.
        existing = db.query(Liability.id).filter_by(plan_id=plan.id).first() if debt else db.query(CurrentAccount.id).filter(
            CurrentAccount.user_id == user_id,
            CurrentAccount.plan_id == plan.id if plan.client_id else CurrentAccount.plan_id.is_(None)).first()
        if existing and not body.acknowledge_duplicate_risk:
            fail("Review existing accounts first. Confirm that creating a new record will not count the same money twice.")
    field = "principal_balance" if debt else "balance"
    if body.account_id:
        target = get_account_or_404(body.account_id, user_id, db, plan.id)
    elif body.liability_id:
        target = db.query(Liability).filter_by(id=body.liability_id, plan_id=plan.id).first()
        if not target:
            fail("Debt not found in this plan.", 404, "NOT_FOUND")
    elif body.new_account:
        if body.new_account.account_type == "taxable_brokerage" and body.new_account.cost_basis is None:
            fail("Enter the taxable account's cost basis; a balance cannot establish its tax basis.", 422, "VALIDATION_ERROR")
        reject_joint_individual_account(body.new_account.account_type, body.new_account.owner, "new_account.owner")
        new_account = body.new_account.model_dump()
        validate_withdrawal_lock(new_account["withdrawal_lock"], user_id, db, plan.id)
        target = CurrentAccount(user_id=user_id, plan_id=plan.id if plan.client_id else None, **new_account)
        db.add(target)
        db.flush()
        insert_into_drawdown_orders(target, user_id, db)
    else:
        validate_liability_fks(plan.id, user_id, body.new_liability, db)
        target = Liability(plan_id=plan.id, **body.new_liability.model_dump())
        db.add(target)
        db.flush()
    if (body.account_id or body.liability_id) and Decimal(str(getattr(target, field))) != body.expected_balance:
        fail("The saved balance changed while you were reviewing it. Reload and review before linking.")
    if not debt and target.account_type == "taxable_brokerage" and target.cost_basis is None:
        fail("Enter the taxable account's cost basis in Accounts before linking it.", 422, "VALIDATION_ERROR")
    if db.query(FinancialBalanceLink.id).filter(or_(FinancialBalanceLink.account_id == target.id, FinancialBalanceLink.liability_id == target.id)).first():
        fail("This planning record already has a connection. Unlink it before switching providers.")
    link = FinancialBalanceLink(user_id=user_id, source_id=source.id, plan_id=plan.id,
        account_id=None if debt else target.id, liability_id=target.id if debt else None,
        last_applied_balance=getattr(target, field), source_revision=0, source_type=source.account_type, source_subtype=source.subtype)
    db.add(link)
    db.flush()
    write_balance(db, link, source, target, field)
    return link


def guard_linked_edit(db: Session, target_id: UUID, fields: set[str], *, debt: bool = False, values: dict | None = None) -> None:
    protected = {"principal_balance"} if debt else {"balance", "account_type"}
    if not fields & protected:
        return
    column = FinancialBalanceLink.liability_id if debt else FinancialBalanceLink.account_id
    if db.query(FinancialBalanceLink.id).filter(column == target_id).first():
        # Existing editors send full records. Permit unchanged linked fields so
        # users can still edit names, cost basis and other manual assumptions.
        target = db.get(Liability if debt else CurrentAccount, target_id)
        if values is not None and target:
            changed = False
            for field in fields & protected:
                saved, proposed = getattr(target, field), values.get(field)
                if field != "account_type" and proposed is not None:
                    saved, proposed = Decimal(str(saved)), Decimal(str(proposed))
                changed |= saved != proposed
            if not changed:
                return
        fail("This balance is linked to an institution. Unlink it in Connections before editing it manually.")

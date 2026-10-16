"""Shared router helpers: owned-record lookups, cross-record validation and
the saved-plan loader.

Feature routers, ledger services and scenario sync import these. This module
must not import any feature router (``app.routers.<feature>``) or the ledger
services, which import it.
"""

import datetime
import math
import uuid

from fastapi import Header
from sqlalchemy.orm import Session, selectinload

from app.access import ensure_plan_openable
from app.engine.plan_converter import plan_to_engine_data
from app.errors import api_error, validation_error
from app.models.account import CurrentAccount
from app.models.charity import CharityEntity
from app.models.drawdown_order import DrawdownOrder
from app.models.milestone import Milestone
from app.models.plan import Plan
from app.models.real_asset import RealAsset
from app.models.tax_jurisdiction import TaxJurisdiction
from app.models.user import User
from app.schemas.account import JOINT_OWNER_REASON, joint_owner_not_allowed
from app.schemas.expense import ExpenseCreate, ExpenseUpdate
from app.schemas.income import IncomeCreate, IncomeUpdate
from app.schemas.liability import LiabilityCreate, LiabilityUpdate
from coastmath.engine import intl_bridge
from coastmath.engine.account_types import ROTH_TYPES, TRADITIONAL_RETIREMENT_TYPES
from coastmath.engine.household_lifecycle import simulation_end_year
from coastmath.engine.intl_regime import validate_regime_settings
from coastmath.engine.milestones import resolve_deterministic_milestones
from coastmath.engine.person_healthcare import validate_person_healthcare_plan
from coastmath.engine.plan_validation import (
    validate_account_history,
    validate_roth_conversion_rules,
    validate_transfer_rules,
)
from coastmath.engine.types import PlanData


def get_account_or_404(
    account_id: uuid.UUID, user_id: uuid.UUID, db: Session, plan_id: uuid.UUID | None = None
) -> CurrentAccount:
    account = (
        db.query(CurrentAccount)
        .filter(CurrentAccount.id == account_id, CurrentAccount.user_id == user_id)
        .filter(plan_account_filter(plan_id, user_id, db) if plan_id else CurrentAccount.plan_id.is_(None))
        .first()
    )
    if not account:
        raise api_error(404, "NOT_FOUND", "Account not found")
    return account


def plan_scope_filter(plan: Plan):
    """Accounts an already loaded plan may use.

    A client plan uses only its own accounts (``plan_id`` is the plan); any
    other plan uses the explicit legacy pool saved without a plan.
    """
    return CurrentAccount.plan_id == plan.id if plan.client_id is not None else CurrentAccount.plan_id.is_(None)


def plan_account_filter(plan_id: uuid.UUID, user_id: uuid.UUID, db: Session):
    """``plan_scope_filter`` for a plan known only by id.

    Loads the plan (404 unless ``user_id`` owns it); a route that already
    holds the plan should call ``plan_scope_filter`` instead.
    """
    return plan_scope_filter(get_plan_or_404(plan_id, user_id, db))


def snapshot_account(
    account_id: str, info: dict, user_id: uuid.UUID, *, default_name: str = ""
) -> CurrentAccount:
    """A transient account from one ``Plan.snapshot_conditions`` entry.

    A fixed-date plan outside a client workspace keeps its historical account
    values in that JSON, keyed by account id. The constructor sets up
    attribute instrumentation; callers decide whether the account is ever
    added to the session. ``default_name`` names an entry saved without one.
    """
    return CurrentAccount(
        id=uuid.UUID(account_id), user_id=user_id,
        name=info.get("name", default_name), balance=info.get("balance", 0),
        account_type=info.get("account_type", "other"), owner=info.get("owner", "self"),
        beneficiary_type=info.get("beneficiary_type", "non_edb"),
        cost_basis=info.get("cost_basis"), inherited_year=info.get("inherited_year"),
        inheritance_settings=info.get("inheritance_settings"),
        roth_settings=info.get("roth_settings"),
        investment_settings=info.get("investment_settings"),
        withdrawal_lock=info.get("withdrawal_lock"),
        distribution_settings=info.get("distribution_settings"),
        include_in_liquid=info.get("include_in_liquid"),
        state_taxed_basis=info.get("state_taxed_basis"),
        intl_account_kind=info.get("intl_account_kind"),
    )


def partner_owned_names(plan: Plan, accounts: list[CurrentAccount]) -> list[str]:
    """Names of the plan's incomes and accounts that belong to the partner.

    They need a partner in the plan: removing the partner first requires
    reassigning or deleting them, and a plan saved without one cannot run.
    """
    return ([income.name for income in plan.income_streams if income.owner == "spouse"]
            + [account.name for account in accounts if account.owner == "spouse"])


def validate_withdrawal_lock(
    lock: dict | None,
    user_id: uuid.UUID,
    db: Session,
    plan_id: uuid.UUID | None,
) -> None:
    """Reject a milestone lock whose milestone the account's plans cannot see.

    A plan's own (client) account and a plan-scoped request use that plan's
    milestones. A household account saved without a plan may use a milestone
    from any of the user's household plans; plans without it ignore the lock.
    """
    if not lock or lock.get("unlock") != "milestone":
        return
    query = (
        db.query(Milestone.id)
        .join(Plan, Milestone.plan_id == Plan.id)
        .filter(Milestone.id == uuid.UUID(str(lock["milestone_id"])), Plan.user_id == user_id)
    )
    query = query.filter(Milestone.plan_id == plan_id) if plan_id else query.filter(Plan.client_id.is_(None))
    if query.first() is None:
        raise validation_error(
            "Account was not saved: the unlock milestone is not in this plan", "withdrawal_lock.milestone_id",
            "not found in plan",
        )


def validate_account_references(
    plan_id: uuid.UUID,
    account_ids: list[uuid.UUID] | None,
    user_id: uuid.UUID,
    db: Session,
    field: str,
) -> None:
    """Validate an ordered account selection against the user's plan scope."""
    if account_ids is None:
        return
    if len(account_ids) != len(set(account_ids)):
        raise validation_error("Choose each funding account only once", field, "account IDs must be unique")
    if not account_ids:
        return
    existing = {
        row[0]
        for row in db.query(CurrentAccount.id).filter(
            CurrentAccount.id.in_(account_ids),
            CurrentAccount.user_id == user_id,
            plan_account_filter(plan_id, user_id, db),
        ).all()
    }
    missing = [str(account_id) for account_id in account_ids if account_id not in existing]
    if missing:
        raise validation_error(
            "Choose accounts belonging to this plan", field, f"account not in plan: {', '.join(missing)}",
        )


def get_real_asset_or_404(
    real_asset_id: uuid.UUID, plan_id: uuid.UUID, db: Session
) -> RealAsset:
    asset = (
        db.query(RealAsset)
        .filter(RealAsset.id == real_asset_id, RealAsset.plan_id == plan_id)
        .first()
    )
    if not asset:
        raise api_error(404, "NOT_FOUND", "Real asset not found")
    return asset


def get_tax_jurisdiction_or_404(
    jurisdiction_id: uuid.UUID, user_id: uuid.UUID, db: Session
) -> TaxJurisdiction:
    jurisdiction = (
        db.query(TaxJurisdiction)
        .filter(
            TaxJurisdiction.id == jurisdiction_id,
            TaxJurisdiction.user_id == user_id,
        )
        .first()
    )
    if not jurisdiction:
        raise api_error(404, "NOT_FOUND", "Tax jurisdiction not found")
    return jurisdiction


def get_charity_or_404(
    charity_id: uuid.UUID, plan_id: uuid.UUID, db: Session
) -> CharityEntity:
    charity = (
        db.query(CharityEntity)
        .filter(CharityEntity.id == charity_id, CharityEntity.plan_id == plan_id)
        .first()
    )
    if not charity:
        raise api_error(404, "NOT_FOUND", "Charity not found")
    return charity


def get_plan_or_404(
    plan_id: uuid.UUID, user_id: uuid.UUID, db: Session, *, for_update: bool = False, for_share: bool = False
) -> Plan:
    """The user's plan; ``for_update`` locks it exclusively, ``for_share`` with a shared lock."""
    query = db.query(Plan).filter(Plan.id == plan_id, Plan.user_id == user_id)
    if for_update or for_share:
        query = query.with_for_update(read=not for_update).populate_existing()
    plan = query.first()
    if not plan:
        raise api_error(404, "NOT_FOUND", "Plan not found")
    return plan


#: Rows of one kind a plan (or an account pool) may hold, well above any real
#: plan. Every row is engine work on each projection, so the cap bounds what a
#: single projection request can cost.
ROW_LIMIT = 200


def ensure_row_capacity(existing, noun: str) -> None:
    """Refuse another row once ``existing`` (a query of its kind) holds ``ROW_LIMIT``."""
    if existing.limit(ROW_LIMIT).count() >= ROW_LIMIT:
        raise api_error(422, "VALIDATION_ERROR", f"Remove {noun} before adding another.")


def lock_priority_revision(plan_id: uuid.UUID, db: Session) -> None:
    """Include FK-driven rule edits in the same parent-lock protocol."""
    plan = db.query(Plan).filter(Plan.id == plan_id).with_for_update().populate_existing().one()
    plan.priorities_revision += 1


def client_today(
    x_client_date: str | None = Header(default=None, alias="X-Client-Date"),
) -> datetime.date:
    """The calendar date where the user is, for "Now" plans.

    The browser sends its local date in ``X-Client-Date`` (``YYYY-MM-DD``).
    Server time is UTC, so late-evening users west of Greenwich would otherwise
    see their plan start "tomorrow". Only dates within two days of the server
    clock are trusted; anything else falls back to the server date.
    """
    server_today = datetime.date.today()
    if not x_client_date:
        return server_today
    try:
        parsed = datetime.date.fromisoformat(x_client_date.strip())
    except ValueError:
        return server_today
    if abs((parsed - server_today).days) > 2:
        return server_today
    return parsed


def resolve_milestone_year(
    milestone: Milestone | None,
    milestones_by_id: dict[uuid.UUID, Milestone],
    birth_year: int,
    _seen: set[uuid.UUID] | None = None,
) -> int | None:
    """Calendar year a milestone fires when that can be known before simulating.

    Age and date triggers resolve directly; relative triggers resolve through
    their base. Net-worth and expense-multiple triggers depend on the
    projection, so they return ``None``, as does a switched-off milestone
    (it never fires).
    """
    if milestone is None:
        return None
    seen = _seen or set()
    if milestone.id in seen or milestone.is_active is False:
        return None
    seen.add(milestone.id)
    if milestone.trigger_type == "age" and milestone.trigger_value is not None:
        return birth_year + math.ceil(float(milestone.trigger_value))
    if milestone.trigger_type == "date" and milestone.trigger_date is not None:
        return milestone.trigger_date.year
    if milestone.trigger_type == "relative" and milestone.relative_to_id is not None:
        base = resolve_milestone_year(
            milestones_by_id.get(milestone.relative_to_id), milestones_by_id, birth_year, seen
        )
        return None if base is None else base + int(milestone.offset_years or 0)
    return None


def validate_milestone_window(
    plan: Plan,
    start_milestone_id: uuid.UUID | None,
    end_milestone_id: uuid.UUID | None,
    db: Session,
    start_month: int | None = None,
    end_month: int | None = None,
    *,
    reject_empty: bool = False,
) -> None:
    """Reject an event whose start milestone resolves after its end milestone.

    Windows bounded by projection-dependent milestones (net worth, expense
    multiple) cannot be checked up front and are left alone.

    With ``reject_empty``, also reject the same milestone as start and end with
    neither month set: the event would start in the trigger month and end the
    month before it, so it never pays (``prorate_for_year``).
    """
    if start_milestone_id is None or end_milestone_id is None:
        return
    if reject_empty and start_milestone_id == end_milestone_id and start_month is None and end_month is None:
        raise validation_error(
            "Starts and ends at the same milestone, so it never applies. Choose a later end or set the months.",
            "end_milestone_id", "same as the start milestone with no months, an empty window",
        )
    milestones = {m.id: m for m in db.query(Milestone).filter(Milestone.plan_id == plan.id).all()}
    start_year = resolve_milestone_year(milestones.get(start_milestone_id), milestones, plan.birth_year)
    end_year = resolve_milestone_year(milestones.get(end_milestone_id), milestones, plan.birth_year)
    if (start_milestone_id == end_milestone_id or (start_year is not None and start_year == end_year)) and start_month is not None and end_month is not None and start_month > end_month:
        raise validation_error(
            "Start month must not be after end month when both milestones occur in the same year.", "end_month",
            "must be on or after start month in the same year",
        )
    if start_year is None or end_year is None or start_year <= end_year:
        return
    start_name = milestones[start_milestone_id].name
    end_name = milestones[end_milestone_id].name
    raise api_error(
        422, "VALIDATION_ERROR",
        (
            f"Start milestone \"{start_name}\" ({start_year}) comes after end milestone "
            f"\"{end_name}\" ({end_year}). Swap them or choose a later end."
        ),
        [
            {"field": "start_milestone_id", "reason": f"resolves to {start_year}, after the end milestone"},
            {"field": "end_milestone_id", "reason": f"resolves to {end_year}, before the start milestone"},
        ],
    )


def validate_plan_start(plan: Plan, changes: dict | None = None, today: datetime.date | None = None) -> None:
    """Validate the merged plan before mutation or simulation, including old data."""
    data = changes or {}
    plan_type = data.get("plan_type", plan.plan_type)
    start = data.get("start_date", plan.start_date) if plan_type == "FIXED_DATE" else None
    start = start or today or datetime.date.today()
    birth_year = data.get("birth_year", plan.birth_year)
    birth_month = data.get("birth_month", plan.birth_month) or 1
    if birth_year is None or start < datetime.date(birth_year, birth_month, 1):
        raise validation_error(
            "Start date must be on or after your birth year/month.", "start_date", "must not precede birth",
        )


def _require_plan_milestone(plan_id: uuid.UUID, milestone_id: uuid.UUID | None, field: str, db: Session) -> None:
    """Reject ``milestone_id`` in ``field`` unless it is one of the plan's milestones; None passes."""
    if milestone_id is None:
        return
    if not db.query(Milestone.id).filter(Milestone.id == milestone_id, Milestone.plan_id == plan_id).first():
        raise validation_error(f"Milestone {milestone_id} does not belong to this plan", field, "not found in plan")


def validate_milestone_fks(
    plan_id: uuid.UUID,
    body: IncomeCreate | IncomeUpdate | ExpenseCreate | ExpenseUpdate,
    db: Session,
) -> None:
    """Reject an income or expense whose start or end milestone is not in the plan."""
    for field in ("start_milestone_id", "end_milestone_id"):
        _require_plan_milestone(plan_id, getattr(body, field, None), field, db)


def validate_liability_fks(
    plan_id: uuid.UUID,
    user_id: uuid.UUID,
    body: LiabilityCreate | LiabilityUpdate,
    db: Session,
) -> None:
    """Reject a debt whose asset, offset account or milestones are not in the plan."""
    if getattr(body, "linked_asset_id", None) is not None:
        exists = (
            db.query(RealAsset.id)
            .filter(RealAsset.id == body.linked_asset_id, RealAsset.plan_id == plan_id)
            .first()
        )
        if not exists:
            raise validation_error(
                f"Real asset {body.linked_asset_id} does not belong to this plan", "linked_asset_id",
                "not found in plan",
            )

    if getattr(body, "offset_account_id", None) is not None:
        exists = (
            db.query(CurrentAccount.id)
            .filter(
                CurrentAccount.id == body.offset_account_id,
                CurrentAccount.user_id == user_id,
                plan_account_filter(plan_id, user_id, db),
            )
            .first()
        )
        if not exists:
            raise validation_error(f"Account {body.offset_account_id} not found", "offset_account_id", "not found")

    forgiveness = getattr(body, "forgiveness", None)
    if forgiveness is not None:
        _require_plan_milestone(plan_id, forgiveness.milestone_id, "forgiveness.milestone_id", db)
    _require_plan_milestone(
        plan_id, getattr(body, "recurrence_end_milestone_id", None), "recurrence_end_milestone_id", db,
    )
    _require_plan_milestone(plan_id, getattr(body, "payoff_milestone_id", None), "payoff_milestone_id", db)


def reject_joint_individual_account(account_type: str, owner: str | None, field: str = "owner") -> None:
    """Raise the shared 422 envelope for a jointly owned IRA, 401(k) or HSA."""
    if joint_owner_not_allowed(account_type, owner):
        raise validation_error(
            "Account was not saved: an IRA, 401(k) or HSA cannot be owned jointly", field, JOINT_OWNER_REASON,
        )


# Default drawdown priority by account type: liquid cash first, then
# taxable, then tax-deferred, then Roth (preserving tax-free growth as
# long as possible), then HSA/other. 529s are education-earmarked and
# excluded from retirement drawdown unless the user adds them manually.
_DEFAULT_DRAWDOWN_PRIORITY: dict[str, int] = {
    "checking": 1,
    "savings": 1,
    "taxable_brokerage": 2,
    **dict.fromkeys(TRADITIONAL_RETIREMENT_TYPES, 3),
    **dict.fromkeys(ROTH_TYPES, 4),
    "hsa": 5,
    "other": 6,
}
#: Country account kinds take the place of the matching US category.
_KIND_CATEGORY_DRAWDOWN_PRIORITY = {"cash": 1, "taxable": 2, "tax_deferred": 3, "tax_free": 4}


def _drawdown_priority(account_type: str | None, intl_account_kind: str | None) -> int | None:
    kind = intl_bridge.account_kind(intl_account_kind) if intl_account_kind else None
    if kind is not None:
        return _KIND_CATEGORY_DRAWDOWN_PRIORITY.get(kind.category)
    return _DEFAULT_DRAWDOWN_PRIORITY.get(account_type)


def insert_into_drawdown_orders(
    account: CurrentAccount, user_id: uuid.UUID, db: Session
) -> None:
    """Insert *account* into each of the user's plans' drawdown orders.

    Uses a stable insert keyed on the type-based default priority, so a
    user's custom ordering of existing entries is preserved. Does not
    commit — the caller owns the transaction.
    """
    priority = _drawdown_priority(account.account_type, account.intl_account_kind)
    if priority is None:
        return

    account_types = {
        row.id: (row.account_type, row.intl_account_kind)
        for row in db.query(CurrentAccount.id, CurrentAccount.account_type, CurrentAccount.intl_account_kind)
        .filter(CurrentAccount.user_id == user_id)
        .all()
    }

    plan_ids = [
        row[0]
        for row in db.query(Plan.id).filter(Plan.user_id == user_id).filter(
            Plan.id == account.plan_id if account.plan_id else Plan.client_id.is_(None)
        ).all()
    ]
    for plan_id in plan_ids:
        entries = (
            db.query(DrawdownOrder)
            .filter(DrawdownOrder.plan_id == plan_id)
            .order_by(DrawdownOrder.rank)
            .all()
        )
        if any(e.source_account_id == account.id for e in entries):
            continue

        insert_idx = len(entries)
        for i, entry in enumerate(entries):
            entry_type, entry_kind = account_types.get(entry.source_account_id, (None, None))
            entry_priority = _drawdown_priority(entry_type, entry_kind)
            entry_priority = 99 if entry_priority is None else entry_priority
            if entry_priority > priority:
                insert_idx = i
                break

        entries.insert(
            insert_idx,
            DrawdownOrder(
                id=uuid.uuid4(),
                plan_id=plan_id,
                rank=0,
                source_account_id=account.id,
            ),
        )
        for i, entry in enumerate(entries):
            entry.rank = i + 1
        db.add_all(entries)


def load_plan_data(
    plan_id: uuid.UUID,
    current_user: User,
    db: Session,
    today: datetime.date | None = None,
) -> PlanData:
    """Load a plan owned by current_user and convert to engine PlanData.

    ``today`` is the user's local date for "Now" plans (defaults to server date).
    Raises HTTPException 404 if the plan is not found (or not owned by user).
    """
    plan = (
        db.query(Plan)
        .options(
            selectinload(Plan.milestones),
            selectinload(Plan.income_streams),
            selectinload(Plan.expenses),
            selectinload(Plan.priorities),
            selectinload(Plan.drawdown_order),
            selectinload(Plan.assumption_curves),
            selectinload(Plan.spouse),
        )
        .filter(Plan.id == plan_id, Plan.user_id == current_user.id)
        .first()
    )
    if not plan:
        raise api_error(404, "NOT_FOUND", "Plan not found")
    # Covers a comparison's baseline plan, which is not in the route's path.
    ensure_plan_openable(plan, current_user)

    validate_plan_start(plan, today=today)

    # A legacy fixed-date plan keeps its accounts in snapshot_conditions. They
    # stay transient: loading a plan never adds them to the session.
    if plan.client_id is None and plan.plan_type == "FIXED_DATE" and plan.snapshot_conditions:
        accounts = [
            snapshot_account(acct_id, info, current_user.id)
            for acct_id, info in plan.snapshot_conditions.items()
        ]
    else:
        accounts = (
            db.query(CurrentAccount)
            .filter(CurrentAccount.user_id == current_user.id)
            .filter(plan_scope_filter(plan))
            .all()
        )

    data = plan_to_engine_data(plan, accounts, today=today)
    try:
        _check_partner_benefits(plan, data)
        if data.start_year >= simulation_end_year(data):
            raise ValueError("Life expectancy must extend beyond the projection start age.")
        validate_transfer_rules(data.priorities, data.accounts)
        validate_roth_conversion_rules(data.priorities, data.accounts)
        validate_account_history(data.accounts, data.start_year)
        validate_person_healthcare_plan(data)
        validate_regime_settings(data)
        resolve_deterministic_milestones(data.milestones, data.birth_year, data.birth_month)
    except ValueError as exc:
        # A retired country names its field (tax_country or a residency period's country).
        raise validation_error(str(exc), getattr(exc, "field", "plan")) from exc
    return data


def _check_partner_benefits(plan: Plan, data: PlanData) -> None:
    """A partner's Social Security is timed from the partner's birth year
    (``coastmath.engine.ss_household.owner_birth``). Plans saved before the plans
    router refused to remove a partner who owns items can lack it."""
    if data.spouse_birth_year is not None:
        return
    names = [income.name for income in data.income_streams
             if income.owner == "spouse" and income.is_social_security and not income.ss_worker_income_id]
    if not names:
        return
    if plan.spouse is None:
        raise ValueError(f"The plan has no partner, but {', '.join(names)} is the partner's. "
                         "Add the partner in Partner and estate, or remove it.")
    raise ValueError(f"{', '.join(names)} needs the partner's birth year (Partner and estate).")

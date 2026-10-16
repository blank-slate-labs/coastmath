"""Who may open, edit and create plans, and link provider connections.

Archived plans are read-only until restored. Beyond that every account has
full access unless a plug-in installs a stricter ``AccessPolicy``
(``app.plugins``). Unknown plans fall through to each route's own 404.
"""
import uuid
from datetime import datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.clock import utcnow
from app.db import get_db
from app.errors import api_error
from app.models.plan import Plan
from app.models.user import User
from app.plugins import extensions

#: Creating, reconnecting or manually syncing a provider connection (Plaid,
#: SimpleFIN or a plug-in provider). Reads, disconnects and file imports are
#: never actions; a policy that limits this one also pauses background sync.
BANK_LINKING = "bank_linking"
#: Storing a provider credential (a SimpleFIN access URL, a Plaid access
#: token) for the account, checked before ``BANK_LINKING`` when linking or
#: reconnecting. A server where every session is the household's own allows it.
PROVIDER_CREDENTIALS = "provider_credentials"
#: Plans one account may hold, archived ones included, far above any real use.
#: Archiving frees an active plan, so without this an account could keep
#: creating plans, each with its full allowance of rows.
PLAN_LIMIT = 500


class AccessPolicy:
    """Full access: the policy without a plug-in. Subclasses override what they limit."""

    def require(self, user: User, action: str) -> None:
        """Raise when ``user`` may not take ``action`` (``duplicate``, ``restore_plan``, ``bank_linking``,
        ``provider_credentials``)."""

    def allows(self, user: User, action: str) -> bool:
        """Whether ``require`` would pass, for work without a request (background sync)."""
        return True

    def ensure_plan_openable(self, plan: Plan, user: User) -> None:
        """Raise when ``user`` may not open ``plan`` (it may be archived)."""

    def ensure_within_edit_window(self, plan: Plan, user: User) -> None:
        """Raise when ``user`` may no longer edit the active ``plan``."""

    def edit_window_ends_at(self, plan: Plan) -> datetime | None:
        """When editing ``plan`` stops; None when it never does."""
        return None

    def plan_editable(self, plan: Plan, user: User, now: datetime) -> bool:
        return plan.archived_at is None

    def present_plans(self, plans: list[Plan], user: User, db: Session, *, start_grace: bool) -> None:
        """Set each plan's ``editable`` for the response."""
        now = utcnow()
        for plan in plans:
            plan.editable = self.plan_editable(plan, user, now)

    def ensure_can_create_plan(self, user: User, db: Session, client_id: uuid.UUID | None) -> None:
        """Raise when ``user`` may not create another plan."""

    def session_entitlement(self, user: User) -> dict | None:
        """The ``entitlement`` object of the session response, if any."""
        return None

    def session_capabilities(self, user: User) -> list[str]:
        """Capabilities added to the session response."""
        return []


FULL_ACCESS = AccessPolicy()


def policy() -> AccessPolicy:
    return extensions.access_policy or FULL_ACCESS


def require(user: User, action: str) -> None:
    policy().require(user, action)


def allows(user: User, action: str) -> bool:
    return policy().allows(user, action)


def present_plans(plans: list[Plan], user: User, db: Session, *, start_grace: bool = False) -> list[Plan]:
    """Set each plan's server-computed ``editable`` for the response.

    ``start_grace`` marks plan reads, where a policy may first update the
    plans' editing state, so clients never apply the rules themselves.
    """
    policy().present_plans(plans, user, db, start_grace=start_grace)
    return plans


def plan_editable(plan: Plan, user: User, now: datetime) -> bool:
    return policy().plan_editable(plan, user, now)


def ensure_can_create_plan(user: User, db: Session, *, client_id: uuid.UUID | None = None) -> None:
    policy().ensure_can_create_plan(user, db, client_id)
    ensure_plan_capacity(user, db)


def ensure_plan_capacity(user: User, db: Session) -> None:
    """Refuse another plan once the account holds ``PLAN_LIMIT``, archived ones included."""
    if db.query(Plan.id).filter(Plan.user_id == user.id).limit(PLAN_LIMIT).count() >= PLAN_LIMIT:
        raise api_error(422, "VALIDATION_ERROR", "Delete a plan before adding another.")


def ensure_plan_openable(plan: Plan, user: User) -> None:
    policy().ensure_plan_openable(plan, user)


def ensure_plan_active(plan: Plan, user: User) -> None:
    """Archived plans take no new data: they are restored first."""
    ensure_plan_openable(plan, user)
    if plan.archived_at is not None:
        raise api_error(409, "CONFLICT", "Restore this plan before editing it.")


def ensure_plan_editable(plan: Plan, user: User) -> None:
    ensure_plan_active(plan, user)
    policy().ensure_within_edit_window(plan, user)


def _owned_plan(plan_id: uuid.UUID, user: User, db: Session) -> Plan | None:
    return db.query(Plan).filter(Plan.id == plan_id, Plan.user_id == user.id).first()


def ensure_plan_readable(plan_id: uuid.UUID, user: User, db: Session) -> None:
    plan = _owned_plan(plan_id, user, db)
    if plan is not None:
        ensure_plan_openable(plan, user)


def ensure_plan_writable(plan_id: uuid.UUID, user: User, db: Session) -> None:
    plan = _owned_plan(plan_id, user, db)
    if plan is not None:
        ensure_plan_editable(plan, user)


def _as_plan_id(raw) -> uuid.UUID | None:
    if raw is None:
        return None
    try:
        return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
    except ValueError:
        return None  # The route's own validation answers malformed IDs.


def _path_plan_id(request: Request) -> uuid.UUID | None:
    return _as_plan_id(request.path_params.get("plan_id"))


def _is_read(request: Request) -> bool:
    return request.method in ("GET", "HEAD", "OPTIONS")


def plan_guard(request: Request, current_user: User = Depends(get_current_user),
               db: Session = Depends(get_db)) -> None:
    """Router dependency for plan-scoped data routes (``/plans/{plan_id}/...``):
    reads need an openable plan, writes an editable one."""
    plan_id = _path_plan_id(request)
    if plan_id is None:
        return
    if _is_read(request):
        ensure_plan_readable(plan_id, current_user, db)
    else:
        ensure_plan_writable(plan_id, current_user, db)


def account_pool_guard(request: Request, current_user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> None:
    """Router dependency for ``/accounts``, which shares its routes with
    ``/plans/{plan_id}/accounts`` and must not be a way around its guard.

    ``?plan_id=`` names the plan exactly as the path does there. Without it the
    routes use the legacy pool behind every plan that has no client, so access
    follows those plans: allowed when any of them would allow it. A pool that
    backs no plan changes no plan."""
    plan_id = _as_plan_id(request.query_params.get("plan_id"))
    if plan_id is not None:
        if _is_read(request):
            ensure_plan_readable(plan_id, current_user, db)
        else:
            ensure_plan_writable(plan_id, current_user, db)
        return
    # Active plans first, so a refusal names the editing window rather than the archive.
    legacy = (db.query(Plan).filter(Plan.user_id == current_user.id, Plan.client_id.is_(None))
              .order_by(Plan.archived_at.is_not(None)).all())
    check = ensure_plan_openable if _is_read(request) else ensure_plan_editable
    refusal = None
    for plan in legacy:
        try:
            check(plan, current_user)
            return
        except HTTPException as exc:
            refusal = refusal or exc
    if refusal is not None:
        raise refusal


def plan_read_guard(request: Request, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> None:
    """Router dependency for analysis routes, which POST without changing the plan."""
    plan_id = _path_plan_id(request)
    if plan_id is not None:
        ensure_plan_readable(plan_id, current_user, db)

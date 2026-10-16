"""/api/ledger/spending-feeds/{plan_id}: connected spending from any provider's accounts.

Built on ``app.ledger.feeds.set_feed`` / ``stop_feed``, which plug-in
providers' own feed routes share. Accounts may
come from any provider in an active environment and must count toward
spending. Changes require TRANSACTIONS_ENABLED; reading and stopping a feed
stay available. Mounted with the plan guard.
"""
import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.access import ensure_plan_active, ensure_plan_openable
from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error
from app.ledger.accounts import counts_toward_spending
from app.ledger.environments import active_filter
from app.ledger.feeds import feed_for_plan, set_feed, stop_feed
from app.ledger.gating import require_transactions_enabled
from app.models.financial_connection import FinancialSource, FinancialSpendingFeed
from app.models.user import User
from app.routers.helpers import get_plan_or_404
from app.schemas.ledger_feeds import LedgerFeedRead, LedgerFeedRequest

router = APIRouter(prefix="/ledger/spending-feeds", tags=["ledger"],
                   dependencies=[Depends(require_transactions_enabled)])


def _lock_user(db: Session, user_id: uuid.UUID) -> None:
    if db.query(User.id).filter(User.id == user_id).with_for_update().first() is None:
        raise api_error(401, "AUTH_REQUIRED", "Account no longer exists.")


def feed_read(plan_id: uuid.UUID, feed: FinancialSpendingFeed | None) -> LedgerFeedRead:
    if feed is None:
        return LedgerFeedRead(plan_id=plan_id, active=False)
    return LedgerFeedRead(
        plan_id=plan_id, active=True, source_ids=[uuid.UUID(value) for value in feed.source_ids],
        basis=feed.basis, basis_months=list(feed.basis_months or []),
        essential_expense_id=feed.essential_expense_id, discretionary_expense_id=feed.discretionary_expense_id,
        annual_essential=float(feed.last_essential) if feed.last_essential is not None else None,
        annual_discretionary=float(feed.last_discretionary) if feed.last_discretionary is not None else None,
        months_used=feed.months_used or 0, error=feed.error, applied_at=feed.applied_at)


@router.get("/{plan_id}", response_model=LedgerFeedRead)
def get_feed(plan_id: uuid.UUID, current_user: User = Depends(get_current_user),
             db: Session = Depends(get_db)) -> LedgerFeedRead:
    plan = get_plan_or_404(plan_id, current_user.id, db)
    ensure_plan_openable(plan, current_user)
    return feed_read(plan.id, feed_for_plan(db, plan.id))


@router.put("/{plan_id}", response_model=LedgerFeedRead)
def put_feed(plan_id: uuid.UUID, body: LedgerFeedRequest, current_user: User = Depends(get_current_user),
             db: Session = Depends(get_db)) -> LedgerFeedRead:
    """Turn spending from transactions on, or change its accounts or basis, and apply it now."""
    _lock_user(db, current_user.id)
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    ensure_plan_active(plan, current_user)
    feed = set_feed(db, current_user.id, plan, body.source_ids,
                    acknowledge_existing_expenses=body.acknowledge_existing_expenses,
                    scope=active_filter(FinancialSource), eligible=counts_toward_spending,
                    basis=body.basis, months=body.months)
    db.commit()
    return feed_read(plan.id, feed)


@router.delete("/{plan_id}", status_code=204)
def delete_feed(plan_id: uuid.UUID, current_user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> Response:
    """Stop updates; the connected expenses keep their last amounts and become editable."""
    _lock_user(db, current_user.id)
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    ensure_plan_active(plan, current_user)
    stop_feed(db, plan)
    db.commit()
    return Response(status_code=204)

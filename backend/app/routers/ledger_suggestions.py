"""Optional LLM category suggestions: status and an immediate run.

Offered only when the operator configured a model (app/ledger/llm.py). A run
stores suggestions, never overrides; customers accept them in the review.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error
from app.ledger.gating import require_transactions_enabled
from app.ledger.llm import llm_offered
from app.ledger.suggestions import (
    Outcome,
    is_running,
    last_outcome,
    pending_rows,
    run_for_user,
)
from app.models.user import User
from app.rate_limit import limiter, session_user
from app.schemas.ledger_suggestions import SuggestionRunRead, SuggestionStatusRead

router = APIRouter(prefix="/ledger/suggestions", tags=["ledger"],
                   dependencies=[Depends(require_transactions_enabled)])


def run_read(outcome: Outcome | None) -> SuggestionRunRead | None:
    if outcome is None or outcome.status not in ("suggested", "nothing_pending", "failed"):
        return None
    return SuggestionRunRead(status=outcome.status, suggested=outcome.suggested, sent=outcome.sent,
                             message=outcome.message, finished_at=outcome.finished_at)


def status_read(db: Session, user: User) -> SuggestionStatusRead:
    offered = llm_offered()
    return SuggestionStatusRead(offered=offered, running=is_running(user.id),
                                pending=len(pending_rows(db, user.id)) if offered else None,
                                last_run=run_read(last_outcome(user.id)))


@router.get("/status", response_model=SuggestionStatusRead)
def suggestion_status(current_user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)) -> SuggestionStatusRead:
    return status_read(db, current_user)


@router.post("/run", response_model=SuggestionStatusRead)
@limiter.limit("6/hour", key_func=session_user)
def run_suggestions(request: Request, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> SuggestionStatusRead:
    outcome = run_for_user(db, current_user.id)
    if outcome.status == "not_offered":
        raise api_error(503, "FEATURE_DISABLED", "Category suggestions are not configured.")
    if outcome.status == "running":
        raise api_error(409, "CONFLICT", "Suggestions are already running.")
    return status_read(db, current_user)

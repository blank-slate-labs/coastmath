import datetime
import uuid
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.models.user import User
from app.rate_limit import engine_budget, limiter, session_user
from app.routers.engine_errors import engine_errors
from app.routers.helpers import client_today, get_plan_or_404, load_plan_data
from app.usage import count_usage
from coastmath.engine.tax_strategy import pre_tax_discount_rate
from coastmath.engine.tax_suggestions import suggest_tax_strategies

router = APIRouter(prefix="/plans/{plan_id}/tax-suggestions", tags=["tax-suggestions"])


class SuggestedRuleRead(BaseModel):
    """An allocation rule in ``CashFlowPriorityCreate`` fields.

    ``add`` inserts it at ``priority_rank`` (later rules move down one);
    ``update`` sets these fields on the rule currently at ``priority_rank``.
    """
    change: Literal["add", "update"]
    priority_rank: int
    priority_type: str
    target_account_id: uuid.UUID | None = None
    source_account_id: uuid.UUID | None = None
    source_income_id: uuid.UUID | None = None
    conversion_mode: Literal["fixed", "fill_bracket"] = "fixed"
    bracket_ceiling_rate: float | None = None
    backdoor_roth: bool = False


class TaxSuggestionRead(BaseModel):
    key: Literal["max_401k", "backdoor_roth", "max_hsa", "mega_backdoor", "roth_conversion", "gain_harvest"]
    title: str
    lifetime_tax_change: float  # nominal dollars, suggestion minus plan; negative saves tax
    end_net_worth_change: float  # nominal dollars at the end of the plan, pre-tax balances after income tax
    rules: list[SuggestedRuleRead]


class TaxSuggestionsResponse(BaseModel):
    suggestions: list[TaxSuggestionRead]
    #: Income tax rate applied to end-of-plan pre-tax balances in
    #: ``end_net_worth_change``: the heir rate, else 0.24.
    pre_tax_discount_rate: float


@router.post("", response_model=TaxSuggestionsResponse, dependencies=[Depends(count_usage("tax_suggestions"))])
@limiter.limit("10/minute", key_func=session_user)
@engine_budget
def suggest(
    request: Request,
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> TaxSuggestionsResponse:
    """Simulate a fixed set of tax rule changes and return those that improve the plan."""
    get_plan_or_404(plan_id, current_user.id, db)
    plan_data = load_plan_data(plan_id, current_user, db, today=today)
    with engine_errors("Tax suggestions engine encountered an error", "Tax suggestions failed for plan %s", plan_id):
        suggestions = suggest_tax_strategies(plan_data)
    return TaxSuggestionsResponse(suggestions=[TaxSuggestionRead(**asdict(s)) for s in suggestions],
                                  pre_tax_discount_rate=pre_tax_discount_rate(plan_data))

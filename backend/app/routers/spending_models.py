"""Spending models: compare spending variants against a plan or apply one to it.

``compare`` is analysis only (plan read guard); ``apply`` persists the same
overlay to the plan's expenses (plan write guard). Both are release-gated by
``TRANSACTIONS_ENABLED``. A variant is a union discriminated by ``kind``:

- ``"amounts"`` states annual essential and discretionary spending directly;
- ``"months"`` names one to twelve complete ledger months, resolved with the
  plan's currency over the plan's feed accounts (or the user's default
  spending accounts, or the variant's own ``source_ids``).

Applying a months variant to a plan with connected spending sets the feed's
basis to those months; without a feed it scales the expenses like amounts.
Complete months are judged on the user's calendar date, as in ``/ledger/months``.
"""
import datetime
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error
from app.ledger.accounts import counts_toward_spending
from app.ledger.environments import active_filter
from app.ledger.feeds import apply_feed, feed_for_plan
from app.ledger.gating import require_transactions_enabled
from app.ledger.month_models import MAX_MONTHS, model_from, months_label
from app.ledger.months import MonthsResult, month_summaries
from app.models.expense import Expense
from app.models.financial_connection import FinancialSource, FinancialSpendingFeed
from app.models.plan import Plan
from app.models.user import User
from app.monte_carlo_capacity import deadline, monte_carlo_slot, time_limit_error
from app.rate_limit import engine_budget, limiter, session_user
from app.routers.engine_errors import engine_errors
from app.routers.helpers import client_today, get_plan_or_404, load_plan_data
from app.routers.ledger import ledger_today
from app.schemas.ledger_feeds import MONTH_PATTERN
from app.usage import count_usage
from coastmath.engine.monte_carlo import MonteCarloTimeLimit
from coastmath.engine.spending_model import (
    MAX_MODELS,
    SpendingModel,
    SpendingOutcome,
    compare_spending_models,
    expense_fingerprint,
    overlay_spending_model,
)

PREFIX = "/plans/{plan_id}/spending-models"
gate = [Depends(require_transactions_enabled)]
router = APIRouter(prefix=PREFIX, tags=["spending-models"], dependencies=gate)
apply_router = APIRouter(prefix=PREFIX, tags=["spending-models"], dependencies=gate)

MAX_ANNUAL = 100_000_000
MAX_MONTHLY = 10_000_000
MAX_SOURCES = 50


class AmountsVariant(BaseModel):
    """Spending stated directly: annual essential and discretionary, optional monthly take-home."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["amounts"]
    label: str | None = Field(default=None, max_length=80)
    essential_annual: float = Field(ge=0, le=MAX_ANNUAL)
    discretionary_annual: float = Field(ge=0, le=MAX_ANNUAL)
    # Used only when the comparison's ``income`` is ``scale_to_take_home``.
    take_home_monthly: float | None = Field(default=None, gt=0, le=MAX_MONTHLY)


class MonthsVariant(BaseModel):
    """Spending from complete ledger months: 12 × their mean, and their mean take-home."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["months"]
    label: str | None = Field(default=None, max_length=80)
    months: list[str] = Field(min_length=1, max_length=MAX_MONTHS)
    # Default: the plan's feed accounts, else the accounts that count toward spending.
    source_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=MAX_SOURCES)

    @field_validator("months")
    @classmethod
    def _months(cls, value: list[str]) -> list[str]:
        if any(not MONTH_PATTERN.fullmatch(key) for key in value):
            raise ValueError("months are YYYY-MM")
        return list(dict.fromkeys(value))


SpendingVariant = Annotated[AmountsVariant | MonthsVariant, Field(discriminator="kind")]
FuturePhases = Literal["scale", "as_planned"]


class SpendingCompareRequest(BaseModel):
    variants: list[SpendingVariant] = Field(min_length=1, max_length=MAX_MODELS)
    future_phases: FuturePhases = "scale"
    income: Literal["as_planned", "scale_to_take_home"] = "as_planned"
    monte_carlo_trials: int = Field(default=0, ge=0, le=500)
    seed: int | None = Field(default=None, ge=0, le=2147483647)


class NetWorthPointRead(BaseModel):
    year: int
    age: int
    net_worth: float
    inflation_factor: float


class SpendingOutcomeRead(BaseModel):
    kind: Literal["plan", "amounts", "months"]
    label: str
    essential_annual: float
    discretionary_annual: float
    take_home_monthly: float | None
    essential_ratio: float | None
    discretionary_ratio: float | None
    income_ratio: float | None
    projected_take_home_monthly: float
    fi_year: int | None
    fi_age: int | None
    success: bool
    failure_year: int | None
    final_net_worth: float
    net_worth_path: list[NetWorthPointRead]
    monte_carlo_success_rate: float | None
    caveats: list[str]
    # Months variants only: the months used, the accounts read and the mean
    # monthly spending per canonical category (refunds negative).
    months: list[str] | None = None
    source_ids: list[uuid.UUID] | None = None
    by_category: dict[str, float] | None = None


class SpendingCompareResponse(BaseModel):
    fingerprint: str
    covered_expense_ids: list[str]
    spending_feed: bool
    plan: SpendingOutcomeRead
    variants: list[SpendingOutcomeRead]
    caveats: list[str]
    seed: int | None


class SpendingApplyRequest(BaseModel):
    variant: SpendingVariant
    future_phases: FuturePhases = "scale"
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class SpendingApplyResponse(BaseModel):
    fingerprint: str
    updated_expense_ids: list[uuid.UUID]
    created_expense_ids: list[uuid.UUID]
    essential_ratio: float | None
    discretionary_ratio: float | None
    # "months" when the plan's connected spending now follows the chosen months;
    # None when the expenses were scaled.
    basis: str | None = None


@dataclass(frozen=True)
class MonthsModel:
    months: list[str]
    source_ids: list[str]
    by_category: dict[str, float]


def feed_expense_ids(db: Session, plan_id: uuid.UUID) -> list[str] | None:
    """The plan's connected spending expenses, or None when it has no active feed."""
    feed = db.query(FinancialSpendingFeed).filter(FinancialSpendingFeed.plan_id == plan_id).first()
    if feed is None:
        return None
    ids = [str(value) for value in (feed.essential_expense_id, feed.discretionary_expense_id) if value is not None]
    return ids or None


def _model(variant: AmountsVariant, index: int) -> SpendingModel:
    return SpendingModel(
        label=variant.label or f"Model {index}",
        essential=variant.essential_annual,
        discretionary=variant.discretionary_annual,
        take_home_monthly=variant.take_home_monthly,
    )


def _resolve(db: Session, user: User, plan: Plan, variants: list,
             ledger_date: datetime.date) -> list[tuple[SpendingModel, MonthsModel | None]]:
    """Each variant's model; months resolve once per set of accounts."""
    feed = feed_for_plan(db, plan.id)
    default = [uuid.UUID(value) for value in feed.source_ids] if feed is not None else None
    summaries: dict[tuple | None, MonthsResult] = {}
    resolved = []
    for index, variant in enumerate(variants, start=1):
        if variant.kind == "amounts":
            resolved.append((_model(variant, index), None))
            continue
        ids = list(dict.fromkeys(variant.source_ids)) if variant.source_ids is not None else default
        if variant.source_ids is not None:
            owned = db.query(FinancialSource.id).filter(FinancialSource.user_id == user.id, active_filter(FinancialSource),
                                                        FinancialSource.id.in_(ids)).count()
            if owned != len(ids):
                raise api_error(404, "NOT_FOUND", "Account not found.")
        key = tuple(sorted(str(value) for value in ids)) if ids is not None else None
        if key not in summaries:
            summaries[key] = month_summaries(db, user.id, ids, plan.currency, ledger_date)
        result = summaries[key]
        chosen = model_from(result, variant.months)
        amounts = chosen.amounts
        model = SpendingModel(
            label=variant.label or months_label(amounts.months),
            essential=float(amounts.annual_essential),
            discretionary=float(amounts.annual_discretionary),
            take_home_monthly=float(amounts.monthly_take_home) if amounts.monthly_take_home > 0 else None,
        )
        resolved.append((model, MonthsModel(amounts.months, [coverage.source_id for coverage in result.sources],
                                            {key: float(value) for key, value in chosen.by_category.items()})))
    return resolved


def _outcome_read(outcome: SpendingOutcome, kind: str, months: MonthsModel | None = None) -> SpendingOutcomeRead:
    return SpendingOutcomeRead(
        kind=kind, label=outcome.label, essential_annual=outcome.essential,
        discretionary_annual=outcome.discretionary, take_home_monthly=outcome.take_home_monthly,
        essential_ratio=outcome.essential_ratio, discretionary_ratio=outcome.discretionary_ratio,
        income_ratio=outcome.income_ratio, projected_take_home_monthly=outcome.projected_take_home_monthly,
        fi_year=outcome.fi_year, fi_age=outcome.fi_age, success=outcome.success,
        failure_year=outcome.failure_year, final_net_worth=outcome.final_net_worth,
        net_worth_path=[NetWorthPointRead(**point) for point in outcome.net_worth_path],
        monte_carlo_success_rate=outcome.monte_carlo_success_rate, caveats=outcome.caveats,
        months=months.months if months else None,
        source_ids=[uuid.UUID(value) for value in months.source_ids] if months else None,
        by_category=months.by_category if months else None,
    )


@router.post("/compare", response_model=SpendingCompareResponse,
             dependencies=[Depends(count_usage("spending_model_compare"))])
@limiter.limit("10/minute", key_func=session_user)
@engine_budget
def compare(
    request: Request,
    plan_id: uuid.UUID,
    body: SpendingCompareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
    ledger_date: datetime.date = Depends(ledger_today),
) -> SpendingCompareResponse:
    """Project the plan as-is and under each spending model. Nothing is saved."""
    plan = get_plan_or_404(plan_id, current_user.id, db)
    covered = feed_expense_ids(db, plan_id)
    resolved = _resolve(db, current_user, plan, body.variants, ledger_date)
    plan_data = load_plan_data(plan_id, current_user, db, today=today)
    models = [model for model, _ in resolved]
    # Trials run in process pools: share the single Monte Carlo slot, as the
    # withdrawal comparison does.
    with (engine_errors("Spending model comparison engine encountered an error",
                        "Spending model comparison failed for plan %s", plan_id,
                        translate={MonteCarloTimeLimit: time_limit_error("monte_carlo_trials")}),
          monte_carlo_slot() if body.monte_carlo_trials else nullcontext()):
        comparison = compare_spending_models(
            plan_data, models, covered_ids=covered, future_phases=body.future_phases, income=body.income,
            mc_trials=body.monte_carlo_trials, seed=body.seed, max_workers=2, deadline=deadline(),
        )
    return SpendingCompareResponse(
        fingerprint=comparison.fingerprint,
        covered_expense_ids=comparison.covered_expense_ids,
        spending_feed=covered is not None,
        plan=_outcome_read(comparison.plan, "plan"),
        variants=[_outcome_read(outcome, variant.kind, months)
                  for outcome, variant, (_, months) in zip(comparison.models, body.variants, resolved, strict=True)],
        caveats=comparison.caveats,
        seed=comparison.seed,
    )


@apply_router.post("/apply", response_model=SpendingApplyResponse,
                   dependencies=[Depends(count_usage("spending_model_apply"))])
@limiter.limit("60/minute", key_func=session_user)
def apply(
    request: Request,
    plan_id: uuid.UUID,
    body: SpendingApplyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
    ledger_date: datetime.date = Depends(ledger_today),
) -> SpendingApplyResponse:
    """Save a spending model to the plan so it projects like the preview.

    Income is never changed here. A plan with connected spending takes a
    months variant as its feed basis and refuses amounts: its expenses follow
    the accounts, not hand-scaled values.
    """
    plan = get_plan_or_404(plan_id, current_user.id, db)
    covered = feed_expense_ids(db, plan_id)
    if covered is not None and body.variant.kind == "amounts":
        raise api_error(409, "SPENDING_FEED_ACTIVE",
                        "This plan's spending comes from connected accounts. Change the connected spending basis instead.")
    [(model, months)] = _resolve(db, current_user, plan, [body.variant], ledger_date)
    # Lock the plan's expenses before reading them, so the fingerprint check
    # and the writes are one atomic step.
    rows = {str(row.id): row for row in db.query(Expense).filter(Expense.plan_id == plan_id)
            .with_for_update().populate_existing().all()}
    plan_data = load_plan_data(plan_id, current_user, db, today=today)
    if expense_fingerprint(plan_data, covered) != body.expected_fingerprint:
        raise api_error(409, "CONFLICT", "This plan's spending changed after the preview. Nothing was saved. Compare again before applying.")
    overlay = overlay_spending_model(plan_data, model, covered_ids=covered, future_phases=body.future_phases)
    if covered is not None:
        return _apply_to_feed(db, current_user, plan_id, body.variant, months, overlay, today, ledger_date)
    for change in overlay.changes:
        row = rows[change.expense_id]
        row.annual_amount = Decimal(str(change.annual_amount))
        row.growth_cap = Decimal(str(change.growth_cap)) if change.growth_cap is not None else None
        if change.discretionary_percent is not None:
            row.discretionary_percent = Decimal(str(change.discretionary_percent))
            row.category = change.category
    created = [
        Expense(plan_id=plan_id, name=expense.name, annual_amount=Decimal(str(expense.annual_amount)),
                amount_frequency="annual", inflation_linked=True, category=expense.category)
        for expense in overlay.added
    ]
    db.add_all(created)
    db.commit()
    db.expire_all()
    fingerprint = expense_fingerprint(load_plan_data(plan_id, current_user, db, today=today))
    return SpendingApplyResponse(
        fingerprint=fingerprint,
        updated_expense_ids=[uuid.UUID(change.expense_id) for change in overlay.changes],
        created_expense_ids=[row.id for row in created],
        essential_ratio=overlay.essential_ratio,
        discretionary_ratio=overlay.discretionary_ratio,
    )


def _apply_to_feed(db: Session, user: User, plan_id: uuid.UUID, variant: MonthsVariant, months: MonthsModel,
                   overlay, today: datetime.date, ledger_date: datetime.date) -> SpendingApplyResponse:
    """Point the plan's feed at the chosen months (and accounts) and apply it now."""
    feed = feed_for_plan(db, plan_id)
    if variant.source_ids is not None:
        sources = db.query(FinancialSource).filter(FinancialSource.id.in_(variant.source_ids)).all()
        if not all(counts_toward_spending(source) for source in sources):
            raise api_error(422, "VALIDATION_ERROR", "Connected spending uses checking and credit card accounts.")
        feed.source_ids = months.source_ids
    before = {feed.essential_expense_id, feed.discretionary_expense_id}
    feed.basis, feed.basis_months = "months", months.months
    db.flush()
    apply_feed(db, feed, today=ledger_date)
    if feed.error:
        message = feed.error
        db.rollback()
        raise api_error(409, "SPENDING_FEED_PAUSED", message)
    after = [value for value in (feed.essential_expense_id, feed.discretionary_expense_id) if value is not None]
    db.commit()
    db.expire_all()
    covered = feed_expense_ids(db, plan_id)
    fingerprint = expense_fingerprint(load_plan_data(plan_id, user, db, today=today), covered)
    return SpendingApplyResponse(
        fingerprint=fingerprint,
        updated_expense_ids=[value for value in after if value in before],
        created_expense_ids=[value for value in after if value not in before],
        essential_ratio=overlay.essential_ratio,
        discretionary_ratio=overlay.discretionary_ratio,
        basis="months",
    )

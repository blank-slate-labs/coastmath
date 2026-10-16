import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error, validation_error
from app.models.account import CurrentAccount
from app.models.cash_flow_priority import CashFlowPriority
from app.models.income import IncomeStream
from app.models.liability import Liability
from app.models.milestone import Milestone
from app.models.plan import Plan
from app.models.user import User
from app.routers.helpers import get_plan_or_404, plan_scope_filter
from app.scenarios.hooks import mark_plan_changed
from app.schemas.cash_flow_priority import (
    CashFlowPriorityBulkUpdate,
    CashFlowPriorityCreate,
    CashFlowPriorityRead,
    PrioritySet,
)
from coastmath.engine.account_types import (
    EMPLOYER_ONLY_PLAN_TYPES,
    EMPLOYER_PLAN_FAMILY,
    EMPLOYER_PLAN_TYPES,
    ROTH_EMPLOYER_PLAN_TYPES,
    ROTH_PLAN_COUNTERPART,
)
from coastmath.engine.plan_validation import conversion_error, transfer_error
from coastmath.schemas.tax_target import bracket_ceiling_error

router = APIRouter(prefix="/plans/{plan_id}/priorities", tags=["priorities"])


def roth_match_error(target: CurrentAccount, plan: Plan, user_id: uuid.UUID, db: Session) -> str | None:
    """Why a Roth employer match cannot be routed, or None.

    SECURE 2.0 sec. 604 Roth employer money goes to the owner's designated
    Roth account in the same plan type. The rule is rejected rather than
    creating that account, so every account in a plan is one the user made.
    """
    if target.account_type in ROTH_EMPLOYER_PLAN_TYPES:
        return None
    roth_type = ROTH_PLAN_COUNTERPART.get(target.account_type)
    if roth_type is None:
        return f"{target.name}: Roth employer contributions need a 401(k), 403(b) or 457(b) plan"
    exists = db.query(CurrentAccount.id).filter(
        CurrentAccount.user_id == user_id, plan_scope_filter(plan),
        CurrentAccount.account_type == roth_type, CurrentAccount.owner == target.owner,
        CurrentAccount.inherited_year.is_(None)).first()
    if exists is None:
        family = EMPLOYER_PLAN_FAMILY[target.account_type]
        return f"{target.name}: add a Roth {family} for the same owner to receive Roth employer contributions"
    return None


def priority_references(
    db: Session, plan: Plan, user_id: uuid.UUID, items: list[CashFlowPriorityCreate],
) -> tuple[dict[uuid.UUID, CurrentAccount], dict[uuid.UUID, CurrentAccount], dict[uuid.UUID, IncomeStream]]:
    """Check that every account, income, milestone and loan the rules name is in scope.

    Returns the target accounts, source accounts and source incomes by ID.
    """
    in_scope = (CurrentAccount.user_id == user_id, plan_scope_filter(plan))
    account_ids = [item.target_account_id for item in items if item.target_account_id]
    targets = {a.id: a for a in db.query(CurrentAccount).filter(CurrentAccount.id.in_(account_ids), *in_scope).all()}
    missing = set(account_ids) - set(targets)
    if missing:
        raise api_error(
            422, "VALIDATION_ERROR", "Invalid target_account_id references",
            [{"field": "target_account_id", "reason": f"{aid} not found"} for aid in missing],
        )

    # Sources must belong to the same user/plan, before replacing any rows.
    source_accounts = {item.source_account_id for item in items if item.source_account_id}
    sources = {a.id: a for a in db.query(CurrentAccount).filter(CurrentAccount.id.in_(source_accounts), *in_scope).all()}
    source_incomes = {item.source_income_id for item in items if item.source_income_id}
    incomes = {inc.id: inc for inc in db.query(IncomeStream).filter(
        IncomeStream.id.in_(source_incomes), IncomeStream.plan_id == plan.id).all()}
    if source_accounts - set(sources) or source_incomes - set(incomes):
        raise validation_error(
            "Invalid priority source", "source", "Account must belong to you and income must belong to this plan",
        )
    window = {mid for item in items for mid in (item.start_milestone_id, item.end_milestone_id) if mid}
    plan_milestones = {row.id for row in db.query(Milestone.id).filter(Milestone.id.in_(window), Milestone.plan_id == plan.id).all()}
    if window - plan_milestones:
        raise validation_error("Rule milestones must belong to this plan.", "start_milestone_id", "not found in plan")

    debt_targets = {item.target_liability_id for item in items if item.target_liability_id}
    if debt_targets:
        plan_loans = {row.id for row in db.query(Liability.id).filter(
            Liability.id.in_(debt_targets), Liability.plan_id == plan.id).all()}
        if debt_targets - plan_loans:
            raise validation_error(
                "A debt payment rule must name a loan in this plan.", "target_liability_id", "not found in plan",
            )
    return targets, sources, incomes


@router.get("", response_model=PrioritySet)
def list_priorities(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrioritySet:
    # Hold a shared lock through both reads so revision and items are consistent.
    plan = get_plan_or_404(plan_id, current_user.id, db, for_share=True)
    items = (
        db.query(CashFlowPriority)
        .filter(CashFlowPriority.plan_id == plan_id)
        .order_by(CashFlowPriority.priority_rank)
        .all()
    )

    return PrioritySet(items=items, revision=plan.priorities_revision)


@router.put("", response_model=PrioritySet)
def bulk_update_priorities(
    plan_id: uuid.UUID,
    body: CashFlowPriorityBulkUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrioritySet:
    # Serialize all replacements on the parent, even when there are no children.
    # READ COMMITTED rechecks the revision after waiting for a competing commit.
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    if plan.priorities_revision != body.expected_revision:
        raise api_error(
            409, "CONFLICT",
            "Allocation changed since you started editing. Review the latest rules before saving; your draft has not been applied.",
            [{"field": "expected_revision", "reason": "stale allocation revision"}],
        )

    # Validate rank uniqueness
    ranks = [item.priority_rank for item in body.items]
    if len(ranks) != len(set(ranks)):
        raise validation_error("Duplicate priority_rank values", "priority_rank", "must be unique")

    targets, sources, incomes = priority_references(db, plan, current_user.id, body.items)
    # Bulk editing unrelated rules must not force migration of stored 401(k)
    # surplus rules. Match every field except rank, consuming each match once
    # so this cannot create duplicates or introduce new legacy contributions.
    preserved_rules = [
        CashFlowPriorityRead.model_validate(row).model_dump(
            exclude={"id", "plan_id", "priority_rank"}
        )
        for row in db.query(CashFlowPriority).filter(
            CashFlowPriority.plan_id == plan_id
        ).all()
    ]
    # A conversion ceiling saved before the plan's brackets changed may be
    # saved again unchanged (the simulation warns); a new or changed one must
    # name one of the plan's bracket rates.
    stored_rules = list(preserved_rules)
    for item in body.items:
        target = targets.get(item.target_account_id)
        source = sources.get(item.source_account_id)
        reason = None
        if item.priority_type not in ("gain_harvest", "debt_payment") and target is None:
            reason = "Choose a destination account"
        elif item.priority_type == "transfer":
            reason = transfer_error(
                source.account_type if source else None, target.account_type if target else None,
                item.source_account_id == item.target_account_id,
                source_owner=source.owner if source else None,
                target_owner=target.owner if target else None,
                source_inherited=source is not None and source.inherited_year is not None,
                target_inherited=target is not None and target.inherited_year is not None,
            )
        elif item.priority_type == "roth_conversion":
            reason = conversion_error(source, target)
        elif item.priority_type in (None, "contribution") and target.account_type in EMPLOYER_PLAN_TYPES:
            unchanged = item.model_dump(exclude={"priority_rank"})
            if unchanged in preserved_rules:
                preserved_rules.remove(unchanged)
            else:
                reason = f"{target.name}: new or changed {EMPLOYER_PLAN_FAMILY[target.account_type]} contributions must use a payroll rule funded by earned income"
        elif item.priority_type in {"income_percent", "pre_tax_contribution"}:
            income = incomes.get(item.source_income_id)
            if target.account_type not in EMPLOYER_PLAN_TYPES | {"hsa"}:
                reason = "Payroll rules support workplace retirement plans and HSA accounts; use surplus allocation for other destinations"
            elif target.account_type in EMPLOYER_ONLY_PLAN_TYPES and (item.priority_type == "pre_tax_contribution" or item.employee_rate > 0):
                reason = f"{target.name}: a 401(a) takes employer contributions only; set an employer rate and no employee rate"
            elif income is None or not income.is_earned_income or income.is_social_security or income.owner != target.owner:
                reason = "Payroll source must be earned income belonging to the destination account owner"
            elif item.employer_match is not None and item.employer_match.roth:
                reason = roth_match_error(target, plan, current_user.id, db)
        elif item.priority_type == "after_tax_401k":
            income = incomes.get(item.source_income_id)
            if target.account_type != "roth_401k":
                reason = "After-tax 401(k) contributions convert to a Roth 401(k); choose one as the destination"
            elif (income is None or not income.is_earned_income or income.is_social_security
                    or income.is_self_employed or income.owner != target.owner):
                reason = "After-tax 401(k) contributions must come from W-2 wages of the destination account owner"
        if (reason is None and item.priority_type == "roth_conversion" and item.conversion_mode == "fill_bracket"
                and not item.use_plan_tax_target and item.bracket_ceiling_rate is not None):
            ceiling_error = bracket_ceiling_error(plan.tax_settings, item.bracket_ceiling_rate)
            if ceiling_error:
                unchanged = item.model_dump(exclude={"priority_rank"})
                if unchanged in stored_rules:
                    stored_rules.remove(unchanged)
                else:
                    raise validation_error(ceiling_error, "bracket_ceiling_rate")
        # Client workspaces reject newly authored strategies that would be
        # silently skipped or misclassified by the engine. Legacy plans retain
        # their established save contract.
        if reason is None and plan.client_id is not None:
            source = sources.get(item.source_account_id)
            if item.priority_type == "gain_harvest":
                if source is None or source.account_type != "taxable_brokerage":
                    reason = "Gain harvesting requires a taxable brokerage source in this plan"
        if reason:
            raise validation_error(reason, "priorities")

    # Delete existing, insert new only after all validation succeeds. The bulk
    # delete bypasses flush tracking, so report it for scenario sync.
    db.query(CashFlowPriority).filter(
        CashFlowPriority.plan_id == plan_id
    ).delete()
    mark_plan_changed(db, plan_id, "priorities")

    new_items = [
        CashFlowPriority(plan_id=plan_id, **item.model_dump())
        for item in body.items
    ]
    db.add_all(new_items)
    plan.priorities_revision += 1
    db.flush()
    # Materialize our own response before releasing the lock.
    result = PrioritySet(
        items=[CashFlowPriorityRead.model_validate(row) for row in sorted(new_items, key=lambda item: item.priority_rank)],
        revision=plan.priorities_revision,
    )
    db.commit()
    return result

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload

from app.access import (
    ensure_can_create_plan,
    ensure_plan_capacity,
    ensure_plan_openable,
    ensure_plan_writable,
    present_plans,
    require,
)
from app.auth.dependencies import get_current_user
from app.clock import utcnow
from app.db import get_db
from app.errors import api_error, validation_error
from app.models.account import CurrentAccount
from app.models.milestone import Milestone
from app.models.plan import Plan
from app.models.residency_period import ResidencyPeriod
from app.models.spouse import Spouse
from app.models.user import User
from app.routers.clients import get_client_or_404
from app.routers.helpers import (
    client_today,
    get_plan_or_404,
    partner_owned_names,
    plan_scope_filter,
    snapshot_account,
    validate_milestone_window,
    validate_plan_start,
)
from app.scenarios.sync import (
    link_new_scenario,
    parent_of,
    release_scenarios,
    sync_guarded,
)
from app.scenarios.values import copy_plan
from app.schemas.plan import (
    ArchivedPlanSummary,
    PlanCreate,
    PlanRead,
    PlanSummary,
    PlanUpdate,
)
from app.usage import record_usage
from coastmath.engine.account_types import SEPP_ELIGIBLE_TYPES
from coastmath.engine.intl_bridge import drop_retired_entries, is_retired_country
from coastmath.schemas.intl_settings import RegimeError, check_plan_regimes
from coastmath.schemas.local_tax import check_local_tax_state
from coastmath.schemas.tax_adjustments import all_adjustments, referenced_milestone_ids
from coastmath.schemas.tax_target import bracket_target_error

router = APIRouter(prefix="/plans", tags=["plans"])

# 26 USC 72(t)(2)(A)(iv) applies to IRAs, qualified plans and 403(b)s; an
# employer-plan series additionally requires separation from service, which
# the user asserts. A governmental 457(b) carries no 72(t) tax to avoid.
SEPP_ELIGIBLE_ACCOUNT_TYPES = SEPP_ELIGIBLE_TYPES


class PlanDuplicate(BaseModel):
    client_id: uuid.UUID | None = None
    # A scenario follows the source (its Main plan) on every save (app.scenarios).
    as_scenario: bool = False
    name: str | None = Field(default=None, min_length=1, max_length=255)


def _scenario_source_error(message: str) -> HTTPException:
    return validation_error(message, "as_scenario")


def _reconcile_local_tax(plan: Plan, data: dict) -> None:
    """Keep the plan's local tax inside its state across partial updates.

    An explicit selection must belong to the saved or updated state. A state
    change without a selection clears a saved locality from another state,
    because a city or county selection has no meaning outside its state.
    """
    state_code = data.get("state_code", plan.state_code)
    if "local_tax" in data:
        try:
            check_local_tax_state(data["local_tax"], state_code)
        except ValueError as exc:
            raise validation_error(str(exc), "local_tax") from None
    elif "state_code" in data and plan.local_tax is not None:
        try:
            check_local_tax_state(plan.local_tax, state_code)
        except ValueError:
            data["local_tax"] = None


def _validate_spending_window(plan: Plan, rules: dict | None, db: Session) -> None:
    if not rules:
        return
    start, end = rules.get("start_milestone_id"), rules.get("end_milestone_id")
    milestones = {str(m.id) for m in plan.milestones}
    if any(mid is not None and mid not in milestones for mid in (start, end)) or (start is not None and start == end):
        raise validation_error(
            "Flexible spending needs distinct milestones belonging to this plan.", "spending_rules",
            "invalid milestone window",
        )
    validate_milestone_window(plan, uuid.UUID(start) if start else None, uuid.UUID(end) if end else None, db)


def _validate_withdrawal_strategy(plan: Plan, settings: dict | None) -> None:
    """A saved withdrawal strategy may only start at this plan's own milestone."""
    start = (settings or {}).get("start_milestone_id")
    if start is not None and start not in {str(m.id) for m in plan.milestones if m.id is not None}:
        raise validation_error(
            "The withdrawal strategy's start milestone must belong to this plan.",
            "withdrawal_strategy.start_milestone_id", "not found in plan",
        )


def _validate_tax_customization(plan: Plan, tax_settings: dict | None, has_spouse: bool) -> None:
    """Tax adjustments and scheduled changes may only use this plan's milestones,
    and a federal bracket target must name one of the plan's bracket rates."""
    if not tax_settings:
        return
    target_error = bracket_target_error(tax_settings)
    if target_error:
        raise validation_error(target_error, "tax_settings.tax_target.bracket_rate")
    milestones = {str(m.id) for m in plan.milestones if m.id is not None}
    if referenced_milestone_ids(tax_settings) - milestones:
        raise validation_error(
            "Tax adjustment and scheduled tax change milestones must belong to this plan.", "tax_settings",
            "milestone not found in plan",
        )
    if not has_spouse and any(row.get("owner") == "spouse" for row in all_adjustments(tax_settings)):
        raise validation_error(
            "A partner tax adjustment needs a partner in the plan.", "tax_settings.adjustments", "no spouse",
        )


def _validate_partner_removal(plan: Plan, current_user: User, db: Session) -> None:
    """Removing the partner must not strand their incomes and accounts."""
    accounts = (
        db.query(CurrentAccount)
        .filter(CurrentAccount.user_id == current_user.id, CurrentAccount.owner == "spouse")
        .filter(plan_scope_filter(plan))
        .all()
    )
    names = partner_owned_names(plan, accounts)
    if names:
        message = f"Reassign or remove the partner's items first: {', '.join(names)}."
        raise validation_error(message, "spouse")


def _validate_residency_milestones(plan: Plan, periods: list[dict]) -> None:
    """A residency period may only be bounded by this plan's own milestones."""
    milestones = {m.id for m in plan.milestones}
    for index, period in enumerate(periods):
        for field in ("start_milestone_id", "end_milestone_id"):
            if period.get(field) is not None and period[field] not in milestones:
                raise validation_error(
                    "Residency milestones must belong to this plan.", f"residency_periods.{index}.{field}",
                    "not found in plan",
                )


def _reconcile_regime(plan: Plan, data: dict, residency_periods: list[dict] | None) -> None:
    """Check the plan's countries, regions and intl settings after a partial update.

    A country change without a region clears a saved region of the old
    country. Benefits may start only at this plan's own milestones.
    """
    if "tax_country" in data and data["tax_country"] in (None, plan.tax_country):
        # Unchanged (a plan in a retired country may resend its own code).
        data.pop("tax_country")
    country = data.get("tax_country") or plan.tax_country or "US"
    if "currency" in data and data["currency"] is None:
        data.pop("currency")
    if "tax_region" in data:
        region = data["tax_region"]
    else:
        region = plan.tax_region
        if "tax_country" in data and region is not None and data["tax_country"] != plan.tax_country:
            region = data["tax_region"] = None
    settings = data.get("intl_settings", plan.intl_settings)
    periods = residency_periods if residency_periods is not None else [
        {"country": p.country, "region": p.region, "state_code": p.state_code} for p in plan.residency_periods]
    regime_fields = {"tax_country", "tax_region", "intl_settings"}
    if residency_periods is None and regime_fields.isdisjoint(data):
        return
    if "intl_settings" not in data and settings:
        # Entries of a retired country can never apply; drop them when the regime changes.
        pruned = drop_retired_entries(settings)
        if pruned != settings:
            settings = data["intl_settings"] = pruned
    # A plan still saved in a retired country keeps saving other edits; it
    # cannot run until it switches (intl_bridge.check_supported_countries).
    if "tax_country" in data or not is_retired_country(country):
        try:
            check_plan_regimes(country, region, settings, periods)
        except RegimeError as exc:
            raise validation_error(str(exc), exc.field) from None
    milestones = {str(m.id) for m in plan.milestones if m.id is not None}
    for index, benefit in enumerate((settings or {}).get("benefits") or []):
        start = benefit.get("start_milestone_id")
        if start is not None and str(start) not in milestones:
            raise validation_error("A benefit's start milestone must belong to this plan.",
                                   f"intl_settings.benefits.{index}.start_milestone_id")


@router.post("/{plan_id}/duplicate", response_model=PlanRead, status_code=201)
def duplicate_plan(
    plan_id: uuid.UUID,
    body: PlanDuplicate | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Plan:
    """Copy client plans, including accounts, atomically with fresh identities.

    Allocate every child identity first so milestone, income and property
    references (including those in JSON settings) point inside the new plan.
    """
    source = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    require(current_user, "duplicate")
    ensure_plan_capacity(current_user, db)
    as_scenario = bool(body and body.as_scenario)
    if as_scenario:
        if source.parent_plan_id is not None:
            main = parent_of(db, source)
            raise _scenario_source_error(
                f"“{source.name}” is already a scenario. Create new scenarios from its main plan"
                + (f" “{main.name}”." if main else "."))
        if source.client_id is None:
            raise _scenario_source_error("Scenarios need a plan in a client workspace.")
        if body.client_id and body.client_id != source.client_id:
            raise _scenario_source_error("A scenario stays in its main plan's client workspace.")
        if source.archived_at is not None:
            raise _scenario_source_error("Restore this plan before creating a scenario from it.")
    client_id = body.client_id if body and body.client_id else source.client_id
    if client_id:
        get_client_or_404(client_id, current_user.id, db)
    accounts = db.query(CurrentAccount).filter(CurrentAccount.user_id == current_user.id,
        plan_scope_filter(source)).all() if client_id else []
    # A fixed-date legacy plan owns its historical account values in JSON.
    # Materialize those values when copying it into a client workspace.
    if client_id and source.client_id is None and source.plan_type == "FIXED_DATE" and source.snapshot_conditions:
        accounts = [snapshot_account(key, info, current_user.id, default_name="Imported account")
                    for key, info in source.snapshot_conditions.items()]
    if body and body.name:
        name = body.name
    else:
        name = f"{source.name[:244]} (scenario)" if as_scenario else f"{source.name[:248]} (copy)"
    copied, pairs = copy_plan(db, source, accounts, client_id=client_id, name=name,
                              parent_plan_id=source.id if as_scenario else None)
    if as_scenario:
        link_new_scenario(db, source, copied, pairs)
    db.commit()
    db.refresh(copied)
    # Counted after the copy commits: the count commits on its own.
    record_usage(db, current_user.id, "duplicate")
    return present_plans([copied], current_user, db)[0]


@router.post("", response_model=PlanRead, status_code=201)
def create_plan(
    body: PlanCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: date = Depends(client_today),
) -> Plan:
    ensure_can_create_plan(current_user, db, client_id=body.client_id)
    payload = body.model_dump()
    if any(change.get("milestone_id") for change in payload.get("filing_status_changes") or []):
        raise api_error(422, "VALIDATION_ERROR", "Create milestones before scheduling filing status changes")
    spouse_payload = payload.pop("spouse", None)
    retirement_age = payload.pop("retirement_milestone_age", None)
    if body.client_id:
        get_client_or_404(body.client_id, current_user.id, db)
        if body.snapshot_conditions:
            raise validation_error(
                "Client plans use plan accounts for opening balances; snapshot_conditions must be empty",
                "snapshot_conditions",
            )
        if body.sepp_settings and body.sepp_settings.source_account_id:
            raise validation_error(
                "Create the plan and its accounts before selecting a SEPP source", "sepp_settings.source_account_id",
            )
    if body.sepp_settings is not None:
        # JSONB cannot store UUID objects; the engine reads the id back as text.
        payload["sepp_settings"] = body.sepp_settings.model_dump(mode="json")
    if body.healthcare_settings is not None:
        payload["healthcare_settings"] = body.healthcare_settings.model_dump(mode="json")
    if body.intl_settings is not None:
        payload["intl_settings"] = body.intl_settings.model_dump(mode="json")
        if body.intl_settings.milestone_ids():
            raise validation_error("Create milestones before starting a benefit at one", "intl_settings.benefits")
    plan = Plan(user_id=current_user.id, **payload)
    if spouse_payload is not None:
        plan.spouse = Spouse(**spouse_payload)
    start_year = (body.start_date or today).year
    if retirement_age is not None and body.birth_year + retirement_age > start_year:
        plan.milestones.append(Milestone(name="Retirement", trigger_type="age", trigger_value=retirement_age))
    _validate_spending_window(plan, payload.get("spending_rules"), db)
    _validate_withdrawal_strategy(plan, payload.get("withdrawal_strategy"))
    _validate_tax_customization(plan, payload.get("tax_settings"), spouse_payload is not None)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return present_plans([plan], current_user, db)[0]


@router.get("", response_model=list[PlanRead])
def list_plans(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client_id: uuid.UUID | None = None,
) -> list[Plan]:
    if client_id:
        get_client_or_404(client_id, current_user.id, db)
    plans = (
        db.query(Plan)
        .filter(Plan.user_id == current_user.id, Plan.archived_at.is_(None))
        .filter(Plan.client_id == client_id if client_id else True)
        .order_by(Plan.created_at.desc())
        .all()
    )
    return present_plans(plans, current_user, db, start_grace=True)


@router.get("/summaries", response_model=list[PlanSummary])
def list_plan_summaries(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client_id: uuid.UUID | None = None,
):
    if client_id:
        get_client_or_404(client_id, current_user.id, db)
    return (
        db.query(Plan.id, Plan.client_id, Plan.name, Plan.plan_type, Plan.created_at, Plan.parent_plan_id)
        .filter(Plan.user_id == current_user.id, Plan.archived_at.is_(None))
        .filter(Plan.client_id == client_id if client_id else True)
        .order_by(Plan.created_at.desc())
        .all()
    )


@router.get("/archived", response_model=list[ArchivedPlanSummary])
def list_archived_plans(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Archived plans by name and date."""
    return (
        db.query(Plan.id, Plan.client_id, Plan.name, Plan.created_at, Plan.archived_at)
        .filter(Plan.user_id == current_user.id, Plan.archived_at.is_not(None))
        .order_by(Plan.archived_at.desc(), Plan.id)
        .all()
    )


@router.get("/{plan_id}", response_model=PlanRead)
def get_plan(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Plan:
    plan = (
        db.query(Plan)
        .options(
            selectinload(Plan.milestones),
            selectinload(Plan.income_streams),
            selectinload(Plan.expenses),
            selectinload(Plan.priorities),
            selectinload(Plan.drawdown_order),
            selectinload(Plan.assumption_curves),
            selectinload(Plan.real_assets),
            selectinload(Plan.liabilities),
            selectinload(Plan.residency_periods),
            selectinload(Plan.spouse),
        )
        .filter(Plan.id == plan_id, Plan.user_id == current_user.id)
        .first()
    )
    if not plan:
        raise api_error(404, "NOT_FOUND", "Plan not found")
    ensure_plan_openable(plan, current_user)
    return present_plans([plan], current_user, db, start_grace=True)[0]


@router.put("/{plan_id}", response_model=PlanRead)
def update_plan(
    plan_id: uuid.UUID,
    body: PlanUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Plan:
    # Serialize replacements before loading child collections, including when
    # the residency list is empty (there are then no child rows to lock).
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    ensure_plan_writable(plan.id, current_user, db)
    data = body.model_dump(exclude_unset=True)
    milestone_ids = {str(ms.id) for ms in plan.milestones}
    if any(change.get("milestone_id") and change["milestone_id"] not in milestone_ids
           for change in data.get("filing_status_changes") or []):
        raise api_error(422, "VALIDATION_ERROR", "Filing status milestone not found in plan")
    if plan.client_id and data.get("snapshot_conditions"):
        raise validation_error(
            "Client plans use plan accounts for opening balances; snapshot_conditions must be empty",
            "snapshot_conditions",
        )
    if data.get("baseline_plan_id") is not None:
        baseline = get_plan_or_404(data["baseline_plan_id"], current_user.id, db)
        if baseline.client_id != plan.client_id:
            raise api_error(422, "VALIDATION_ERROR", "Comparison plans must belong to the same client")
    validate_plan_start(plan, data)
    _reconcile_local_tax(plan, data)
    if "spending_rules" in data:
        _validate_spending_window(plan, data["spending_rules"], db)
    if "sepp_settings" in data and body.sepp_settings is not None:
        data["sepp_settings"] = body.sepp_settings.model_dump(mode="json")
    if "healthcare_settings" in data and body.healthcare_settings is not None:
        data["healthcare_settings"] = body.healthcare_settings.model_dump(mode="json")
    if data.get("cash_reserve_settings") is not None:
        data["cash_reserve_settings"] = body.cash_reserve_settings.model_dump(mode="json")
    if data.get("withdrawal_strategy") is not None:
        data["withdrawal_strategy"] = body.withdrawal_strategy.model_dump(mode="json")
        _validate_withdrawal_strategy(plan, data["withdrawal_strategy"])
    if data.get("intl_settings") is not None:
        data["intl_settings"] = body.intl_settings.model_dump(mode="json")
    residency_periods = data.pop("residency_periods", None)
    if residency_periods:
        _validate_residency_milestones(plan, residency_periods)
    _reconcile_regime(plan, data, residency_periods)
    spouse_set = "spouse" in data
    spouse_payload = data.pop("spouse", None)
    if spouse_set and spouse_payload is None and plan.spouse is not None:
        _validate_partner_removal(plan, current_user, db)
    if "tax_settings" in data or (spouse_set and spouse_payload is None):
        _validate_tax_customization(plan, data.get("tax_settings", plan.tax_settings),
                                    spouse_payload is not None if spouse_set else plan.spouse is not None)
    sepp = data.get("sepp_settings")
    if isinstance(sepp, dict) and sepp.get("enabled") and sepp.get("source_account_id") is not None:
        account = (
            db.query(CurrentAccount)
            .filter(CurrentAccount.id == uuid.UUID(str(sepp["source_account_id"])), CurrentAccount.user_id == current_user.id)
            .filter(plan_scope_filter(plan))
            .first()
        )
        if account is None or account.account_type not in SEPP_ELIGIBLE_ACCOUNT_TYPES:
            raise validation_error(
                "SEPP source must be a traditional IRA, 401(k), 403(b) or 401(a) you own",
                "sepp_settings.source_account_id", "not an eligible pre-tax account",
            )
    reserve = data.get("cash_reserve_settings")
    if isinstance(reserve, dict) and reserve.get("account_ids"):
        reserve_ids = [uuid.UUID(str(value)) for value in reserve["account_ids"]]
        found = {
            account.id: account.account_type
            for account in db.query(CurrentAccount)
            .filter(CurrentAccount.id.in_(reserve_ids), CurrentAccount.user_id == current_user.id)
            .filter(plan_scope_filter(plan))
            .all()
        }
        if len(found) != len(reserve_ids) or any(kind not in ("checking", "savings") for kind in found.values()):
            raise validation_error(
                "Cash reserve accounts must be checking or savings accounts in this plan",
                "cash_reserve_settings.account_ids", "not an eligible cash account",
            )
    for field, value in data.items():
        setattr(plan, field, value)
    if spouse_set:
        if spouse_payload is None:
            plan.spouse = None  # delete-orphan cascade removes the record
        elif plan.spouse is None:
            plan.spouse = Spouse(**spouse_payload)
        else:
            for field, value in spouse_payload.items():
                setattr(plan.spouse, field, value)
    if residency_periods is not None:
        plan.residency_periods.clear()
        db.flush()
        for rp in residency_periods:
            plan.residency_periods.append(ResidencyPeriod(**rp))
    db.commit()
    db.refresh(plan)
    return present_plans([plan], current_user, db)[0]


@router.delete("/{plan_id}", status_code=204)
def delete_plan(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    plan = get_plan_or_404(plan_id, current_user.id, db)
    # Clear comparison links before the referenced plan is deleted.
    db.query(Plan).filter(Plan.user_id == current_user.id, Plan.baseline_plan_id == plan_id).update({Plan.baseline_plan_id: None}, synchronize_session="fetch")
    # A deleted Main's scenarios keep their data as independent plans.
    release_scenarios(db, plan_id)
    db.delete(plan)
    db.commit()
    return Response(status_code=204)


@router.post("/{plan_id}/archive", response_model=PlanRead)
def archive_plan(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Plan:
    """Set a plan aside. The archived plan is kept and can be restored."""
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    if plan.archived_at is None:
        plan.archived_at = utcnow()
        db.commit()
        db.refresh(plan)
    else:
        # Already archived: answering shows its content, which the policy may limit.
        ensure_plan_openable(plan, current_user)
    return present_plans([plan], current_user, db)[0]


@router.post("/{plan_id}/restore", response_model=PlanRead)
def restore_plan(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Plan:
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    require(current_user, "restore_plan")
    if plan.archived_at is not None:
        plan.archived_at = None
        # A restored scenario catches up with the changes Main made meanwhile.
        main = parent_of(db, plan)
        if main is not None:
            sync_guarded(db, main, plan)
        db.commit()
        db.refresh(plan)
    return present_plans([plan], current_user, db)[0]


@router.post("/{plan_id}/edit-notice", status_code=204)
def record_edit_notice(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """A client showed this plan's closing notice. The first time is kept: once a
    notice has been seen, a closed window gets no grace."""
    plan = get_plan_or_404(plan_id, current_user.id, db, for_update=True)
    if plan.edit_notice_seen_at is None:
        plan.edit_notice_seen_at = utcnow()
        db.commit()
    return Response(status_code=204)

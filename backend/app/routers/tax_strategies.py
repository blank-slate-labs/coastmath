import datetime
import uuid
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.engine.plan_converter import plan_to_engine_data
from app.errors import validation_error
from app.models.account import CurrentAccount
from app.models.milestone import Milestone
from app.models.plan import Plan
from app.models.user import User
from app.rate_limit import engine_budget, limiter, session_user
from app.routers.engine_errors import engine_errors
from app.routers.helpers import client_today, get_plan_or_404, plan_account_filter
from app.usage import count_usage
from coastmath.engine.account_types import ROTH_TYPES, TRADITIONAL_RETIREMENT_TYPES
from coastmath.engine.household_lifecycle import simulation_end_year
from coastmath.engine.intl_bridge import (
    UnsupportedCountryError,
    check_supported_countries,
)
from coastmath.engine.milestones import resolve_deterministic_milestones
from coastmath.engine.plan_validation import (
    validate_account_history,
    validate_roth_conversion_rules,
    validate_transfer_rules,
)
from coastmath.engine.tax_strategy import (
    OBJECTIVES,
    build_candidates,
    compare_strategies,
    objective_direction,
)
from coastmath.engine.tax_strategy_search import (
    DEFAULT_SIMULATIONS,
    MAX_RATES,
    MAX_SIMULATIONS,
    MAX_WINDOWS,
    SearchSpace,
    SearchWindow,
    StrategySpec,
    materialize,
    run_search,
)
from coastmath.engine.tax_target import plan_bracket_rates
from coastmath.engine.types import MilestoneData

router = APIRouter(prefix="/plans/{plan_id}/tax-strategies", tags=["tax-strategies"])

_SOURCE_TYPES = TRADITIONAL_RETIREMENT_TYPES
_TARGET_TYPES = ROTH_TYPES


class StrategyCompareRequest(BaseModel):
    strategy_type: Literal["roth_conversion", "gain_harvest"] = "roth_conversion"
    source_account_id: uuid.UUID
    target_account_id: uuid.UUID | None = None
    bracket_ceilings: list[float] = Field(default=[0.12, 0.22, 0.24], min_length=1, max_length=6)
    magi_cap: float | None = Field(default=None, ge=0)
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    objective: str = "net_legacy"


class StrategyMetricsRead(BaseModel):
    key: str
    label: str
    success: bool
    failure_year: int | None
    lifetime_taxes: float
    lifetime_healthcare: float
    final_net_worth: float
    net_legacy: float
    total_converted: float
    conversion_years: int
    irmaa_years: int
    aca_credit_lost_years: int
    peak_marginal_rate: float
    objective_value: float
    delta_vs_baseline: float
    is_best: bool
    notes: list[str]
    # Additive objective measures; the other objectives' dollar totals.
    lifetime_effective_tax_rate: float = 0.0
    total_aca_subsidies: float = 0.0
    total_rmd_distributions: float = 0.0
    total_irmaa_surcharge: float = 0.0


class StrategyCompareResponse(BaseModel):
    objective: str
    objective_description: str
    baseline_key: str
    best_key: str | None
    candidates: list[StrategyMetricsRead]
    caveats: list[str]
    proposed_priority: dict | None
    #: Income tax rate applied to end-of-plan pre-tax balances in the net
    #: legacy and end net worth objectives: the heir rate, else 0.24.
    pre_tax_discount_rate: float


def _plan_accounts(plan_id: uuid.UUID, current_user: User, db: Session) -> dict[uuid.UUID, CurrentAccount]:
    rows = db.query(CurrentAccount).filter(
        CurrentAccount.user_id == current_user.id, plan_account_filter(plan_id, current_user.id, db)).all()
    return {a.id: a for a in rows}


def _check_harvest_source(source: CurrentAccount | None, field: str) -> None:
    if source is None or source.account_type != "taxable_brokerage":
        raise validation_error("Harvesting needs a taxable brokerage account", field, "not a taxable brokerage account")
    if source.cost_basis is None:
        raise validation_error("Enter the account's cost basis before harvesting gains", field, "cost basis unknown")


def _check_conversion_accounts(source: CurrentAccount | None, target: CurrentAccount | None,
                               source_field: str, target_field: str) -> None:
    if source is None or source.account_type not in _SOURCE_TYPES:
        raise validation_error("Source must be your traditional IRA or workplace plan", source_field, "not an eligible pre-tax account")
    if target is None or target.account_type not in _TARGET_TYPES:
        raise validation_error("Target must be your Roth IRA or Roth workplace plan", target_field, "not an eligible Roth account")
    if (source.owner or "self") != (target.owner or "self"):
        raise validation_error("Conversions stay with one owner", target_field, "source and target must have the same owner")


def _check_milestones(plan_id: uuid.UUID, db: Session, references: tuple[tuple[str, uuid.UUID | None], ...]) -> dict[uuid.UUID, str]:
    """Names of the referenced milestones; 422 for any that is not in this plan."""
    names: dict[uuid.UUID, str] = {}
    for label, ms_id in references:
        if ms_id is None:
            continue
        row = db.query(Milestone.id, Milestone.name).filter(Milestone.id == ms_id, Milestone.plan_id == plan_id).first()
        if not row:
            raise validation_error("Milestone not found in this plan", label, f"{ms_id} not found")
        names[ms_id] = row.name
    return names


def _load_engine_plan(plan_id: uuid.UUID, accounts: dict[uuid.UUID, CurrentAccount], db: Session,
                      today: datetime.date, purpose: str):
    """The plan with its children as engine input, validated before any simulation."""
    plan = (
        db.query(Plan)
        .options(
            selectinload(Plan.milestones), selectinload(Plan.income_streams), selectinload(Plan.expenses),
            selectinload(Plan.priorities), selectinload(Plan.drawdown_order), selectinload(Plan.assumption_curves),
            selectinload(Plan.real_assets), selectinload(Plan.liabilities), selectinload(Plan.residency_periods),
            selectinload(Plan.spouse), selectinload(Plan.charity_entities),
        )
        .filter(Plan.id == plan_id)
        .first()
    )
    plan_data = plan_to_engine_data(plan, list(accounts.values()), today=today)
    try:
        check_supported_countries(plan_data)
    except UnsupportedCountryError as error:
        raise validation_error(str(error), error.field) from error
    try:
        validate_transfer_rules(plan_data.priorities, plan_data.accounts)
        validate_roth_conversion_rules(plan_data.priorities, plan_data.accounts)
        validate_account_history(plan_data.accounts, plan_data.start_year)
        resolve_deterministic_milestones(plan_data.milestones,plan_data.birth_year,plan_data.birth_month)
        if simulation_end_year(plan_data) <= plan_data.start_year:
            raise ValueError("Life expectancy must be later than the plan start age")
    except ValueError as error:
        raise validation_error(str(error), "plan", f"Review the saved plan inputs before {purpose}") from error
    return plan, plan_data


@router.post("/compare", response_model=StrategyCompareResponse, dependencies=[Depends(count_usage("tax_optimizer"))])
@limiter.limit("10/minute", key_func=session_user)
@engine_budget
def compare_tax_strategies(
    request: Request,
    plan_id: uuid.UUID,
    body: StrategyCompareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> StrategyCompareResponse:
    """Run full simulations for a bounded set of bracket-fill conversion rules."""
    get_plan_or_404(plan_id, current_user.id, db)
    if body.objective not in OBJECTIVES:
        raise validation_error("Unknown objective", "objective", f"must be one of {sorted(OBJECTIVES)}")
    accounts = _plan_accounts(plan_id, current_user, db)
    source = accounts.get(body.source_account_id)
    target = accounts.get(body.target_account_id) if body.target_account_id else None
    if body.strategy_type == "gain_harvest":
        _check_harvest_source(source, "source_account_id")
    else:
        _check_conversion_accounts(source, target, "source_account_id", "target_account_id")
    _check_milestones(plan_id, db, (("start_milestone_id", body.start_milestone_id), ("end_milestone_id", body.end_milestone_id)))
    _, plan_data = _load_engine_plan(plan_id, accounts, db, today, "comparing strategies")
    candidates = build_candidates(
        plan_data,
        source_account_id=str(body.source_account_id),
        target_account_id=str(body.target_account_id) if body.target_account_id else None,
        bracket_ceilings=body.bracket_ceilings, magi_cap=body.magi_cap, strategy_type=body.strategy_type,
        start_milestone_id=str(body.start_milestone_id) if body.start_milestone_id else None,
        end_milestone_id=str(body.end_milestone_id) if body.end_milestone_id else None,
    )
    if len(candidates) < 2:
        raise validation_error("No valid bracket ceilings", "bracket_ceilings",
                               "choose capital-gains rates such as 0.0 or 0.15" if body.strategy_type == "gain_harvest"
                               else "choose federal bracket rates such as 0.12, 0.22 or 0.24")
    with engine_errors("Tax strategy comparison engine encountered an error",
                       "Tax strategy comparison failed for plan %s", plan_id):
        comparison = compare_strategies(plan_data, candidates, body.objective)
    best = next((c for c in candidates if c.key == comparison.best_key and c.priority is not None), None)
    proposed = None
    if best is not None:
        p = best.priority
        proposed = {
            "priority_type": p.priority_type, "source_account_id": p.source_account_id,
            "target_account_id": p.target_account_id, "conversion_mode": "fill_bracket",
            "bracket_ceiling_rate": p.bracket_ceiling_rate, "magi_cap": p.magi_cap,
            "start_milestone_id": p.start_milestone_id, "end_milestone_id": p.end_milestone_id,
            "max_annual_amount": None,
        }
    return StrategyCompareResponse(
        objective=comparison.objective, objective_description=comparison.objective_description,
        baseline_key=comparison.baseline_key, best_key=comparison.best_key,
        candidates=[StrategyMetricsRead(**asdict(m)) for m in comparison.candidates],
        caveats=comparison.caveats, proposed_priority=proposed,
        pre_tax_discount_rate=comparison.pre_tax_discount_rate,
    )


# ---------------------------------------------------------------------------
# Bounded staged search
# ---------------------------------------------------------------------------

BracketRate = Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]


class SearchConversionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_account_id: uuid.UUID
    target_account_id: uuid.UUID


class SearchHarvestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_account_id: uuid.UUID


class SearchWindowRequest(BaseModel):
    """A timing window. Each side is a milestone of this plan, a calendar year
    or the plan holder's age; years and ages are inclusive (the rules run in
    ``end_year`` and at ``end_age``, and stop the year after)."""
    model_config = ConfigDict(extra="forbid")

    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    start_year: int | None = Field(default=None, ge=1900, le=2200)
    end_year: int | None = Field(default=None, ge=1900, le=2200)
    start_age: int | None = Field(default=None, ge=0, le=120)
    end_age: int | None = Field(default=None, ge=0, le=120)

    @model_validator(mode="after")
    def _has_a_bound(self) -> "SearchWindowRequest":
        for side in ("start", "end"):
            given = [name for name in (f"{side}_milestone_id", f"{side}_year", f"{side}_age")
                     if getattr(self, name) is not None]
            if len(given) > 1:
                raise ValueError(f"a window's {side} is a milestone, a year or an age, not several")
        if self.start_bound is None and self.end_bound is None:
            raise ValueError("a window needs a start or an end")
        for kind in ("year", "age"):
            start, end = getattr(self, f"start_{kind}"), getattr(self, f"end_{kind}")
            if start is not None and end is not None and end < start:
                raise ValueError(f"end_{kind} must not be before start_{kind}")
        return self

    @property
    def start_bound(self):
        return next((v for v in (self.start_milestone_id, self.start_year, self.start_age) if v is not None), None)

    @property
    def end_bound(self):
        return next((v for v in (self.end_milestone_id, self.end_year, self.end_age) if v is not None), None)

    def key(self) -> tuple:
        return (self.start_milestone_id, self.start_year, self.start_age,
                self.end_milestone_id, self.end_year, self.end_age)


class StrategySearchRequest(BaseModel):
    """Which dimensions the search may vary. Everything is bounded server-side."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    objective: str = "net_legacy"
    #: Federal bracket rates to try as the tax target; required with any action.
    bracket_rates: list[BracketRate] = Field(default_factory=list, max_length=MAX_RATES)
    conversion: SearchConversionRequest | None = None
    harvest: SearchHarvestRequest | None = None
    blend_withdrawals: bool = False
    drawdown_presets: list[Literal["taxable_first", "pretax_first", "roth_before_pretax"]] = Field(
        default_factory=list, max_length=3)
    windows: list[SearchWindowRequest] = Field(default_factory=list, max_length=MAX_WINDOWS)
    max_simulations: int = Field(default=DEFAULT_SIMULATIONS, ge=2, le=MAX_SIMULATIONS)

    @model_validator(mode="after")
    def _consistent_dimensions(self) -> "StrategySearchRequest":
        actions = self.conversion is not None or self.harvest is not None or self.blend_withdrawals
        if not actions and not self.drawdown_presets:
            raise ValueError("choose at least one action or withdrawal order to search")
        if actions and not self.bracket_rates:
            raise ValueError("bracket_rates is required when an action is selected")
        if self.bracket_rates and not actions:
            raise ValueError("bracket_rates apply only with a conversion, harvest or withdrawal-blending action")
        if self.windows and self.conversion is None and self.harvest is None:
            raise ValueError("windows apply only to conversions and gain harvesting")
        if len({round(r, 9) for r in self.bracket_rates}) != len(self.bracket_rates):
            raise ValueError("bracket_rates must be distinct")
        if len(set(self.drawdown_presets)) != len(self.drawdown_presets):
            raise ValueError("drawdown_presets must be distinct")
        if len({w.key() for w in self.windows}) != len(self.windows):
            raise ValueError("windows must be distinct")
        if actions and len(self.bracket_rates) + 1 > self.max_simulations:
            raise ValueError("max_simulations must cover the baseline and one simulation per bracket rate")
        return self


class PlanChangeRead(BaseModel):
    kind: Literal["add", "replace"]
    target: Literal["priority", "milestone", "tax_target", "blend_drawdown", "drawdown_order"]
    summary: str
    before: Any = None
    after: Any = None


class SearchProposalRead(BaseModel):
    """What applying the candidate would write; nothing is written by the search."""
    priorities_to_add: list[dict[str, Any]]
    #: Keys to set in the plan's tax settings (tax_target and/or blend flag), or null.
    tax_settings: dict[str, Any] | None
    #: The complete replacement withdrawal order, or null to keep the saved one.
    drawdown_order: list[dict[str, Any]] | None
    #: Milestones a year or age window needs, created before the rules. Each
    #: ``id`` is a placeholder that ``priorities_to_add`` refers to.
    milestones_to_add: list[dict[str, Any]] = Field(default_factory=list)


class SearchCandidateRead(BaseModel):
    key: str
    label: str
    stage: Literal["baseline", "rate_scan", "combination"]
    rank: int
    is_baseline: bool
    is_best: bool
    improves_baseline: bool
    success: bool
    failure_year: int | None
    actions: list[str]
    bracket_rate: float | None
    drawdown_preset: str
    window_index: int | None
    objective_value: float
    delta_vs_baseline: float
    lifetime_taxes: float
    lifetime_healthcare: float
    final_net_worth: float
    net_legacy: float
    lifetime_income: float
    lifetime_effective_tax_rate: float
    total_aca_subsidies: float
    total_rmd_distributions: float
    total_irmaa_surcharge: float
    total_converted: float
    total_harvested: float
    peak_marginal_rate: float
    notes: list[str]
    changes: list[PlanChangeRead]
    proposal: SearchProposalRead


class SearchCountsRead(BaseModel):
    max_simulations: int
    simulated: int
    stage1_simulated: int
    stage2_simulated: int
    cache_hits: int
    grid_requested: int
    grid_size: int
    skipped_by_budget: int
    screened_out: int
    budget_exhausted: bool


class SearchWindowRead(BaseModel):
    index: int
    label: str
    start_milestone_id: uuid.UUID | None
    end_milestone_id: uuid.UUID | None
    start_year: int | None = None
    end_year: int | None = None
    start_age: int | None = None
    end_age: int | None = None


class StrategySearchResponse(BaseModel):
    objective: str
    objective_description: str
    objective_direction: Literal["higher", "lower"]
    baseline_key: str
    #: The best of the evaluated candidates ("baseline" means keep the saved plan);
    #: null when no evaluated candidate keeps the plan funded. Never a global optimum.
    best_key: str | None
    candidates: list[SearchCandidateRead]
    counts: SearchCountsRead
    survivor_rates: list[float]
    windows: list[SearchWindowRead]
    caveats: list[str]
    pre_tax_discount_rate: float
    #: The plan's allocation revision when the search ran; pass it as
    #: ``expected_revision`` when applying so a changed plan is rejected.
    priorities_revision: int


def _window_label(start: str | None, end: str | None) -> str:
    if start and end:
        return f"From {start} to {end}"
    return f"From {start}" if start else f"Until {end}"


def _search_window(index: int, w: "SearchWindowRequest", names: dict) -> SearchWindow:
    """An engine window; a year or age bound becomes a new milestone."""
    milestones: list[MilestoneData] = []
    ids: dict[str, str | None] = {}
    words: dict[str, str | None] = {}
    for side in ("start", "end"):
        milestone_id, year, age = (getattr(w, f"{side}_milestone_id"), getattr(w, f"{side}_year"),
                                   getattr(w, f"{side}_age"))
        # An inclusive end stops the rules from the following year or age.
        shift = 1 if side == "end" else 0
        new_id = f"strategy-window-{index + 1}-{side}"
        if milestone_id is not None:
            ids[side] = str(milestone_id)
            words[side] = names.get(milestone_id)
        elif year is not None:
            milestones.append(MilestoneData(id=new_id, name=f"Start of {year + shift}", trigger_type="date",
                                            trigger_date=f"{year + shift:04d}-01-01"))
            ids[side] = new_id
            words[side] = str(year)
        elif age is not None:
            milestones.append(MilestoneData(id=new_id, name=f"Age {age + shift}", trigger_type="age",
                                            trigger_value=float(age + shift)))
            ids[side] = new_id
            words[side] = f"age {age}"
        else:
            ids[side] = None
            words[side] = None
    inclusive_end = w.end_milestone_id is None and words["end"] is not None
    if inclusive_end:
        label = f"From {words['start']} through {words['end']}" if words["start"] else f"Through {words['end']}"
    else:
        label = _window_label(words["start"], words["end"])
    return SearchWindow(label=label, start_milestone_id=ids["start"], end_milestone_id=ids["end"],
                        milestones=tuple(milestones))


@router.post("/search", response_model=StrategySearchResponse, dependencies=[Depends(count_usage("tax_optimizer"))])
@limiter.limit("10/minute", key_func=session_user)
@engine_budget
def search_tax_strategies(
    request: Request,
    plan_id: uuid.UUID,
    body: StrategySearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> StrategySearchResponse:
    """Staged grid search over bracket rates, actions, withdrawal order and timing.

    Read-only: the saved plan is never changed. The best result is the best of
    the bounded set that was simulated, not a global optimum.
    """
    get_plan_or_404(plan_id, current_user.id, db)
    if body.objective not in OBJECTIVES:
        raise validation_error("Unknown objective", "objective", f"must be one of {sorted(OBJECTIVES)}")
    accounts = _plan_accounts(plan_id, current_user, db)
    if body.conversion is not None:
        _check_conversion_accounts(accounts.get(body.conversion.source_account_id),
                                   accounts.get(body.conversion.target_account_id),
                                   "conversion.source_account_id", "conversion.target_account_id")
    if body.harvest is not None:
        _check_harvest_source(accounts.get(body.harvest.source_account_id), "harvest.source_account_id")
    references = tuple(
        (f"windows[{index}].{side}_milestone_id", getattr(window, f"{side}_milestone_id"))
        for index, window in enumerate(body.windows) for side in ("start", "end"))
    milestone_names = _check_milestones(plan_id, db, references)
    plan, plan_data = _load_engine_plan(plan_id, accounts, db, today, "searching strategies")

    available = plan_bracket_rates(plan_data.tax_settings, plan_data.filing_status)
    rates: list[float] = []
    for index, requested in enumerate(body.bracket_rates):
        match = next((rate for rate in available if abs(rate - requested) < 1e-9), None)
        if match is None:
            raise validation_error("Not one of the plan's federal bracket rates", f"bracket_rates[{index}]",
                                   "choose from " + ", ".join(f"{rate:g}" for rate in available))
        rates.append(match)

    windows = tuple(_search_window(index, w, milestone_names) for index, w in enumerate(body.windows))
    space = SearchSpace(
        objective=body.objective, bracket_rates=tuple(rates),
        conversion_source_id=str(body.conversion.source_account_id) if body.conversion else None,
        conversion_target_id=str(body.conversion.target_account_id) if body.conversion else None,
        harvest_source_id=str(body.harvest.source_account_id) if body.harvest else None,
        allow_blend=body.blend_withdrawals,
        order_presets=("saved", *body.drawdown_presets), windows=windows, max_simulations=body.max_simulations,
    )
    # The rules every action would add must pass the same checks as saved ones.
    try:
        widest = materialize(plan_data, space, StrategySpec(actions=space.enabled_actions, rate=rates[0] if rates else None))
        validate_transfer_rules(widest.plan.priorities, widest.plan.accounts)
        validate_roth_conversion_rules(widest.plan.priorities, widest.plan.accounts)
    except ValueError as error:
        raise validation_error(str(error), "plan", "Review the strategy rules before searching") from error

    with engine_errors(
        "Tax strategy search engine encountered an error", "Tax strategy search failed for plan %s", plan_id,
        translate={ValueError: lambda exc: validation_error(str(exc), "plan", "Adjust the search settings")},
    ):
        outcome = run_search(plan_data, space)

    candidates = []
    for c in outcome.candidates:
        m = c.measures
        candidates.append(SearchCandidateRead(
            key=c.key, label=c.label, stage=c.stage, rank=c.rank, is_baseline=c.is_baseline,
            is_best=c.key == outcome.best_key, improves_baseline=c.improves_baseline,
            success=c.success, failure_year=c.failure_year, actions=list(c.spec.actions),
            bracket_rate=c.spec.rate, drawdown_preset=c.spec.order, window_index=c.spec.window,
            objective_value=c.objective_value, delta_vs_baseline=c.delta_vs_baseline,
            lifetime_taxes=m.lifetime_taxes, lifetime_healthcare=m.lifetime_healthcare,
            final_net_worth=m.final_net_worth, net_legacy=m.net_legacy, lifetime_income=m.lifetime_income,
            lifetime_effective_tax_rate=m.lifetime_effective_tax_rate,
            total_aca_subsidies=m.total_aca_subsidies, total_rmd_distributions=m.total_rmd_distributions,
            total_irmaa_surcharge=m.total_irmaa_surcharge,
            total_converted=c.total_converted, total_harvested=c.total_harvested,
            peak_marginal_rate=c.peak_marginal_rate, notes=c.notes,
            changes=[PlanChangeRead(**asdict(change)) for change in c.changes],
            proposal=SearchProposalRead(**c.proposal),
        ))
    return StrategySearchResponse(
        objective=outcome.objective, objective_description=outcome.objective_description,
        objective_direction=objective_direction(outcome.objective),
        baseline_key=outcome.baseline_key, best_key=outcome.best_key, candidates=candidates,
        counts=SearchCountsRead(**asdict(outcome.counts)), survivor_rates=outcome.survivor_rates,
        windows=[SearchWindowRead(index=i, label=w.label, start_milestone_id=body.windows[i].start_milestone_id,
                                  end_milestone_id=body.windows[i].end_milestone_id,
                                  start_year=body.windows[i].start_year, end_year=body.windows[i].end_year,
                                  start_age=body.windows[i].start_age, end_age=body.windows[i].end_age)
                 for i, w in enumerate(windows)],
        caveats=outcome.caveats, pre_tax_discount_rate=outcome.pre_tax_discount_rate,
        priorities_revision=plan.priorities_revision,
    )

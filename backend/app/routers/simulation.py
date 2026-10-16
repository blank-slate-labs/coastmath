"""Simulation endpoint — runs the projection engine for a plan."""

import datetime
import math
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import validation_error
from app.models.user import User
from app.rate_limit import engine_budget, limiter, session_user
from app.routers.engine_errors import engine_errors
from app.routers.helpers import client_today, load_plan_data
from app.routers.simulation_stateless import (
    check_historical_start_year,
    net_worth_deltas,
)
from app.usage import count_usage, record_usage
from coastmath.engine.historical_stress import run_historical_stress_test
from coastmath.engine.scenario_stress import (
    ScenarioInputError,
    ScenarioParams,
    plan_years,
    run_scenario_stress_test,
)
from coastmath.engine.sepp import (
    calculate_sepp,
    custom_amount_qualifies,
    first_distribution_month,
    get_sepp_end_age,
    sepp_rate_ceiling,
    sepp_year_fraction,
    single_life_expectancy,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.social_security import (
    claiming_factor,
    estimate_ss_benefit,
    estimate_ss_benefit_from_pia,
    expected_benefit_fraction,
    full_retirement_age,
)
from coastmath.schemas.birth_year import BirthYear
from coastmath.schemas.simulation import (
    CompareRequest,
    CompareResponse,
    HistoricalStressResult,
    ScenarioStressRequest,
    ScenarioStressResult,
    SimulationResult,
)

router = APIRouter(prefix="/plans", tags=["simulation"])


def _load_and_simulate(
    plan_id: uuid.UUID,
    current_user: User,
    db: Session,
    today: datetime.date | None = None,
) -> SimulationResult:
    """Load a plan and run the simulation engine on it.

    Raises HTTPException 404 if the plan is not found (or not owned by user),
    and 500 if the simulation engine fails.
    """
    plan_data = load_plan_data(plan_id, current_user, db, today=today)

    with engine_errors("Simulation engine encountered an error", "Simulation failed for plan %s", plan_id):
        return run_simulation(plan_data)


@router.post(
    "/{plan_id}/simulate",
    response_model=SimulationResult | HistoricalStressResult,
)
@limiter.limit("60/minute", key_func=session_user)
@engine_budget
def simulate_plan(
    request: Request,
    plan_id: uuid.UUID,
    historical_start_year: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> SimulationResult | HistoricalStressResult:
    record_usage(db, current_user.id, "projection" if historical_start_year is None else "historical_stress_test")
    if historical_start_year is None:
        return _load_and_simulate(plan_id, current_user, db, today=today)

    check_historical_start_year(historical_start_year)

    plan_data = load_plan_data(plan_id, current_user, db, today=today)

    with engine_errors("Historical stress test engine encountered an error",
                       "Historical stress test failed for plan %s (start_year=%d)", plan_id, historical_start_year):
        raw = run_historical_stress_test(plan_data, start_year=historical_start_year)

    return HistoricalStressResult(
        simulation_result=raw["simulation_result"],
        metadata=raw["metadata"],
    )


@router.post(
    "/{plan_id}/scenario-stress",
    response_model=ScenarioStressResult,
    dependencies=[Depends(count_usage("scenario_stress_test"))],
)
@limiter.limit("60/minute", key_func=session_user)
@engine_budget
def scenario_stress_test(
    request: Request,
    plan_id: uuid.UUID,
    body: ScenarioStressRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> ScenarioStressResult:
    """Run a hypothetical preset (job loss, crash, both, new child). Not saved."""
    plan_data = load_plan_data(plan_id, current_user, db, today=today)
    first, last = plan_years(plan_data)
    if not first <= body.start_year <= last:
        raise validation_error(f"start_year must be between {first} and {last}", "start_year")
    params = ScenarioParams(**body.model_dump(exclude={"preset"}))

    with engine_errors("Stress test engine encountered an error",
                       "Scenario stress test failed for plan %s (preset=%s)", plan_id, body.preset,
                       translate={ScenarioInputError: lambda exc: validation_error(str(exc), "preset")}):
        raw = run_scenario_stress_test(plan_data, body.preset, params)

    return ScenarioStressResult(simulation_result=raw["simulation_result"], metadata=raw["metadata"])


@router.post(
    "/{plan_id}/compare",
    response_model=CompareResponse,
    dependencies=[Depends(count_usage("scenario_comparison"))],
)
@limiter.limit("60/minute", key_func=session_user)
@engine_budget
def compare_plans(
    request: Request,
    plan_id: uuid.UUID,
    body: CompareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> CompareResponse:
    current_result = _load_and_simulate(plan_id, current_user, db, today=today)
    baseline_result = _load_and_simulate(body.baseline_plan_id, current_user, db, today=today)

    return CompareResponse(
        current=current_result,
        baseline=baseline_result,
        delta=net_worth_deltas(current_result, baseline_result),
    )


class SSEstimateRequest(BaseModel):
    # Existing callers use current_annual_income.  monthly_pia is a transient
    # alternative; neither estimate input is persisted as a new DB field.
    current_annual_income: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    monthly_pia: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    expected_benefit_percentage: float = Field(default=100, ge=0, le=100, allow_inf_nan=False)
    claiming_age: int = Field(default=67, ge=62, le=70)
    birth_year: BirthYear = 1960

    @model_validator(mode="after")
    def require_one_estimate_input(self):
        if (self.current_annual_income is None) == (self.monthly_pia is None):
            raise ValueError("Provide exactly one of current_annual_income or monthly_pia")
        if self.monthly_pia is None and self.expected_benefit_percentage != 100:
            raise ValueError("expected_benefit_percentage is only available with monthly_pia")
        return self


class SSEstimateResponse(BaseModel):
    estimated_annual_benefit: float
    claiming_age: int
    claiming_factor: float
    full_retirement_age: float
    # Present only for the PIA path so legacy response JSON remains unchanged.
    expected_benefit_percentage: float | None = None
    expected_benefit_fraction: float | None = None


SEPPMethodName = Literal["rmd_method", "fixed_amortization", "fixed_annuitization"]


class SEPPPreviewRequest(BaseModel):
    balance: float = Field(ge=0)
    start_age: int = Field(ge=18, le=59)
    interest_rate: float = Field(default=0.05, ge=0, le=0.15)
    birth_year: BirthYear | None = None
    birth_month: int | None = Field(default=None, ge=1, le=12)
    # A custom yearly amount to test against the approved fixed amortization payment.
    annual_amount: float | None = Field(default=None, gt=0, le=1e9)


class SEPPPreviewYear(BaseModel):
    age: int
    year: int | None = None
    withdrawal: float
    remaining: float


class SEPPPreviewMethod(BaseModel):
    method: SEPPMethodName
    first_year_amount: float
    # Illustrative schedule assuming the balance earns ``interest_rate``;
    # the projection engine uses the plan's actual return assumptions.
    schedule: list[SEPPPreviewYear]


class SEPPPreviewCustom(BaseModel):
    annual_amount: float
    # True only when the amount equals the fixed amortization payment and the
    # rate is within ``rate_ceiling``.
    qualifies: bool
    approved_amount: float
    message: str


class SEPPPreviewResponse(BaseModel):
    single_life_divisor: float
    end_age: float
    payment_years: int
    methods: list[SEPPPreviewMethod]
    notes: list[str]
    custom: SEPPPreviewCustom | None = None
    # Highest allowed interest rate: the greater of 5% and 120% of the federal
    # mid-term rate for either of the two months before the first payment
    # (5% without a birth year or bundled rates for those months).
    rate_ceiling: float = 0.05



@router.post("/sepp-preview", response_model=SEPPPreviewResponse, dependencies=[Depends(count_usage("sepp"))])
@limiter.limit("60/minute", key_func=session_user)
def preview_sepp(
    request: Request,
    req: SEPPPreviewRequest,
    current_user: User = Depends(get_current_user),
) -> SEPPPreviewResponse:
    """Engine-computed SEPP 72(t) amounts for the three IRS methods.

    Uses the same code path as the simulation so the preview cannot drift
    from projected withdrawals. Schedules grow the remaining balance at the
    chosen interest rate purely for illustration.
    """
    end_age = get_sepp_end_age(req.start_age)
    last_age = math.ceil(end_age + ((req.birth_month or 1) - 1) / 12) - 1
    methods: list[SEPPPreviewMethod] = []
    for name in ("rmd_method", "fixed_amortization"):
        remaining = req.balance
        fixed = None
        schedule: list[SEPPPreviewYear] = []
        for age in range(req.start_age, last_age + 1):
            if name == "rmd_method":
                amount = calculate_sepp(remaining, age, name, req.interest_rate)
            else:
                if fixed is None:
                    fixed = calculate_sepp(remaining, age, name, req.interest_rate)
                amount = fixed
            amount = min(amount * sepp_year_fraction(age, req.start_age, req.birth_month), remaining)
            remaining -= amount
            schedule.append(SEPPPreviewYear(
                age=age,
                year=(req.birth_year + age) if req.birth_year is not None else None,
                withdrawal=amount, remaining=remaining,
            ))
            remaining *= 1 + req.interest_rate
            if remaining <= 0:
                break
        methods.append(SEPPPreviewMethod(
            method=name,
            first_year_amount=schedule[0].withdrawal if schedule else 0.0,
            schedule=schedule,
        ))
    ceiling = sepp_rate_ceiling(*(
        first_distribution_month(req.birth_year, req.birth_month, req.start_age)
        if req.birth_year is not None else (None, None)))
    custom = None
    if req.annual_amount is not None:
        approved = calculate_sepp(req.balance, req.start_age, "fixed_amortization", req.interest_rate)
        qualifies = custom_amount_qualifies(
            req.annual_amount, req.balance, req.start_age, "fixed_amortization", req.interest_rate, ceiling)
        if qualifies:
            message = "Matches the fixed amortization payment, so it can qualify as a 72(t) series."
        elif req.interest_rate > ceiling + 1e-12:
            message = (f"The interest rate is above the {ceiling:.2%} allowed for this start month. "
                       "It is projected as an ordinary early withdrawal with the 10% additional tax.")
        else:
            message = ("Does not match an approved method for this balance, age and rate. "
                       "It is projected as an ordinary early withdrawal with the 10% additional tax.")
        custom = SEPPPreviewCustom(
            annual_amount=req.annual_amount, qualifies=qualifies, approved_amount=approved, message=message)
    return SEPPPreviewResponse(
        custom=custom,
        rate_ceiling=ceiling,
        single_life_divisor=single_life_expectancy(req.start_age),
        end_age=end_age,
        payment_years=last_age - req.start_age + 1,
        methods=methods,
        notes=[
            "Monthly planning installments stop at the later of the fifth anniversary and age 59 1/2. First and final calendar years include only months within that interval.",
            "The interest rate may not exceed the greater of 5% or 120% of the federal mid-term rate for either of the two months before the first payment (IRS Notice 2022-6).",
            "RMD method recalculates yearly from the balance and Single Life Table; amortization and annuitization are fixed at the first year's amount.",
            "Fixed annuitization is not offered: the exact IRS mortality table is not bundled and the approximation overstates payments (in the IRS example amortization and annuitization differ by well under 1%).",
            "While the series is active the source account is excluded from other withdrawals; taking extra from it would modify the series and trigger the retroactive penalty.",
        ],
    )


@router.post("/ss-estimate", response_model=SSEstimateResponse, response_model_exclude_none=True)
@limiter.limit("60/minute", key_func=session_user)
def estimate_social_security(
    request: Request,
    req: SSEstimateRequest,
    current_user: User = Depends(get_current_user),
) -> SSEstimateResponse:
    if req.monthly_pia is not None:
        benefit = estimate_ss_benefit_from_pia(
            req.monthly_pia,
            req.claiming_age,
            req.birth_year,
            req.expected_benefit_percentage,
        )
    else:
        # Preserve the legacy replacement-rate estimator and its annual result
        # shape.  No claiming adjustment is applied by the simulator after the
        # caller saves this result as annual_amount.
        benefit = estimate_ss_benefit(req.current_annual_income or 0.0, req.claiming_age, req.birth_year)
    factor = claiming_factor(req.claiming_age, req.birth_year)
    response = SSEstimateResponse(
        estimated_annual_benefit=benefit,
        claiming_age=req.claiming_age,
        claiming_factor=factor,
        full_retirement_age=full_retirement_age(req.birth_year),
    )
    if req.monthly_pia is not None:
        response.expected_benefit_percentage = req.expected_benefit_percentage
        response.expected_benefit_fraction = expected_benefit_fraction(req.expected_benefit_percentage)
    return response

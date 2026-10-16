"""Convert SQLAlchemy ORM objects to engine dataclasses."""

from __future__ import annotations

import datetime

from app.models.account import CurrentAccount
from app.models.assumption_curve import AssumptionCurve
from app.models.cash_flow_priority import CashFlowPriority
from app.models.charity import CharityEntity
from app.models.drawdown_order import DrawdownOrder
from app.models.expense import Expense
from app.models.income import IncomeStream
from app.models.liability import Liability
from app.models.milestone import Milestone
from app.models.plan import Plan
from app.models.real_asset import RealAsset
from app.models.residency_period import ResidencyPeriod
from coastmath.engine import real_estate
from coastmath.engine.amortization import (
    liability_rate_to_decimal,
    resolve_monthly_payment,
)
from coastmath.engine.cash_reserve import cash_reserve_from_settings
from coastmath.engine.debt_relief import forgiveness_from_settings
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    CharityData,
    DrawdownEntryData,
    EstateSettingsData,
    ExpenseData,
    IncomeData,
    LiabilityData,
    MilestoneData,
    PlanData,
    PriorityData,
    RealAssetData,
    ResidencyPeriodData,
    SEPPSettingsData,
    SpendingRulesData,
    SpendingRuleThresholdData,
    SpendingUpsideData,
    employer_match_from_settings,
)
from coastmath.engine.withdrawal_strategy import spec_from_settings

# Map AssumptionCurve.curve_type → AssumptionData field name
_CURVE_TYPE_MAP = {
    "inflation": "inflation_rate",
    "market_return": "stock_growth_rate",
    "bond_return": "bond_return_rate",
    "dividend_yield": "stock_dividend_yield",
    "cash_yield": "cash_yield_rate",
}


def _str_or_none(val: object) -> str | None:
    return str(val) if val is not None else None


def _float_or_none(val: object) -> float | None:
    return float(val) if val is not None else None


def _percent_or_none(val: object) -> float | None:
    """A stored percent (5 means 5%) as a decimal."""
    return float(val) / 100.0 if val is not None else None


def _milestone(m: Milestone) -> MilestoneData:
    """Milestones."""
    return MilestoneData(
        id=str(m.id),
        name=m.name,
        trigger_type=m.trigger_type,
        trigger_value=_float_or_none(m.trigger_value),
        trigger_date=m.trigger_date.isoformat() if m.trigger_date is not None else None,
        metric=m.metric,
        expense_multiple=_float_or_none(m.expense_multiple),
        relative_to_id=_str_or_none(m.relative_to_id),
        offset_years=m.offset_years,
        conditions=m.conditions,
        is_active=m.is_active is not False,
    )


def _income(inc: IncomeStream) -> IncomeData:
    """Income streams."""
    return IncomeData(
        id=str(inc.id),
        name=inc.name,
        annual_amount=float(inc.annual_amount),
        is_active=inc.is_active,
        tax_category=inc.tax_category,
        start_milestone_id=_str_or_none(inc.start_milestone_id),
        end_milestone_id=_str_or_none(inc.end_milestone_id),
        growth_rate=_percent_or_none(inc.growth_rate),
        growth_cap=_float_or_none(inc.growth_cap),
        growth_cap_inflation_linked=inc.growth_cap_inflation_linked,
        withholding_percent=(
            float(inc.withholding_percent) / 100.0 if inc.withholding_percent is not None else 0.0
        ),
        start_month=inc.start_month,
        end_month=inc.end_month,
        is_social_security=inc.is_social_security,
        is_earned_income=inc.is_earned_income,
        is_self_employed=inc.is_self_employed,
        owner=inc.owner or "self",
        claiming_age=inc.claiming_age,
        ss_benefit_basis=inc.ss_benefit_basis or "amount",
        frequency=inc.frequency or "recurring",
        recurrence_years=inc.recurrence_years,
        pension_formula=inc.pension_formula,
        pia_reflects=inc.pia_reflects,
        covered_years_to_date=inc.covered_years_to_date,
        pia_monthly=_float_or_none(inc.pia_monthly),
        expected_benefit_percent=_float_or_none(inc.expected_benefit_percent),
        growth_schedule=inc.growth_schedule or None,
        ex_spouse=inc.ex_spouse or None,
    )


def _expense(exp: Expense) -> ExpenseData:
    """Expenses."""
    return ExpenseData(
        id=str(exp.id),
        name=exp.name,
        annual_amount=float(exp.annual_amount),
        start_milestone_id=_str_or_none(exp.start_milestone_id),
        end_milestone_id=_str_or_none(exp.end_milestone_id),
        inflation_linked=exp.inflation_linked,
        growth_rate=_percent_or_none(exp.growth_rate),
        growth_cap=_float_or_none(exp.growth_cap),
        growth_cap_inflation_linked=exp.growth_cap_inflation_linked,
        recurrence_years=exp.recurrence_years,
        recurrence_growth_rate=(
            float(exp.recurrence_growth_rate) / 100.0 if exp.recurrence_growth_rate is not None else 0.0
        ),
        is_payroll_deduction=exp.is_payroll_deduction,
        payroll_tax_treatment=exp.payroll_tax_treatment or "pre_tax",
        tied_income_id=_str_or_none(exp.tied_income_id),
        specific_funding_source_id=_str_or_none(exp.specific_funding_source_id),
        specific_funding_source_ids=(
            [str(account_id) for account_id in exp.specific_funding_source_ids]
            if exp.specific_funding_source_ids is not None
            else None
        ),
        start_month=exp.start_month,
        end_month=exp.end_month,
        category=exp.category,
        discretionary_fraction=_percent_or_none(exp.discretionary_percent),
        qualified_education=bool(exp.qualified_education),
        payroll_tax_elections=dict(exp.payroll_tax_elections or {}) or None,
    )


def _priority(p: CashFlowPriority) -> PriorityData:
    """Cash flow priorities."""
    return PriorityData(
        priority_rank=p.priority_rank,
        allocation_mode=p.allocation_mode or "remaining",
        allocation_value=_float_or_none(p.allocation_value),
        target_account_id=_str_or_none(p.target_account_id),
        target_liability_id=_str_or_none(p.target_liability_id),
        max_annual_amount=_float_or_none(p.max_annual_amount),
        priority_type=p.priority_type,
        source_account_id=_str_or_none(p.source_account_id),
        source_income_id=_str_or_none(p.source_income_id),
        employee_rate=float(p.employee_rate or 0) / 100.0,
        employer_match_rate=float(p.employer_match_rate or 0) / 100.0,
        conversion_mode=p.conversion_mode or "fixed",
        bracket_ceiling_rate=_float_or_none(p.bracket_ceiling_rate),
        magi_cap=_float_or_none(p.magi_cap),
        backdoor_roth=bool(p.backdoor_roth),
        use_plan_tax_target=bool(p.use_plan_tax_target),
        employer_match=employer_match_from_settings(p.employer_match),
        limit_mode=p.limit_mode or "irs",
        custom_annual_limit=_float_or_none(p.custom_annual_limit),
        start_milestone_id=_str_or_none(p.start_milestone_id),
        end_milestone_id=_str_or_none(p.end_milestone_id),
        withdraw_if_short=bool(p.withdraw_if_short),
        reduce_employer_contribution=bool(p.reduce_employer_contribution),
        transfer_frequency=p.transfer_frequency or "annual",
        target_balance=_float_or_none(p.target_balance),
    )


def _drawdown_entry(d: DrawdownOrder) -> DrawdownEntryData:
    """Drawdown order."""
    return DrawdownEntryData(
        rank=d.rank,
        source_account_id=_str_or_none(d.source_account_id),
    )


def _assumptions(curves: list[AssumptionCurve]) -> AssumptionData:
    """Assumptions: each curve's fixed rate."""
    assumptions = AssumptionData()
    for curve in curves:
        field_name = _CURVE_TYPE_MAP.get(curve.curve_type)
        if field_name and curve.fixed_rate is not None:
            setattr(assumptions, field_name, float(curve.fixed_rate))
    return assumptions


def _assumption_curve(c: AssumptionCurve) -> AssumptionCurveData:
    """Assumption curves, interpolated per year by the engine."""
    return AssumptionCurveData(
        curve_type=c.curve_type,
        mode=c.mode,
        fixed_rate=_float_or_none(c.fixed_rate),
        control_points=c.control_points or [],
    )


def _account(acct: CurrentAccount) -> AccountInfo:
    """Accounts.

    cost_basis passes through as-is; None is resolved to balance at SimState
    init in simulator.run_simulation (mirrors the stateless path).
    """
    return AccountInfo(
        balance=float(acct.balance),
        account_type=acct.account_type,
        name=acct.name,
        cost_basis=_float_or_none(acct.cost_basis),
        inherited_year=acct.inherited_year,
        inheritance_settings=acct.inheritance_settings,
        roth_settings=acct.roth_settings,
        investment_settings=acct.investment_settings,
        withdrawal_lock=acct.withdrawal_lock,
        distribution_settings=acct.distribution_settings,
        include_in_liquid=acct.include_in_liquid,
        state_taxed_basis=_float_or_none(acct.state_taxed_basis),
        owner=acct.owner,
        beneficiary_type=acct.beneficiary_type,
        intl_account_kind=acct.intl_account_kind,
    )


def _real_asset(ra: RealAsset) -> RealAssetData:
    """Real assets."""
    return RealAssetData(
        id=str(ra.id),
        name=ra.name,
        current_value=float(ra.current_value),
        adjusted_basis=_float_or_none(ra.adjusted_basis),
        annual_appreciation_rate=float(ra.annual_appreciation_rate),
        annual_property_tax=float(ra.annual_property_tax),
        annual_maintenance=float(ra.annual_maintenance),
        property_tax_rate=_float_or_none(ra.property_tax_rate),
        maintenance_rate=_float_or_none(ra.maintenance_rate),
        insurance_rate=_float_or_none(ra.insurance_rate),
        sale_year=ra.sale_year,
        sale_month=ra.sale_month,
        is_primary_residence=ra.is_primary_residence,
        tax_treatment=ra.tax_treatment,
        auto_liquidate_on_depletion=ra.auto_liquidate_on_depletion,
        liquidation_target_account_id=_str_or_none(ra.liquidation_target_account_id),
        **real_estate.engine_fields(ra),
    )


def _liability(liab: Liability) -> LiabilityData:
    """Liabilities."""
    # Stored contract: ``interest_rate`` is an annual percentage (5.5 means
    # 5.5%). The engine works in decimals, so convert exactly once here.
    annual_rate = liability_rate_to_decimal(liab.interest_rate)
    interest_method = liab.interest_method or "monthly"
    monthly_pmt = resolve_monthly_payment(
        float(liab.principal_balance), annual_rate, liab.term_months,
        _float_or_none(liab.monthly_payment),
        liab.payment_type, interest_method,
    )
    return LiabilityData(
        id=str(liab.id),
        name=liab.name,
        principal_balance=float(liab.principal_balance),
        interest_rate=annual_rate,
        term_months=liab.term_months,
        monthly_payment=monthly_pmt,
        payment_type=liab.payment_type,
        extra_payment=float(liab.extra_payment),
        offset_account_id=_str_or_none(liab.offset_account_id),
        linked_asset_id=_str_or_none(liab.linked_asset_id),
        payoff_milestone_id=_str_or_none(liab.payoff_milestone_id),
        forgiveness=forgiveness_from_settings(liab.forgiveness),
        interest_method=interest_method,
        recurrence_years=liab.recurrence_years,
        recurrence_end_year=liab.recurrence_end_year,
        recurrence_end_milestone_id=_str_or_none(liab.recurrence_end_milestone_id),
    )


def _sepp_settings(raw: object) -> SEPPSettingsData | None:
    """SEPP settings; None unless enabled."""
    if not (isinstance(raw, dict) and raw.get("enabled")):
        return None
    return SEPPSettingsData(
        enabled=True,
        source_account_id=str(raw["source_account_id"]),
        method=raw.get("method", "fixed_amortization"),
        start_age=float(raw["start_age"]),
        interest_rate=float(raw.get("interest_rate", 0.05)),
        annual_amount=float(raw["annual_amount"]) if raw.get("annual_amount") is not None else None,
    )


def _estate_settings(raw: object) -> EstateSettingsData | None:
    """Estate settings; None when the stored mapping is empty."""
    if not (isinstance(raw, dict) and raw):
        return None
    return EstateSettingsData(
        household_lifecycle=raw.get("household_lifecycle", "legacy_primary_endpoint"),
        survivor_social_security_policy=raw.get("survivor_social_security_policy", "off"),
        survivor_social_security_eligibility_confirmed=raw.get("survivor_social_security_eligibility_confirmed", False),
        survivor_social_security_eligibility_source=raw.get("survivor_social_security_eligibility_source"),
        step_up_basis_on_death=raw.get("step_up_basis_on_death", True),
        filing_status_after_death=raw.get("filing_status_after_death", "single"),
        federal_estate_exemption=float(raw.get("federal_estate_exemption", 13_990_000.0)),
        state_estate_tax_enabled=raw.get("state_estate_tax_enabled", False),
        state_estate_exemption=float(raw.get("state_estate_exemption", 0.0)),
        state_estate_tax_rate=float(raw.get("state_estate_tax_rate", 0.0)),
        custom_federal_exemption_enabled=bool(raw.get("custom_federal_exemption_enabled", False)),
        portability_election=bool(raw.get("portability_election", True)),
        settlement_cost_fixed=float(raw.get("settlement_cost_fixed", 0.0) or 0.0),
        settlement_cost_rate=float(raw.get("settlement_cost_rate", 0.0) or 0.0),
        heir_income_tax_rate=float(raw.get("heir_income_tax_rate", 0.0) or 0.0),
        heir_capital_gains_rate=float(raw.get("heir_capital_gains_rate", 0.0) or 0.0),
        # Stored as percents (0-100).
        estate_selling_cost_rate=float(raw.get("estate_selling_cost_percent", 0.0) or 0.0) / 100.0,
        charitable_bequest_rate=float(raw.get("charitable_bequest_percent", 0.0) or 0.0) / 100.0,
        joint_account_step_up=bool(raw.get("joint_account_step_up", False)),
    )


def _charity(ce: CharityEntity) -> CharityData:
    """Charity entities."""
    return CharityData(
        id=str(ce.id),
        name=ce.name,
        entity_type=ce.entity_type,
        annual_amount=float(ce.annual_amount),
        start_milestone_id=_str_or_none(ce.start_milestone_id),
        end_milestone_id=_str_or_none(ce.end_milestone_id),
        source_account_id=_str_or_none(ce.source_account_id),
        funding=ce.funding or "cash",
    )


def _spending_rules(raw: object) -> SpendingRulesData | None:
    """Spending rules; None when the stored mapping is empty."""
    if not (isinstance(raw, dict) and raw):
        return None
    return SpendingRulesData(
        flex_threshold=float(raw["flex_threshold"]) if raw.get("flex_threshold") is not None else None,
        flex_reduction=float(raw.get("flex_reduction", 0.20)),
        lookback_years=int(raw.get("lookback_years", 1)),
        spending_floor=float(raw.get("spending_floor", 0.8)),
        performance_mode=raw.get("performance_mode", "trailing_return"),
        interpolation=raw.get("interpolation", "step"),
        thresholds=[
            SpendingRuleThresholdData(
                threshold=float(item["threshold"]),
                reduction=float(item["reduction"]),
            )
            for item in (raw.get("thresholds") or [])
            if isinstance(item, dict)
            and item.get("threshold") is not None
            and item.get("reduction") is not None
        ],
        start_milestone_id=raw.get("start_milestone_id"),
        end_milestone_id=raw.get("end_milestone_id"),
        upside_thresholds=[
            SpendingUpsideData(
                threshold=float(item["threshold"]),
                increase=float(item["increase"]),
            )
            for item in (raw.get("upside_thresholds") or [])
            if isinstance(item, dict)
            and item.get("threshold") is not None
            and item.get("increase") is not None
        ],
        flex_scope=list(raw.get("flex_scope") or ["expenses"]),
        surplus_mode=raw.get("surplus_mode") or "save",
    )


def _residency_period(rp: ResidencyPeriod) -> ResidencyPeriodData:
    """Residency periods."""
    return ResidencyPeriodData(
        state_code=rp.state_code,
        start_milestone_id=_str_or_none(rp.start_milestone_id),
        end_milestone_id=_str_or_none(rp.end_milestone_id),
        start_year=rp.start_year,
        end_year=rp.end_year,
        rank=rp.rank,
        local_tax=rp.local_tax or None,
        country=rp.country,
        region=rp.region,
    )


def _start_year(plan: Plan, today: datetime.date | None) -> tuple[int, float]:
    """Start year, and the share of it the projection covers."""
    if plan.plan_type == "FIXED_DATE" and plan.start_date is not None:
        simulation_start_date = plan.start_date
    else:
        simulation_start_date = today or datetime.date.today()
    start_year = simulation_start_date.year
    next_year = datetime.date(start_year + 1, 1, 1)
    year_start = datetime.date(start_year, 1, 1)
    first_year_fraction = (
        (next_year - simulation_start_date).days
        / (next_year - year_start).days
    )
    return start_year, first_year_fraction


def plan_to_engine_data(
    plan: Plan,
    accounts: list[CurrentAccount],
    today: datetime.date | None = None,
) -> PlanData:
    """Convert a SQLAlchemy Plan (with loaded relationships) to engine PlanData.

    ``today`` is the user's local calendar date for "Now" plans (see
    ``app.routers.helpers.client_today``); it defaults to the server date.
    """
    start_year, first_year_fraction = _start_year(plan, today)
    spouse = plan.spouse
    return PlanData(
        plan_id=str(plan.id),
        birth_year=plan.birth_year,
        birth_month=plan.birth_month,
        filing_status=plan.filing_status,
        filing_status_changes=plan.filing_status_changes or [],
        life_expectancy=plan.life_expectancy,
        start_year=start_year,
        first_year_fraction=first_year_fraction,
        milestones=[_milestone(m) for m in plan.milestones],
        income_streams=[_income(inc) for inc in plan.income_streams],
        expenses=[_expense(exp) for exp in plan.expenses],
        priorities=[_priority(p) for p in plan.priorities],
        drawdown_order=[_drawdown_entry(d) for d in plan.drawdown_order],
        assumptions=_assumptions(plan.assumption_curves),
        assumption_curves=[_assumption_curve(c) for c in plan.assumption_curves],
        accounts={str(acct.id): _account(acct) for acct in accounts},
        real_assets=[_real_asset(ra) for ra in plan.real_assets],
        liabilities=[_liability(liab) for liab in plan.liabilities],
        spouse_birth_year=spouse.birth_year if spouse is not None else None,
        spouse_birth_month=spouse.birth_month if spouse is not None else None,
        spouse_life_expectancy=spouse.life_expectancy if spouse is not None else None,
        sepp_settings=_sepp_settings(plan.sepp_settings),
        cash_reserve=cash_reserve_from_settings(plan.cash_reserve_settings),
        estate_settings=_estate_settings(plan.estate_settings),
        charity_entities=[_charity(ce) for ce in plan.charity_entities],
        spending_rules=_spending_rules(plan.spending_rules),
        tax_settings=plan.tax_settings or None,
        healthcare_settings=plan.healthcare_settings or None,
        state_code=plan.state_code,
        local_tax=plan.local_tax or None,
        residency_periods=[_residency_period(rp) for rp in plan.residency_periods],
        withdrawal_strategy=spec_from_settings(plan.withdrawal_strategy),
        tax_country=plan.tax_country or "US",
        tax_region=plan.tax_region,
        currency=plan.currency or "USD",
        intl_settings=plan.intl_settings or None,
    )

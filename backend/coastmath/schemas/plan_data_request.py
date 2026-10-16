"""Pydantic v2 request schema mirroring the engine's PlanData dataclass.

Stateless simulation requests send the full plan in the body and never
touch the database.
"""

from __future__ import annotations

import math
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from coastmath.engine import real_estate
from coastmath.engine.account_types import RETIREMENT_ACCOUNT_TYPES, ROTH_TYPES
from coastmath.engine.amortization import (
    liability_rate_to_decimal,
    resolve_monthly_payment,
)
from coastmath.engine.cash_reserve import cash_reserve_from_settings
from coastmath.engine.debt_relief import forgiveness_from_settings
from coastmath.engine.household_lifecycle import simulation_end_year
from coastmath.engine.intl_regime import validate_regime_settings
from coastmath.engine.milestones import resolve_deterministic_milestones
from coastmath.engine.person_healthcare import validate_person_healthcare_plan
from coastmath.engine.plan_validation import (
    validate_account_history,
    validate_roth_conversion_rules,
    validate_transfer_rules,
)
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    CashReserveData,
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
from coastmath.engine.withdrawal_strategy import (
    WithdrawalStrategySpec,
    spec_from_settings,
)
from coastmath.schemas.account import (
    AccountCreate,
    AccountDistributionSettings,
    AccountInvestmentSettings,
    WithdrawalLock,
    coerce_intl_account_type,
)
from coastmath.schemas.asset_location import AssetLocation
from coastmath.schemas.assumption_curve import validate_control_points, validate_rate
from coastmath.schemas.birth_year import BirthYear
from coastmath.schemas.cash_flow_priority import (
    AllocationFields,
    ContributionFormulaFields,
    FundingModeFields,
)
from coastmath.schemas.coverage_settings import CoverageSettings
from coastmath.schemas.estimated_payments import EstimatedPayments
from coastmath.schemas.expense import (
    PayrollTaxElections,
    category_for_discretionary_percent,
)
from coastmath.schemas.filing_status_change import FilingStatusChange
from coastmath.schemas.healthcare_settings import HealthcareSettings
from coastmath.schemas.income import (
    ExSpouseRecord,
    GrowthSchedule,
    IncomeTaxCategory,
    PensionFormula,
    SsBenefitBasis,
    validate_growth_schedule,
    validate_income_extensions,
    validate_ss_benefit_basis,
)
from coastmath.schemas.inheritance_settings import InheritanceSettings
from coastmath.schemas.intl_settings import (
    IntlSettings,
    check_account_kind,
    check_plan_regimes,
    normalize_currency,
    normalize_region,
    normalize_supported_country,
    plan_countries,
)
from coastmath.schemas.liability import InterestMethod
from coastmath.schemas.local_tax import LocalTaxSelection, check_local_tax_state
from coastmath.schemas.milestone import (
    MilestoneConditions,
    MilestoneTriggerType,
    condition_references,
)
from coastmath.schemas.real_asset import (
    AssetTaxTreatment,
    RealEstateSettings,
    real_estate_errors,
)
from coastmath.schemas.residency_period import ResidencyPeriodRequest
from coastmath.schemas.roth_settings import RothSettings
from coastmath.schemas.spending_flex import (
    MAX_UPSIDE_POINTS,
    FlexScope,
    SpendingUpsidePoint,
    SurplusMode,
    check_spending_flex,
    default_scope,
)
from coastmath.schemas.state_brackets import StateBrackets
from coastmath.schemas.tax_adjustments import (
    TaxCustomizationFields,
    all_adjustments,
    referenced_milestone_ids,
)
from coastmath.schemas.tax_target import TaxTarget
from coastmath.schemas.withdrawal_strategy import WithdrawalStrategySettings
from coastmath.schemas.year_to_date import YearToDateTax

FilingStatus = Literal[
    "single",
    "married_filing_jointly",
    "married_filing_separately",
    "head_of_household",
]


# ---------------------------------------------------------------------------
# Nested request models (mirror engine dataclasses from types.py)
# ---------------------------------------------------------------------------


class AccountInfoRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    balance: float
    account_type: str
    name: str = ""
    cost_basis: float | None = None
    inherited_year: int | None = None
    owner: str = "self"
    beneficiary_type: str = "non_edb"
    inheritance_settings: InheritanceSettings | None = None
    roth_settings: RothSettings | None = None
    investment_settings: AccountInvestmentSettings | None = None
    withdrawal_lock: WithdrawalLock | None = None
    distribution_settings: AccountDistributionSettings | None = None
    state_taxed_basis: float | None = Field(default=None, ge=0, lt=1e13)
    # Country account kind; omitted while unset so request dumps are unchanged.
    intl_account_kind: str | None = Field(default=None, max_length=40, exclude_if=lambda value: value is None)
    # Liquid net worth override (null: liquid unless withdrawal-locked).
    include_in_liquid: bool | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="before")
    @classmethod
    def _intl_account_type(cls, data: Any) -> Any:
        return coerce_intl_account_type(data)

    @model_validator(mode='after')
    def validate_inheritance(self):
        if self.account_type not in RETIREMENT_ACCOUNT_TYPES:
            self.inherited_year = None
            self.inheritance_settings = None
        if self.account_type not in ROTH_TYPES:
            self.roth_settings = None
        if self.inheritance_settings is not None or self.roth_settings is not None:
            body = self.model_dump()
            if self.roth_settings is not None:
                body['roth_settings'] = self.roth_settings.model_dump(exclude_unset=True)
            validated = AccountCreate.model_validate(body)
            self.inheritance_settings = validated.inheritance_settings
            self.roth_settings = validated.roth_settings
        return self


class MilestoneRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    trigger_type: MilestoneTriggerType
    conditions: MilestoneConditions | None = Field(default=None, exclude_if=lambda value: value is None)
    trigger_value: float | None = None
    trigger_date: str | None = None
    metric: str | None = None
    expense_multiple: float | None = Field(default=None, gt=0)
    relative_to_id: str | None = None
    offset_years: int = 0
    # A switched-off milestone never fires; omitted from dumps while on.
    is_active: bool = Field(default=True, exclude_if=lambda value: value)


class IncomeRequest(BaseModel):
    frequency: Literal["recurring", "once"] = Field(default="recurring", exclude_if=lambda v: v == "recurring")
    recurrence_years: int | None = Field(default=None, ge=1, le=100, exclude_if=lambda v: v is None)
    pension_formula: PensionFormula | None = Field(default=None, exclude_if=lambda v: v is None)
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    annual_amount: float
    is_active: bool = True
    tax_category: IncomeTaxCategory | None = None
    start_milestone_id: str | None = None
    end_milestone_id: str | None = None
    growth_rate: float | None = None  # percent; None follows the plan income curve
    growth_cap: float | None = Field(default=None, ge=0)
    growth_cap_inflation_linked: bool = False
    withholding_percent: float | None = 0.0  # percent; legacy null means no withholding
    start_month: int | None = Field(default=None, ge=1, le=12)
    end_month: int | None = Field(default=None, ge=1, le=12)
    is_social_security: bool = False
    is_earned_income: bool = True
    is_self_employed: bool = False
    owner: Literal["self", "spouse"] = "self"
    claiming_age: int | None = Field(default=None, ge=62, le=70)
    pia_reflects: Literal["current_record", "continued_work"] = Field(default="continued_work", exclude_if=lambda v: v == "continued_work")
    covered_years_to_date: int = Field(default=35, ge=1, le=35, exclude_if=lambda v: v == 35)
    ss_benefit_basis: SsBenefitBasis | None = None
    pia_monthly: float | None = Field(default=None, ge=0)
    expected_benefit_percent: float | None = Field(default=None, ge=0, le=100)
    growth_schedule: GrowthSchedule | None = Field(default=None, exclude_if=lambda v: v is None)
    ex_spouse: ExSpouseRecord | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def check_ss_benefit_basis(self):
        validate_ss_benefit_basis(self.ss_benefit_basis, self.pia_monthly, self.claiming_age, self.tax_category)
        validate_growth_schedule(self.growth_schedule)
        validate_income_extensions(
            growth_schedule=self.growth_schedule, ex_spouse=self.ex_spouse,
            ss_benefit_basis=self.ss_benefit_basis, tax_category=self.tax_category,
            is_social_security=self.is_social_security, pension_formula=self.pension_formula,
        )
        return self


class ExpenseRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    annual_amount: float
    start_milestone_id: str | None = None
    end_milestone_id: str | None = None
    inflation_linked: bool = True
    growth_rate: float | None = None
    growth_cap: float | None = Field(default=None, ge=0)
    growth_cap_inflation_linked: bool = False
    recurrence_years: int | None = Field(default=None, gt=0)
    recurrence_growth_rate: float = 0.0
    is_payroll_deduction: bool = False
    payroll_tax_treatment: Literal["pre_tax", "after_tax"] = "pre_tax"
    # Explicit wage-base elections; omitted keeps the treatment's defaults.
    payroll_tax_elections: PayrollTaxElections | None = Field(default=None, exclude_if=lambda value: value is None)
    tied_income_id: str | None = None
    specific_funding_source_id: str | None = None
    specific_funding_source_ids: list[str] | None = Field(default=None, max_length=100)
    start_month: int | None = Field(default=None, ge=1, le=12)
    end_month: int | None = Field(default=None, ge=1, le=12)
    category: str | None = None
    # Percent (0-100) flexible spending may cut; wins over category, which is
    # rewritten to match as on saved expenses (schemas/expense.py).
    discretionary_percent: float | None = Field(default=None, ge=0, le=100)
    # Qualified higher education expense (529 withdrawals up to it are tax free).
    qualified_education: bool = Field(default=False, exclude_if=lambda value: not value)

    @model_validator(mode="after")
    def sync_category(self):
        if self.discretionary_percent is not None:
            self.category = category_for_discretionary_percent(self.discretionary_percent)
        return self

    @model_validator(mode="after")
    def validate_funding_order(self):
        if self.specific_funding_source_ids is None:
            return self
        if len(self.specific_funding_source_ids) != len(set(self.specific_funding_source_ids)):
            raise ValueError("specific_funding_source_ids must contain unique account IDs")
        if (
            self.specific_funding_source_id is not None
            and self.specific_funding_source_ids
            and self.specific_funding_source_ids[0] != self.specific_funding_source_id
        ):
            raise ValueError("specific_funding_source_id must match the first selected account")
        return self


class AssumptionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    inflation_rate: float = 0.03
    stock_growth_rate: float = 0.07
    bond_return_rate: float = 0.04
    stock_dividend_yield: float = 0.0
    cash_yield_rate: float = 0.0

    @field_validator("inflation_rate", "stock_growth_rate", "bond_return_rate",
                     "stock_dividend_yield", "cash_yield_rate")
    @classmethod
    def validate_rates(cls, v: float, info) -> float:
        return validate_rate(v, info.field_name)


class AssumptionCurveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    curve_type: str
    mode: Literal["fixed", "curve"] = "fixed"
    fixed_rate: float | None = None
    control_points: list[dict[str, Any]] = []

    @field_validator("fixed_rate")
    @classmethod
    def validate_fixed_rate(cls, v: float | None) -> float | None:
        return None if v is None else validate_rate(v)

    @field_validator("control_points")
    @classmethod
    def validate_points(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return validate_control_points(v)


class PriorityRequest(ContributionFormulaFields, AllocationFields, FundingModeFields):
    model_config = ConfigDict(extra="ignore")

    priority_rank: int
    target_account_id: str | None = None
    target_liability_id: str | None = Field(default=None, exclude_if=lambda value: value is None)
    max_annual_amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    priority_type: str | None = None
    source_account_id: str | None = None
    source_income_id: str | None = None
    employee_rate: float = 0.0
    employer_match_rate: float = 0.0
    target_balance: float | None = Field(default=None, ge=0)
    backdoor_roth: bool = False
    conversion_mode: Literal["fixed", "fill_bracket"] = "fixed"
    bracket_ceiling_rate: float | None = Field(default=None, ge=0, le=1)
    magi_cap: float | None = Field(default=None, ge=0)
    use_plan_tax_target: bool = False
    start_milestone_id: str | None = None
    end_milestone_id: str | None = None
    withdraw_if_short: bool = Field(default=False, exclude_if=lambda value: not value)
    reduce_employer_contribution: bool = Field(default=False, exclude_if=lambda value: not value)
    transfer_frequency: Literal["annual", "monthly"] = Field(
        default="annual", exclude_if=lambda value: value == "annual")


class DrawdownEntryRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rank: int
    source_account_id: str | None = None


class RealAssetRequest(RealEstateSettings):
    model_config = ConfigDict(extra="ignore")

    tax_treatment: AssetTaxTreatment = "unspecified"
    id: str
    name: str
    current_value: float
    adjusted_basis: float | None = Field(default=None, ge=0)
    annual_appreciation_rate: float = 0.03
    annual_property_tax: float = 0.0
    annual_maintenance: float = 0.0
    property_tax_rate: float | None = Field(default=None, ge=0, le=1)
    maintenance_rate: float | None = Field(default=None, ge=0, le=1)
    insurance_rate: float | None = Field(default=None, ge=0, le=1)
    sale_year: int | None = None
    sale_month: int = Field(default=1, ge=1, le=12)
    is_primary_residence: bool = False
    auto_liquidate_on_depletion: bool = False
    liquidation_target_account_id: str | None = None
    purchase_funding_account_id: str | None = None
    qbi_eligible: bool = False
    rental_active_participation: bool = True

    @model_validator(mode="after")
    def check_real_estate(self) -> RealAssetRequest:
        errors = real_estate_errors(self.__dict__)
        if errors:
            raise ValueError("; ".join(errors))
        return self


class DebtForgivenessRequest(BaseModel):
    """One-time loan cancellation; mirrors ``LiabilityForgiveness`` with text ids."""

    model_config = ConfigDict(extra="ignore")

    year: int | None = Field(default=None, ge=1900, le=2200)
    milestone_id: str | None = None
    amount: float | None = Field(default=None, gt=0)
    tax_treatment: Literal["taxable", "declared_exclusion"] = "taxable"
    excluded_amount: float | None = Field(default=None, ge=0)
    exclusion_basis: str | None = None

    @model_validator(mode="after")
    def check_forgiveness(self) -> DebtForgivenessRequest:
        if (self.year is None) == (self.milestone_id is None):
            raise ValueError("Choose either a year or a milestone for the forgiveness")
        if self.tax_treatment == "taxable":
            if self.excluded_amount is not None or self.exclusion_basis is not None:
                raise ValueError("An excluded amount and basis require the declared exclusion treatment")
        elif self.exclusion_basis is None:
            raise ValueError("A declared exclusion needs its IRC 108 basis")
        return self


class LiabilityRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    principal_balance: float
    #: Annual rate in percent (5.5 means 5.5%), matching the stored liability contract.
    interest_rate: float = Field(ge=0, le=100)
    term_months: int | None = None
    # Keep stateless liability inputs aligned with persisted liabilities:
    # zero is not a valid payment, while omission retains the engine's
    # percent-of-balance default.
    monthly_payment: float | None = Field(default=None, gt=0)
    payment_type: str = "fixed"
    extra_payment: float = 0.0
    offset_account_id: str | None = None
    linked_asset_id: str | None = None
    payoff_milestone_id: str | None = None
    forgiveness: DebtForgivenessRequest | None = Field(default=None, exclude_if=lambda value: value is None)
    interest_method: InterestMethod = Field(default="monthly", exclude_if=lambda value: value == "monthly")
    recurrence_years: int | None = Field(default=None, ge=1, le=100, exclude_if=lambda value: value is None)
    recurrence_end_year: int | None = Field(default=None, ge=1900, le=2200, exclude_if=lambda value: value is None)
    recurrence_end_milestone_id: str | None = Field(default=None, exclude_if=lambda value: value is None)


class SEPPSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    source_account_id: str | None = None
    method: str = "fixed_amortization"
    start_age: float = 50.0
    interest_rate: float = 0.05
    annual_amount: float | None = Field(default=None, gt=0, exclude_if=lambda value: value is None)


class CashReserveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    account_ids: list[str] = Field(default_factory=list)
    reserve_amount: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    sweep_excess: bool = Field(default=False, exclude_if=lambda value: not value)


class CharityRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    entity_type: str
    annual_amount: float
    start_milestone_id: str | None = None
    end_milestone_id: str | None = None
    source_account_id: str | None = None
    # "appreciated_shares" gives shares from the taxable source account.
    funding: Literal["cash", "appreciated_shares"] = Field(default="cash", exclude_if=lambda value: value == "cash")


class EstateSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    step_up_basis_on_death: bool = True
    filing_status_after_death: str = "single"
    federal_estate_exemption: float = 13_990_000.0
    state_estate_tax_enabled: bool = False
    state_estate_exemption: float = 0.0
    state_estate_tax_rate: float = 0.0
    custom_federal_exemption_enabled: bool = False
    portability_election: bool = True
    settlement_cost_fixed: float = 0.0
    settlement_cost_rate: float = 0.0
    heir_income_tax_rate: float = 0.0
    household_lifecycle: Literal['legacy_primary_endpoint', 'last_survivor_calendar_year_end'] = 'legacy_primary_endpoint'
    survivor_social_security_policy: Literal['off', 'claimed_benefit_at_survivor_fra'] = 'off'
    survivor_social_security_eligibility_confirmed: bool = False
    survivor_social_security_eligibility_source: str | None = Field(default=None, min_length=1, max_length=2000)
    # Net legacy detail: heirs' capital gains rate (decimal) when step-up is
    # off, selling costs on real assets and charitable bequest (percents).
    heir_capital_gains_rate: float = Field(default=0.0, ge=0, le=1, exclude_if=lambda value: not value)
    estate_selling_cost_percent: float = Field(default=0.0, ge=0, le=100, exclude_if=lambda value: not value)
    charitable_bequest_percent: float = Field(default=0.0, ge=0, le=100, exclude_if=lambda value: not value)
    joint_account_step_up: bool = Field(default=False, exclude_if=lambda value: not value)


class SpendingRuleThresholdRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    threshold: float
    reduction: float = Field(ge=0.0, le=1.0)


class SpendingRulesRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    flex_threshold: float | None = None
    flex_reduction: float = Field(default=0.20, ge=0.0, le=1.0)
    lookback_years: int = Field(default=1, ge=1, le=5)
    spending_floor: float = Field(default=0.8, ge=0.0, le=1.0)
    performance_mode: Literal["trailing_return", "all_time_high"] = "trailing_return"
    interpolation: Literal["step", "linear"] = "step"
    thresholds: list[SpendingRuleThresholdRequest] = Field(default_factory=list, max_length=10)
    start_milestone_id: str | None = None
    end_milestone_id: str | None = None
    upside_thresholds: list[SpendingUpsidePoint] = Field(
        default_factory=list, max_length=MAX_UPSIDE_POINTS, exclude_if=lambda value: not value,
    )
    flex_scope: list[FlexScope] = Field(
        default_factory=lambda: ["expenses"], max_length=3, exclude_if=default_scope,
    )
    surplus_mode: SurplusMode = Field(default="save", exclude_if=lambda value: value == "save")

    @model_validator(mode="after")
    def _check_flex_additions(self):
        check_spending_flex(
            upside_thresholds=self.upside_thresholds, flex_scope=self.flex_scope,
            surplus_mode=self.surplus_mode, performance_mode=self.performance_mode,
        )
        return self


class TaxSettingsRequest(CoverageSettings, TaxCustomizationFields):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["detailed", "flat"] = "detailed"
    ordinary_income_tax_rate: float | None = Field(default=None, ge=0, le=1)
    capital_gains_tax_rate: float | None = Field(default=None, ge=0, le=1)
    taxable_withholding_rate: float = Field(default=0, ge=0, lt=1)
    tax_deferred_withholding_rate: float = Field(default=0, ge=0, lt=1)
    settlement_lag_years: int = Field(default=0, ge=0, le=5)
    cash_flow_frequency: Literal["annual", "monthly"] = "monthly"
    withdrawal_cash_flow_frequency: Literal["annual", "monthly"] | None = None
    state_brackets: StateBrackets | None = None
    year_to_date: YearToDateTax | None = None
    capital_loss_carryforward: float = Field(default=0, ge=0)
    mfs_lived_apart_all_year: bool = False
    estimated_payments: EstimatedPayments | None = None
    tax_target: TaxTarget | None = None
    blend_drawdown_to_tax_target: bool = Field(default=False, exclude_if=lambda value: not value)
    asset_location: AssetLocation | None = Field(default=None, exclude_if=lambda value: value is None)
    # Itemized medical expenses above 7.5% of AGI and the self-employed
    # health insurance deduction; state deduction for 529 contributions.
    medical_expense_deductions: bool = Field(default=False, exclude_if=lambda value: not value)
    state_529_deduction: bool = Field(default=False, exclude_if=lambda value: not value)


# ---------------------------------------------------------------------------
# Top-level request model
# ---------------------------------------------------------------------------


class PlanDataRequest(BaseModel):
    filing_status_changes: list[FilingStatusChange] | None = Field(default=None, max_length=100, exclude_if=lambda v: v is None)
    model_config = ConfigDict(extra="ignore")

    plan_id: uuid.UUID
    birth_year: BirthYear
    birth_month: int | None = Field(default=None, ge=1, le=12)
    filing_status: FilingStatus = "single"
    life_expectancy: int = Field(default=95, ge=50, le=120)
    start_year: int
    first_year_fraction: float = Field(default=1.0, ge=0, le=1)
    milestones: list[MilestoneRequest] = []
    income_streams: list[IncomeRequest] = []
    expenses: list[ExpenseRequest] = []
    priorities: list[PriorityRequest] = []
    drawdown_order: list[DrawdownEntryRequest] = []
    assumptions: AssumptionRequest = Field(default_factory=AssumptionRequest)
    assumption_curves: list[AssumptionCurveRequest] = []
    accounts: dict[str, AccountInfoRequest] = {}
    real_assets: list[RealAssetRequest] = []
    liabilities: list[LiabilityRequest] = []
    spouse_birth_year: BirthYear | None = None
    spouse_birth_month: int | None = Field(default=None, ge=1, le=12)
    spouse_life_expectancy: int | None = None
    sepp_settings: SEPPSettingsRequest | None = None
    cash_reserve_settings: CashReserveRequest | None = Field(default=None, exclude_if=lambda value: value is None)
    state_code: str | None = None
    # Local income tax for state_code; residency periods carry their own.
    local_tax: LocalTaxSelection | None = None
    residency_periods: list[ResidencyPeriodRequest] = []
    charity_entities: list[CharityRequest] = []
    estate_settings: EstateSettingsRequest | None = None
    healthcare_settings: HealthcareSettings | None = None
    spending_rules: SpendingRulesRequest | None = None
    tax_settings: TaxSettingsRequest | None = None
    withdrawal_strategy: WithdrawalStrategySettings | None = Field(default=None, exclude_if=lambda value: value is None)
    # Country tax regime; omitted at the US defaults so request dumps are unchanged.
    tax_country: str = Field(default="US", min_length=2, max_length=2, exclude_if=lambda value: value == "US")
    tax_region: str | None = Field(default=None, max_length=8, exclude_if=lambda value: value is None)
    currency: str = Field(default="USD", min_length=3, max_length=3, exclude_if=lambda value: value == "USD")
    intl_settings: IntlSettings | None = Field(default=None, exclude_if=lambda value: value is None)

    _normalize_country = field_validator("tax_country")(classmethod(lambda cls, v: normalize_supported_country(v)))
    _normalize_region = field_validator("tax_region")(classmethod(lambda cls, v: normalize_region(v)))
    _normalize_currency = field_validator("currency")(classmethod(lambda cls, v: normalize_currency(v)))

    @model_validator(mode="after")
    def _local_tax_in_state(self):
        check_local_tax_state(self.local_tax, self.state_code)
        return self

    @model_validator(mode="after")
    def _check_regimes(self):
        check_plan_regimes(self.tax_country, self.tax_region, self.intl_settings, self.residency_periods)
        countries = plan_countries(self.tax_country, self.residency_periods)
        for account in self.accounts.values():
            check_account_kind(account.intl_account_kind, countries)
        milestones = {m.id for m in self.milestones}
        if self.intl_settings is not None and self.intl_settings.milestone_ids() - milestones:
            raise ValueError("A benefit's start milestone must belong to this plan")
        validate_regime_settings(self)
        return self

    @model_validator(mode="after")
    def check_dates(self):
        if self.start_year < self.birth_year:
            raise ValueError("Start year must be on or after birth year.")
        if self.start_year >= simulation_end_year(self):
            raise ValueError("Life expectancy must extend beyond the projection start age.")
        validate_transfer_rules(self.priorities, self.accounts)
        validate_roth_conversion_rules(self.priorities, self.accounts)
        validate_account_history(self.accounts, self.start_year)
        for expense in self.expenses:
            selected = (
                expense.specific_funding_source_ids
                if expense.specific_funding_source_ids is not None
                else (
                    [expense.specific_funding_source_id]
                    if expense.specific_funding_source_id is not None
                    else []
                )
            )
            missing = [account_id for account_id in selected if account_id not in self.accounts]
            if missing:
                raise ValueError(
                    "specific_funding_source_ids must reference existing accounts: "
                    + ", ".join(missing)
                )
        validate_person_healthcare_plan(self)
        resolve_deterministic_milestones(
            [MilestoneData(**m.model_dump()) for m in self.milestones], self.birth_year, self.birth_month,
        )
        milestones = {m.id: m for m in self.milestones}
        for milestone in self.milestones:
            if milestone.trigger_type == "conditions" and milestone.conditions is None:
                raise ValueError("Conditions are required for conditions milestones")
            refs, account_refs = condition_references(milestone.conditions.model_dump() if milestone.conditions else None)
            if refs - milestones.keys() or account_refs - self.accounts.keys():
                raise ValueError("Condition references must belong to this plan")


        def year(mid, seen=None):
            seen = set() if seen is None else seen
            if mid not in milestones or mid in seen or not milestones[mid].is_active:
                return None
            seen.add(mid)
            ms = milestones[mid]
            if ms.trigger_type == "date" and ms.trigger_date:
                return int(ms.trigger_date[:4])
            if ms.trigger_type == "age" and ms.trigger_value is not None:
                return self.birth_year + ((self.birth_month or 1) - 1 + math.ceil(ms.trigger_value * 12 - 1e-9)) // 12
            if ms.trigger_type == "relative":
                base = year(ms.relative_to_id, seen)
                return None if base is None else base + (ms.offset_years or 0)
            return None

        for change in self.filing_status_changes or []:
            if change.milestone_id and change.milestone_id not in milestones:
                raise ValueError("Filing status milestone not found in plan")
        if self.tax_settings is not None:
            customization = self.tax_settings.model_dump()
            if referenced_milestone_ids(customization) - set(milestones):
                raise ValueError("Tax adjustment or scheduled tax change milestone not found in plan")
            if self.spouse_birth_year is None and any(
                    row.get("owner") == "spouse" for row in all_adjustments(customization)):
                raise ValueError("A partner tax adjustment needs a partner in the plan")
        if self.spouse_birth_year is None and any(inc.owner == "spouse" and inc.is_social_security for inc in self.income_streams):
            raise ValueError("A partner's Social Security needs the partner's birth year")
        by_income_id = {inc.id: inc for inc in self.income_streams}
        for inc in self.income_streams:
            formula = inc.pension_formula
            if not formula:
                continue
            if inc.tax_category != "qualified_pension":
                raise ValueError("Pension formulas require qualified pension income")
            if formula.kind != "flat":
                salary = by_income_id.get(formula.linked_income_id)
                if salary is None or salary.owner != inc.owner or salary.id == inc.id:
                    raise ValueError("Pension salary must exist in this plan and belong to the same owner")
                if salary.frequency == "once" or salary.tax_category not in {None, "employment", "self_employment"} or (salary.tax_category is None and not salary.is_earned_income) or salary.pension_formula:
                    raise ValueError("Pension salary must be a recurring earned income stream")
        strategy_start = self.withdrawal_strategy.start_milestone_id if self.withdrawal_strategy else None
        if strategy_start is not None and strategy_start not in milestones:
            raise ValueError("Withdrawal strategy start milestone not found in plan.")
        if self.spending_rules is not None:
            start, end = self.spending_rules.start_milestone_id, self.spending_rules.end_milestone_id
            if any(mid is not None and mid not in milestones for mid in (start, end)):
                raise ValueError("Flexible spending milestone not found in plan.")
            if start and end:
                sy, ey = year(start), year(end)
                if start == end or (sy is not None and ey is not None and sy > ey):
                    raise ValueError("Flexible spending start must precede end.")
        for event in [*self.income_streams, *self.expenses]:
            start, end = event.start_milestone_id, event.end_milestone_id
            if not start or not end:
                continue
            sy, ey = year(start), year(end)
            if sy is not None and ey is not None and sy > ey:
                raise ValueError(f"{event.name}: start milestone is after end milestone.")
            if (start == end or (sy is not None and sy == ey)) and event.start_month is not None and event.end_month is not None and event.start_month > event.end_month:
                raise ValueError(f"{event.name}: start month must not be after end month in the same year.")
        for gift in self.charity_entities:
            if gift.source_account_id is not None:
                account = self.accounts.get(gift.source_account_id)
                if gift.entity_type != "qcd" or account is None or account.account_type != "traditional_ira" or account.owner not in {"self", "spouse"}:
                    raise ValueError(f"{gift.name}: QCD source must be a traditional IRA in this plan.")
            start, end = gift.start_milestone_id, gift.end_milestone_id
            if any(mid is not None and mid not in milestones for mid in (start, end)):
                raise ValueError(f"{gift.name}: milestone not found in plan.")
            if start and end:
                sy, ey = year(start), year(end)
                if start == end or (sy is not None and ey is not None and sy >= ey):
                    raise ValueError(f"{gift.name}: giving must end in a later year than it starts.")
        return self


# ---------------------------------------------------------------------------
# Converter: Pydantic request → engine dataclasses
# ---------------------------------------------------------------------------


def _filing_status_changes(changes: list[FilingStatusChange] | None) -> list[dict]:
    """Filing status changes, dumped to the dicts the engine reads."""
    return [change.model_dump() for change in changes or []]


def _milestone(m: MilestoneRequest) -> MilestoneData:
    """Milestones."""
    return MilestoneData(
        id=m.id,
        name=m.name,
        trigger_type=m.trigger_type,
        trigger_value=m.trigger_value,
        trigger_date=m.trigger_date,
        metric=m.metric,
        expense_multiple=m.expense_multiple,
        relative_to_id=m.relative_to_id,
        offset_years=m.offset_years,
        conditions=m.conditions.model_dump() if m.conditions else None,
        is_active=m.is_active,
    )


def _income(inc: IncomeRequest) -> IncomeData:
    """Income streams; growth and withholding percents become decimals."""
    return IncomeData(
        id=inc.id,
        name=inc.name,
        annual_amount=inc.annual_amount,
        is_active=inc.is_active,
        tax_category=inc.tax_category,
        start_milestone_id=inc.start_milestone_id,
        end_milestone_id=inc.end_milestone_id,
        growth_rate=inc.growth_rate / 100.0 if inc.growth_rate is not None else None,
        growth_cap=inc.growth_cap,
        growth_cap_inflation_linked=inc.growth_cap_inflation_linked,
        withholding_percent=(inc.withholding_percent or 0.0) / 100.0,
        start_month=inc.start_month,
        end_month=inc.end_month,
        is_social_security=inc.is_social_security,
        is_earned_income=inc.is_earned_income,
        is_self_employed=inc.is_self_employed,
        owner=inc.owner,
        claiming_age=inc.claiming_age,
        ss_benefit_basis=inc.ss_benefit_basis or "amount",
        frequency=inc.frequency,
        recurrence_years=inc.recurrence_years,
        pension_formula=inc.pension_formula.model_dump() if inc.pension_formula else None,
        pia_reflects=inc.pia_reflects,
        covered_years_to_date=inc.covered_years_to_date,
        pia_monthly=inc.pia_monthly,
        expected_benefit_percent=inc.expected_benefit_percent,
        growth_schedule=[segment.model_dump() for segment in inc.growth_schedule] if inc.growth_schedule else None,
        ex_spouse=inc.ex_spouse.model_dump() if inc.ex_spouse else None,
    )


def _expense(exp: ExpenseRequest) -> ExpenseData:
    """Expenses; growth, recurrence growth and discretionary percents become decimals."""
    return ExpenseData(
        id=exp.id,
        name=exp.name,
        annual_amount=exp.annual_amount,
        start_milestone_id=exp.start_milestone_id,
        end_milestone_id=exp.end_milestone_id,
        inflation_linked=exp.inflation_linked,
        growth_rate=(
            exp.growth_rate / 100.0
            if exp.growth_rate is not None
            else None
        ),
        growth_cap=exp.growth_cap,
        growth_cap_inflation_linked=exp.growth_cap_inflation_linked,
        recurrence_years=exp.recurrence_years,
        recurrence_growth_rate=exp.recurrence_growth_rate / 100.0,
        is_payroll_deduction=exp.is_payroll_deduction,
        payroll_tax_treatment=exp.payroll_tax_treatment,
        tied_income_id=exp.tied_income_id,
        specific_funding_source_id=exp.specific_funding_source_id,
        specific_funding_source_ids=exp.specific_funding_source_ids,
        start_month=exp.start_month,
        end_month=exp.end_month,
        category=exp.category,
        discretionary_fraction=(
            exp.discretionary_percent / 100.0
            if exp.discretionary_percent is not None
            else None
        ),
        qualified_education=exp.qualified_education,
        payroll_tax_elections=(exp.payroll_tax_elections.model_dump()
                               if exp.payroll_tax_elections is not None else None) or None,
    )


def _priority(p: PriorityRequest) -> PriorityData:
    """Cash flow priorities; employee and employer match rates become decimals."""
    return PriorityData(
        priority_rank=p.priority_rank,
        allocation_mode=p.allocation_mode,
        allocation_value=p.allocation_value,
        target_account_id=p.target_account_id,
        target_liability_id=p.target_liability_id,
        max_annual_amount=p.max_annual_amount,
        priority_type=p.priority_type,
        source_account_id=p.source_account_id,
        source_income_id=p.source_income_id,
        employee_rate=p.employee_rate / 100.0,
        employer_match_rate=p.employer_match_rate / 100.0,
        target_balance=p.target_balance,
        backdoor_roth=p.backdoor_roth,
        conversion_mode=p.conversion_mode,
        bracket_ceiling_rate=p.bracket_ceiling_rate,
        magi_cap=p.magi_cap,
        use_plan_tax_target=p.use_plan_tax_target,
        start_milestone_id=p.start_milestone_id,
        end_milestone_id=p.end_milestone_id,
        employer_match=employer_match_from_settings(
            p.employer_match.model_dump() if p.employer_match is not None else None),
        limit_mode=p.limit_mode,
        custom_annual_limit=p.custom_annual_limit,
        withdraw_if_short=p.withdraw_if_short,
        reduce_employer_contribution=p.reduce_employer_contribution,
        transfer_frequency=p.transfer_frequency,
    )


def _drawdown_entry(d: DrawdownEntryRequest) -> DrawdownEntryData:
    """Drawdown order."""
    return DrawdownEntryData(
        rank=d.rank,
        source_account_id=d.source_account_id,
    )


def _assumptions(a: AssumptionRequest) -> AssumptionData:
    """Plan-level growth and inflation assumptions."""
    return AssumptionData(
        inflation_rate=a.inflation_rate,
        stock_growth_rate=a.stock_growth_rate,
        bond_return_rate=a.bond_return_rate,
        stock_dividend_yield=a.stock_dividend_yield,
        cash_yield_rate=a.cash_yield_rate,
    )


def _assumption_curve(ac: AssumptionCurveRequest) -> AssumptionCurveData:
    """Assumption curves."""
    return AssumptionCurveData(
        curve_type=ac.curve_type,
        mode=ac.mode,
        fixed_rate=ac.fixed_rate,
        control_points=ac.control_points,
    )


def _account(acct: AccountInfoRequest) -> AccountInfo:
    """Accounts; nested settings are dumped to the dicts the engine reads."""
    return AccountInfo(
        balance=acct.balance,
        account_type=acct.account_type,
        name=acct.name,
        cost_basis=acct.cost_basis,
        inherited_year=acct.inherited_year,
        inheritance_settings=acct.inheritance_settings.model_dump() if acct.inheritance_settings else None,
        roth_settings=acct.roth_settings.model_dump(exclude_unset=True) if acct.roth_settings else None,
        investment_settings=(
            acct.investment_settings.model_dump()
            if acct.investment_settings else None
        ),
        withdrawal_lock=acct.withdrawal_lock.model_dump() if acct.withdrawal_lock else None,
        distribution_settings=(acct.distribution_settings.model_dump()
                               if acct.distribution_settings else None),
        include_in_liquid=acct.include_in_liquid,
        state_taxed_basis=acct.state_taxed_basis,
        owner=acct.owner,
        beneficiary_type=acct.beneficiary_type,
        intl_account_kind=acct.intl_account_kind,
    )


def _real_asset(ra: RealAssetRequest) -> RealAssetData:
    """Real assets; ``real_estate.engine_fields`` converts the real estate fields."""
    return RealAssetData(
        id=ra.id,
        name=ra.name,
        current_value=ra.current_value,
        adjusted_basis=ra.adjusted_basis,
        annual_appreciation_rate=ra.annual_appreciation_rate,
        annual_property_tax=ra.annual_property_tax,
        annual_maintenance=ra.annual_maintenance,
        property_tax_rate=ra.property_tax_rate,
        maintenance_rate=ra.maintenance_rate,
        insurance_rate=ra.insurance_rate,
        sale_year=ra.sale_year,
        sale_month=ra.sale_month,
        is_primary_residence=ra.is_primary_residence,
        tax_treatment=ra.tax_treatment,
        auto_liquidate_on_depletion=ra.auto_liquidate_on_depletion,
        liquidation_target_account_id=ra.liquidation_target_account_id,
        **real_estate.engine_fields(ra),
    )


def _liability(lb: LiabilityRequest) -> LiabilityData:
    """Liabilities."""
    # Request contract: ``interest_rate`` is an annual percentage (5.5 means
    # 5.5%). The engine works in decimals, so convert exactly once here.
    annual_rate = liability_rate_to_decimal(lb.interest_rate)
    return LiabilityData(
        id=lb.id,
        name=lb.name,
        principal_balance=lb.principal_balance,
        interest_rate=annual_rate,
        term_months=lb.term_months,
        monthly_payment=resolve_monthly_payment(
            lb.principal_balance, annual_rate,
            lb.term_months, lb.monthly_payment, lb.payment_type, lb.interest_method,
        ),
        payment_type=lb.payment_type,
        extra_payment=lb.extra_payment,
        offset_account_id=lb.offset_account_id,
        linked_asset_id=lb.linked_asset_id,
        payoff_milestone_id=lb.payoff_milestone_id,
        forgiveness=forgiveness_from_settings(
            lb.forgiveness.model_dump() if lb.forgiveness is not None else None),
        interest_method=lb.interest_method,
        recurrence_years=lb.recurrence_years,
        recurrence_end_year=lb.recurrence_end_year,
        recurrence_end_milestone_id=lb.recurrence_end_milestone_id,
    )


def _healthcare_settings(settings: HealthcareSettings | None) -> dict | None:
    """Healthcare settings, dumped in JSON mode (milestone UUIDs become strings)."""
    return settings.model_dump(mode="json") if settings is not None else None


def _sepp_settings(settings: SEPPSettingsRequest | None) -> SEPPSettingsData | None:
    """72(t) SEPP settings."""
    if settings is None:
        return None
    return SEPPSettingsData(
        enabled=settings.enabled,
        source_account_id=settings.source_account_id,
        method=settings.method,
        start_age=settings.start_age,
        interest_rate=settings.interest_rate,
        annual_amount=settings.annual_amount,
    )


def _cash_reserve(settings: CashReserveRequest | None) -> CashReserveData | None:
    """Cash reserve settings."""
    return cash_reserve_from_settings(settings.model_dump() if settings is not None else None)


def _local_tax(selection: LocalTaxSelection | None) -> dict | None:
    """A local income tax selection, for the plan or a residency period."""
    return selection.model_dump() if selection is not None else None


def _residency_period(rp: ResidencyPeriodRequest) -> ResidencyPeriodData:
    """Residency periods."""
    return ResidencyPeriodData(
        state_code=rp.state_code,
        start_milestone_id=rp.start_milestone_id,
        end_milestone_id=rp.end_milestone_id,
        start_year=rp.start_year,
        end_year=rp.end_year,
        rank=rp.rank,
        local_tax=_local_tax(rp.local_tax),
        country=rp.country,
        region=rp.region,
    )


def _charity(ch: CharityRequest) -> CharityData:
    """Charitable giving."""
    return CharityData(
        id=ch.id,
        name=ch.name,
        entity_type=ch.entity_type,
        annual_amount=ch.annual_amount,
        start_milestone_id=ch.start_milestone_id,
        end_milestone_id=ch.end_milestone_id,
        source_account_id=ch.source_account_id,
        funding=ch.funding,
    )


def _estate_settings(settings: EstateSettingsRequest | None) -> EstateSettingsData | None:
    """Estate settings; selling-cost and bequest percents become decimals."""
    if settings is None:
        return None
    return EstateSettingsData(
        household_lifecycle=settings.household_lifecycle,
        survivor_social_security_policy=settings.survivor_social_security_policy,
        survivor_social_security_eligibility_confirmed=settings.survivor_social_security_eligibility_confirmed,
        survivor_social_security_eligibility_source=settings.survivor_social_security_eligibility_source,
        step_up_basis_on_death=settings.step_up_basis_on_death,
        filing_status_after_death=settings.filing_status_after_death,
        federal_estate_exemption=settings.federal_estate_exemption,
        state_estate_tax_enabled=settings.state_estate_tax_enabled,
        state_estate_exemption=settings.state_estate_exemption,
        state_estate_tax_rate=settings.state_estate_tax_rate,
        custom_federal_exemption_enabled=settings.custom_federal_exemption_enabled,
        portability_election=settings.portability_election,
        settlement_cost_fixed=settings.settlement_cost_fixed,
        settlement_cost_rate=settings.settlement_cost_rate,
        heir_income_tax_rate=settings.heir_income_tax_rate,
        heir_capital_gains_rate=settings.heir_capital_gains_rate,
        estate_selling_cost_rate=settings.estate_selling_cost_percent / 100.0,
        charitable_bequest_rate=settings.charitable_bequest_percent / 100.0,
        joint_account_step_up=settings.joint_account_step_up,
    )


def _spending_rules(rules: SpendingRulesRequest | None) -> SpendingRulesData | None:
    """Flexible spending rules."""
    if rules is None:
        return None
    return SpendingRulesData(
        flex_threshold=rules.flex_threshold,
        flex_reduction=rules.flex_reduction,
        lookback_years=rules.lookback_years,
        spending_floor=rules.spending_floor,
        performance_mode=rules.performance_mode,
        interpolation=rules.interpolation,
        thresholds=[
            SpendingRuleThresholdData(
                threshold=item.threshold,
                reduction=item.reduction,
            )
            for item in rules.thresholds
        ],
        start_milestone_id=rules.start_milestone_id,
        end_milestone_id=rules.end_milestone_id,
        upside_thresholds=[
            SpendingUpsideData(threshold=point.threshold, increase=point.increase)
            for point in rules.upside_thresholds
        ],
        flex_scope=list(rules.flex_scope),
        surplus_mode=rules.surplus_mode,
    )


def _tax_settings(settings: TaxSettingsRequest | None) -> dict | None:
    """Tax settings, dumped without unset optional values."""
    return settings.model_dump(exclude_none=True) if settings is not None else None


def _withdrawal_strategy(settings: WithdrawalStrategySettings | None) -> WithdrawalStrategySpec | None:
    """Withdrawal strategy spec."""
    return spec_from_settings(settings.model_dump(mode="json")) if settings is not None else None


def _intl_settings(settings: IntlSettings | None) -> dict | None:
    """Country regime settings, dumped in JSON mode."""
    return settings.model_dump(mode="json") if settings is not None else None


def request_to_engine_data(request: PlanDataRequest) -> PlanData:
    """Convert a validated PlanDataRequest into the engine's PlanData dataclass."""
    return PlanData(
        plan_id=str(request.plan_id),
        birth_year=request.birth_year,
        birth_month=request.birth_month,
        filing_status=request.filing_status,
        filing_status_changes=_filing_status_changes(request.filing_status_changes),
        life_expectancy=request.life_expectancy,
        start_year=request.start_year,
        first_year_fraction=request.first_year_fraction,
        milestones=[_milestone(m) for m in request.milestones],
        income_streams=[_income(inc) for inc in request.income_streams],
        expenses=[_expense(exp) for exp in request.expenses],
        priorities=[_priority(p) for p in request.priorities],
        drawdown_order=[_drawdown_entry(d) for d in request.drawdown_order],
        assumptions=_assumptions(request.assumptions),
        assumption_curves=[_assumption_curve(ac) for ac in request.assumption_curves],
        accounts={aid: _account(acct) for aid, acct in request.accounts.items()},
        real_assets=[_real_asset(ra) for ra in request.real_assets],
        liabilities=[_liability(lb) for lb in request.liabilities],
        spouse_birth_year=request.spouse_birth_year,
        spouse_birth_month=request.spouse_birth_month,
        spouse_life_expectancy=request.spouse_life_expectancy,
        healthcare_settings=_healthcare_settings(request.healthcare_settings),
        sepp_settings=_sepp_settings(request.sepp_settings),
        cash_reserve=_cash_reserve(request.cash_reserve_settings),
        state_code=request.state_code,
        local_tax=_local_tax(request.local_tax),
        residency_periods=[_residency_period(rp) for rp in request.residency_periods],
        charity_entities=[_charity(ch) for ch in request.charity_entities],
        estate_settings=_estate_settings(request.estate_settings),
        spending_rules=_spending_rules(request.spending_rules),
        tax_settings=_tax_settings(request.tax_settings),
        withdrawal_strategy=_withdrawal_strategy(request.withdrawal_strategy),
        tax_country=request.tax_country,
        tax_region=request.tax_region,
        currency=request.currency,
        intl_settings=_intl_settings(request.intl_settings),
    )

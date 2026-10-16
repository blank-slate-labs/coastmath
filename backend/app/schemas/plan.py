import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.schemas.assumption_curve import AssumptionCurveRead
from app.schemas.cash_flow_priority import CashFlowPriorityRead
from app.schemas.cash_reserve import CashReserveSettings
from app.schemas.drawdown_order import DrawdownOrderRead
from app.schemas.estate_settings import EstateSettings
from app.schemas.expense import ExpenseRead
from app.schemas.income import IncomeRead
from app.schemas.liability import LiabilityRead
from app.schemas.milestone import MilestoneRead
from app.schemas.real_asset import RealAssetRead
from app.schemas.residency_period import ResidencyPeriodCreate, ResidencyPeriodRead
from app.schemas.sepp_settings import SEPPSettings
from app.schemas.spouse import SpouseRead, SpouseUpdate
from app.schemas.tax_jurisdiction import US_STATE_CODES
from coastmath.engine.assumption_curves import default_assumption_rates
from coastmath.schemas.birth_year import BirthYear
from coastmath.schemas.estimated_payments import EstimatedPayments
from coastmath.schemas.filing_status_change import FilingStatusChange
from coastmath.schemas.healthcare_settings import HealthcareSettings
from coastmath.schemas.intl_settings import (
    IntlSettings,
    check_plan_regimes,
    normalize_country,
    normalize_currency,
    normalize_region,
    normalize_supported_country,
)
from coastmath.schemas.item_name import ItemName
from coastmath.schemas.local_tax import (
    LocalTaxSelection,
    LocalTaxSelectionRead,
    check_local_tax_state,
)
from coastmath.schemas.plan_data_request import (
    SpendingRulesRequest,
    SpendingRuleThresholdRequest,
    TaxSettingsRequest,
)
from coastmath.schemas.tax_target import TaxTarget
from coastmath.schemas.withdrawal_strategy import WithdrawalStrategySettings

# Plain-text plan notes; generous but bounded so a single plan cannot carry
# unbounded payloads through the API.
NOTES_MAX_LENGTH = 20_000
# Collection bounds far above real plans; they cap stored JSON and engine work.
MAX_SNAPSHOT_ACCOUNTS = 200
MAX_RESIDENCY_PERIODS = 50

FilingStatus = Literal[
    "single",
    "married_filing_jointly",
    "married_filing_separately",
    "head_of_household",
]


# Saved plan settings share the engine request fields and validators. Saved
# spending rules reject unknown keys, which the engine request ignores.
class SpendingRuleThreshold(SpendingRuleThresholdRequest):
    model_config = ConfigDict(extra="forbid")


class SpendingRules(SpendingRulesRequest):
    model_config = ConfigDict(extra="forbid")

    thresholds: list[SpendingRuleThreshold] = Field(default_factory=list, max_length=10)


class TaxSettings(TaxSettingsRequest):
    # Omitted when unset, so stored settings and plan reads without it are unchanged.
    estimated_payments: EstimatedPayments | None = Field(default=None, exclude_if=lambda value: value is None)
    # Plan tax target. Omitted when unset, so stored settings and plan reads
    # without it are unchanged.
    tax_target: TaxTarget | None = Field(default=None, exclude_if=lambda value: value is None)


def check_state_code(value: str | None) -> str | None:
    """A US state or DC postal code; blank means no state."""
    if value is None or not value.strip():
        return None
    code = value.strip().upper()
    if code not in US_STATE_CODES:
        raise ValueError("Choose a US state, or none")
    return code


class PlanCreate(BaseModel):
    filing_status_changes: list[FilingStatusChange] | None = Field(default=None, max_length=100)
    profile_name: str | None = Field(default=None, max_length=255)
    client_id: uuid.UUID | None = None
    name: ItemName
    plan_type: Literal["NOW", "FIXED_DATE"] = "NOW"
    start_date: date | None = None
    snapshot_conditions: dict = Field(default_factory=dict, max_length=MAX_SNAPSHOT_ACCOUNTS)
    birth_year: BirthYear
    birth_month: int | None = Field(default=None, ge=1, le=12)
    filing_status: FilingStatus = "single"
    state_code: str | None = None
    # Local income tax for state_code; residency periods carry their own.
    local_tax: LocalTaxSelection | None = None
    life_expectancy: int = Field(default=95, ge=50, le=120)
    sepp_settings: SEPPSettings | None = None
    estate_settings: EstateSettings | None = None
    spending_rules: SpendingRules | None = None
    tax_settings: TaxSettings | None = None
    notes: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH)
    healthcare_settings: HealthcareSettings | None = None
    withdrawal_strategy: WithdrawalStrategySettings | None = None
    # Optional partner created with the plan in one transaction (same shape as PlanUpdate.spouse).
    spouse: SpouseUpdate | None = None
    # Seeds an age-triggered "Retirement" milestone; skipped when the plan starts at or after that age.
    retirement_milestone_age: int | None = Field(default=None, ge=18, le=120)
    # Country tax regime (coastmath.schemas.intl_settings). Defaults keep a US plan.
    tax_country: str = Field(default="US", min_length=2, max_length=2)
    tax_region: str | None = Field(default=None, max_length=8)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    intl_settings: IntlSettings | None = None

    _check_state = field_validator("state_code")(classmethod(lambda cls, v: check_state_code(v)))
    _normalize_country = field_validator("tax_country")(classmethod(lambda cls, v: normalize_supported_country(v)))
    _normalize_region = field_validator("tax_region")(classmethod(lambda cls, v: normalize_region(v)))
    _normalize_currency = field_validator("currency")(classmethod(lambda cls, v: normalize_currency(v)))

    @model_validator(mode="after")
    def _check_regime(self):
        check_plan_regimes(self.tax_country, self.tax_region, self.intl_settings)
        return self

    @model_validator(mode="after")
    def check_start_after_birth(self):
        if self.plan_type == "FIXED_DATE" and self.start_date is not None and self.start_date < date(self.birth_year, self.birth_month or 1, 1):
            raise ValueError("Start date must be on or after your birth year/month.")
        return self

    @model_validator(mode="after")
    def _local_tax_in_state(self):
        check_local_tax_state(self.local_tax, self.state_code)
        return self


class PlanUpdate(BaseModel):
    filing_status_changes: list[FilingStatusChange] | None = Field(default=None, max_length=100)
    profile_name: str | None = Field(default=None, max_length=255)
    name: ItemName | None = None
    plan_type: Literal["NOW", "FIXED_DATE"] | None = None
    start_date: date | None = None
    snapshot_conditions: dict | None = Field(default=None, max_length=MAX_SNAPSHOT_ACCOUNTS)
    birth_year: BirthYear | None = None
    birth_month: int | None = Field(default=None, ge=1, le=12)
    filing_status: FilingStatus | None = None
    state_code: str | None = None
    # Checked against the saved or updated state_code by the plans router.
    local_tax: LocalTaxSelection | None = None
    life_expectancy: int | None = Field(default=None, ge=50, le=120)
    sepp_settings: SEPPSettings | None = None
    estate_settings: EstateSettings | None = None
    spending_rules: SpendingRules | None = None
    tax_settings: TaxSettings | None = None
    baseline_plan_id: uuid.UUID | None = None
    healthcare_settings: HealthcareSettings | None = None
    # Null clears the saved strategy; omit to leave it unchanged.
    withdrawal_strategy: WithdrawalStrategySettings | None = None
    cash_reserve_settings: CashReserveSettings | None = None
    residency_periods: list[ResidencyPeriodCreate] | None = Field(default=None, max_length=MAX_RESIDENCY_PERIODS)
    # Omit to leave the partner unchanged; null removes the partner record.
    spouse: SpouseUpdate | None = None
    notes: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH)
    # Country tax regime; checked against the saved plan by the plans router.
    tax_country: str | None = Field(default=None, min_length=2, max_length=2)
    tax_region: str | None = Field(default=None, max_length=8)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    # Null clears the settings; omit to leave them unchanged.
    intl_settings: IntlSettings | None = None

    _check_state = field_validator("state_code")(classmethod(lambda cls, v: check_state_code(v)))
    # A plan saved in a retired country may resend it unchanged; the router refuses a change to one.
    _normalize_country = field_validator("tax_country")(classmethod(lambda cls, v: normalize_country(v)))
    _normalize_region = field_validator("tax_region")(classmethod(lambda cls, v: normalize_region(v)))
    _normalize_currency = field_validator("currency")(
        classmethod(lambda cls, v: None if v is None else normalize_currency(v)))


class PlanSummary(BaseModel):
    """Plan-picker identity without loading or serializing child inputs."""
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    client_id: uuid.UUID | None = None
    name: str
    plan_type: Literal["NOW", "FIXED_DATE"]
    created_at: datetime
    # A scenario's Main plan; omitted for every other plan.
    parent_plan_id: uuid.UUID | None = Field(default=None, exclude_if=lambda value: value is None)


class ArchivedPlanSummary(BaseModel):
    """An archived plan as the archive list shows it: identity only, on every tier."""
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    client_id: uuid.UUID | None = None
    name: str
    created_at: datetime
    archived_at: datetime


class PlanRead(BaseModel):
    filing_status_changes: list[FilingStatusChange] | None = Field(default=None, max_length=100)
    profile_name: str | None = None
    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def assumption_defaults(self) -> dict[str, float]:
        """Engine defaults; saved assumption_curves override these rates."""
        return default_assumption_rates()

    id: uuid.UUID
    user_id: uuid.UUID
    client_id: uuid.UUID | None = None
    name: str = Field(max_length=255)
    plan_type: Literal["NOW", "FIXED_DATE"]
    start_date: date | None = None
    snapshot_conditions: dict = {}
    birth_year: int
    birth_month: int | None = None
    filing_status: FilingStatus
    state_code: str | None = None
    local_tax: LocalTaxSelectionRead | None = None
    life_expectancy: int
    created_at: datetime
    # An access policy that limits editing (app.access) allows it until
    # edit_window_ends_at, or edit_grace_ends_at when that grace was given.
    # editable is the server's verdict for this account; null when not evaluated.
    archived_at: datetime | None = None
    edit_window_ends_at: datetime | None = None
    edit_notice_seen_at: datetime | None = None
    edit_grace_ends_at: datetime | None = None
    editable: bool | None = None

    milestones: list[MilestoneRead] = []
    income_streams: list[IncomeRead] = []
    expenses: list[ExpenseRead] = []
    priorities: list[CashFlowPriorityRead] = []
    priorities_revision: int = 0
    drawdown_order: list[DrawdownOrderRead] = []
    assumption_curves: list[AssumptionCurveRead] = []
    real_assets: list[RealAssetRead] = []
    liabilities: list[LiabilityRead] = []
    residency_periods: list[ResidencyPeriodRead] = []
    spouse: SpouseRead | None = None
    sepp_settings: SEPPSettings | None = None
    estate_settings: EstateSettings | None = None
    spending_rules: SpendingRules | None = None
    tax_settings: TaxSettings | None = None
    baseline_plan_id: uuid.UUID | None = None
    notes: str | None = None
    healthcare_settings: HealthcareSettings | None = None
    # Omitted when no strategy is saved, so existing plan reads are unchanged.
    withdrawal_strategy: WithdrawalStrategySettings | None = Field(default=None, exclude_if=lambda value: value is None)
    cash_reserve_settings: CashReserveSettings | None = Field(default=None, exclude_if=lambda value: value is None)
    tax_country: str = "US"
    tax_region: str | None = None
    currency: str = "USD"
    # Stored settings are read back as saved (not re-validated against the
    # registry); omitted when unset.
    intl_settings: dict | None = Field(default=None, exclude_if=lambda value: value is None)
    # A scenario's Main plan (app.scenarios); omitted for every other plan, so
    # existing plan reads are unchanged.
    parent_plan_id: uuid.UUID | None = Field(default=None, exclude_if=lambda value: value is None)

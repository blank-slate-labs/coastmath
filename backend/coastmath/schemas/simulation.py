import uuid
from datetime import date
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    computed_field,
    model_serializer,
)

from coastmath.engine.cash_flow_graph import build_cash_flow_graph


class TransferFlowSchema(BaseModel):
    source_account_id: str
    target_account_id: str
    amount: float
    source_account_name: str | None = None
    target_account_name: str | None = None


class NamedAmountSchema(BaseModel):
    name: str
    amount: float
    category: str | None = None
    account_id: str | None = None
    account_name: str | None = None
    source: str | None = None
    priority_rank: int | None = None
    requested_amount: float | None = None
    limited_by: list[str] = []
    funding_reasons: list[Literal["insufficient_surplus", "earlier_rules", "ownership", "income_eligibility", "compensation", "contribution_limit", "annual_maximum", "target_balance", "zero_request", "inactive_rule", "loan_paid_off", "withdrawal_shortfall"]] = []
    # Expense rows with a discretionary percent only: the discretionary part of
    # ``amount`` after any flex cut; the rest is essential. ``category`` still
    # names the larger share. Omitted otherwise.
    discretionary_amount: float | None = None

    @model_serializer(mode="wrap")
    def omit_absent_split(self, handler):
        """Keep rows without a split byte-identical to responses before it existed."""
        data = handler(self)
        if self.discretionary_amount is None:
            data.pop("discretionary_amount", None)
        return data


class CashFlowNodeSchema(BaseModel):
    id: str = Field(description="Stable across years, e.g. hub:gross, income:Salary, to:<account id>.")
    name: str
    group: Literal["income", "tax", "saving", "spending", "shortfall", "hub"]


class CashFlowLinkSchema(BaseModel):
    source: str
    target: str
    amount: float


class CashFlowGraphSchema(BaseModel):
    nodes: list[CashFlowNodeSchema] = []
    links: list[CashFlowLinkSchema] = []


class CashFlowBreakdownSchema(BaseModel):
    income_sources: list[NamedAmountSchema] = []
    gross_income: float = 0
    tax_withheld: float = 0
    payroll_deductions: float = 0
    net_pay: float = 0
    tax_delta: float = 0
    early_withdrawal_penalty: float = 0
    expenses: list[NamedAmountSchema] = []
    payroll_expenses: list[NamedAmountSchema] = Field(
        default=[], exclude_if=lambda value: not value,
        description="Expenses deducted from pay, included in payroll_deductions. Omitted when empty.")
    contributions: list[NamedAmountSchema] = []
    transfers: list[TransferFlowSchema] = []
    drawdowns: list[NamedAmountSchema] = []
    # Opt-in estimated tax (tax_settings.estimated_payments). Omitted when
    # zero, so responses for plans without it are unchanged; read as 0.
    estimated_tax_payments: float = Field(
        default=0, exclude_if=lambda value: value == 0,
        description="Federal estimated tax paid during the year; tax_delta is the balance at filing after it. Omitted when zero.")
    required_annual_payment: float = Field(
        default=0, exclude_if=lambda value: value == 0,
        description="IRC 6654(d) required annual payment for the year. Omitted when zero.")
    underpayment_penalty: float = Field(
        default=0, exclude_if=lambda value: value == 0,
        description="Estimated IRC 6654 underpayment penalty, a nondeductible outflow included in the year's taxes. Omitted when zero.")

    @computed_field(description="The year as a Sankey graph that every client draws as served "
                                "(coastmath.engine.cash_flow_graph).")
    @property
    def graph(self) -> CashFlowGraphSchema:
        built = build_cash_flow_graph(self)
        return CashFlowGraphSchema(
            nodes=[CashFlowNodeSchema(id=item.id, name=item.name, group=item.group) for item in built.nodes],
            links=[CashFlowLinkSchema(source=item.source, target=item.target, amount=item.amount) for item in built.links],
        )


class HealthcareYearSchema(BaseModel):
    aca_covered_adults: int = 0
    aca_household_size: int = 0
    aca_magi: float = 0
    aca_fpl_ratio: float = 0
    aca_applicable_percentage: float = 0
    aca_benchmark_premium: float = 0
    aca_gross_premium: float = 0
    aca_credit: float = 0
    aca_net_premium: float = 0
    aca_cash_premium: float = 0
    aca_eligible: bool = False
    aca_reason: str | None = None
    aca_magi_estimate: float = 0
    aca_credit_advanced: float = 0
    aca_reconciliation: float = 0
    medicare_persons: float = 0
    medicare_magi_used: float = 0
    medicare_lookback_year: int | None = None
    medicare_lookback_source: str = "none"
    medicare_lookback_filing_status: str | None = None
    medicare_tier: int = 0
    medicare_part_b: float = 0
    medicare_irmaa_part_b: float = 0
    medicare_irmaa_part_d: float = 0
    medicare_part_d_plan: float = 0
    medicare_supplement: float = 0
    medicare_part_a: float = 0
    itemized_medical: float = 0
    out_of_pocket: float = 0
    long_term_care_gross: float = 0
    long_term_care_covered: float = 0
    long_term_care: float = 0
    person_costs: list[dict] = Field(default_factory=list)
    total: float = 0


class IntlTaxLineSchema(BaseModel):
    """One line of a country-regime year's tax."""

    code: str
    label: str
    # income_national, income_regional, income_local, social_contribution,
    # levy, wealth, transaction, credit (negative), benefit_recovery, estate.
    category: str
    person: Literal["self", "spouse"] | None = None
    amount: float


class YearSnapshot(BaseModel):
    year: int
    age: int = 0
    gross_income: float = 0
    taxes: float = 0
    federal_tax: float = 0
    state_tax: float = 0
    local_tax: float = 0
    # State retirement-income subtraction taken in computing state_tax.
    # Additive; older services omit it.
    state_retirement_exclusion: float = 0
    # State subtraction of federally taxable Social Security and the state
    # capital gains excise (Washington, included in state_tax). Additive.
    ss_earnings_test_withheld: float = 0.0
    state_social_security_subtraction: float = 0
    state_capital_gains_excise: float = 0
    # User tax adjustments behind taxes: federal deductions taken, credits
    # used on both returns (including any refunded part) and surcharges
    # added. Additive; older services omit them.
    tax_adjustment_deductions: float = 0
    tax_adjustment_credits: float = 0
    tax_adjustment_surcharge: float = 0
    # Rental properties: collected rent, cash expenses (operating, property
    # tax and upkeep, loan interest), depreciation, the net amount in AGI
    # after the passive loss rules and suspended losses carried forward.
    # Real property sales: gain from depreciation (unrecaptured section 1250
    # gain). Planned purchases: cash paid. Additive; older services omit them.
    rental_income: float = 0
    rental_expenses: float = 0
    rental_depreciation: float = 0
    rental_taxable_income: float = 0
    suspended_passive_losses: float = 0
    unrecaptured_section_1250_gain: float = 0
    real_estate_purchases: float = 0
    rule_funding_shortfall: float = 0
    # Country tax regime: the country whose regime taxed the year ("US" for
    # the US path), its tax lines and totals by kind, all included in taxes.
    # Lines are empty and totals 0 in US years. Additive.
    tax_country: str = "US"
    intl_tax_lines: list[IntlTaxLineSchema] = Field(default_factory=list)
    national_income_tax: float = 0
    regional_income_tax: float = 0
    social_contributions: float = 0
    wealth_tax: float = 0
    transaction_tax: float = 0
    benefit_recovery_tax: float = 0
    # Full calendar-year basis for tax lines; gross_income remains the
    # simulated-period cash-flow figure. Optional for older services.
    calendar_year_gross_income: float | None = None
    capital_gains_tax: float = 0
    fica_tax: float = 0
    niit_tax: float = 0
    amt_tax: float = 0
    early_withdrawal_penalty: float = 0
    tax_balance: float = 0
    unfunded_expenses: float = 0
    capital_loss_carryforward: float = 0
    expenses: float = 0
    net_cash_flow: float = 0
    accounts: dict[str, float] = {}
    real_assets_value: float = 0
    liabilities_balance: float = 0
    net_worth: float = 0
    effective_rate: float = 0
    marginal_rate: float = 0
    deduction_used: str = "standard"
    deduction_amount: float = 0
    standard_deduction: float = 0
    flex_spending_reduction: float = 0
    # Additive: extra spending allowed by a new all-time high, and surplus cash
    # spent rather than saved (spend-the-leftover mode).
    flex_spending_increase: float = 0
    leftover_spending: float = 0
    investment_growth: float = 0
    #: Account fees deducted this year (annual_fee_rate); already netted out
    #: of investment_growth.
    investment_fees: float = 0.0
    milestones_triggered: list[str] = []
    transfers: list[TransferFlowSchema] = []
    cash_flow: CashFlowBreakdownSchema | None = None
    healthcare: HealthcareYearSchema | None = None
    harvested_gains: float = 0
    debt_forgiven: float = 0
    debt_forgiveness_taxable: float = 0
    # Plan tax target (tax_settings.tax_target). Additive; null/zero for
    # years without a target in force.
    tax_target_room: float | None = Field(
        default=None,
        description="Income room below the year's effective tax target before target-sized strategies ran. Null when no target applies.")
    tax_target_blended_withdrawals: float = Field(
        default=0,
        description="Gross shortfall withdrawals taken by the first, tax-target-filling drawdown pass.")
    bond_allocation_by_account: dict[str, float] = Field(
        default_factory=dict,
        description="Household asset location (tax_settings.asset_location): each pooled account's bond share "
                    "this year as a decimal. Empty in per-account mode.")
    strategy_spending: float | None = None
    planned_expenses: float | None = None
    # Cumulative general inflation the engine applied to plan amounts in this
    # year, from the plan's own inflation assumption (fixed rate or curve, or a
    # historical path's inflation). Start-of-year anchor: the first snapshot is
    # 1.0 and year n is the product of (1 + rate) over the n prior years, the
    # same convention as the web deflators and withdrawal comparison's
    # plan_inflation_factor. Today's dollars: real = nominal / inflation_factor.
    # Optional and additive: older services omit it.
    inflation_factor: float | None = None
    # Opening partial year: full-year liability less tax paid before the start.
    # Includes federal, FICA, state/local tax and penalties; state payroll
    # costs remain separate expenses. Signed for a refund. Null otherwise.
    post_start_taxes: float | None = None
    # Stable codes for the year's modeling basis (``ytd_imputed_pro_rata``). Additive.
    warnings: list[str] = Field(default_factory=list)
    # Engine-only: accounts not liquid this year (withdrawal-locked or
    # excluded by the account's liquid override), which Monte Carlo's
    # liquid_assets failure mode treats as illiquid. Never serialized.
    _locked_account_ids: frozenset[str] = PrivateAttr(default_factory=frozenset)
    # Engine-only: accounts whose liquid override always excludes them.
    _liquid_excluded_account_ids: frozenset[str] = PrivateAttr(default_factory=frozenset)
    # Engine-only: ss_earnings_test_withheld by the owner whose earnings the
    # test counted, before auxiliary top-ups (coastmath.engine.ss_claiming).
    _ss_earnings_test_withheld_by_earner: dict[str, float] = PrivateAttr(default_factory=dict)

    def liquid_account_total(self) -> float:
        """Account balances excluding this year's illiquid accounts."""
        return sum(value for account_id, value in self.accounts.items() if account_id not in self._locked_account_ids)

    def liquid_excluded_total(self) -> float:
        """Balances of accounts the plan always leaves out of liquid net worth."""
        return sum(value for account_id, value in self.accounts.items()
                   if account_id in self._liquid_excluded_account_ids)


class NetLegacyBreakdown(BaseModel):
    """Itemised estate result at the plan holder's death (engine-derived)."""

    total_assets: float
    total_liabilities: float
    gross_estate: float
    federal_exemption: float
    dsue_amount: float = 0
    federal_taxable_estate: float
    federal_estate_tax: float
    state_exemption: float = 0
    state_taxable_estate: float = 0
    state_estate_tax: float = 0
    estate_tax: float
    net_legacy: float
    marital_deduction_applied: bool = False
    custom_federal_exemption: bool = False
    death_year: int
    exclusions: list[str] = []
    debts: float = 0
    accrued_taxes: float = 0
    settlement_costs: float = 0
    taxable_estate_before_exemptions: float = 0
    pretax_balance: float = 0
    heir_income_tax_deduction_691c: float = 0
    heir_income_tax: float = 0
    net_to_heirs_after_income_tax: float = 0
    education_savings_outside_estate: float = 0
    charitable_bequest: float = 0
    selling_costs: float = 0
    unrealized_gains: float = 0
    heir_capital_gains_tax: float = 0


class MilestoneOutcome(BaseModel):
    """When (if ever) each milestone fired in the projection."""

    id: str
    name: str
    trigger_type: str
    year: int | None = None
    missed_year: int | None = Field(default=None, exclude_if=lambda value: value is None)


class FiEstimate(BaseModel):
    """CoastMath's financial independence estimate.

    The year an ``expense_multiple`` milestone at ``multiple``× on liquid
    accounts minus debt would fire: the prior year's closing balance strictly
    exceeds ``multiple`` times that year's spending, annualized for a partial
    opening year. ``target`` is in ``basis_year`` nominal dollars. All three
    are null when the projection never reaches it. Display only: it does not
    end income or change the projection.
    """

    year: int | None = None
    basis_year: int | None = None
    target: float | None = None
    multiple: float = 25


class SimMetadata(BaseModel):
    plan_id: uuid.UUID
    start_year: int
    end_year: int
    start_date: date | None = None
    first_year_fraction: float = 1
    success: bool = True
    failure_year: int | None = None
    net_legacy: NetLegacyBreakdown | None = None
    rmd_start_age: int | None = None
    warnings: list[str] = []
    milestone_outcomes: list[MilestoneOutcome] = []
    #: Set by every deterministic projection; null only from older servers.
    fi_estimate: FiEstimate | None = None
    # Always empty; kept so shipped clients keep decoding results.
    locked_sections: list[str] = []


class OpeningSnapshot(BaseModel):
    as_of: date
    accounts: dict[str, float]
    real_assets_value: float = 0
    liabilities_balance: float = 0
    net_worth: float


class SimulationResult(BaseModel):
    metadata: SimMetadata
    initial_snapshot: OpeningSnapshot | None = None
    yearly_snapshots: list[YearSnapshot]


class CompareRequest(BaseModel):
    baseline_plan_id: uuid.UUID


class YearDelta(BaseModel):
    year: int
    current_net_worth: float
    baseline_net_worth: float
    difference: float  # current - baseline


class CompareResponse(BaseModel):
    current: SimulationResult
    baseline: SimulationResult
    delta: list[YearDelta]


class HistoricalStressMetadata(BaseModel):
    historical_start_year: int
    years_used: list[int]
    wrapped: bool


class HistoricalStressResult(BaseModel):
    simulation_result: SimulationResult
    metadata: HistoricalStressMetadata


class ScenarioStressRequest(BaseModel):
    """A hypothetical stress preset. Unused parameters are ignored."""
    model_config = ConfigDict(extra="forbid")

    preset: Literal["job_loss", "market_crash", "tech_bust", "new_child", "downturn"]
    start_year: int = Field(ge=1900, le=2300)
    person: Literal["self", "spouse"] = "self"
    months_without_pay: int = Field(default=6, ge=1, le=60)
    resume_percent: float = Field(default=80, ge=0, le=200, allow_inf_nan=False)
    stock_drop_percent: float = Field(default=35, ge=1, le=90, allow_inf_nan=False)
    # Plan-start-year dollars, inflation-linked.
    child_annual_cost: float = Field(default=18_000, ge=0, le=1_000_000, allow_inf_nan=False)
    # downturn: stock_drop_percent is the cumulative decline over downturn_years.
    downturn_years: int = Field(default=3, ge=1, le=10)
    recovery_years: int = Field(default=0, ge=0, le=10)
    # Annual, downturn years only; null keeps the plan's assumption.
    bond_return_percent: float | None = Field(default=None, ge=-50, le=50, allow_inf_nan=False)
    inflation_percent: float | None = Field(default=None, ge=-10, le=30, allow_inf_nan=False)


class DownturnPathYear(BaseModel):
    """One shocked year, decimal rates as applied.

    ``stock_return`` is the yearly total-return factor before a partial
    opening year's annualization.
    """
    year: int
    stock_return: float
    bond_return: float
    inflation: float
    phase: Literal["downturn", "recovery"]


class ScenarioStressMetadata(BaseModel):
    preset: Literal["job_loss", "market_crash", "tech_bust", "new_child", "downturn"]
    start_year: int
    person: Literal["self", "spouse"] | None = None
    months_without_pay: int | None = None
    resume_percent: float | None = None
    stock_drop_percent: float | None = None
    child_annual_cost: float | None = None
    child_cost_years: int | None = None
    downturn_years: int | None = None
    recovery_years: int | None = None
    bond_return_percent: float | None = None
    inflation_percent: float | None = None
    downturn_path: list[DownturnPathYear] | None = None


class ScenarioStressResult(BaseModel):
    simulation_result: SimulationResult
    metadata: ScenarioStressMetadata

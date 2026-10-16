"""Core simulation data structures for the projection engine.

All types here are plain Python dataclasses (not Pydantic) — these are
engine internals, not API schemas.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from coastmath.engine.account_types import ROTH_TYPES
from coastmath.engine.cost_basis import (
    calculate_gain_on_withdrawal,
    update_cost_basis_on_deposit,
)
from coastmath.engine.roth import ledger
from coastmath.engine.withdrawal_strategy import WithdrawalStrategySpec

# Account types that earn 0% growth (cash-like).
# Everything else grows at the stock_growth_rate.
_ZERO_GROWTH_TYPES = frozenset({"checking", "savings"})

# Account types that generate capital gains on withdrawal.
# Tax-advantaged accounts (IRA, 401k, Roth, HSA, 529) do NOT. Cryptocurrency
# has no dividend yield below, but realized price gains are taxable just like
# gains from a brokerage account.
_TAXABLE_TYPES = frozenset({"taxable_brokerage", "cryptocurrency"})


# ---------------------------------------------------------------------------
# Primitive building blocks
# ---------------------------------------------------------------------------

@dataclass
class AccountInfo:
    balance: float
    account_type: str
    cost_basis: float | None = None
    inherited_year: int | None = None
    owner: str = "self"  # "self", "spouse", or "joint"
    beneficiary_type: str = "non_edb"  # "spouse", "edb", or "non_edb"
    name: str = ""
    inheritance_settings: dict | None = None
    roth_settings: dict | None = None
    # Optional fixed account investment overrides.  Each nullable value
    # inherits the corresponding plan assumption; values are decimal rates.
    investment_settings: dict | None = None
    # When voluntary withdrawals may start (coastmath.engine.withdrawal_locks).
    # None: any time.
    withdrawal_lock: dict | None = None
    # Distribution metadata (schemas.account.AccountDistributionSettings):
    # separation_year (Rule of 55) and spouse_sole_beneficiary (RMD table).
    distribution_settings: dict | None = None
    # Employee contributions in a traditional account that the state of
    # residence at plan start already taxed (coastmath.engine.state_taxed_basis).
    state_taxed_basis: float | None = None
    # Country account kind "<CC>:<kind_id>" (coastmath.engine.intl_accounts); its
    # rules replace the US account rules for this account.
    intl_account_kind: str | None = None
    # Liquid net worth override: None counts the account as liquid unless it
    # is withdrawal-locked that year; True always counts it; False never does.
    include_in_liquid: bool | None = None


def account_investment_rates(
    account: AccountInfo,
    stock_growth_rate: float,
    bond_growth_rate: float,
    bond_allocation: float,
    stock_dividend_yield: float,
    resolved_bond_allocation: float | None = None,
) -> tuple[float, float, float, float]:
    """Return annual stock/bond/allocation/dividend rates for one account.

    Account overrides intentionally cover only fixed stock price growth,
    stock dividend yield, and bond allocation.  Bond return always comes from
    the plan (or its sampled Monte Carlo return sequence).
    ``resolved_bond_allocation`` is a bond share already decided for this year
    (glide path or household asset location, coastmath.engine.bond_location); it
    replaces both the account's fixed value and the plan allocation.
    """
    settings = account.investment_settings or {}
    return (
        settings.get("stock_growth_rate")
        if settings.get("stock_growth_rate") is not None
        else stock_growth_rate,
        bond_growth_rate,
        0.0 if account.account_type == "cryptocurrency" else (
            resolved_bond_allocation
            if resolved_bond_allocation is not None
            else settings.get("bond_allocation")
            if settings.get("bond_allocation") is not None
            else bond_allocation
        ),
        0.0 if account.account_type == "cryptocurrency" else (
            settings.get("dividend_yield")
            if settings.get("dividend_yield") is not None
            else stock_dividend_yield
        ),
    )


def account_fee_rate(account: AccountInfo) -> float:
    """Annual fee rate (expense ratio plus advisory/AUM fee) for one account.

    Null or missing means no fee. Cash accounts never pay one. The API
    bounds the rate to 0-5%; direct engine callers are floored at 0 here.
    """
    if account.account_type in _ZERO_GROWTH_TYPES:
        return 0.0
    rate = (account.investment_settings or {}).get("annual_fee_rate")
    return max(0.0, float(rate)) if rate is not None else 0.0


def account_fee_amount(account: AccountInfo) -> float:
    """Flat annual account fee in today's dollars (indexed with plan inflation).

    Null or missing means none; cash accounts never pay one.
    """
    if account.account_type in _ZERO_GROWTH_TYPES:
        return 0.0
    amount = (account.investment_settings or {}).get("annual_fee_amount")
    return max(0.0, float(amount)) if amount is not None else 0.0


def account_earnings_fee_rate(account: AccountInfo) -> float:
    """Fee as a share (decimal) of the year's positive investment growth."""
    if account.account_type in _ZERO_GROWTH_TYPES:
        return 0.0
    rate = (account.investment_settings or {}).get("fee_percent_of_earnings")
    return max(0.0, float(rate)) if rate is not None else 0.0


def reinvests_income(account: AccountInfo) -> bool:
    """Whether an account's dividends and interest stay in its balance.

    Only a taxable brokerage account can pay them out instead
    (``investment_settings.reinvest_income`` false); every other account,
    and a null setting, reinvests.
    """
    if account.account_type != "taxable_brokerage":
        return True
    return (account.investment_settings or {}).get("reinvest_income") is not False


@dataclass(frozen=True)
class IncomeCharacter:
    """Shares of an account's reinvested income by tax character (sum 1).

    The default is the legacy treatment: every dollar is a qualified dividend.
    """

    qualified_dividends: float = 1.0
    ordinary_dividends: float = 0.0
    treasury_interest: float = 0.0
    municipal_interest: float = 0.0
    other_bond_interest: float = 0.0
    municipal_state_exempt: bool = False

    @property
    def stock_dividends(self) -> float:
        return self.qualified_dividends + self.ordinary_dividends


@dataclass(frozen=True)
class IncomeComposition:
    """Tax character of one account's stock dividends and bond income.

    Built from ``investment_settings``; the defaults reproduce the legacy
    engine (all stock dividends qualified, bond return entirely unrealized
    price change). Character only changes tax in ``_TAXABLE_TYPES`` accounts.

    ``bond_income_yield`` is a share of the bond sleeve for the period being
    modeled. It is carved out of the bond total return, never added to it.
    """

    qualified_dividend_ratio: float = 1.0
    bond_income_yield: float = 0.0
    treasury: float = 0.0
    municipal: float = 0.0
    other: float = 1.0
    municipal_state_exempt: bool = False

    def for_period(self, fraction: float) -> IncomeComposition:
        """Scale the income yield to a partial year, like stock dividends."""
        return replace(self, bond_income_yield=self.bond_income_yield * fraction)

    def bond_income_rate(self, bond_total_return: float) -> float:
        """Income share of the bond sleeve, bounded by the total return.

        Income can never exceed what the sleeve is worth at the end of the
        period, so the price component stays at or above -100%.
        """
        return min(self.bond_income_yield, max(0.0, 1.0 + bond_total_return))

    def character(self, stock_dividend_rate: float, bond_income_rate: float) -> IncomeCharacter:
        """Split income from both sleeves into tax-character shares."""
        total = stock_dividend_rate + bond_income_rate
        if total <= 0.0:
            return IncomeCharacter(
                qualified_dividends=self.qualified_dividend_ratio,
                ordinary_dividends=1.0 - self.qualified_dividend_ratio,
                municipal_state_exempt=self.municipal_state_exempt,
            )
        stock = stock_dividend_rate / total
        bond = bond_income_rate / total
        return IncomeCharacter(
            qualified_dividends=stock * self.qualified_dividend_ratio,
            ordinary_dividends=stock * (1.0 - self.qualified_dividend_ratio),
            treasury_interest=bond * self.treasury,
            municipal_interest=bond * self.municipal,
            other_bond_interest=bond * self.other,
            municipal_state_exempt=self.municipal_state_exempt,
        )


_LEGACY_COMPOSITION = IncomeComposition()
_LEGACY_CHARACTER = IncomeCharacter()


def account_income_composition(account: AccountInfo) -> IncomeComposition:
    """Return the account's income composition; null settings keep legacy.

    The API validates ranges and the mix total. Direct engine callers are
    bounded here so recognized income always equals reinvested income.
    """
    settings = account.investment_settings or {}
    ratio = settings.get("qualified_dividend_ratio")
    bond_yield = settings.get("bond_income_yield")
    mix = settings.get("bond_income_mix") or {}
    parts = [max(0.0, float(mix.get(key) or 0.0)) for key in ("treasury", "municipal", "other")]
    total = sum(parts)
    treasury, municipal, other = (part / total for part in parts) if total > 0 else (0.0, 0.0, 1.0)
    if ratio is None and bond_yield is None and total <= 0 and not settings.get("municipal_state_exempt"):
        return _LEGACY_COMPOSITION
    return IncomeComposition(
        qualified_dividend_ratio=1.0 if ratio is None else min(1.0, max(0.0, float(ratio))),
        bond_income_yield=(0.0 if bond_yield is None or account.account_type == "cryptocurrency"
                           else max(0.0, float(bond_yield))),
        treasury=treasury,
        municipal=municipal,
        other=other,
        municipal_state_exempt=bool(settings.get("municipal_state_exempt")),
    )


@dataclass
class TaxResult:
    federal: float
    state: float = 0.0
    local: float = 0.0
    capital_gains_tax: float = 0.0
    effective_rate: float = 0.0
    marginal_rate: float = 0.0
    # Optional detail fields
    agi: float = 0.0
    taxable_income: float = 0.0
    deduction_used: str = "standard"
    deduction_amount: float = 0.0
    standard_deduction: float = 0.0
    total_tax: float = 0.0
    # Further optional detail fields
    fica_tax: float = 0.0
    niit: float = 0.0
    # Tentative minimum tax (Form 6251 line 9), compared with regular tax.
    amt: float = 0.0
    # The AMT owed: tentative minimum tax above regular and capital gains tax, included in `federal`.
    amt_excess: float = 0.0
    qbi_deduction: float = 0.0
    capital_loss_carryforward: float = 0.0
    taxable_social_security: float = 0.0
    # AGI including net capital gains and qualified dividends (the IRC 62
    # figure); ``agi`` above is the ordinary-income component only.
    modified_agi: float = 0.0
    # IRC 151(d)(5) senior deduction (2025-2028) included in deduction_amount.
    senior_deduction: float = 0.0
    # IRC 103 municipal interest: excluded from AGI but added back for Social
    # Security provisional income (IRC 86(b)(2)(B)), ACA MAGI (IRC
    # 36B(d)(2)(B)) and IRMAA MAGI (42 U.S.C. 1395r(i)(4)(A)).
    tax_exempt_interest: float = 0.0
    # Nonrefundable IRC 24 child tax credit already netted from ``federal``
    # (then ``capital_gains_tax``). Engine-internal; not a snapshot field.
    child_tax_credit: float = 0.0
    # Parts of ``fica_tax`` that IRC 6654 counts as estimated-tax liability:
    # Schedule SE tax and the 0.9% Additional Medicare Tax. Engine-internal.
    self_employment_tax: float = 0.0
    additional_medicare_tax: float = 0.0
    # Internal diagnostics surface through SimulationResult.metadata.warnings;
    # no additional public snapshot or persisted-plan fields are required.
    state_allocation_diagnostics: tuple[str, ...] = ()
    # Local income tax limitations for the selected residence, surfaced the
    # same way. ``local`` above is the city/county/regional tax itself.
    local_tax_diagnostics: tuple[str, ...] = ()
    # State retirement-income subtraction (coastmath.engine.state_retirement_exclusion)
    # already taken in computing ``state``.
    state_retirement_exclusion: float = 0.0
    # State subtraction of federally taxable Social Security
    # (coastmath.engine.state_social_security) already taken in computing ``state``.
    state_social_security_subtraction: float = 0.0
    # Separate state excise on long-term capital gains (Washington), included
    # in ``state``.
    state_capital_gains_excise: float = 0.0
    # Previously state-taxed retirement contributions recovered from this
    # year's distributions (coastmath.engine.state_taxed_basis), subtracted in
    # computing ``state``. Engine-internal, not a snapshot field.
    state_contribution_basis_recovery: float = 0.0
    # Unrecaptured section 1250 gain taxed in the 25% rate group
    # (IRC 1(h)(1)(E)), limited to the net capital gain.
    unrecaptured_section_1250_gain: float = 0.0
    # Projected traditional IRA contributions left out of ``deductions``
    # because of the workplace-plan deduction phase-out (IRC 219(g)).
    # Set by the simulator; engine-internal, not a snapshot field.
    ira_nondeductible_contributions: float = 0.0
    # User tax adjustments (coastmath.engine.tax_adjustments), already reflected in
    # the fields above. Deductions: the user deductions taken on the federal
    # return (above the line, plus itemized ones when itemizing). Credits:
    # user credits used on both returns, including the refunded part
    # ``tax_adjustment_refund``, which ``total_tax`` nets as a payment.
    tax_adjustment_deductions: float = 0.0
    tax_adjustment_credits: float = 0.0
    tax_adjustment_refund: float = 0.0
    tax_adjustment_surcharge: float = 0.0
    # Statutory state deduction rules (opt-in): the evaluator's coverage for
    # the state ("" when not requested) and its federal income tax subtraction.
    state_deduction_coverage: str = ""
    state_federal_tax_subtraction: float = 0.0
    # Plain-language limits of the adjustments and state rules, surfaced like
    # the diagnostics above. Engine-internal.
    tax_adjustment_diagnostics: tuple[str, ...] = ()
    # A country year's normalized regime result (coastmath.engine.intl_bridge.
    # RegimeTax); None in US years. Engine-internal, not a snapshot field.
    regime: object | None = None


# ---------------------------------------------------------------------------
# Plan sub-structures (lightweight engine-internal representations)
# ---------------------------------------------------------------------------

@dataclass
class MilestoneData:
    id: str
    name: str
    trigger_type: str
    trigger_value: float | None = None
    trigger_date: str | None = None
    metric: str | None = None
    expense_multiple: float | None = None
    relative_to_id: str | None = None
    offset_years: int = 0
    conditions: dict | None = None
    resolved_month: int | None = None
    # A switched-off milestone never fires; references treat it as unreached.
    is_active: bool = True


@dataclass
class IncomeData:
    id: str
    name: str
    annual_amount: float
    is_active: bool = True
    start_milestone_id: str | None = None
    end_milestone_id: str | None = None
    growth_rate: float | None = None  # None follows plan wage/SS curve; explicit zero fixes nominal income
    growth_cap: float | None = None
    growth_cap_inflation_linked: bool = False
    withholding_percent: float = 0.0  # decimal fraction (0.20 = 20%); wire/storage format is percent
    start_month: int | None = None
    end_month: int | None = None
    is_social_security: bool = False
    is_earned_income: bool = True
    is_self_employed: bool = False
    owner: str = "self"
    # Social Security only: age benefits begin when no start milestone is set.
    claiming_age: int | None = None
    tax_category: str | None = None
    # Scenario stress overlay only (coastmath.engine.scenario_stress); never
    # persisted or on the wire. ``(pause_start, resume_at, multiplier)`` in
    # fractional calendar years (2027.5 = July 1, 2027): no pay from
    # ``pause_start`` until ``resume_at``, then ``multiplier`` times the amount.
    pay_interruption: tuple[float, float, float] | None = None
    frequency: str = "recurring"
    recurrence_years: int | None = None
    pension_formula: dict | None = None
    # Social Security only. "amount" pays ``annual_amount``; "pia" sizes the
    # benefit from ``pia_monthly`` (plan-start dollars) and the claim date
    # (coastmath.engine.ss_household). ``expected_benefit_percent`` (0-100, None =
    # 100) scales every PIA-basis payment the recipient receives.
    pia_reflects: str = "continued_work"
    covered_years_to_date: int = 35
    ss_benefit_basis: str = "amount"
    pia_monthly: float | None = None
    expected_benefit_percent: float | None = None
    # Engine-only: a synthetic spousal-excess stream paid on this worker
    # stream's record. Never persisted or on the wire.
    ss_worker_income_id: str | None = None
    # Engine-only, spousal-type auxiliary streams (household spousal or
    # divorced spouse): (pool, months of entitlement before the recipient's
    # FRA in the reduction, gross annual before any offset, annual offset).
    # Streams of one entitlement share a pool of earnings-test withheld months
    # for the adjustment at FRA (coastmath.engine.ss_earnings.spousal_arf_factor).
    ss_spousal_reduction: tuple[str, int, float, float] | None = None
    # Engine-only, an auxiliary stream paid as the excess of a larger benefit
    # over the spousal stream ``offset_id``: (offset_id, larger annual, offset
    # annual), plan-start dollars. Withholding from the offset stream raises
    # this stream so the larger benefit stays payable.
    ss_aux_offset: tuple[str, float, float] | None = None
    # Ordered year segments that replace the default growth step in the years
    # they cover (coastmath.engine.income_growth_schedule). Wire format: percent
    # values and dollar amounts as entered. None keeps growth_rate/curve growth.
    growth_schedule: list[dict] | None = None
    # PIA-basis Social Security only: one former spouse's record for divorced
    # and surviving-divorced-spouse benefits (coastmath.engine.ss_divorced).
    ex_spouse: dict | None = None

    def __post_init__(self):
        if self.tax_category is not None:
            self.is_social_security = self.tax_category == "social_security"
            self.is_earned_income = self.tax_category in {"employment", "self_employment"}
            self.is_self_employed = self.tax_category == "self_employment"


@dataclass
class ExpenseData:
    id: str
    name: str
    annual_amount: float
    start_milestone_id: str | None = None
    end_milestone_id: str | None = None
    inflation_linked: bool = True
    is_payroll_deduction: bool = False
    tied_income_id: str | None = None
    specific_funding_source_id: str | None = None
    start_month: int | None = None
    end_month: int | None = None
    category: str | None = None  # "essential" or "discretionary"
    growth_rate: float | None = None
    growth_cap: float | None = None
    growth_cap_inflation_linked: bool = False
    recurrence_years: int | None = None
    recurrence_growth_rate: float = 0.0
    # New fields are appended to preserve positional construction of legacy expenses.
    # After-tax payroll expenses reduce cash but do not create a tax deduction.
    payroll_tax_treatment: str = "pre_tax"
    specific_funding_source_ids: list[str] | None = None
    # Share (0-1) that flexible spending may cut. None means the category
    # decides; read it through flex_spending.discretionary_share.
    discretionary_fraction: float | None = None
    # Qualified higher education expense (IRC 529(c)(3)(B)): 529 withdrawals
    # up to the year's marked amounts are tax free (coastmath.engine.education_savings).
    qualified_education: bool = False
    # Explicit payroll wage-base elections {federal, state, local, fica}; a
    # missing key keeps the payroll_tax_treatment default
    # (coastmath.engine.payroll_elections).
    payroll_tax_elections: dict[str, bool] | None = None


@dataclass
class SpendingRuleThresholdData:
    threshold: float
    reduction: float


@dataclass
class SpendingUpsideData:
    """One upside point: spending rises by ``increase`` (a decimal fraction of
    planned spending) when the portfolio is ``threshold`` above its prior high."""
    threshold: float
    increase: float


@dataclass
class SpendingRulesData:
    flex_threshold: float | None = None
    flex_reduction: float = 0.20
    lookback_years: int = 1
    spending_floor: float = 0.8
    performance_mode: str = "trailing_return"
    interpolation: str = "step"
    thresholds: list[SpendingRuleThresholdData] = field(default_factory=list)
    start_milestone_id: str | None = None
    end_milestone_id: str | None = None
    # Opt-in additions; the defaults keep older documents unchanged.
    upside_thresholds: list[SpendingUpsideData] = field(default_factory=list)
    flex_scope: list[str] = field(default_factory=lambda: ["expenses"])
    surplus_mode: str = "save"


@dataclass
class MatchTierData:
    """One band of an employer matching formula, as decimals.

    ``match_percent`` of the employee's deferrals on the next
    ``up_to_percent_of_pay`` of compensation: tiers stack in order, so
    100%/3% then 50%/2% matches all of the first 3% of pay deferred and half
    of the next 2%.
    """
    match_percent: float
    up_to_percent_of_pay: float


@dataclass
class EmployerMatchData:
    """An employer contribution formula on a payroll (``income_percent``) rule.

    The match follows the employee's actual deferral as a share of the
    year's plan compensation, tier by tier, plus ``nonelective_percent`` of
    compensation paid regardless of deferrals; ``cap_amount`` (today's
    dollars, indexed with plan inflation) then caps the year's total.
    ``true_up`` figures the match on the whole year's deferrals; without it
    the match is figured month by month (see
    :func:`coastmath.engine.waterfall.employer_match_amount`). ``roth`` deposits the
    employer money in the owner's designated Roth account of the same plan
    (SECURE 2.0 sec. 604).
    """
    tiers: list[MatchTierData] = field(default_factory=list)
    cap_amount: float | None = None
    nonelective_percent: float = 0.0
    true_up: bool = True
    roth: bool = False


def employer_match_from_settings(settings: dict | None) -> EmployerMatchData | None:
    """Engine formula from stored/wire settings, whose percents use 0..100."""
    if not settings:
        return None
    cap = settings.get("cap_amount")
    return EmployerMatchData(
        tiers=[MatchTierData(match_percent=float(tier.get("match_percent") or 0) / 100.0,
                             up_to_percent_of_pay=float(tier.get("up_to_percent_of_pay") or 0) / 100.0)
               for tier in settings.get("tiers") or []],
        cap_amount=float(cap) if cap is not None else None,
        nonelective_percent=float(settings.get("nonelective_percent") or 0) / 100.0,
        true_up=settings.get("true_up", True) is not False,
        roth=bool(settings.get("roth", False)),
    )


@dataclass
class PriorityData:
    priority_rank: int
    target_account_id: str | None = None
    max_annual_amount: float | None = None
    priority_type: str | None = None
    source_account_id: str | None = None
    source_income_id: str | None = None
    employee_rate: float = 0.0
    employer_match_rate: float = 0.0
    target_balance: float | None = None
    allocation_mode: str = "remaining"
    allocation_value: float | None = None  # percent 0..100 or annual dollars
    # Roth conversion controls. "fixed" converts up to max_annual_amount;
    # "fill_bracket" converts only the ordinary-income headroom below the top
    # of the federal bracket with rate ``bracket_ceiling_rate`` (decimal).
    conversion_mode: str = "fixed"
    bracket_ceiling_rate: float | None = None
    magi_cap: float | None = None  # today's dollars; indexed with plan inflation
    start_milestone_id: str | None = None
    end_milestone_id: str | None = None
    # Roth IRA contribution rules: nondeductible IRA contribution converted at
    # once. Bypasses the income phaseout; pre-tax IRA balances make the
    # conversion partly taxable under the pro-rata rule.
    backdoor_roth: bool = False
    # Roth conversion / gain harvest rules: size the year's amount from the
    # plan's tax target (coastmath.engine.tax_target) instead of
    # ``bracket_ceiling_rate``/``magi_cap``.
    use_plan_tax_target: bool = False
    # Employer formula for income_percent rules. None keeps the legacy
    # ``employer_match_rate``: a percent of pay paid regardless of deferrals.
    employer_match: EmployerMatchData | None = None
    # "custom" adds ``custom_annual_limit`` (today's dollars, indexed like the
    # IRS limits) as a lower ceiling on the year's contributions to the
    # rule's account. It never raises the IRS limit.
    limit_mode: str = "irs"
    custom_annual_limit: float | None = None
    # ``debt_payment`` rules: the liability that receives the allocation.
    target_liability_id: str | None = None
    # Surplus rules run before every other surplus rule and draw any surplus
    # shortfall from the withdrawal order (coastmath.engine.waterfall
    # .fund_rule_shortfalls). Payroll rules already come off the top
    # of pay, so for them it only rules out ``reduce_employer_contribution``.
    withdraw_if_short: bool = False
    # income_percent rules with a flat ``employer_match_rate``: scale the
    # employer amount by the share of the elected deferral pay could fund.
    reduce_employer_contribution: bool = False
    # ``transfer`` rules: "annual" moves the year's amount once, after the
    # year's growth; "monthly" spreads it over the rule's active months, so
    # the moved money grows in the target from each month on.
    transfer_frequency: str = "annual"

@dataclass
class PayrollContribution:
    target_account_id: str
    employee_amount: float = 0.0
    employer_amount: float = 0.0
    source_income_id: str | None = None
    # Set for after-tax 401(k) rules, which report their limits like
    # surplus rules: the rule's rank, its request and why it was capped.
    priority_rank: int | None = None
    requested_amount: float | None = None
    limited_by: list[str] = field(default_factory=list)
    funding_reasons: list[str] = field(default_factory=list)


@dataclass
class DrawdownEntryData:
    rank: int
    source_account_id: str | None = None


@dataclass
class RealAssetData:
    id: str
    name: str
    current_value: float
    annual_appreciation_rate: float = 0.03
    annual_property_tax: float = 0.0
    annual_maintenance: float = 0.0
    property_tax_rate: float | None = None
    maintenance_rate: float | None = None
    insurance_rate: float | None = None
    sale_year: int | None = None
    sale_month: int = 1
    is_primary_residence: bool = False
    auto_liquidate_on_depletion: bool = False
    liquidation_target_account_id: str | None = None
    adjusted_basis: float | None = None
    # Unclassified legacy assets need review; never assume a deductible loss.
    # "rental" adds Schedule E income, depreciation and passive loss rules
    # (coastmath.engine.real_estate).
    tax_treatment: str = "unspecified"
    # Planned purchase at the start of purchase_month. purchase_price,
    # down_payment_amount and closing_costs are plan-start (today's) dollars;
    # the price grows with annual_appreciation_rate until the purchase.
    # A loan exists when purchase_loan_term_months is set; its rate is an
    # annual decimal (converted from the stored percent, like liabilities).
    purchase_year: int | None = None
    purchase_month: int = 1
    purchase_price: float | None = None
    down_payment_amount: float | None = None
    down_payment_rate: float | None = None
    closing_costs: float = 0.0
    purchase_funding_account_id: str | None = None
    purchase_loan_rate: float | None = None
    purchase_loan_term_months: int | None = None
    # Share of the sale price paid as selling costs (commissions, fees).
    selling_cost_rate: float = 0.0
    # Rental settings (tax_treatment == "rental"). rental_income and
    # rental_expenses are annual plan-start dollars; blank income growth
    # follows inflation. rental_expense_rate replaces rental_expenses as a
    # share of collected rent.
    rental_income: float = 0.0
    rental_income_growth_rate: float | None = None
    rental_expenses: float = 0.0
    rental_expense_rate: float | None = None
    vacancy_rate: float = 0.0
    rental_property_class: str = "residential"
    land_value_rate: float | None = None
    building_basis: float | None = None
    prior_depreciation: float = 0.0
    qbi_eligible: bool = False
    rental_active_participation: bool = True
    suspended_passive_loss: float = 0.0
    # IRC 121 ownership and use start dates for a primary residence.
    owned_since_year: int | None = None
    owned_since_month: int | None = None
    primary_residence_since_year: int | None = None
    primary_residence_since_month: int | None = None
    # Mixed use (rentals only): the share of the property rented out, as a
    # decimal. None means fully rented. Schedule steps are sorted
    # (year, rate) pairs; each applies from its year until the next one.
    rental_use_rate: float | None = None
    rental_use_schedule: tuple[tuple[int, float], ...] = ()


@dataclass
class DebtForgivenessData:
    """One-time cancellation of a loan balance, fired by a year or a milestone.

    ``amount`` None forgives the whole remaining balance, including unpaid
    simple interest. Forgiven debt is cancellation-of-debt income unless the
    plan declares an excluded amount
    (``tax_treatment == "declared_exclusion"``); ``excluded_amount`` None
    declares the whole forgiven amount excluded. The engine never infers an
    exclusion from the loan type.
    """

    year: int | None = None
    milestone_id: str | None = None
    amount: float | None = None
    tax_treatment: str = "taxable"
    excluded_amount: float | None = None
    exclusion_basis: str | None = None


@dataclass
class LiabilityData:
    """Engine view of a loan. ``interest_rate`` is an annual *decimal* (0.055 for
    5.5%); the API/DB contract is percent and is converted by the plan converter
    and the stateless request converter."""

    id: str
    name: str
    principal_balance: float
    interest_rate: float
    term_months: int | None = None
    monthly_payment: float | None = None
    payment_type: str = "fixed"
    extra_payment: float = 0.0
    offset_account_id: str | None = None
    linked_asset_id: str | None = None
    payoff_milestone_id: str | None = None
    forgiveness: DebtForgivenessData | None = None
    # coastmath.engine.amortization.INTEREST_METHODS
    interest_method: str = "monthly"
    # Take the same loan again every N years from the plan start, until
    # ``recurrence_end_year`` (inclusive) or the end milestone is reached.
    recurrence_years: int | None = None
    recurrence_end_year: int | None = None
    recurrence_end_milestone_id: str | None = None


@dataclass
class LiabilityState:
    remaining_balance: float
    name: str = ""
    # Unpaid simple interest (owed, but it earns no interest).
    accrued_interest: float = 0.0


@dataclass
class AssumptionData:
    inflation_rate: float = 0.03
    stock_growth_rate: float = 0.07
    bond_return_rate: float = 0.04
    stock_dividend_yield: float = 0.0
    cash_yield_rate: float = 0.0


@dataclass
class AssumptionCurveData:
    curve_type: str
    mode: str = "fixed"
    fixed_rate: float | None = None
    control_points: list[dict[str, float]] = field(default_factory=list)


@dataclass
class SEPPSettingsData:
    enabled: bool = False
    source_account_id: str | None = None
    method: str = "fixed_amortization"
    start_age: float = 50.0
    interest_rate: float = 0.05
    # A custom yearly amount in nominal dollars. It keeps the 72(t) exemption
    # only when it equals the amount an approved method yields; otherwise it is
    # an ordinary early withdrawal.
    annual_amount: float | None = None


@dataclass
class CashReserveData:
    """Opt-in emergency reserve held in designated accounts.

    ``amount`` is in start-year dollars and is indexed with inflation. The
    reserve is skipped by the normal withdrawal order and is spent only when
    nothing else in the order can fund the shortfall, drawing the listed
    accounts in the listed order.
    """

    account_ids: tuple[str, ...] = ()
    amount: float = 0.0
    #: Each year, move cash above the reserve into the allocation rules.
    sweep_excess: bool = False


@dataclass
class CharityData:
    id: str
    name: str
    entity_type: str  # 'qcd', 'daf', 'direct'
    annual_amount: float
    start_milestone_id: str | None = None
    end_milestone_id: str | None = None
    source_account_id: str | None = None
    # DAF/direct gifts: "cash" (default) or "appreciated_shares", which gives
    # shares from the taxable account ``source_account_id`` at market value.
    funding: str = "cash"


@dataclass
class ResidencyPeriodData:
    # None for a period abroad; ignored when the period's country is not US.
    state_code: str | None
    start_milestone_id: str | None = None
    end_milestone_id: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    rank: int = 0
    # Local income tax selection for this residence (coastmath.engine.local_tax).
    local_tax: dict | None = None
    # Country and region of this residence; None means the plan's.
    country: str | None = None
    region: str | None = None


@dataclass
class EstateSettingsData:
    step_up_basis_on_death: bool = True
    filing_status_after_death: str = "single"
    federal_estate_exemption: float = 13_990_000.0
    state_estate_tax_enabled: bool = False
    state_estate_exemption: float = 0.0
    state_estate_tax_rate: float = 0.0
    # When False the statutory federal basic exclusion schedule is used and
    # ``federal_estate_exemption`` is ignored; when True the value is applied
    # as-is in the year of death (useful for sunset or reform scenarios).
    custom_federal_exemption_enabled: bool = False
    # Portability of the deceased spouse's unused exclusion (DSUE) to the
    # survivor when the partner dies first during the projection.
    portability_election: bool = True
    # Settlement (probate, administration, liquidation) costs deducted from
    # the gross estate before estate tax: fixed dollars plus a share of the
    # gross estate (decimal). Deductible under IRC 2053.
    settlement_cost_fixed: float = 0.0
    settlement_cost_rate: float = 0.0
    # Effective ordinary income tax rate heirs pay on inherited pre-tax
    # balances (income in respect of a decedent), net of the IRC 691(c)
    # deduction for estate tax attributable to those balances.
    heir_income_tax_rate: float = 0.0
    household_lifecycle: str = "legacy_primary_endpoint"
    survivor_social_security_policy: str = "off"
    survivor_social_security_eligibility_confirmed: bool = False
    survivor_social_security_eligibility_source: str | None = None
    # Net legacy detail (decimals). Heirs' capital gains rate on unrealized
    # taxable-account gains, applied only when step-up is off; selling costs
    # on real assets; share of the estate left to charity (IRC 2055).
    heir_capital_gains_rate: float = 0.0
    estate_selling_cost_rate: float = 0.0
    charitable_bequest_rate: float = 0.0
    # First-death basis step-up for joint taxable accounts: the decedent's
    # half (IRC 2040(b)), or both halves in a community property state (IRC
    # 1014(b)(6)). Requires step_up_basis_on_death.
    joint_account_step_up: bool = False


@dataclass
class TransferFlow:
    source_account_id: str
    target_account_id: str
    amount: float
    source_account_name: str | None = None
    target_account_name: str | None = None


@dataclass
class NamedAmount:
    name: str
    amount: float
    category: str | None = None  # for expenses: 'essential'/'discretionary'
    account_id: str | None = None
    account_name: str | None = None
    source: str | None = None  # priority, payroll, employer, default_sink
    priority_rank: int | None = None
    requested_amount: float | None = None
    limited_by: list[str] = field(default_factory=list)
    funding_reasons: list[str] = field(default_factory=list)
    # Expenses with a discretionary percent only: the part of ``amount`` that
    # is discretionary (after any flex cut); the rest is essential.
    discretionary_amount: float | None = None


@dataclass
class CashFlowBreakdown:
    income_sources: list[NamedAmount] = field(default_factory=list)
    gross_income: float = 0.0
    tax_withheld: float = 0.0
    payroll_deductions: float = 0.0
    net_pay: float = 0.0
    tax_delta: float = 0.0  # positive = refund, negative = owed
    early_withdrawal_penalty: float = 0.0
    expenses: list[NamedAmount] = field(default_factory=list)
    # Expenses deducted from pay; ``payroll_deductions`` includes them.
    payroll_expenses: list[NamedAmount] = field(default_factory=list)
    contributions: list[NamedAmount] = field(default_factory=list)
    transfers: list[TransferFlow] = field(default_factory=list)
    drawdowns: list[NamedAmount] = field(default_factory=list)
    # Opt-in IRC 6654 estimated tax (coastmath.engine.estimated_tax). Estimates are
    # federal tax paid during the year; ``tax_delta`` is then the balance at
    # filing after them. The penalty is a separate, nondeductible outflow.
    estimated_tax_payments: float = 0.0
    required_annual_payment: float = 0.0
    underpayment_penalty: float = 0.0


# ---------------------------------------------------------------------------
# PlanData — engine-internal representation of a full financial plan
# ---------------------------------------------------------------------------

@dataclass
class PlanData:
    plan_id: str
    birth_year: int
    filing_status: str
    life_expectancy: int
    start_year: int
    birth_month: int | None = None
    filing_status_changes: list[dict] = field(default_factory=list)
    first_year_fraction: float = 1.0
    milestones: list[MilestoneData] = field(default_factory=list)
    income_streams: list[IncomeData] = field(default_factory=list)
    expenses: list[ExpenseData] = field(default_factory=list)
    priorities: list[PriorityData] = field(default_factory=list)
    drawdown_order: list[DrawdownEntryData] = field(default_factory=list)
    assumptions: AssumptionData = field(default_factory=AssumptionData)
    assumption_curves: list[AssumptionCurveData] = field(default_factory=list)
    accounts: dict[str, AccountInfo] = field(default_factory=dict)
    real_assets: list[RealAssetData] = field(default_factory=list)
    liabilities: list[LiabilityData] = field(default_factory=list)
    spouse_birth_year: int | None = None
    spouse_birth_month: int | None = None
    spouse_life_expectancy: int | None = None
    sepp_settings: SEPPSettingsData | None = None
    cash_reserve: CashReserveData | None = None
    state_code: str | None = None
    # Local income tax selection for ``state_code`` (coastmath.engine.local_tax).
    local_tax: dict | None = None
    residency_periods: list[ResidencyPeriodData] = field(default_factory=list)
    charity_entities: list[CharityData] = field(default_factory=list)
    estate_settings: EstateSettingsData | None = None
    spending_rules: SpendingRulesData | None = None
    tax_settings: dict | None = None
    healthcare_settings: dict | None = None
    # Saved withdrawal strategy (coastmath.engine.withdrawal_strategy); set only
    # when the plan's setting is enabled. An explicit run_simulation
    # withdrawal_strategy argument takes precedence.
    withdrawal_strategy: WithdrawalStrategySpec | None = None
    # Country tax regime (coastmath.engine.intl_regime): ISO country ("XX" =
    # custom), region, display currency and intl settings (benefits, custom
    # regime, wealth and transaction tax overrides).
    tax_country: str = "US"
    tax_region: str | None = None
    currency: str = "USD"
    intl_settings: dict | None = None


# ---------------------------------------------------------------------------
# SimState — mutable state carried across simulation years
# ---------------------------------------------------------------------------

@dataclass
class SimState:
    year: int
    accounts: dict[str, AccountInfo] = field(default_factory=dict)
    real_asset_values: dict[str, float] = field(default_factory=dict)
    inflation_factor: float = 1.0
    triggered_milestones: set[str] = field(default_factory=set)
    failure_year: int | None = None
    roth_conversions_this_year: float = 0.0
    # Calendar-year retirement income by owner and state-exclusion source
    # (coastmath.engine.state_retirement_exclusion.SOURCES plus "social_security").
    retirement_income_this_year: dict[str, dict[str, float]] = field(default_factory=dict)
    # Calendar-year taxable distributions (withdrawals, RMDs, SEPP) by
    # traditional account, for state-taxed contribution basis recovery.
    retirement_distributions_this_year: dict[str, float] = field(default_factory=dict)
    # Unrecovered employee retirement contributions a state taxed when made,
    # by account and taxing state (coastmath.engine.state_taxed_basis).
    state_taxed_basis: dict[str, dict[str, float]] = field(default_factory=dict)
    # Surplus-waterfall deposits into traditional retirement accounts this
    # year, by account (the per-account share of the state add-back).
    waterfall_retirement_contributions_this_year: dict[str, float] = field(default_factory=dict)
    # Gains on real property sales included in capital_gains_this_year; a
    # state capital gains excise (Washington) excludes them.
    real_estate_gains_this_year: float = 0.0
    # Real estate (coastmath.engine.real_estate). The part of real property sale
    # gains that is depreciation (unrecaptured section 1250 gain), net
    # section 1231 losses on rental sales (ordinary), rentals sold this year,
    # depreciation claimed within the plan, suspended passive losses and the
    # cost basis and grown price of planned purchases, all by asset.
    unrecaptured_1250_this_year: float = 0.0
    real_estate_ordinary_loss_this_year: float = 0.0
    disposed_rentals_this_year: set[str] = field(default_factory=set)
    real_estate_depreciation: dict[str, float] = field(default_factory=dict)
    suspended_passive_losses: dict[str, float] = field(default_factory=dict)
    real_asset_basis: dict[str, float] = field(default_factory=dict)
    pending_purchase_values: dict[str, float] = field(default_factory=dict)
    real_asset_purchase_dates: dict[str, tuple[int, int]] = field(default_factory=dict)
    real_estate_warnings: set[str] = field(default_factory=set)
    roth_ledger: object | None = None
    roth_penalty_charged: float = 0.0
    # State additional taxes on early distributions (CA FTB 3805P) for this
    # year: (start month, end month, rate), months 0-12 with exclusive end.
    early_distribution_state_rates: tuple[tuple[float, float, float], ...] = ()
    owner_birth_months: dict[str, int | None] = field(default_factory=dict)
    capital_gains_this_year: float = 0.0
    # Lifetime taxable share of backdoor Roth contributions under the pro-rata rule.
    backdoor_prorata_taxable: float = 0.0
    drawdown_tax_withheld_this_year: float = 0.0
    # Retirement distributions and 10% additional tax from transfer rules this year.
    transfer_income_this_year: float = 0.0
    transfer_penalty_this_year: float = 0.0
    liability_states: dict[str, LiabilityState] = field(default_factory=dict)
    # Surplus applied to loan principal this year (liability id -> amount).
    debt_prepayments: dict[str, float] = field(default_factory=dict)
    # Withdraw-if-short rule amounts this year that neither surplus nor the
    # withdrawal order could fund (not an unfunded expense or a failure).
    rule_funding_shortfall: float = 0.0
    # Reserve accounts and today's reserve target (nominal, this year); None
    # keeps the withdrawal order exactly as configured.
    cash_reserve_accounts: tuple[str, ...] = ()
    cash_reserve_target: float = 0.0
    # This year's cash moved above the reserve into allocation rules
    # (target account -> amount); set by the simulator's sweep.
    swept_reserve_cash: dict[str, float] = field(default_factory=dict)
    # Loans whose one-time forgiveness has already run.
    forgiven_liability_ids: set[str] = field(default_factory=set)
    debt_forgiven_this_year: float = 0.0
    # Cancellation-of-debt income recognized this year (not spendable cash).
    cod_income_this_year: float = 0.0
    sepp_fixed_amount: float | None = None
    # Custom SEPP amount: True when it equals an approved method's payment,
    # False when it is an ordinary early distribution, None when not custom.
    sepp_custom_qualified: bool | None = None
    sepp_underfunded: bool = False
    daf_carryforward: list[tuple[int, float]] = field(default_factory=list)
    # Unused deductions for gifts of appreciated shares (30% limit), by gift year.
    capital_gain_gift_carryforward: list[tuple[int, float]] = field(default_factory=list)
    partner_deceased: bool = False
    partner_death_year: int | None = None
    # Legacy lifecycle: accounts re-owned from the deceased spouse in the death year.
    partner_reowned_account_ids: set[str] = field(default_factory=set)
    primary_deceased: bool = False
    magi_history: dict[int, float] = field(default_factory=dict)
    filing_status_history: dict[int, str] = field(default_factory=dict)
    harvested_gains_this_year: float = 0.0
    withdrawal_strategy_state: object | None = None
    current_filing_status: str | None = None
    return_history: list[float] = field(default_factory=list)
    # Spend-the-leftover mode: this year's surplus cash not yet saved or spent.
    # It pays bills raised by tax settlement before any account is drawn.
    leftover_cash_held: float = 0.0
    transfers: list[TransferFlow] = field(default_factory=list)
    ytd_contributions: dict[str, float] = field(default_factory=dict)
    allocation_flows: list[NamedAmount] = field(default_factory=list)
    ytd_employer_contributions: dict[str, float] = field(default_factory=dict)
    # After-tax (non-Roth) 401(k) contributions: section 415(c) annual
    # additions that use neither the 402(g) deferral limit nor employer room.
    ytd_after_tax_contributions: dict[str, float] = field(default_factory=dict)
    pending_tax_settlements: dict[int, float] = field(default_factory=dict)
    triggered_milestone_years: dict[str, int] = field(default_factory=dict)
    triggered_milestone_months: dict[str, int] = field(default_factory=dict)
    missed_milestone_years: dict[str, int] = field(default_factory=dict)
    milestone_metric_history: list[dict[str, float]] = field(default_factory=list)
    # Completed prior-year spending, annualized over the simulated fraction.
    last_year_expenses: float | None = None
    qualified_dividends_this_year: float = 0.0
    # Other reinvested taxable-account income, by tax character (account
    # investment_settings): nonqualified dividends, U.S. Treasury interest,
    # IRC 103 municipal interest (and the in-state part a state also exempts)
    # and other bond interest. All stay zero under legacy settings.
    ordinary_dividends_this_year: float = 0.0
    treasury_interest_this_year: float = 0.0
    municipal_interest_this_year: float = 0.0
    state_exempt_municipal_interest_this_year: float = 0.0
    other_bond_interest_this_year: float = 0.0
    # Account fees (investment_settings fee fields) charged this year.
    investment_fees_this_year: float = 0.0
    # Taxable-account stock dividends and bond income on opening balances
    # paid to household cash instead of reinvested (reinvest_income false).
    paid_out_dividends_this_year: float = 0.0
    paid_out_bond_interest_this_year: float = 0.0
    # This year's IncomeCharacter per account, used to split income on
    # mid-year contributions and the income withdrawn money never earned.
    income_character: dict[str, IncomeCharacter] = field(default_factory=dict)
    capital_loss_carryforward: float = 0.0
    unfunded_expenses: float = 0.0
    # Shortfalls from specifically funded expenses remain restricted to their
    # selected accounts and must not be recovered from the global order.
    restricted_unfunded_expenses: float = 0.0
    withdrawal_growth_factors: dict[str, float] = field(default_factory=dict)
    withdrawal_dividend_factors: dict[str, float] = field(default_factory=dict)
    withdrawal_growth_adjustment: float = 0.0
    closed_employer_account_ids: set[str] = field(default_factory=set)
    owner_ages: dict[str, int] = field(default_factory=dict)
    compensation_by_owner: dict[str, float] | None = None
    roth_catchup_owners: set[str] = field(default_factory=set)
    hsa_coverage: list[dict] = field(default_factory=list)
    # 415(c) plan accounts funded from self-employment profit: the owner's
    # business is a separate employer from their W-2 jobs.
    self_employment_plan_ids: set[str] = field(default_factory=set)
    # Owner -> share of the calendar year before the engine's modeled
    # Medicare enrollment (0 = enrolled all year); absent = not enrolled.
    hsa_medicare_start: dict[str, float] = field(default_factory=dict)
    coverage_inflation_factor: float = 1.0
    # Modeled share of the current calendar year (partial opening year).
    year_fraction: float = 1.0
    # Remaining modeled qualified medical costs an HSA may reimburse untaxed
    # this year. None (direct engine callers) keeps HSA withdrawals untaxed.
    hsa_medical_allowance: float | None = None
    # The Medicare-premium part of that allowance. Only an HSA whose owner
    # is 65 or older may pay insurance premiums (IRC 223(d)(2)(C)(iv)).
    hsa_medicare_premium_allowance: float = 0.0
    hsa_taxable_distributions_this_year: float = 0.0
    # 529 accounts (coastmath.engine.education_savings): remaining qualified
    # education expenses withdrawals may cover tax free this year (None for
    # direct engine callers keeps every withdrawal untaxed), the earnings
    # share of nonqualified withdrawals (ordinary income), and this year's
    # deposits and qualified withdrawals for the state deduction.
    education_allowance: float | None = None
    education_taxable_earnings_this_year: float = 0.0
    education_contributions_this_year: float = 0.0
    education_qualified_withdrawals_this_year: float = 0.0
    # Accounts whose withdrawal lock blocks voluntary withdrawals this year
    # (coastmath.engine.withdrawal_locks). Their balances are not liquid.
    locked_account_ids: set[str] = field(default_factory=set)
    # Gross deposits into and withdrawals from each account this year
    # (country transaction taxes and account-kind withdrawals).
    deposits_this_year: dict[str, float] = field(default_factory=dict)
    withdrawals_this_year: dict[str, float] = field(default_factory=dict)
    # Country account kinds (coastmath.engine.intl_accounts): this year's resolved
    # kind and early-withdrawal penalty rate by account, lifetime
    # contributions and tax-free withdrawals used, this year's bonus, and tax
    # taken inside the accounts this year.
    intl_kinds: dict[str, object] = field(default_factory=dict)
    intl_penalty_rates: dict[str, float] = field(default_factory=dict)
    intl_lifetime_contributions: dict[str, float] = field(default_factory=dict)
    intl_tax_free_used: dict[str, float] = field(default_factory=dict)
    intl_bonus_this_year: dict[str, float] = field(default_factory=dict)
    intl_account_tax_this_year: float = 0.0
    # Room ledger for kinds whose room carries forward: (owner, ledger key)
    # -> unused room carried into this year; the plan's entered starting room
    # by (owner, kind ref) and first-year prior earned income by owner; and
    # last year's earned income by owner (None in the first year).
    intl_room_carried: dict[tuple[str, str], float] = field(default_factory=dict)
    intl_starting_room: dict[tuple[str, str], float] = field(default_factory=dict)
    intl_entered_prior_income: dict[str, float] = field(default_factory=dict)
    intl_prior_earned_income: dict[str, float] | None = None
    # Indexed cost bases (coastmath.engine.intl_cost_base): None until a year whose
    # regime indexes cost bases; then the deferred gain and indexation of each
    # taxable account and real asset, and this year's split of realized gains.
    # Both values are replaced, never mutated, so a trial can restore them.
    indexed_cost_bases: dict[str, object] | None = None
    capital_gain_split_this_year: object | None = None

    def illiquid_account_ids(self) -> frozenset[str]:
        """Accounts left out of liquid balances this year.

        An account's ``include_in_liquid`` override wins; without one, an
        account is liquid unless it is withdrawal-locked this year.
        """
        return frozenset(
            aid for aid, a in self.accounts.items()
            if a.include_in_liquid is False
            or (a.include_in_liquid is None and aid in self.locked_account_ids))

    def liquid_account_balance(self) -> float:
        """Account balances counted as liquid this year (see ``illiquid_account_ids``)."""
        illiquid = self.illiquid_account_ids()
        return sum(a.balance for aid, a in self.accounts.items() if aid not in illiquid)

    def record_retirement_income(self, owner: str, source: str, amount: float,
                                 account_id: str | None = None) -> None:
        """Add taxable retirement income for state exclusions (see the field).

        An *account_id* also records the distribution against that account.
        """
        if amount:
            by_source = self.retirement_income_this_year.setdefault(owner, {})
            by_source[source] = by_source.get(source, 0.0) + amount
            if account_id is not None:
                self.retirement_distributions_this_year[account_id] = (
                    self.retirement_distributions_this_year.get(account_id, 0.0) + amount)

    def record_transfer(
        self,
        source_account_id: str,
        target_account_id: str,
        amount: float,
        source_account_name: str | None = None,
        target_account_name: str | None = None,
    ) -> None:
        self.transfers.append(TransferFlow(
            source_account_id=source_account_id,
            target_account_id=target_account_id,
            amount=amount,
            source_account_name=source_account_name,
            target_account_name=target_account_name,
        ))

    def portfolio_return_over(self, lookback_years: int) -> float | None:
        """Compound return over last N years. Return None if not enough history."""
        if len(self.return_history) < lookback_years:
            return None
        recent = self.return_history[-lookback_years:]
        compound = 1.0
        for r in recent:
            compound *= (1 + r)
        return compound - 1.0

    def total_liability_balance(self) -> float:
        return sum(ls.remaining_balance + ls.accrued_interest for ls in self.liability_states.values())

    def total_real_asset_value(self) -> float:
        return sum(self.real_asset_values.values())

    def get_real_asset_value(self, asset_id: str) -> float:
        return self.real_asset_values.get(asset_id, 0.0)

    def set_real_asset_value(self, asset_id: str, value: float) -> None:
        self.real_asset_values[asset_id] = value

    def remove_real_asset(self, asset_id: str) -> None:
        self.real_asset_values.pop(asset_id, None)

    def total_net_worth(self) -> float:
        liquid = sum(a.balance for a in self.accounts.values())
        return (liquid + self.total_real_asset_value() - self.total_liability_balance()
                + sum(self.pending_tax_settlements.values()) - self.unfunded_expenses)

    def cash_account(self) -> str:
        """Return a cash destination, retaining surplus even without user accounts."""
        for kind in ("checking", "savings", "taxable_brokerage"):
            for aid, account in self.accounts.items():
                if account.account_type == kind:
                    return aid
        aid = "unallocated_cash"
        self.accounts.setdefault(aid, AccountInfo(0.0, "checking"))
        return aid

    def deposit_to(self, account_id: str, amount: float, *, conversion_taxable: float | None = None) -> None:
        if account_id in self.accounts:
            acct = self.accounts[account_id]
            if amount > 0:
                self.deposits_this_year[account_id] = self.deposits_this_year.get(account_id, 0.0) + amount
            if acct.account_type in ROTH_TYPES:
                ledger(self).deposit(account_id, amount, conversion_taxable)
            acct.balance += amount
            if acct.account_type in _TAXABLE_TYPES:
                opening_basis = (
                    acct.cost_basis
                    if acct.cost_basis is not None
                    else max(acct.balance - amount, 0.0)
                )
                acct.cost_basis = update_cost_basis_on_deposit(amount, opening_basis)
            elif acct.account_type == "five_twenty_nine":
                # Contribution basis; an unknown opening basis is the balance.
                opening_basis = acct.cost_basis if acct.cost_basis is not None else max(acct.balance - amount, 0.0)
                acct.cost_basis = opening_basis + max(0.0, amount)
                self.education_contributions_this_year += max(0.0, amount)

    def withdraw_from(self, account_id: str, amount: float) -> None:
        if account_id in self.accounts:
            acct = self.accounts[account_id]
            if amount > 0:
                self.withdrawals_this_year[account_id] = self.withdrawals_this_year.get(account_id, 0.0) + amount
            if acct.account_type in _TAXABLE_TYPES:
                gain, new_basis = calculate_gain_on_withdrawal(
                    amount, acct.balance, acct.cost_basis,
                )
                if self.indexed_cost_bases is not None:
                    from coastmath.engine.intl_cost_base import (  # noqa: PLC0415 - intl_cost_base imports this module
                        record_sale,
                    )
                    record_sale(self, account_id, amount / acct.balance if acct.balance > 0 else 0.0, gain)
                acct.cost_basis = new_basis
                self.capital_gains_this_year += gain
            elif acct.account_type == "five_twenty_nine" and acct.cost_basis is not None:
                # Basis is recovered pro rata; the earnings share is taxed by
                # the caller (coastmath.engine.waterfall.execute_drawdown).
                _, acct.cost_basis = calculate_gain_on_withdrawal(amount, acct.balance, acct.cost_basis)
            acct.balance -= amount

    def get_balance(self, account_id: str) -> float:
        acct = self.accounts.get(account_id)
        return acct.balance if acct is not None else 0.0

    def reset_investment_income(self) -> None:
        """Start a tax year with no recognized account income."""
        self.qualified_dividends_this_year = 0.0
        self.ordinary_dividends_this_year = 0.0
        self.treasury_interest_this_year = 0.0
        self.municipal_interest_this_year = 0.0
        self.state_exempt_municipal_interest_this_year = 0.0
        self.other_bond_interest_this_year = 0.0

    @property
    def ordinary_investment_income_this_year(self) -> float:
        """Ordinary dividends and taxable interest: ordinary income and NII."""
        return (self.ordinary_dividends_this_year + self.treasury_interest_this_year
                + self.other_bond_interest_this_year)

    @property
    def bond_interest_this_year(self) -> float:
        return (self.treasury_interest_this_year + self.municipal_interest_this_year
                + self.other_bond_interest_this_year)

    def recognize_yield_income(self, account_id: str, amount: float) -> None:
        """Recognize reinvested taxable-account income by its tax character."""
        character = self.income_character.get(account_id, _LEGACY_CHARACTER)
        self.qualified_dividends_this_year += amount * character.qualified_dividends
        self.ordinary_dividends_this_year += amount * character.ordinary_dividends
        self.treasury_interest_this_year += amount * character.treasury_interest
        municipal = amount * character.municipal_interest
        self.municipal_interest_this_year += municipal
        if character.municipal_state_exempt:
            self.state_exempt_municipal_interest_this_year += municipal
        self.other_bond_interest_this_year += amount * character.other_bond_interest

    def reverse_yield_income(self, account_id: str, amount: float) -> None:
        """Remove income that money withdrawn during the year never earned."""
        character = self.income_character.get(account_id, _LEGACY_CHARACTER)
        self.qualified_dividends_this_year = max(
            0.0, self.qualified_dividends_this_year - amount * character.qualified_dividends)
        self.ordinary_dividends_this_year = max(
            0.0, self.ordinary_dividends_this_year - amount * character.ordinary_dividends)
        self.treasury_interest_this_year = max(
            0.0, self.treasury_interest_this_year - amount * character.treasury_interest)
        municipal = amount * character.municipal_interest
        self.municipal_interest_this_year = max(0.0, self.municipal_interest_this_year - municipal)
        if character.municipal_state_exempt:
            self.state_exempt_municipal_interest_this_year = max(
                0.0, self.state_exempt_municipal_interest_this_year - municipal)
        self.other_bond_interest_this_year = max(
            0.0, self.other_bond_interest_this_year - amount * character.other_bond_interest)

    def apply_growth(
        self,
        stock_growth_rate: float,
        bond_growth_rate: float = 0.0,
        bond_allocation: float = 0.0,
        stock_dividend_yield: float = 0.0,
        cash_yield_rate: float = 0.0,
        account_rates: dict[str, tuple[float, float, float, float]] | None = None,
        income_composition: dict[str, IncomeComposition] | None = None,
        fee_year_fraction: float = 1.0,
    ) -> tuple[float, float]:
        """Apply price growth and reinvested yields.

        Returns ``(taxable_dividends, taxable_cash_interest)``. Cash interest
        is returned as spendable income rather than credited here, so the
        simulator's cash-flow allocation cannot double-deposit it. Dividends in
        taxable brokerage accounts increase cost basis because they are
        reinvested after being recognized as current income.  Crypto receives
        price growth but no stock dividend.

        ``income_composition`` holds each account's period composition. Its
        bond income is carved out of the bond total return, so balances are
        unchanged; in taxable accounts that income is recognized by character
        (state accumulators) and raises basis like dividends. Stock dividends,
        qualified or not, are the returned ``taxable_dividends``.

        Account fees (``investment_settings.annual_fee_rate``) use an
        opening-balance convention: ``fee = rate * fee_year_fraction *
        starting balance``, deducted after growth and capped so the balance
        never goes below zero. Money contributed during the year pays no fee
        until the next year's opening balance. Cash accounts pay none. The
        total is recorded in ``investment_fees_this_year``. Two more fee
        types add to it under the same cap: ``annual_fee_amount``, a flat fee
        in today's dollars (indexed by ``inflation_factor`` and prorated by
        ``fee_year_fraction``) charged when the account opens the year with a
        balance, and ``fee_percent_of_earnings``, a share of the period's
        positive growth (price change plus income); a loss year pays none.

        A taxable brokerage account with ``reinvest_income`` false keeps
        its dividends and bond income out of the balance and basis. The
        income is still recognized by character, and the amounts are added
        to ``paid_out_dividends_this_year`` and
        ``paid_out_bond_interest_this_year`` for the household cash flow.

        Fees are not deductible. Investment and advisory fees were
        miscellaneous itemized deductions subject to the 2%-of-AGI floor
        (IRC 67(a)-(b), 212). TCJA (P.L. 115-97, sec. 11045) suspended them
        for 2018-2025; P.L. 119-21 (2025, "OBBBA", sec. 70110) made that
        permanent, now IRC 67(h): "no miscellaneous itemized deduction shall
        be allowed for any taxable year beginning after December 31, 2017."
        The fee therefore never reduces taxable income. In taxable accounts
        it reduces the balance and leaves cost basis unchanged: a modeling
        simplification, since a fee paid by selling shares would realize a
        small gain or loss. In tax-advantaged accounts it reduces only the
        balance.
        """
        taxable_dividends = 0.0
        taxable_cash_interest = 0.0
        qualified_dividends = 0.0
        ordinary_dividends = 0.0
        treasury_interest = 0.0
        municipal_interest = 0.0
        state_exempt_municipal_interest = 0.0
        other_bond_interest = 0.0
        investment_fees = 0.0
        paid_out_dividends = 0.0
        paid_out_bond_interest = 0.0
        for aid, acct in self.accounts.items():
            starting_balance = acct.balance
            if (acct.account_type in _TAXABLE_TYPES or acct.account_type == "five_twenty_nine") \
                    and acct.cost_basis is None:
                # Normalize before price changes, including years with no
                # dividend. A later sale must not erase unrealized gains/losses.
                acct.cost_basis = max(starting_balance, 0.0)
            if acct.account_type in _ZERO_GROWTH_TYPES:
                interest = starting_balance * cash_yield_rate
                taxable_cash_interest += interest
                continue

            acct_stock_growth, acct_bond_growth, acct_bond_allocation, acct_dividend = (
                account_rates.get(aid, (
                    stock_growth_rate,
                    bond_growth_rate,
                    bond_allocation,
                    stock_dividend_yield,
                ))
                if account_rates is not None
                else (
                    stock_growth_rate,
                    bond_growth_rate,
                    bond_allocation,
                    stock_dividend_yield,
                )
            )
            # Crypto is a distinct holding, never a stock/bond portfolio.
            if acct.account_type == "cryptocurrency":
                acct_bond_allocation = 0.0
            composition = (income_composition or {}).get(aid, _LEGACY_COMPOSITION)
            # Bond return is a total return (historical years use the 10-year
            # Treasury total return built in historical_data.py); the income
            # share is separated from it so the ending balance is unchanged.
            bond_income_rate = composition.bond_income_rate(acct_bond_growth)
            price_growth_rate = (
                acct_bond_allocation * (acct_bond_growth - bond_income_rate)
                + (1.0 - acct_bond_allocation) * acct_stock_growth
            )
            dividend = 0.0
            if acct.account_type != "cryptocurrency":
                dividend = (
                    starting_balance
                    * (1.0 - acct_bond_allocation)
                    * acct_dividend
                )
            bond_income = starting_balance * acct_bond_allocation * bond_income_rate
            # Price growth is unrealized and does not change basis. Reinvested
            # taxable dividends and bond income are new basis because tax is
            # recognized now. Bond income is modeled when an account sets
            # ``bond_income_yield``.
            # Without it, bond total returns cannot identify coupon income
            # separately from price movements; simulations warn explicitly.
            earnings = starting_balance * price_growth_rate + dividend + bond_income
            paid_out = not reinvests_income(acct)
            acct.balance += earnings - (dividend + bond_income if paid_out else 0.0)
            fee = 0.0
            fee_rate = account_fee_rate(acct)
            if fee_rate > 0 and starting_balance > 0:
                fee += starting_balance * fee_rate * fee_year_fraction
            fee_amount = account_fee_amount(acct)
            if fee_amount > 0 and starting_balance > 0:
                fee += fee_amount * self.inflation_factor * fee_year_fraction
            earnings_fee_rate = account_earnings_fee_rate(acct)
            if earnings_fee_rate > 0 and earnings > 0:
                fee += earnings * earnings_fee_rate
            if fee > 0:
                fee = min(fee, max(acct.balance, 0.0))
                acct.balance -= fee
                investment_fees += fee
            reinvested = dividend + bond_income
            if acct.account_type in _TAXABLE_TYPES and reinvested > 0:
                if paid_out:
                    paid_out_dividends += dividend
                    paid_out_bond_interest += bond_income
                else:
                    opening_basis = (
                        acct.cost_basis
                        if acct.cost_basis is not None
                        else max(starting_balance, 0.0)
                    )
                    acct.cost_basis = update_cost_basis_on_deposit(reinvested, opening_basis)
                taxable_dividends += dividend
                qualified = dividend * composition.qualified_dividend_ratio
                qualified_dividends += qualified
                ordinary_dividends += dividend - qualified
                treasury_interest += bond_income * composition.treasury
                municipal = bond_income * composition.municipal
                municipal_interest += municipal
                if composition.municipal_state_exempt:
                    state_exempt_municipal_interest += municipal
                other_bond_interest += bond_income * composition.other

        # Qualified dividends are taxable at preferential rates but cannot be
        # erased by capital losses: keep them separate from realized sales.
        self.qualified_dividends_this_year += qualified_dividends
        self.ordinary_dividends_this_year += ordinary_dividends
        self.treasury_interest_this_year += treasury_interest
        self.municipal_interest_this_year += municipal_interest
        self.state_exempt_municipal_interest_this_year += state_exempt_municipal_interest
        self.other_bond_interest_this_year += other_bond_interest
        self.investment_fees_this_year += investment_fees
        self.paid_out_dividends_this_year += paid_out_dividends
        self.paid_out_bond_interest_this_year += paid_out_bond_interest
        return taxable_dividends, taxable_cash_interest

    def snapshot(self) -> dict[str, float]:
        return {aid: acct.balance for aid, acct in self.accounts.items()}


# ---------------------------------------------------------------------------
# YearSnapshot — immutable record of one simulation year
# ---------------------------------------------------------------------------

@dataclass
class HealthcareYear:
    """Health coverage costs recognised in a projection year."""
    aca_covered_adults: int = 0
    # Internal annualized premium segments used again at final MAGI settlement.
    aca_coverage_periods: list[tuple[float, float, float]] = field(default_factory=list)
    aca_household_size: int = 0
    aca_magi: float = 0.0
    aca_fpl_ratio: float = 0.0
    aca_applicable_percentage: float = 0.0
    aca_benchmark_premium: float = 0.0
    aca_gross_premium: float = 0.0
    aca_credit: float = 0.0
    aca_net_premium: float = 0.0  # final gross premium less the allowed credit
    aca_cash_premium: float = 0.0  # premium paid during coverage after advance credit
    aca_eligible: bool = False
    aca_reason: str | None = None
    aca_magi_estimate: float = 0.0  # income used for the advance credit during the year
    aca_credit_advanced: float = 0.0  # credit netted against premiums during the year
    aca_reconciliation: float = 0.0  # final credit minus advanced credit, settled with taxes
    medicare_persons: float = 0.0
    medicare_magi_used: float = 0.0
    medicare_lookback_year: int | None = None
    medicare_lookback_source: str = "none"
    medicare_lookback_filing_status: str | None = None
    medicare_tier: int = 0
    medicare_part_b: float = 0.0
    medicare_irmaa_part_b: float = 0.0
    medicare_irmaa_part_d: float = 0.0
    medicare_part_d_plan: float = 0.0
    medicare_supplement: float = 0.0
    medicare_part_a: float = 0.0
    itemized_medical: float = 0.0
    out_of_pocket: float = 0.0
    long_term_care_gross: float = 0.0
    long_term_care_covered: float = 0.0
    long_term_care: float = 0.0
    person_costs: list[dict] = field(default_factory=list)
    total: float = 0.0


@dataclass
class YearSnapshot:
    year: int
    age: int
    gross_income: float
    taxes: float
    expenses: float
    net_cash_flow: float
    federal_tax: float = 0.0
    state_tax: float = 0.0
    local_tax: float = 0.0
    # State retirement-income subtraction behind ``state_tax``.
    state_retirement_exclusion: float = 0.0
    # State subtraction of federally taxable Social Security behind ``state_tax``.
    ss_earnings_test_withheld: float = 0.0
    # Earnings-test withholding by the owner ("self"/"spouse") whose earnings
    # the test counted, before any auxiliary top-up offsets it.
    ss_earnings_test_withheld_by_earner: dict[str, float] = field(default_factory=dict)
    state_social_security_subtraction: float = 0.0
    # State capital gains excise (Washington) included in ``state_tax``.
    state_capital_gains_excise: float = 0.0
    # User tax adjustments behind ``taxes`` (coastmath.engine.tax_adjustments):
    # federal deductions taken, credits used on both returns (including the
    # refunded part) and surcharges added.
    tax_adjustment_deductions: float = 0.0
    tax_adjustment_credits: float = 0.0
    tax_adjustment_surcharge: float = 0.0
    # Rental properties (coastmath.engine.real_estate): collected rent, cash
    # expenses (operating, property tax and upkeep, loan interest),
    # depreciation, the net amount in AGI after the passive loss rules, and
    # suspended losses carried to next year. Real property sales: gain from
    # depreciation (unrecaptured section 1250 gain). Planned purchases: cash
    # paid (down payment or price, plus closing costs).
    rental_income: float = 0.0
    rental_expenses: float = 0.0
    rental_depreciation: float = 0.0
    rental_taxable_income: float = 0.0
    suspended_passive_losses: float = 0.0
    unrecaptured_section_1250_gain: float = 0.0
    real_estate_purchases: float = 0.0
    # Withdraw-if-short rule amounts within their limits that neither the
    # year's surplus nor the withdrawal order could fund. Reported only; it
    # is not an unfunded expense and does not fail the plan.
    rule_funding_shortfall: float = 0.0
    # Country tax regime (coastmath.engine.intl_regime): the country whose regime
    # taxed the year ("US" for the US path), its tax lines and totals by
    # kind. All are included in taxes; the lines are empty and the totals 0
    # in US years, where the US-only fields carry the tax instead.
    tax_country: str = "US"
    intl_tax_lines: list[dict] = field(default_factory=list)
    national_income_tax: float = 0.0
    regional_income_tax: float = 0.0
    social_contributions: float = 0.0
    wealth_tax: float = 0.0
    transaction_tax: float = 0.0
    benefit_recovery_tax: float = 0.0
    # Tax lines/effective rates use calendar-year income even when cash income
    # covers only the period after a mid-year plan start.
    calendar_year_gross_income: float | None = None
    capital_gains_tax: float = 0.0
    fica_tax: float = 0.0
    niit_tax: float = 0.0
    # AMT owed (part of federal income tax), not the tentative minimum tax.
    amt_tax: float = 0.0
    early_withdrawal_penalty: float = 0.0
    tax_balance: float = 0.0  # positive payable, negative receivable
    unfunded_expenses: float = 0.0
    capital_loss_carryforward: float = 0.0
    accounts: dict[str, float] = field(default_factory=dict)
    real_assets_value: float = 0.0
    liabilities_balance: float = 0.0
    net_worth: float = 0.0
    effective_rate: float = 0.0
    marginal_rate: float = 0.0
    deduction_used: str = "standard"
    deduction_amount: float = 0.0
    standard_deduction: float = 0.0
    flex_spending_reduction: float = 0.0
    # Extra spending a new all-time high allowed, and the surplus cash spent
    # instead of saved (spend-the-leftover mode). Both always present.
    flex_spending_increase: float = 0.0
    leftover_spending: float = 0.0
    investment_growth: float = 0.0
    # Account fees deducted this year; already netted out of investment_growth.
    investment_fees: float = 0.0
    milestones_triggered: list[str] = field(default_factory=list)
    transfers: list[TransferFlow] = field(default_factory=list)
    cash_flow: CashFlowBreakdown | None = None
    healthcare: HealthcareYear | None = None
    harvested_gains: float = 0.0  # gains realised by harvesting rules (no cash movement)
    # Loan balance cancelled this year and the part recognized as income (no cash).
    debt_forgiven: float = 0.0
    debt_forgiveness_taxable: float = 0.0
    # Plan tax target (coastmath.engine.tax_target): the year's room before
    # target-sized strategies ran (None without a target in force), and the
    # gross shortfall withdrawals the blended first pass took.
    tax_target_room: float | None = None
    tax_target_blended_withdrawals: float = 0.0
    # Household asset location (tax_settings.asset_location): each pooled
    # account's bond share this year. Empty in per-account mode.
    bond_allocation_by_account: dict[str, float] = field(default_factory=dict)
    strategy_spending: float | None = None  # withdrawal-strategy spending that replaced planned expenses
    planned_expenses: float | None = None  # the plan's own ordinary expenses that were replaced
    inflation_factor: float | None = None  # start-of-year cumulative inflation; first year 1.0
    # Opening partial year: full-year tax liability less tax already paid
    # before plan start (entered or imputed), including federal, FICA, state,
    # local and penalties. It is signed so an earlier overpayment can be a
    # refund; state payroll costs remain separate expenses. None otherwise.
    post_start_taxes: float | None = None
    # Stable codes for this year's modeling basis, e.g. ``ytd_imputed_pro_rata``.
    warnings: list[str] = field(default_factory=list)
    # Engine-only: accounts not counted as liquid this year, i.e.
    # withdrawal-locked or excluded by their liquid override (not in the API).
    locked_account_ids: frozenset[str] = frozenset()
    # Engine-only: accounts whose liquid override always excludes them.
    liquid_excluded_account_ids: frozenset[str] = frozenset()

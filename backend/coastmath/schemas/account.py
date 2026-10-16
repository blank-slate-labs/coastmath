import uuid
from datetime import date
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from coastmath.engine import intl_bridge
from coastmath.engine.account_types import (
    INDIVIDUAL_ONLY_ACCOUNT_TYPES,
    RETIREMENT_ACCOUNT_TYPES,
    RMD_TYPES,
    ROTH_TYPES,
    RULE_OF_55_TYPES,
    TRADITIONAL_RETIREMENT_TYPES,
)
from coastmath.schemas.amount_frequency import MAX_ANNUAL_AMOUNT
from coastmath.schemas.inheritance_settings import InheritanceSettings
from coastmath.schemas.roth_settings import RothSettings

AccountType = Literal[
    "checking",
    "savings",
    "traditional_401k",
    "roth_401k",
    "traditional_403b",
    "roth_403b",
    "traditional_457b",
    "roth_457b",
    "traditional_401a",
    "traditional_ira",
    "roth_ira",
    "taxable_brokerage",
    "hsa",
    "five_twenty_nine",
    "other",
]


BeneficiaryType = Literal["spouse", "edb", "non_edb"]

#: Account types that keep a cost basis: taxable brokerage (purchase basis)
#: and 529 plans (contribution basis).
BASIS_ACCOUNT_TYPES = frozenset({"taxable_brokerage", "five_twenty_nine"})

#: IRAs, workplace plans (401(k), 403(b), 457(b), 401(a)) and HSAs belong to one
#: person, so they cannot be owned jointly (``INDIVIDUAL_ONLY_ACCOUNT_TYPES``).
JOINT_OWNER_REASON = "IRAs, 401(k)s and HSAs have one owner; choose the primary person or partner."


def coerce_intl_account_type(data: Any) -> Any:
    """Give an account with a country account kind the kind's account type.

    The kind's category decides the stored ``account_type`` (see
    ``coastmath.engine.intl_bridge.CATEGORY_ACCOUNT_TYPES``) so US account rules
    never apply to it. Raises for an unregistered kind, except one left over
    from a retired country: its account keeps its saved type, and the routes
    refuse it as a new or changed kind.
    """
    if not isinstance(data, dict) or not data.get("intl_account_kind"):
        return data
    kind = intl_bridge.account_kind(data["intl_account_kind"])
    if kind is None and intl_bridge.is_retired_kind(data["intl_account_kind"]):
        return data
    if kind is None:
        raise ValueError(f"Unknown account kind {data['intl_account_kind']}")
    if data.get("account_type") != kind.account_type:
        data = {**data, "account_type": kind.account_type}
    return data


def joint_owner_not_allowed(account_type: str, owner: str | None) -> bool:
    """Whether ``owner`` is a joint owner of an individual-only account type."""
    return owner == "joint" and account_type in INDIVIDUAL_ONLY_ACCOUNT_TYPES


#: Allowed rounding when bond income mix fractions are added.
BOND_INCOME_MIX_TOLERANCE = 1e-6


class BondIncomeMix(BaseModel):
    """Tax character of bond income, as fractions that add up to 1."""

    treasury: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    municipal: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    other: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def _fractions_add_up_to_one(self) -> "BondIncomeMix":
        if abs(self.treasury + self.municipal + self.other - 1) > BOND_INCOME_MIX_TOLERANCE:
            raise ValueError("Treasury, municipal and other bond income must add up to 100%")
        return self


#: Bound far above real glide paths; caps stored JSON.
MAX_GLIDE_POINTS = 20


class BondGlidePoint(BaseModel):
    """One point of an account bond glide path, keyed by calendar year or by
    the account owner's age (exactly one of them)."""

    model_config = ConfigDict(extra="forbid")

    year: int | None = Field(default=None, ge=1900, le=2200)
    age: float | None = Field(default=None, ge=0, le=130, allow_inf_nan=False)
    bond_allocation: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def _year_or_age(self) -> "BondGlidePoint":
        if (self.year is None) == (self.age is None):
            raise ValueError("A glide path point needs either a year or an age")
        return self


class AccountInvestmentSettings(BaseModel):
    """Optional fixed account rates; each null field inherits the plan rate.

    The income-composition fields change tax only in taxable accounts. Null
    keeps the legacy treatment: all stock dividends qualified, no separate
    bond income, bond income (when set) taxed as other interest and municipal
    interest taxed by the plan's state.
    """

    stock_growth_rate: float | None = Field(default=None, ge=-0.99, le=1, allow_inf_nan=False)
    dividend_yield: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    bond_allocation: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    #: Share of stock dividends that are qualified (IRC 1(h)(11)); null = 1.
    qualified_dividend_ratio: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    #: Annual bond income as a share of the bond sleeve, carved out of the
    #: bond total return; null = 0.
    bond_income_yield: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    #: Tax character of that bond income; null = all other (taxable) interest.
    bond_income_mix: BondIncomeMix | None = None
    #: Municipal interest is also exempt from the plan's state tax; null = no.
    municipal_state_exempt: bool | None = None
    #: Annual expense ratio plus advisory/AUM fee as a decimal (0.01 = 1%/yr),
    #: charged on the opening balance of accounts with investment growth;
    #: null = no fee. Not deductible (IRC 67(h)); see SimState.apply_growth.
    annual_fee_rate: float | None = Field(default=None, ge=0, le=0.05, allow_inf_nan=False)
    #: Bond share over time, linearly interpolated between points and
    #: constant beyond them; replaces bond_allocation when present. An empty
    #: list clears it. Omitted when unset, so stored settings are unchanged.
    bond_allocation_glide: list[BondGlidePoint] | None = Field(
        default=None, max_length=MAX_GLIDE_POINTS, exclude_if=lambda value: value is None)
    #: Flat annual fee in today's dollars, indexed with plan inflation and
    #: charged when the account opens the year with a balance; null = none.
    annual_fee_amount: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    #: Fee as a decimal share of the year's positive growth (price change
    #: plus income); a loss year pays none. Null = none.
    fee_percent_of_earnings: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    #: Taxable brokerage accounts only: false pays dividends and interest to
    #: household cash instead of reinvesting them (still taxed). Null = true.
    reinvest_income: bool | None = None

    @model_validator(mode="after")
    def _one_glide_basis(self) -> "AccountInvestmentSettings":
        points = self.bond_allocation_glide or []
        if len({point.year is None for point in points}) > 1:
            raise ValueError("Glide path points must all use years or all use ages")
        return self


#: The WithdrawalLock field each ``unlock`` kind requires.
WITHDRAWAL_LOCK_FIELDS = {"age": "age", "milestone": "milestone_id", "year": "year"}


class WithdrawalLock(BaseModel):
    """When voluntary withdrawals from an account may start.

    ``age`` is the owner's age (a joint account uses the primary person);
    halves such as 59.5 are allowed. Exactly the field named by ``unlock``
    is set. RMDs are still taken while an account is locked.
    """

    model_config = ConfigDict(extra="forbid")

    unlock: Literal["age", "milestone", "year"]
    age: float | None = Field(default=None, ge=0, le=120, allow_inf_nan=False)
    milestone_id: uuid.UUID | None = None
    year: int | None = Field(default=None, ge=1900, le=2200)

    @model_validator(mode="after")
    def _exactly_the_unlock_field(self) -> "WithdrawalLock":
        values = {"age": self.age, "milestone_id": self.milestone_id, "year": self.year}
        required = WITHDRAWAL_LOCK_FIELDS[self.unlock]
        if values[required] is None:
            raise ValueError(f"A withdrawal lock that unlocks by {self.unlock} needs {required}")
        extra = [key for key, value in values.items() if value is not None and key != required]
        if extra:
            raise ValueError(f"A withdrawal lock that unlocks by {self.unlock} cannot also set {', '.join(extra)}")
        return self

    @field_serializer("milestone_id")
    def _milestone_id_text(self, value: uuid.UUID | None) -> str | None:
        # Stored in JSONB, which cannot hold a UUID object.
        return str(value) if value is not None else None


class AccountDistributionSettings(BaseModel):
    """Per-account facts that change how distributions are taxed or sized.

    ``separation_year`` is the calendar year the owner separated from the
    employer that sponsors this plan. In or after the year the owner turns
    55 it lifts the 10% additional tax on this plan's distributions (IRC
    72(t)(2)(A)(v)); the engine models the separation as January 1 of that
    year. It is for 401(k), 403(b) and 401(a) plans only, never IRAs.

    ``spouse_sole_beneficiary`` says the owner's spouse is this account's
    sole beneficiary all year. When that spouse is more than 10 years
    younger, required minimum distributions use the Joint Life and Last
    Survivor table (Treas. Reg. 1.401(a)(9)-9(c)(2)); otherwise they use the
    Uniform Lifetime table as before.
    """

    model_config = ConfigDict(extra="forbid")

    separation_year: int | None = Field(default=None, ge=1900, le=2200, exclude_if=lambda value: value is None)
    spouse_sole_beneficiary: bool = Field(default=False, exclude_if=lambda value: not value)


def inherited_year_not_future(value: int | None) -> int | None:
    """An inherited account's original owner has already died: the year cannot be after this one."""
    if value is not None and value > date.today().year:
        raise ValueError(f"Year original owner died can't be after {date.today().year}")
    return value


class AccountCreate(BaseModel):
    withdrawal_lock: WithdrawalLock | None = None
    #: Rule of 55 separation year and the spouse-sole-beneficiary election.
    distribution_settings: AccountDistributionSettings | None = None
    investment_settings: AccountInvestmentSettings | None = None
    inheritance_settings: InheritanceSettings | None = None
    roth_settings: RothSettings | None = None
    inherited_year: int | None = Field(default=None, ge=1900, le=2200)
    name: str = Field(..., max_length=255)
    account_type: AccountType
    #: Accounts hold assets. Debts belong under Property and debt (liabilities).
    #: Past $1 trillion, like a yearly amount, is a typo.
    balance: float = Field(default=0, ge=0, le=MAX_ANNUAL_AMOUNT, description="Current balance; cannot be negative")
    owner: str = "self"
    beneficiary_type: BeneficiaryType = "non_edb"
    cost_basis: float | None = Field(default=None, ge=0, le=MAX_ANNUAL_AMOUNT)
    #: Contributions the state of residence already taxed (traditional
    #: retirement accounts only); recovered from withdrawals in that state.
    state_taxed_basis: float | None = Field(default=None, ge=0, lt=1e13)
    #: Country account kind "<CC>:<kind_id>"; sets account_type from its category.
    intl_account_kind: str | None = Field(default=None, max_length=40, pattern=intl_bridge.KIND_PATTERN.pattern)
    #: Liquid net worth override. Null: liquid unless withdrawal-locked that
    #: year. True always counts the account; false never does.
    include_in_liquid: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _intl_account_type(cls, data: Any) -> Any:
        return coerce_intl_account_type(data)

    _inherited_year_not_future = field_validator("inherited_year")(inherited_year_not_future)

    @model_validator(mode="after")
    def _distribution_settings_fit_the_account(self) -> "AccountCreate":
        settings = self.distribution_settings
        if settings is None:
            return self
        if settings.separation_year is not None and (
                self.account_type not in RULE_OF_55_TYPES or self.inherited_year is not None):
            raise ValueError("A separation year applies only to your own 401(k), 403(b) or 401(a) plan, never an IRA or inherited account")
        if settings.spouse_sole_beneficiary and (
                self.account_type not in RMD_TYPES or self.inherited_year is not None or self.owner not in ("self", "spouse")):
            raise ValueError("The spouse-sole-beneficiary election applies only to a traditional retirement account owned by you or your spouse")
        if settings.separation_year is None and not settings.spouse_sole_beneficiary:
            self.distribution_settings = None
        return self

    @model_validator(mode="after")
    def _null_cost_basis_for_non_taxable(self) -> "AccountCreate":
        # Assign only when set so an unset field stays out of exclude_unset dumps.
        if self.account_type not in TRADITIONAL_RETIREMENT_TYPES and self.state_taxed_basis is not None:
            self.state_taxed_basis = None
        if self.account_type not in ROTH_TYPES:
            self.roth_settings = None
        if self.roth_settings:
            first = self.roth_settings.first_contribution_year
            if first is not None and any(c.year < first for c in self.roth_settings.conversions):
                raise ValueError('A Roth conversion cannot precede the first Roth contribution year')
        # A 529's basis is its contributions (coastmath.engine.education_savings).
        if self.account_type not in BASIS_ACCOUNT_TYPES:
            self.cost_basis = None
        if self.account_type not in RETIREMENT_ACCOUNT_TYPES:
            self.inherited_year = None
            self.inheritance_settings = None
        if self.inherited_year is None:
            self.inheritance_settings = None
        if self.inheritance_settings:
            if self.inheritance_settings.beneficiary_is_minor_child and self.beneficiary_type != 'edb':
                raise ValueError('The minor-child rule requires an eligible designated beneficiary')
            method=self.inheritance_settings.distribution_method
            if method=='spousal_rollover' and self.beneficiary_type!='spouse':
                raise ValueError('Own-account treatment requires a spouse beneficiary')
            if method=='life_expectancy' and self.beneficiary_type=='non_edb' and self.inherited_year >= 2020:
                raise ValueError('Non-eligible beneficiaries are subject to the ten-year deadline')
            if method=='ten_year' and self.beneficiary_type!='non_edb' and self.inheritance_settings.decedent_died_after_rbd and self.account_type.startswith('traditional'):
                raise ValueError('Eligible beneficiaries cannot elect the ten-year rule after the required beginning date')
        return self

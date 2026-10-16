"""Request and response models for /api/ledger: imported transactions and their categories.

Amounts are positive when money leaves the account and negative when it arrives.
"""
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ledger.categories import CATEGORY_IDS
from app.ledger.rules import DIRECTIONS, MATCH_FIELDS, MATCH_TYPES, normalize
from app.ledger.types import ACCOUNT_TYPES

CategoryId = Literal[CATEGORY_IDS]
MatchField = Literal[MATCH_FIELDS]
MatchType = Literal[MATCH_TYPES]
Direction = Literal[DIRECTIONS]
AccountType = Literal[ACCOUNT_TYPES]


class CategoryRead(BaseModel):
    id: str
    role: Literal["spending", "income", "excluded", "unclear"]
    bucket: str | None
    kind: str | None
    label: str


class DateRange(BaseModel):
    start: date
    end: date


class LedgerAccountRead(BaseModel):
    id: uuid.UUID
    provider: str
    institution_name: str
    name: str
    mask: str | None
    account_type: str
    subtype: str | None
    currency: str | None
    status: str
    spending_eligible: bool
    include_in_spending: bool | None
    counts_toward_spending: bool
    coverage: list[DateRange]
    last_read_at: datetime | None
    transaction_count: int
    editable: bool


class LedgerAccountUpdate(BaseModel):
    """Omitted fields are unchanged; a null ``include_in_spending`` restores the default."""
    model_config = ConfigDict(extra="forbid")
    include_in_spending: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    account_type: AccountType | None = None
    subtype: str | None = Field(default=None, max_length=60)

    @model_validator(mode="after")
    def required_values(self):
        for name in ("name", "account_type"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        return self


class LedgerTransactionRead(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    provider: str
    date: date
    posted_date: date | None
    description: str
    merchant_name: str | None
    amount: float
    currency: str | None
    status: str
    provider_category: str | None
    category: str
    category_source: Literal["override", "rule", "llm", "provider", "none"]
    rule_id: uuid.UUID | None
    category_override: str | None
    kind: str
    bucket: str | None
    excluded: bool
    one_time: bool
    recurring: bool


class LedgerTransactionPage(BaseModel):
    transactions: list[LedgerTransactionRead]
    total: int


class TransactionChanges(BaseModel):
    """Omitted fields are unchanged; a null category restores the automatic one."""
    model_config = ConfigDict(extra="forbid")
    category: CategoryId | None = None
    excluded: bool | None = None
    one_time: bool | None = None

    @model_validator(mode="after")
    def flags_are_booleans(self):
        for name in ("excluded", "one_time"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"Choose whether to mark {name.replace('_', '-')}")
        return self


class LedgerTransactionUpdate(TransactionChanges):
    # Also categorize similar transactions: a rule on the merchant, else the description.
    apply_to_similar: bool = False

    @model_validator(mode="after")
    def similar_needs_category(self):
        if self.apply_to_similar and self.category is None:
            raise ValueError("Choose a category to apply to similar transactions")
        return self


class BulkTransactionUpdate(TransactionChanges):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class RuleBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_field: MatchField
    match_type: MatchType = "contains"
    pattern: str = Field(min_length=1, max_length=100)
    source_id: uuid.UUID | None = None
    direction: Direction = "any"
    category: CategoryId

    @field_validator("pattern")
    @classmethod
    def normalized(cls, value: str) -> str:
        value = normalize(value)
        if not value:
            raise ValueError("Enter text to match")
        return value


class RuleCreate(RuleBase):
    pass


class RuleUpdate(BaseModel):
    """Omitted fields are unchanged."""
    model_config = ConfigDict(extra="forbid")
    match_field: MatchField | None = None
    match_type: MatchType | None = None
    pattern: str | None = Field(default=None, min_length=1, max_length=100)
    source_id: uuid.UUID | None = None
    direction: Direction | None = None
    category: CategoryId | None = None

    @field_validator("pattern")
    @classmethod
    def normalized(cls, value: str | None) -> str | None:
        return RuleBase.normalized(value) if value is not None else None

    @model_validator(mode="after")
    def required_values(self):
        for name in ("match_field", "match_type", "pattern", "direction", "category"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        return self


class RuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    match_field: str
    match_type: str
    pattern: str
    source_id: uuid.UUID | None
    direction: str
    category: str
    created_at: datetime
    updated_at: datetime
    # Transactions whose category this rule decides now.
    match_count: int = 0


class LedgerTransactionUpdateRead(BaseModel):
    transaction: LedgerTransactionRead
    rule: RuleRead | None = None


class BulkUpdateRead(BaseModel):
    transactions: list[LedgerTransactionRead]


class MonthReason(BaseModel):
    code: str
    source_ids: list[uuid.UUID]


class MonthRead(BaseModel):
    month: str
    complete: bool
    reasons: list[MonthReason]
    essential: float
    discretionary: float
    income: float
    income_wages: float
    by_category: dict[str, float]
    income_by_category: dict[str, float]
    excluded: dict[str, float]
    one_time: float
    one_time_count: int
    uncategorized_outflow: float
    transaction_count: int
    pending_count: int


class MonthSourceRead(BaseModel):
    id: uuid.UUID
    provider: str
    name: str
    coverage: list[DateRange]
    settled: list[DateRange]
    waiting: bool


class DuplicateRead(BaseModel):
    source_ids: list[uuid.UUID]
    matched: int
    compared: int


class MonthsRead(BaseModel):
    currency: str
    months: list[MonthRead]
    sources: list[MonthSourceRead]
    duplicates: list[DuplicateRead]

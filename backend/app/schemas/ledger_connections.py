"""Request and response models for provider connections and neutral balance links.

``LinkBalanceRequest`` is shared with plug-in providers' own routes.
"""
import math
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.account import AccountCreate, AccountType
from app.schemas.ledger import LedgerAccountRead
from app.schemas.liability import LiabilityCreate


class ProviderRead(BaseModel):
    key: str
    label: str
    link_flow: str
    capabilities: list[str]
    offered: bool
    reason: str | None
    history_days: int | None


class SimpleFINConnectRequest(BaseModel):
    """A SimpleFIN setup token; with ``connection_id`` it reconnects that connection."""
    model_config = ConfigDict(extra="forbid")
    setup_token: str = Field(min_length=1, max_length=4096, repr=False)
    connection_id: uuid.UUID | None = None


class PlaidLinkTokenRequest(BaseModel):
    """With ``connection_id``, a token for Link's update mode on that connection."""
    model_config = ConfigDict(extra="forbid")
    connection_id: uuid.UUID | None = None


class PlaidLinkTokenRead(BaseModel):
    link_token: str
    expiration: datetime | None


class PlaidConnectRequest(BaseModel):
    """Link's ``public_token`` for a new connection, or ``connection_id`` after update mode succeeded."""
    model_config = ConfigDict(extra="forbid")
    public_token: str | None = Field(default=None, min_length=1, max_length=4096, repr=False)
    connection_id: uuid.UUID | None = None
    #: The institution name from Link's success metadata, shown until the first sync names it.
    institution_name: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def one_mode(self):
        if (self.public_token is None) == (self.connection_id is None):
            raise ValueError("Send a public token for a new connection or a connection ID after update mode")
        return self


class PlaidWebhookRead(BaseModel):
    received: bool


class LedgerLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source_id: uuid.UUID
    plan_id: uuid.UUID
    account_id: uuid.UUID | None
    liability_id: uuid.UUID | None
    last_applied_balance: float
    error: str | None


class ConnectionAccountRead(LedgerAccountRead):
    """A synced account with what linking and type confirmation need."""
    balance: float | None
    balance_updated_at: datetime | None
    revision: int
    type_confirmed: bool
    blocked_reason: str | None
    suggested_account_type: AccountType | None
    links: list[LedgerLinkRead]


class LedgerConnectionRead(BaseModel):
    id: uuid.UUID
    provider: str
    label: str
    institution_name: str
    status: str
    error: str | None
    last_success_at: datetime | None
    next_check_at: datetime | None
    created_at: datetime
    accounts: list[ConnectionAccountRead]


class LinkBalanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    plan_id: uuid.UUID
    source_revision: int = Field(ge=1)
    account_id: uuid.UUID | None = None
    liability_id: uuid.UUID | None = None
    new_account: AccountCreate | None = None
    new_liability: LiabilityCreate | None = None
    expected_balance: Decimal | None = None
    acknowledge_duplicate_risk: bool = False
    acknowledge_shared_accounts: bool = False

    @model_validator(mode="after")
    def one_target(self):
        if sum(x is not None for x in (self.account_id, self.liability_id, self.new_account, self.new_liability)) != 1:
            raise ValueError("Choose one existing account/debt or create one new record")
        if (self.account_id or self.liability_id) and self.expected_balance is None:
            raise ValueError("The existing saved balance is required for conflict detection")
        for record in (self.new_account, self.new_liability):
            if record:
                for value in record.model_dump().values():
                    if isinstance(value, (float, Decimal)) and not math.isfinite(value):
                        raise ValueError("Planning amounts must be finite")
        return self

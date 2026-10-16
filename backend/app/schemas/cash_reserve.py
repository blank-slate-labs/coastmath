"""Saved cash-reserve withdrawal policy (plans.cash_reserve_settings).

Opt-in. With the policy off or absent, withdrawals follow the configured
order unchanged. With it on, the designated accounts keep a protected amount
that the normal order skips; it is spent only when nothing else can fund a
shortfall, in the order the accounts are listed here.

``sweep_excess`` (opt-in) also moves cash the reserve accounts hold above
the protected amount into the plan's surplus contribution rules each year
(coastmath.engine.simulator._sweep_excess_reserve_cash).
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


class CashReserveSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    #: Reserve accounts, in the order they are spent as the last resort.
    account_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    #: Protected amount in the plan's start-year dollars (indexed with inflation).
    reserve_amount: float = Field(default=0.0, ge=0, le=1e9)
    #: Each year, move cash above the reserve into the allocation rules.
    #: Omitted while off, so saved settings keep their shape.
    sweep_excess: bool = Field(default=False, exclude_if=lambda value: not value)

    @model_validator(mode="after")
    def check_reserve(self) -> "CashReserveSettings":
        if len(set(self.account_ids)) != len(self.account_ids):
            raise ValueError("A reserve account can be listed only once")
        if self.enabled and (not self.account_ids or self.reserve_amount <= 0):
            raise ValueError("A cash reserve needs at least one account and an amount above zero")
        return self

    @field_serializer("account_ids")
    def _account_ids_as_text(self, value: list[uuid.UUID]) -> list[str]:
        return [str(item) for item in value]

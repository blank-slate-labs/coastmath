"""Saved plan withdrawal strategy (plans.withdrawal_strategy); see coastmath.engine.withdrawal_strategy.

Rates and shares are decimals (0.04 = 4%). Dollar amounts are today's dollars,
indexed with the plan's inflation.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

WithdrawalMethod = Literal[
    "constant_dollar", "constant_percentage", "guyton_klinger", "vanguard_dynamic", "rmd_table",
    "fixed_amount", "one_over_n", "vpw", "kitces_ratchet", "clyatt_95",
]
IncomeHandling = Literal["replace_expenses", "withdrawal_plus_income"]


class WithdrawalBound(BaseModel):
    """A minimum or maximum yearly withdrawal."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    # today_dollars: inflation-indexed dollars; portfolio_percent: decimal share
    # of the portfolio at the start of the year.
    unit: Literal["today_dollars", "portfolio_percent"] = "today_dollars"
    amount: float = Field(ge=0)

    @model_validator(mode="after")
    def _share_at_most_whole(self) -> "WithdrawalBound":
        if self.unit == "portfolio_percent" and self.amount > 1:
            raise ValueError("A portfolio share bound must be a decimal between 0 and 1")
        return self


class WithdrawalStrategySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    enabled: bool = False
    method: WithdrawalMethod = "constant_dollar"
    initial_rate: float = Field(default=0.04, gt=0, le=0.20)
    # Start when this plan milestone triggers or at this age; neither means
    # the plan's first year.
    start_milestone_id: str | None = None
    start_age: int | None = Field(default=None, ge=18, le=110)
    # Guyton-Klinger
    upper_guardrail: float = Field(default=1.20, gt=1, le=3)
    lower_guardrail: float = Field(default=0.80, gt=0, lt=1)
    guardrail_adjustment: float = Field(default=0.10, ge=0, le=0.5)
    guardrail_freeze_years: int = Field(default=15, ge=0, le=60)
    # Vanguard dynamic
    floor: float = Field(default=-0.025, ge=-0.5, le=0)
    ceiling: float = Field(default=0.05, ge=0, le=0.5)
    # Fixed amount
    fixed_amount: float = Field(default=0.0, ge=0)
    fixed_amount_inflation_adjusted: bool = True
    # VPW real return assumptions
    vpw_stock_return: float = Field(default=0.05, ge=-0.1, le=0.15)
    vpw_bond_return: float = Field(default=0.019, ge=-0.1, le=0.15)
    # Kitces ratchet
    ratchet_threshold: float = Field(default=1.50, gt=1, le=5)
    ratchet_increase: float = Field(default=0.10, ge=0, le=1)
    ratchet_cooldown_years: int = Field(default=3, ge=0, le=30)
    # Clyatt: share of last year's withdrawal kept as a floor
    clyatt_floor: float = Field(default=0.95, ge=0, le=1)
    minimum: WithdrawalBound | None = None
    maximum: WithdrawalBound | None = None
    income_handling: IncomeHandling = "replace_expenses"

    @model_validator(mode="after")
    def _consistent(self) -> "WithdrawalStrategySettings":
        if self.start_milestone_id is not None and self.start_age is not None:
            raise ValueError("withdrawal_strategy starts at a milestone or an age, not both")
        if self.enabled and self.method == "fixed_amount" and self.fixed_amount <= 0:
            raise ValueError("withdrawal_strategy.fixed_amount must be positive for the fixed amount method")
        if (self.minimum is not None and self.maximum is not None
                and self.minimum.unit == self.maximum.unit and self.minimum.amount > self.maximum.amount):
            raise ValueError("withdrawal_strategy.minimum must not exceed maximum")
        return self

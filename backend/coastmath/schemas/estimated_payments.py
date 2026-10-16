"""Opt-in federal estimated tax strategy (IRC 6654); see coastmath.engine.estimated_tax."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EstimatedPayments(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    # "off" (also when the setting is absent): no estimates, no penalty.
    # "settle_at_filing": no estimates; the penalty is estimated on the shortfall.
    # "safe_harbor": the required annual payment less withholding, paid in four
    #   equal installments; no penalty.
    # "pay_in_full": projected federal tax less withholding in four installments.
    strategy: Literal["off", "settle_at_filing", "safe_harbor", "pay_in_full"] = "off"
    # First plan year only (the preceding tax year's return); later years use
    # the simulated prior year. Accepted with any strategy.
    prior_year_total_tax: float | None = Field(default=None, ge=0)
    prior_year_agi: float | None = Field(default=None, ge=0)

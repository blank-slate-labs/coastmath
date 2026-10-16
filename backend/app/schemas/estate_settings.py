from typing import Literal

from pydantic import BaseModel, Field, model_serializer

FilingStatusAfterDeath = Literal[
    "single",
    "head_of_household",
    "married_filing_jointly",
    "married_filing_separately",
]


class EstateSettings(BaseModel):
    """Plan-level estate assumptions stored as JSONB.

    ``federal_estate_exemption`` is only applied when
    ``custom_federal_exemption_enabled`` is True; otherwise the engine uses the
    statutory federal basic exclusion schedule in ``data/federal_estate_tax.json``.
    Rates are decimals (0.16 = 16 percent).
    """

    step_up_basis_on_death: bool = True
    filing_status_after_death: FilingStatusAfterDeath = "single"
    federal_estate_exemption: float = Field(default=13_600_000, ge=0)
    custom_federal_exemption_enabled: bool = False
    portability_election: bool = True
    state_estate_tax_enabled: bool = False
    state_estate_exemption: float = Field(default=0, ge=0)
    state_estate_tax_rate: float = Field(default=0, ge=0, le=1)
    # Settlement costs (IRC 2053 deductible) and heir income tax on pre-tax
    # balances; rates are decimals.
    settlement_cost_fixed: float = Field(default=0, ge=0)
    settlement_cost_rate: float = Field(default=0, ge=0, le=0.5)
    heir_income_tax_rate: float = Field(default=0, ge=0, le=1)
    household_lifecycle: Literal[
        "legacy_primary_endpoint", "last_survivor_calendar_year_end"
    ] = "legacy_primary_endpoint"
    survivor_social_security_policy: Literal[
        "off", "claimed_benefit_at_survivor_fra"
    ] = "off"
    survivor_social_security_eligibility_confirmed: bool = False
    survivor_social_security_eligibility_source: str | None = Field(
        default=None, min_length=1, max_length=2000
    )
    # Amount to leave heirs, in today's dollars. Not used by the deterministic
    # projection; Monte Carlo runs that omit a final net worth target use it,
    # inflated to the final projection year.
    legacy_target: float | None = Field(default=None, ge=0, le=1e12)
    # Net legacy detail. Heirs' capital gains rate (decimal) on unrealized
    # taxable-account gains, used only when step-up is off; selling costs on
    # real assets and the share of the estate left to charity, as percents
    # (0-100). Joint taxable accounts step up at the first death (half, or
    # all in a community property state) when joint_account_step_up is set.
    heir_capital_gains_rate: float = Field(default=0, ge=0, le=1)
    estate_selling_cost_percent: float = Field(default=0, ge=0, le=100)
    charitable_bequest_percent: float = Field(default=0, ge=0, le=100)
    joint_account_step_up: bool = False

    @model_serializer(mode="wrap")
    def preserve_omitted_lifecycle(self, handler):
        """Do not add opt-in keys to previously saved estate documents."""
        data = handler(self)
        for name in (
            "household_lifecycle",
            "survivor_social_security_policy",
            "survivor_social_security_eligibility_confirmed",
            "survivor_social_security_eligibility_source",
            "legacy_target",
            "heir_capital_gains_rate",
            "estate_selling_cost_percent",
            "charitable_bequest_percent",
            "joint_account_step_up",
        ):
            if name not in self.model_fields_set:
                data.pop(name, None)
        return data

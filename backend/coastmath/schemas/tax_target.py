"""Plan-level tax target (tax_settings.tax_target); see coastmath.engine.tax_target."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from coastmath.engine.tax_target import plan_bracket_rates

TaxTargetKind = Literal["federal_bracket", "taxable_income", "magi", "irmaa_tier", "aca_fpl_percent"]


class TaxTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    kind: TaxTargetKind
    # federal_bracket: stay within the federal bracket taxed at this rate
    # (decimal). Write paths check it against the plan's federal brackets
    # (bracket_target_error); reads accept any saved rate.
    bracket_rate: float | None = Field(default=None, gt=0, le=1)
    # taxable_income / magi: today's dollars, indexed with plan inflation.
    amount: float | None = Field(default=None, ge=0)
    # irmaa_tier: stay below this surcharge tier (1 = no surcharge at all).
    irmaa_tier: int | None = Field(default=None, ge=1, le=5)
    # aca_fpl_percent: stay at or below this percentage of the poverty line
    # in years with marketplace coverage.
    aca_fpl_percent: float | None = Field(default=None, gt=0, le=1000)
    # Extra ceilings, each also binding when enabled.
    avoid_niit: bool = False
    avoid_irmaa: bool = False
    aca_cap_fpl_percent: float | None = Field(default=None, gt=0, le=1000)

    @model_validator(mode="after")
    def _value_for_kind(self) -> "TaxTarget":
        required = {
            "federal_bracket": "bracket_rate",
            "taxable_income": "amount",
            "magi": "amount",
            "irmaa_tier": "irmaa_tier",
            "aca_fpl_percent": "aca_fpl_percent",
        }[self.kind]
        if getattr(self, required) is None:
            raise ValueError(f"tax_target.{required} is required when kind is '{self.kind}'")
        return self


def _percent(rate: float) -> str:
    return f"{rate * 100:g}%"


def bracket_target_error(tax_settings: dict | None) -> str | None:
    """Why a federal bracket target cannot be saved with these settings, or None.

    The rate must be one of the plan's federal bracket rates: the built-in
    brackets, the custom ``federal_brackets`` or a scheduled change's.
    """
    settings = tax_settings or {}
    target = settings.get("tax_target") or {}
    rate = target.get("bracket_rate")
    if target.get("kind") != "federal_bracket" or rate is None:
        return None
    return _bracket_rate_error(settings, float(rate), "The tax target's")


def bracket_ceiling_error(tax_settings: dict | None, rate: float) -> str | None:
    """Why a Roth conversion rule's own ``bracket_ceiling_rate`` cannot be saved, or None.

    The same check as the plan's bracket target: the rate must be one of the
    plan's federal (ordinary-income) bracket rates. Gain-harvest ceilings are
    capital-gains rates and are not checked here.
    """
    return _bracket_rate_error(tax_settings or {}, float(rate), "The conversion rule's")


def _bracket_rate_error(settings: dict, rate: float, subject: str) -> str | None:
    rates = plan_bracket_rates(settings)
    if any(abs(rate - available) < 1e-9 for available in rates):
        return None
    return (f"{subject} {_percent(rate)} rate is not one of the plan's federal bracket rates "
            f"({', '.join(_percent(available) for available in rates)}).")

"""Local income tax selection shared by plans and residency periods.

A selection names a jurisdiction in ``local_income_tax_2026.json``
or gives custom rates for a locality outside the catalog. The selection
applies only while its residence is active; see ``coastmath.engine.local_tax``.
"""
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from coastmath.engine.local_tax import CUSTOM_JURISDICTION, get_jurisdiction

_CUSTOM_RATES = ("earned_income_rate", "taxable_income_rate", "state_tax_surcharge_rate")


class LocalTaxSelectionRead(BaseModel):
    """Stored selection as returned to clients (not re-validated on read)."""
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    jurisdiction: str = Field(min_length=1, max_length=64)
    # Custom rates only. Earned income is wages plus net self-employment
    # profit; taxable income is the state's taxable income; the surcharge is
    # a share of state income tax (for example an Iowa school district).
    earned_income_rate: float | None = Field(default=None, ge=0, le=0.1)
    taxable_income_rate: float | None = Field(default=None, ge=0, le=0.1)
    state_tax_surcharge_rate: float | None = Field(default=None, ge=0, le=1)

    @model_serializer(mode="wrap")
    def _omit_unset_rates(self, handler):
        # Stored JSONB and responses carry only the rates a selection uses.
        return {key: value for key, value in handler(self).items() if value is not None}


class LocalTaxSelection(LocalTaxSelectionRead):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="after")
    def check_jurisdiction(self) -> "LocalTaxSelection":
        rates = [getattr(self, name) for name in _CUSTOM_RATES]
        if self.jurisdiction == CUSTOM_JURISDICTION:
            if not any(rate for rate in rates):
                raise ValueError("A custom local tax needs at least one positive rate")
        else:
            if get_jurisdiction(self.jurisdiction) is None:
                raise ValueError(f"Unknown local tax jurisdiction {self.jurisdiction!r}")
            if any(rate is not None for rate in rates):
                raise ValueError("Local tax rates apply only to a custom jurisdiction")
        return self


def check_local_tax_state(local_tax: LocalTaxSelectionRead | dict | None, state_code: str | None) -> None:
    """Reject a catalog locality that lies outside the residence's state.

    Custom rates carry no state and apply wherever they are selected.
    """
    if local_tax is None:
        return
    identifier = local_tax["jurisdiction"] if isinstance(local_tax, dict) else local_tax.jurisdiction
    jurisdiction = get_jurisdiction(identifier)
    if jurisdiction is not None and jurisdiction["state_code"] != (state_code or "").strip().upper():
        raise ValueError(
            f"Local tax jurisdiction {identifier!r} is in {jurisdiction['state_code']}, "
            f"not {state_code or 'no state'}"
        )

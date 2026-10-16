"""Household bond target and asset location (tax_settings.asset_location).

See coastmath.engine.bond_location for how the engine applies it.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from coastmath.engine.bond_location import DEFAULT_LOCATION_ORDER

BondAllocationMode = Literal["per_account", "household"]
#: Bounds far above real plans; they cap stored JSON.
MAX_LOCATION_ENTRIES = 200


class AssetLocation(BaseModel):
    """``household`` treats the plan bond allocation as a target for the pooled
    accounts together and places bonds in ``bond_location_order``.

    Order entries are account buckets (``tax_deferred``, ``tax_free``,
    ``taxable``) or account ids; an account named by id takes that position
    instead of its bucket's. Accounts not covered by any entry come last.
    """

    model_config = ConfigDict(extra="forbid")

    bond_allocation_mode: BondAllocationMode = "per_account"
    bond_location_order: list[str] = Field(
        default_factory=lambda: list(DEFAULT_LOCATION_ORDER), max_length=MAX_LOCATION_ENTRIES)
    excluded_account_ids: list[str] = Field(default_factory=list, max_length=MAX_LOCATION_ENTRIES)

    @field_validator("bond_location_order", "excluded_account_ids")
    @classmethod
    def _distinct_entries(cls, entries: list[str]) -> list[str]:
        if any(not entry.strip() or len(entry) > 64 for entry in entries):
            raise ValueError("Entries must be account buckets or account ids")
        if len(set(entries)) != len(entries):
            raise ValueError("Entries must not repeat")
        return entries


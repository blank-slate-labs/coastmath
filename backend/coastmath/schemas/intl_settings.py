"""Country tax regime settings for a plan (``plans.intl_settings``) and code checks.

A plan's ``tax_country`` (ISO 3166-1 alpha-2, ``XX`` for a custom regime)
selects the regime that replaces US tax in the years the household lives
there; ``tax_region`` picks a region inside it and ``currency`` (ISO 4217)
is for display only. Country codes never go into ``state_code``.
"""

from __future__ import annotations

import math
import uuid
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

#: Active ISO 4217 currency codes (List One, 2025), plus the precious-metal
#: and special codes excluded.
ISO_4217_CODES = frozenset("""
AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD
CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD
GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT
LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR
NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP
STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VED VES VND VUV WST XAF XCD
XCG XOF XPF YER ZAR ZMW ZWG
""".split())

#: Bound far above real plans; caps stored JSON and engine work.
MAX_BENEFITS = 20


def normalize_country(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().upper()
    if len(value) != 2 or not value.isalpha():
        raise ValueError("Country must be a two-letter ISO 3166-1 code")
    return value


def normalize_supported_country(value: str | None, field: str = "tax_country") -> str | None:
    """``normalize_country``, refusing a retired country (a plan's or, with ``field="country"``, a period's)."""
    value = normalize_country(value)
    if intl_bridge.is_retired_country(value):
        raise intl_bridge.UnsupportedCountryError(value, field)
    return value


def check_country(code: str, field: str = "tax_country") -> None:
    if intl_bridge.is_retired_country(code):
        raise intl_bridge.UnsupportedCountryError(code, field)
    if not intl_bridge.is_known_country(code):
        raise ValueError(f"No tax regime is available for country {code}")


def check_region(country: str, region: str | None) -> None:
    """A region must belong to its country; the US has none (states are separate)."""
    if region is None:
        return
    info = intl_bridge.country(country)
    if info is None or region not in info.region_codes:
        raise ValueError(f"Region {region} is not a region of {country}")


def normalize_region(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().upper()
    if not value:
        return None
    if len(value) > 8 or not value.replace("-", "").isalnum():
        raise ValueError("Region must be a code of at most 8 letters or digits")
    return value


def normalize_currency(value: str) -> str:
    value = value.strip().upper()
    if value not in ISO_4217_CODES:
        raise ValueError("Currency must be an ISO 4217 code")
    return value


class IntlBenefit(BaseModel):
    """A country benefit paid as yearly income (e.g. a public pension)."""

    model_config = ConfigDict(extra="forbid")

    rule: str = Field(min_length=1, max_length=40)
    owner: Literal["self", "spouse"] = "self"
    start_age: int | None = Field(default=None, ge=0, le=120)
    start_milestone_id: uuid.UUID | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _registered_rule(self) -> IntlBenefit:
        if self.start_age is not None and self.start_milestone_id is not None:
            raise ValueError("Set a benefit's start age or its start milestone, not both")
        validated = intl_bridge.benefit_params(self.rule, self.params)
        normalized = validated.model_dump(mode="json")
        if normalized != self.params:
            self.params = normalized
        return self

    @field_serializer("start_milestone_id")
    def _milestone_text(self, value: uuid.UUID | None) -> str | None:
        # Stored in JSONB, which cannot hold a UUID object.
        return str(value) if value is not None else None


#: Bound on entered room and income amounts (far above any real figure).
MAX_ROOM_AMOUNT = 1_000_000_000.0


class IntlStartingRoom(BaseModel):
    """Unused contribution room at the plan's start for a kind whose room carries forward.

    The room carried in from earlier years, before the first plan year's new
    room.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=4, max_length=40)
    owner: Literal["self", "spouse"] = "self"
    amount: float = Field(ge=0, le=MAX_ROOM_AMOUNT, allow_inf_nan=False)

    @model_validator(mode="after")
    def _ledger_kind(self) -> IntlStartingRoom:
        kind = intl_bridge.account_kind(self.kind)
        if kind is None:
            raise ValueError(f"Unknown account kind {self.kind}")
        if not intl_bridge.carries_room(kind):
            raise ValueError(f"Account kind {self.kind} has no contribution room that carries forward")
        return self


class IntlSettings(BaseModel):
    """``plans.intl_settings``: benefits, a custom regime, tax overrides and contribution room.

    Benefits and starting room of a retired country are dropped on input
    (``intl_bridge.drop_retired_entries``).
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _drop_retired(cls, data: Any) -> Any:
        return intl_bridge.drop_retired_entries(data) if isinstance(data, dict) else data

    benefits: list[IntlBenefit] = Field(default_factory=list, max_length=MAX_BENEFITS)
    # Unused room at the plan's start for kinds whose room carries forward.
    starting_room: list[IntlStartingRoom] = Field(default_factory=list, max_length=MAX_BENEFITS,
                                                  exclude_if=lambda value: not value)
    # Earned income in the year before the plan starts (prior-year percent limits).
    # Keyed by owner ("self", "spouse").
    prior_year_earned_income: dict[Literal["self", "spouse"], float] | None = Field(
        default=None, exclude_if=lambda value: value is None)
    # A RegimeSpec document; used when tax_country is "XX".
    custom_regime: dict[str, Any] | None = None
    # Replace the country's wealth or transaction tax section when present.
    wealth_tax: dict[str, Any] | None = None
    transaction_tax: dict[str, Any] | None = None

    @field_validator("custom_regime")
    @classmethod
    def _valid_custom_regime(cls, value: dict | None) -> dict | None:
        if value is not None:
            intl_bridge.custom_spec(value)
        return value

    @field_validator("wealth_tax", "transaction_tax")
    @classmethod
    def _valid_override(cls, value: dict | None, info) -> dict | None:
        if value is not None:
            intl_bridge.validate_spec_section(info.field_name, value)
        return value

    @field_validator("prior_year_earned_income")
    @classmethod
    def _valid_income(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        for owner, amount in (value or {}).items():
            if not math.isfinite(amount) or amount < 0 or amount > MAX_ROOM_AMOUNT:
                raise ValueError(f"Prior-year earned income for {owner} must be between 0 and {MAX_ROOM_AMOUNT:,.0f}")
        return value

    @field_validator("starting_room")
    @classmethod
    def _one_entry_per_ledger(cls, value: list[IntlStartingRoom]) -> list[IntlStartingRoom]:
        seen = set()
        for entry in value:
            kind = intl_bridge.account_kind(entry.kind)
            key = (entry.owner, intl_bridge.room_ledger_key(kind) if kind is not None else entry.kind)
            if key in seen:
                raise ValueError(f"Starting room for {entry.kind} ({entry.owner}) is entered more than once")
            seen.add(key)
        return value

    def milestone_ids(self) -> set[str]:
        return {str(b.start_milestone_id) for b in self.benefits if b.start_milestone_id is not None}


class RegimeError(ValueError):
    """A plan regime check failure, naming the request field it concerns."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def _period_value(period: Any, name: str) -> Any:
    return period.get(name) if isinstance(period, dict) else getattr(period, name, None)


def check_plan_regimes(
    tax_country: str,
    tax_region: str | None,
    intl_settings: IntlSettings | dict | None,
    residency_periods: list | tuple = (),
) -> None:
    """Cross-field checks: every country and region the plan uses, and a custom regime.

    A residency period without a country uses the plan's country (and the
    plan's region unless it names its own). A period in the US needs a state.
    """
    def check(field: str, country: str, region: str | None) -> None:
        try:
            check_country(country, field)
            check_region(country, region)
        except ValueError as exc:
            raise RegimeError(field, str(exc)) from None

    check("tax_country", tax_country, tax_region)
    used = {tax_country}
    for index, period in enumerate(residency_periods):
        own_country = _period_value(period, "country")
        country = own_country or tax_country
        region = _period_value(period, "region")
        if own_country is None and region is None:
            region = tax_region
        check(f"residency_periods.{index}.country", country, region)
        if country == intl_bridge.US and not _period_value(period, "state_code"):
            raise RegimeError(f"residency_periods.{index}.state_code", "A residency period in the US needs a state")
        used.add(country)
    settings = (IntlSettings.model_validate(intl_settings)
                if isinstance(intl_settings, dict) else intl_settings)
    if intl_bridge.CUSTOM in used and (settings is None or settings.custom_regime is None):
        raise RegimeError("intl_settings.custom_regime",
                          "A custom (Other) country needs a custom regime in intl_settings.custom_regime")


def plan_countries(tax_country: str, residency_periods: list | tuple = ()) -> set[str]:
    """Every country a plan can be taxed in: its own and its residency periods'."""
    return {tax_country, *(_period_value(p, "country") or tax_country for p in residency_periods)}


def check_account_kind(kind_ref: str | None, countries: set[str]) -> None:
    """An account kind must belong to a country the plan (or one of its periods) uses."""
    if kind_ref is None:
        return
    kind = intl_bridge.account_kind(kind_ref)
    if kind is None:
        raise ValueError(f"Unknown account kind {kind_ref}")
    if kind.country not in countries:
        raise ValueError(f"Account kind {kind_ref} belongs to {kind.country}, which this plan does not use")

"""Country registry: discovers packs from data files and rule modules.

A pack is a directory `coastmath/data/tax_regimes/<CC>/` holding one spec per
year (`<YEAR>.json`, a `RegimeSpec` whose `sources` table cites every figure), plus
optional rule modules in `coastmath/engine/intl/rules/`. Nothing central lists packs.
No pack ships today (the tests use one under `tests/fixtures/tax_regimes/`); plans
saved in a removed country are handled by `coastmath.engine.intl_bridge`.

`XX` (Other / custom) is built in: it has no data files and is evaluated from
the plan's own `custom_regime` document. The United States is not listed; US
plans keep the existing federal/state path.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from coastmath.engine.intl import plugins
from coastmath.engine.intl.plugins import (
    register_benefit_rule,
    register_estate_rule,
    register_tax_rule,
)
from coastmath.engine.intl.spec import AccountKindSpec, RegimeSpec
from coastmath.engine.intl.types import BenefitRule, EstateRule

__all__ = [
    "CUSTOM_COUNTRY",
    "CountryInfo",
    "DATA_DIR",
    "account_kinds",
    "benefit_rule",
    "estate_rule",
    "get_country",
    "list_countries",
    "load_spec",
    "register_benefit_rule",
    "register_estate_rule",
    "register_tax_rule",
    "spec_years",
]

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "tax_regimes"
CUSTOM_COUNTRY = "XX"
_CUSTOM_NAME = "Other (custom)"
_YEAR_FILE = re.compile(r"^(\d{4})\.json$")
_COUNTRY_DIR = re.compile(r"^[A-Z]{2}$")


@dataclass(frozen=True, slots=True)
class CountryInfo:
    """Registry metadata, shaped for `GET /tax-regimes`."""

    code: str
    name: str
    # None for `XX`: a custom regime's currency is the plan's own choice.
    currency: str | None
    filing_unit: str | None
    regions: list[dict[str, str]] = field(default_factory=list)
    default_region: str | None = None
    account_kinds: list[dict[str, Any]] = field(default_factory=list)
    benefit_rules: list[dict[str, Any]] = field(default_factory=list)
    spec_years: list[int] = field(default_factory=list)
    approximations: list[str] = field(default_factory=list)
    custom: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "currency": self.currency,
            "filing_unit": self.filing_unit,
            "regions": [dict(region) for region in self.regions],
            "default_region": self.default_region,
            "account_kinds": [dict(kind) for kind in self.account_kinds],
            "benefit_rules": [dict(rule) for rule in self.benefit_rules],
            "spec_years": list(self.spec_years),
            "approximations": list(self.approximations),
            "custom": self.custom,
        }


@cache
def _pack_codes() -> tuple[str, ...]:
    if not DATA_DIR.is_dir():
        return ()
    return tuple(
        sorted(
            entry.name
            for entry in DATA_DIR.iterdir()
            if entry.is_dir() and _COUNTRY_DIR.match(entry.name) and entry.name not in {"US", CUSTOM_COUNTRY}
        )
    )


@cache
def _pack_files(code: str) -> tuple[tuple[int, Path], ...]:
    directory = DATA_DIR / code
    if not directory.is_dir():
        return ()
    files = []
    for entry in directory.iterdir():
        match = _YEAR_FILE.match(entry.name)
        if match:
            files.append((int(match.group(1)), entry))
    return tuple(sorted(files))


@cache
def _load_file(path: Path) -> RegimeSpec:
    plugins.discover()
    return RegimeSpec.model_validate(json.loads(path.read_text()))


def spec_years(code: str) -> list[int]:
    return [year for year, _ in _pack_files(code.upper())]


def load_spec(code: str, year: int) -> RegimeSpec:
    """The pack's spec for `year`: the latest spec year <= `year`, else the earliest.

    Raises KeyError for an unknown country or for `XX` (custom regimes come from
    the plan, not from data).
    """
    files = _pack_files(code.upper())
    if not files:
        raise KeyError(f"no tax regime data for country {code!r}")
    chosen = files[0][1]
    for spec_year, path in files:
        if spec_year <= year:
            chosen = path
    return _load_file(chosen)


def account_kinds(code: str) -> list[AccountKindSpec]:
    """Country-specific account kinds from the latest spec (empty for none or `XX`)."""
    code = code.upper()
    years = spec_years(code)
    if not years:
        return []
    return list(load_spec(code, years[-1]).account_kinds)


def benefit_rule(rule_id: str) -> BenefitRule:
    rules = plugins.benefit_rules()
    if rule_id not in rules:
        raise KeyError(f"unknown benefit rule {rule_id!r}")
    return rules[rule_id]


def estate_rule(code: str) -> EstateRule | None:
    return plugins.estate_rules().get(code.upper())


def _custom_info() -> CountryInfo:
    return CountryInfo(
        code=CUSTOM_COUNTRY,
        name=_CUSTOM_NAME,
        currency=None,
        filing_unit=None,
        custom=True,
        approximations=[
            "A custom regime is evaluated exactly as entered; CoastMath does not check it "
            "against any country's law.",
        ],
    )


@cache
def _country_info(code: str) -> CountryInfo:
    years = spec_years(code)
    latest = load_spec(code, years[-1])
    rules = plugins.benefit_rules()
    benefit_rows = []
    for rule_id in latest.benefit_rules:
        rule = rules[rule_id]
        benefit_rows.append(
            {
                "id": rule.id,
                "label": rule.label,
                "params_schema": rule.params_model.model_json_schema(),
            }
        )
    approximations: list[str] = []
    for year in years:
        for note in load_spec(code, year).meta.approximations:
            if note not in approximations:
                approximations.append(note)
    return CountryInfo(
        code=code,
        name=latest.meta.name,
        currency=latest.meta.currency,
        filing_unit=latest.meta.filing_unit,
        regions=[{"code": region.code, "name": region.name} for region in latest.meta.regions],
        default_region=latest.meta.default_region,
        account_kinds=[
            {"id": f"{code}:{kind.id}", "label": kind.label, "category": kind.category}
            for kind in latest.account_kinds
        ],
        benefit_rules=benefit_rows,
        spec_years=years,
        approximations=approximations,
    )


def list_countries() -> list[CountryInfo]:
    """Every pack country (sorted by code) followed by `XX`."""
    return [*(_country_info(code) for code in _pack_codes()), _custom_info()]


def get_country(code: str) -> CountryInfo | None:
    code = code.upper()
    if code == CUSTOM_COUNTRY:
        return _custom_info()
    if code not in _pack_codes():
        return None
    return _country_info(code)

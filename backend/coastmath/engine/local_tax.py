"""Local (city, county and regional) personal income taxes on residents.

Rates and rules: ``coastmath/data/local_income_tax_2026.json``. Sources and
limitations: ``_sources`` in ``local_income_tax_2026.json``.

A residence (the plan default or a residency period) selects a catalog
jurisdiction or custom rates. A jurisdiction is a list of components, each
applying a rate, brackets or a fixed amount to one base:

``state_taxable_income``
    The engine's taxable income for the resident state. State-layer
    simplifications carry into this base, as they do into state tax.
``state_income_tax``
    The engine's state income tax (a surcharge base).
``earned_income``
    Medicare wages (traditional 401(k) deferrals included, section 125
    salary reductions excluded) plus positive net self-employment profit.
``taxable_earned_income``
    Federal taxable wages (W-2 box 1, after pre-tax payroll deductions) plus
    positive net self-employment profit.
``gross_wages``
    Wages before any employee pre-tax deduction.
``self_employment``
    Positive net self-employment profit.
``federal_agi``
    Federal AGI including net capital gains and dividends.
``michigan_city_income``
    Federal AGI less taxable Social Security, pensions, annuities and
    retirement-plan distributions (the Detroit resident return method).
``philadelphia_unearned_income``
    Dividends, investment income streams and non-employer annuities.

A ``credit`` component reduces its jurisdiction's tax, never below zero.
Brackets are marginal unless ``method`` is ``tiered``, where the bracket
containing the whole base sets one rate for all of it. ``rate`` may be a
schedule keyed by the first tax year each rate applies. ``from_year`` and
``through_year`` bound a component to the years it is in effect.

Taxes owed because of work location rather than residence (nonresident wage
taxes, occupational license and head taxes) are not modeled. The residence
resolved for a year applies to the whole year, as the state layer does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CUSTOM_JURISDICTION = "custom"

_DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "local_income_tax_2026.json"
_CATALOG: dict = json.loads(_DATA_FILE.read_text())

# Custom selection field -> component base.
_CUSTOM_BASES = {
    "earned_income_rate": "earned_income",
    "taxable_income_rate": "state_taxable_income",
    "state_tax_surcharge_rate": "state_income_tax",
}


def catalog_tax_year() -> int:
    return int(_CATALOG["tax_year"])


def get_jurisdiction(identifier: str) -> dict | None:
    """Return the catalog entry for ``identifier`` (with its id), or None."""
    entry = _CATALOG["jurisdictions"].get(identifier)
    return None if entry is None else {"id": identifier, **entry}


@lru_cache(maxsize=1)
def list_jurisdictions() -> tuple[dict, ...]:
    """Catalog entries ordered by state, then name."""
    entries = (get_jurisdiction(identifier) for identifier in _CATALOG["jurisdictions"])
    return tuple(sorted(entries, key=lambda entry: (entry["state_code"], entry["name"])))


@dataclass(frozen=True)
class LocalIncome:
    """Calendar-year income by the categories local tax bases distinguish."""

    wages: float = 0.0  # gross compensation before employee pre-tax deductions
    medicare_wages: float | None = None  # wages less section 125 reductions; None = wages
    taxable_wages: float | None = None  # wages less pre-tax payroll deductions; None = wages
    self_employment: float = 0.0  # net business profit
    dividends: float = 0.0
    investment_income: float = 0.0  # investment income streams
    # U.S. Treasury interest included in federal AGI. Political subdivisions
    # cannot tax it (31 U.S.C. 3124(a)).
    us_obligation_interest: float = 0.0
    annuity_income: float = 0.0
    pension_income: float = 0.0
    retirement_distributions: float = 0.0  # IRA/401(k) withdrawals, RMDs, SEPP, conversions

    @property
    def earned_income(self) -> float:
        medicare = self.wages if self.medicare_wages is None else self.medicare_wages
        return max(0.0, medicare) + max(0.0, self.self_employment)

    @property
    def taxable_earned_income(self) -> float:
        taxable = self.wages if self.taxable_wages is None else self.taxable_wages
        return max(0.0, taxable) + max(0.0, self.self_employment)


@dataclass(frozen=True)
class LocalTaxContext:
    state_code: str | None
    filing_status: str
    tax_year: int
    state_taxable_income: float
    state_income_tax: float
    federal_agi: float  # including net capital gains and dividends
    taxable_social_security: float = 0.0
    persons: int = 1  # taxpayer, and spouse on a joint return
    aged_persons: int = 0
    # Calendar-anchored index for amounts the catalog marks as indexed.
    index_factor: float = 1.0


@dataclass(frozen=True)
class LocalTaxResult:
    amount: float = 0.0
    diagnostics: tuple[str, ...] = ()


def _base_amount(base: str, income: LocalIncome, context: LocalTaxContext) -> float:
    if base == "state_taxable_income":
        return max(0.0, context.state_taxable_income)
    if base == "state_income_tax":
        return max(0.0, context.state_income_tax)
    if base == "earned_income":
        return income.earned_income
    if base == "taxable_earned_income":
        return income.taxable_earned_income
    if base == "gross_wages":
        return max(0.0, income.wages)
    if base == "self_employment":
        return max(0.0, income.self_employment)
    if base == "federal_agi":
        return max(0.0, context.federal_agi)
    if base == "michigan_city_income":
        return max(0.0, context.federal_agi - context.taxable_social_security
                   - income.pension_income - income.annuity_income
                   - income.retirement_distributions - income.us_obligation_interest)
    if base == "philadelphia_unearned_income":
        return max(0.0, income.dividends + income.investment_income + income.annuity_income)
    raise ValueError(f"Unknown local tax base {base!r}")


def _for_status(value, filing_status: str):
    """Pick a per-filing-status value; single is the fallback."""
    if isinstance(value, dict) and ("single" in value or filing_status in value):
        return value.get(filing_status, value["single"])
    return value


def _for_year(value, tax_year: int):
    """Pick from a schedule keyed by first tax year; earlier years use the first entry."""
    if not isinstance(value, dict):
        return value
    years = sorted(int(year) for year in value)
    chosen = max((year for year in years if year <= tax_year), default=years[0])
    return value[str(chosen)]


def _brackets(rows: list, factor: float) -> list[tuple[float, float]]:
    return [(float("inf") if upper is None else float(upper) * factor, float(rate))
            for upper, rate in rows]


def _apply_brackets(amount: float, brackets: list[tuple[float, float]], method: str) -> float:
    if amount <= 0:
        return 0.0
    if method == "tiered":
        rate = next(rate for upper, rate in brackets if amount <= upper)
        return amount * rate
    tax, lower = 0.0, 0.0
    for upper, rate in brackets:
        if amount <= lower:
            break
        tax += (min(amount, upper) - lower) * rate
        lower = upper
    return tax


def _in_effect(component: dict, tax_year: int) -> bool:
    return (int(component.get("from_year", tax_year)) <= tax_year
            <= int(component.get("through_year", tax_year)))


def _component_amount(component: dict, income: LocalIncome, context: LocalTaxContext) -> float:
    if not _in_effect(component, context.tax_year):
        return 0.0
    factor = context.index_factor if component.get("indexed", False) else 1.0
    status = context.filing_status
    base = _base_amount(component["base"], income, context)
    limit = component.get("income_limit")
    if limit is not None:
        measure = _base_amount(component.get("income_limit_base", component["base"]), income, context)
        if measure > float(_for_status(limit, status)) * factor:
            return 0.0
    minimum = component.get("minimum_base")
    if minimum is not None and base <= float(_for_status(minimum, status)) * factor:
        return 0.0
    if "amount" in component:
        return float(_for_status(component["amount"], status)) * factor
    exemptions = context.persons + (context.aged_persons if component.get("aged_exemption") else 0)
    taxable = max(0.0, base - float(component.get("exemption_per_person", 0.0)) * factor * exemptions)
    if "brackets" in component:
        rows = _for_year(_for_status(component["brackets"], status), context.tax_year)
        return _apply_brackets(taxable, _brackets(rows, factor), component.get("method", "marginal"))
    return taxable * float(_for_year(component["rate"], context.tax_year))


def _components(selection: dict) -> tuple[str, list[dict], tuple[str, ...]]:
    """Resolve a selection to (display name, components, limitation notes)."""
    if selection["jurisdiction"] == CUSTOM_JURISDICTION:
        components = [
            {"label": field, "base": base, "rate": float(selection[field])}
            for field, base in _CUSTOM_BASES.items() if selection.get(field)
        ]
        return "Custom local tax", components, ()
    jurisdiction = get_jurisdiction(selection["jurisdiction"])
    if jurisdiction is None:
        raise ValueError(f"Unknown local tax jurisdiction {selection['jurisdiction']!r}")
    return jurisdiction["name"], jurisdiction["components"], tuple(jurisdiction.get("limitations", ()))


def calculate_local_tax(
    selection: dict | None,
    income: LocalIncome,
    context: LocalTaxContext,
) -> LocalTaxResult:
    """Resident local income tax for one calendar year.

    A catalog jurisdiction outside the resident state yields no tax and a
    diagnostic; the plan schemas reject that combination on input, so this
    guards engine callers that bypass them.
    """
    if not selection:
        return LocalTaxResult()
    name, components, limitations = _components(selection)
    jurisdiction = get_jurisdiction(selection["jurisdiction"])
    if jurisdiction is not None and jurisdiction["state_code"] != context.state_code:
        return LocalTaxResult(diagnostics=(
            f"{name} local income tax applies only to {jurisdiction['state_code']} residents; "
            f"it is not calculated for a {context.state_code or 'no-state'} residence.",
        ))
    tax = credits = 0.0
    for component in components:
        amount = _component_amount(component, income, context)
        if component.get("kind") == "credit":
            credits += amount
        else:
            tax += amount
    return LocalTaxResult(amount=max(0.0, tax - credits), diagnostics=limitations)

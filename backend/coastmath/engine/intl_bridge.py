"""Adapter between the planner and the country tax regime package.

``coastmath.engine.intl`` (spec, registry, evaluator and the country rule modules)
is pure and knows nothing about plans. Everything the planner needs from it
goes through this module, so schemas, routes and the simulator depend on one
small surface:

- the registry, normalized into plain frozen dataclasses (countries, regions,
  account kinds, benefit rules);
- validation of benefit parameters, a custom regime and the wealth and
  transaction tax overrides through the package's own models;
- construction of the evaluator's input types and evaluation of one year.

Tests install a stand-in package with :func:`use_package`. When the package
is not installed, no country other than the US is known.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from pydantic import TypeAdapter

US = "US"
#: "Other": a regime the user describes (intl_settings.custom_regime).
CUSTOM = "XX"
ACCOUNT_CATEGORIES = ("cash", "taxable", "tax_deferred", "tax_free")
#: Persisted account_type for a country account kind, by its category. The
#: US rules keyed on account_type (limits, RMDs, 72(t), Roth ordering, SEPP)
#: never match these, so only the kind's own rules apply.
CATEGORY_ACCOUNT_TYPES = {
    "cash": "savings",
    "taxable": "taxable_brokerage",
    "tax_deferred": "other",
    "tax_free": "other",
}
KIND_PATTERN = re.compile(r"^([A-Z]{2}):([a-z0-9_]{1,37})$")

# The stand-in package installed by `use_package`, or None for the real one.
_override = SimpleNamespace(package=None)


def use_package(namespace: Any) -> None:
    """Install a stand-in package (tests); ``None`` restores the real one."""
    _override.package = namespace


def package() -> Any:
    """The regime package as a namespace (types, spec, registry, evaluator), or None."""
    if _override.package is not None:
        return _override.package
    try:
        from coastmath.engine.intl import (  # noqa: PLC0415 - the regime package is optional; without it only the US is known
            evaluator,
            registry,
            spec,
            types,
        )
    except ImportError:
        return None
    return SimpleNamespace(evaluator=evaluator, registry=registry, spec=spec, types=types)


def _require() -> Any:
    pkg = package()
    if pkg is None:
        raise ValueError("Country tax regimes are not available on this server.")
    return pkg


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def _value(item: Any) -> Any:
    """An enum member's value, or the item itself."""
    return getattr(item, "value", item)


# ---------------------------------------------------------------------------
# Registry, normalized
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegionInfo:
    code: str
    name: str


@dataclass(frozen=True)
class CountryInfo:
    code: str
    name: str
    # None for "XX": a custom regime's currency and filing unit are its own.
    currency: str | None
    filing_unit: str | None
    regions: tuple[RegionInfo, ...] = ()
    benefit_rules: tuple[str, ...] = ()
    spec_years: tuple[int, ...] = ()
    approximations: tuple[str, ...] = ()
    # The region a new plan or move starts in (None: the first region).
    default_region: str | None = None
    # True for "XX", the regime the user describes.
    custom: bool = False

    @property
    def region_codes(self) -> frozenset[str]:
        return frozenset(region.code for region in self.regions)


def _country_info(meta: Any, registry: Any) -> CountryInfo | None:
    if isinstance(meta, str):
        meta = _lookup_country(registry, meta)
    code = _get(meta, "code")
    if not code:
        return None
    regions = tuple(
        RegionInfo(code=str(_get(region, "code", region)), name=str(_get(region, "name", _get(region, "code", region))))
        for region in (_get(meta, "regions") or ())
    )
    rules = tuple(str(_get(rule, "id", rule)) for rule in (_get(meta, "benefit_rules") or ()))
    currency = _get(meta, "currency")
    filing_unit = _get(meta, "filing_unit")
    return CountryInfo(
        code=str(code).upper(),
        name=str(_get(meta, "name", code)),
        currency=str(currency) if currency else None,
        filing_unit=str(_value(filing_unit)) if filing_unit else None,
        regions=regions,
        benefit_rules=rules,
        spec_years=tuple(int(year) for year in (_get(meta, "spec_years") or ())),
        approximations=tuple(str(text) for text in (_get(meta, "approximations") or ())),
        default_region=_get(meta, "default_region"),
        custom=bool(_get(meta, "custom", str(code).upper() == CUSTOM)),
    )


def _lookup_country(registry: Any, code: str) -> Any:
    try:
        return registry.get_country(code)
    except (KeyError, ValueError, LookupError):
        return None


def countries() -> dict[str, CountryInfo]:
    """Every registered country regime except the US, keyed by code."""
    pkg = package()
    if pkg is None:
        return {}
    result = {}
    for meta in pkg.registry.list_countries():
        info = _country_info(meta, pkg.registry)
        if info is not None and info.code != US:
            result[info.code] = info
    return dict(sorted(result.items()))


def country(code: str | None) -> CountryInfo | None:
    if not code or code == US:
        return None
    return countries().get(code)


def is_known_country(code: str | None) -> bool:
    return code == US or country(code) is not None


#: Countries whose bundled tax packs were removed. A plan saved with one still
#: loads, so it can be switched, but it cannot be created or run.
RETIRED_COUNTRIES: dict[str, str] = {
    "AU": "Australia",
    "BE": "Belgium",
    "BR": "Brazil",
    "CA": "Canada",
    "CH": "Switzerland",
    "CN": "China",
    "DE": "Germany",
    "ES": "Spain",
    "GB": "United Kingdom",
    "HK": "Hong Kong",
    "IL": "Israel",
    "NL": "Netherlands",
    "NO": "Norway",
    "NZ": "New Zealand",
    "SG": "Singapore",
}


def is_retired_country(code: str | None) -> bool:
    """A removed country that no installed pack provides again."""
    return bool(code) and code in RETIRED_COUNTRIES and country(code) is None


class UnsupportedCountryError(ValueError):
    """A plan, or one of its residency periods, uses a retired country."""

    def __init__(self, code: str, field: str = "tax_country"):
        name = RETIRED_COUNTRIES.get(code, code)
        if field == "tax_country":
            message = (f"This plan's country ({name}) is no longer supported. "
                       "Switch the plan to United States or Other (custom).")
        else:
            message = (f"A residency period's country ({name}) is no longer supported. "
                       "Switch it to United States or Other (custom).")
        super().__init__(message)
        self.code = code
        self.field = field


def check_supported_countries(plan: Any) -> None:
    """Raise :class:`UnsupportedCountryError` for a plan (or period) in a retired country.

    Accepts engine plan data, a stateless plan request or a saved plan.
    """
    if is_retired_country(_get(plan, "tax_country")):
        raise UnsupportedCountryError(_get(plan, "tax_country"))
    for index, period in enumerate(_get(plan, "residency_periods") or ()):
        code = _get(period, "country")
        if is_retired_country(code):
            raise UnsupportedCountryError(code, f"residency_periods.{index}.country")


def is_retired_kind(ref: Any) -> bool:
    """An account kind, benefit rule or room entry (``"<CC>:<id>"``) of a retired country."""
    return isinstance(ref, str) and ":" in ref and is_retired_country(ref.split(":", 1)[0])


def drop_retired_entries(settings: dict | None) -> dict | None:
    """``intl_settings`` without benefits or starting room of a retired country.

    Their rules and kinds no longer exist, so the entries could never apply;
    dropping them lets a plan saved in a removed country switch to another one.
    """
    if not isinstance(settings, dict):
        return settings
    result = dict(settings)
    for key, ref_key in (("benefits", "rule"), ("starting_room", "kind")):
        entries = settings.get(key)
        if isinstance(entries, list):
            kept = [entry for entry in entries
                    if not (isinstance(entry, dict) and is_retired_kind(entry.get(ref_key)))]
            if len(kept) != len(entries):
                result[key] = kept
    if result.get("starting_room") == []:
        # Saved settings omit empty room, like IntlSettings dumps.
        result.pop("starting_room")
    return result


@dataclass(frozen=True)
class ContributionLimit:
    annual_amount: float | None = None
    percent_of_earned_income: float | None = None
    percent_cap_amount: float | None = None
    age_min: float | None = None
    age_max: float | None = None
    shared_group: str | None = None
    lifetime_cap: float | None = None
    balance_cap: float | None = None
    index: bool = True
    # Room ledger (coastmath.engine.intl_accounts): unused room carries forward,
    # withdrawals restore room the next year, the percent limit uses the
    # prior year's earned income, and the indexed annual amount is rounded.
    carry_forward: bool = False
    withdrawals_restore_room: bool = False
    percent_of_prior_year_income: bool = False
    index_rounding: float | None = None
    # The percent limit counts only the member's own contributions.
    percent_limit_excludes_employer: bool = False


@dataclass(frozen=True)
class AccountKind:
    """A country account kind's rules (``AccountKindSpec``), normalized."""

    ref: str  # "<CC>:<kind_id>"
    country: str
    id: str
    label: str
    category: str
    limit: ContributionLimit | None = None
    contribution_deductible: bool = False
    contribution_tax_rate: float = 0.0
    earnings_tax_rate: float = 0.0
    access_age: float | None = None
    early_withdrawal_penalty_rate: float = 0.0
    withdrawal_taxable: bool = True
    tax_free_withdrawal_fraction: float = 0.0
    tax_free_lifetime_cap: float | None = None
    minimum_withdrawal_start_age: float | None = None
    minimum_withdrawal_rates: tuple[tuple[int, float], ...] = ()
    converts_to: str | None = None  # kind ref
    converts_at_age: float | None = None
    bonus_rate: float = 0.0
    bonus_cap: float | None = None
    employer_match_allowed: bool = False

    @property
    def account_type(self) -> str:
        return CATEGORY_ACCOUNT_TYPES[self.category]

    def minimum_withdrawal_rate(self, age: int) -> float:
        """The minimum withdrawal rate at ``age``: the highest listed age at or below it."""
        if self.minimum_withdrawal_start_age is None or age < self.minimum_withdrawal_start_age:
            return 0.0
        rate = 0.0
        for listed_age, listed_rate in self.minimum_withdrawal_rates:
            if listed_age <= age:
                rate = listed_rate
        return rate


def _kind_from_spec(code: str, spec: Any) -> AccountKind:
    kind_id = str(_get(spec, "id"))
    if ":" in kind_id:
        kind_id = kind_id.split(":", 1)[1]
    raw_limit = _get(spec, "contribution_limit")
    limit = None if raw_limit is None else ContributionLimit(
        annual_amount=_float(_get(raw_limit, "annual_amount")),
        percent_of_earned_income=_float(_get(raw_limit, "percent_of_earned_income")),
        percent_cap_amount=_float(_get(raw_limit, "percent_cap_amount")),
        age_min=_float(_get(raw_limit, "age_min")),
        age_max=_float(_get(raw_limit, "age_max")),
        shared_group=_get(raw_limit, "shared_group"),
        lifetime_cap=_float(_get(raw_limit, "lifetime_cap")),
        balance_cap=_float(_get(raw_limit, "balance_cap")),
        index=_get(raw_limit, "index", True) is not False,
        carry_forward=bool(_get(raw_limit, "carry_forward", False)),
        withdrawals_restore_room=bool(_get(raw_limit, "withdrawals_restore_room", False)),
        percent_of_prior_year_income=bool(_get(raw_limit, "percent_of_prior_year_income", False)),
        index_rounding=_float(_get(raw_limit, "index_rounding")),
        percent_limit_excludes_employer=bool(_get(raw_limit, "percent_limit_excludes_employer", False)),
    )
    minimum = _get(spec, "minimum_withdrawal")
    rates = _get(minimum, "rates_by_age") or {}
    converts = _get(spec, "converts_to")
    target = _get(converts, "kind_id", _get(converts, "kind")) if converts is not None else None
    if target is not None and ":" not in str(target):
        target = f"{code}:{target}"
    category = str(_value(_get(spec, "category")))
    # Unset: withdrawals from a tax-deferred kind are taxable, others are not.
    withdrawal_taxable = _get(spec, "withdrawal_taxable")
    if withdrawal_taxable is None:
        withdrawal_taxable = category == "tax_deferred"
    return AccountKind(
        ref=f"{code}:{kind_id}",
        country=code,
        id=kind_id,
        label=str(_get(spec, "label", kind_id)),
        category=category,
        limit=limit,
        contribution_deductible=bool(_get(spec, "contribution_deductible", False)),
        contribution_tax_rate=float(_get(spec, "contribution_tax_rate", 0.0) or 0.0),
        earnings_tax_rate=float(_get(spec, "earnings_tax_rate", 0.0) or 0.0),
        access_age=_float(_get(spec, "access_age")),
        early_withdrawal_penalty_rate=float(_get(spec, "early_withdrawal_penalty_rate", 0.0) or 0.0),
        withdrawal_taxable=bool(withdrawal_taxable),
        tax_free_withdrawal_fraction=float(_get(spec, "tax_free_withdrawal_fraction", 0.0) or 0.0),
        tax_free_lifetime_cap=_float(_get(spec, "tax_free_lifetime_cap")),
        minimum_withdrawal_start_age=_float(_get(minimum, "start_age")) if minimum is not None else None,
        minimum_withdrawal_rates=tuple(sorted((int(age), float(rate)) for age, rate in dict(rates).items())),
        converts_to=str(target) if target is not None else None,
        converts_at_age=_float(_get(converts, "age")) if converts is not None else None,
        bonus_rate=float(_get(spec, "bonus_rate", 0.0) or 0.0),
        bonus_cap=_float(_get(spec, "bonus_cap")),
        employer_match_allowed=bool(_get(spec, "employer_match_allowed", False)),
    )


def account_kinds(code: str) -> tuple[AccountKind, ...]:
    pkg = package()
    if pkg is None or not code or code == US:
        return ()
    try:
        specs = pkg.registry.account_kinds(code) or ()
    except (KeyError, ValueError, LookupError):
        return ()
    return tuple(_kind_from_spec(code, spec) for spec in specs)


def account_kind(ref: str | None) -> AccountKind | None:
    """The account kind ``"<CC>:<kind_id>"``, or None when it is not registered."""
    if not ref:
        return None
    match = KIND_PATTERN.match(ref)
    if match is None:
        return None
    return next((kind for kind in account_kinds(match.group(1)) if kind.id == match.group(2)), None)


def benefit_rule(rule_id: str) -> Any:
    """The registered ``BenefitRule``, or None."""
    pkg = package()
    if pkg is None:
        return None
    try:
        return pkg.registry.benefit_rule(rule_id)
    except (KeyError, ValueError, LookupError):
        return None


def benefit_params(rule_id: str, params: dict) -> Any:
    """Validate ``params`` with the rule's own model; returns the model instance."""
    rule = benefit_rule(rule_id)
    if rule is None:
        raise ValueError(f"Unknown benefit rule {rule_id!r}")
    return rule.params_model.model_validate(params or {})


def estate_rule(code: str) -> Any:
    pkg = package()
    if pkg is None:
        return None
    try:
        return pkg.registry.estate_rule(code)
    except (KeyError, ValueError, LookupError):
        return None


def spec_base_year(code: str, year: int, custom: Any = None) -> int:
    """The base year of the spec that taxes ``year`` (inflation is indexed from it)."""
    spec = custom if code == CUSTOM else _require().registry.load_spec(code, year)
    meta = _get(spec, "meta")
    return int(_get(meta, "base_year", _get(spec, "base_year", year)))


def capital_gains_spec(code: str, year: int, custom: Any = None) -> Any:
    """The capital gains section of the spec that taxes ``year`` (None for the US)."""
    if code == US:
        return None
    spec = custom if code == CUSTOM else _require().registry.load_spec(code, year)
    return _get(spec, "capital_gains")


def custom_spec(document: dict) -> Any:
    """A custom ("Other") regime validated by the package's ``RegimeSpec``."""
    return _require().spec.RegimeSpec.model_validate(document)


def validate_spec_section(name: str, value: Any) -> Any:
    """Validate a wealth or transaction tax override with the spec's own section model."""

    regime_spec = _require().spec.RegimeSpec
    field_info = regime_spec.model_fields.get(name)
    if field_info is None:
        raise ValueError(f"The regime has no {name} section")
    return TypeAdapter(field_info.annotation).validate_python(value)


def _amount(value: float) -> str:
    return f"{value:,.0f}"


def _percent(rate: float) -> str:
    return f"{rate * 100:g}%"


def kind_rules(kind: AccountKind) -> list[str]:
    """A country account kind's key rules in plain words (amounts in the plan's currency)."""
    rules = []
    limit = kind.limit
    if limit is not None:
        indexed = " a year, indexed with inflation" if limit.index else " a year"
        if limit.percent_of_earned_income is not None:
            income = "the prior year's earned income" if limit.percent_of_prior_year_income else "earned income"
            whose = "Your own contributions" if limit.percent_limit_excludes_employer else "Contributions"
            text = f"{whose} up to {_percent(limit.percent_of_earned_income)} of {income}"
            if limit.percent_cap_amount is not None:
                text += f", at most {_amount(limit.percent_cap_amount)}"
            rules.append(text + indexed + ".")
        if limit.annual_amount is not None:
            shared = " (shared with the owner's other accounts of this group)" if limit.shared_group else ""
            steps = (f" in steps of {_amount(limit.index_rounding)}"
                     if limit.index and limit.index_rounding is not None else "")
            rules.append(f"Contributions up to {_amount(limit.annual_amount)}{indexed}{steps}{shared}.")
        if limit.carry_forward:
            rules.append("Unused contribution room carries forward to later years.")
        if limit.withdrawals_restore_room:
            rules.append("Withdrawals are added back to contribution room on the next January 1.")
        if limit.lifetime_cap is not None:
            rules.append(f"Lifetime contributions up to {_amount(limit.lifetime_cap)}.")
        if limit.balance_cap is not None:
            rules.append(f"No contributions above a balance of {_amount(limit.balance_cap)}.")
        if limit.age_min is not None or limit.age_max is not None:
            if limit.age_min is not None and limit.age_max is not None:
                window = f"from age {limit.age_min:g} to {limit.age_max:g}"
            elif limit.age_min is not None:
                window = f"from age {limit.age_min:g}"
            else:
                window = f"until age {limit.age_max:g}"
            rules.append(f"Contributions only {window}.")
    if kind.category in ("tax_deferred", "tax_free"):
        rules.append("Contributions are deductible." if kind.contribution_deductible
                     else "Contributions are not deductible.")
    if kind.contribution_tax_rate:
        rules.append(f"{_percent(kind.contribution_tax_rate)} tax is taken from contributions inside the account.")
    if kind.bonus_rate:
        cap = f", up to {_amount(kind.bonus_cap)} a year" if kind.bonus_cap is not None else ""
        rules.append(f"A {_percent(kind.bonus_rate)} government bonus is added to contributions{cap}.")
    if kind.earnings_tax_rate:
        rules.append(f"Earnings are taxed at {_percent(kind.earnings_tax_rate)} inside the account.")
    if kind.employer_match_allowed:
        rules.append("Employer contributions are allowed.")
    if kind.category == "tax_deferred" and kind.withdrawal_taxable:
        text = "Withdrawals are taxed as income"
        if kind.tax_free_withdrawal_fraction:
            text += f", except {_percent(kind.tax_free_withdrawal_fraction)} of each withdrawal"
            if kind.tax_free_lifetime_cap is not None:
                text += f" up to {_amount(kind.tax_free_lifetime_cap)} in total"
        rules.append(text + ".")
    elif kind.category in ("tax_deferred", "tax_free"):
        rules.append("Withdrawals are tax free.")
    if kind.access_age is not None:
        penalty = (f" pay a {_percent(kind.early_withdrawal_penalty_rate)} penalty"
                   if kind.early_withdrawal_penalty_rate else " are not available")
        rules.append(f"Withdrawals before age {kind.access_age:g}{penalty}.")
    if kind.minimum_withdrawal_start_age is not None:
        rules.append(f"Minimum withdrawals each year from age {kind.minimum_withdrawal_start_age:g}.")
    if kind.converts_to is not None and kind.converts_at_age is not None:
        target = account_kind(kind.converts_to)
        rules.append(f"Becomes a {target.label if target else kind.converts_to} at age {kind.converts_at_age:g}.")
    return rules


def room_ledger_key(kind: AccountKind) -> str:
    """The room ledger a kind uses: its shared group (per country), else the kind itself."""
    group = kind.limit.shared_group if kind.limit is not None else None
    return f"{kind.country}:group:{group}" if group else kind.ref


def carries_room(kind: AccountKind) -> bool:
    """Whether the kind keeps a room ledger (``intl_settings.starting_room`` applies)."""
    return kind.limit is not None and kind.limit.carry_forward


def uses_prior_year_income(kind: AccountKind) -> bool:
    """Whether the kind's room uses the prior year's earned income."""
    return (kind.limit is not None and kind.limit.percent_of_earned_income is not None
            and kind.limit.percent_of_prior_year_income)


def catalog() -> list[dict]:
    """The registry as the ``GET /tax-regimes`` route returns it (US excluded)."""
    entries = []
    for info in countries().values():
        rules = []
        for rule_id in info.benefit_rules:
            rule = benefit_rule(rule_id)
            if rule is None:
                continue
            model = getattr(rule, "params_model", None)
            rules.append({
                "id": str(getattr(rule, "id", rule_id)),
                "label": str(getattr(rule, "label", rule_id)),
                "params_schema": model.model_json_schema() if model is not None else {},
            })
        entries.append({
            "code": info.code,
            "name": info.name,
            "currency": info.currency,
            "filing_unit": info.filing_unit,
            "regions": [{"code": region.code, "name": region.name} for region in info.regions],
            "default_region": info.default_region,
            "custom": info.custom,
            "account_kinds": [
                {"id": kind.ref, "label": kind.label, "category": kind.category, "rules": kind_rules(kind),
                 "carries_room": carries_room(kind),
                 "uses_prior_year_income": uses_prior_year_income(kind)}
                for kind in account_kinds(info.code)
            ],
            "benefit_rules": rules,
            "spec_years": list(info.spec_years),
            "approximations": list(info.approximations),
        })
    return entries


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def make(type_name: str, **values: Any) -> Any:
    """Construct one of the package's input types by its contract name."""
    return getattr(_require().types, type_name)(**values)


def evaluate(inputs: Any) -> Any:
    return _require().evaluator.evaluate(inputs)


@dataclass(frozen=True)
class RegimeTax:
    """One year's country tax, normalized for the snapshot and settlement."""

    country: str
    total: float = 0.0
    national_income_tax: float = 0.0
    regional_income_tax: float = 0.0
    social_contributions: float = 0.0
    wealth_tax: float = 0.0
    transaction_tax: float = 0.0
    benefit_recovery_tax: float = 0.0
    lines: tuple[dict, ...] = ()
    taxable_income: float = 0.0
    marginal_rate: float = 0.0
    # The evaluator's own result, passed back as next year's prior_year.
    raw: Any = field(default=None, compare=False)
    # The evaluator inputs that produced it (for a death-year recomputation).
    inputs: Any = field(default=None, compare=False)


_REGIONAL_CATEGORIES = frozenset({"income_regional", "income_local"})


def normalize_result(country_code: str, result: Any) -> RegimeTax:
    lines = []
    regional = 0.0
    for line in _get(result, "lines") or ():
        category = str(_value(_get(line, "category")))
        amount = float(_get(line, "amount", 0.0) or 0.0)
        person = _get(line, "person")
        lines.append({
            "code": str(_get(line, "code", "")),
            "label": str(_get(line, "label", "")),
            "category": category,
            "person": None if person is None else str(_value(person)),
            "amount": amount,
        })
        if category in _REGIONAL_CATEGORIES:
            regional += amount
    income_tax = float(_get(result, "income_tax", 0.0) or 0.0)
    marginal = _get(result, "marginal_ordinary_rate_by_person") or {}
    taxable = _get(result, "taxable_income_by_person") or {}
    return RegimeTax(
        country=country_code,
        total=float(_get(result, "total", 0.0) or 0.0),
        national_income_tax=income_tax - regional,
        regional_income_tax=regional,
        social_contributions=float(_get(result, "social_contributions", 0.0) or 0.0),
        wealth_tax=float(_get(result, "wealth_tax", 0.0) or 0.0),
        transaction_tax=float(_get(result, "transaction_tax", 0.0) or 0.0),
        benefit_recovery_tax=float(_get(result, "benefit_recovery", 0.0) or 0.0),
        lines=tuple(lines),
        taxable_income=sum(float(value) for value in dict(taxable).values()),
        marginal_rate=max((float(value) for value in dict(marginal).values()), default=0.0),
        raw=result,
    )

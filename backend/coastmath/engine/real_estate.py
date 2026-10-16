"""Real estate purchases, rentals, depreciation, passive losses and sales.

Pure helpers the simulator calls each year:

* planned purchases (``RealAssetData.purchase_*``): the price is entered in
  plan-start (today's) dollars and grows with the asset's appreciation rate
  until the purchase month. Down payment and closing-cost amounts are also
  today's dollars and scale with the price.
* rental properties (``tax_treatment == "rental"``): Schedule E income and
  expenses, straight-line depreciation with the mid-month convention
  (IRC 168(b)(3), (c), (d)(2)) and the passive activity loss rules for rental
  real estate (IRC 469(b), (g), (i)).
* mixed-use property: a rental with a rental-use share below 100%
  (``rental_use_rate``, optionally changed by year with
  ``rental_use_schedule``) divides its rental items and carrying costs
  between the rental and personal shares (IRC 280A(e)).
* the IRC 121 ownership and use test for a primary residence sale, and the
  use-ratio split of a mixed-use sale's gain (IRC 121(b)(5), (d)(6)).

Statutory figures: ``coastmath/data/real_estate_tax_rules.json``; sources in
``_sources`` in ``real_estate_tax_rules.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from coastmath.engine.types import RealAssetData

_RULES = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "real_estate_tax_rules.json").read_text()
)
_RECOVERY_YEARS: dict[str, float] = {
    key: float(value) for key, value in _RULES["depreciation"]["recovery_years"].items()
}
_PASSIVE = _RULES["passive_loss"]
UNRECAPTURED_1250_RATE = float(_RULES["unrecaptured_section_1250_rate"])
_HOME_SALE = _RULES["home_sale_exclusion"]

RENTAL = "rental"


def home_sale_exclusion_amount(filing_status: str) -> float:
    """IRC 121(b)(1)-(2): the maximum excluded gain, not indexed."""
    key = "married_filing_jointly" if filing_status == "married_filing_jointly" else "single"
    return float(_HOME_SALE[key])


def recovery_years(asset: RealAssetData) -> float:
    return _RECOVERY_YEARS.get(asset.rental_property_class or "residential", _RECOVERY_YEARS["residential"])


def is_rental(asset: RealAssetData) -> bool:
    return asset.tax_treatment == RENTAL


def rental_use_share(asset: RealAssetData, year: int) -> float:
    """Share of the property in rental use in ``year`` (0-1).

    Only a rental has a rental share. The latest schedule step at or before
    ``year`` wins; before the first step (or with no schedule) the base
    ``rental_use_rate`` applies, and a blank rate means fully rented.
    """
    if not is_rental(asset):
        return 0.0
    share = asset.rental_use_rate if asset.rental_use_rate is not None else 1.0
    for step_year, rate in asset.rental_use_schedule:
        if step_year > year:
            break
        share = rate
    return min(1.0, max(0.0, share))


def is_mixed_use(asset: RealAssetData) -> bool:
    """Whether a rental has any personal-use share."""
    if not is_rental(asset):
        return False
    rates = [asset.rental_use_rate if asset.rental_use_rate is not None else 1.0]
    rates += [rate for _, rate in asset.rental_use_schedule]
    return any(rate < 1.0 for rate in rates)


# ---------------------------------------------------------------------------
# Planned purchases
# ---------------------------------------------------------------------------


def purchase_start(asset: RealAssetData, start_year: int, first_year_fraction: float) -> float | None:
    """Fraction-of-calendar-year position of a planned purchase.

    Returns ``purchase_year + (month - 1) / 12`` when the purchase falls on or
    after the first modeled month, else None (the asset is already owned and
    its purchase fields describe history only).
    """
    if asset.purchase_year is None:
        return None
    position = asset.purchase_year + (asset.purchase_month - 1) / 12.0
    plan_start = start_year + (1.0 - first_year_fraction)
    return position if position >= plan_start - 1e-9 else None


@dataclass
class PurchaseTerms:
    price: float
    cash_due: float
    loan_principal: float
    basis: float
    building_basis: float | None


def purchase_terms(asset: RealAssetData, price: float) -> PurchaseTerms:
    """Cash, loan and basis for a purchase at the grown ``price``."""
    today_price = asset.purchase_price or 0.0
    scale = price / today_price if today_price > 0 else 1.0
    closing = max(0.0, asset.closing_costs) * scale
    loan_principal = 0.0
    if asset.purchase_loan_term_months:
        if asset.down_payment_amount is not None:
            down = min(price, max(0.0, asset.down_payment_amount) * scale)
        elif asset.down_payment_rate is not None:
            down = price * min(1.0, max(0.0, asset.down_payment_rate))
        else:
            down = 0.0
        loan_principal = price - down
        cash_due = down + closing
    else:
        cash_due = price + closing
    # Closing costs that are acquisition costs are added to basis
    # (IRS Pub. 551, "Settlement costs").
    basis = price + closing
    building = None
    if asset.building_basis is not None:
        building = max(0.0, asset.building_basis) * scale
    elif asset.land_value_rate is not None:
        building = basis * (1.0 - min(1.0, max(0.0, asset.land_value_rate)))
    return PurchaseTerms(price=price, cash_due=cash_due, loan_principal=loan_principal,
                         basis=basis, building_basis=building)


# ---------------------------------------------------------------------------
# Depreciation
# ---------------------------------------------------------------------------


def opening_building_basis(asset: RealAssetData) -> float | None:
    """Depreciable building basis of a rental owned at plan start.

    An explicit ``building_basis`` wins. Otherwise the original cost
    (adjusted basis plus depreciation already taken; current value when the
    basis is blank) less the land share. None when the land split is unknown.
    """
    if asset.building_basis is not None:
        return max(0.0, asset.building_basis)
    if asset.land_value_rate is None:
        return None
    cost = (asset.adjusted_basis if asset.adjusted_basis is not None else asset.current_value)
    cost += max(0.0, asset.prior_depreciation)
    return max(0.0, cost) * (1.0 - min(1.0, max(0.0, asset.land_value_rate)))


def depreciation_for_year(
    building_basis: float,
    recovery: float,
    taken: float,
    start_month: float,
    end_month: float,
    use_share: float = 1.0,
) -> float:
    """Straight-line depreciation for months ``start_month``-``end_month``.

    Months are positions in the calendar year (0 = January 1, 12 = year end).
    The caller places a purchase or sale at the midpoint of its month
    (mid-month convention). ``taken`` is depreciation already claimed; the
    total never exceeds the building basis. ``use_share`` is the rental-use
    share of a mixed-use property: only that share is depreciated.
    """
    if building_basis <= 0 or recovery <= 0:
        return 0.0
    months = max(0.0, min(12.0, end_month) - max(0.0, start_month))
    annual = building_basis / recovery
    share = min(1.0, max(0.0, use_share))
    return max(0.0, min(annual * months / 12.0 * share, building_basis - taken))


# ---------------------------------------------------------------------------
# Passive activity losses
# ---------------------------------------------------------------------------


@dataclass
class RentalYear:
    """One rental property's Schedule E items for the modeled year."""

    asset_id: str
    rent: float = 0.0
    operating: float = 0.0
    carrying: float = 0.0
    interest: float = 0.0
    depreciation: float = 0.0
    active_participation: bool = True
    qbi_eligible: bool = False

    @property
    def expenses(self) -> float:
        return self.operating + self.carrying + self.interest

    @property
    def net(self) -> float:
        return self.rent - self.expenses - self.depreciation


@dataclass
class PassiveResult:
    # Net rental amount entering AGI this year (negative = deductible loss).
    allowed: float = 0.0
    allowed_by_asset: dict[str, float] = field(default_factory=dict)
    # End-of-year suspended losses (positive amounts) for properties still held.
    suspended: dict[str, float] = field(default_factory=dict)
    # Losses released by dispositions (prior suspended plus that year's loss).
    released: float = 0.0
    special_allowance_used: float = 0.0


def special_allowance(modified_agi: float, filing_status: str, lived_apart: bool) -> float:
    """IRC 469(i): the rental real estate allowance after the phase-out."""
    if filing_status == "married_filing_separately":
        if not lived_apart:
            return 0.0
        cap = float(_PASSIVE["separate_lived_apart_allowance"])
        start = float(_PASSIVE["separate_lived_apart_phaseout_start"])
    else:
        cap = float(_PASSIVE["special_allowance"])
        start = float(_PASSIVE["phaseout_start"])
    return max(0.0, cap - float(_PASSIVE["phaseout_rate"]) * max(0.0, modified_agi - start))


def passive_activity_result(
    activities: list[RentalYear],
    suspended: dict[str, float],
    disposed: set[str],
    modified_agi: float,
    filing_status: str,
    lived_apart: bool = False,
) -> PassiveResult:
    """Apply IRC 469 to the year's rental activities.

    Each property's prior suspended loss is a deduction of the current year
    (469(b)). A property disposed of in a fully taxable sale releases its
    current and suspended losses in full (469(g)). The remaining properties
    are netted; a net loss is allowed up to the special allowance for
    properties with active participation (469(i)) and the rest is suspended,
    allocated ratably to the properties with losses (Treas. Reg.
    1.469-1T(f)(2)).
    """
    result = PassiveResult()
    held: dict[str, float] = {}
    active: dict[str, bool] = {}
    for activity in activities:
        combined = activity.net - max(0.0, suspended.get(activity.asset_id, 0.0))
        if activity.asset_id in disposed:
            result.allowed_by_asset[activity.asset_id] = combined
            result.released += max(0.0, -combined)
        else:
            held[activity.asset_id] = combined
            active[activity.asset_id] = activity.active_participation
    # Properties with no activity this year keep their suspended losses
    # unless they were disposed of.
    seen = {activity.asset_id for activity in activities}
    for asset_id, amount in suspended.items():
        if asset_id in seen or amount <= 0:
            continue
        if asset_id in disposed:
            result.allowed_by_asset[asset_id] = -amount
            result.released += amount
        else:
            result.suspended[asset_id] = amount
    net = sum(held.values())
    if net >= 0:
        result.allowed_by_asset.update(held)
    else:
        loss = -net
        active_losses = sum(-amount for asset_id, amount in held.items() if amount < 0 and active[asset_id])
        allowed = min(loss, active_losses, special_allowance(modified_agi, filing_status, lived_apart))
        disallowed = loss - allowed
        result.special_allowance_used = allowed
        total_losses = sum(-amount for amount in held.values() if amount < 0)
        for asset_id, amount in held.items():
            carried = disallowed * (-amount) / total_losses if amount < 0 and total_losses > 0 else 0.0
            if carried > 0.005:
                result.suspended[asset_id] = carried
            result.allowed_by_asset[asset_id] = amount + carried
    result.allowed = sum(result.allowed_by_asset.values())
    return result


# ---------------------------------------------------------------------------
# Home sale exclusion (IRC 121)
# ---------------------------------------------------------------------------


def _months_between(since_year: int, since_month: int | None, year: int, month: int) -> int:
    return (year * 12 + month) - (since_year * 12 + (since_month or 1))


def section_121_test(
    asset: RealAssetData,
    sale_year: int,
    sale_month: int,
    purchased_at: tuple[int, int] | None = None,
) -> bool | None:
    """Whether the 2-of-5-year ownership and use test is met at the sale.

    Ownership runs from ``owned_since`` (or a purchase within the plan) and
    use from ``primary_residence_since`` (else the ownership date); both are
    assumed continuous to the sale, so the five-year lookback never shortens
    them below the required period. Returns None when no date is known.
    """
    owned = ((asset.owned_since_year, asset.owned_since_month) if asset.owned_since_year is not None
             else purchased_at)
    used = ((asset.primary_residence_since_year, asset.primary_residence_since_month)
            if asset.primary_residence_since_year is not None else owned)
    if owned is None and used is None:
        return None
    ownership_ok = owned is None or _months_between(owned[0], owned[1], sale_year, sale_month) >= int(
        _HOME_SALE["ownership_months"])
    use_ok = used is None or _months_between(used[0], used[1], sale_year, sale_month) >= int(
        _HOME_SALE["use_months"])
    return ownership_ok and use_ok


def sale_rental_share(
    asset: RealAssetData,
    sale_year: int,
    sale_month: int,
    owned_from: tuple[int, int],
) -> float:
    """Month-weighted rental share of a mixed-use property over its ownership.

    Months run from ``owned_from`` (year, month) to the sale month. For a
    primary residence only nonqualified use counts: months before the
    nonqualified-use start year (IRC 121(b)(5)(C)(i)) count as personal use,
    while still counting in the ownership period. A fully rented property
    returns 1.0. A sale in or before the ownership month uses the sale year's
    share.
    """
    if not is_mixed_use(asset):
        return 1.0 if is_rental(asset) else 0.0
    floor_year = int(_HOME_SALE["nonqualified_use_start_year"]) if asset.is_primary_residence else None
    start = owned_from[0] * 12 + (owned_from[1] or 1) - 1
    end = sale_year * 12 + sale_month - 1
    if end <= start:
        return rental_use_share(asset, sale_year)
    rented = 0.0
    for index in range(start, end):
        year = index // 12
        if floor_year is None or year >= floor_year:
            rented += rental_use_share(asset, year)
    return rented / (end - start)


# ---------------------------------------------------------------------------
# Input conversion
# ---------------------------------------------------------------------------


def engine_fields(source: object) -> dict:
    """``RealAssetData`` keyword arguments for the real estate fields.

    *source* is a stored real asset or a stateless request item. Blank values
    keep the engine defaults, which reproduce the earlier behavior. The loan
    rate is stored as an annual percent and converted to a decimal here.
    """
    def value(name: str):
        return getattr(source, name, None)

    def number(name: str) -> float | None:
        raw = value(name)
        return float(raw) if raw is not None else None

    loan_rate = number("purchase_loan_rate")
    account_id = value("purchase_funding_account_id")
    schedule = []
    for step in value("rental_use_schedule") or []:
        raw = step if isinstance(step, dict) else step.model_dump()
        schedule.append((int(raw["year"]), float(raw["rate"])))
    return {
        "purchase_year": value("purchase_year"),
        "purchase_month": value("purchase_month") or 1,
        "purchase_price": number("purchase_price"),
        "down_payment_amount": number("down_payment_amount"),
        "down_payment_rate": number("down_payment_rate"),
        "closing_costs": number("closing_costs") or 0.0,
        "purchase_funding_account_id": str(account_id) if account_id is not None else None,
        "purchase_loan_rate": loan_rate / 100.0 if loan_rate is not None else None,
        "purchase_loan_term_months": value("purchase_loan_term_months"),
        "selling_cost_rate": number("selling_cost_rate") or 0.0,
        "rental_income": number("rental_income") or 0.0,
        "rental_income_growth_rate": number("rental_income_growth_rate"),
        "rental_expenses": number("rental_expenses") or 0.0,
        "rental_expense_rate": number("rental_expense_rate"),
        "vacancy_rate": number("vacancy_rate") or 0.0,
        "rental_property_class": value("rental_property_class") or "residential",
        "land_value_rate": number("land_value_rate"),
        "building_basis": number("building_basis"),
        "prior_depreciation": number("prior_depreciation") or 0.0,
        "qbi_eligible": bool(value("qbi_eligible")),
        "rental_active_participation": value("rental_active_participation") is not False,
        "suspended_passive_loss": number("suspended_passive_loss") or 0.0,
        "owned_since_year": value("owned_since_year"),
        "owned_since_month": value("owned_since_month"),
        "primary_residence_since_year": value("primary_residence_since_year"),
        "primary_residence_since_month": value("primary_residence_since_month"),
        "rental_use_rate": number("rental_use_rate"),
        "rental_use_schedule": tuple(sorted(schedule)),
    }

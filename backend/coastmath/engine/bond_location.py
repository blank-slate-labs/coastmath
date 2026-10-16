"""Per-account bond allocations: glide paths and the household asset location.

Two independent settings decide an account's stock/bond split each year:

- ``investment_settings.bond_allocation_glide`` on an account: points keyed by
  calendar year or by the owner's age, linearly interpolated and constant
  beyond the end points. It replaces the account's fixed ``bond_allocation``.
- ``tax_settings.asset_location`` on the plan. In ``household`` mode the
  plan's bond allocation (its assumption, fixed or curve) is a target for the
  pooled accounts together. Accounts with their own allocation (fixed or glide)
  keep it and count toward the target. The remaining bond dollars are placed
  in ``bond_location_order``: each entry is an account bucket or an account id,
  and accounts of the same entry share the bonds in proportion to their
  balances. Everything else in a pooled account is stock.

Allocations are decided from opening balances each year, so they are notional:
no rebalancing trades, costs or realized gains are modeled. Money contributed
during the year grows at its account's allocation for that year. Cash, HSA and
cryptocurrency accounts are never pooled (real estate is not an account); an
HSA keeps the plan allocation, as an excluded account does.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise

from coastmath.engine.account_types import ROTH_TYPES, TRADITIONAL_RETIREMENT_TYPES
from coastmath.engine.types import AccountInfo

#: Account buckets for ``bond_location_order``.
ACCOUNT_BUCKETS: dict[str, frozenset[str]] = {
    "tax_deferred": frozenset(TRADITIONAL_RETIREMENT_TYPES),
    "tax_free": frozenset(ROTH_TYPES | {"five_twenty_nine"}),
    "taxable": frozenset({"taxable_brokerage", "other"}),
}
DEFAULT_LOCATION_ORDER: tuple[str, ...] = ("tax_deferred", "tax_free", "taxable")
#: Never part of the household pool.
NEVER_POOLED_TYPES = frozenset({"checking", "savings", "hsa", "cryptocurrency"})

_EPSILON = 1e-9


@dataclass(frozen=True)
class AssetLocationSpec:
    """Household mode settings; per-account mode is represented by ``None``."""

    order: tuple[str, ...] = DEFAULT_LOCATION_ORDER
    excluded_account_ids: frozenset[str] = frozenset()


def parse_asset_location(tax_settings: Mapping | None) -> AssetLocationSpec | None:
    """Household asset location from ``tax_settings``, or ``None`` for per-account."""
    raw = (tax_settings or {}).get("asset_location")
    if not isinstance(raw, Mapping) or raw.get("bond_allocation_mode") != "household":
        return None
    order = tuple(str(entry) for entry in (raw.get("bond_location_order") or ()))
    return AssetLocationSpec(
        order=order or DEFAULT_LOCATION_ORDER,
        excluded_account_ids=frozenset(str(aid) for aid in (raw.get("excluded_account_ids") or ())),
    )


def account_bucket(account_type: str) -> str | None:
    """The location bucket of an account type, or ``None`` if it has none."""
    return next((name for name, types in ACCOUNT_BUCKETS.items() if account_type in types), None)


def linear_interpolate(points: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear value at ``x``; constant beyond the end points.

    Duplicate x values use the last supplied point, like the assumption curves.
    """
    values = dict(points)
    xs = sorted(values)
    if not xs:
        return 0.0
    if x <= xs[0]:
        return values[xs[0]]
    if x >= xs[-1]:
        return values[xs[-1]]
    for left, right in pairwise(xs):
        if x <= right:
            t = (x - left) / (right - left)
            return values[left] + t * (values[right] - values[left])
    return values[xs[-1]]  # pragma: no cover - unreachable


def glide_bond_allocation(glide: list[Mapping] | None, year: int, owner_age: float) -> float | None:
    """The bond share a glide path sets for ``year``, or ``None`` without one.

    Points keyed by ``year`` use the calendar year; points keyed by ``age``
    use the account owner's age in that year (year minus birth year).
    """
    points: list[tuple[float, float]] = []
    for point in glide or ():
        allocation = point.get("bond_allocation")
        if allocation is None:
            continue
        if point.get("year") is not None:
            points.append((float(point["year"]), float(allocation)))
        elif point.get("age") is not None:
            points.append((float(point["age"]) - owner_age + year, float(allocation)))
    if not points:
        return None
    return min(1.0, max(0.0, linear_interpolate(points, float(year))))


def account_bond_override(account: AccountInfo, year: int, owner_ages: Mapping[str, float]) -> float | None:
    """An account's own bond allocation this year (glide path, then fixed value)."""
    if account.account_type == "cryptocurrency":
        return None
    settings = account.investment_settings or {}
    owner_age = owner_ages.get(account.owner, owner_ages.get("self", 0.0))
    glide = glide_bond_allocation(settings.get("bond_allocation_glide"), year, owner_age)
    if glide is not None:
        return glide
    fixed = settings.get("bond_allocation")
    return float(fixed) if fixed is not None else None


def resolve_bond_allocations(
    accounts: Mapping[str, AccountInfo],
    plan_bond_allocation: float,
    spec: AssetLocationSpec | None,
    year: int,
    owner_ages: Mapping[str, float],
) -> tuple[dict[str, float], dict[str, float]]:
    """Return ``(allocations, household_allocations)`` for this year.

    ``allocations`` holds the accounts whose bond share is decided here rather
    than by ``account_investment_rates`` (glide paths, and every pooled account
    in household mode). ``household_allocations`` is the per-account split of
    the household pool for the snapshot; empty in per-account mode.
    """
    overrides: dict[str, float] = {}
    for aid, account in accounts.items():
        settings = account.investment_settings or {}
        if settings.get("bond_allocation_glide"):
            value = account_bond_override(account, year, owner_ages)
            if value is not None:
                overrides[aid] = value
    if spec is None:
        return overrides, {}

    pooled = {
        aid: account for aid, account in accounts.items()
        if account.account_type not in NEVER_POOLED_TYPES
        and aid not in spec.excluded_account_ids
        and account_bucket(account.account_type) is not None
    }
    balances = {aid: max(0.0, account.balance) for aid, account in pooled.items()}
    allocations: dict[str, float] = {}
    flexible: list[str] = []
    fixed_bonds = 0.0
    for aid, account in pooled.items():
        own = account_bond_override(account, year, owner_ages)
        if own is None:
            flexible.append(aid)
        else:
            allocations[aid] = own
            fixed_bonds += balances[aid] * own
    remaining = plan_bond_allocation * sum(balances.values()) - fixed_bonds

    def rank(aid: str) -> int:
        if aid in spec.order:
            return spec.order.index(aid)
        bucket = account_bucket(pooled[aid].account_type)
        return spec.order.index(bucket) if bucket in spec.order else len(spec.order)

    groups: dict[int, list[str]] = {}
    for aid in flexible:
        groups.setdefault(rank(aid), []).append(aid)
    for position in sorted(groups):
        members = groups[position]
        group_balance = sum(balances[aid] for aid in members)
        if remaining <= _EPSILON:
            share = 0.0
        elif group_balance <= remaining:
            # Includes an empty group while bonds are still unplaced, so this
            # year's contributions to it go to bonds.
            share = 1.0
            remaining -= group_balance
        else:
            share = remaining / group_balance
            remaining = 0.0
        for aid in members:
            allocations[aid] = share
    overrides.update(allocations)
    return overrides, {aid: round(value, 6) for aid, value in allocations.items()}

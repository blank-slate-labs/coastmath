"""Indexed cost bases for country regimes that index capital gains.

A regime spec whose capital gains section has `cost_base_indexation` measures
gains on cost bases indexed by inflation from `start_year`, and treats the gain
accrued before then as a deferred gain. The engine
keeps nominal cost bases (`AccountInfo.cost_basis`, the real asset basis less
depreciation). This module keeps two amounts on top of them for each taxable
account and each real asset other than the main residence:

- `deferred`: value minus nominal cost basis at the transition (the deemed sale
  and reacquisition), not yet realized. It can be negative (a deferred loss).
- `indexation`: the inflation uplift of the cost base since the transition.

After the transition the cost base is nominal basis + deferred, and the indexed
cost base adds the indexation. A sale of a fraction f with nominal gain g
realizes the deferred part f x deferred; the rest, g - f x deferred, is the
current gain. A current gain is reduced by f x indexation but not below zero
(indexation never creates or increases a loss); a current loss is unchanged.
Both amounts shrink by f. Contributions join the nominal basis at cost and are
indexed from the next year. Each account or asset is one pooled holding.

Activation: at the start of the first year whose regime spec indexes cost bases
and whose year is at or after `start_year`:
- in `start_year` itself every holding is deemed reacquired at its value at the
  start of the year (the deferred amount is value minus basis);
- in a later year (the plan starts later, or the household first lives in that
  country later) the entered nominal basis is indexed from that year, with no
  deferred amount.
Once active, each later year start indexes every holding by the previous
year's plan inflation (a fall in prices does not reduce it), whichever country
taxes the year. The split of realized gains is reported every country year;
only specs that ask for it use it (`coastmath.engine.intl.gains`). Gains on the main
residence are reported in every country year for specs that exempt them.

Values are replaced, never mutated, so the simulator's withdrawal trials restore
them with the other year fields.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from coastmath.engine.types import _TAXABLE_TYPES, PlanData, SimState


@dataclass(frozen=True, slots=True)
class Pool:
    deferred: float = 0.0
    indexation: float = 0.0


@dataclass(frozen=True, slots=True)
class GainSplit:
    """This year's realized gains by part (all inside `capital_gains_this_year`)."""

    deferred: float = 0.0
    indexation: float = 0.0
    main_residence: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {"deferred": self.deferred, "indexation": self.indexation, "main_residence": self.main_residence}


def _real_asset_basis(state: SimState, asset: Any) -> float:
    """The nominal basis `_sell_real_asset` uses: basis less depreciation."""
    basis = state.real_asset_basis.get(asset.id)
    if basis is None:
        basis = asset.adjusted_basis if asset.adjusted_basis is not None else asset.current_value
    return basis - state.real_estate_depreciation.get(asset.id, 0.0)


def _holdings(state: SimState, plan: PlanData) -> list[tuple[str, float, float]]:
    """(id, value, nominal basis) for each taxable account and investment real asset."""
    holdings = []
    for account_id, account in state.accounts.items():
        if account.account_type in _TAXABLE_TYPES:
            basis = account.cost_basis if account.cost_basis is not None else account.balance
            holdings.append((account_id, account.balance, basis))
    for asset in plan.real_assets:
        if asset.is_primary_residence or asset.id not in state.real_asset_values:
            continue
        holdings.append((asset.id, state.get_real_asset_value(asset.id), _real_asset_basis(state, asset)))
    return holdings


def start_year(state: SimState, plan: PlanData, year: int, capital_gains_spec: Any,
               calendar_inflation: dict[int, float]) -> None:
    """Begin a country-regime plan's year: activate or index the pools, reset the split.

    `capital_gains_spec` is the capital gains section of the spec taxing this
    year (None in a US year).
    """
    state.capital_gain_split_this_year = GainSplit()
    pools = state.indexed_cost_bases
    if pools is None:
        indexation = getattr(capital_gains_spec, "cost_base_indexation", None)
        if indexation is None or year < indexation.start_year:
            return
        transition = year == indexation.start_year
        state.indexed_cost_bases = {
            key: Pool(deferred=value - basis if transition else 0.0)
            for key, value, basis in _holdings(state, plan)
        }
        return
    previous, current = calendar_inflation.get(year - 1), calendar_inflation.get(year)
    rate = current / previous - 1.0 if previous and current else 0.0
    if rate <= 0:
        return
    indexed = dict(pools)
    for key, _value, basis in _holdings(state, plan):
        pool = pools.get(key, Pool())
        base = basis + pool.deferred + pool.indexation
        indexed[key] = replace(pool, indexation=pool.indexation + rate * max(0.0, base))
    state.indexed_cost_bases = indexed


def _add_split(state: SimState, **amounts: float) -> None:
    split = state.capital_gain_split_this_year
    if not isinstance(split, GainSplit):
        return
    state.capital_gain_split_this_year = replace(
        split, **{name: getattr(split, name) + amount for name, amount in amounts.items()})


def record_sale(state: SimState, key: str, fraction: float, gain: float) -> None:
    """Split the nominal `gain` of selling `fraction` of a holding and shrink its pool."""
    pools = state.indexed_cost_bases
    if pools is None:
        return
    fraction = min(1.0, max(0.0, fraction))
    pool = pools.get(key, Pool())
    deferred = fraction * pool.deferred
    uplift = fraction * pool.indexation
    current = gain - deferred
    indexed = max(0.0, current - uplift) if current > 0 else current
    _add_split(state, deferred=deferred, indexation=current - indexed)
    state.indexed_cost_bases = {
        **pools, key: Pool(deferred=pool.deferred - deferred, indexation=pool.indexation - uplift)}


def record_disposal(state: SimState, key: str, fraction: float) -> None:
    """Shrink a holding's pool for a disposal that realizes no gain (a gift of shares)."""
    pools = state.indexed_cost_bases
    if pools is None or key not in pools:
        return
    keep = 1.0 - min(1.0, max(0.0, fraction))
    pool = pools[key]
    state.indexed_cost_bases = {
        **pools, key: Pool(deferred=pool.deferred * keep, indexation=pool.indexation * keep)}


def record_real_asset_sale(state: SimState, asset_id: str, gain: float, main_residence: bool) -> None:
    """A real asset sold whole: the main residence gain, or the split of an investment gain."""
    if main_residence:
        _add_split(state, main_residence=max(0.0, gain))
        return
    record_sale(state, asset_id, 1.0, gain)
    pools = state.indexed_cost_bases
    if pools is not None and asset_id in pools:
        state.indexed_cost_bases = {key: pool for key, pool in pools.items() if key != asset_id}


def parts_by_person(state: SimState, shares: dict[str, float]) -> dict[str, dict[str, float]]:
    """This year's split, divided like household investment income."""
    split = state.capital_gain_split_this_year
    if not isinstance(split, GainSplit) or split == GainSplit():
        return {}
    return {person: {name: amount * share for name, amount in split.as_dict().items()}
            for person, share in shares.items()}

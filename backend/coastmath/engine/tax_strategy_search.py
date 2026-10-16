"""Bounded, staged search over tax-strategy combinations.

The simple comparison in :mod:`coastmath.engine.tax_strategy` ranks one conversion
or harvesting ceiling at a time. This module searches combinations of

- a target federal bracket rate,
- three actions that share that target: Roth conversions, long-term gain
  harvesting and tax-targeted withdrawal blending,
- the order accounts are drawn down in, and
- a timing window (a pair of milestones from the same plan),

by running the full projection for each distinct candidate. It is a grid
search, never a global optimizer:

1. *Rate scan.* The baseline (the plan exactly as saved) and every
   requested rate with all selected actions on are simulated, which ranks
   the rates.
2. *Survivors.* The best-ranked rate (every rate tied with it) and its
   neighbours in the requested rate list go first in the next stage.
3. *Combinations.* Action subsets x order presets x timing windows at every
   rate, and order-only changes, are simulated until the budget is spent:
   candidates with at most two changes at the surviving rates first, then
   those at the other rates in scan order, then the larger ones in the same
   order. The other rates are only deferred, never dropped, so a large enough
   budget covers the whole grid.

Candidates are normalized (settings that cannot matter are dropped) and
deduplicated on the exact plan they produce, each is simulated once, and the
counts of simulated, cached and budget-skipped candidates are reported. The
input plan is never mutated: each scenario is a copy.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field, replace

from coastmath.engine.account_types import ROTH_TYPES, TRADITIONAL_RETIREMENT_TYPES
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_strategy import (
    OBJECTIVES,
    OutcomeMeasures,
    measure_result,
    objective_direction,
    pre_tax_discount_rate,
)
from coastmath.engine.types import (
    DrawdownEntryData,
    MilestoneData,
    PlanData,
    PriorityData,
)

#: Hard server-side bounds. The request may ask for less, never more.
MAX_SIMULATIONS = 128
DEFAULT_SIMULATIONS = 64
MAX_RATES = 7
MAX_WINDOWS = 4

ACTIONS = ("conversion", "harvest", "blend")
_ACTION_TEXT = {
    "conversion": "Roth conversions",
    "harvest": "gain harvesting",
    "blend": "tax-targeted withdrawals",
}
#: Group order each preset draws from. Groups: 0 cash and taxable, 1 pre-tax
#: retirement, 2 Roth, 3 HSA and other accounts. Unknown accounts go last.
ORDER_PRESETS: dict[str, tuple[str, tuple[int, ...]]] = {
    "saved": ("Keep the saved withdrawal order", (0, 1, 2, 3)),
    "taxable_first": ("Draw cash and taxable accounts, then pre-tax, then Roth", (0, 1, 2, 3)),
    "pretax_first": ("Draw pre-tax accounts first, then cash and taxable, then Roth", (1, 0, 2, 3)),
    "roth_before_pretax": ("Draw cash and taxable accounts, then Roth, then pre-tax", (0, 2, 1, 3)),
}
_CASH_TAXABLE_TYPES = frozenset({"checking", "savings", "taxable_brokerage"})
#: Dollar objectives tie within a cent; the effective rate within 1e-8.
_TIE_DECIMALS = {"lifetime_effective_tax_rate": 8}

@dataclass(frozen=True)
class SearchWindow:
    """A timing window: rules run between two milestones.

    A bound given as a year or an age becomes a new date or age milestone in
    ``milestones``; the candidate's plan includes it and its proposal asks to
    create it (``milestones_to_add``) before adding the rules.
    """
    label: str
    start_milestone_id: str | None = None
    end_milestone_id: str | None = None
    milestones: tuple[MilestoneData, ...] = ()


@dataclass(frozen=True)
class SearchSpace:
    objective: str
    bracket_rates: tuple[float, ...] = ()
    conversion_source_id: str | None = None
    conversion_target_id: str | None = None
    harvest_source_id: str | None = None
    allow_blend: bool = False
    order_presets: tuple[str, ...] = ("saved",)
    windows: tuple[SearchWindow, ...] = ()
    max_simulations: int = DEFAULT_SIMULATIONS

    @property
    def enabled_actions(self) -> tuple[str, ...]:
        actions = []
        if self.conversion_source_id and self.conversion_target_id:
            actions.append("conversion")
        if self.harvest_source_id:
            actions.append("harvest")
        if self.allow_blend:
            actions.append("blend")
        return tuple(actions)


@dataclass(frozen=True)
class StrategySpec:
    """One point of the grid. ``window`` indexes ``SearchSpace.windows``."""
    actions: tuple[str, ...] = ()
    rate: float | None = None
    order: str = "saved"
    window: int | None = None


@dataclass(frozen=True)
class PlanChange:
    """One disclosed difference between the saved plan and a candidate."""
    kind: str  # "add" or "replace"
    target: str  # "priority", "milestone", "tax_target", "blend_drawdown" or "drawdown_order"
    summary: str
    before: object = None
    after: object = None


@dataclass
class Scenario:
    plan: PlanData
    changes: list[PlanChange]
    fingerprint: str
    proposal: dict


@dataclass
class SearchCandidate:
    key: str
    label: str
    stage: str
    spec: StrategySpec
    success: bool
    failure_year: int | None
    measures: OutcomeMeasures
    objective_value: float
    total_converted: float
    total_harvested: float
    peak_marginal_rate: float
    changes: list[PlanChange]
    proposal: dict
    rank: int = 0
    delta_vs_baseline: float = 0.0
    is_baseline: bool = False
    improves_baseline: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class SearchCounts:
    max_simulations: int
    simulated: int = 0
    stage1_simulated: int = 0
    stage2_simulated: int = 0
    cache_hits: int = 0
    #: Grid points before and after merging identical candidates.
    grid_requested: int = 0
    grid_size: int = 0
    #: Distinct grid points at the surviving rates (or changing only the
    #: order) left out because the budget ran out.
    skipped_by_budget: int = 0
    #: Distinct grid points at the other rates left out because the budget ran out.
    screened_out: int = 0
    budget_exhausted: bool = False


@dataclass
class SearchOutcome:
    objective: str
    objective_description: str
    direction: str
    baseline_key: str
    best_key: str | None
    candidates: list[SearchCandidate]
    counts: SearchCounts
    survivor_rates: list[float]
    caveats: list[str]
    pre_tax_discount_rate: float


# ---------------------------------------------------------------------------
# Drawdown order
# ---------------------------------------------------------------------------

def _account_group(plan_data: PlanData, account_id: str | None) -> int:
    account = plan_data.accounts.get(account_id or "")
    if account is None:
        return 4
    if account.account_type in _CASH_TAXABLE_TYPES:
        return 0
    if account.account_type in TRADITIONAL_RETIREMENT_TYPES:
        return 1
    if account.account_type in ROTH_TYPES:
        return 2
    return 3


def reorder_drawdown(plan_data: PlanData, preset: str) -> list[DrawdownEntryData]:
    """The saved drawdown entries regrouped by ``preset``.

    Only accounts already in the saved order are moved; the set of ranks is
    kept, and accounts keep their saved relative order inside a group.
    """
    saved = sorted(plan_data.drawdown_order, key=lambda entry: entry.rank)
    if preset == "saved":
        return [replace(entry) for entry in saved]
    sequence = ORDER_PRESETS[preset][1]
    position = {group: index for index, group in enumerate(sequence)}
    ordered = sorted(
        enumerate(saved),
        key=lambda item: (position.get(_account_group(plan_data, item[1].source_account_id), len(sequence)), item[0]),
    )
    ranks = [entry.rank for entry in saved]
    return [DrawdownEntryData(rank=rank, source_account_id=entry.source_account_id)
            for rank, (_, entry) in zip(ranks, ordered, strict=True)]


def _order_ids(order: list[DrawdownEntryData]) -> list[str | None]:
    return [entry.source_account_id for entry in sorted(order, key=lambda e: e.rank)]


def _account_name(plan_data: PlanData, account_id: str | None) -> str:
    account = plan_data.accounts.get(account_id or "")
    return (account.name if account and account.name else None) or str(account_id)


# ---------------------------------------------------------------------------
# Candidate construction
# ---------------------------------------------------------------------------

def _percent(rate: float) -> str:
    return f"{round(rate * 100)}%"


def _spec_key(spec: StrategySpec) -> str:
    if not spec.actions and spec.order == "saved":
        return "baseline"
    rate = "-" if spec.rate is None else str(round(spec.rate * 10000))
    window = "all" if spec.window is None else f"w{spec.window + 1}"
    return f"{'+'.join(spec.actions) or 'order'}@{rate}/{spec.order}/{window}"


def _join_words(words: list[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _label(spec: StrategySpec, space: SearchSpace) -> str:
    if not spec.actions and spec.order == "saved":
        return "Current plan, no changes"
    parts: list[str] = []
    if spec.actions:
        text = _join_words([_ACTION_TEXT[a] for a in spec.actions])
        parts.append(f"{text[:1].upper()}{text[1:]} within the {_percent(spec.rate or 0)} bracket")
    if spec.order != "saved":
        parts.append(ORDER_PRESETS[spec.order][0])
    if spec.window is not None:
        parts.append(space.windows[spec.window].label)
    return "; ".join(parts)


def normalize(plan_data: PlanData, space: SearchSpace, spec: StrategySpec) -> StrategySpec:
    """Drop the settings of ``spec`` that cannot change the simulation."""
    actions = tuple(a for a in ACTIONS if a in spec.actions)
    rate = spec.rate if actions else None
    window = spec.window if ("conversion" in actions or "harvest" in actions) else None
    order = spec.order
    if order != "saved" and _order_ids(reorder_drawdown(plan_data, order)) == _order_ids(plan_data.drawdown_order):
        order = "saved"
    return StrategySpec(actions=actions, rate=rate, order=order, window=window)


def _comparable_target(target: dict | None) -> dict | None:
    """The target without unset fields, so equal targets compare equal."""
    if not target:
        return None
    return {key: round(value, 9) if isinstance(value, float) else value
            for key, value in sorted(target.items()) if value is not None}


def materialize(plan_data: PlanData, space: SearchSpace, spec: StrategySpec) -> Scenario:
    """The plan ``spec`` produces, the disclosed changes and the apply proposal.

    ``plan_data`` is copied, never modified. Rules are added after the saved
    ones, the saved tax target and withdrawal order are replaced only when
    the candidate differs, and the saved rules stay untouched.
    """
    changes: list[PlanChange] = []
    added: list[PriorityData] = []
    proposal: dict = {"priorities_to_add": [], "tax_settings": None, "drawdown_order": None, "milestones_to_add": []}
    scenario = plan_data
    window = space.windows[spec.window] if spec.window is not None else SearchWindow("")

    if spec.actions and window.milestones:
        scenario = replace(scenario, milestones=[*plan_data.milestones, *window.milestones])
        for milestone in window.milestones:
            changes.append(PlanChange("add", "milestone", f"Add milestone: {milestone.name}"))
            proposal["milestones_to_add"].append({
                "id": milestone.id, "name": milestone.name, "trigger_type": milestone.trigger_type,
                "trigger_value": milestone.trigger_value, "trigger_date": milestone.trigger_date,
            })
    if spec.actions:
        next_rank = max((p.priority_rank for p in plan_data.priorities), default=0) + 1
        base = dict(conversion_mode="fill_bracket", bracket_ceiling_rate=None, use_plan_tax_target=True,
                    start_milestone_id=window.start_milestone_id, end_milestone_id=window.end_milestone_id)
        if "conversion" in spec.actions:
            added.append(PriorityData(priority_rank=next_rank + len(added), priority_type="roth_conversion",
                                      source_account_id=space.conversion_source_id,
                                      target_account_id=space.conversion_target_id, **base))
        if "harvest" in spec.actions:
            added.append(PriorityData(priority_rank=next_rank + len(added), priority_type="gain_harvest",
                                      source_account_id=space.harvest_source_id, target_account_id=None, **base))
        for rule in added:
            what = "Roth conversion" if rule.priority_type == "roth_conversion" else "Gain harvesting"
            source = _account_name(plan_data, rule.source_account_id)
            route = (f"{source} to {_account_name(plan_data, rule.target_account_id)}"
                     if rule.priority_type == "roth_conversion" else source)
            changes.append(PlanChange("add", "priority", f"Add rule {rule.priority_rank}: {what} from {route}, sized to the tax target",
                                      None, rule.priority_rank))
            proposal["priorities_to_add"].append({
                "priority_rank": rule.priority_rank, "priority_type": rule.priority_type,
                "source_account_id": rule.source_account_id, "target_account_id": rule.target_account_id,
                "conversion_mode": "fill_bracket", "bracket_ceiling_rate": None, "magi_cap": None,
                "max_annual_amount": None, "use_plan_tax_target": True,
                "start_milestone_id": rule.start_milestone_id, "end_milestone_id": rule.end_milestone_id,
            })

        saved_settings = dict(plan_data.tax_settings or {})
        saved_target = saved_settings.get("tax_target") or None
        target = {"kind": "federal_bracket", "bracket_rate": spec.rate}
        for extra in ("avoid_niit", "avoid_irmaa", "aca_cap_fpl_percent"):
            if saved_target and saved_target.get(extra) is not None:
                target[extra] = saved_target[extra]
        settings = dict(saved_settings)
        settings_changed: dict = {}
        if _comparable_target(saved_target) != _comparable_target(target):
            settings["tax_target"] = target
            settings_changed["tax_target"] = target
            kind = "replace" if saved_target else "add"
            changes.append(PlanChange(
                kind, "tax_target",
                f"Set the tax target to stay within the {_percent(spec.rate or 0)} federal bracket"
                + (" (replaces the saved target)" if saved_target else ""),
                saved_target, target))
        if "blend" in spec.actions and not settings.get("blend_drawdown_to_tax_target"):
            settings["blend_drawdown_to_tax_target"] = True
            settings_changed["blend_drawdown_to_tax_target"] = True
            changes.append(PlanChange("replace", "blend_drawdown", "Turn on tax-targeted withdrawal blending",
                                      bool(saved_settings.get("blend_drawdown_to_tax_target")), True))
        scenario = replace(scenario, priorities=list(plan_data.priorities) + added, tax_settings=settings)
        proposal["tax_settings"] = settings_changed or None

    if spec.order != "saved":
        order = reorder_drawdown(plan_data, spec.order)
        before = _order_ids(plan_data.drawdown_order)
        after = _order_ids(order)
        names = " > ".join(_account_name(plan_data, a) for a in after)
        changes.append(PlanChange("replace", "drawdown_order", f"Replace the withdrawal order: {names}", before, after))
        scenario = replace(scenario, drawdown_order=order)
        proposal["drawdown_order"] = [{"rank": e.rank, "source_account_id": e.source_account_id}
                                      for e in sorted(order, key=lambda e: e.rank)]

    fingerprint = json.dumps({
        "added": [(p.priority_type, p.source_account_id, p.target_account_id, p.start_milestone_id, p.end_milestone_id)
                  for p in added],
        "target": _comparable_target((scenario.tax_settings or {}).get("tax_target")),
        "blend": bool((scenario.tax_settings or {}).get("blend_drawdown_to_tax_target")),
        "order": _order_ids(scenario.drawdown_order),
        "milestones": [(m.id, m.trigger_type, m.trigger_value, m.trigger_date)
                       for m in (window.milestones if spec.actions else ())],
    }, sort_keys=True, default=str)
    return Scenario(plan=scenario, changes=changes, fingerprint=fingerprint, proposal=proposal)


# ---------------------------------------------------------------------------
# Evaluation and ranking
# ---------------------------------------------------------------------------

def _transfer_total(result, source: str | None, target: str | None) -> float:
    if source is None or target is None:
        return 0.0
    return sum(t.amount for s in result.yearly_snapshots for t in s.transfers
               if t.source_account_id == source and t.target_account_id == target)


def _simulate(space: SearchSpace, spec: StrategySpec, scenario: Scenario, stage: str,
              discount_rate: float, baseline_run: dict) -> tuple[SearchCandidate, dict]:
    result = run_simulation(scenario.plan)
    measures = measure_result(result, discount_rate)
    run = {"converted": _transfer_total(result, space.conversion_source_id, space.conversion_target_id),
           "harvested": sum(s.harvested_gains for s in result.yearly_snapshots)}
    # Amounts the added rules moved, beyond what the saved plan already did.
    converted = max(0.0, run["converted"] - baseline_run.get("converted", 0.0)) if "conversion" in spec.actions else 0.0
    harvested = max(0.0, run["harvested"] - baseline_run.get("harvested", 0.0)) if "harvest" in spec.actions else 0.0
    notes: list[str] = []
    if not result.metadata.success:
        notes.append(f"Plan fails in {result.metadata.failure_year} under this strategy.")
    if ("conversion" in spec.actions or "harvest" in spec.actions) and "blend" not in spec.actions \
            and converted <= 0 and harvested <= 0:
        notes.append("No headroom or unrealised gain was available, so the added rules did nothing.")
    candidate = SearchCandidate(
        key=_spec_key(spec), label=_label(spec, space), stage=stage, spec=spec,
        success=result.metadata.success, failure_year=result.metadata.failure_year,
        measures=measures, objective_value=measures.objective_values()[space.objective],
        total_converted=converted, total_harvested=harvested,
        peak_marginal_rate=max((s.marginal_rate for s in result.yearly_snapshots), default=0.0),
        changes=scenario.changes, proposal=scenario.proposal, is_baseline=stage == "baseline", notes=notes,
    )
    return candidate, run


def _tie_value(objective: str, value: float) -> float:
    return round(value, _TIE_DECIMALS.get(objective, 2))


def rank_key(objective: str, candidate: SearchCandidate) -> tuple:
    """Deterministic order: feasible first, then objective, then simplicity.

    Values that agree to the tie precision are equal; ties go to the fewer
    plan changes (the unchanged plan wins), then the lower target rate, then
    the stable candidate key.
    """
    sign = -1.0 if objective_direction(objective) == "higher" else 1.0
    return (
        0 if candidate.success else 1,
        sign * _tie_value(objective, candidate.objective_value),
        len(candidate.changes),
        candidate.spec.rate if candidate.spec.rate is not None else -1.0,
        candidate.key,
    )


def _enumerate_subsets(actions: tuple[str, ...]) -> list[tuple[str, ...]]:
    return [combo for size in range(len(actions), 0, -1) for combo in itertools.combinations(actions, size)]


def grid_specs(space: SearchSpace, rates: tuple[float, ...]) -> list[StrategySpec]:
    """Every combination over ``rates``, ordered simplest first (before dedupe)."""
    windows: list[int | None] = [None, *range(len(space.windows))]
    specs: list[StrategySpec] = [StrategySpec(order=preset) for preset in space.order_presets]
    for rate in rates:
        for subset in _enumerate_subsets(space.enabled_actions):
            for preset in space.order_presets:
                for window in windows:
                    specs.append(StrategySpec(actions=subset, rate=rate, order=preset, window=window))
    return specs


def _complexity(spec: StrategySpec) -> int:
    return len(spec.actions) + (spec.order != "saved") + (spec.window is not None)


def run_search(plan_data: PlanData, space: SearchSpace) -> SearchOutcome:
    """Run the staged search. ``plan_data`` is not modified."""
    if space.objective not in OBJECTIVES:
        raise ValueError(f"Unknown objective {space.objective!r}")
    if not 2 <= space.max_simulations <= MAX_SIMULATIONS:
        raise ValueError(f"max_simulations must be between 2 and {MAX_SIMULATIONS}")
    rates = tuple(sorted(set(space.bracket_rates)))
    actions = space.enabled_actions
    if len(rates) > MAX_RATES or len(space.windows) > MAX_WINDOWS:
        raise ValueError("Too many rates or windows")
    if actions and not rates:
        raise ValueError("Bracket rates are required when an action is selected")
    if rates and not actions:
        raise ValueError("Bracket rates need at least one action")
    if actions and len(rates) + 1 > space.max_simulations:
        raise ValueError("max_simulations is too small for the rate scan")
    unknown = [p for p in space.order_presets if p not in ORDER_PRESETS]
    if unknown:
        raise ValueError(f"Unknown order presets {unknown}")
    # The saved order is always searched: it is the baseline and the sweep's order.
    presets = tuple(dict.fromkeys(("saved", *space.order_presets)))
    space = replace(space, order_presets=presets, bracket_rates=rates)

    discount_rate = pre_tax_discount_rate(plan_data)
    counts = SearchCounts(max_simulations=space.max_simulations)
    cache: dict[str, SearchCandidate] = {}
    baseline_run: dict = {}

    def prepare(spec: StrategySpec) -> tuple[StrategySpec, Scenario]:
        spec = normalize(plan_data, space, spec)
        return spec, materialize(plan_data, space, spec)

    def evaluate(spec: StrategySpec, stage: str) -> SearchCandidate | None:
        """Simulate ``spec`` once per distinct plan; None when the budget is spent."""
        spec, scenario = prepare(spec)
        existing = cache.get(scenario.fingerprint)
        if existing is not None:
            counts.cache_hits += 1
            return existing
        if counts.simulated >= space.max_simulations:
            return None
        candidate, run = _simulate(space, spec, scenario, stage, discount_rate, baseline_run)
        if stage == "baseline":
            baseline_run.update(run)
        cache[scenario.fingerprint] = candidate
        counts.simulated += 1
        if stage == "rate_scan":
            counts.stage1_simulated += 1
        elif stage == "combination":
            counts.stage2_simulated += 1
        return candidate

    # The saved plan is always simulated first, so every figure has a reference.
    baseline = evaluate(StrategySpec(), "baseline")
    assert baseline is not None

    # The whole grid, to report how much of it the search covered.
    grid = grid_specs(space, rates)
    grid_fingerprints = {prepare(s)[1].fingerprint for s in grid} | set(cache)
    counts.grid_requested = len(grid) + 1
    counts.grid_size = len(grid_fingerprints)

    # Stage 1: one candidate per rate, every selected action on.
    scan: list[SearchCandidate] = []
    for rate in rates:
        candidate = evaluate(StrategySpec(actions=actions, rate=rate), "rate_scan")
        if candidate is not None and not candidate.is_baseline:
            scan.append(candidate)
    scan.sort(key=lambda c: rank_key(space.objective, c))
    # Each rate's place in the scan. A rate whose candidate was the saved plan
    # (or another rate's plan) ranks after every scanned one.
    scan_place: dict[float, int] = {}
    for place, candidate in enumerate(scan):
        scan_place.setdefault(candidate.spec.rate, place)

    # Survivors: the best rate (and any rate tied with it) plus neighbouring requested rates.
    survivors: list[float] = []
    if scan:
        best_tie = rank_key(space.objective, scan[0])[:2]
        keep: set[float] = set()
        for candidate in scan:
            if rank_key(space.objective, candidate)[:2] != best_tie:
                break
            index = rates.index(candidate.spec.rate)
            keep.update(rates[max(0, index - 1): index + 2])
        survivors = sorted(keep)
    survivor_set = frozenset(survivors)

    def outside_survivors(spec: StrategySpec) -> bool:
        return spec.rate is not None and spec.rate not in survivor_set

    def priority(spec: StrategySpec) -> tuple:
        # The scan's best rate can sit a step away from the grid's best, and a
        # subset of actions or another order can prefer a different rate, so
        # the other rates are deferred rather than dropped.
        complexity = _complexity(spec)
        tier = int(outside_survivors(spec)) + (2 if complexity > 2 else 0)
        place = -1 if spec.rate is None else scan_place.get(spec.rate, len(rates))
        return (tier, complexity, place, _spec_key(spec))

    # Stage 2: the whole grid in priority order until the budget is spent.
    pending_near: set[str] = set()
    pending_other: set[str] = set()
    for spec in sorted(grid, key=priority):
        if evaluate(spec, "combination") is None:
            fingerprint = prepare(spec)[1].fingerprint
            (pending_other if outside_survivors(spec) else pending_near).add(fingerprint)
    pending_other -= pending_near
    counts.skipped_by_budget = len(pending_near)
    counts.screened_out = len(pending_other)
    counts.budget_exhausted = bool(pending_near or pending_other)

    ranked = sorted(cache.values(), key=lambda c: rank_key(space.objective, c))
    base_tie = _tie_value(space.objective, baseline.objective_value)
    higher = objective_direction(space.objective) == "higher"
    for index, candidate in enumerate(ranked, start=1):
        candidate.rank = index
        candidate.delta_vs_baseline = candidate.objective_value - baseline.objective_value
        tie = _tie_value(space.objective, candidate.objective_value)
        better = tie > base_tie if higher else tie < base_tie
        candidate.improves_baseline = (not candidate.is_baseline) and candidate.success and (
            better or not baseline.success)
    best = ranked[0] if ranked and ranked[0].success else None
    caveats = [
        "Only the candidates listed were simulated; the best of them is not a global optimum.",
        "Rates are ranked with every selected action on; combinations at the best rates and their neighbours are simulated first.",
        "Conversions, harvests and tax-targeted withdrawals share one target: the federal bracket rate being tried.",
        "Bracket headroom is measured before the year's withdrawals; later withdrawals can push income above the target.",
        "A changed tax target also steers tax-targeted withdrawal blending when it is already on.",
        "Net estate and end net worth rankings tax pre-tax balances at one flat rate without the estate tax deduction (IRC 691(c)).",
        "Health coverage effects (ACA credits, IRMAA) are included only when health coverage is modeled for this plan.",
    ]
    if counts.budget_exhausted:
        caveats.append(f"The simulation budget ({space.max_simulations}) ran out; {counts.skipped_by_budget + counts.screened_out} candidates were not simulated.")
    return SearchOutcome(
        objective=space.objective, objective_description=OBJECTIVES[space.objective],
        direction=objective_direction(space.objective), baseline_key="baseline",
        best_key=best.key if best else None, candidates=ranked, counts=counts,
        survivor_rates=survivors, caveats=caveats, pre_tax_discount_rate=discount_rate,
    )

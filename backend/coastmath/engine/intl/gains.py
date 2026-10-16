"""Net capital gain for specs that split the engine's realized gain.

The simulator reports `capital_gains` as the nominal net realized gain and, in
`PersonYear.capital_gain_parts`, how much of it is a deferred pre-transition
gain, how much cost-base indexation removes and how much comes from the main
residence. A spec's capital gains section decides which parts matter:

- `main_residence_exempt`: the main residence gain is removed.
- `cost_base_indexation`: the rest splits into the deferred gain and the gain
  measured on indexed cost bases (the "current" gain). Losses reduce the deferred
  gain first, then the current gain; the deferred gain left is included at
  `deferred_inclusion` and the current gain in full. The result is the net
  capital gain, which the evaluator uses as `capital_gains` income.

Losses are netted within the year from the summed parts, so a loss and a gain of
the same kind offset each other before losses of the other kind apply. A net
loss is not carried forward.

This module imports only `coastmath.engine.intl.types`, so rule modules may use it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from coastmath.engine.intl.types import CapitalGainParts, IncomeType, PersonYear


@dataclass(frozen=True, slots=True)
class NetCapitalGain:
    # Gain on indexed (or nominal) cost bases left after losses, included in full.
    current: float
    # Deferred pre-transition gain left after losses, before its inclusion rate.
    deferred: float
    # current + deferred x deferred inclusion.
    assessable: float


def net_capital_gain(
    gain: float,
    parts: CapitalGainParts | None,
    *,
    deferred_inclusion: float | None,
    main_residence_exempt: bool,
) -> NetCapitalGain:
    """Split `gain` (a person's `capital_gains`) by `parts`.

    `deferred_inclusion` is None when the spec does not index cost bases; the
    gain is then all current (less an exempt main residence gain).
    """
    parts = parts or CapitalGainParts()
    home = max(0.0, parts.main_residence) if main_residence_exempt else 0.0
    if deferred_inclusion is None:
        current = max(0.0, gain - home)
        return NetCapitalGain(current=current, deferred=0.0, assessable=current)
    deferred = parts.deferred
    current = gain - home - deferred - max(0.0, parts.indexation)
    deferred_gain = max(0.0, deferred)
    current_gain = max(0.0, current)
    losses = max(0.0, -deferred) + max(0.0, -current)
    used = min(losses, deferred_gain)
    deferred_gain -= used
    current_gain = max(0.0, current_gain - (losses - used))
    return NetCapitalGain(
        current=current_gain,
        deferred=deferred_gain,
        assessable=current_gain + deferred_gain * deferred_inclusion,
    )


def uses_parts(capital_gains_spec: Any) -> bool:
    """Whether a spec's capital gains section reads `capital_gain_parts`."""
    return capital_gains_spec.cost_base_indexation is not None or capital_gains_spec.main_residence_exempt


def person_net_capital_gain(capital_gains_spec: Any, person: PersonYear) -> NetCapitalGain:
    """`net_capital_gain` for a person's input under a spec's capital gains section."""
    indexation = capital_gains_spec.cost_base_indexation
    return net_capital_gain(
        person.amount(IncomeType.CAPITAL_GAINS),
        person.capital_gain_parts,
        deferred_inclusion=None if indexation is None else indexation.deferred_inclusion,
        main_residence_exempt=capital_gains_spec.main_residence_exempt,
    )

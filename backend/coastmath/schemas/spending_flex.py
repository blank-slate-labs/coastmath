"""Opt-in flexible spending additions shared by saved and stateless plans.

Three additive settings extend the spending rules without touching the legacy
threshold/reduction/floor fields:

* ``upside_thresholds``: points of a spending increase earned when the
  portfolio index is above its earlier all-time high;
* ``flex_scope``: which spending streams the flex multiplier applies to;
* ``surplus_mode``: whether unallocated surplus cash is saved or spent.

Each is omitted from serialized settings while it holds its default, so stored
documents and request bytes without them do not change.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FlexScope = Literal["expenses", "strategy_spending", "leftover_spending"]
SurplusMode = Literal["save", "spend_leftover"]

DEFAULT_FLEX_SCOPE: list[str] = ["expenses"]
MAX_UPSIDE_POINTS = 10
# A point may sit up to 1000% above the earlier high and add up to 200% of
# planned spending; larger values are almost certainly a unit mistake.
MAX_UPSIDE_THRESHOLD = 10.0
MAX_UPSIDE_INCREASE = 2.0


class SpendingUpsidePoint(BaseModel):
    """Spending rises by ``increase`` when the index is ``threshold`` above its high.

    Both are decimal fractions (0.1 is 10%).  The neutral point at zero is
    implicit: no increase at or below the earlier all-time high.
    """

    model_config = ConfigDict(extra="forbid")

    threshold: float = Field(gt=0.0, le=MAX_UPSIDE_THRESHOLD, allow_inf_nan=False)
    increase: float = Field(ge=0.0, le=MAX_UPSIDE_INCREASE, allow_inf_nan=False)


def default_scope(value: list[str]) -> bool:
    """True for the default scope (used to omit it from serialized settings)."""
    return list(value) == DEFAULT_FLEX_SCOPE


def check_spending_flex(
    *,
    upside_thresholds: list[SpendingUpsidePoint],
    flex_scope: list[str],
    surplus_mode: str,
    performance_mode: str,
) -> None:
    """Raise ValueError for an inconsistent combination of the new settings."""
    thresholds = [point.threshold for point in upside_thresholds]
    if len(set(thresholds)) != len(thresholds):
        raise ValueError("upside_thresholds must not repeat a threshold")
    if upside_thresholds and performance_mode != "all_time_high":
        raise ValueError("upside_thresholds require performance_mode 'all_time_high'")
    if not flex_scope:
        raise ValueError("flex_scope needs at least one stream")
    if len(set(flex_scope)) != len(flex_scope):
        raise ValueError("flex_scope must not repeat a stream")
    if "leftover_spending" in flex_scope and surplus_mode != "spend_leftover":
        raise ValueError("flex_scope 'leftover_spending' requires surplus_mode 'spend_leftover'")

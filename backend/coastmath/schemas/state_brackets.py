"""Custom income tax brackets in plan tax settings (state and federal)."""

import math
from functools import partial
from typing import Annotated

from pydantic import AfterValidator, Field

# Far above any real schedule; caps stored JSON and engine work.
MAX_STATE_BRACKETS = 50


def _check_brackets(brackets: list[tuple[float, float]], label: str) -> list[tuple[float, float]]:
    previous_upper = 0.0
    for upper, rate in brackets:
        if not math.isfinite(upper) or upper <= previous_upper:
            raise ValueError(f"{label} bracket upper bounds must be finite, positive and increasing")
        if not 0 <= rate <= 1:
            raise ValueError(f"{label} bracket rates must be between 0 and 1")
        previous_upper = upper
    return brackets


def _check_state_brackets(brackets: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return _check_brackets(brackets, "State")


# (upper bound, rate) pairs in ascending order, the shape of the built-in
# tables. Income above the last bound is untaxed, so a top bracket needs a
# large bound; the built-in tables use 999,999,999. The length bound is
# checked before the brackets themselves.
StateBrackets = Annotated[
    list[tuple[float, float]],
    Field(max_length=MAX_STATE_BRACKETS),
    AfterValidator(_check_state_brackets),
]

# The same shape for a custom federal ordinary-income schedule.
FederalBrackets = Annotated[
    list[tuple[float, float]],
    Field(max_length=MAX_STATE_BRACKETS),
    AfterValidator(partial(_check_brackets, label="Federal")),
]

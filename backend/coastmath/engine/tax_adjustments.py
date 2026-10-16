"""User tax adjustments: deductions, credits and percent surcharges.

The simulator resolves ``tax_settings.adjustments`` (the year's effective
settings, after ``coastmath.engine.tax_schedule``) into nominal amounts for one tax
year; ``coastmath.engine.tax_engine.calculate`` applies them:

- Above-the-line deductions reduce AGI on the returns in their scope. A
  federal-only one is added back to the state base; a state-only one is a
  state subtraction only.
- Itemized deductions never reduce AGI. A federal one joins the federal
  itemized total (allowed for AMT); a state one joins the state itemized
  categories when statutory state deduction rules are in use.
- Surcharges add a percentage of an explicit base to income tax, before
  credits, never to payroll tax, self-employment tax or NIIT.
- Nonrefundable credits reduce income tax (regular tax and AMT, or state
  income tax) to no less than zero. Refundable credits reduce it the same
  way and the rest is refunded: it lowers total tax, which the settlement
  pays out as cash.

Amounts are annual tax-return figures: a start or end milestone inside a year
applies the whole amount for that tax year, and the opening partial year is
not prorated (the engine taxes the full calendar year).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedAdjustment:
    """One adjustment active this tax year, in nominal dollars."""

    id: str
    name: str
    kind: str                     # deduction | credit | surcharge
    scope: str                    # federal | state | both
    deduction_type: str | None = None
    refundable: bool = False
    amount: float = 0.0           # deductions and credits
    rate: float = 0.0             # surcharges
    base: str | None = None       # surcharges
    max_amount: float | None = None

    def applies_to(self, jurisdiction: str) -> bool:
        return self.scope in (jurisdiction, "both")


@dataclass(frozen=True)
class YearAdjustments:
    items: tuple[ResolvedAdjustment, ...] = ()

    def _deductions(self, jurisdiction: str, deduction_type: str) -> float:
        return sum(item.amount for item in self.items if item.kind == "deduction"
                   and item.deduction_type == deduction_type and item.applies_to(jurisdiction))

    @property
    def federal_above_the_line(self) -> float:
        return self._deductions("federal", "above_the_line")

    @property
    def state_above_the_line(self) -> float:
        return self._deductions("state", "above_the_line")

    @property
    def federal_itemized(self) -> float:
        return self._deductions("federal", "itemized")

    @property
    def state_itemized(self) -> float:
        return self._deductions("state", "itemized")

    def credits(self, jurisdiction: str) -> tuple[ResolvedAdjustment, ...]:
        return tuple(item for item in self.items if item.kind == "credit" and item.scope == jurisdiction)

    def surcharges(self, jurisdiction: str) -> tuple[ResolvedAdjustment, ...]:
        return tuple(item for item in self.items if item.kind == "surcharge" and item.scope == jurisdiction)


@dataclass(frozen=True)
class CreditResult:
    tax_after: float              # income tax left after credits, never negative
    applied: float                # credit amount used, including any refund
    refund: float                 # refundable excess paid as cash


def _active(row: Mapping, year: int, plan_start_year: int, milestone_years: Mapping[str, int]) -> bool:
    if row.get("start_year") is not None:
        start = int(row["start_year"])
    elif row.get("start_milestone_id") is not None:
        reached = milestone_years.get(str(row["start_milestone_id"]))
        if reached is None:
            return False
        start = int(reached)
    else:
        start = plan_start_year
    frequency = row.get("frequency", "annual")
    if frequency == "once":
        return year == start
    if year < start:
        return False
    if row.get("end_year") is not None:
        end: int | None = int(row["end_year"])
    elif row.get("end_milestone_id") is not None:
        reached = milestone_years.get(str(row["end_milestone_id"]))
        end = None if reached is None else int(reached)
    else:
        end = None
    if end is not None and year > end:
        return False
    if frequency == "every_n_years":
        return (year - start) % int(row.get("interval_years") or 1) == 0
    return True


def resolve_year_adjustments(
    rows: Iterable[Mapping] | None,
    *,
    year: int,
    plan_start_year: int,
    milestone_years: Mapping[str, int],
    inflation_factor: float,
    owners_on_return: frozenset[str] | set[str],
) -> YearAdjustments | None:
    """The adjustments that apply to ``year``'s return, or None if none do.

    ``inflation_factor`` converts today's (plan-start) dollars to this year's.
    ``owners_on_return`` lists the people whose items still apply; a
    household item always applies.
    """
    resolved = []
    for row in rows or ():
        owner = row.get("owner", "household")
        if owner != "household" and owner not in owners_on_return:
            continue
        if not _active(row, year, plan_start_year, milestone_years):
            continue
        factor = inflation_factor if row.get("amount_basis") == "today" else 1.0
        cap = row.get("max_amount")
        resolved.append(ResolvedAdjustment(
            id=str(row.get("id", "")),
            name=str(row.get("name", "")),
            kind=row["kind"],
            scope=row["scope"],
            deduction_type=row.get("deduction_type"),
            refundable=bool(row.get("refundable", False)),
            amount=max(0.0, float(row.get("amount") or 0.0)) * factor,
            rate=float(row.get("rate") or 0.0),
            base=row.get("base"),
            max_amount=None if cap is None else max(0.0, float(cap)) * factor,
        ))
    return YearAdjustments(tuple(resolved)) if resolved else None


def surcharge_amount(surcharges: Iterable[ResolvedAdjustment], bases: Mapping[str, float]) -> float:
    """Total surcharge on the given non-negative bases, each capped if set."""
    total = 0.0
    for item in surcharges:
        amount = item.rate * max(0.0, bases.get(item.base or "", 0.0))
        if item.max_amount is not None:
            amount = min(amount, item.max_amount)
        total += amount
    return total


def apply_credits(tax: float, credits: Iterable[ResolvedAdjustment]) -> CreditResult:
    """Nonrefundable credits first, then refundable ones (Form 1040 order)."""
    tax = max(0.0, tax)
    items = tuple(credits)
    nonrefundable = sum(item.amount for item in items if not item.refundable)
    refundable = sum(item.amount for item in items if item.refundable)
    used_nonrefundable = min(nonrefundable, tax)
    tax -= used_nonrefundable
    used_against_tax = min(refundable, tax)
    tax -= used_against_tax
    refund = refundable - used_against_tax
    return CreditResult(tax_after=tax, applied=used_nonrefundable + refundable, refund=refund)

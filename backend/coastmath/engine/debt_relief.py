"""One-time loan forgiveness and its federal tax treatment.

Forgiven debt is gross income to the borrower (IRC 61(a)(11)) unless an
exclusion in IRC 108 applies (IRS Publication 4681). The engine never decides
that an exclusion applies: the plan must declare an excluded amount, and the
declared figure is taken as given. Forgiveness creates no cash.
"""

from __future__ import annotations

from collections.abc import Collection

from coastmath.engine.types import DebtForgivenessData, LiabilityState


def forgiveness_from_settings(raw: object) -> DebtForgivenessData | None:
    """The engine event for a stored or requested ``forgiveness`` mapping."""
    if not isinstance(raw, dict):
        return None
    year = raw.get("year")
    milestone_id = raw.get("milestone_id")
    amount = raw.get("amount")
    excluded = raw.get("excluded_amount")
    return DebtForgivenessData(
        year=int(year) if year is not None else None,
        milestone_id=str(milestone_id) if milestone_id is not None else None,
        amount=float(amount) if amount is not None else None,
        tax_treatment=raw.get("tax_treatment") or "taxable",
        excluded_amount=float(excluded) if excluded is not None else None,
        exclusion_basis=raw.get("exclusion_basis"),
    )


def forgiveness_due(event: DebtForgivenessData, year: int, newly_triggered: Collection[str]) -> bool:
    """Whether the event fires this year.

    A milestone fires in the year it is first reached during the projection; a
    milestone already reached before the plan starts is part of the opening
    balances, as is a year before the start.
    """
    if event.year is not None:
        return event.year == year
    return event.milestone_id is not None and event.milestone_id in newly_triggered


def forgiven_amounts(event: DebtForgivenessData, balance: float) -> tuple[float, float]:
    """``(forgiven, taxable)`` dollars for a loan with ``balance`` outstanding.

    ``balance`` is everything owed, including unpaid simple interest: a
    cancelled debt's reportable amount includes interest (Form 1099-C box 2).
    """
    forgiven = max(0.0, balance if event.amount is None else min(event.amount, balance))
    if event.tax_treatment != "declared_exclusion":
        return forgiven, forgiven
    excluded = forgiven if event.excluded_amount is None else min(max(0.0, event.excluded_amount), forgiven)
    return forgiven, forgiven - excluded


def apply_forgiveness(loan: LiabilityState, forgiven: float) -> None:
    """Cancel ``forgiven`` dollars of ``loan``.

    Unpaid simple interest is cancelled before principal, the order in which
    payments settle a simple-interest loan.
    """
    interest_part = min(forgiven, loan.accrued_interest)
    loan.accrued_interest -= interest_part
    loan.remaining_balance = max(0.0, loan.remaining_balance - (forgiven - interest_part))

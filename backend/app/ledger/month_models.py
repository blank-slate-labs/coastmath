"""Turn chosen months into a spending model, with refusals the client can show.

Shared by the spending-model comparison, its apply path and the connected
spending feed's ``months`` basis, so all three resolve the same months to the
same amounts (``app.ledger.months.model_amounts``).
"""
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.errors import api_error
from app.ledger.months import (
    CENT,
    ZERO,
    ModelAmounts,
    MonthSelectionError,
    MonthsResult,
    MonthSummary,
    model_amounts,
    month_start,
    month_summaries,
)

MAX_MONTHS = 12
_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def months_label(keys: list[str]) -> str:
    """``June 2026`` for one month, ``Jun – Aug 2026`` for a span, with a count when months are skipped."""
    ordered = sorted(set(keys))
    first, last = month_start(ordered[0]), month_start(ordered[-1])
    if len(ordered) == 1:
        return f"{_NAMES[first.month - 1]} {first.year}"
    start = _NAMES[first.month - 1][:3] + ("" if first.year == last.year else f" {first.year}")
    label = f"{start} – {_NAMES[last.month - 1][:3]} {last.year}"
    span = (last.year - first.year) * 12 + last.month - first.month + 1
    return label if span == len(ordered) else f"{label} ({len(ordered)} months)"


def average_by_category(months: list[MonthSummary], chosen: list[str]) -> dict[str, Decimal]:
    """Mean monthly spending per category over the chosen months (refunds negative)."""
    picked = [month for month in months if month.month in set(chosen)]
    totals: dict[str, Decimal] = {}
    for month in picked:
        for key, value in month.by_category.items():
            totals[key] = totals.get(key, ZERO) + value
    count = len(picked) or 1
    return {key: (value / count).quantize(CENT) for key, value in sorted(totals.items())}


def selection_error(error: MonthSelectionError, result: MonthsResult) -> HTTPException:
    """422 naming each refused month and why it cannot model spending."""
    by_key = {month.month: month for month in result.months}
    details = []
    for key in error.months:
        month = by_key.get(key)
        reasons = [{"code": reason["code"], "source_ids": [str(value) for value in reason["source_ids"]]}
                   for reason in month.reasons] if month else [{"code": "no_coverage", "source_ids": []}]
        details.append({"month": key, "reasons": reasons})
    return api_error(422, error.code, error.message, details)


@dataclass(frozen=True)
class MonthModel:
    amounts: ModelAmounts
    by_category: dict[str, Decimal]
    result: MonthsResult


def month_model(db: Session, user_id: uuid.UUID, source_ids: list[uuid.UUID] | None, months: list[str],
                currency: str, today: date | None = None) -> MonthModel:
    """Model amounts for the chosen months over these accounts, or a 422 the client can show."""
    return model_from(month_summaries(db, user_id, source_ids, currency, today), months)


def model_from(result: MonthsResult, months: list[str]) -> MonthModel:
    """Model amounts for the chosen months of an existing summary, or a 422 the client can show."""
    try:
        amounts = model_amounts(result.months, months)
    except MonthSelectionError as error:
        raise selection_error(error, result) from error
    return MonthModel(amounts, average_by_category(result.months, amounts.months), result)

"""The unit an income or expense amount was entered in.

A display and entry preference only: ``annual_amount`` remains the value the
engine reads, and nothing converts it on the server. ``None`` marks a record
saved before the unit was stored, which clients open in their legacy default.
The database CHECK constraints ``ck_income_streams_amount_frequency`` and
``ck_expenses_amount_frequency`` list the same values.

Incomes can also be entered as hourly pay (``INCOME_AMOUNT_FREQUENCIES``):
the income keeps ``hourly_rate`` and ``hours_per_week``, and the server sets
``annual_amount`` to rate x hours x ``WEEKS_PER_YEAR`` (``hourly_annual_amount``).
"""
from typing import Literal, get_args

AmountFrequency = Literal["annual", "quarterly", "monthly", "semimonthly", "biweekly", "weekly"]

AMOUNT_FREQUENCIES: tuple[str, ...] = get_args(AmountFrequency)

IncomeAmountFrequency = Literal["annual", "quarterly", "monthly", "semimonthly", "biweekly", "weekly", "hourly"]

INCOME_AMOUNT_FREQUENCIES: tuple[str, ...] = get_args(IncomeAmountFrequency)

#: The clients' money-field cap on a saved yearly amount: past $1 trillion is a typo.
MAX_ANNUAL_AMOUNT = 1e12

#: Paid weeks in a year for hourly pay.
WEEKS_PER_YEAR = 52


def hourly_annual_amount(hourly_rate: float, hours_per_week: float) -> float:
    """Annual pay for an hourly rate and weekly hours, to the cent."""
    return round(float(hourly_rate) * float(hours_per_week) * WEEKS_PER_YEAR, 2)


def check_hourly_fields(frequency: str | None, hourly_rate: float | None, hours_per_week: float | None) -> None:
    """Hourly pay needs both its rate and its hours."""
    if frequency == "hourly" and (hourly_rate is None or hours_per_week is None):
        raise ValueError("Hourly pay needs an hourly rate and hours per week")

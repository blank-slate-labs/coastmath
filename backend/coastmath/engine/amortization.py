"""Core amortization calculator for liabilities.

Provides monthly-loop amortization with support for fixed, percent-of-balance,
and custom payment types, plus offset accounts and extra payments.

Three interest methods are supported (``INTEREST_METHODS``):

- ``monthly`` (the default): interest is charged each month at the annual
  rate / 12 on the balance; unpaid interest is added to the balance.
- ``simple``: interest is charged each month at the annual rate / 12 on the
  principal only. Unpaid interest is carried separately as accrued interest,
  never earns interest itself and is paid before principal.
- ``daily``: interest compounds every day at the annual rate / 365 over the
  actual days of each calendar month (actual/365) and is settled by the
  month's payment; unpaid interest stays in the balance.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass

INTEREST_METHODS = ("monthly", "simple", "daily")


def liability_rate_to_decimal(interest_rate_percent: float) -> float:
    """Convert the stored liability rate (percent, e.g. 5.5) to a decimal (0.055).

    Liabilities are stored and exchanged over the API in percent because that is
    what the loan editor labels and displays. Every engine entry point must pass
    through this helper so the simulator, the standalone schedule and the payment
    preview all describe the same loan.
    """
    return float(interest_rate_percent) / 100.0


@dataclass
class AmortizationResult:
    remaining_balance: float
    interest_paid: float
    principal_paid: float
    interest_capitalized: float = 0.0
    #: Unpaid simple interest carried to the next month (``simple`` only).
    accrued_interest: float = 0.0


@dataclass
class AmortizationScheduleRow:
    year: int
    principal_paid: float
    interest_paid: float
    remaining_balance: float
    cumulative_interest: float
    months_active: int  # 12 normally, less in final year


def monthly_rate_for(annual_rate: float, interest_method: str = "monthly") -> float:
    """The rate for an average month under ``interest_method``.

    Daily compounding over an average month of 365/12 days; the monthly and
    simple methods charge the annual rate / 12.
    """
    if interest_method == "daily":
        return (1.0 + annual_rate / 365.0) ** (365.0 / 12.0) - 1.0
    return annual_rate / 12.0


def calculate_fixed_payment(
    principal: float, annual_rate: float, term_months: int,
    interest_method: str = "monthly",
) -> float:
    """Standard mortgage payment formula.

    Returns the fixed monthly payment for a fully amortizing loan.
    Edge case: if rate is 0, returns principal / term_months. A daily-accrual
    loan uses the average month's compounded rate (``monthly_rate_for``).
    """
    if term_months <= 0:
        return 0.0
    if annual_rate == 0:
        return principal / term_months
    monthly_rate = monthly_rate_for(annual_rate, interest_method)
    factor = (1 + monthly_rate) ** term_months
    return principal * (monthly_rate * factor) / (factor - 1)


def resolve_monthly_payment(
    principal: float,
    annual_rate: float,
    term_months: int | None,
    monthly_payment: float | None,
    payment_type: str,
    interest_method: str = "monthly",
) -> float | None:
    """The entered payment, or the level payment a fixed loan's term implies.

    Saved and stateless plans share this so a term-only fixed loan amortizes
    the same way on both paths. ``annual_rate`` is a decimal.
    """
    if monthly_payment is None and payment_type == "fixed" and term_months:
        return calculate_fixed_payment(principal, annual_rate, term_months, interest_method)
    return monthly_payment


def _month_days(year: int | None, month_index: int) -> float:
    """Days in the calendar month ``month_index`` (1-12) of ``year``.

    Without a calendar year the average month (365/12 days) is used.
    """
    if year is None:
        return 365.0 / 12.0
    return float(calendar.monthrange(year, month_index)[1])


def _month_step(
    balance: float,
    accrued: float,
    annual_rate: float,
    payment: float,
    offset_balance: float,
    month_fraction: float,
    interest_method: str,
    days: float,
) -> tuple[float, float, float, float, float]:
    """One month of a loan: (balance, accrued, interest paid, principal paid, capitalized).

    ``payment`` is the cash available for the month (already prorated).
    """
    effective_balance = max(0.0, balance - offset_balance)
    if interest_method == "simple":
        # Interest on principal only; the unpaid part waits in ``accrued``.
        owed = accrued + effective_balance * annual_rate / 12.0 * month_fraction
        interest_paid = min(payment, owed)
        accrued = owed - interest_paid
        principal_portion = min(balance, payment - interest_paid)
        return balance - principal_portion, accrued, interest_paid, principal_portion, 0.0
    if interest_method == "daily":
        interest = effective_balance * ((1.0 + annual_rate / 365.0) ** (days * month_fraction) - 1.0)
    else:
        monthly_rate = annual_rate / 12.0
        interest = effective_balance * monthly_rate * month_fraction
    principal_portion = payment - interest
    capitalized = 0.0
    if principal_portion < 0:
        # Default contract: unpaid interest capitalizes. Keep cash paid
        # separate so the simulator never spends accrued debt.
        capitalized = -principal_portion
        balance += capitalized
        principal_portion = 0.0
        interest = payment
    principal_portion = min(principal_portion, balance)
    return max(0.0, balance - principal_portion), accrued, interest, principal_portion, capitalized


def calculate_year(
    principal_balance: float,
    annual_rate: float,
    monthly_payment: float,
    extra_payment_annual: float = 0.0,
    offset_balance: float = 0.0,
    payment_type: str = "fixed",
    months: float = 12.0,
    interest_method: str = "monthly",
    accrued_interest: float = 0.0,
    year: int | None = None,
    first_month: int = 1,
) -> AmortizationResult:
    """Simulate up to 12 months of amortization and return the result.

    Args:
        principal_balance: Starting balance for the year.
        annual_rate: Annual interest rate as a decimal (e.g. 0.06 for 6%).
        monthly_payment: Base monthly payment amount.
        extra_payment_annual: Additional annual payment spread across 12 months.
        offset_balance: Offset account balance; reduces effective balance for
            interest calculation only.
        payment_type: One of 'fixed', 'percent_of_balance', 'custom'.
        months: Active months in this simulation year. Fractional final months
            prorate both interest accrual and the scheduled payment.
        interest_method: One of ``INTEREST_METHODS``.
        accrued_interest: Unpaid simple interest carried in from last year.
        year, first_month: Calendar year and first active month, used by the
            daily method to count each month's actual days.
    """
    extra_monthly = extra_payment_annual / 12.0
    balance = principal_balance
    accrued = accrued_interest
    total_interest = 0.0
    total_principal = 0.0
    capitalized_interest = 0.0

    active_months = min(12.0, max(0.0, months))
    full_months = int(active_months)
    month_fractions = [1.0] * full_months
    fractional_month = active_months - full_months
    if fractional_month > 1e-9:
        month_fractions.append(fractional_month)

    for index, month_fraction in enumerate(month_fractions):
        if balance + accrued <= 0.01:
            break

        if payment_type == "percent_of_balance":
            pmt = (balance * (monthly_payment or 0.02) + extra_monthly) * month_fraction
        else:
            pmt = (monthly_payment + extra_monthly) * month_fraction

        month_index = min(12, max(1, first_month + index))
        balance, accrued, interest, principal_portion, capitalized = _month_step(
            balance, accrued, annual_rate, pmt, offset_balance, month_fraction,
            interest_method, _month_days(year, month_index))
        capitalized_interest += capitalized
        total_interest += interest
        total_principal += principal_portion

    return AmortizationResult(
        remaining_balance=balance,
        interest_paid=total_interest,
        principal_paid=total_principal,
        interest_capitalized=capitalized_interest,
        accrued_interest=accrued,
    )


def generate_full_schedule(
    principal: float,
    annual_rate: float,
    term_months: int,
    monthly_payment: float,
    payment_type: str = "fixed",
    extra_payment: float = 0.0,
    offset_balance: float = 0.0,
    interest_method: str = "monthly",
    start_year: int | None = None,
) -> list[AmortizationScheduleRow]:
    """Generate a year-by-year amortization schedule.

    Runs until the balance reaches zero or a 50-year safety cap.

    Args:
        principal: Original loan principal.
        annual_rate: Annual interest rate as a decimal.
        term_months: Original loan term in months.
        monthly_payment: Base monthly payment.
        payment_type: One of 'fixed', 'percent_of_balance', 'custom'.
        extra_payment: Extra annual payment.
        offset_balance: Offset account balance for interest reduction.
            Note: offset_balance is static for schedule generation; dynamic
            offset changes over time are handled by the simulator.
        interest_method: One of ``INTEREST_METHODS``.
        start_year: Calendar year of schedule year 1 (daily method day
            counts); without it every month has 365/12 days.

    Returns:
        List of AmortizationScheduleRow, one per year. ``remaining_balance``
        includes unpaid simple interest.
    """
    schedule: list[AmortizationScheduleRow] = []
    balance = principal
    accrued = 0.0
    cumulative_interest = 0.0
    extra_monthly = extra_payment / 12.0

    for year_num in range(1, 51):  # 50-year cap
        if balance + accrued <= 0.01:
            break

        year_principal = 0.0
        year_interest = 0.0
        months_active = 0
        calendar_year = None if start_year is None else start_year + year_num - 1

        for month_index in range(1, 13):
            if balance + accrued <= 0.01:
                break

            months_active += 1
            if payment_type == "percent_of_balance":
                pmt = balance * (monthly_payment or 0.02) + extra_monthly
            else:
                pmt = monthly_payment + extra_monthly

            # Unpaid interest increases debt; only the payment counts as
            # cash interest paid, matching the simulator.
            balance, accrued, interest, principal_portion, _ = _month_step(
                balance, accrued, annual_rate, pmt, offset_balance, 1.0,
                interest_method, _month_days(calendar_year, month_index))

            year_principal += principal_portion
            year_interest += interest

        cumulative_interest += year_interest
        schedule.append(
            AmortizationScheduleRow(
                year=year_num,
                principal_paid=year_principal,
                interest_paid=year_interest,
                remaining_balance=balance + accrued,
                cumulative_interest=cumulative_interest,
                months_active=months_active,
            )
        )

    return schedule

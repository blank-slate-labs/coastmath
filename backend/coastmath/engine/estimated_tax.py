"""Federal estimated tax payments and the IRC 6654 underpayment addition.

Rules and dated rates: ``coastmath/data/estimated_tax_2026.json``. Sources and
limitations: ``_sources`` in ``estimated_tax_2026.json``.

Opt-in through ``tax_settings.estimated_payments.strategy``. When it is absent
or ``"off"``, :func:`parse_settings` returns None and the simulator runs none
of this module.

**Which tax counts.** IRC 6654(f) "tax" is built from
:class:`~coastmath.engine.types.TaxResult`:

``federal``
    Ordinary income tax, including the AMT excess, after the child tax credit
    (chapter 1).
``capital_gains_tax``
    Federal tax on net capital gains and qualified dividends (chapter 1).
``self_employment_tax``
    Social Security and Medicare on self-employment earnings (chapter 2).
``additional_medicare_tax``
    The 0.9% IRC 3101(b)(2) tax, which 6654(m) treats as chapter 2 tax. The
    engine cannot tell how much an employer withheld, so all of it counts and
    the withholding pool below may cover it, as on Form 2210.
``niit``
    Net investment income tax (chapter 2A).
minus the year's premium tax credit reconciliation
    A net credit is a part IV refundable credit; a repayment of excess advance
    credit is chapter 1 tax. The settlement already carries it as cash.

Left out: ``state`` and ``local`` income tax; employee Social Security and
Medicare on wages (``fica_tax`` less the two payroll items above), which is
not income tax; and the early-withdrawal additional tax, which the engine
pays out of the withdrawal when it is made, so it is left out of both the tax
and the payments. Flat mode reports its one blended tax as ``federal`` plus
``capital_gains_tax``; all of it is treated as federal tax.

**Which payments count.** The engine has one withholding pool, compared with
the year's total tax: income-stream withholding, drawdown and RMD
withholding, and first-year taxes paid before the plan start. The pool first
covers employee payroll tax on wages, which employers always withhold. The
rest is shared between the federal tax above and state plus local tax in
proportion to their amounts. The federal share is treated as withholding,
deemed paid in equal parts on the four due dates (6654(g)(1)).

**Penalty.** Each required installment is 25% of the required annual payment
(6654(d)). Payments are credited to installments in due-date order, so the
unpaid amount after each due date is the required total so far less the
payments so far. It accrues simple interest at the 6621(a)(2) rate in effect
each day, over 365 or 366 days, until the next payment date or April 15 of
the next year (6654(b)). Statutory due dates are used without weekend or
holiday shifts.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from coastmath.engine.types import TaxResult

_DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "estimated_tax_2026.json"
_DATA: dict = json.loads(_DATA_FILE.read_text())

Strategy = Literal["settle_at_filing", "safe_harbor", "pay_in_full"]
STRATEGIES: tuple[str, ...] = ("off", "settle_at_filing", "safe_harbor", "pay_in_full")

# Dated noncorporate underpayment rates, ascending by first day in effect.
RATE_SCHEDULE: tuple[tuple[date, float], ...] = tuple(sorted(
    (date.fromisoformat(row["start"]), float(row["rate"])) for row in _DATA["underpayment_rates"]))

# Unpaid amounts below half a cent are rounding noise, not an underpayment.
_TOLERANCE = .005


@dataclass(frozen=True)
class EstimatedTaxSettings:
    strategy: Strategy
    # First plan year only; later years use the simulated prior year.
    prior_year_total_tax: float | None = None
    prior_year_agi: float | None = None


@dataclass(frozen=True)
class PriorYear:
    """The preceding tax year's 6654(f) tax and AGI. None means unknown."""

    tax: float | None = None
    agi: float | None = None


@dataclass(frozen=True)
class EstimatedTaxYear:
    tax: float
    federal_withholding: float
    required_annual_payment: float
    estimated_payments: float
    underpayment_penalty: float
    agi: float

    def in_year_cash(self, settlement_lag_years: int) -> float:
        """Cash this feature moves in the tax year itself (zero or negative).

        Same-year settlement already pays the whole tax in the year, so
        estimates only shift it earlier; the penalty is the extra outflow. A
        carried balance leaves the estimates as this year's outflow and sends
        the penalty with the balance, as the existing balance-due path does.
        """
        return -(self.underpayment_penalty if settlement_lag_years == 0 else self.estimated_payments)

    def carried_adjustment(self) -> float:
        """Change to a carried settlement: estimates already paid, less the penalty."""
        return self.estimated_payments - self.underpayment_penalty

    def next_prior_year(self) -> PriorYear:
        return PriorYear(tax=self.tax, agi=self.agi)


def parse_settings(tax_settings: dict | None) -> EstimatedTaxSettings | None:
    """The opt-in settings, or None when absent or off."""
    raw = (tax_settings or {}).get("estimated_payments")
    if not raw:
        return None
    strategy = raw.get("strategy", "off")
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown estimated_payments strategy: {strategy}")
    if strategy == "off":
        return None
    prior_tax, prior_agi = raw.get("prior_year_total_tax"), raw.get("prior_year_agi")
    return EstimatedTaxSettings(
        strategy=strategy,
        prior_year_total_tax=None if prior_tax is None else float(prior_tax),
        prior_year_agi=None if prior_agi is None else float(prior_agi),
    )


def first_prior_year(settings: EstimatedTaxSettings) -> PriorYear:
    return PriorYear(tax=settings.prior_year_total_tax, agi=settings.prior_year_agi)


def section_6654_tax(tax: TaxResult, ptc_reconciliation: float = 0.0) -> float:
    """The year's IRC 6654(f) tax; see the module docstring for the mapping."""
    return max(0.0, tax.federal + tax.capital_gains_tax + tax.self_employment_tax
               + tax.additional_medicare_tax + tax.niit - ptc_reconciliation)


def federal_withholding(tax: TaxResult, payments: float, liability: float) -> float:
    """The federal share of the engine's withholding pool."""
    wage_payroll_tax = max(0.0, tax.fica_tax - tax.self_employment_tax - tax.additional_medicare_tax)
    pool = max(0.0, payments - wage_payroll_tax)
    total = liability + max(0.0, tax.state + tax.local)
    return pool if total <= 0 else pool * liability / total


def required_annual_payment(current_tax: float, prior_tax: float | None,
                            prior_agi: float | None, filing_status: str) -> float:
    """IRC 6654(d)(1)(B)-(C): lesser of 90% of this year or 100%/110% of last year.

    An unknown prior year leaves only the current-year share. An unknown
    prior-year AGI uses the 110% share, since the lower share needs AGI at or
    below the threshold. The thresholds are statutory and not indexed.
    """
    rules = _DATA["required_annual_payment"]
    current = rules["current_year_share"] * max(0.0, current_tax)
    if prior_tax is None:
        return current
    threshold = (rules["high_income_agi_threshold_married_filing_separately"]
                 if filing_status == "married_filing_separately" else rules["high_income_agi_threshold"])
    share = (rules["prior_year_share"] if prior_agi is not None and prior_agi <= threshold
             else rules["high_income_prior_year_share"])
    return min(current, share * max(0.0, prior_tax))


def _dated(tax_year: int, spec: dict) -> date:
    return date(tax_year + spec["year_offset"], spec["month"], spec["day"])


def installment_due_dates(tax_year: int) -> tuple[date, ...]:
    return tuple(_dated(tax_year, spec) for spec in _DATA["installment_due_dates"])


def period_end(tax_year: int) -> date:
    return _dated(tax_year, _DATA["period_end"])


def underpayment_rate(day: date, schedule: Sequence[tuple[date, float]] = RATE_SCHEDULE) -> float:
    """The rate in effect on ``day``: the last one published for later days."""
    rate = schedule[0][1]
    for start, value in schedule:
        if start > day:
            break
        rate = value
    return rate


def _accrual(start: date, end: date, schedule: Sequence[tuple[date, float]]) -> float:
    """Simple interest on $1 from ``start`` to ``end`` at the dated rates."""
    total = 0.0
    cursor = start
    while cursor < end:
        boundary = min([end, date(cursor.year + 1, 1, 1)]
                       + [change for change, _ in schedule if change > cursor])
        days_in_year = (date(cursor.year + 1, 1, 1) - date(cursor.year, 1, 1)).days
        total += underpayment_rate(cursor, schedule) * (boundary - cursor).days / days_in_year
        cursor = boundary
    return total


def underpayment_penalty(required: float, withholding: float, estimates_by_quarter: Sequence[float],
                         tax_year: int, schedule: Sequence[tuple[date, float]] = RATE_SCHEDULE) -> float:
    """The 6654 addition for one year's installments (exceptions not applied).

    ``withholding`` is the year's total, deemed paid in equal parts on the due
    dates; ``estimates_by_quarter`` are paid on their due dates.
    """
    if len(estimates_by_quarter) != 4:
        raise ValueError("estimates_by_quarter needs one amount per installment")
    share = _DATA["installment_share"]
    dates = (*installment_due_dates(tax_year), period_end(tax_year))
    unpaid = 0.0
    penalty = 0.0
    for index, estimate in enumerate(estimates_by_quarter):
        unpaid += share * required - share * withholding - estimate
        if unpaid >= _TOLERANCE:
            penalty += unpaid * _accrual(dates[index], dates[index + 1], schedule)
    return penalty


def evaluate_year(settings: EstimatedTaxSettings, *, tax_year: int, filing_status: str,
                  tax: TaxResult, payments: float, ptc_reconciliation: float,
                  prior: PriorYear) -> EstimatedTaxYear:
    """Estimates, required annual payment and penalty for one tax year.

    ``payments`` is the engine's whole withholding pool for the year.
    """
    liability = section_6654_tax(tax, ptc_reconciliation)
    withholding = federal_withholding(tax, payments, liability)
    required = required_annual_payment(liability, prior.tax, prior.agi, filing_status)
    if settings.strategy == "safe_harbor":
        estimates = max(0.0, required - withholding)
    elif settings.strategy == "pay_in_full":
        estimates = max(0.0, liability - withholding)
    else:
        estimates = 0.0
    small_balance = liability - withholding < _DATA["minimum_balance_due"]  # 6654(e)(1)
    no_prior_liability = prior.tax is not None and prior.tax < _TOLERANCE  # 6654(e)(2)
    penalty = 0.0 if small_balance or no_prior_liability else underpayment_penalty(
        required, withholding, [estimates * _DATA["installment_share"]] * 4, tax_year)
    return EstimatedTaxYear(
        tax=liability,
        federal_withholding=withholding,
        required_annual_payment=required,
        estimated_payments=estimates,
        underpayment_penalty=penalty,
        agi=tax.modified_agi,
    )

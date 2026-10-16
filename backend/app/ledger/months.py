"""Month summaries with explicit completeness, and spending models from months.

A month is complete only when every selected account covers every day of it,
so a partial month can never masquerade as cheap:

- synced providers cover ``[transactions_coverage_start, last read]``, and a
  month must end at least ``SETTLE_DAYS`` before the read so late postings land;
- file accounts cover the union of their committed imports' statement periods,
  with no settle delay; gaps between imports matter.

The trailing average that keeps a plan's connected spending current
(``trailing_summary`` and ``annual_amounts``) also lives here.
"""
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.ledger.accounts import counts_toward_spending, source_label
from app.ledger.categories import TAKE_HOME, UNCATEGORIZED
from app.ledger.classify import (
    DEFAULT_CURRENCY,
    EXCLUDED_KINDS,
    PAIR_DAYS,
    LedgerTxn,
    classify,
    from_row,
)
from app.ledger.environments import active_filter
from app.ledger.rules import Rule
from app.ledger.store import RETENTION_DAYS
from app.models.financial_connection import (
    FinancialSource,
    FinancialTransaction,
    utcnow,
)
from app.models.ledger import FinancialImport, FinancialRule

# Pending card transactions post within days; wait before treating a month as final.
SETTLE_DAYS = 5
CENT = Decimal("0.01")
ZERO = Decimal(0)
# Duplicate-account check: at least this many posted rows in the smaller account,
# at least this share of them matched by amount and date within MATCH_DAYS.
DUPLICATE_MIN = 10
DUPLICATE_SHARE = Decimal("0.5")
MATCH_DAYS = 1


# --- calendar helpers ---------------------------------------------------------

def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def next_month(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def first_complete_month(coverage_start: date) -> date:
    return coverage_start if coverage_start.day == 1 else next_month(coverage_start)


def month_start(key: str) -> date:
    year, month = key.split("-")
    return date(int(year), int(month), 1)


def merge_intervals(intervals: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """Union of inclusive date intervals; adjacent days join."""
    merged: list[tuple[date, date]] = []
    for start, end in sorted(i for i in intervals if i[0] <= i[1]):
        if merged and start <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def covers(intervals: list[tuple[date, date]], start: date, end: date) -> bool:
    return any(lo <= start and end <= hi for lo, hi in intervals)


def overlaps(intervals: list[tuple[date, date]], start: date, end: date) -> bool:
    return any(lo <= end and start <= hi for lo, hi in intervals)


# --- the trailing average used by spending feeds ------------------------------

@dataclass
class Month:
    month: str
    essential: Decimal = ZERO
    discretionary: Decimal = ZERO
    income: Decimal = ZERO
    by_category: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class Summary:
    months: list[Month]
    coverage_start: date | None
    average_essential: Decimal
    average_discretionary: Decimal
    average_income: Decimal
    excluded: dict[str, Decimal]
    waiting_for: list[str]
    # Unrounded sums over `months`; annual amounts round once, from these.
    total_essential: Decimal = ZERO
    total_discretionary: Decimal = ZERO

    @property
    def average_spending(self) -> Decimal:
        return self.average_essential + self.average_discretionary


def trailing_summary(txns: list[LedgerTxn], coverage: dict[str, tuple[date | None, date | None]],
                     names: dict[str, str], today: date, max_months: int = 12, rules: list[Rule] = (),
                     currency: str = DEFAULT_CURRENCY, complete: list[str] | None = None) -> Summary:
    """Average spending across the most recent months every source fully covers.

    `coverage` maps each chosen spending source to (first day of complete
    history, day its transactions were last read); None while still loading.
    A month counts only when every source covers all of it and it ended at
    least SETTLE_DAYS before the oldest read, so late postings are included.
    A card with 30 days of history cannot make an older month look cheaper, and
    a disconnected card cannot make later months look cheaper.

    ``complete`` (``YYYY-MM`` keys, oldest first) replaces the months derived
    from ``coverage`` for callers that judged completeness with ``month_frame``
    (file accounts' coverage has gaps); ``coverage`` then only selects the
    sources and names those still loading.
    """
    waiting = sorted(names.get(source_id, "A connected account")
                     for source_id, (start, through) in coverage.items() if start is None or through is None)
    starts = [start for start, _ in coverage.values() if start is not None]
    throughs = [through for _, through in coverage.values() if through is not None]
    coverage_start = max(starts) if starts and not waiting else None
    months: list[Month] = []
    if complete is not None:
        months = [Month(key) for key in complete[-max_months:]] if coverage_start is not None else []
    elif coverage_start is not None:
        limit = min([*throughs, today])
        cursor = first_complete_month(coverage_start)
        while next_month(cursor) + timedelta(days=SETTLE_DAYS) <= limit:
            months.append(Month(month_key(cursor)))
            cursor = next_month(cursor)
        months = months[-max_months:]
    by_key = {m.month: m for m in months}
    excluded: dict[str, Decimal] = defaultdict(Decimal)
    labels = classify(txns, rules, currency)
    for txn in txns:
        if txn.source_id not in coverage:
            continue
        month = by_key.get(month_key(txn.day))
        if month is None:
            continue
        label = labels[txn.id]
        if label.kind in {"spending", "refund"}:
            setattr(month, label.bucket, getattr(month, label.bucket) + label.value)
            month.by_category[label.category] = month.by_category.get(label.category, ZERO) + label.value
        elif label.kind == "income":
            if label.category in TAKE_HOME:
                month.income += label.value
        elif label.kind in EXCLUDED_KINDS:
            excluded[label.kind] += label.value
    count = len(months)

    def average(values) -> Decimal:
        return (sum(values, ZERO) / count).quantize(CENT) if count else ZERO

    total_essential = sum((m.essential for m in months), ZERO)
    total_discretionary = sum((m.discretionary for m in months), ZERO)
    for month in months:
        month.essential, month.discretionary = month.essential.quantize(CENT), month.discretionary.quantize(CENT)
        month.income = month.income.quantize(CENT)
        month.by_category = {key: value.quantize(CENT) for key, value in sorted(month.by_category.items())}
    return Summary(
        months=months, coverage_start=coverage_start,
        average_essential=average(m.essential for m in months),
        average_discretionary=average(m.discretionary for m in months),
        average_income=average(m.income for m in months),
        excluded={key: (value / count).quantize(CENT) for key, value in sorted(excluded.items())} if count else {},
        waiting_for=waiting,
        total_essential=total_essential, total_discretionary=total_discretionary,
    )


def annual_amounts(summary: Summary) -> tuple[Decimal, Decimal]:
    """Annual essential and discretionary spending; refunds cannot go below zero."""
    count = len(summary.months)
    if not count:
        return Decimal("0.00"), Decimal("0.00")
    return tuple(max(total * 12 / count, ZERO).quantize(CENT)
                 for total in (summary.total_essential, summary.total_discretionary))


# --- loading ------------------------------------------------------------------

def load_ledger(db: Session, user_id: uuid.UUID, since: date) -> list[LedgerTxn]:
    """Every transaction of the user's active (provider, environment) pairs since a day."""
    rows = db.query(FinancialTransaction).filter(
        FinancialTransaction.user_id == user_id, active_filter(FinancialTransaction),
        FinancialTransaction.transaction_date >= since).all()
    return [from_row(row) for row in rows]


def load_rules(db: Session, user_id: uuid.UUID) -> list[Rule]:
    return [Rule.from_row(row) for row in db.query(FinancialRule).filter_by(user_id=user_id).all()]


def active_sources(db: Session, user_id: uuid.UUID) -> list[FinancialSource]:
    return db.query(FinancialSource).filter(
        FinancialSource.user_id == user_id, active_filter(FinancialSource)).order_by(
        FinancialSource.institution_name, FinancialSource.name, FinancialSource.id).all()


# --- coverage -----------------------------------------------------------------

@dataclass
class Coverage:
    """``seen``: days with any data; ``settled``: days complete enough to count."""
    source_id: str
    provider: str
    name: str
    seen: list[tuple[date, date]]
    settled: list[tuple[date, date]]
    waiting: bool


def import_periods(db: Session, source_ids: list[uuid.UUID]) -> dict[str, list[tuple[date, date]]]:
    periods: dict[str, list[tuple[date, date]]] = defaultdict(list)
    if source_ids:
        for row in db.query(FinancialImport).filter(
                FinancialImport.source_id.in_(source_ids), FinancialImport.status == "committed").all():
            periods[str(row.source_id)].append((row.date_from, row.date_to))
    return periods


def source_coverage(source: FinancialSource, today: date, periods: list[tuple[date, date]]) -> Coverage:
    name = source_label(source)
    if source.provider == "file":
        merged = merge_intervals(periods)
        return Coverage(str(source.id), source.provider, name, merged, merged, not merged)
    start = source.transactions_coverage_start
    if start is None or source.transactions_synced_at is None:
        return Coverage(str(source.id), source.provider, name, [], [], True)
    through = min(source.transactions_synced_at.date(), today)
    # A month must end SETTLE_DAYS before the read: its last settled day is one earlier.
    settled_through = through - timedelta(days=SETTLE_DAYS + 1)
    return Coverage(str(source.id), source.provider, name, merge_intervals([(start, through)]),
                    merge_intervals([(start, settled_through)]), False)


# --- month summaries ----------------------------------------------------------

@dataclass
class MonthSummary:
    month: str
    complete: bool
    reasons: list[dict]
    essential: Decimal = ZERO
    discretionary: Decimal = ZERO
    income: Decimal = ZERO
    income_wages: Decimal = ZERO
    by_category: dict[str, Decimal] = field(default_factory=dict)
    income_by_category: dict[str, Decimal] = field(default_factory=dict)
    excluded: dict[str, Decimal] = field(default_factory=dict)
    one_time: Decimal = ZERO
    one_time_count: int = 0
    uncategorized_outflow: Decimal = ZERO
    transaction_count: int = 0
    pending_count: int = 0


@dataclass
class DuplicateWarning:
    source_ids: list[str]
    matched: int
    compared: int


@dataclass
class MonthsResult:
    months: list[MonthSummary]
    sources: list[Coverage]
    duplicates: list[DuplicateWarning]
    currency: str


class MonthSelectionError(ValueError):
    """``code`` is MONTH_REQUIRED, MONTH_UNKNOWN or MONTH_INCOMPLETE."""

    def __init__(self, code: str, message: str, months: list[str] | None = None):
        super().__init__(message)
        self.code, self.message, self.months = code, message, months or []


def month_reasons(start: date, end: date, today: date, coverages: list[Coverage]) -> list[dict]:
    if end >= today:
        return [{"code": "in_progress", "source_ids": []}]
    grouped: dict[str, list[str]] = defaultdict(list)
    for coverage in coverages:
        if coverage.waiting:
            grouped["waiting_for_history"].append(coverage.source_id)
        elif covers(coverage.settled, start, end):
            continue
        elif covers(coverage.seen, start, end):
            grouped["settling"].append(coverage.source_id)
        else:
            grouped["partial_coverage"].append(coverage.source_id)
    return [{"code": code, "source_ids": ids} for code, ids in grouped.items()]


def duplicate_warnings(txns: list[LedgerTxn], source_ids: list[str]) -> list[DuplicateWarning]:
    """Two selected accounts that share most of their posted transactions.

    The same card can arrive twice (a file import and a sync, or two logins).
    Matching is one-to-one by amount, with dates at most MATCH_DAYS apart.
    """
    posted: dict[str, list[LedgerTxn]] = defaultdict(list)
    for txn in txns:
        if txn.status == "POSTED" and txn.source_id in source_ids:
            posted[txn.source_id].append(txn)
    warnings = []
    ordered = sorted(posted)
    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            small, large = sorted((posted[first], posted[second]), key=len)
            if len(small) < DUPLICATE_MIN:
                continue
            by_amount: dict[Decimal, list[LedgerTxn]] = defaultdict(list)
            for txn in large:
                by_amount[txn.amount].append(txn)
            used: set[str] = set()
            matched = 0
            for txn in sorted(small, key=lambda t: (t.day, t.id)):
                candidate = min((other for other in by_amount.get(txn.amount, [])
                                 if other.id not in used and abs((other.day - txn.day).days) <= MATCH_DAYS),
                                key=lambda other: (abs((other.day - txn.day).days), other.id), default=None)
                if candidate is not None:
                    used.add(candidate.id)
                    matched += 1
            if matched >= DUPLICATE_SHARE * len(small):
                warnings.append(DuplicateWarning([first, second], matched, len(small)))
    return warnings


def default_source_ids(db: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    return [source.id for source in active_sources(db, user_id) if counts_toward_spending(source)]


def month_frame(db: Session, user_id: uuid.UUID, source_ids: list[uuid.UUID] | None,
                today: date) -> tuple[list[Coverage], list[MonthSummary]]:
    """The selected accounts' coverage and every month inside retention, without amounts.

    Completeness depends on coverage alone, so a caller that only needs to know
    which months are complete skips the ledger read.
    """
    wanted = set(source_ids) if source_ids is not None else set(default_source_ids(db, user_id))
    sources = [source for source in active_sources(db, user_id) if source.id in wanted]
    periods = import_periods(db, [source.id for source in sources if source.provider == "file"])
    coverages = [source_coverage(source, today, periods.get(str(source.id), [])) for source in sources]
    first_month = first_complete_month(today - timedelta(days=RETENTION_DAYS))
    seen = merge_intervals([interval for coverage in coverages for interval in coverage.seen])
    months: list[MonthSummary] = []
    if seen:
        cursor = max(seen[0][0].replace(day=1), first_month)
        last = min(seen[-1][1], today)
        while cursor <= last:
            end = next_month(cursor) - timedelta(days=1)
            if overlaps(seen, cursor, end):
                reasons = month_reasons(cursor, end, today, coverages)
                months.append(MonthSummary(month_key(cursor), not reasons, reasons))
            cursor = next_month(cursor)
    return coverages, months


def month_summaries(db: Session, user_id: uuid.UUID, source_ids: list[uuid.UUID] | None = None,
                    currency: str = DEFAULT_CURRENCY, today: date | None = None) -> MonthsResult:
    """Every month any selected account covers inside retention, oldest first.

    ``source_ids`` defaults to the accounts that count toward spending; IDs of
    other users or inactive environments are ignored. The current month is
    never complete.
    """
    today = today or utcnow().date()
    coverages, months = month_frame(db, user_id, source_ids, today)
    first_month = first_complete_month(today - timedelta(days=RETENTION_DAYS))
    txns = load_ledger(db, user_id, first_month - timedelta(days=PAIR_DAYS))
    selected = {coverage.source_id for coverage in coverages}
    _aggregate(months, txns, selected, load_rules(db, user_id), currency)
    return MonthsResult(months, coverages, duplicate_warnings(
        [txn for txn in txns if txn.day >= first_month], sorted(selected)), currency)


def _add(totals: dict[str, Decimal], key: str, value: Decimal) -> None:
    totals[key] = totals.get(key, ZERO) + value


def _aggregate(months: list[MonthSummary], txns: list[LedgerTxn], selected: set[str], rules: list[Rule],
               currency: str) -> None:
    by_key = {month.month: month for month in months}
    labels = classify(txns, rules, currency)
    for txn in txns:
        month = by_key.get(month_key(txn.day)) if txn.source_id in selected else None
        if month is None:
            continue
        label = labels[txn.id]
        month.transaction_count += 1
        if label.kind == "pending":
            month.pending_count += 1
        elif label.kind in {"spending", "refund"}:
            setattr(month, label.bucket, getattr(month, label.bucket) + label.value)
            _add(month.by_category, label.category, label.value)
            if label.category == UNCATEGORIZED and label.value > 0:
                month.uncategorized_outflow += label.value
        elif label.kind == "income":
            _add(month.income_by_category, label.category, label.value)
            if label.category in TAKE_HOME:
                month.income += label.value
            if label.category == "income_wages":
                month.income_wages += label.value
        elif label.kind == "one_time":
            month.one_time += label.value
            month.one_time_count += 1
        elif label.kind in EXCLUDED_KINDS:
            # Rows the customer excluded total their size, so the review shows what was left out.
            _add(month.excluded, label.kind, abs(txn.amount) if label.kind == "excluded" else label.value)
    for month in months:
        month.by_category = dict(sorted(month.by_category.items()))
        month.income_by_category = dict(sorted(month.income_by_category.items()))
        month.excluded = dict(sorted(month.excluded.items()))


# --- spending models from months ----------------------------------------------

@dataclass(frozen=True)
class ModelAmounts:
    months: list[str]
    annual_essential: Decimal
    annual_discretionary: Decimal
    monthly_take_home: Decimal


def model_amounts(months: list[MonthSummary], chosen: list[str]) -> ModelAmounts:
    """``12 ×`` the mean of the chosen complete months, floored at zero, and mean take-home."""
    keys = list(dict.fromkeys(chosen))
    if not keys:
        raise MonthSelectionError("MONTH_REQUIRED", "Choose at least one month.")
    by_key = {month.month: month for month in months}
    unknown = [key for key in keys if key not in by_key]
    if unknown:
        raise MonthSelectionError("MONTH_UNKNOWN", "A chosen month has no coverage.", unknown)
    incomplete = [key for key in keys if not by_key[key].complete]
    if incomplete:
        raise MonthSelectionError("MONTH_INCOMPLETE", "Only complete months can model spending.", incomplete)
    picked = [by_key[key] for key in keys]
    count = len(picked)

    def annual(attr: str) -> Decimal:
        return max(sum((getattr(m, attr) for m in picked), ZERO) * 12 / count, ZERO).quantize(CENT)

    return ModelAmounts(keys, annual("essential"), annual("discretionary"),
                        (sum((m.income for m in picked), ZERO) / count).quantize(CENT))

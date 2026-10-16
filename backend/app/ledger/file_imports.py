"""File imports: parse an upload, preview it, commit it into a ``file`` account, revert it.

A committed import records its statement period in ``financial_imports``; that
period is the coverage months read for file accounts, so a confirmed June
statement is what makes June complete. Imports never delete rows outside what
the file itself says: OFX correction records and pending rows the new file no
longer contains inside its period.

Ownership: a row carries only the import that first inserted it. Reverting an
import removes its rows, except rows inside another committed import's range on
the same account (overlapping statements contain the same transactions), which
move to that import instead. An import's range is its statement period, widened
to the dates of the rows its file held (OFX rows can fall outside DTSTART and
DTEND; CSV periods must contain every row).

Nothing here logs or returns file content in errors: IDs, codes and counts only.
"""
import base64
import binascii
import hashlib
import logging
import uuid
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ledger.categories import category_for
from app.ledger.environments import active_filter, environment_for
from app.ledger.feeds import apply_feeds, feeds_using, refresh_feeds
from app.ledger.importers import (
    CsvMapping,
    CsvParseResult,
    CsvPreview,
    DateDetection,
    ImportFileError,
    OfxParseResult,
    OfxStatement,
    detect_file_format,
    detect_mapped_dates,
    parse_csv,
    parse_ofx,
    preview_csv,
)
from app.ledger.months import next_month
from app.ledger.rules import Rule, best_rule, normalize, order
from app.ledger.store import (
    RETENTION_DAYS,
    StoreResult,
    chunks,
    stored_id,
    upsert_transactions,
)
from app.ledger.types import NormalizedTransaction
from app.models.financial_connection import (
    FinancialBalanceLink,
    FinancialSource,
    FinancialTransaction,
    utcnow,
)
from app.models.ledger import FinancialImport, FinancialRule

logger = logging.getLogger(__name__)

PROVIDER = "file"
DEFAULT_CURRENCY = "USD"
DEFAULT_INSTITUTION = "Imported"
#: Rows a preview shows as they would import.
SAMPLE_ROWS = 10
MAX_PREVIEW_ISSUES = 20
#: Matches ``POST /ledger/rules``.
MAX_RULES = 500
#: A file committed into a new account of the same name this soon after an
#: earlier commit of it repeats that request (a double submit or a retry).
REPEAT_WINDOW = timedelta(minutes=10)


class FileImportError(Exception):
    """A refused import step. ``status`` and ``code`` follow the shared error envelope."""

    def __init__(self, code: str, message: str, status: int = 422, details: list[dict] | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details or []


def from_parser(error: ImportFileError) -> FileImportError:
    """Parser errors carry limits or field names, never file content."""
    details = [{"field": str(value) if key == "field" else key, "reason": error.message if key == "field" else str(value)}
               for key, value in error.details.items()]
    return FileImportError(error.code, error.message, 422, details)


# --- upload -------------------------------------------------------------------

@dataclass(frozen=True)
class Upload:
    data: bytes
    sha256: str
    format: str  # csv | ofx


def decode_upload(content_base64: str) -> Upload:
    try:
        data = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise FileImportError("VALIDATION_ERROR", "The file could not be read.",
                              details=[{"field": "content_base64", "reason": "invalid base64"}]) from exc
    try:
        kind = detect_file_format(data)
    except ImportFileError as exc:
        raise from_parser(exc) from exc
    if kind == "unknown":
        raise FileImportError("UNSUPPORTED_FORMAT", "Choose a CSV, OFX or QFX file.")
    return Upload(data, hashlib.sha256(data).hexdigest(), kind)


def csv_mapping(raw: dict[str, Any]) -> CsvMapping:
    try:
        return CsvMapping.from_dict(raw)
    except ImportFileError as exc:
        raise from_parser(exc) from exc


def read_csv(upload: Upload, mapping: CsvMapping, account_external_id: str = "file") -> CsvParseResult:
    try:
        return parse_csv(upload.data, mapping, account_external_id=account_external_id)
    except ImportFileError as exc:
        raise from_parser(exc) from exc


def read_ofx(upload: Upload) -> OfxParseResult:
    try:
        return parse_ofx(upload.data)
    except ImportFileError as exc:
        raise from_parser(exc) from exc


def read_csv_preview(upload: Upload) -> CsvPreview:
    try:
        return preview_csv(upload.data)
    except ImportFileError as exc:
        raise from_parser(exc) from exc


def read_mapped_dates(upload: Upload, mapping: CsvMapping) -> DateDetection:
    try:
        return detect_mapped_dates(upload.data, mapping)
    except ImportFileError as exc:
        raise from_parser(exc) from exc


def retention_cutoff(today: date) -> date:
    """The first transaction date an import keeps; earlier rows are skipped."""
    return today - timedelta(days=RETENTION_DAYS)


def before_retention(rows: list[NormalizedTransaction], today: date) -> int:
    cutoff = retention_cutoff(today)
    return sum(1 for row in rows if row.transaction_date < cutoff)


# --- periods ------------------------------------------------------------------

def month_end(day: date) -> date:
    return next_month(day.replace(day=1)) - timedelta(days=1)


@dataclass(frozen=True)
class PeriodBounds:
    """The file's own dates (the suggested period); a confirmed period contains
    them and lies in ``[earliest, latest]``: whole months, never past today."""
    rows_from: date
    rows_to: date
    earliest: date
    latest: date


def period_bounds(rows_from: date, rows_to: date, today: date) -> PeriodBounds:
    return PeriodBounds(rows_from, rows_to, rows_from.replace(day=1), max(rows_to, min(month_end(rows_to), today)))


def check_period(bounds: PeriodBounds, start: date, end: date) -> None:
    if start > end:
        raise FileImportError("INVALID_PERIOD", "The statement period ends before it starts.",
                              details=[{"field": "period", "reason": "order"}])
    if start > bounds.rows_from or end < bounds.rows_to:
        raise FileImportError("INVALID_PERIOD", "The statement period must include every transaction in the file.",
                              details=[{"field": "period", "reason": "rows_outside"}])
    if start < bounds.earliest or end > bounds.latest:
        raise FileImportError("INVALID_PERIOD", "The statement period can extend only to whole months of the file.",
                              details=[{"field": "period", "reason": "beyond_file"}])


def ofx_period(statement: OfxStatement) -> tuple[date, date] | None:
    """The statement's own period; the rows' dates fill a missing edge."""
    days = [row.transaction_date for row in statement.transactions]
    start = statement.period_start or (min(days) if days else None)
    end = statement.period_end or (max(days) if days else None)
    if start is None or end is None:
        return None
    return start, max(start, end)


def choose_statement(result: OfxParseResult, index: int | None) -> tuple[int, OfxStatement]:
    if index is None:
        if len(result.statements) > 1:
            raise FileImportError("STATEMENT_REQUIRED", "Choose which account in the file to import.",
                                  details=[{"field": "statement_index", "reason": "required"}])
        index = 0
    if index >= len(result.statements):
        raise FileImportError("VALIDATION_ERROR", "That account is not in the file.",
                              details=[{"field": "statement_index", "reason": "out of range"}])
    return index, result.statements[index]


# --- accounts, duplicates and categories --------------------------------------

def file_sources(db: Session, user_id: uuid.UUID):
    return db.query(FinancialSource).filter(FinancialSource.user_id == user_id, FinancialSource.provider == PROVIDER,
                                            active_filter(FinancialSource))


def file_source(db: Session, user_id: uuid.UUID, source_id: uuid.UUID) -> FinancialSource:
    source = db.query(FinancialSource).filter(FinancialSource.id == source_id, FinancialSource.user_id == user_id,
                                              active_filter(FinancialSource)).first()
    if source is None:
        raise FileImportError("NOT_FOUND", "Account not found.", 404)
    if source.provider != PROVIDER:
        raise FileImportError("VALIDATION_ERROR", "Import files only into imported accounts.",
                              details=[{"field": "source_id", "reason": "not a file account"}])
    return source


def source_by_external(db: Session, user_id: uuid.UUID, external_id: str) -> FinancialSource | None:
    return file_sources(db, user_id).filter(FinancialSource.provider_account_id == external_id).first()


def existing_count(db: Session, source: FinancialSource, rows: list[NormalizedTransaction]) -> int:
    """Rows of the file already stored in this account."""
    keys = list({stored_id(source, row.external_id) for row in rows})
    count = 0
    for part in chunks(keys):
        count += db.query(FinancialTransaction.id).filter(
            FinancialTransaction.source_id == source.id,
            FinancialTransaction.provider_transaction_id.in_(part)).count()
    return count


def previous_import(db: Session, source: FinancialSource | None, sha256: str) -> FinancialImport | None:
    if source is None:
        return None
    return db.query(FinancialImport).filter(FinancialImport.source_id == source.id, FinancialImport.file_sha256 == sha256,
                                            FinancialImport.status == "committed").order_by(
        FinancialImport.created_at.desc()).first()


def category_rules(db: Session, user_id: uuid.UUID, source_id: uuid.UUID | None) -> list[Rule]:
    """The user's direction-free bank-category rules that apply to this account."""
    rows = db.query(FinancialRule).filter(FinancialRule.user_id == user_id,
                                          FinancialRule.match_field == "provider_category",
                                          FinancialRule.direction == "any").all()
    return order([Rule.from_row(row) for row in rows if row.source_id is None or row.source_id == source_id])


def suggest_category(value: str, rules: list[Rule], source_id: uuid.UUID | None) -> tuple[str | None, str | None]:
    """(category, ``rule`` | ``alias``) the ledger would give this raw category.

    Text aliases give the default; one of the user's rules overrides it, as it
    does when transactions are classified.
    """
    rule = best_rule(rules, source_id=str(source_id) if source_id else "", amount=1, description=None,
                     merchant=None, provider_category=value)
    if rule is not None:
        return rule.category, "rule"
    alias = category_for(PROVIDER, value)
    return (alias, "alias") if alias else (None, None)


def category_counts(rows: list[NormalizedTransaction], limit: int = 200) -> list[tuple[str, int]]:
    counts = Counter(row.provider_category for row in rows if row.provider_category)
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]


def save_category_rules(db: Session, user_id: uuid.UUID, source: FinancialSource,
                        choices: list[tuple[str, str]]) -> int:
    """Keep confirmed choices that differ from what the ledger would do as
    ``provider_category``/``equals`` rules scoped to the account; returns how
    many rules were added or changed."""
    rules = category_rules(db, user_id, source.id)
    changed = 0
    for value, category in dict(choices).items():
        pattern = normalize(value)[:100].strip()
        if not pattern or (suggest_category(value, rules, source.id)[0] or "uncategorized") == category:
            continue
        rule = db.query(FinancialRule).filter_by(user_id=user_id, match_field="provider_category", match_type="equals",
                                                 pattern=pattern, source_id=source.id, direction="any").first()
        if rule is None:
            if db.query(FinancialRule.id).filter_by(user_id=user_id).count() >= MAX_RULES:
                raise FileImportError("VALIDATION_ERROR", "Remove an unused rule before mapping more categories.")
            rule = FinancialRule(user_id=user_id, match_field="provider_category", match_type="equals",
                                 pattern=pattern, source_id=source.id, direction="any", category=category)
            db.add(rule)
        else:
            rule.category, rule.updated_at = category, utcnow()
        db.flush()
        rules = category_rules(db, user_id, source.id)
        changed += 1
    return changed


# --- preview ------------------------------------------------------------------

def sample_rows(rows: list[NormalizedTransaction]) -> list[dict]:
    return [dict(date=row.transaction_date, amount=float(row.amount), description=row.description,
                 merchant_name=row.merchant_name, category=row.provider_category, status=row.status,
                 currency=row.currency) for row in rows[:SAMPLE_ROWS]]


def csv_preview(db: Session, user_id: uuid.UUID, upload: Upload, source: FinancialSource | None,
                mapping: dict[str, Any] | None, today: date) -> dict:
    found = read_csv_preview(upload)
    date_formats, date_ambiguous = found.date_formats, found.date_ambiguous
    date_column = next((c.index for c in found.columns if c.suggested_role == "date"), None)
    if mapping is None:
        chosen = found.suggested_mapping.to_dict() if found.suggested_mapping else None
    else:
        chosen = mapping
        try:
            confirmed = csv_mapping(mapping)
        except FileImportError:
            confirmed = None  # the parse below reports it
        date_column = None
        if confirmed is not None:
            # Formats fit the column the customer chose as the date, not the one first suggested.
            detection = read_mapped_dates(upload, confirmed)
            date_formats, date_ambiguous, date_column = detection.candidates, detection.ambiguous, confirmed.date_column
            if detection.candidates and confirmed.date_format not in [c.format for c in detection.candidates]:
                # A format from another column; ambiguous dates still leave the choice to the customer.
                chosen = {**mapping, "date_format": detection.suggested}
    date_name = next((c.name for c in found.columns if c.index == date_column), None)
    # The date column holds values, but no supported format reads them.
    dates_unread = date_name is not None and not date_formats
    unread_error = {"code": "INVALID_MAPPING", "message": f"Dates in “{date_name}” match no supported format.",
                    "field": "date_column"}
    parsed = parse_error = None
    if chosen is None:
        parse_error = unread_error if dates_unread else {
            "code": "INVALID_MAPPING", "message": "Choose the date and amount columns.", "field": None}
    else:
        try:
            parsed = read_csv(upload, csv_mapping(chosen))
        except FileImportError as error:
            parse_error = unread_error if dates_unread else {
                "code": error.code, "message": error.message,
                "field": error.details[0]["field"] if error.details else None}
    rows = list(parsed.transactions) if parsed else []
    values = category_counts(rows) if parsed else list(found.category_values)
    rules = category_rules(db, user_id, source.id if source else None)
    categories = []
    for value, count in values:
        suggested, basis = suggest_category(value, rules, source.id if source else None)
        categories.append(dict(value=value, count=count, suggested=suggested, suggested_source=basis))
    bounds = period_bounds(parsed.date_from, parsed.date_to, today) if parsed else None
    return dict(
        csv=dict(
            encoding=found.encoding, delimiter=found.delimiter, header_row=found.header_row,
            data_start=found.data_start, row_count=found.row_count,
            columns=[dict(index=c.index, name=c.name, suggested_role=c.suggested_role) for c in found.columns],
            date_formats=[dict(format=c.format, label=c.label, matches=c.matches, date_from=c.date_from,
                               date_to=c.date_to) for c in date_formats],
            date_ambiguous=date_ambiguous, decimal_separator=found.number_format.decimal_separator,
            negative_styles=list(found.negative_styles), currency_symbols=list(found.currency_symbols),
            sign=dict(convention=found.sign.convention, confidence=found.sign.confidence, basis=found.sign.basis)
            if found.sign else None,
            suggested_mapping=found.suggested_mapping.to_dict() if found.suggested_mapping else None,
            sample_rows=[list(row) for row in found.sample_rows]),
        mapping=chosen,
        parsed=dict(
            rows=sample_rows(rows), transaction_count=len(rows), row_count=parsed.row_count,
            issue_count=parsed.issue_count,
            issues=[dict(row=i.row, reason=i.reason) for i in parsed.issues[:MAX_PREVIEW_ISSUES]],
            repeated_in_file=parsed.duplicate_count, date_from=parsed.date_from, date_to=parsed.date_to,
            currencies=list(parsed.currencies),
            existing_count=existing_count(db, source, rows) if source else None,
            before_retention=before_retention(rows, today)) if parsed else None,
        parse_error=parse_error,
        categories=categories,
        period=dict(suggested=dict(start=bounds.rows_from, end=bounds.rows_to), earliest=bounds.earliest,
                    latest=bounds.latest) if bounds else None,
        statements=[],
    )


def ofx_preview(db: Session, user_id: uuid.UUID, upload: Upload, source: FinancialSource | None,
                today: date) -> dict:
    statements = []
    for index, statement in enumerate(read_ofx(upload).statements):
        account = statement.account
        matched = source_by_external(db, user_id, account.external_id)
        target = source or matched
        rows = list(statement.transactions)
        days = [row.transaction_date for row in rows]
        period = ofx_period(statement)
        statements.append(dict(
            index=index, kind=statement.kind, name=account.name, account_type=account.account_type,
            subtype=account.subtype, mask=account.mask, currency=account.currency,
            institution_name=account.institution_name,
            period=dict(start=period[0], end=period[1]) if period else None,
            transaction_count=len(rows), issue_count=statement.issue_count,
            corrections=len(statement.removed_external_ids),
            date_from=min(days) if days else None, date_to=max(days) if days else None,
            matched_source_id=matched.id if matched else None,
            existing_count=existing_count(db, target, rows) if target else None,
            before_retention=before_retention(rows, today),
            rows=sample_rows(rows)))
    return dict(csv=None, mapping=None, parsed=None, parse_error=None, categories=[], period=None,
                statements=statements)


def preview_import(db: Session, user_id: uuid.UUID, upload: Upload, *, source_id: uuid.UUID | None,
                   mapping: dict[str, Any] | None, today: date | None = None) -> dict:
    """Everything the customer confirms before an import; persists nothing."""
    today = today or utcnow().date()
    source = file_source(db, user_id, source_id) if source_id else None
    if upload.format == "csv":
        body = csv_preview(db, user_id, upload, source, mapping, today)
    else:
        body = ofx_preview(db, user_id, upload, source, today)
    previous = previous_import(db, source, upload.sha256)
    return dict(format=upload.format, file_sha256=upload.sha256,
                previous_import_id=previous.id if previous else None, retention_start=retention_cutoff(today), **body)


# --- commit -------------------------------------------------------------------

@dataclass
class NewAccount:
    name: str
    account_type: str
    subtype: str | None = None
    currency: str | None = None
    institution_name: str | None = None


@dataclass
class CommitResult:
    record: FinancialImport
    source: FinancialSource
    created_account: bool
    inserted: int
    existing: int
    skipped: int
    removed: int
    rules_saved: int
    #: Rows dated before ``retention_start``; counted in ``skipped`` and never stored.
    before_retention: int = 0
    retention_start: date | None = None


def create_source(db: Session, user_id: uuid.UUID, account: NewAccount, external_id: str,
                  mask: str | None = None, institution: str | None = None) -> FinancialSource:
    source = FinancialSource(
        id=uuid.uuid4(), user_id=user_id, provider=PROVIDER, environment=environment_for(PROVIDER),
        provider_account_id=external_id, connection_ids=[],
        institution_name=(account.institution_name or institution or DEFAULT_INSTITUTION)[:255],
        name=account.name[:255], mask=mask, account_type=account.account_type, subtype=account.subtype,
        status="ACTIVE", currency=account.currency or DEFAULT_CURRENCY, revision=1, fetched_at=utcnow())
    db.add(source)
    db.flush()
    return source


def repeated_commit(db: Session, user_id: uuid.UUID, sha256: str, created: FinancialSource) -> FinancialImport | None:
    """A committed import of this file, inside ``REPEAT_WINDOW``, into another file account of the same name."""
    return db.query(FinancialImport).join(FinancialSource, FinancialSource.id == FinancialImport.source_id).filter(
        FinancialImport.user_id == user_id, FinancialImport.file_sha256 == sha256,
        FinancialImport.status == "committed", FinancialImport.created_at >= utcnow() - REPEAT_WINDOW,
        FinancialSource.provider == PROVIDER, FinancialSource.name == created.name, FinancialSource.id != created.id,
        active_filter(FinancialSource)).first()


def remove_stale_pending(db: Session, source: FinancialSource, keys: set[str], start: date, end: date) -> int:
    """Pending rows inside the period that the new file no longer holds have posted
    under a new key (their amount changed) or were cancelled."""
    stale = [row_id for row_id, key in db.query(FinancialTransaction.id, FinancialTransaction.provider_transaction_id).filter(
        FinancialTransaction.source_id == source.id, FinancialTransaction.status == "PENDING",
        FinancialTransaction.transaction_date >= start, FinancialTransaction.transaction_date <= end).all()
        if key not in keys]
    for part in chunks(stale):
        db.query(FinancialTransaction).filter(FinancialTransaction.id.in_(part)).delete(synchronize_session=False)
    return len(stale)


def remove_corrected(db: Session, source: FinancialSource, external_ids: tuple[str, ...]) -> int:
    keys = [stored_id(source, value) for value in dict.fromkeys(external_ids)]
    count = 0
    for part in chunks(keys):
        count += db.query(FinancialTransaction).filter(
            FinancialTransaction.source_id == source.id,
            FinancialTransaction.provider_transaction_id.in_(part)).delete(synchronize_session=False)
    return count


def commit_import(db: Session, user_id: uuid.UUID, upload: Upload, filename: str, *,
                  source_id: uuid.UUID | None, new_account: NewAccount | None, mapping: dict[str, Any] | None,
                  statement_index: int | None, period: tuple[date, date] | None,
                  categories: list[tuple[str, str]], today: date | None = None) -> CommitResult:
    """Store a confirmed import; the caller commits the session."""
    today = today or utcnow().date()
    source = file_source(db, user_id, source_id) if source_id else None
    mask = institution = None
    if upload.format == "csv":
        if mapping is None:
            raise FileImportError("VALIDATION_ERROR", "Confirm how to read the file's columns.",
                                  details=[{"field": "mapping", "reason": "required"}])
        if period is None:
            raise FileImportError("VALIDATION_ERROR", "Confirm the statement period.",
                                  details=[{"field": "period", "reason": "required"}])
        confirmed = csv_mapping(mapping)
        parsed = read_csv(upload, confirmed)
        rows, issue_count, row_count = list(parsed.transactions), parsed.issue_count, parsed.row_count
        check_period(period_bounds(parsed.date_from, parsed.date_to, today), *period)
        stored_mapping = confirmed.to_dict()
        removed_ids: tuple[str, ...] = ()
        external_id = f"csv-{uuid.uuid4().hex}"
    else:
        index, statement = choose_statement(read_ofx(upload), statement_index)
        found = ofx_period(statement)
        if found is None:
            raise FileImportError("INVALID_PERIOD", "The statement has no period or transactions.")
        period = found
        rows, issue_count = list(statement.transactions), statement.issue_count
        row_count = len(rows) + issue_count
        days = [row.transaction_date for row in rows] or [period[0]]
        stored_mapping = {"statement_index": index, "row_from": min(days).isoformat(), "row_to": max(days).isoformat()}
        removed_ids = statement.removed_external_ids
        external_id = statement.account.external_id
        mask, institution = statement.account.mask, statement.account.institution_name
        if new_account is not None and new_account.currency is None:
            new_account = replace(new_account, currency=statement.account.currency)
    created = False
    if source is None:
        if new_account is None:
            raise FileImportError("VALIDATION_ERROR", "Choose an account to import into.",
                                  details=[{"field": "source_id", "reason": "required"}])
        existing_source = source_by_external(db, user_id, external_id)
        if existing_source is not None:
            raise FileImportError("ACCOUNT_EXISTS", "This account was imported before. Import into it instead.", 409,
                                  details=[{"field": "source_id", "reason": str(existing_source.id)}])
        source = create_source(db, user_id, new_account, external_id, mask, institution)
        # Checked after the account's insert: on SQLite that write waits for a concurrent
        # commit to finish, so this read sees it; PostgreSQL already waited in ``lock_user``.
        repeated = repeated_commit(db, user_id, upload.sha256, source)
        if repeated is not None:
            raise FileImportError("ALREADY_IMPORTED", "This file was just imported into an account with this name.",
                                  409, details=[{"field": "source_id", "reason": str(repeated.source_id)}])
        created = True
    elif previous_import(db, source, upload.sha256) is not None:
        raise FileImportError("ALREADY_IMPORTED", "This file is already imported into this account.", 409)
    currency = source.currency or DEFAULT_CURRENCY
    cutoff = retention_cutoff(today)
    kept = [replace(row, currency=row.currency or currency) for row in rows if row.transaction_date >= cutoff]
    old = len(rows) - len(kept)
    record = FinancialImport(id=uuid.uuid4(), user_id=user_id, source_id=source.id, filename=filename[:255],
                             file_sha256=upload.sha256, format=upload.format, mapping=stored_mapping,
                             date_from=period[0], date_to=period[1], row_count=row_count, status="committed",
                             created_at=utcnow())
    db.add(record)
    db.flush()
    removed = remove_corrected(db, source, removed_ids)
    removed += remove_stale_pending(db, source, {stored_id(source, row.external_id) for row in kept}, *period)
    stored: StoreResult = upsert_transactions(db, source, kept, import_id=record.id, today=today)
    record.imported_count = stored.inserted
    record.duplicate_count = stored.updated + stored.unchanged + stored.duplicates
    record.skipped_count = issue_count + stored.skipped + old
    rules_saved = save_category_rules(db, user_id, source, categories) if upload.format == "csv" else 0
    db.flush()
    refresh_feeds(db, user_id, {str(source.id)})
    logger.info("ledger import committed import=%s source=%s inserted=%d existing=%d skipped=%d removed=%d",
                record.id, source.id, record.imported_count, record.duplicate_count, record.skipped_count, removed)
    return CommitResult(record, source, created, stored.inserted, record.duplicate_count, record.skipped_count,
                        removed, rules_saved, before_retention=old, retention_start=cutoff)


# --- revert and account removal -----------------------------------------------

def owned_range(record: FinancialImport) -> tuple[date, date]:
    """The statement period widened to the dates of the rows its file held."""
    start, end = record.date_from, record.date_to
    mapping = record.mapping or {}
    for key in ("row_from", "row_to"):
        value = mapping.get(key)
        if isinstance(value, str):
            try:
                day = date.fromisoformat(value)
            except ValueError:
                continue
            start, end = min(start, day), max(end, day)
    return start, end


@dataclass
class RevertResult:
    record: FinancialImport
    removed: int
    reassigned: int


def import_for_user(db: Session, user_id: uuid.UUID, import_id: uuid.UUID) -> FinancialImport:
    record = db.query(FinancialImport).join(FinancialSource, FinancialSource.id == FinancialImport.source_id).filter(
        FinancialImport.id == import_id, FinancialImport.user_id == user_id, active_filter(FinancialSource)).first()
    if record is None:
        raise FileImportError("NOT_FOUND", "Import not found.", 404)
    return record


def revert_import(db: Session, user_id: uuid.UUID, import_id: uuid.UUID) -> RevertResult:
    """Remove the rows this import inserted that no other committed import may own."""
    record = import_for_user(db, user_id, import_id)
    if record.status != "committed":
        raise FileImportError("CONFLICT", "This import was already reverted.", 409)
    others = db.query(FinancialImport).filter(
        FinancialImport.source_id == record.source_id, FinancialImport.status == "committed",
        FinancialImport.id != record.id).order_by(FinancialImport.created_at.desc(), FinancialImport.id).all()
    ranges = [(other, owned_range(other)) for other in others]
    removed: list[uuid.UUID] = []
    reassigned = 0
    for row in db.query(FinancialTransaction).filter(FinancialTransaction.import_id == record.id).all():
        owner = next((other for other, (start, end) in ranges if start <= row.transaction_date <= end), None)
        if owner is None:
            removed.append(row.id)
        else:
            row.import_id = owner.id
            reassigned += 1
    for part in chunks(removed):
        db.query(FinancialTransaction).filter(FinancialTransaction.id.in_(part)).delete(synchronize_session=False)
    record.status, record.reverted_at = "reverted", utcnow()
    db.flush()
    refresh_feeds(db, user_id, {str(record.source_id)})
    logger.info("ledger import reverted import=%s removed=%d reassigned=%d", record.id, len(removed), reassigned)
    return RevertResult(record, len(removed), reassigned)


def reverts_empty_account(db: Session, records: list[FinancialImport]) -> set[uuid.UUID]:
    """Committed imports whose revert leaves their account empty, so the account can go with them.

    The import created the account (a file account's first import creates it), no other
    import is committed there, every row there is the import's own and no plan account
    reads the account's balance.
    """
    committed = [record for record in records if record.status == "committed"]
    if not committed:
        return set()
    source_ids = {record.source_id for record in committed}
    first: dict[uuid.UUID, tuple] = {}
    live: Counter[uuid.UUID] = Counter()
    for source_id, import_id, status, created_at in db.query(
            FinancialImport.source_id, FinancialImport.id, FinancialImport.status, FinancialImport.created_at).filter(
            FinancialImport.source_id.in_(source_ids)).all():
        first[source_id] = min(first.get(source_id, (created_at, str(import_id))), (created_at, str(import_id)))
        live[source_id] += status == "committed"
    rows = dict(db.query(FinancialTransaction.source_id, func.count(FinancialTransaction.id)).filter(
        FinancialTransaction.source_id.in_(source_ids)).group_by(FinancialTransaction.source_id).all())
    owned = dict(db.query(FinancialTransaction.import_id, func.count(FinancialTransaction.id)).filter(
        FinancialTransaction.import_id.in_([record.id for record in committed])).group_by(
        FinancialTransaction.import_id).all())
    linked = {value for (value,) in db.query(FinancialBalanceLink.source_id).filter(
        FinancialBalanceLink.source_id.in_(source_ids)).distinct().all()}
    return {record.id for record in committed
            if first[record.source_id][1] == str(record.id) and live[record.source_id] == 1
            and rows.get(record.source_id, 0) == owned.get(record.id, 0) and record.source_id not in linked}


def delete_file_account(db: Session, user_id: uuid.UUID, source_id: uuid.UUID) -> int:
    """Remove a file account, its imports, rules and rows; returns the rows removed."""
    source = file_source(db, user_id, source_id)
    key = str(source.id)
    count = db.query(FinancialTransaction).filter(FinancialTransaction.source_id == source.id).delete(
        synchronize_session=False)
    for model in (FinancialImport, FinancialRule, FinancialBalanceLink):
        db.query(model).filter(model.source_id == source.id).delete(synchronize_session=False)
    feeds = feeds_using(db, user_id, {key})
    for feed in feeds:
        feed.source_ids = [value for value in feed.source_ids if value != key]
    db.delete(source)
    db.flush()
    if feeds:
        apply_feeds(db, feeds)
    logger.info("ledger file account removed source=%s rows=%d feeds=%d", key, count, len(feeds))
    return count

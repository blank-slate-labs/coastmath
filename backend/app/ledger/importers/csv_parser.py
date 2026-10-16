"""CSV statements: a mapping preview, then a parse with an explicit mapping.

``preview_csv`` reads a file without any mapping and suggests one: delimiter,
header row (after any preamble lines), column roles, date format candidates,
number format and a sign convention. ``parse_csv`` takes the mapping the
customer confirmed and returns normalized transactions. Neither function
touches the database.

Row keys: a CSV has no transaction IDs, so ``external_id`` hashes the
transaction date, the ledger-signed amount, the normalized description and the
occurrence index of that tuple within the file. Re-importing the same file, or
a file whose period overlaps an earlier one, reproduces the same keys for the
same rows. Changing the description columns or sign convention between imports
changes the keys.
"""
import csv
import io
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from app.ledger.importers.amounts import (
    NegativeStyle,
    NumberFormat,
    ParsedAmount,
    currency_symbols,
    detect_negative_styles,
    detect_number_format,
    looks_numeric,
    parse_amount,
)
from app.ledger.importers.dates import (
    DATE_FORMATS,
    DateDetection,
    DateFormatCandidate,
    detect_date_formats,
    looks_like_date,
    parse_date,
)
from app.ledger.importers.decoding import MAX_ROWS, decode_bytes, detect_format
from app.ledger.importers.errors import ImportFileError, IssueLog, RowIssue
from app.ledger.importers.keys import normalize_description, row_key
from app.ledger.types import NormalizedTransaction, TransactionStatus

Delimiter = Literal[",", ";", "\t", "|"]
AmountStrategy = Literal["signed", "split", "indicator"]
SignConvention = Literal["inflows_positive", "inflows_negative"]
Confidence = Literal["high", "medium", "low"]
ColumnRole = Literal[
    "date", "posted_date", "description", "memo", "merchant", "amount", "debit", "credit",
    "type", "category", "currency", "status", "ignored",
]

DELIMITERS: tuple[Delimiter, ...] = (",", ";", "\t", "|")
MAX_COLUMNS = 100
SAMPLE_ROWS = 10
MAX_CATEGORY_VALUES = 200
#: Column widths of ``financial_transactions``.
DESCRIPTION_LENGTH, MERCHANT_LENGTH, CATEGORY_LENGTH = 255, 255, 100

_SUPPORTED_DATE_FORMATS = {fmt for fmt, _ in DATE_FORMATS}
_PENDING_VALUES = {"pending", "pend", "authorized", "authorised", "processing", "in progress", "not posted", "unposted", "hold"}
_DEBIT_VALUES = {"debit", "dr", "d", "db", "withdrawal", "purchase", "sale", "fee", "charge", "check", "atm", "pos", "out"}
_CREDIT_VALUES = {"credit", "cr", "c", "deposit", "refund", "return", "interest", "in"}
# Description words that name money arriving, for the sign suggestion only.
_INFLOW_WORDS = re.compile(
    r"\b(deposit|payroll|direct dep|salary|refund|interest paid|payment received|payment thank you|thank you for your payment|reversal)\b",
)
_WHITESPACE = re.compile(r"\s+")

# Header names (casefolded, punctuation removed) to roles. Order matters only
# for ties between columns; the first column claiming a role keeps it.
_HEADER_ROLES: tuple[tuple[ColumnRole, frozenset[str]], ...] = (
    ("date", frozenset({"date", "transaction date", "trans date", "txn date", "booking date", "transaction date time", "date of transaction"})),
    ("posted_date", frozenset({"posted date", "posting date", "post date", "posted", "settlement date", "value date", "cleared date"})),
    ("description", frozenset({"description", "payee", "name", "details", "narrative", "transaction description", "transaction details", "particulars", "transaction"})),
    ("memo", frozenset({"memo", "notes", "note", "reference", "extended description", "additional info", "comments"})),
    ("merchant", frozenset({"merchant", "merchant name", "vendor", "counterparty"})),
    ("amount", frozenset({"amount", "transaction amount", "amt", "value", "net amount", "amount usd", "amount eur", "amount gbp", "amount cad"})),
    ("debit", frozenset({"debit", "debits", "debit amount", "withdrawal", "withdrawals", "withdrawal amount", "money out", "paid out", "outflow", "charges", "charge"})),
    ("credit", frozenset({"credit", "credits", "credit amount", "deposit", "deposits", "deposit amount", "money in", "paid in", "inflow"})),
    ("type", frozenset({"type", "transaction type", "debit credit", "credit debit", "dr cr", "cr dr", "indicator", "debit or credit"})),
    ("category", frozenset({"category", "categories", "transaction category", "spending category"})),
    ("currency", frozenset({"currency", "ccy", "currency code"})),
    ("status", frozenset({"status", "state", "transaction status"})),
    ("ignored", frozenset({"balance", "running balance", "available balance", "account", "account number", "account name", "card", "card number", "check number", "check"})),
)


@dataclass(frozen=True)
class CsvMapping:
    """How to read a CSV's columns. Column indexes are 0-based.

    ``data_start`` is the 0-based record index of the first data row (records
    count every CSV record, blank lines included). ``date_format`` must be one
    of ``DATE_FORMATS``; the preview leaves it None when the file is ambiguous.
    Amount strategies:

    - ``signed``: one ``amount_column``; ``sign_convention`` says whether money
      arriving is positive (bank style) or negative (card style).
    - ``split``: ``debit_column`` (money out) and ``credit_column`` (money in);
      signs inside the columns are ignored.
    - ``indicator``: ``amount_column`` magnitude plus ``type_column`` whose
      casefolded value is in ``debit_values`` (out) or ``credit_values`` (in).

    A CR or DR mark on an amount (``12.50 CR``) decides the direction under
    every strategy: CR is money in, DR money out.
    """

    delimiter: Delimiter
    data_start: int
    date_column: int
    date_format: str | None
    description_columns: tuple[int, ...]
    amount_strategy: AmountStrategy
    amount_column: int | None = None
    sign_convention: SignConvention = "inflows_positive"
    debit_column: int | None = None
    credit_column: int | None = None
    type_column: int | None = None
    debit_values: tuple[str, ...] = ()
    credit_values: tuple[str, ...] = ()
    posted_date_column: int | None = None
    merchant_column: int | None = None
    category_column: int | None = None
    currency_column: int | None = None
    status_column: int | None = None
    decimal_separator: Literal[".", ","] = "."
    default_currency: str | None = None
    header_row: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form for ``financial_imports.mapping``."""
        data = asdict(self)
        for key in ("description_columns", "debit_values", "credit_values"):
            data[key] = list(data[key])
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CsvMapping":
        """Build a mapping from client or stored JSON; refuses unknown keys."""
        known = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - known)
        if unknown:
            raise ImportFileError("INVALID_MAPPING", "Mapping has unknown fields.", {"fields": unknown})
        values = dict(data)
        try:
            for key in ("description_columns", "debit_values", "credit_values"):
                if key in values:
                    values[key] = tuple(values[key])
            return cls(**values)
        except TypeError as exc:
            raise ImportFileError("INVALID_MAPPING", "Mapping is missing required fields.") from exc


@dataclass(frozen=True)
class CsvColumn:
    index: int
    name: str
    suggested_role: ColumnRole


@dataclass(frozen=True)
class SignSuggestion:
    """``basis``: ``keywords`` (descriptions that name money arriving share a
    sign), ``majority`` (most rows share a sign; spending usually dominates),
    or ``default`` (no evidence)."""

    convention: SignConvention
    confidence: Confidence
    basis: Literal["keywords", "majority", "default"]


@dataclass(frozen=True)
class CsvPreview:
    encoding: str
    delimiter: Delimiter
    header_row: int | None
    data_start: int
    row_count: int
    columns: tuple[CsvColumn, ...]
    date_formats: tuple[DateFormatCandidate, ...]
    date_ambiguous: bool
    number_format: NumberFormat
    negative_styles: tuple[NegativeStyle, ...]
    currency_symbols: tuple[str, ...]
    sign: SignSuggestion | None
    suggested_mapping: CsvMapping | None
    sample_rows: tuple[tuple[str, ...], ...]
    category_values: tuple[tuple[str, int], ...]
    date_range: tuple[date, date] | None


@dataclass(frozen=True)
class CsvParseResult:
    """``duplicate_count`` counts rows identical (date, amount, description) to
    an earlier row in the file; they are kept with distinct keys."""

    encoding: str
    transactions: tuple[NormalizedTransaction, ...]
    issues: tuple[RowIssue, ...]
    issue_count: int
    row_count: int
    duplicate_count: int
    date_from: date
    date_to: date
    currencies: tuple[str, ...] = field(default=())


# --------------------------------------------------------------------------- records


def _records(text: str, delimiter: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter, quotechar='"', skipinitialspace=True)
    rows: list[list[str]] = []
    try:
        for row in reader:
            if len(rows) > MAX_ROWS + 1000:
                raise ImportFileError("TOO_MANY_ROWS", "File has more rows than the import limit.", {"max_rows": MAX_ROWS})
            rows.append(row)
    except csv.Error as exc:
        raise ImportFileError("MALFORMED_CSV", "File is not a readable CSV.") from exc
    return rows


def _decode_csv(data: bytes) -> tuple[str, str]:
    decoded = decode_bytes(data)
    if detect_format(decoded.text) != "csv":
        raise ImportFileError("UNSUPPORTED_FORMAT", "File is not a CSV.")
    return decoded.text, decoded.encoding


def _modal_width(rows: Sequence[list[str]]) -> tuple[int, int]:
    widths = Counter(len(row) for row in rows if len(row) >= 2)
    if not widths:
        return 0, 0
    width, count = max(widths.items(), key=lambda item: (item[1], item[0]))
    return width, count


def _choose_delimiter(text: str) -> tuple[Delimiter, list[list[str]], int]:
    best: tuple[int, int, int] | None = None
    chosen: tuple[Delimiter, list[list[str]], int] | None = None
    for rank, delimiter in enumerate(DELIMITERS):
        rows = _records(text, delimiter)
        width, count = _modal_width(rows)
        score = (count, width, -rank)
        if width and (best is None or score > best):
            best, chosen = score, (delimiter, rows, width)
    if chosen is None:
        raise ImportFileError("MALFORMED_CSV", "File has no delimited columns.")
    if chosen[2] > MAX_COLUMNS:
        raise ImportFileError("MALFORMED_CSV", "File has too many columns.", {"max_columns": MAX_COLUMNS})
    return chosen


def _locate_header(rows: Sequence[list[str]], width: int) -> tuple[int | None, int]:
    first = next(index for index, row in enumerate(rows) if len(row) == width)
    cells = [cell for cell in rows[first] if cell.strip()]
    is_header = bool(cells) and not any(looks_like_date(cell) or looks_numeric(cell) for cell in cells)
    return (first, first + 1) if is_header else (None, first)


def _data_rows(rows: Sequence[list[str]], data_start: int) -> list[tuple[int, list[str]]]:
    data = [(index + 1, row) for index, row in enumerate(rows) if index >= data_start and any(cell.strip() for cell in row)]
    if len(data) > MAX_ROWS:
        raise ImportFileError("TOO_MANY_ROWS", "File has more rows than the import limit.", {"max_rows": MAX_ROWS})
    return data


def _cell(row: Sequence[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


# --------------------------------------------------------------------------- preview


def _header_key(name: str) -> str:
    return _WHITESPACE.sub(" ", re.sub(r"[^\w]+", " ", name.casefold())).strip()


def _suggest_roles(header: Sequence[str] | None, data: Sequence[list[str]], width: int) -> list[ColumnRole]:
    roles: list[ColumnRole | None] = [None] * width
    if header:
        claimed: set[ColumnRole] = set()
        for index in range(width):
            key = _header_key(header[index]) if index < len(header) else ""
            for role, names in _HEADER_ROLES:
                if key in names and (role == "ignored" or role not in claimed):
                    roles[index] = role
                    claimed.add(role)
                    break
    _infer_from_content(roles, data)
    if "date" not in roles and "posted_date" in roles:
        # A file whose only date is the posting date ("Posting Date", "Posted") dates rows by it.
        roles[roles.index("posted_date")] = "date"
    return [role or "ignored" for role in roles]


def _infer_from_content(roles: list[ColumnRole | None], data: Sequence[list[str]]) -> None:
    """Fill roles the header did not settle from what the columns hold."""
    sample = data[:200]

    def share(index: int, test: Any) -> float:
        cells = [_cell(row, index) for row in sample]
        filled = [cell for cell in cells if cell]
        return sum(1 for cell in filled if test(cell)) / len(filled) if filled else 0.0

    present: set[ColumnRole | None] = set(roles)
    for index, role in enumerate(roles):
        if role is not None:
            continue
        if share(index, looks_like_date) >= 0.8:
            roles[index] = "date" if "date" not in present else ("posted_date" if "posted_date" not in present else "ignored")
        elif share(index, looks_numeric) >= 0.8:
            has_amount = present & {"amount", "debit", "credit"}
            roles[index] = "ignored" if has_amount else "amount"
        present.add(roles[index])
    if "description" not in present:
        text_columns = [index for index, role in enumerate(roles) if role is None]
        if text_columns:
            def average_length(index: int) -> float:
                return sum(len(_cell(row, index)) for row in sample) / max(len(sample), 1)
            roles[max(text_columns, key=average_length)] = "description"


def _suggest_sign(descriptions: Sequence[str], amounts: Sequence[ParsedAmount]) -> SignSuggestion:
    signed = [(text, amount.value) for text, amount in zip(descriptions, amounts, strict=True) if amount.direction is None and amount.value]
    keyword_signs = [value > 0 for text, value in signed if _INFLOW_WORDS.search(text.casefold())]
    if len(keyword_signs) >= 3:
        positive = sum(keyword_signs) / len(keyword_signs)
        if positive >= 0.8 or positive <= 0.2:
            return SignSuggestion("inflows_positive" if positive >= 0.8 else "inflows_negative", "high", "keywords")
    if signed:
        negative_share = sum(value < 0 for _, value in signed) / len(signed)
        if negative_share >= 0.6:
            return SignSuggestion("inflows_positive", "medium" if negative_share >= 0.75 else "low", "majority")
        if negative_share <= 0.4:
            return SignSuggestion("inflows_negative", "medium" if negative_share <= 0.25 else "low", "majority")
    return SignSuggestion("inflows_positive", "low", "default")


def preview_csv(data: bytes) -> CsvPreview:
    """Inspect a CSV and suggest a mapping; never guesses an ambiguous date."""
    text, encoding = _decode_csv(data)
    delimiter, rows, width = _choose_delimiter(text)
    header_row, data_start = _locate_header(rows, width)
    data_rows = [row for _, row in _data_rows(rows, data_start)]
    if not data_rows:
        raise ImportFileError("NO_USABLE_ROWS", "File has no data rows.")
    header = rows[header_row] if header_row is not None else None
    roles = _suggest_roles(header, data_rows, width)
    columns = tuple(
        CsvColumn(index, (header[index].strip() if header and index < len(header) else "") or f"Column {index + 1}", roles[index])
        for index in range(width)
    )

    def column(role: ColumnRole) -> int | None:
        return next((item.index for item in columns if item.suggested_role == role), None)

    date_column = column("date")
    detection = detect_date_formats([_cell(row, date_column) for row in data_rows]) if date_column is not None else None
    # Without a description column, the memo describes the row.
    description_column = column("description")
    if description_column is None:
        description_column = column("memo")
    amount_columns = [index for index in (column("amount"), column("debit"), column("credit")) if index is not None]
    amount_cells = [_cell(row, index) for row in data_rows for index in amount_columns]
    number_format = detect_number_format(amount_cells)

    strategy: AmountStrategy | None = None
    sign: SignSuggestion | None = None
    debit_values: tuple[str, ...] = ()
    credit_values: tuple[str, ...] = ()
    amount_column, type_column = column("amount"), column("type")
    if column("debit") is not None and column("credit") is not None:
        strategy = "split"
    elif amount_column is not None:
        parsed = [parse_amount(_cell(row, amount_column), number_format) for row in data_rows]
        valid = [(row, amount) for row, amount in zip(data_rows, parsed, strict=True) if amount is not None]
        has_negative = any(amount.value < 0 or amount.direction for _, amount in valid)
        if type_column is not None and not has_negative:
            type_values = {_cell(row, type_column).casefold() for row in data_rows} - {""}
            debit_values = tuple(sorted(type_values & _DEBIT_VALUES))
            credit_values = tuple(sorted(type_values & _CREDIT_VALUES))
            strategy = "indicator"
        else:
            strategy = "signed"
            sign = _suggest_sign([_cell(row, description_column) for row, _ in valid], [amount for _, amount in valid])

    suggested = None
    if date_column is not None and strategy is not None and detection is not None and detection.candidates:
        suggested = CsvMapping(
            delimiter=delimiter, data_start=data_start, date_column=date_column, date_format=detection.suggested,
            description_columns=(description_column,) if description_column is not None else (),
            amount_strategy=strategy, amount_column=amount_column,
            sign_convention=sign.convention if sign else "inflows_positive",
            debit_column=column("debit") if strategy == "split" else None,
            credit_column=column("credit") if strategy == "split" else None,
            type_column=type_column if strategy == "indicator" else None,
            debit_values=debit_values, credit_values=credit_values,
            posted_date_column=column("posted_date"), merchant_column=column("merchant"),
            category_column=column("category"), currency_column=column("currency"), status_column=column("status"),
            decimal_separator=number_format.decimal_separator, header_row=header_row,
        )

    category_column = column("category")
    category_values: tuple[tuple[str, int], ...] = ()
    if category_column is not None:
        counts = Counter(_cell(row, category_column)[:CATEGORY_LENGTH] for row in data_rows)
        counts.pop("", None)
        category_values = tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:MAX_CATEGORY_VALUES])

    date_range = None
    if detection and detection.suggested:
        chosen = next(candidate for candidate in detection.candidates if candidate.format == detection.suggested)
        date_range = (chosen.date_from, chosen.date_to)

    return CsvPreview(
        encoding=encoding, delimiter=delimiter, header_row=header_row, data_start=data_start, row_count=len(data_rows),
        columns=columns,
        date_formats=detection.candidates if detection else (),
        date_ambiguous=bool(detection and detection.ambiguous),
        number_format=number_format,
        negative_styles=detect_negative_styles(amount_cells),
        currency_symbols=currency_symbols(amount_cells),
        sign=sign, suggested_mapping=suggested,
        sample_rows=tuple(tuple(row) for row in data_rows[:SAMPLE_ROWS]),
        category_values=category_values, date_range=date_range,
    )


def detect_mapped_dates(data: bytes, mapping: CsvMapping) -> DateDetection:
    """Date formats that fit the mapping's date column, whichever column the
    customer chose; empty when that column is missing or outside the file."""
    text, _ = _decode_csv(data)
    if mapping.delimiter not in DELIMITERS or not _is_index(mapping.data_start) or not _is_index(mapping.date_column):
        return DateDetection((), None, False)
    rows = _records(text, mapping.delimiter)
    return detect_date_formats([_cell(row, mapping.date_column) for _, row in _data_rows(rows, mapping.data_start)])


# --------------------------------------------------------------------------- parse


def _validate(mapping: CsvMapping, width: int) -> None:
    def refuse(message: str, field_name: str) -> None:
        raise ImportFileError("INVALID_MAPPING", message, {"field": field_name})

    if mapping.delimiter not in DELIMITERS:
        refuse("Delimiter is not supported.", "delimiter")
    if mapping.date_format is None:
        refuse("Choose a date format.", "date_format")
    if mapping.date_format not in _SUPPORTED_DATE_FORMATS:
        refuse("Date format is not supported.", "date_format")
    if not _is_index(mapping.data_start):
        refuse("Data start row is invalid.", "data_start")
    if mapping.decimal_separator not in (".", ","):
        refuse("Decimal separator is not supported.", "decimal_separator")
    if mapping.amount_strategy not in ("signed", "split", "indicator"):
        refuse("Amount strategy is not supported.", "amount_strategy")
    if mapping.sign_convention not in ("inflows_positive", "inflows_negative"):
        refuse("Sign convention is not supported.", "sign_convention")
    required: dict[str, int | None] = {"date_column": mapping.date_column}
    if mapping.amount_strategy == "split":
        required |= {"debit_column": mapping.debit_column, "credit_column": mapping.credit_column}
    else:
        required["amount_column"] = mapping.amount_column
    if mapping.amount_strategy == "indicator":
        required["type_column"] = mapping.type_column
        if not mapping.debit_values and not mapping.credit_values:
            refuse("Name the type values for money out and money in.", "debit_values")
    for name, value in required.items():
        if value is None:
            refuse("A required column is missing.", name)
    optional = {
        "posted_date_column": mapping.posted_date_column, "merchant_column": mapping.merchant_column,
        "category_column": mapping.category_column, "currency_column": mapping.currency_column,
        "status_column": mapping.status_column, "type_column": mapping.type_column,
    }
    if not mapping.description_columns:
        refuse("Choose at least one description column.", "description_columns")
    columns = {**required, **optional, **{f"description_columns[{i}]": c for i, c in enumerate(mapping.description_columns)}}
    for name, value in columns.items():
        if value is not None and not (_is_index(value) and value < width):
            refuse("Column is outside the file.", name)
    for name in ("debit_values", "credit_values"):
        if not all(isinstance(value, str) for value in getattr(mapping, name)):
            refuse("Type values must be text.", name)
    if mapping.default_currency is not None and not re.fullmatch(r"[A-Z]{3}", mapping.default_currency):
        refuse("Currency must be a three-letter code.", "default_currency")


def _is_index(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _ledger_amount(row: Sequence[str], mapping: CsvMapping, number_format: NumberFormat) -> Decimal | str:
    """The ledger-signed amount (positive leaves the account), or a reason."""
    if mapping.amount_strategy == "split":
        debit_text, credit_text = _cell(row, mapping.debit_column), _cell(row, mapping.credit_column)
        debit = parse_amount(debit_text, number_format) if debit_text else None
        credit = parse_amount(credit_text, number_format) if credit_text else None
        if (debit_text and debit is None) or (credit_text and credit is None):
            return "invalid_amount"
        debit_value = _directed(debit, "out") if debit and debit.value else None
        credit_value = _directed(credit, "in") if credit and credit.value else None
        if debit_value is not None and credit_value is not None:
            return "debit_and_credit"
        if debit_value is not None:
            return debit_value
        if credit_value is not None:
            return credit_value
        return "missing_amount" if not (debit or credit) else "zero_amount"
    text = _cell(row, mapping.amount_column)
    if not text:
        return "missing_amount"
    parsed = parse_amount(text, number_format)
    if parsed is None:
        return "invalid_amount"
    if not parsed.value:
        return "zero_amount"
    if parsed.direction is not None:
        return _directed(parsed, parsed.direction)
    if mapping.amount_strategy == "indicator":
        kind = _cell(row, mapping.type_column).casefold()
        if kind in {value.casefold() for value in mapping.debit_values}:
            return abs(parsed.value)
        if kind in {value.casefold() for value in mapping.credit_values}:
            return -abs(parsed.value)
        return "unknown_type"
    return -parsed.value if mapping.sign_convention == "inflows_positive" else parsed.value


def _directed(amount: ParsedAmount, default: Literal["in", "out"]) -> Decimal:
    """Magnitude signed by the amount's CR/DR mark, else by its column."""
    direction = amount.direction or default
    return abs(amount.value) if direction == "out" else -abs(amount.value)


def parse_csv(data: bytes, mapping: CsvMapping, *, account_external_id: str) -> CsvParseResult:
    """Parse a CSV with a confirmed mapping into normalized transactions.

    Rows that cannot be read become ``issues`` (row number and reason:
    ``invalid_date``, ``missing_date``, ``invalid_amount``, ``missing_amount``,
    ``zero_amount``, ``debit_and_credit``, ``unknown_type``,
    ``column_count``); a file without any usable row raises ``NO_USABLE_ROWS``.
    """
    text, encoding = _decode_csv(data)
    _validate(mapping, MAX_COLUMNS)
    rows = _records(text, mapping.delimiter)
    width, _ = _modal_width(rows)
    _validate(mapping, width)
    assert mapping.date_format is not None  # _validate refuses None
    number_format = NumberFormat(mapping.decimal_separator)
    issues = IssueLog()
    occurrences: Counter[tuple[date, Decimal, str]] = Counter()
    date_cache: dict[str, date | None] = {}
    transactions: list[NormalizedTransaction] = []
    duplicates = 0
    data = _data_rows(rows, mapping.data_start)

    def read_date(cell: str) -> date | None:
        if cell not in date_cache:
            date_cache[cell] = parse_date(cell, mapping.date_format)  # type: ignore[arg-type]
        return date_cache[cell]

    for number, row in data:
        if len(row) > width and any(cell.strip() for cell in row[width:]):
            issues.add(number, "column_count")
            continue
        date_text = _cell(row, mapping.date_column)
        if not date_text:
            issues.add(number, "missing_date", mapping.date_column)
            continue
        transaction_date = read_date(date_text)
        if transaction_date is None:
            issues.add(number, "invalid_date", mapping.date_column)
            continue
        amount = _ledger_amount(row, mapping, number_format)
        if isinstance(amount, str):
            issues.add(number, amount)
            continue
        description = " ".join(part for part in (_cell(row, index) for index in mapping.description_columns) if part)
        merchant = _cell(row, mapping.merchant_column)[:MERCHANT_LENGTH] or None
        category = _cell(row, mapping.category_column)[:CATEGORY_LENGTH] or None
        description = _WHITESPACE.sub(" ", description or merchant or category or "").strip()[:DESCRIPTION_LENGTH]
        tuple_key = (transaction_date, amount, normalize_description(description))
        occurrence = occurrences[tuple_key]
        occurrences[tuple_key] += 1
        duplicates += occurrence > 0
        posted_text = _cell(row, mapping.posted_date_column)
        currency = _cell(row, mapping.currency_column).upper()
        status: TransactionStatus = "PENDING" if _cell(row, mapping.status_column).casefold() in _PENDING_VALUES else "POSTED"
        transactions.append(NormalizedTransaction(
            external_id=row_key(transaction_date, amount, description, occurrence),
            account_external_id=account_external_id,
            amount=amount,
            transaction_date=transaction_date,
            description=description,
            status=status,
            posted_date=read_date(posted_text) if posted_text else None,
            currency=currency if re.fullmatch(r"[A-Z]{3}", currency) else mapping.default_currency,
            provider_category=category,
            merchant_name=merchant,
        ))
    if not transactions:
        raise ImportFileError("NO_USABLE_ROWS", "File has no rows that could be imported.", {"issue_count": issues.count})
    dates = [item.transaction_date for item in transactions]
    currencies = tuple(sorted({item.currency for item in transactions if item.currency}))
    return CsvParseResult(
        encoding=encoding, transactions=tuple(transactions), issues=tuple(issues.issues), issue_count=issues.count,
        row_count=len(data), duplicate_count=duplicates, date_from=min(dates), date_to=max(dates), currencies=currencies,
    )


__all__ = [
    "CsvColumn", "CsvMapping", "CsvParseResult", "CsvPreview", "SignSuggestion",
    "detect_mapped_dates", "parse_csv", "preview_csv",
]

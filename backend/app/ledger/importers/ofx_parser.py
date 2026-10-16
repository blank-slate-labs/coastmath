"""OFX and QFX statements to normalized accounts and transactions.

The tokenizer reads OFX 1.x SGML (leaf elements without closing tags) and OFX
2.x XML alike, and never hands the file to an XML parser: no DTDs, no entity
expansion (only the five predefined XML entities and numeric character
references are decoded), no external references. Comments, processing
instructions and declarations are skipped in one linear pass.

Rules come from the OFX 2.3 specification (ofx.net): banking statement
responses (``STMTRS``, section 11.4.2), credit card statements (``CCSTMTRS``,
11.4.3), corrections (``CORRECTFITID``/``CORRECTACTION``, 11.4.4.3), datetime
format (3.2.8.2) and the comma-or-period decimal of amounts (3.2.9.1).

Statement period: ``period_start`` is the calendar date ``DTSTART`` names.
``period_end`` is the calendar date ``DTEND`` names, except that an end stamped
exactly at midnight (``HHMMSS`` all zero, any fraction zero, in the stamp's own
time zone) marks the start of that day, so the period ends the day before. A
date-only ``DTEND`` covers its whole day. Batch 2 uses the period as import
coverage, so the midnight rule errs toward claiming one day less.
"""
import hashlib
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal

from app.ledger.importers.amounts import NumberFormat, parse_amount
from app.ledger.importers.decoding import MAX_ROWS, decode_bytes, detect_format
from app.ledger.importers.errors import ImportFileError, IssueLog, RowIssue
from app.ledger.importers.keys import normalize_description, row_key
from app.ledger.types import NormalizedAccount, NormalizedTransaction

StatementKind = Literal["bank", "credit_card"]

MAX_DEPTH = 64
MAX_VALUE_LENGTH = 1024
DESCRIPTION_LENGTH, MERCHANT_LENGTH = 255, 255

#: OFX ``ACCTTYPE`` to (``account_type``, ``subtype``). A credit line is a
#: borrowing account, not a card, so it does not feed spending by default.
BANK_ACCOUNT_TYPES: dict[str, tuple[str, str | None]] = {
    "CHECKING": ("DEPOSITORY", "CHECKING"),
    "SAVINGS": ("DEPOSITORY", "SAVINGS"),
    "MONEYMRKT": ("DEPOSITORY", "MONEY_MARKET"),
    "CD": ("DEPOSITORY", "CD"),
    "CREDITLINE": ("CREDIT", "LINE_OF_CREDIT"),
}
_SUBTYPE_LABELS = {
    "CHECKING": "Checking", "SAVINGS": "Savings", "MONEY_MARKET": "Money market", "CD": "CD",
    "LINE_OF_CREDIT": "Credit line", "CREDIT_CARD": "Credit card",
}

# An open tag followed by text is a leaf (SGML leaves have no closing tag); one
# followed directly by another tag is an aggregate, unless it is a known leaf
# left empty, so an empty SGML leaf never swallows its siblings.
_LEAVES = frozenset({
    "TRNTYPE", "DTPOSTED", "DTUSER", "DTAVAIL", "TRNAMT", "FITID", "CORRECTFITID", "CORRECTACTION", "SRVRTID",
    "CHECKNUM", "REFNUM", "SIC", "PAYEEID", "NAME", "MEMO", "CURDEF", "BANKID", "BRANCHID", "ACCTID", "ACCTTYPE",
    "ACCTKEY", "BALAMT", "DTASOF", "DTSTART", "DTEND", "CODE", "SEVERITY", "MESSAGE", "DTSERVER", "LANGUAGE",
    "ORG", "FID", "TRNUID", "CURRATE", "CURSYM", "EXTDNAME", "INTU.BID", "INTU.USERID",
})
_TAG = re.compile(r"(/?)([A-Za-z0-9_.]{1,64})")
_ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
_ENTITY = re.compile(r"&(#x[0-9A-Fa-f]{1,6}|#[0-9]{1,7}|[A-Za-z]{2,6});")
_DATETIME = re.compile(
    r"^(\d{4})(\d{2})(\d{2})"
    r"(?:(\d{2})(\d{2})(?:(\d{2})(?:\.(\d{1,6}))?)?)?"
    r"\s*(?:\[\s*([+-]?\d{1,2}(?:[.:]\d{1,2})?)?\s*(?::\s*[A-Za-z0-9_+-]{0,10})?\s*\])?$"
)
_WHITESPACE = re.compile(r"\s+")


# --------------------------------------------------------------------------- tokenizer


@dataclass
class _Node:
    name: str
    value: str | None = None
    children: list["_Node"] = field(default_factory=list)

    def child(self, name: str) -> "_Node | None":
        return next((node for node in self.children if node.name == name), None)

    def text(self, name: str) -> str | None:
        node = self.child(name)
        if node is None:
            return None
        return (node.value or "").strip() or None

    def walk(self, name: str) -> Iterator["_Node"]:
        for node in self.children:
            if node.name == name:
                yield node
            else:
                yield from node.walk(name)


def _unescape(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token.startswith("#"):
            code = int(token[2:], 16) if token[1:2] in ("x", "X") else int(token[1:])
            return chr(code) if 0 < code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF else ""
        return _ENTITIES.get(token.lower(), match.group(0))

    return _ENTITY.sub(replace, value)


def _tokens(body: str) -> Iterator[tuple[str, str]]:
    """Yield (``open`` | ``close`` | ``text``, value) in one linear pass."""
    position, length = 0, len(body)
    while position < length:
        start = body.find("<", position)
        if start < 0:
            yield "text", body[position:]
            return
        if start > position:
            yield "text", body[position:start]
        if body.startswith("<!--", start):
            end = body.find("-->", start + 4)
            position = length if end < 0 else end + 3
            continue
        end = body.find(">", start + 1)
        if end < 0:
            return  # Unterminated tag: the rest of the file is ignored.
        if body.startswith(("<!", "<?"), start):
            position = end + 1
            continue
        inner_start = body.rfind("<", start, end) + 1
        match = _TAG.fullmatch(body, inner_start, end)
        if match:
            yield ("close" if match.group(1) else "open"), match.group(2).upper()
        position = end + 1


def _tree(text: str) -> _Node:
    begin = re.search(r"<OFX>", text, re.IGNORECASE)
    if begin is None:
        raise ImportFileError("MALFORMED_OFX", "File has no OFX body.")
    root = _Node("#root")
    stack = [root]
    pending: _Node | None = None  # an open tag waiting to learn whether it holds text
    for kind, value in _tokens(text[begin.start():]):
        if kind == "text":
            if pending is not None and value.strip():
                pending.value = _unescape(_WHITESPACE.sub(" ", value.strip()[:MAX_VALUE_LENGTH]))
                stack[-1].children.append(pending)
                pending = None
            continue
        if pending is not None:
            _settle(pending, stack)
            pending = None
        if kind == "open":
            pending = _Node(value)
        else:
            names = [node.name for node in stack]
            if value in names[1:]:
                del stack[len(names) - names[::-1].index(value) - 1:]
    if pending is not None:
        _settle(pending, stack)
    return root


def _settle(node: _Node, stack: list[_Node]) -> None:
    """An open tag followed directly by another tag: empty leaf or aggregate."""
    stack[-1].children.append(node)
    if node.name in _LEAVES:
        return
    if len(stack) > MAX_DEPTH:
        raise ImportFileError("MALFORMED_OFX", "File nests too deeply.", {"max_depth": MAX_DEPTH})
    stack.append(node)


# --------------------------------------------------------------------------- values


@dataclass(frozen=True)
class OfxDateTime:
    """An OFX datetime: the calendar date it names and, when stamped, its time
    and UTC offset (``None`` when the stamp has no zone)."""

    date: date
    time: time | None
    offset: timedelta | None

    @property
    def is_midnight(self) -> bool:
        return self.time is not None and self.time == time(0, 0)

    def as_datetime(self) -> datetime:
        zone = timezone(self.offset) if self.offset is not None else UTC
        return datetime.combine(self.date, self.time or time(0, 0), tzinfo=zone)


def parse_ofx_datetime(text: str | None) -> OfxDateTime | None:
    """``YYYYMMDD[HHMM[SS[.XXX]]][ [gmt offset[:tz name]]]``, or None."""
    if not text:
        return None
    match = _DATETIME.match(text.strip())
    if not match:
        return None
    year, month, day, hour, minute, second, fraction, offset = match.groups()
    try:
        calendar_date = date(int(year), int(month), int(day))
        clock = None
        if hour is not None:
            micro = int((fraction or "0").ljust(6, "0"))
            clock = time(int(hour), int(minute), int(second or 0), micro)
    except ValueError:
        return None
    zone = None
    if offset:
        # "-3.5" is decimal hours; "+5:30" is hours and minutes.
        hours_text, separator, rest = offset.partition(":") if ":" in offset else offset.partition(".")
        hours = abs(int(hours_text))
        if separator == ":":
            minutes = int(rest)
        else:
            minutes = round(float(f"0.{rest}") * 60) if rest else 0
        if hours > 14 or minutes >= 60:
            return None
        sign = -1 if hours_text.startswith("-") else 1
        zone = sign * timedelta(hours=hours, minutes=minutes)
    return OfxDateTime(calendar_date, clock, zone)


def _amount(text: str | None) -> Decimal | None:
    """OFX amounts use a period or a comma as the decimal and no grouping."""
    if not text:
        return None
    cleaned = text.strip()
    if "," in cleaned and "." in cleaned:
        return None
    parsed = parse_amount(cleaned, NumberFormat("," if "," in cleaned else "."))
    if parsed is None or parsed.direction is not None:
        return None
    return parsed.value


# --------------------------------------------------------------------------- statements


@dataclass(frozen=True)
class OfxStatement:
    """One account's statement in the file.

    ``transaction_types`` maps each transaction's ``external_id`` to its OFX
    ``TRNTYPE``. ``removed_external_ids`` lists FITIDs that correction records
    delete or replace; rows already stored under them must be removed.
    ``derived_id_count`` counts transactions without a FITID whose key was
    derived from date, amount, description and occurrence, as for CSV rows.
    """

    kind: StatementKind
    account: NormalizedAccount
    period_start: date | None
    period_end: date | None
    transactions: tuple[NormalizedTransaction, ...]
    transaction_types: dict[str, str]
    removed_external_ids: tuple[str, ...]
    issues: tuple[RowIssue, ...]
    issue_count: int
    derived_id_count: int


@dataclass(frozen=True)
class OfxParseResult:
    encoding: str
    statements: tuple[OfxStatement, ...]
    unsupported_statement_count: int


def _account(kind: StatementKind, statement: _Node, institution: str | None) -> NormalizedAccount:
    source = statement.child("BANKACCTFROM" if kind == "bank" else "CCACCTFROM") or _Node("#missing")
    account_id = source.text("ACCTID")
    if account_id is None:
        raise ImportFileError("MALFORMED_OFX", "A statement has no account ID.")
    if kind == "bank":
        raw_type = (source.text("ACCTTYPE") or "").upper()
        account_type, subtype = BANK_ACCOUNT_TYPES.get(raw_type, ("OTHER", None))
        identity = f"bank|{source.text('BANKID') or ''}|{source.text('BRANCHID') or ''}|{account_id}"
    else:
        account_type, subtype = "CREDIT", "CREDIT_CARD"
        identity = f"cc|{account_id}"
    mask = re.sub(r"[^0-9A-Za-z]", "", account_id)[-4:] or None
    label = _SUBTYPE_LABELS.get(subtype or "", "Account")
    balance_node = statement.child("LEDGERBAL")
    balance = _amount(balance_node.text("BALAMT")) if balance_node else None
    balance_stamp = parse_ofx_datetime(balance_node.text("DTASOF")) if balance_node else None
    if balance is not None and account_type in ("CREDIT", "LOAN"):
        # OFX signs balances from the holder's side: a debt is negative.
        balance = -balance
    return NormalizedAccount(
        # A hash keeps the full account number out of storage.
        external_id="ofx-" + hashlib.sha256(identity.encode()).hexdigest()[:24],
        name=f"{label} ··{mask}" if mask else label,
        account_type=account_type,
        subtype=subtype,
        institution_name=institution,
        mask=mask,
        currency=(statement.text("CURDEF") or "").upper() or None,
        balance=balance,
        balance_date=balance_stamp.as_datetime() if balance_stamp else None,
    )


def _description(record: _Node) -> tuple[str, str | None]:
    payee = record.child("PAYEE")
    name = record.text("NAME") or (payee.text("NAME") or (payee.value or "").strip() or None if payee else None)
    memo = record.text("MEMO")
    check = record.text("CHECKNUM")
    parts = [name] if name else []
    if memo and (not name or memo.casefold() not in name.casefold()):
        parts.append(memo)
    description = " ".join(parts)
    if check and check not in description:
        description = f"Check {check}" + (f" {description}" if description else "")
    return description[:DESCRIPTION_LENGTH], (name[:MERCHANT_LENGTH] if name else None)


def _statement(kind: StatementKind, statement: _Node, institution: str | None) -> OfxStatement:
    account = _account(kind, statement, institution)
    transaction_list = statement.child("BANKTRANLIST") or _Node("#missing")
    start = parse_ofx_datetime(transaction_list.text("DTSTART"))
    end = parse_ofx_datetime(transaction_list.text("DTEND"))
    period_start = start.date if start else None
    period_end = None
    if end is not None:
        period_end = end.date - timedelta(days=1) if end.is_midnight else end.date
        if period_start is not None and period_end < period_start:
            period_end = period_start
    issues = IssueLog()
    found: dict[str, NormalizedTransaction] = {}
    types: dict[str, str] = {}
    removed: list[str] = []
    occurrences: Counter[tuple[date, Decimal, str]] = Counter()
    derived = 0
    records = list(transaction_list.walk("STMTTRN"))
    corrected = {
        target for record in records
        if (target := record.text("CORRECTFITID")) and (record.text("CORRECTACTION") or "").upper() in ("REPLACE", "DELETE")
    }
    for number, record in enumerate(records, start=1):
        correct_id = record.text("CORRECTFITID")
        action = (record.text("CORRECTACTION") or "").upper()
        if correct_id is not None:
            if action not in ("REPLACE", "DELETE"):
                issues.add(number, "invalid_correction")
                continue
            removed.append(correct_id)
            if action == "DELETE":
                continue
        elif record.text("FITID") in corrected:
            continue  # Superseded by a correction record in this file.
        stamp = parse_ofx_datetime(record.text("DTPOSTED"))
        if stamp is None:
            issues.add(number, "invalid_date" if record.text("DTPOSTED") else "missing_date")
            continue
        user_stamp = parse_ofx_datetime(record.text("DTUSER"))
        amount_text = record.text("TRNAMT")
        amount = _amount(amount_text)
        if amount is None:
            issues.add(number, "invalid_amount" if amount_text else "missing_amount")
            continue
        if not amount:
            issues.add(number, "zero_amount")
            continue
        ledger_amount = -amount  # OFX signs from the holder's side: a credit is positive.
        description, merchant = _description(record)
        transaction_date = user_stamp.date if user_stamp else stamp.date
        external_id = record.text("FITID")
        if external_id is None:
            key = (transaction_date, ledger_amount, normalize_description(description))
            external_id = row_key(transaction_date, ledger_amount, description, occurrences[key])
            occurrences[key] += 1
            derived += 1
        elif external_id in found:
            issues.add(number, "duplicate_fitid")
            continue
        currency = account.currency
        foreign = record.child("CURRENCY")
        if foreign is not None and foreign.text("CURSYM"):
            # CURRENCY: amounts are in CURSYM. ORIGCURRENCY: already in CURDEF.
            currency = (foreign.text("CURSYM") or "").upper()
        trntype = (record.text("TRNTYPE") or "OTHER").upper()
        found[external_id] = NormalizedTransaction(
            external_id=external_id,
            account_external_id=account.external_id,
            amount=ledger_amount,
            transaction_date=transaction_date,
            description=description,
            status="POSTED",
            posted_date=stamp.date,
            currency=currency,
            merchant_name=merchant,
        )
        types[external_id] = trntype
        if len(found) > MAX_ROWS:
            raise ImportFileError("TOO_MANY_ROWS", "File has more transactions than the import limit.", {"max_rows": MAX_ROWS})
    return OfxStatement(
        kind=kind, account=account, period_start=period_start, period_end=period_end,
        transactions=tuple(found.values()), transaction_types=types,
        removed_external_ids=tuple(dict.fromkeys(removed)),
        issues=tuple(issues.issues), issue_count=issues.count, derived_id_count=derived,
    )


def parse_ofx(data: bytes) -> OfxParseResult:
    """Parse an OFX or QFX download into one statement per account section.

    Bank (``STMTRS``) and credit card (``CCSTMTRS``) statements are read;
    investment statements are counted in ``unsupported_statement_count``, and a
    file holding only those raises ``UNSUPPORTED_STATEMENT``. A statement with
    no transactions is still returned: its period is coverage.
    """
    decoded = decode_bytes(data)
    if detect_format(decoded.text) != "ofx":
        raise ImportFileError("UNSUPPORTED_FORMAT", "File is not OFX or QFX.")
    root = _tree(decoded.text)
    signon = next(root.walk("SONRS"), None)
    fi = signon.child("FI") if signon else None
    institution = fi.text("ORG") if fi else None
    statements: list[OfxStatement] = []
    total = 0
    for node in root.walk("STMTRS"):
        statements.append(_statement("bank", node, institution))
    for node in root.walk("CCSTMTRS"):
        statements.append(_statement("credit_card", node, institution))
    for statement in statements:
        total += len(statement.transactions)
        if total > MAX_ROWS:
            raise ImportFileError("TOO_MANY_ROWS", "File has more transactions than the import limit.", {"max_rows": MAX_ROWS})
    unsupported = sum(1 for _ in root.walk("INVSTMTRS"))
    if not statements:
        if unsupported:
            raise ImportFileError("UNSUPPORTED_STATEMENT", "Investment statements are not supported.")
        raise ImportFileError("NO_STATEMENTS", "File has no bank or credit card statements.")
    return OfxParseResult(decoded.encoding, tuple(statements), unsupported)


__all__ = ["BANK_ACCOUNT_TYPES", "OfxDateTime", "OfxParseResult", "OfxStatement", "parse_ofx", "parse_ofx_datetime"]

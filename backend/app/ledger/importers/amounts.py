"""Amount text to decimals: separators, negative styles and debit/credit marks."""
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

#: Largest magnitude accepted; ``financial_transactions.amount`` is Numeric(15, 2).
MAX_AMOUNT = Decimal("999999999999.99")
CENT = Decimal("0.01")

NegativeStyle = Literal["minus", "parentheses", "trailing_minus", "cr_dr"]
Direction = Literal["in", "out"]

_CURRENCY_SYMBOLS = "$€£¥₹₩₪₱₽¢"
_SPACES = " \u00a0\u202f\u2009"
_MINUS_SIGNS = "-\u2212\u2013"
_CODE = re.compile(r"^(?:[A-Z]{3}\s*)?(.*?)(?:\s*[A-Z]{3})?$")
_MARK = re.compile(r"^(.*?)\s*(CR|DR)\.?$", re.IGNORECASE)
_DIGITS = re.compile(r"^(?:\d+(?:\.\d+)?|\.\d+)$")
_LOOSE_NUMBER = re.compile(r"\d")
_COMMA_DECIMAL = re.compile(r"\d,\d{1,2}$")
_DOT_DECIMAL = re.compile(r"\d\.\d{1,2}$")
_DOT_GROUPS = re.compile(r"\d\.\d{3}(?:\.\d{3})*(?:,\d+)?$")
_COMMA_GROUPS = re.compile(r"\d,\d{3}(?:,\d{3})*(?:\.\d+)?$")


@dataclass(frozen=True)
class NumberFormat:
    """Decimal separator of a file's amounts. The other of ``.`` and ``,``,
    spaces and apostrophes are thousands separators."""

    decimal_separator: Literal[".", ","] = "."

    @property
    def thousands_separator(self) -> str:
        return "," if self.decimal_separator == "." else "."


@dataclass(frozen=True)
class ParsedAmount:
    """``value`` carries the text's own sign; ``direction`` is set when the text
    has a CR (money in) or DR (money out) mark, which then decides the sign."""

    value: Decimal
    direction: Direction | None = None


def parse_amount(text: str, number_format: NumberFormat = NumberFormat()) -> ParsedAmount | None:
    """Parse one amount cell, or None when it is not a number.

    Accepts currency symbols and ISO codes, a leading or trailing minus,
    parentheses and CR/DR marks. Digits beyond cents must be zeros (``1.234``
    under a dot decimal is refused rather than rounded, since it usually means
    the separators were misread). Blank cells are None; the caller decides
    whether blank is allowed.
    """
    raw = text.strip().strip(_SPACES)
    if not raw or len(raw) > 40:
        return None
    direction: Direction | None = None
    mark = _MARK.match(raw)
    if mark:
        raw = mark.group(1)
        direction = "in" if mark.group(2).upper() == "CR" else "out"
    negative = False
    raw = raw.strip(_SPACES)
    if raw.startswith("(") and raw.endswith(")"):
        negative, raw = True, raw[1:-1]
    raw = _strip_currency(raw)
    if raw[:1] in _MINUS_SIGNS:
        negative, raw = not negative, raw[1:]
    elif raw[-1:] in _MINUS_SIGNS:
        negative, raw = not negative, raw[:-1]
    elif raw[:1] == "+":
        raw = raw[1:]
    raw = _strip_currency(raw)
    for char in _SPACES + "'":
        raw = raw.replace(char, "")
    raw = raw.replace(number_format.thousands_separator, "")
    if number_format.decimal_separator == ",":
        raw = raw.replace(",", ".")
    if not _DIGITS.match(raw):
        return None
    fraction = raw.partition(".")[2]
    if fraction[2:].strip("0"):
        # More than cents usually means the separators were read the wrong way.
        return None
    value = Decimal(raw).quantize(CENT, rounding=ROUND_HALF_UP)  # the pattern admits only valid decimals
    if value > MAX_AMOUNT:
        return None
    return ParsedAmount(-value if negative else value, direction)


def _strip_currency(raw: str) -> str:
    raw = raw.strip(_SPACES).strip(_CURRENCY_SYMBOLS).strip(_SPACES)
    match = _CODE.match(raw)
    return match.group(1).strip(_SPACES) if match else raw  # no match only across a line break


def looks_numeric(text: str) -> bool:
    """Loose check used for column-role and header detection."""
    stripped = text.strip()
    return bool(stripped) and bool(_LOOSE_NUMBER.search(stripped)) and (
        parse_amount(stripped) is not None or parse_amount(stripped, NumberFormat(",")) is not None
    )


def detect_number_format(values: Iterable[str]) -> NumberFormat:
    """Comma decimal when the amounts' own evidence says so, else dot."""
    comma = dot = 0
    for value in values:
        text = _strip_marks(value)
        if _DOT_GROUPS.search(text) and "," in text or _COMMA_DECIMAL.search(text) and "." not in text[-3:]:
            comma += 1
        elif _COMMA_GROUPS.search(text) and "." in text or _DOT_DECIMAL.search(text):
            dot += 1
    return NumberFormat(",") if comma > dot else NumberFormat(".")


def detect_negative_styles(values: Iterable[str]) -> tuple[NegativeStyle, ...]:
    """Negative styles seen in a column, in a fixed order."""
    seen: set[NegativeStyle] = set()
    for value in values:
        text = value.strip()
        if not text or not _LOOSE_NUMBER.search(text):
            continue
        mark = _MARK.match(text)
        if mark:
            seen.add("cr_dr")
            text = mark.group(1).strip()
        if text.startswith("(") and text.endswith(")"):
            seen.add("parentheses")
        stripped = _strip_currency(text)
        if stripped[:1] in _MINUS_SIGNS:
            seen.add("minus")
        elif stripped[-1:] in _MINUS_SIGNS:
            seen.add("trailing_minus")
    order: tuple[NegativeStyle, ...] = ("minus", "parentheses", "trailing_minus", "cr_dr")
    return tuple(style for style in order if style in seen)


def currency_symbols(values: Iterable[str]) -> tuple[str, ...]:
    """Currency symbols that appear in amount cells."""
    seen = {char for value in values for char in value if char in _CURRENCY_SYMBOLS}
    return tuple(sorted(seen))


def _strip_marks(value: str) -> str:
    text = value.strip()
    mark = _MARK.match(text)
    if mark:
        text = mark.group(1)
    return _strip_currency(text.strip("()")).strip(_MINUS_SIGNS + "+")

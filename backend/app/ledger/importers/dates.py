"""CSV date formats: detection with explicit month/day ambiguity."""
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

#: Supported formats (strptime pattern, display label), in suggestion order.
DATE_FORMATS: tuple[tuple[str, str], ...] = (
    ("%Y-%m-%d", "YYYY-MM-DD"),
    ("%Y/%m/%d", "YYYY/MM/DD"),
    ("%Y.%m.%d", "YYYY.MM.DD"),
    ("%Y%m%d", "YYYYMMDD"),
    ("%m/%d/%Y", "MM/DD/YYYY"),
    ("%m/%d/%y", "MM/DD/YY"),
    ("%m-%d-%Y", "MM-DD-YYYY"),
    ("%m-%d-%y", "MM-DD-YY"),
    ("%m.%d.%Y", "MM.DD.YYYY"),
    ("%d/%m/%Y", "DD/MM/YYYY"),
    ("%d/%m/%y", "DD/MM/YY"),
    ("%d-%m-%Y", "DD-MM-YYYY"),
    ("%d-%m-%y", "DD-MM-YY"),
    ("%d.%m.%Y", "DD.MM.YYYY"),
    ("%d.%m.%y", "DD.MM.YY"),
    ("%d %b %Y", "DD Mon YYYY"),
    ("%d-%b-%Y", "DD-Mon-YYYY"),
    ("%d-%b-%y", "DD-Mon-YY"),
    ("%b %d, %Y", "Mon DD, YYYY"),
    ("%b %d %Y", "Mon DD YYYY"),
    ("%d %B %Y", "DD Month YYYY"),
    ("%B %d, %Y", "Month DD, YYYY"),
)
_LABELS = dict(DATE_FORMATS)
_TIME_SUFFIX = re.compile(r"(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?\s*(?:[AaPp][Mm])?(?:Z|[+-]\d{2}:?\d{2})?)$")
_MIN_YEAR, _MAX_YEAR = 1970, 2100


@dataclass(frozen=True)
class DateFormatCandidate:
    """A format that reads every dated row, with the range it implies."""

    format: str
    label: str
    matches: int
    date_from: date
    date_to: date


@dataclass(frozen=True)
class DateDetection:
    """``suggested`` is None when no format fits or when candidates disagree
    (US versus day-first): the customer must choose; it is never guessed."""

    candidates: tuple[DateFormatCandidate, ...]
    suggested: str | None
    ambiguous: bool


def parse_date(text: str, fmt: str) -> date | None:
    """Parse one date cell in a supported format; a trailing time is ignored."""
    value = _TIME_SUFFIX.sub("", text.strip()).strip()
    if not value or len(value) > 40:
        return None
    try:
        parsed = datetime.strptime(value, fmt).date()
    except ValueError:
        return None
    return parsed if _MIN_YEAR <= parsed.year <= _MAX_YEAR else None


def looks_like_date(text: str) -> bool:
    return any(parse_date(text, fmt) is not None for fmt, _ in DATE_FORMATS)


def detect_date_formats(values: Sequence[str]) -> DateDetection:
    """Formats that read the most non-blank values (at least 90% of them).

    When more than one format remains and they read some value as different
    dates, detection is ambiguous. Formats that agree on every value (a file
    whose days all equal their months) are not ambiguous.
    """
    cells = Counter(value.strip() for value in values if value.strip())
    if not cells:
        return DateDetection((), None, False)
    total = sum(cells.values())
    distinct_cells = list(cells)
    parsed: dict[str, list[date | None]] = {fmt: [parse_date(cell, fmt) for cell in distinct_cells] for fmt, _ in DATE_FORMATS}
    counts = {
        fmt: sum(cells[cell] for cell, item in zip(distinct_cells, dates, strict=True) if item is not None)
        for fmt, dates in parsed.items()
    }
    best = max(counts.values())
    if best == 0 or best < 0.9 * total:
        return DateDetection((), None, False)
    candidates = []
    for fmt, label in DATE_FORMATS:
        if counts[fmt] != best:
            continue
        found = [item for item in parsed[fmt] if item is not None]
        candidates.append(DateFormatCandidate(fmt, label, best, min(found), max(found)))
    readings = {tuple(parsed[candidate.format]) for candidate in candidates}
    ambiguous = len(readings) > 1
    return DateDetection(tuple(candidates), None if ambiguous else candidates[0].format, ambiguous)


def date_format_label(fmt: str) -> str | None:
    return _LABELS.get(fmt)

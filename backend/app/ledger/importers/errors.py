"""Errors and per-row diagnostics shared by the file importers.

Messages and reasons never quote file content: no amounts, descriptions,
account numbers or raw cell text. A row is identified by its number only.
"""
from dataclasses import dataclass, field
from typing import Any

#: Per-row issues kept in a result; ``issue_count`` still counts every one.
MAX_ISSUES = 200


class ImportFileError(ValueError):
    """The whole file cannot be imported.

    ``code`` is stable for clients (``FILE_TOO_LARGE``, ``EMPTY_FILE``,
    ``UNDECODABLE``, ``TOO_MANY_ROWS``, ``UNSUPPORTED_FORMAT``,
    ``MALFORMED_CSV``, ``MALFORMED_OFX``, ``INVALID_MAPPING``,
    ``NO_USABLE_ROWS``, ``NO_STATEMENTS``, ``UNSUPPORTED_STATEMENT``).
    ``details`` carries limits or field names, never file content.
    """

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class RowIssue:
    """One skipped row: its 1-based number in the file and a reason code.

    CSV rows count every record in the file, preamble and header included, so
    the number matches the spreadsheet row. OFX rows count transactions within
    their statement.
    """

    row: int
    reason: str
    column: int | None = None


@dataclass
class IssueLog:
    """Collects issues up to ``MAX_ISSUES`` while counting all of them."""

    issues: list[RowIssue] = field(default_factory=list)
    count: int = 0

    def add(self, row: int, reason: str, column: int | None = None) -> None:
        self.count += 1
        if len(self.issues) < MAX_ISSUES:
            self.issues.append(RowIssue(row, reason, column))

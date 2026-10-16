"""File importers: CSV and OFX/QFX text to normalized ledger transactions.

Pure functions, bytes in: no database, routes or category mapping. Limits:
``MAX_FILE_BYTES`` (10 MiB) and ``MAX_ROWS`` (50,000 data rows or OFX
transactions per file).
"""
from app.ledger.importers.amounts import NumberFormat
from app.ledger.importers.csv_parser import (
    CsvColumn,
    CsvMapping,
    CsvParseResult,
    CsvPreview,
    SignSuggestion,
    detect_mapped_dates,
    parse_csv,
    preview_csv,
)
from app.ledger.importers.dates import DATE_FORMATS, DateDetection, DateFormatCandidate
from app.ledger.importers.decoding import (
    MAX_FILE_BYTES,
    MAX_ROWS,
    DecodedText,
    FileFormat,
    decode_bytes,
    detect_format,
)
from app.ledger.importers.errors import ImportFileError, RowIssue
from app.ledger.importers.keys import row_key
from app.ledger.importers.ofx_parser import (
    BANK_ACCOUNT_TYPES,
    OfxParseResult,
    OfxStatement,
    parse_ofx,
    parse_ofx_datetime,
)


def detect_file_format(data: bytes) -> FileFormat:
    """Decode an upload and name its format (``csv``, ``ofx`` or ``unknown``)."""
    return detect_format(decode_bytes(data).text)


__all__ = [
    "BANK_ACCOUNT_TYPES", "DATE_FORMATS", "MAX_FILE_BYTES", "MAX_ROWS",
    "CsvColumn", "CsvMapping", "CsvParseResult", "CsvPreview", "DateDetection", "DateFormatCandidate", "DecodedText", "FileFormat",
    "ImportFileError", "NumberFormat", "OfxParseResult", "OfxStatement", "RowIssue", "SignSuggestion",
    "decode_bytes", "detect_file_format", "detect_format", "detect_mapped_dates", "parse_csv", "parse_ofx", "parse_ofx_datetime",
    "preview_csv", "row_key",
]

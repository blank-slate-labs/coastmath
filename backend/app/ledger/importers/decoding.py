"""Bytes to text, input caps and format detection for imported files."""
import re
from dataclasses import dataclass
from typing import Literal

from app.ledger.importers.errors import ImportFileError

#: Largest accepted file. Batch 2 sizes the upload request limit from this.
MAX_FILE_BYTES = 10 * 1024 * 1024
#: Most data rows (CSV records after the header, or OFX transactions) per file.
MAX_ROWS = 50_000

FileFormat = Literal["csv", "ofx", "unknown"]

_UTF8_BOM = b"\xef\xbb\xbf"
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
_UTF32_BOMS = (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")
_CSV_DELIMITERS = (",", ";", "\t", "|")
_OFX_SNIFF_CHARS = 4096


@dataclass(frozen=True)
class DecodedText:
    """Decoded file text with newlines normalized to ``\\n``."""

    text: str
    encoding: Literal["utf-8", "utf-16", "windows-1252"]


def decode_bytes(data: bytes) -> DecodedText:
    """Decode an uploaded file.

    UTF-8 (with or without BOM) and UTF-16 with a BOM decode exactly; anything
    that is not valid UTF-8 falls back to Windows-1252, the usual encoding of
    bank downloads that are not UTF-8. NUL characters (UTF-32, UTF-16 without
    a BOM, binary files) are refused.
    """
    if len(data) > MAX_FILE_BYTES:
        raise ImportFileError("FILE_TOO_LARGE", "File is larger than the import limit.", {"max_bytes": MAX_FILE_BYTES})
    if data.startswith(_UTF32_BOMS):
        raise ImportFileError("UNDECODABLE", "File encoding is not supported.")
    encoding: Literal["utf-8", "utf-16", "windows-1252"]
    if data.startswith(_UTF8_BOM):
        text, encoding = _strict(data[len(_UTF8_BOM):], "utf-8"), "utf-8"
    elif data.startswith(_UTF16_BOMS):
        text, encoding = _strict(data, "utf-16"), "utf-16"
    else:
        try:
            text, encoding = data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            text, encoding = data.decode("cp1252", errors="replace"), "windows-1252"
    if "\x00" in text:
        raise ImportFileError("UNDECODABLE", "File encoding is not supported.")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise ImportFileError("EMPTY_FILE", "File is empty.")
    return DecodedText(text, encoding)


def _strict(data: bytes, codec: str) -> str:
    try:
        return data.decode(codec)
    except UnicodeDecodeError as exc:
        raise ImportFileError("UNDECODABLE", "File encoding is not supported.") from exc


def detect_format(text: str) -> FileFormat:
    """OFX/QFX (SGML header, XML with an OFX processing instruction, or a bare
    ``<OFX>`` root), CSV (delimited lines), or unknown."""
    head = text.lstrip()[:_OFX_SNIFF_CHARS]
    upper = head.upper()
    if upper.startswith("OFXHEADER") or "<?OFX" in upper or re.match(r"(<\?XML[^>]*>\s*)?<OFX>", upper):
        return "ofx"
    if head.startswith("<"):
        return "unknown"
    lines = [line for line in head.split("\n")[:50] if line.strip()]
    if any(delimiter in line for line in lines for delimiter in _CSV_DELIMITERS):
        return "csv"
    return "unknown"

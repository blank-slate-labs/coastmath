"""Stable row keys for transactions that carry no provider ID."""
import hashlib
import re
from datetime import date
from decimal import Decimal

_WHITESPACE = re.compile(r"\s+")


def normalize_description(text: str) -> str:
    """Casefolded, whitespace-collapsed text used in row keys."""
    return _WHITESPACE.sub(" ", text).strip().casefold()


def row_key(transaction_date: date, amount: Decimal, description: str, occurrence: int) -> str:
    """Key from the transaction date, ledger-signed amount, normalized
    description and the occurrence index of that tuple within one file.

    The same rows produce the same keys in every file that contains them, so
    re-importing a file or an overlapping one finds the stored rows again.
    """
    material = f"{transaction_date.isoformat()}|{amount:.2f}|{normalize_description(description)}|{occurrence}"
    return "row-" + hashlib.sha256(material.encode()).hexdigest()[:32]

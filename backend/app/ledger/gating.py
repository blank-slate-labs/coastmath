"""Release gate shared by ledger and spending-model routers."""
from fastapi import Request

from app.errors import api_error
from app.feature_flags import transactions_enabled

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "DELETE"})
#: Session capability advertised while the feature is on, so native clients show
#: Transactions and month comparisons only on servers that accept changes.
TRANSACTIONS_CAPABILITY = "transactions"


def session_capabilities() -> list[str]:
    return [TRANSACTIONS_CAPABILITY] if transactions_enabled() else []


def require_transactions_enabled(request: Request) -> None:
    """Router dependency: refuse changes while the feature is off.

    Reads and deletions stay available so customers can always see and remove
    data saved while the feature was on.
    """
    if request.method not in READ_METHODS and not transactions_enabled():
        raise api_error(503, "FEATURE_DISABLED", "Transactions are unavailable in this release.")

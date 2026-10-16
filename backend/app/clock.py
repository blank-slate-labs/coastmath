"""UTC time helpers shared by models, routes and the ledger."""
from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime | None) -> datetime | None:
    """``value`` as an aware UTC time, or None.

    Stored times are UTC. This guards comparisons against naive values from
    drivers, providers or tests (read as UTC) and converts an aware value in
    another zone to the same instant in UTC.
    """
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

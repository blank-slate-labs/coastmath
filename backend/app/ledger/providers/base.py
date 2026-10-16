"""The seam every synced provider adapter implements (duck-typed).

An adapter has a ``provider`` key and three methods.

The ledger sync worker runs a connection in two phases so no database lock is
held during provider calls:

1. ``read(connection, secret, today)`` performs every remote call and returns
   an opaque read. It may look at the connection's fields (last success,
   cursor) but never writes to the database.
2. ``store(db, connection, read, now)`` writes accounts and transactions under
   the user lock and returns the accounts it updated. A cursor-based provider
   saves its cursor here, after every page is stored.

``revoke(secret)`` removes the provider's access remotely before a disconnect
or an account deletion completes. Providers whose access ends when the
credential is dropped (SimpleFIN) make it a no-op. It raises ``ProviderError``
when revocation fails, which keeps the connection in place.

Link flows differ (a pasted token, a hosted widget) and live in the routes;
they end by creating a connection through ``app.ledger.connections``.
"""
from dataclasses import dataclass, field
from datetime import timedelta

#: Default time between successful syncs.
SYNC_INTERVAL = timedelta(hours=12)


@dataclass
class SyncOutcome:
    """What a stored read changed. ``notice`` is user-safe text from the provider."""

    source_ids: set[str] = field(default_factory=set)
    notice: str | None = None
    next_check: timedelta = SYNC_INTERVAL
    institution_name: str | None = None


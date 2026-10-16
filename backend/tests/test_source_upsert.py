"""Both pull adapters' upsert_account: a late read never regresses a newer balance, and an unchanged read keeps the revision."""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.clock import aware, utcnow
from app.ledger import connections as lifecycle
from app.ledger.providers import plaid_adapter, simplefin_adapter
from app.ledger.types import NormalizedAccount

ADAPTERS = {
    "plaid": (plaid_adapter, "DEPOSITORY"),
    "simplefin": (simplefin_adapter, None),
}


@pytest.mark.parametrize("provider", sorted(ADAPTERS))
def test_an_older_balance_read_keeps_the_newer_balance(plaid, db_session, test_user, provider):
    adapter, account_type = ADAPTERS[provider]
    connection = lifecycle.create_connection(db_session, test_user.id, provider, "secret",
                                             institution_name="Synthetic Bank")
    now = utcnow()

    def read(balance: str, stamp, at):
        account = NormalizedAccount(external_id="acc-1", name="Checking", account_type=account_type,
                                    institution_name="Synthetic Bank", currency="USD",
                                    balance=Decimal(balance), balance_date=stamp)
        return adapter.upsert_account(db_session, connection, account, at)

    source = read("100.00", now, now)
    assert (source.balance, source.revision) == (Decimal("100.00"), 1)
    assert source.connection_ids == [connection.provider_connection_id]

    # A late read carrying an older balance: the newer one stays and nothing else changed.
    later = now + timedelta(minutes=5)
    source = read("40.00", now - timedelta(days=1), later)
    assert source.balance == Decimal("100.00") and aware(source.balance_updated_at) == now
    assert source.revision == 1 and aware(source.fetched_at) == later
    assert source.connection_ids == [connection.provider_connection_id]

    # The same balance and time again, given as a naive UTC value, is not a change either.
    source = read("100.00", now.replace(tzinfo=None), later)
    assert source.revision == 1

    # A newer balance does change the source.
    source = read("120.00", later, later)
    assert source.balance == Decimal("120.00") and source.revision == 2

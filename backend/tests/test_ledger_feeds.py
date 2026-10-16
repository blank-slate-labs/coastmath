"""Provider-neutral feed entry points: refresh only the feeds that read changed accounts."""
from app.ledger.feeds import refresh_feeds
from tests.ledger_fixture import make_source, plan_with_feed


def test_refresh_without_accounts_touches_nothing(db_session, test_user):
    assert refresh_feeds(db_session, test_user.id, set()) == 0


def test_refresh_reapplies_only_feeds_reading_the_accounts(db_session, test_user):
    read = make_source(db_session, test_user, external="acct-read")
    other = make_source(db_session, test_user, external="acct-other")
    _, reading_feed = plan_with_feed(db_session, test_user, [read.id])
    _, other_feed = plan_with_feed(db_session, test_user, [other.id])
    reading_feed.error = other_feed.error = "Stale"
    db_session.flush()

    # Neither account has a complete month yet, so nothing is written, but the
    # feed that reads the changed account is re-evaluated and its error cleared.
    assert refresh_feeds(db_session, test_user.id, [read.id]) == 0
    assert reading_feed.error is None
    assert reading_feed.months_used == 0
    assert other_feed.error == "Stale"

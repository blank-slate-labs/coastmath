"""UTC helpers: utcnow is aware UTC; aware reads naive values as UTC and converts other zones."""
from datetime import UTC, datetime, timedelta, timezone

from app.clock import aware, utcnow


def test_utcnow_is_aware_utc():
    now = utcnow()
    assert now.tzinfo is UTC and now.utcoffset() == timedelta(0)


def test_aware_reads_a_naive_value_as_utc():
    assert aware(datetime(2026, 1, 2, 3, 4, 5)) == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert aware(datetime(2026, 1, 2, 3, 4, 5)).tzinfo is UTC


def test_aware_converts_another_zone_to_the_same_utc_instant():
    eastern = datetime(2026, 1, 1, 22, 0, tzinfo=timezone(timedelta(hours=-5)))
    converted = aware(eastern)
    assert converted == eastern and converted.tzinfo is UTC
    assert converted == datetime(2026, 1, 2, 3, 0, tzinfo=UTC)
    # The UTC date, not the local one.
    assert converted.date().isoformat() == "2026-01-02"


def test_aware_keeps_a_utc_value_and_none():
    value = datetime(2026, 5, 6, tzinfo=UTC)
    assert aware(value) == value and aware(value).tzinfo is UTC
    assert aware(None) is None

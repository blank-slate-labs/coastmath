"""Bound concurrent projection work per API worker, without a waiting queue.

Projection routes are synchronous, so they share the server's thread pool with
every other synchronous route. Per-user rate limits do not bound the total:
anonymous sessions are free to create. Excess projections are refused with 429,
as Monte Carlo already is, so unrelated requests keep their threads. One client
address holds at most ``SLOTS_PER_CLIENT`` projections across all workers
(app.client_slots), so it cannot take every slot with long runs.
"""
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from threading import BoundedSemaphore

from fastapi import HTTPException

from app.client_slots import client_slot
from app.errors import api_error

logger = logging.getLogger(__name__)

DEFAULT_ENGINE_CONCURRENCY = 4
#: A page asks for a few analyses at once (projection, checks, scorecard).
SLOTS_PER_CLIENT = 4


def parse_engine_concurrency(raw: str | None) -> int:
    """Slots per worker: blank or non-integer means the default; below 1 means 1."""
    if raw is None or not raw.strip():
        return DEFAULT_ENGINE_CONCURRENCY
    try:
        value = int(raw)
    except ValueError:
        logger.warning("ENGINE_CONCURRENCY=%r is not an integer; using %d",
                       raw, DEFAULT_ENGINE_CONCURRENCY)
        return DEFAULT_ENGINE_CONCURRENCY
    return max(1, value)


ENGINE_CONCURRENCY = parse_engine_concurrency(os.getenv("ENGINE_CONCURRENCY"))
_slots = BoundedSemaphore(ENGINE_CONCURRENCY)


def _busy() -> HTTPException:
    return api_error(
        429, "RATE_LIMIT_EXCEEDED", "The planner is busy. Please try again shortly.", headers={"Retry-After": "2"},
    )


@contextmanager
def engine_slot() -> Iterator[None]:
    with client_slot("engine", SLOTS_PER_CLIENT, _busy):
        if not _slots.acquire(blocking=False):
            raise _busy()
        try:
            yield
        finally:
            _slots.release()

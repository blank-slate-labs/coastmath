"""One Monte Carlo job per API worker, without an unbounded waiting queue.

One client address runs at most one job at a time across all workers
(app.client_slots); otherwise one request per worker would hold every slot.
A job also stops at ``TIME_LIMIT_SECONDS``: production's proxy answers 524
after 100 seconds, so a longer run could never reach its client.
"""
import asyncio
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from threading import BoundedSemaphore

from fastapi import HTTPException

from app.client_slots import client_slot
from app.errors import api_error, validation_error

_slot = BoundedSemaphore(1)

TIME_LIMIT_SECONDS = 90


def _busy() -> HTTPException:
    return api_error(
        429, "RATE_LIMIT_EXCEEDED", "A simulation is already running. Please try again shortly.",
        headers={"Retry-After": "5"},
    )


def deadline() -> float:
    """The ``time.monotonic()`` value a job starting now must finish by."""
    return time.monotonic() + TIME_LIMIT_SECONDS


def time_limit_error(field: str) -> Callable[[Exception], HTTPException]:
    """Translate the engine's time-limit error (``engine_errors`` ``translate``) for ``field``."""
    return lambda exc: validation_error(
        f"This run would take over {TIME_LIMIT_SECONDS} seconds. Run fewer trials.", field)


@contextmanager
def monte_carlo_slot() -> Iterator[None]:
    """The same slot for synchronous routes that run Monte Carlo trials inline."""
    with client_slot("monte_carlo", 1, _busy):
        if not _slot.acquire(blocking=False):
            raise _busy()
        try:
            yield
        finally:
            _slot.release()


async def run_with_capacity[T](operation: Callable[[], T]) -> T:
    held = ExitStack()
    held.enter_context(monte_carlo_slot())

    def run() -> T:
        with held:
            return operation()

    try:
        future = asyncio.get_running_loop().run_in_executor(None, run)
    except BaseException:
        held.close()
        raise
    # A disconnected/cancelled request must not release capacity while its
    # process pool still runs, or allow cancellation of a queued thread job.
    return await asyncio.shield(future)

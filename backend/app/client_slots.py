"""Cap one client address's share of engine capacity across worker processes.

Projection and Monte Carlo slots belong to each worker process, and requests
from one address spread over every worker, so per-worker counting would let
one address hold every slot in the container: one Monte Carlo request per
worker is enough. These caps are lock files that every worker process opens.
The kernel drops a lock when its holder closes the file or the process exits,
so a crashed worker never leaks a slot.

Addresses share a fixed set of lock files (``BUCKETS``) so that many distinct
addresses cannot create unbounded files. Two addresses on the same bucket share
one cap, which is rare while only a few runs are in flight.
"""
import hashlib
import logging
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

from app.rate_limit import current_client

try:
    import fcntl
except ImportError:  # Windows: no per-address cap, the per-worker slots still apply.
    fcntl = None

logger = logging.getLogger(__name__)

#: Shared by the worker processes of one deployment: the same database means the
#: same deployment, so local servers for different databases never block each other.
LOCK_DIR = Path(tempfile.gettempdir()) / (
    "coastmath_client_slots_" + hashlib.sha256(os.getenv("DATABASE_URL", "").encode()).hexdigest()[:12])
BUCKETS = 4096


def _bucket(key: str) -> int:
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "big") % BUCKETS


def _locked(path: Path) -> int | None:
    """An open descriptor holding ``path``'s exclusive lock, or None while another holder has it."""
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextmanager
def client_slot(kind: str, per_client: int, busy: Callable[[], HTTPException]) -> Iterator[None]:
    """Hold one of ``per_client`` ``kind`` slots for the current request's client, or raise ``busy()``.

    Requests without a client key (background work, scripts, tests that call
    the engine directly) are not capped here, nor is any request while the lock
    directory is unusable: the per-worker slots still bound the work.
    """
    key = current_client.get()
    fd = None
    if key is not None and fcntl is not None:
        bucket = _bucket(key)
        try:
            LOCK_DIR.mkdir(mode=0o700, exist_ok=True)
            for index in range(per_client):
                if (fd := _locked(LOCK_DIR / f"{kind}_{bucket}_{index}")) is not None:
                    break
            else:
                logger.warning("capacity: %s refused for client bucket %d (%d in use)", kind, bucket, per_client)
                raise busy()
        except OSError:
            logger.warning("capacity: per-client %s cap skipped; %s is unusable", kind, LOCK_DIR, exc_info=True)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)  # Closing the file releases the lock.

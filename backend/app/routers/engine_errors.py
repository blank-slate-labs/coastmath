"""One translation of projection-engine failures for every analysis route.

Routes that run the engine wrap the call in :func:`engine_errors`. It keeps the
error envelope the same whichever route ran the engine: plan input the engine
cannot model is a 422, and any other engine failure is logged without its
message and reported as 500 ``SIMULATION_FAILED``. Feature routers import this
module; it never imports one of them.
"""

import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from typing import Any

from fastapi import HTTPException

from app.engine_capacity import engine_slot
from app.errors import api_error, lifecycle_input_error
from app.safe_logging import exception_summary
from coastmath.engine.household_lifecycle import UnsupportedLifecycleInput

logger = logging.getLogger(__name__)

#: Route-specific 422s, checked in order after the lifecycle translation.
Translators = Mapping[type[Exception], Callable[[Any], HTTPException]]


@contextmanager
def engine_errors(
    message: str,
    log: str,
    *log_args: object,
    slot: bool = True,
    translate: Translators | None = None,
) -> Iterator[None]:
    """Run the enclosed engine call with the shared error translation.

    ``message`` is the 500 response text and never includes exception text.
    ``log`` and ``log_args`` name the route and the plan in the error log.
    ``slot`` acquires a projection slot first; routes that admit work through
    the Monte Carlo capacity pass False. ``HTTPException`` passes through
    unchanged, including the 429 from a busy slot.
    """
    try:
        with engine_slot() if slot else nullcontext():
            yield
    except HTTPException:
        raise
    except UnsupportedLifecycleInput as exc:
        raise lifecycle_input_error(exc) from exc
    except Exception as exc:
        for kind, translator in (translate or {}).items():
            if isinstance(exc, kind):
                raise translator(exc) from exc
        logger.error(log + ":\n%s", *log_args, exception_summary(exc))
        raise api_error(500, "SIMULATION_FAILED", message) from exc

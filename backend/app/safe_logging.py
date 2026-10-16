"""Log exceptions without their messages.

Exception text can quote user data: SQLAlchemy and database-driver errors carry
bound parameters and ``DETAIL: Key (email)=...``, engine errors can name
amounts, and provider SDK errors can repeat request fields. Logs keep each
exception's type and stack frames, which locate a failure without copying
financial or identity data into the deployment's logs.
"""
import traceback


def exception_summary(exc: BaseException) -> str:
    """Types and stack frames of ``exc`` and its causes; every message is withheld."""
    parts = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        kind = type(current)
        name = kind.__qualname__ if kind.__module__ == "builtins" else f"{kind.__module__}.{kind.__qualname__}"
        frames = "".join(traceback.format_tb(current.__traceback__))
        parts.append(f"{name} (message withheld)\n{frames}".rstrip())
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return "\nCaused by: ".join(parts)

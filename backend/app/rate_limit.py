"""Shared rate-limiter instance for the FastAPI application.

Defined in its own module to avoid circular imports between main.py
and the routers that need to reference the limiter.
"""

from contextvars import ContextVar
from ipaddress import IPv6Address, ip_address, ip_network

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.plugins import extensions

#: The client key of the request being served, set by app.middleware.client_budget.
#: Engine capacity reads it to cap one address's share of the slots (app.client_slots).
current_client: ContextVar[str | None] = ContextVar("current_client", default=None)


def address_key(address: str) -> str:
    """One key per IPv4 address or IPv6 /64: a single IPv6 host can use any address in its /64."""
    try:
        parsed = ip_address(address)
    except ValueError:
        return address
    if isinstance(parsed, IPv6Address):
        if parsed.ipv4_mapped is not None:
            return str(parsed.ipv4_mapped)
        return str(ip_network(f"{parsed}/64", strict=False))
    return str(parsed)


def client_address(request: Request) -> str:
    # A deployment behind a known edge may name the client from the edge's own
    # header (app.plugins). Elsewhere use Uvicorn's explicitly trusted proxy
    # configuration.
    if extensions.client_address is not None and (address := extensions.client_address(request)):
        return address_key(address)
    return address_key(get_remote_address(request))


def session_user(request: Request) -> str:
    # SlowAPI checks limits after FastAPI resolves dependencies, so routes that
    # depend on get_current_user are keyed by that user. Households behind one
    # NAT or carrier IP keep separate budgets; one session cannot drain others'.
    user_id = getattr(request.state, "user_id", None)
    return f"user:{user_id}" if user_id else client_address(request)


limiter = Limiter(key_func=client_address)

#: Every route that runs the projection engine also draws on one budget per
#: client address. Sessions are free to create, so the per-user limits alone
#: never bound what one address can ask the engine to do.
ENGINE_ADDRESS_LIMIT = "120/minute"
engine_budget = limiter.shared_limit(ENGINE_ADDRESS_LIMIT, scope="engine")

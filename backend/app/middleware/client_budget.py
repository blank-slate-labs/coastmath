"""Per-client request budgets, enforced before routing, sign-in checks or body parsing.

Route limits (app.rate_limit) run after FastAPI resolves a route's
dependencies, so a refused request has already cost a session lookup and a
parsed body, and most are keyed by session user, which anyone can create.
These budgets are keyed by client address (``client_address``) and refuse
before any of that work:

- requests in flight, so one address cannot hold the thread pool, the database
  connections or many buffered bodies;
- requests per minute, and state changes per minute.

The handler also records the address in ``current_client`` for the engine's
per-client slot caps (app.client_slots). Counts are per worker process, like
the route limits.
"""
import logging
import time
from collections import Counter

from limits import RateLimitItem, parse
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.rate_limit import client_address, current_client, limiter

logger = logging.getLogger(__name__)

MAX_IN_FLIGHT = 24
REQUESTS = parse("600/minute")
WRITES = parse("120/minute")
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: Platform health probes reach the container directly and must always answer.
EXEMPT_PATHS = frozenset({"/api/health", "/api/ready"})
#: Each refused address is logged at most once per interval.
LOG_INTERVAL_SECONDS = 60.0


def _refusal(message: str, retry_after: int) -> JSONResponse:
    return JSONResponse({"error": {"code": "RATE_LIMIT_EXCEEDED", "message": message, "details": []}},
                        status_code=429, headers={"Retry-After": str(max(1, retry_after))})


class ClientBudgetMiddleware:
    def __init__(self, app: ASGIApp, max_in_flight: int = MAX_IN_FLIGHT,
                 requests: RateLimitItem = REQUESTS, writes: RateLimitItem = WRITES) -> None:
        self.app = app
        self.max_in_flight = max_in_flight
        self.requests = requests
        self.writes = writes
        self.in_flight: Counter[str] = Counter()
        self.logged: dict[str, float] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/") or path in EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        key = client_address(Request(scope))
        refusal = self.refusal(key, scope["method"]) if limiter.enabled else None
        if refusal is not None:
            await refusal(scope, receive, send)
            return
        self.in_flight[key] += 1
        token = current_client.set(key)
        try:
            await self.app(scope, receive, send)
        finally:
            current_client.reset(token)
            self.in_flight[key] -= 1
            if self.in_flight[key] <= 0:
                del self.in_flight[key]

    def refusal(self, key: str, method: str) -> JSONResponse | None:
        if self.in_flight[key] >= self.max_in_flight:
            self.report(key, "in flight")
            return _refusal("Too many requests at once. Try again shortly.", 1)
        for item, scope in ((self.requests, "requests"), (self.writes, "writes")):
            if scope == "writes" and method in READ_METHODS:
                continue
            if not limiter.limiter.hit(item, "client_budget", scope, key):
                self.report(key, scope)
                reset = limiter.limiter.get_window_stats(item, "client_budget", scope, key).reset_time
                return _refusal("Too many requests. Try again in a minute.", int(reset - time.time()) + 1)
        return None

    def report(self, key: str, budget: str) -> None:
        now = time.monotonic()
        if now - self.logged.get(key, -LOG_INTERVAL_SECONDS) < LOG_INTERVAL_SECONDS:
            return
        if len(self.logged) >= 10_000:
            self.logged.clear()
        self.logged[key] = now
        logger.warning("client budget: refused %s (%s)", key, budget)

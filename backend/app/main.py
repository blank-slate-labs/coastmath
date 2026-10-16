import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from app.access import account_pool_guard, plan_guard, plan_read_guard
from app.auth.account_deletion import router as account_deletion_router
from app.auth.config import DEV_SESSION_SECRET, SESSION_SECRET
from app.auth.router import router as auth_router
from app.db import SessionLocal, engine
from app.errors import api_error
from app.feature_flags import api_docs_enabled, stateless_api_enabled
from app.ledger.suggestions import start_suggestion_worker
from app.ledger.sync_worker import run_sync_worker as run_ledger_sync_worker
from app.ledger.sync_worker import worker_wanted as ledger_worker_wanted
from app.middleware.body_limit import PATH_LIMITS, BodySizeLimitMiddleware
from app.middleware.client_budget import ClientBudgetMiddleware
from app.middleware.error_handler import (
    generic_exception_handler,
    http_exception_handler,
    rate_limit_exception_handler,
    validation_exception_handler,
)
from app.plugins import load_plugins
from app.rate_limit import limiter
from app.routers.accounts import plan_router as plan_accounts_router
from app.routers.accounts import router as accounts_router
from app.routers.assumptions import router as assumptions_router
from app.routers.charity import router as charity_router
from app.routers.clients import router as clients_router
from app.routers.drawdown import router as drawdown_router
from app.routers.expenses import router as expenses_router
from app.routers.incomes import router as incomes_router
from app.routers.ledger import router as ledger_router
from app.routers.ledger_connections import PLAID_WEBHOOK_PATH
from app.routers.ledger_connections import router as ledger_connections_router
from app.routers.ledger_feeds import router as ledger_feeds_router
from app.routers.ledger_imports import router as ledger_imports_router
from app.routers.ledger_suggestions import router as ledger_suggestions_router
from app.routers.liabilities import router as liabilities_router
from app.routers.local_tax_jurisdictions import router as local_tax_jurisdictions_router
from app.routers.milestones import router as milestones_router
from app.routers.monte_carlo import router as monte_carlo_router
from app.routers.monte_carlo_stateless import router as monte_carlo_stateless_router
from app.routers.plan_checks import router as plan_checks_router
from app.routers.plan_intake import router as plan_intake_router
from app.routers.plans import router as plans_router
from app.routers.priorities import router as priorities_router
from app.routers.progress_points import router as progress_points_router
from app.routers.public_help import help_router
from app.routers.readiness import router as readiness_router
from app.routers.real_assets import router as real_assets_router
from app.routers.scenarios import router as scenarios_router
from app.routers.simulation import router as simulation_router
from app.routers.simulation_stateless import router as simulation_stateless_router
from app.routers.spending_models import apply_router as spending_models_apply_router
from app.routers.spending_models import router as spending_models_router
from app.routers.ss_claiming import router as ss_claiming_router
from app.routers.tax_jurisdictions import router as tax_jurisdictions_router
from app.routers.tax_regimes import router as tax_regimes_router
from app.routers.tax_strategies import router as tax_strategies_router
from app.routers.tax_suggestions import router as tax_suggestions_router
from app.routers.wellness import router as wellness_router
from app.routers.withdrawal_strategies import router as withdrawal_strategies_router
from app.sqlite_schema import upgrade_sqlite_schema

logger = logging.getLogger(__name__)
# Before the app is built: plug-ins add routes, middleware sources and hooks.
extensions = load_plugins()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    if engine is None:
        raise RuntimeError(
            "DATABASE_URL is not configured. "
            "Set it to a PostgreSQL URL or to sqlite:////path/to/coastmath.db."
        )
    # Block startup if production is using the default dev secret
    if os.getenv("DATABASE_URL") and SESSION_SECRET == DEV_SESSION_SECRET:
        raise RuntimeError(
            "SESSION_SECRET must be changed from the default value "
            "in production deployments."
        )
    if len(SESSION_SECRET) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 characters")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            for check in extensions.startup_checks:
                check(conn)
        logger.info("Database connection verified")
    except Exception as e:
        raise RuntimeError(f"Database is not reachable: {e}") from e
    # PostgreSQL schemas are migrated before the app starts; an SQLite file upgrades itself.
    if engine.dialect.name == "sqlite":
        upgrade_sqlite_schema(engine)
    plugin_tasks = [start(SessionLocal) for start in extensions.background_tasks] if SessionLocal else []
    suggestion_worker = start_suggestion_worker(SessionLocal)
    ledger_worker = asyncio.create_task(run_ledger_sync_worker(SessionLocal)) if ledger_worker_wanted() and SessionLocal else None
    try:
        yield
    finally:
        for task in (*plugin_tasks, suggestion_worker, ledger_worker):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


# Without an OpenAPI URL, FastAPI also omits /docs and /redoc.
app = FastAPI(title="CoastMath", lifespan=lifespan, openapi_url="/openapi.json" if api_docs_enabled() else None)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)


def parse_allowed_origins(value: str) -> list[str]:
    """Comma-separated origins without surrounding spaces or a trailing slash; blanks are dropped.

    ``*`` and ``null`` are refused: with credentials allowed, either would let
    any site call the API with the user's cookie.
    """
    origins = [origin for origin in (origin.strip().rstrip("/") for origin in value.split(",")) if origin]
    refused = [origin for origin in origins if origin.lower() in ("*", "null")]
    if refused:
        raise ValueError(f"ALLOWED_ORIGINS must list specific origins; {', '.join(refused)} is not allowed")
    return origins


# One list for CORS and for the cross-site refusal below.
allowed_origins = parse_allowed_origins(os.getenv("ALLOWED_ORIGINS", "http://localhost:3000"))

# Plug-in middleware wraps the routes directly, so every built-in middleware
# below (size limit, client budget, CORS, security headers) runs around it.
for plugin_middleware, options in extensions.asgi_middleware:
    app.add_middleware(plugin_middleware, **options)
# Added next so it sits innermost of the built-ins: its 413 responses still
# receive CORS and security headers from the middleware below.
app.add_middleware(BodySizeLimitMiddleware, limits=(*PATH_LIMITS, *extensions.body_limits))
# Before routing, sign-in and body parsing; its 429s also get CORS headers.
app.add_middleware(ClientBudgetMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def cross_site_refusal(request) -> JSONResponse | None:
    """Refuse a browser state change that did not come from a trusted origin.

    Browsers send Origin with every cross-origin state change, so SameSite is
    not the only defence. Native clients send neither header checked here; the
    provider webhooks are signed server-to-server traffic.
    """
    path = request.url.path
    if not path.startswith("/api/") or request.method in ("GET", "HEAD", "OPTIONS") or path == PLAID_WEBHOOK_PATH or path in extensions.callback_paths:
        return None
    origin = request.headers.get("origin")
    trusted = {*allowed_origins, str(request.base_url).rstrip("/")}
    cross_site = request.headers.get("sec-fetch-site") in ("cross-site", "same-site")
    if (origin and origin not in trusted) or (not origin and cross_site):
        error = ({"code": "AUTH_ORIGIN_INVALID", "message": "Sessions must start from a trusted origin."} if path.startswith("/api/auth/")
                 else {"code": "ORIGIN_INVALID", "message": "Changes must come from CoastMath."})
        return JSONResponse({"error": {**error, "details": []}}, status_code=403)
    return None


# Enforced: directives no page relies on relaxing.
CONTENT_SECURITY_POLICY = "frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'"
# The full source allowlist is observed before it is enforced. Transaction
# linking loads and frames Plaid Link. Each directive lists its keywords, then
# plug-in sources (app.plugins), then the hosts the planner itself needs.
REPORT_ONLY_DIRECTIVES = [
    ("default-src", ["'self'"], []),
    ("script-src", ["'self'"], ["https://cdn.plaid.com"]),
    ("style-src", ["'self'", "'unsafe-inline'"], ["https://fonts.googleapis.com"]),
    ("font-src", ["'self'"], ["https://fonts.gstatic.com"]),
    ("img-src", ["'self'", "data:"], []),
    ("connect-src", ["'self'"], []),
    ("frame-src", [], ["https://cdn.plaid.com"]),
    ("worker-src", ["'self'"], []),
    ("manifest-src", ["'self'"], []),
    ("object-src", ["'none'"], []),
    ("base-uri", ["'none'"], []),
    ("form-action", ["'self'"], []),
]
CONTENT_SECURITY_POLICY_REPORT_ONLY = "; ".join(
    " ".join([name, *keywords, *extensions.csp_sources.get(name, []), *hosts])
    for name, keywords, hosts in REPORT_ONLY_DIRECTIVES)


def plugin_response(request) -> JSONResponse | None:
    for request_filter in extensions.request_filters:
        if (response := request_filter(request)) is not None:
            return response
    return None


@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = cross_site_refusal(request) or plugin_response(request) or await call_next(request)
    if request.url.path.startswith("/assets/") and response.status_code in (200, 304):
        # Vite names every build file after its content hash, so a URL never changes content.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["Content-Security-Policy-Report-Only"] = CONTENT_SECURITY_POLICY_REPORT_ONLY
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


# Plan-blob engine routes (no DB required) exist only for tests and local tools.
if stateless_api_enabled():
    app.include_router(monte_carlo_stateless_router, prefix="/api")
    app.include_router(simulation_stateless_router, prefix="/api")

# DB-dependent routers
# Plan-scoped data routes: reads need an openable plan and writes an editable
# one (app.access). Analysis routes only need an openable plan.
plan_write = [Depends(plan_guard)]
plan_read = [Depends(plan_read_guard)]
app.include_router(tax_strategies_router, prefix="/api", dependencies=plan_read)
app.include_router(tax_suggestions_router, prefix="/api", dependencies=plan_read)
app.include_router(withdrawal_strategies_router, prefix="/api", dependencies=plan_read)
app.include_router(spending_models_router, prefix="/api", dependencies=plan_read)
app.include_router(spending_models_apply_router, prefix="/api", dependencies=plan_write)
app.include_router(plan_checks_router, prefix="/api", dependencies=plan_read)
app.include_router(ss_claiming_router, prefix="/api", dependencies=plan_read)
app.include_router(wellness_router, prefix="/api", dependencies=plan_read)
app.include_router(auth_router, prefix="/api")
app.include_router(extensions.account_deletion_router or account_deletion_router, prefix="/api")
app.include_router(readiness_router, prefix="/api")
app.include_router(accounts_router, prefix="/api", dependencies=[Depends(account_pool_guard)])
app.include_router(plan_accounts_router, prefix="/api", dependencies=plan_write)
app.include_router(clients_router, prefix="/api")
app.include_router(ledger_router, prefix="/api")
app.include_router(ledger_suggestions_router, prefix="/api")
app.include_router(ledger_imports_router, prefix="/api")
app.include_router(ledger_feeds_router, prefix="/api", dependencies=plan_write)
app.include_router(ledger_connections_router, prefix="/api")
app.include_router(assumptions_router, prefix="/api", dependencies=plan_write)
app.include_router(charity_router, prefix="/api", dependencies=plan_write)
app.include_router(drawdown_router, prefix="/api", dependencies=plan_write)
app.include_router(expenses_router, prefix="/api", dependencies=plan_write)
app.include_router(incomes_router, prefix="/api", dependencies=plan_write)
app.include_router(liabilities_router, prefix="/api", dependencies=plan_write)
app.include_router(milestones_router, prefix="/api", dependencies=plan_write)
app.include_router(monte_carlo_router, prefix="/api", dependencies=plan_read)
app.include_router(plans_router, prefix="/api")
app.include_router(plan_intake_router, prefix="/api", dependencies=plan_write)
app.include_router(priorities_router, prefix="/api", dependencies=plan_write)
app.include_router(progress_points_router, prefix="/api")
app.include_router(real_assets_router, prefix="/api", dependencies=plan_write)
app.include_router(scenarios_router, prefix="/api", dependencies=plan_write)
app.include_router(simulation_router, prefix="/api", dependencies=plan_read)
app.include_router(tax_jurisdictions_router, prefix="/api")
app.include_router(local_tax_jurisdictions_router, prefix="/api")
app.include_router(tax_regimes_router, prefix="/api")
for plugin_router, options in extensions.api_routers:
    app.include_router(plugin_router, prefix="/api", **options)


@app.get("/api/health")
async def health_check() -> dict:
    return {"status": "ok"}


# Serve Vite build output (only if static dir exists — graceful in dev mode)
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
# Before the SPA catch-all below, which would otherwise answer these GET paths.
for page_router in extensions.page_routers:
    app.include_router(page_router(static_dir))
app.include_router(help_router(static_dir))
if os.path.isdir(static_dir):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(static_dir, "assets")),
        name="static-assets",
    )

    KNOWN_PAGES = {"", "terminal", "plaid/oauth"}

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        # Never serve index.html for /api/* routes — let them 404 properly
        if full_path == "api" or full_path.startswith("api/"):
            raise api_error(404, "NOT_FOUND", "Not found")
        # Serve root-level static files (favicon.ico, vite.svg, etc.) if they exist
        candidate = os.path.realpath(os.path.join(static_dir, full_path))
        if full_path and candidate.startswith(os.path.realpath(static_dir) + os.sep) and os.path.isfile(candidate):
            return FileResponse(candidate)
        page = full_path.rstrip("/")
        status = 200 if page in KNOWN_PAGES or page in extensions.spa_pages else 404
        return FileResponse(os.path.join(static_dir, "index.html"), status_code=status)

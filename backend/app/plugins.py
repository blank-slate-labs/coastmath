"""Optional extensions loaded when the app starts.

The open-source build runs without any. A deployment adds its own package and
names it in ``COASTMATH_PLUGINS`` (comma-separated module names). Unset, the
``business`` package beside this one loads when it exists (the hosted
deployment relies on that); a module of that name found anywhere else on the
import path is never loaded. An empty value loads none. Each module's
``register(extensions)`` adds routes, hooks and policies to the shared
``extensions`` below before ``app.main`` builds the app.
"""
import importlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_PLUGIN = "business"
# Where the default plug-in is looked for: the directory that holds ``app``.
PACKAGE_DIR = Path(__file__).resolve().parents[1]


@dataclass
class Extensions:
    #: ``(router, include_router keyword arguments)`` served under ``/api``.
    api_routers: list[tuple[Any, dict]] = field(default_factory=list)
    #: Routers outside ``/api``, matched before the single-page app fallback.
    page_routers: list[Any] = field(default_factory=list)
    #: More paths the single-page app answers with 200 instead of 404.
    spa_pages: set[str] = field(default_factory=set)
    #: Signed server-to-server POST paths exempt from the browser origin check.
    callback_paths: set[str] = field(default_factory=set)
    #: ``(path prefix, bytes)`` request body limits above the default (app.middleware.body_limit).
    body_limits: list[tuple[str, int]] = field(default_factory=list)
    #: More report-only Content-Security-Policy sources, by directive.
    csp_sources: dict[str, list[str]] = field(default_factory=dict)
    #: ``(request) -> str | None``, the client address an edge proxy reports; None uses the connection's.
    client_address: Callable | None = None
    #: ``(request) -> response | None``, run before routing; a response answers the request.
    request_filters: list[Callable] = field(default_factory=list)
    #: ``(ASGI middleware class, keyword arguments)``, wrapped directly around the routes.
    asgi_middleware: list[tuple[type, dict]] = field(default_factory=list)
    #: ``(request, user, token_payload, db)``, run after the session cookie is verified; raise to refuse.
    session_checks: list[Callable] = field(default_factory=list)
    #: Issuer and audience of session tokens; changing it signs every session out.
    session_token_issuer: str = "coastmath"
    #: ``(user)``, run when a session signs out.
    logout_hooks: list[Callable] = field(default_factory=list)
    #: Replaces the router that serves ``DELETE /api/auth/me``.
    account_deletion_router: Any = None
    #: ``(db) -> dict``, run by ``GET /api/ready``; raise to refuse, return fields to add.
    readiness_checks: list[Callable] = field(default_factory=list)
    #: ``(connection)``, run at startup with an open database connection.
    startup_checks: list[Callable] = field(default_factory=list)
    #: ``(session_factory) -> asyncio.Task | None``, started with the app and cancelled at shutdown.
    background_tasks: list[Callable] = field(default_factory=list)
    #: The plan access policy (``app.access.AccessPolicy``); None grants full access.
    access_policy: Any = None
    #: ``(db, user_id, feature)``, records one use of a feature; None records nothing.
    usage_recorder: Callable | None = None
    loaded: list[str] = field(default_factory=list)


extensions = Extensions()


def plugin_names() -> list[str]:
    configured = os.environ.get("COASTMATH_PLUGINS")
    if configured is None:
        return [DEFAULT_PLUGIN] if (PACKAGE_DIR / DEFAULT_PLUGIN / "__init__.py").is_file() else []
    return [name.strip() for name in configured.split(",") if name.strip()]


def load_plugins() -> Extensions:
    """Register each configured plug-in once."""
    for name in plugin_names():
        if name not in extensions.loaded:
            importlib.import_module(name).register(extensions)
            extensions.loaded.append(name)
    return extensions

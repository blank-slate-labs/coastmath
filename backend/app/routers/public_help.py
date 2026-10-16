"""Serve the prerendered help center. No sessions, plan data, or engine calls."""
import html
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from app.errors import api_error

HELP_MANIFEST = "help_manifest.json"
HELP_REDIRECTS = "help_redirects.json"


def read_help_manifest(root: Path) -> dict[str, str] | None:
    """Route -> file map written by the frontend build, or None before the help center is built."""
    file = root / HELP_MANIFEST
    if not file.is_file():
        return None
    try:
        files = json.loads(file.read_text())
        if not isinstance(files, dict) or "/help" not in files or any(
            not isinstance(route, str) or not isinstance(name, str) or not route.startswith("/help")
            for route, name in files.items()
        ):
            raise ValueError("Invalid help manifest")
    except (OSError, ValueError) as error:
        raise api_error(503, "HTTP_503", "Help build is unavailable.") from error
    return files


def read_help_redirects(root: Path) -> dict[str, str]:
    """Renamed article route -> current route, written by the same build; empty when none exist."""
    file = root / HELP_REDIRECTS
    if not file.is_file():
        return {}
    try:
        moved = json.loads(file.read_text())
        if not isinstance(moved, dict) or any(
            not isinstance(old, str) or not isinstance(new, str)
            or not old.startswith("/help/") or not new.startswith("/help/")
            for old, new in moved.items()
        ):
            raise ValueError("Invalid help redirects")
    except (OSError, ValueError) as error:
        raise api_error(503, "HTTP_503", "Help build is unavailable.") from error
    return moved


def _error_page(status_code: int, message: str) -> HTMLResponse:
    """A plain HTML error: help opens in browsers and the app's in-app browser, never as a JSON envelope."""
    text = html.escape(message)
    return HTMLResponse(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{text}</title></head>"
        "<body style=\"font-family:-apple-system,system-ui,sans-serif;margin:48px 24px;color:#1d1d1f\">"
        f"<h1 style=\"font-size:22px;font-weight:600\">{text}</h1>"
        "<p><a href=\"\">Try again</a></p></body></html>",
        status_code=status_code,
    )


def help_router(static_dir: str) -> APIRouter:
    router = APIRouter(include_in_schema=False)
    root = Path(static_dir).resolve()

    async def serve(path: str, request: Request) -> Response:
        try:
            files = read_help_manifest(root)
        except HTTPException as error:
            return _error_page(error.status_code, "Help is unavailable right now.")
        if files is None:
            return _error_page(503, "Help is unavailable right now.")
        normalized = path.rstrip("/")
        if normalized not in files:
            try:
                moved = read_help_redirects(root).get(normalized)
            except HTTPException as error:
                return _error_page(error.status_code, "Help is unavailable right now.")
            if moved not in files:
                return _error_page(404, "Help article not found.")
            # A renamed article: one permanent hop to its current path; the browser keeps the #anchor.
            return RedirectResponse(request.url.replace(path=moved), status_code=308)
        if normalized != path:
            return RedirectResponse(request.url.replace(path=normalized), status_code=308)
        file = (root / files[normalized]).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            return _error_page(503, "Help is unavailable right now.")
        return FileResponse(file, media_type="text/html")

    @router.get("/help")
    async def index(request: Request) -> Response:
        return await serve("/help", request)

    @router.get("/help/{slug:path}")
    async def article(slug: str, request: Request) -> Response:
        return await serve(f"/help/{slug}", request)

    return router

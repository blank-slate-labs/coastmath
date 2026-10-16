"""Real HTTP serving of the prerendered help center over an isolated static tree."""
import json

import httpx
import pytest
from fastapi import FastAPI

from app.routers.public_help import help_router

pytestmark = pytest.mark.anyio


@pytest.fixture
def help_app(tmp_path, monkeypatch):
    monkeypatch.delenv("PUBLIC_SITE_URL", raising=False)
    static = tmp_path / "static"
    (static / "help").mkdir(parents=True)
    paths = {"/help": "help/index.html"}
    for slug in ["required-minimum-distributions", "roth-conversions"]:
        paths[f"/help/{slug}"] = f"help/{slug.replace('-', '_')}.html"
    for route, file in paths.items():
        (static / file).write_text(f"<html><h1>{route}</h1></html>")
    (static / "help_manifest.json").write_text(json.dumps(paths))
    app = FastAPI()
    app.include_router(help_router(str(static)))
    return app, static, paths


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test")


async def test_help_pages_are_public_html_and_redirect_trailing_slashes(help_app):
    app, _, paths = help_app
    async with client(app) as http:
        for path in paths:
            response = await http.get(path)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/html")
            assert f"<h1>{path}</h1>" in response.text
            assert "set-cookie" not in response.headers
            redirected = await http.get(path + "/?from=planner")
            assert redirected.status_code == 308
            assert redirected.headers["location"] == f"https://example.test{path}?from=planner"


async def test_unknown_articles_and_traversal_do_not_serve_other_files(help_app):
    app, static, _ = help_app
    (static / "secret.txt").write_text("not help")
    async with client(app) as http:
        for path in ["/help/missing", "/help/roth_conversions.html", "/help/roth-conversions/extra", "/help/%2e%2e/secret.txt"]:
            response = await http.get(path)
            assert response.status_code == 404
            assert response.headers["content-type"].startswith("text/html")
            assert "not help" not in response.text


async def test_missing_build_fails_explicitly(help_app):
    app, static, _ = help_app
    (static / "help/roth_conversions.html").unlink()
    async with client(app) as http:
        assert (await http.get("/help/roth-conversions")).status_code == 503
        (static / "help_manifest.json").unlink()
        response = await http.get("/help")
        assert response.status_code == 503
        # Help opens in browsers and the iOS in-app browser: an HTML page, never the JSON envelope.
        assert response.headers["content-type"].startswith("text/html")
        assert "Help is unavailable right now." in response.text
        assert '"error"' not in response.text


async def test_manifest_cannot_point_outside_help_or_the_static_directory(help_app):
    app, static, _ = help_app
    (static / "help_manifest.json").write_text(json.dumps({"/help": "../outside.html"}))
    (static.parent / "outside.html").write_text("outside")
    async with client(app) as http:
        assert (await http.get("/help")).status_code == 503
    (static / "help_manifest.json").write_text(json.dumps({"/help": "help/index.html", "/calculators": "calculators/index.html"}))
    async with client(app) as http:
        assert (await http.get("/help")).status_code == 503


async def test_renamed_articles_redirect_once_to_their_current_path(help_app):
    app, static, _ = help_app
    (static / "help_redirects.json").write_text(json.dumps({
        "/help/roth-conversion-ladder": "/help/roth-conversions",
        "/help/retired-elsewhere": "/help/not-built",
    }))
    async with client(app) as http:
        for old in ["/help/roth-conversion-ladder?from=app", "/help/roth-conversion-ladder/?from=app"]:
            response = await http.get(old)
            assert response.status_code == 308
            # The browser carries an old #anchor across the redirect; the article page maps it.
            assert response.headers["location"] == "https://example.test/help/roth-conversions?from=app"
        assert (await http.get("/help/retired-elsewhere")).status_code == 404
        assert (await http.get("/help/missing")).status_code == 404
        # Current articles never consult the redirects, so a broken file only fails unknown paths.
        (static / "help_redirects.json").write_text("[]")
        assert (await http.get("/help/roth-conversions")).status_code == 200
        broken = await http.get("/help/roth-conversion-ladder")
        assert broken.status_code == 503
        assert "Help is unavailable right now." in broken.text
        (static / "help_redirects.json").unlink()
        assert (await http.get("/help/roth-conversion-ladder")).status_code == 404

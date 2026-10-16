"""Every response carries the browser security headers, whatever served it."""
import httpx
import pytest

from app import main
from tests.static_app_support import APP_SHELL, isolated_spa

pytestmark = pytest.mark.anyio


def report_only_directives(policy: str) -> dict[str, list[str]]:
    directives = {}
    for directive in policy.split("; "):
        name, *sources = directive.split(" ")
        directives[name] = sources
    return directives


def assert_security_headers(response: httpx.Response) -> None:
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["content-security-policy"] == main.CONTENT_SECURITY_POLICY
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    report_only = response.headers["content-security-policy-report-only"]
    assert report_only == main.CONTENT_SECURITY_POLICY_REPORT_ONLY
    # Plug-ins may add sources after each directive's keywords; the planner's own stay put.
    directives = report_only_directives(report_only)
    assert directives["default-src"] == ["'self'"]
    assert directives["script-src"][0] == "'self'" and directives["script-src"][-1] == "https://cdn.plaid.com"
    assert directives["frame-src"][-1] == "https://cdn.plaid.com"
    assert directives["object-src"] == ["'none'"] and directives["base-uri"] == ["'none'"]
    if not main.extensions.csp_sources:
        assert report_only.startswith("default-src 'self'; script-src 'self' https://cdn.plaid.com;")


async def test_api_responses_and_api_errors_carry_the_headers():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        health = await client.get("/api/health")
        assert health.status_code == 200
        assert_security_headers(health)
        missing = await client.get("/api/not-a-route")
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"
        assert_security_headers(missing)


async def test_app_shell_carries_the_headers(monkeypatch, tmp_path):
    load, _ = isolated_spa(monkeypatch, tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=load()), base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200 and response.text == APP_SHELL
        assert_security_headers(response)


async def test_strict_transport_security_is_sent_only_over_https():
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert "strict-transport-security" not in (await client.get("/api/health")).headers
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get("/api/health")
        assert response.headers["strict-transport-security"] == "max-age=31536000"
        assert_security_headers(response)


async def test_cross_site_refusal_keeps_the_headers():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post("/api/plans", json={}, headers={"Origin": "https://attacker.test"})
    assert response.status_code == 403
    assert response.json() == {"error": {"code": "ORIGIN_INVALID", "message": "Changes must come from CoastMath.",
                                         "details": []}}
    assert_security_headers(response)

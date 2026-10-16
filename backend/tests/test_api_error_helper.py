"""The shared API error constructor renders the envelope a hand-built detail did."""

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import db, errors
from app.ledger import balances, feeds
from app.ledger.file_imports import FileImportError
from app.middleware import body_limit
from app.middleware.error_handler import http_exception_handler
from app.routers import (
    accounts,
    helpers,
    ledger,
    ledger_imports,
    public_help,
    simulation,
    simulation_stateless,
)
from coastmath.engine.household_lifecycle import UnsupportedLifecycleInput
from tests.static_app_support import isolated_spa


async def _render(exc: HTTPException):
    request = Request({"type": "http", "method": "POST", "path": "/api/x", "headers": []})
    return await http_exception_handler(request, exc)


def _inline(status: int, code: str, message: str, details: list, headers: dict | None = None) -> HTTPException:
    """The hand-written form the routers raised before the shared constructor."""
    return HTTPException(status_code=status, detail={"error": {"code": code, "message": message, "details": details}},
                         headers=headers)


@pytest.mark.anyio
@pytest.mark.parametrize(("built", "status", "body", "headers"), [
    (errors.api_error(422, "VALIDATION_ERROR", "Bad start", [{"field": "start_year", "reason": "too early"}]),
     422, b'{"error":{"code":"VALIDATION_ERROR","message":"Bad start","details":[{"field":"start_year","reason":"too early"}]}}',
     None),
    (errors.api_error(404, "NOT_FOUND", "Account not found."),
     404, b'{"error":{"code":"NOT_FOUND","message":"Account not found.","details":[]}}', None),
    (errors.api_error(409, "SPENDING_FEED_ACTIVE", "Spending is connected."),
     409, b'{"error":{"code":"SPENDING_FEED_ACTIVE","message":"Spending is connected.","details":[]}}', None),
    (errors.api_error(429, "RATE_LIMIT_EXCEEDED", "Too many requests.", headers={"Retry-After": "30"}),
     429, b'{"error":{"code":"RATE_LIMIT_EXCEEDED","message":"Too many requests.","details":[]}}',
     {"Retry-After": "30"}),
])
async def test_constructor_matches_hand_built_envelope(built, status, body, headers):
    payload = built.detail["error"]
    inline = _inline(status, payload["code"], payload["message"], payload["details"], headers)
    assert built.status_code == status
    assert built.detail == inline.detail
    assert built.headers == inline.headers

    rendered, expected = await _render(built), await _render(inline)
    assert rendered.status_code == expected.status_code == status
    assert rendered.body == expected.body == body
    assert rendered.headers.items() == expected.headers.items()
    if headers:
        assert rendered.headers["retry-after"] == "30"


def test_validation_error_names_one_field():
    assert errors.validation_error("Unknown objective", "objective", "must be one of a, b").detail == {"error": {
        "code": "VALIDATION_ERROR", "message": "Unknown objective",
        "details": [{"field": "objective", "reason": "must be one of a, b"}],
    }}
    # Without a reason the message is repeated, as the simulation routes report it.
    assert errors.validation_error("Restore it first.", "kind").detail["error"]["details"] == [
        {"field": "kind", "reason": "Restore it first."}]


def test_lifecycle_input_error_reports_household_lifecycle_field():
    exc = errors.lifecycle_input_error(UnsupportedLifecycleInput("Successor treatment is not modeled"))
    assert exc.status_code == 422
    assert exc.detail["error"]["details"] == [
        {"field": "estate_settings.household_lifecycle", "reason": "Successor treatment is not modeled"}]


def test_details_are_copied_from_the_caller():
    details = [{"field": "a", "reason": "b"}]
    exc = errors.api_error(422, "VALIDATION_ERROR", "Bad", details)
    details.append({"field": "c", "reason": "d"})
    assert exc.detail["error"]["details"] == [{"field": "a", "reason": "b"}]


def test_compatibility_names_point_at_the_shared_helpers():
    assert accounts._insert_into_drawdown_orders is helpers.insert_into_drawdown_orders
    # The simulation routers' former aliases are gone; callers import the shared helpers.
    assert not hasattr(simulation, "_load_plan_data")
    assert not hasattr(simulation, "_simulation_validation_error")
    assert not hasattr(simulation_stateless, "_lifecycle_input_error")


def _exception(make) -> HTTPException:
    """The exception a factory raises, or the one it returns."""
    try:
        result = make()
    except HTTPException as raised:
        return raised
    return result


@pytest.mark.anyio
@pytest.mark.parametrize(("make", "status", "code", "message", "details"), [
    (lambda: ledger.fail("Rule changed."), 409, "CONFLICT", "Rule changed.", []),
    (lambda: ledger.fail("Account no longer exists.", 401, "AUTH_REQUIRED"),
     401, "AUTH_REQUIRED", "Account no longer exists.", []),
    (lambda: feeds._fail("Choose a basis.", 422, "VALIDATION_ERROR"), 422, "VALIDATION_ERROR", "Choose a basis.", []),
    (lambda: balances.fail("Link changed."), 409, "CONFLICT", "Link changed.", []),
    (lambda: balances.fail("Account not found.", 404, "NOT_FOUND"), 404, "NOT_FOUND", "Account not found.", []),
    (lambda: ledger_imports.refuse(FileImportError("FILE_TOO_LARGE", "File is too large.", 413,
                                                   [{"field": "file", "reason": "over the limit"}])),
     413, "FILE_TOO_LARGE", "File is too large.", [{"field": "file", "reason": "over the limit"}]),
], ids=["ledger_fail", "ledger_fail_status", "feeds_fail", "balances_fail", "balances_fail_status", "imports_refuse"])
async def test_folded_ledger_factories_render_their_former_inline_envelope(make, status, code, message, details):
    built = _exception(make)
    inline = _inline(status, code, message, details)
    assert (built.status_code, built.detail, built.headers) == (inline.status_code, inline.detail, inline.headers)
    rendered, expected = await _render(built), await _render(inline)
    assert rendered.status_code == expected.status_code == status
    assert rendered.body == expected.body


def _no_database(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "SessionLocal", None)
    return next(db.get_db())


def _broken_help_manifest(monkeypatch, tmp_path):
    (tmp_path / public_help.HELP_MANIFEST).write_text("[]")
    return public_help.read_help_manifest(tmp_path)


@pytest.mark.anyio
@pytest.mark.parametrize(("make", "former", "body"), [
    (_no_database, HTTPException(status_code=503, detail="Database not configured."),
     b'{"error":{"code":"HTTP_503","message":"Database not configured.","details":[]}}'),
    (_broken_help_manifest, HTTPException(status_code=503, detail="Help build is unavailable."),
     b'{"error":{"code":"HTTP_503","message":"Help build is unavailable.","details":[]}}'),
    (lambda monkeypatch, tmp_path: body_limit.too_large(2 * body_limit.MIB),
     HTTPException(status_code=413, detail={"error": {
         "code": "REQUEST_TOO_LARGE", "message": "This request is larger than 2 MB.", "details": []}}),
     b'{"error":{"code":"REQUEST_TOO_LARGE","message":"This request is larger than 2 MB.","details":[]}}'),
], ids=["database_not_configured", "help_build_unavailable", "request_too_large"])
async def test_former_string_detail_sites_render_the_same_body(monkeypatch, tmp_path, make, former, body):
    built = _exception(lambda: make(monkeypatch, tmp_path))
    rendered, expected = await _render(built), await _render(former)
    assert rendered.status_code == expected.status_code == former.status_code
    assert rendered.body == expected.body == body


def test_declared_oversized_body_sends_the_same_envelope():
    former = {"error": {"code": "REQUEST_TOO_LARGE", "message": "This request is larger than 15 MB.", "details": []}}
    assert JSONResponse(body_limit.too_large(15 * body_limit.MIB).detail, status_code=413).body == \
        JSONResponse(former, status_code=413).body


@pytest.mark.anyio
async def test_spa_api_not_found_keeps_its_former_body(monkeypatch, tmp_path):
    load, _ = isolated_spa(monkeypatch, tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=load()), base_url="http://test") as client:
        response = await client.get("/api/unknown")
    former = await _render(HTTPException(status_code=404, detail="Not found"))
    assert response.status_code == 404
    assert response.content == former.body == b'{"error":{"code":"NOT_FOUND","message":"Not found","details":[]}}'

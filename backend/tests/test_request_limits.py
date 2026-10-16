"""Request bodies and collections are bounded before parsing or engine work."""
from uuid import uuid4

import pytest
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from app.middleware.body_limit import DEFAULT_LIMIT, MIB, BodySizeLimitMiddleware
from app.models.user import User
from app.routers import helpers, progress_points
from app.schemas.assumption_curve import AssumptionCurveCreate, AssumptionCurveUpdate
from app.schemas.cash_flow_priority import CashFlowPriorityBulkUpdate
from app.schemas.drawdown_order import DrawdownOrderBulkUpdate
from app.schemas.plan import PlanCreate, PlanUpdate, TaxSettings
from app.schemas.progress_point import ProgressPointCreate
from app.schemas.tax_jurisdiction import TaxJurisdictionCreate
from coastmath.schemas.roth_settings import RothSettings
from coastmath.schemas.year_to_date import YearToDateTax
from tests.api_support import assert_error, contract_plan


def scope(path="/api/plans", headers=()):
    return {"type": "http", "method": "POST", "path": path, "headers": [(k.encode(), v.encode()) for k, v in headers]}


def chunks(*parts):
    messages = iter([{"type": "http.request", "body": part, "more_body": i < len(parts) - 1}
                     for i, part in enumerate(parts)])

    async def receive():
        return next(messages)
    return receive


class Downstream:
    def __init__(self):
        self.body = b""
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True
        while True:
            message = await receive()
            self.body += message.get("body", b"")
            if not message.get("more_body"):
                return


class Sent:
    def __init__(self):
        self.messages = []

    async def __call__(self, message):
        self.messages.append(message)


@pytest.mark.anyio
async def test_declared_oversized_body_is_refused_before_the_route_runs():
    downstream, sent = Downstream(), Sent()
    middleware = BodySizeLimitMiddleware(downstream, default=8)
    await middleware(scope(headers=[("content-length", "9")]), chunks(b"123456789"), sent)
    assert not downstream.called
    assert sent.messages[0]["status"] == 413
    assert b'"code":"REQUEST_TOO_LARGE"' in sent.messages[1]["body"]


@pytest.mark.anyio
@pytest.mark.parametrize("declared", [None, "4"])
async def test_streamed_bytes_are_counted_even_with_missing_or_false_length(declared):
    downstream = Downstream()
    middleware = BodySizeLimitMiddleware(downstream, default=8)
    headers = [("content-length", declared)] if declared else []
    with pytest.raises(HTTPException) as error:
        await middleware(scope(headers=headers), chunks(b"12345", b"6789"), Sent())
    assert error.value.status_code == 413
    assert error.value.detail["error"]["code"] == "REQUEST_TOO_LARGE"


@pytest.mark.anyio
async def test_bodies_within_the_path_limit_pass_through_unchanged():
    downstream = Downstream()
    middleware = BodySizeLimitMiddleware(downstream, default=8, limits=(("/api/uploads", 16),))
    await middleware(scope("/api/uploads/preview"), chunks(b"1234567890", b"12345"), Sent())
    assert downstream.body == b"123456789012345"
    assert middleware.limit_for("/api/uploadsx") == 8  # Prefixes match whole segments.


@pytest.mark.anyio
async def test_unauthenticated_oversized_session_request_creates_nothing(client, db_session):
    users = db_session.query(User).count()
    client.cookies.clear()
    padding = "x" * (DEFAULT_LIMIT + 1)
    response = await client.post("/api/auth/session", content=b'{"seed_demo": true, "pad": "' + padding.encode() + b'"}',
                                 headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert response.headers["x-content-type-options"] == "nosniff"

    async def stream():  # No Content-Length: counted chunk by chunk.
        yield b'{"pad": "'
        for _ in range(3):
            yield b"x" * MIB
        yield b'"}'

    streamed = await client.post("/api/auth/session", content=stream(), headers={"content-type": "application/json"})
    assert streamed.status_code == 413
    assert streamed.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert db_session.query(User).count() == users


OVERSIZED = [
    (PlanCreate, {"name": "P", "birth_year": 1980, "snapshot_conditions": {str(uuid4()): {} for _ in range(201)}}),
    (PlanUpdate, {"snapshot_conditions": {str(uuid4()): {} for _ in range(201)}}),
    (PlanUpdate, {"residency_periods": [{"state_code": "CA"}] * 51}),
    (TaxSettings, {"state_brackets": [(0, 0.01)] * 51}),
    (CashFlowPriorityBulkUpdate, {"expected_revision": 0, "items": [{"priority_rank": i} for i in range(201)]}),
    (DrawdownOrderBulkUpdate, {"items": [{"rank": i} for i in range(201)]}),
    (AssumptionCurveCreate, {"curve_type": "inflation", "mode": "curve", "control_points": [{"x": i, "y": 0.03} for i in range(201)]}),
    (AssumptionCurveUpdate, {"control_points": [{"x": i, "y": 0.03} for i in range(201)]}),
    (ProgressPointCreate, {"recorded_date": "2026-01-01", "assets_breakdown": {str(i): 1 for i in range(201)}}),
    (RothSettings, {"conversions": [{"year": 2000 + i % 100} for i in range(201)]}),
    (TaxJurisdictionCreate, {"level": "state", "custom_brackets": [{"min": i, "rate": 0.01} for i in range(51)]}),
    (YearToDateTax, {"tax_year": 2026, "contributions_by_account": {str(i): 1 for i in range(201)}}),
]


@pytest.mark.parametrize("model,payload", OVERSIZED, ids=[f"{model.__name__}-{i}" for i, (model, _) in enumerate(OVERSIZED)])
def test_collections_feeding_storage_or_the_engine_are_bounded(model, payload):
    with pytest.raises(ValidationError) as error:
        model.model_validate(payload)
    assert any(item["type"] == "too_long" for item in error.value.errors())


def test_progress_breakdowns_take_labeled_totals_only():
    ok = ProgressPointCreate.model_validate({"recorded_date": "2026-01-01", "assets_breakdown": {"liquid_assets": 1, "property": 2.5}})
    assert ok.assets_breakdown == {"liquid_assets": 1.0, "property": 2.5}
    for bad in ({"cash": "9" * 9_000}, {"cash": {"nested": 1}}, {"cash": True}, {"cash": None}, {"k" * 65: 1}):
        with pytest.raises(ValidationError):
            ProgressPointCreate.model_validate({"recorded_date": "2026-01-01", "liabilities_breakdown": bad})


@pytest.mark.anyio
async def test_an_account_keeps_a_bounded_number_of_progress_points(client, monkeypatch):
    monkeypatch.setattr(progress_points, "MAX_POINTS", 2)
    body = {"recorded_date": "2026-01-01", "net_worth": 1}
    for _ in range(2):
        assert (await client.post("/api/progress-points", json=body)).status_code == 201
    assert_error(await client.post("/api/progress-points", json=body), 422, "VALIDATION_ERROR")
    point = (await client.get("/api/progress-points")).json()[0]
    assert (await client.delete(f"/api/progress-points/{point['id']}")).status_code == 204
    assert (await client.post("/api/progress-points", json=body)).status_code == 201


PLAN_ROWS = [
    ("expenses", {"name": "Row", "annual_amount": 100}),
    ("incomes", {"name": "Row"}),
    ("milestones", {"name": "Row", "trigger_type": "age", "trigger_value": 65}),
    ("liabilities", {"name": "Row", "principal_balance": 1_000, "interest_rate": 0.05, "monthly_payment": 100}),
    ("real-assets", {"name": "Row", "current_value": 1_000}),
    ("charities", {"name": "Row", "entity_type": "direct", "annual_amount": 100}),
]


@pytest.mark.anyio
@pytest.mark.parametrize("kind,body", PLAN_ROWS, ids=[kind for kind, _ in PLAN_ROWS])
async def test_a_plan_holds_a_bounded_number_of_rows_of_each_kind(client, monkeypatch, kind, body):
    monkeypatch.setattr(helpers, "ROW_LIMIT", 2)
    plan_id = await contract_plan(client)
    for _ in range(2):
        response = await client.post(f"/api/plans/{plan_id}/{kind}", json=body)
        assert response.status_code == 201, response.text
    assert_error(await client.post(f"/api/plans/{plan_id}/{kind}", json=body), 422, "VALIDATION_ERROR")
    # Another plan has its own allowance.
    other = await contract_plan(client)
    assert (await client.post(f"/api/plans/{other}/{kind}", json=body)).status_code == 201


@pytest.mark.anyio
async def test_an_account_pool_holds_a_bounded_number_of_accounts(client, monkeypatch):
    monkeypatch.setattr(helpers, "ROW_LIMIT", 2)
    body = {"name": "Cash", "account_type": "savings", "balance": 1}
    for _ in range(2):
        response = await client.post("/api/accounts", json=body)
        assert response.status_code == 201, response.text
    assert_error(await client.post("/api/accounts", json=body), 422, "VALIDATION_ERROR")

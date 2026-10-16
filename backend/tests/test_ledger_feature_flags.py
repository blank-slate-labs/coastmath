"""Transaction features need explicit opt-in; provider flags also need the feature flag."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.feature_flags import (
    ledger_llm_enabled,
    plaid_enabled,
    simplefin_enabled,
    transactions_enabled,
)
from app.ledger.gating import require_transactions_enabled
from app.plugins import extensions

PROVIDER_FLAGS = [
    (simplefin_enabled, "SIMPLEFIN_ENABLED"),
    (plaid_enabled, "PLAID_ENABLED"),
    (ledger_llm_enabled, "LEDGER_LLM_ENABLED"),
]


@pytest.mark.parametrize("value", [None, "", "false", "0", "yes", "typo"])
def test_transactions_flag_requires_exact_true(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("TRANSACTIONS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("TRANSACTIONS_ENABLED", value)
    assert not transactions_enabled()


def test_transactions_flag_accepts_true_case_insensitively(monkeypatch):
    monkeypatch.setenv("TRANSACTIONS_ENABLED", " True ")
    assert transactions_enabled()


@pytest.mark.parametrize("flag,variable", PROVIDER_FLAGS)
def test_provider_flags_need_the_transactions_flag(monkeypatch, flag, variable):
    monkeypatch.setenv(variable, "true")
    monkeypatch.delenv("TRANSACTIONS_ENABLED", raising=False)
    assert not flag()
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "true")
    assert flag()
    monkeypatch.setenv(variable, "false")
    assert not flag()


def _request(method: str) -> Request:
    return Request({"type": "http", "method": method, "path": "/api/ledger/rules", "headers": []})


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
def test_gate_refuses_changes_while_disabled(monkeypatch, method):
    monkeypatch.delenv("TRANSACTIONS_ENABLED", raising=False)
    with pytest.raises(HTTPException) as refused:
        require_transactions_enabled(_request(method))
    assert refused.value.status_code == 503
    assert refused.value.detail["error"]["code"] == "FEATURE_DISABLED"


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "DELETE"])
def test_gate_keeps_reads_and_deletions_available(monkeypatch, method):
    monkeypatch.delenv("TRANSACTIONS_ENABLED", raising=False)
    assert require_transactions_enabled(_request(method)) is None


def test_gate_allows_changes_when_enabled(monkeypatch):
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "true")
    assert require_transactions_enabled(_request("POST")) is None


@pytest.mark.anyio
@pytest.mark.parametrize(("value", "advertised"), [(None, False), ("false", False), ("true", True), (" TRUE ", True)])
async def test_transactions_capability_follows_the_flag(client, monkeypatch, value, advertised):
    if value is None:
        monkeypatch.delenv("TRANSACTIONS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("TRANSACTIONS_ENABLED", value)
    me = await client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    capabilities = me.json()["capabilities"]
    # Additive: the existing capabilities keep their order; older clients ignore the new one.
    assert capabilities[:4] == ["personal_onboarding", "profile_edit", "client_workspaces", "personal_plans"]
    assert ("transactions" in capabilities) is advertised and capabilities.count("transactions") <= 1


@pytest.mark.anyio
async def test_transactions_capability_on_a_server_without_a_plug_in(client, monkeypatch):
    monkeypatch.setattr(extensions, "access_policy", None)
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "true")
    created = await client.post("/api/auth/session", json={})
    assert created.status_code in (200, 201), created.text
    assert "transactions" in created.json()["capabilities"]

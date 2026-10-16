"""OpenAI-compatible suggestion client: settings, payload, validation and failures."""
import json
from decimal import Decimal

import httpx
import pytest

from app.ledger import llm
from app.ledger.llm import (
    LedgerLlmClient,
    LlmError,
    LlmSettings,
    SuggestionInput,
    parse_answer,
)

SETTINGS = LlmSettings("https://llm.example.test/v1", "synthetic-model", "synthetic-key", 5.0)
ITEMS = [
    SuggestionInput("row-a", "SYNTHETIC GROCER   #12", "Synthetic Grocer", Decimal("80.49"), None),
    SuggestionInput("row-b", "PAYROLL DEPOSIT", None, Decimal("-3000.50"), "Deposit"),
]


def completion(content, status=200):
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})


def client_with(handler):
    return LedgerLlmClient(SETTINGS, transport=httpx.MockTransport(handler))


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "true")
    monkeypatch.setenv("LEDGER_LLM_ENABLED", "true")
    monkeypatch.setenv("LEDGER_LLM_BASE_URL", "http://localhost:11434/v1/")
    monkeypatch.setenv("LEDGER_LLM_MODEL", "synthetic-model")
    monkeypatch.delenv("LEDGER_LLM_API_KEY", raising=False)
    monkeypatch.delenv("LEDGER_LLM_TIMEOUT_SECONDS", raising=False)


def test_settings_require_the_flags_a_base_url_and_a_model(configured, monkeypatch):
    settings = LlmSettings.load()
    assert settings == LlmSettings("http://localhost:11434/v1", "synthetic-model", None, 30.0)
    assert llm.llm_offered()
    monkeypatch.setenv("LEDGER_LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("LEDGER_LLM_TIMEOUT_SECONDS", "500")
    assert LlmSettings.load().api_key == "synthetic-key" and LlmSettings.load().timeout == 120.0
    monkeypatch.setenv("LEDGER_LLM_TIMEOUT_SECONDS", "soon")
    assert LlmSettings.load().timeout == 30.0
    monkeypatch.setenv("LEDGER_LLM_BASE_URL", "ftp://llm.example.test")
    assert LlmSettings.load() is None
    monkeypatch.setenv("LEDGER_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("LEDGER_LLM_MODEL", " ")
    assert LlmSettings.load() is None
    monkeypatch.setenv("LEDGER_LLM_MODEL", "synthetic-model")
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "false")
    assert LlmSettings.load() is None and not llm.llm_offered()


def test_success_sends_only_permitted_fields_and_maps_answers_back():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return completion(json.dumps({"suggestions": [
            {"ref": "1", "category": "groceries"}, {"ref": "2", "category": " income_wages "},
            {"ref": "1", "category": "dining"}]}))

    assert client_with(handler).suggest(ITEMS) == {"row-a": "groceries", "row-b": "income_wages"}
    assert seen["url"] == "https://llm.example.test/v1/chat/completions"
    assert seen["auth"] == "Bearer synthetic-key"
    body = seen["body"]
    assert body["model"] == "synthetic-model" and body["response_format"] == {"type": "json_object"}
    assert "uncategorized" not in body["messages"][0]["content"].split("list: ")[1].split(". ")[0]
    sent = json.loads(body["messages"][1]["content"])["transactions"]
    assert sent == [
        {"ref": "1", "description": "SYNTHETIC GROCER #12", "merchant": "Synthetic Grocer", "direction": "outflow",
         "amount": 80, "provider_category": None},
        {"ref": "2", "description": "PAYROLL DEPOSIT", "merchant": None, "direction": "inflow", "amount": 3001,
         "provider_category": "Deposit"},
    ]
    assert "row-a" not in body["messages"][1]["content"]


def test_no_key_sends_no_authorization_and_empty_input_sends_nothing():
    calls = []

    def handler(request):
        calls.append(request.headers.get("authorization"))
        return completion('```json\n{"suggestions": [{"ref": "1", "category": "groceries"}]}\n```')

    keyless = LedgerLlmClient(LlmSettings("http://localhost:8080/v1", "local"), transport=httpx.MockTransport(handler))
    assert keyless.suggest([]) == {}
    assert keyless.suggest(ITEMS[:1]) == {"row-a": "groceries"}
    assert calls == [None]


def test_unknown_categories_refs_and_entries_are_discarded():
    content = json.dumps({"suggestions": [
        {"ref": "1", "category": "not_a_category"}, {"ref": "2", "category": "uncategorized"},
        {"ref": "9", "category": "groceries"}, "groceries", {"ref": "2", "category": 7}]})
    assert client_with(lambda request: completion(content)).suggest(ITEMS) == {}


@pytest.mark.parametrize("content", ["not json", "[]", '{"suggestions": {}}', None])
def test_malformed_output_raises(content):
    with pytest.raises(LlmError) as error:
        client_with(lambda request: completion(content)).suggest(ITEMS)
    assert error.value.code == "malformed" and "unreadable" in error.value.message


def test_malformed_envelope_raises():
    for response in (httpx.Response(200, text="oops"), httpx.Response(200, json={"choices": []})):
        with pytest.raises(LlmError, match="malformed"):
            client_with(lambda request, r=response: r).suggest(ITEMS)


@pytest.mark.parametrize("status,code", [(401, "auth"), (403, "auth"), (429, "rate_limited"), (500, "unavailable"),
                                         (302, "unavailable")])
def test_http_errors_map_to_safe_codes(status, code):
    with pytest.raises(LlmError) as error:
        client_with(lambda request: httpx.Response(status, text="secret detail")).suggest(ITEMS)
    assert error.value.code == code and "secret" not in error.value.message


def test_timeouts_and_transport_errors():
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    def broken(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LlmError, match="timeout"):
        client_with(slow).suggest(ITEMS)
    with pytest.raises(LlmError, match="unavailable"):
        client_with(broken).suggest(ITEMS)


def test_parse_answer_rejects_non_string_content():
    with pytest.raises(LlmError):
        parse_answer({"suggestions": []}, {})

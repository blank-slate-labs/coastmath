"""Plaid client: settings, calls, sync pagination, errors, normalization and webhook JWTs.

Payloads are synthetic and shaped like https://plaid.com/docs/api/. No network access.
"""
import base64
import hashlib
import json
import time
from datetime import date
from decimal import Decimal

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.ledger.providers import plaid_client as pc
from app.ledger.providers.errors import ProviderError
from app.ledger.providers.plaid_client import (
    PlaidClient,
    PlaidError,
    PlaidSettings,
    map_account_type,
)

SETTINGS = PlaidSettings("demo-client-id", "demo-secret-value", "sandbox", ("US", "CA"))
ACCESS_TOKEN = "access-sandbox-demo-0001"


@pytest.fixture(autouse=True)
def _clear_cache():
    pc.clear_webhook_key_cache()
    yield
    pc.clear_webhook_key_cache()


def client(handler, settings: PlaidSettings = SETTINGS) -> PlaidClient:
    return PlaidClient(settings, httpx.MockTransport(handler))


def ok(payload):
    return httpx.Response(200, json=payload)


def plaid_error(status, error_type, error_code):
    return httpx.Response(status, json={"error_type": error_type, "error_code": error_code,
                                        "error_message": "secret detail demo-secret-value", "request_id": "req-1"})


def txn(transaction_id, **overrides):
    row = {"transaction_id": transaction_id, "account_id": "acc-checking", "amount": 12.34, "iso_currency_code": "USD",
           "unofficial_currency_code": None, "date": "2026-09-03", "authorized_date": "2026-09-01", "pending": False,
           "pending_transaction_id": None, "name": "CORNER CAFE 123", "merchant_name": "Corner Cafe",
           "personal_finance_category": {"primary": "FOOD_AND_DRINK", "detailed": "FOOD_AND_DRINK_COFFEE",
                                         "confidence_level": "HIGH"}}
    row.update(overrides)
    return row


# --- Settings -----------------------------------------------------------------------------


def test_settings_load(monkeypatch):
    for name in ("PLAID_CLIENT_ID", "PLAID_SECRET", "PLAID_ENV", "PLAID_COUNTRY_CODES", "PLAID_REDIRECT_URI", "PLAID_WEBHOOK_URL"):
        monkeypatch.delenv(name, raising=False)
    settings = PlaidSettings.load()
    assert settings.environment == "sandbox" and settings.country_codes == ("US",)
    assert not settings.configured and settings.redirect_uri is None and settings.webhook_url is None
    assert settings.api_origin == "https://sandbox.plaid.com"
    monkeypatch.setenv("PLAID_CLIENT_ID", "id")
    monkeypatch.setenv("PLAID_SECRET", "shh")
    monkeypatch.setenv("PLAID_ENV", "production")
    monkeypatch.setenv("PLAID_COUNTRY_CODES", "us, ca")
    monkeypatch.setenv("PLAID_REDIRECT_URI", "https://app.example/oauth")
    monkeypatch.setenv("PLAID_WEBHOOK_URL", "https://app.example/api/ledger/webhooks/plaid")
    settings = PlaidSettings.load()
    assert settings.configured and settings.country_codes == ("US", "CA")
    assert settings.api_origin == "https://production.plaid.com" and "shh" not in repr(settings)
    assert settings.redirect_uri == "https://app.example/oauth"
    monkeypatch.setenv("PLAID_ENV", "development")
    with pytest.raises(ValueError, match="PLAID_ENV"):
        PlaidSettings.load()
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    monkeypatch.setenv("PLAID_COUNTRY_CODES", "USA")
    with pytest.raises(ValueError, match="PLAID_COUNTRY_CODES"):
        PlaidSettings.load()


def test_unconfigured_client_refuses_without_a_request():
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("request sent")

    with pytest.raises(PlaidError) as error:
        client(handler, PlaidSettings("", "", "sandbox")).accounts(ACCESS_TOKEN)
    assert error.value.code == "INTEGRATION_UNAVAILABLE" and error.value.status == 503


# --- Calls --------------------------------------------------------------------------------


def test_link_token_for_new_item():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return ok({"link_token": "link-sandbox-demo", "expiration": "2026-10-11T16:00:00Z", "request_id": "r"})

    settings = PlaidSettings("demo-client-id", "demo-secret-value", "sandbox", ("US",), "https://app.example/oauth",
                             "https://app.example/hook")
    result = client(handler, settings).create_link_token("user-uuid-1")
    assert result.link_token == "link-sandbox-demo" and result.expiration.year == 2026
    assert "link-sandbox-demo" not in repr(result)
    request = seen[0]
    assert str(request.url) == "https://sandbox.plaid.com/link/token/create"
    assert request.headers["plaid-client-id"] == "demo-client-id" and request.headers["plaid-secret"] == "demo-secret-value"
    assert request.headers["plaid-version"] == pc.API_VERSION
    body = json.loads(request.content)
    assert body == {"client_name": "CoastMath", "language": "en", "country_codes": ["US"],
                    "user": {"client_user_id": "user-uuid-1"}, "products": ["transactions"],
                    "transactions": {"days_requested": 730}, "webhook": "https://app.example/hook",
                    "redirect_uri": "https://app.example/oauth"}
    assert "demo-secret-value" not in request.content.decode()


def test_link_token_update_mode_omits_products():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return ok({"link_token": "link-sandbox-update"})

    client(handler).create_link_token("user-uuid-1", access_token=ACCESS_TOKEN, redirect_uri="https://native.example/r")
    body = seen[0]
    assert body["access_token"] == ACCESS_TOKEN and body["redirect_uri"] == "https://native.example/r"
    assert "products" not in body and "transactions" not in body and "webhook" not in body
    assert body["country_codes"] == ["US", "CA"]
    client(handler).create_link_token("user-uuid-1")
    assert "redirect_uri" not in seen[1] and seen[1]["products"] == ["transactions"]


def test_exchange_public_token():
    def handler(request):
        assert json.loads(request.content) == {"public_token": "public-sandbox-demo"}
        return ok({"access_token": ACCESS_TOKEN, "item_id": "item-1", "request_id": "r"})

    result = client(handler).exchange_public_token("public-sandbox-demo")
    assert result.item_id == "item-1" and result.access_token == ACCESS_TOKEN
    assert ACCESS_TOKEN not in repr(result)


def test_accounts_normalization():
    payload = {
        "item": {"item_id": "item-1", "institution_id": "ins_demo", "institution_name": "Demo Bank"},
        "accounts": [
            {"account_id": "acc-checking", "name": "Plaid Checking", "mask": "0000", "type": "depository",
             "subtype": "checking", "balances": {"current": 110.5, "available": 100, "iso_currency_code": "USD",
                                                 "last_updated_datetime": "2026-10-10T12:00:00Z"}},
            {"account_id": "acc-card", "name": "", "official_name": "Demo Rewards Card", "mask": "3333",
             "type": "credit", "subtype": "credit card", "balances": {"current": 410, "iso_currency_code": "usd"}},
            {"account_id": "acc-457", "name": "Deferred Comp", "type": "investment", "subtype": "457b",
             "balances": {"current": None, "iso_currency_code": None}},
            {"account_id": "acc-odd", "name": "Mystery", "type": "payroll", "subtype": None},
        ],
    }
    result = client(lambda request: ok(payload)).accounts(ACCESS_TOKEN)
    assert result.item_id == "item-1" and result.institution_id == "ins_demo"
    checking, card, deferred, odd = result.accounts
    assert (checking.account_type, checking.subtype, checking.mask) == ("DEPOSITORY", "CHECKING", "0000")
    assert checking.balance == Decimal("110.5") and checking.currency == "USD"
    assert checking.balance_date.isoformat() == "2026-10-10T12:00:00+00:00"
    assert checking.institution_name == "Demo Bank" and checking.institution_id == "ins_demo"
    assert (card.name, card.account_type, card.subtype) == ("Demo Rewards Card", "CREDIT", "CREDIT_CARD")
    assert card.balance == Decimal("410") and card.currency == "USD" and card.balance_date is None
    assert (deferred.account_type, deferred.subtype, deferred.balance, deferred.currency) == ("INVESTMENT", None, None, None)
    assert (odd.account_type, odd.subtype) == ("OTHER", None)


@pytest.mark.parametrize(("plaid_type", "plaid_subtype", "expected"), [
    ("depository", "checking", ("DEPOSITORY", "CHECKING")),
    ("depository", "savings", ("DEPOSITORY", "SAVINGS")),
    ("depository", "cash management", ("DEPOSITORY", "CASH_MANAGEMENT")),
    ("depository", "money market", ("DEPOSITORY", "MONEY_MARKET")),
    ("depository", "cd", ("DEPOSITORY", "CD")),
    ("depository", "prepaid", ("DEPOSITORY", "PREPAID")),
    ("depository", "hsa", ("DEPOSITORY", "HSA")),
    ("depository", "paypal", ("DEPOSITORY", None)),
    ("credit", "credit card", ("CREDIT", "CREDIT_CARD")),
    ("credit", "paypal", ("CREDIT", None)),
    ("loan", "mortgage", ("LOAN", "MORTGAGE")),
    ("loan", "student", ("LOAN", "STUDENT")),
    ("loan", "auto", ("LOAN", "AUTO")),
    ("loan", "home equity", ("LOAN", "HOME_EQUITY")),
    ("loan", "line of credit", ("LOAN", "LINE_OF_CREDIT")),
    ("loan", "consumer", ("LOAN", None)),
    ("investment", "401k", ("INVESTMENT", "PLAN_401K")),
    ("investment", "roth 401k", ("INVESTMENT", "ROTH_401K")),
    ("investment", "403B", ("INVESTMENT", "PLAN_403B")),
    ("investment", "401a", ("INVESTMENT", "PLAN_401A")),
    ("investment", "ira", ("INVESTMENT", "IRA")),
    ("investment", "roth", ("INVESTMENT", "ROTH")),
    ("investment", "sep ira", ("INVESTMENT", "SEP_IRA")),
    ("investment", "simple ira", ("INVESTMENT", "SIMPLE_IRA")),
    ("investment", "brokerage", ("INVESTMENT", "BROKERAGE")),
    ("investment", "hsa", ("INVESTMENT", "HSA")),
    ("investment", "529", ("INVESTMENT", "PLAN_529")),
    ("investment", "457b", ("INVESTMENT", None)),
    ("investment", "thrift savings plan", ("INVESTMENT", None)),
    ("investment", "pension", ("INVESTMENT", None)),
    ("investment", "retirement", ("INVESTMENT", None)),
    ("investment", "non-taxable brokerage account", ("INVESTMENT", None)),
    ("brokerage", "ira", ("INVESTMENT", "IRA")),
    ("other", "other", ("OTHER", None)),
    ("", None, ("OTHER", None)),
])
def test_account_type_mapping_table(plaid_type, plaid_subtype, expected):
    assert map_account_type(plaid_type, plaid_subtype) == expected


def test_sync_paginates_and_normalizes():
    pages = [
        {"added": [txn("t-1"), txn("t-pending", pending=True, authorized_date=None, date="2026-09-05",
                                   personal_finance_category={"primary": "GENERAL_MERCHANDISE", "detailed": None},
                                   merchant_name=None, iso_currency_code=None)],
         "modified": [], "removed": [], "next_cursor": "c1", "has_more": True},
        {"added": [txn("t-posted", pending_transaction_id="t-pending", amount=-2500, personal_finance_category=None,
                       name=None)],
         "modified": [txn("t-1", amount=13.0)], "removed": [{"transaction_id": "t-gone", "account_id": "acc-checking"},
                                                            {"transaction_id": "t-gone-2"}],
         "next_cursor": "c2", "has_more": False, "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE"},
    ]
    cursors = []

    def handler(request):
        body = json.loads(request.content)
        cursors.append(body.get("cursor"))
        assert body["access_token"] == ACCESS_TOKEN and body["count"] == pc.SYNC_PAGE_SIZE
        return ok(pages[len(cursors) - 1])

    result = client(handler).sync_transactions(ACCESS_TOKEN)
    assert cursors == [None, "c1"]
    assert result.next_cursor == "c2" and result.update_status == "HISTORICAL_UPDATE_COMPLETE"
    first, pending, posted = result.added
    assert first.amount == Decimal("12.34") and first.status == "POSTED"
    assert first.transaction_date == date(2026, 9, 1) and first.posted_date == date(2026, 9, 3)
    assert first.provider_category == "FOOD_AND_DRINK_COFFEE" and first.merchant_name == "Corner Cafe"
    assert first.description == "CORNER CAFE 123" and first.currency == "USD" and first.account_external_id == "acc-checking"
    assert pending.status == "PENDING" and pending.posted_date is None and pending.transaction_date == date(2026, 9, 5)
    assert pending.provider_category == "GENERAL_MERCHANDISE" and pending.merchant_name is None and pending.currency is None
    assert posted.amount == Decimal("-2500") and posted.pending_external_id == "t-pending"
    assert posted.provider_category is None and posted.description == ""
    assert [row.amount for row in result.modified] == [Decimal("13.0")]
    assert [(row.external_id, row.account_external_id) for row in result.removed] == [
        ("t-gone", "acc-checking"), ("t-gone-2", None)]


def test_sync_resumes_from_cursor_and_restarts_after_mutation():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body.get("cursor"))
        if len(calls) == 2:
            return plaid_error(400, "TRANSACTIONS_ERROR", pc.MUTATION_DURING_PAGINATION)
        if body.get("cursor") == "saved":
            return ok({"added": [txn("stale")], "modified": [], "removed": [], "next_cursor": "p1", "has_more": True})
        return ok({"added": [txn("fresh")], "modified": [], "removed": [], "next_cursor": "p2", "has_more": False})

    # Pass 1: saved -> p1 -> mutation error. Pass 2 restarts at saved -> p1 -> p2.
    result = client(handler).sync_transactions(ACCESS_TOKEN, "saved")
    assert calls == ["saved", "p1", "saved", "p1"]
    assert [row.external_id for row in result.added] == ["stale", "fresh"] and result.next_cursor == "p2"


def test_sync_gives_up_after_repeated_mutation():
    with pytest.raises(PlaidError) as error:
        client(lambda request: plaid_error(400, "TRANSACTIONS_ERROR", pc.MUTATION_DURING_PAGINATION)).sync_transactions(ACCESS_TOKEN)
    assert error.value.code == "PROVIDER_UNAVAILABLE" and error.value.retryable


def test_sync_page_limit(monkeypatch):
    monkeypatch.setattr(pc, "MAX_SYNC_PAGES", 2)
    page = {"added": [], "modified": [], "removed": [], "next_cursor": "again", "has_more": True}
    with pytest.raises(PlaidError) as error:
        client(lambda request: ok(page)).sync_transactions(ACCESS_TOKEN)
    assert error.value.code == "PROVIDER_DATA_INVALID"


def test_sync_other_errors_propagate():
    with pytest.raises(PlaidError) as error:
        client(lambda request: plaid_error(400, "ITEM_ERROR", "ITEM_LOGIN_REQUIRED")).sync_transactions(ACCESS_TOKEN)
    assert error.value.code == "PROVIDER_RECONNECT_REQUIRED" and error.value.reconnect_required


def test_remove_item_and_already_removed():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return ok({"request_id": "r"})

    client(handler).remove_item(ACCESS_TOKEN)
    assert seen == ["https://sandbox.plaid.com/item/remove"]
    client(lambda request: plaid_error(400, "INVALID_INPUT", "ITEM_NOT_FOUND")).remove_item(ACCESS_TOKEN)
    with pytest.raises(PlaidError):
        client(lambda request: plaid_error(500, "API_ERROR", "INTERNAL_SERVER_ERROR")).remove_item(ACCESS_TOKEN)


# --- Errors -------------------------------------------------------------------------------


@pytest.mark.parametrize(("response", "code", "status"), [
    (plaid_error(400, "ITEM_ERROR", "ITEM_LOGIN_REQUIRED"), "PROVIDER_RECONNECT_REQUIRED", 409),
    (plaid_error(400, "ITEM_ERROR", "PENDING_EXPIRATION"), "PROVIDER_RECONNECT_REQUIRED", 409),
    (plaid_error(400, "INVALID_INPUT", "INVALID_ACCESS_TOKEN"), "PROVIDER_RECONNECT_REQUIRED", 409),
    (plaid_error(400, "INVALID_INPUT", "ITEM_NOT_FOUND"), "PROVIDER_NOT_FOUND", 404),
    (plaid_error(429, "RATE_LIMIT_EXCEEDED", "TRANSACTIONS_SYNC_LIMIT"), "PROVIDER_RATE_LIMIT", 429),
    (plaid_error(400, "RATE_LIMIT_EXCEEDED", "RATE_LIMIT"), "PROVIDER_RATE_LIMIT", 429),
    (httpx.Response(429), "PROVIDER_RATE_LIMIT", 429),
    (plaid_error(400, "INVALID_INPUT", "INVALID_API_KEYS"), "PROVIDER_CONFIGURATION", 503),
    (plaid_error(400, "INVALID_REQUEST", "UNAUTHORIZED_ENVIRONMENT"), "PROVIDER_CONFIGURATION", 503),
    (httpx.Response(401, text="nope"), "PROVIDER_CONFIGURATION", 503),
    (plaid_error(500, "API_ERROR", "INTERNAL_SERVER_ERROR"), "PROVIDER_UNAVAILABLE", 502),
    (plaid_error(400, "INSTITUTION_ERROR", "INSTITUTION_DOWN"), "PROVIDER_UNAVAILABLE", 502),
    (httpx.Response(503, text="<html>"), "PROVIDER_UNAVAILABLE", 502),
    (plaid_error(400, "INVALID_REQUEST", "MISSING_FIELDS"), "PROVIDER_ERROR", 502),
    (httpx.Response(400, json={"error_code": 7}), "PROVIDER_ERROR", 502),
])
def test_error_mapping(response, code, status):
    with pytest.raises(PlaidError) as error:
        client(lambda request: response).accounts(ACCESS_TOKEN)
    assert isinstance(error.value, ProviderError)
    assert (error.value.code, error.value.status) == (code, status)
    assert "demo-secret-value" not in error.value.message and ACCESS_TOKEN not in error.value.message


def test_error_keeps_plaid_code_for_diagnosis():
    with pytest.raises(PlaidError) as error:
        client(lambda request: plaid_error(400, "ITEM_ERROR", "ITEM_LOCKED")).accounts(ACCESS_TOKEN)
    assert error.value.provider_code == "ITEM_LOCKED"


def test_network_error_and_unreadable_and_invalid_responses():
    def broken(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(PlaidError) as error:
        client(broken).accounts(ACCESS_TOKEN)
    assert error.value.code == "PROVIDER_UNAVAILABLE"
    with pytest.raises(PlaidError) as error:
        client(lambda request: httpx.Response(200, text="not json")).accounts(ACCESS_TOKEN)
    assert error.value.code == "PROVIDER_DATA_INVALID"
    with pytest.raises(PlaidError) as error:
        client(lambda request: ok({"accounts": [{"name": "x"}], "item": {"item_id": "i"}})).accounts(ACCESS_TOKEN)
    assert error.value.code == "PROVIDER_DATA_INVALID"


def test_redirects_are_not_followed():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(307, headers={"location": "https://evil.example/accounts/get"})

    with pytest.raises(PlaidError):
        client(handler).accounts(ACCESS_TOKEN)
    assert calls == ["https://sandbox.plaid.com/accounts/get"]


# --- Webhook verification -----------------------------------------------------------------


def b64(value: int) -> str:
    return base64.urlsafe_b64encode(value.to_bytes(32, "big")).rstrip(b"=").decode()


@pytest.fixture
def signer():
    private = ec.generate_private_key(ec.SECP256R1())
    numbers = private.public_key().public_numbers()
    jwk = {"alg": "ES256", "created_at": 1760000000, "crv": "P-256", "expired_at": None, "kid": "kid-1",
           "kty": "EC", "use": "sig", "x": b64(numbers.x), "y": b64(numbers.y)}
    return private, jwk


def key_server(jwk, calls):
    def handler(request):
        body = json.loads(request.content)
        calls.append(body["key_id"])
        if body["key_id"] != jwk["kid"]:
            return plaid_error(400, "INVALID_INPUT", "INVALID_WEBHOOK_VERIFICATION_KEY_ID")
        return ok({"key": jwk, "request_id": "r"})
    return handler


def sign(private, body: bytes, *, iat=None, kid="kid-1", algorithm="ES256", digest=None):
    claims = {"iat": int(time.time()) if iat is None else iat,
              "request_body_sha256": digest or hashlib.sha256(body).hexdigest()}
    return jwt.encode(claims, private, algorithm=algorithm, headers={"kid": kid})


BODY = b'{"webhook_type":"TRANSACTIONS","webhook_code":"SYNC_UPDATES_AVAILABLE","item_id":"item-1"}'


def test_webhook_happy_path_caches_key(signer):
    private, jwk = signer
    calls = []
    plaid = client(key_server(jwk, calls))
    claims = plaid.verify_webhook(BODY, sign(private, BODY))
    assert claims["request_body_sha256"] == hashlib.sha256(BODY).hexdigest()
    plaid.verify_webhook(BODY, sign(private, BODY))
    assert calls == ["kid-1"]


def test_webhook_rejections(signer):
    private, jwk = signer
    calls = []
    plaid = client(key_server(jwk, calls))
    other = ec.generate_private_key(ec.SECP256R1())
    rejected = [
        sign(private, BODY, iat=int(time.time()) - pc.WEBHOOK_MAX_AGE_SECONDS - 5),  # expired
        sign(private, BODY, digest=hashlib.sha256(b"other body").hexdigest()),      # wrong body hash
        sign(private, BODY, kid="kid-unknown"),                                      # unknown key
        jwt.encode({"iat": int(time.time()), "request_body_sha256": hashlib.sha256(BODY).hexdigest()},
                   "shared-secret-for-test-only-0123456789", algorithm="HS256", headers={"kid": "kid-1"}),  # wrong alg
        sign(other, BODY),                                                           # wrong signature
        jwt.encode({"request_body_sha256": hashlib.sha256(BODY).hexdigest()}, private, algorithm="ES256",
                   headers={"kid": "kid-1"}),                                        # no iat
        jwt.encode({"iat": int(time.time())}, private, algorithm="ES256", headers={"kid": "kid-1"}),  # no hash claim
        jwt.encode({"iat": int(time.time()), "request_body_sha256": "x"}, private, algorithm="ES256"),  # no kid
        "not-a-jwt",
        "",
        None,
    ]
    for header in rejected:
        with pytest.raises(PlaidError) as error:
            plaid.verify_webhook(BODY, header)
        assert error.value.code == "WEBHOOK_UNVERIFIED" and error.value.status == 401


def test_webhook_rejects_expired_or_mismatched_key(signer):
    private, jwk = signer
    expired = dict(jwk, expired_at=1760000500)
    with pytest.raises(PlaidError):
        client(key_server(expired, [])).verify_webhook(BODY, sign(private, BODY))
    pc.clear_webhook_key_cache()
    with pytest.raises(PlaidError):
        client(key_server(dict(jwk, alg="RS256"), [])).verify_webhook(BODY, sign(private, BODY))
    pc.clear_webhook_key_cache()
    with pytest.raises(PlaidError):
        client(key_server(dict(jwk, x="AAAA"), [])).verify_webhook(BODY, sign(private, BODY))


def test_webhook_iat_uses_injected_clock(signer):
    private, jwk = signer
    header = sign(private, BODY, iat=1_000_000)
    plaid = client(key_server(jwk, []))
    assert plaid.verify_webhook(BODY, header, now=1_000_000 + 299)["iat"] == 1_000_000
    with pytest.raises(PlaidError):
        plaid.verify_webhook(BODY, header, now=1_000_000 + 301)


def test_webhook_key_cache_is_bounded(signer, monkeypatch):
    _, jwk = signer
    monkeypatch.setattr(pc, "_MAX_CACHED_KEYS", 2)

    def handler(request):
        kid = json.loads(request.content)["key_id"]
        return ok({"key": dict(jwk, kid=kid)})

    plaid = client(handler)
    for kid in ("a", "b", "c"):
        plaid.webhook_verification_key(kid)
    assert set(pc._WEBHOOK_KEYS) == {("sandbox", "c")}

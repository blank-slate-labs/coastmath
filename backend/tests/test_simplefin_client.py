"""SimpleFIN client: setup-token claim, SSRF guard, windowed reads, errors and normalization.

Payloads are synthetic and shaped like the protocol's examples
(https://www.simplefin.org/protocol.html). No network access.
"""
import base64
import json
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from app.ledger.providers import simplefin_client as sf
from app.ledger.providers.errors import ProviderError
from app.ledger.providers.simplefin_client import (
    SimpleFINClient,
    SimpleFINError,
    SimpleFINSettings,
    date_windows,
    decode_setup_token,
    validate_bridge_url,
)

ACCESS = "https://demo-user:demo-pass@beta-bridge.simplefin.org/simplefin"
CLAIM = "https://beta-bridge.simplefin.org/simplefin/claim/demo-claim-0001"
SETTINGS = SimpleFINSettings(frozenset({("beta-bridge.simplefin.org", 443), ("bridge.simplefin.org", 443),
                                        ("bridge.selfhost.test", 8443)}))


def token(url: str) -> str:
    return base64.b64encode(url.encode()).decode()


def epoch(day: date, hour: int = 12) -> int:
    return int(datetime(day.year, day.month, day.day, hour, tzinfo=UTC).timestamp())


def account(**overrides):
    payload = {
        "org": {"domain": "bank.example", "sfin-url": "https://bank.example/simplefin", "name": "Example Bank"},
        "id": "ACT-1", "name": "Everyday Checking", "currency": "USD", "balance": "1250.50",
        "available-balance": "1200.00", "balance-date": epoch(date(2026, 9, 30)),
        "transactions": [
            {"id": "T-1", "posted": epoch(date(2026, 9, 2)), "amount": "-42.10", "description": "GROCERY 0042",
             "payee": "Neighborhood Grocer", "memo": "card purchase"},
            {"id": "T-2", "posted": epoch(date(2026, 9, 15)), "amount": "2500.00", "description": "PAYROLL",
             "transacted_at": epoch(date(2026, 9, 14), 23)},
            {"id": "T-3", "posted": 0, "amount": "-9.99", "description": "STREAMING", "pending": True,
             "transacted_at": epoch(date(2026, 9, 29))},
            {"id": "T-4", "posted": epoch(date(2026, 9, 28)), "amount": "-5.00", "description": "COFFEE", "pending": True},
            {"id": "T-5", "posted": 0, "amount": "-1.00", "description": "UNDATED"},
        ],
    }
    payload.update(overrides)
    return payload


def client(handler) -> SimpleFINClient:
    return SimpleFINClient(SETTINGS, httpx.MockTransport(handler))


def json_response(payload, status=200):
    return httpx.Response(status, content=json.dumps(payload).encode(), headers={"content-type": "application/json"})


# --- Settings and URL guard -----------------------------------------------------------


def test_settings_default_hosts_and_custom_hosts(monkeypatch):
    monkeypatch.delenv("SIMPLEFIN_ALLOWED_HOSTS", raising=False)
    assert SimpleFINSettings.load().allowed_hosts == {("beta-bridge.simplefin.org", 443), ("bridge.simplefin.org", 443)}
    monkeypatch.setenv("SIMPLEFIN_ALLOWED_HOSTS", " Bridge.SelfHost.test:8443 , ,bridge.simplefin.org")
    assert SimpleFINSettings.load().allowed_hosts == {("bridge.selfhost.test", 8443), ("bridge.simplefin.org", 443)}
    monkeypatch.setenv("SIMPLEFIN_ALLOWED_HOSTS", "bridge.selfhost.test:https")
    with pytest.raises(ValueError, match="host or host:port"):
        SimpleFINSettings.load()


def test_validate_access_url_strips_credentials():
    target = validate_bridge_url("https://us%40er:p%3Ass@BETA-BRIDGE.simplefin.org:443/simplefin", SETTINGS, credentials=True)
    assert target.url == "https://beta-bridge.simplefin.org/simplefin"
    assert target.auth == ("us@er", "p:ss")
    assert "p:ss" not in repr(target)
    custom = validate_bridge_url("https://u@bridge.selfhost.test:8443/sf", SETTINGS, credentials=True)
    assert custom.url == "https://bridge.selfhost.test:8443/sf" and custom.auth == ("u", "")
    claim = validate_bridge_url(CLAIM, SETTINGS, credentials=False)
    assert claim.url == CLAIM and claim.auth is None


@pytest.mark.parametrize("url", [
    "http://u:p@beta-bridge.simplefin.org/simplefin",                 # scheme
    "https://u:p@bridge.simplefin.org.evil.example/simplefin",        # suffix trick
    "https://u:p@evil.example/simplefin",                             # host
    "https://bridge.simplefin.org@evil.example/simplefin",            # @ in authority
    "https://u:p@bridge.simplefin.org:8443/simplefin",                # port not allowed
    "https://u:p@bridge.selfhost.test/simplefin",                     # allowed only on its port
    "https://u:p@bridge.simplefin.org:0/simplefin",                   # port zero
    "https://u:p@bridge.simplefin.org:99999/simplefin",               # invalid port
    "https://u:p@bridge.simplefin.org./simplefin",                    # trailing dot
    "https://u:p@bridge.simplefin.org:/simplefin",                    # empty port
    "https://u:p@bridge.simplefin.org\\@evil.example/simplefin",      # backslash
    "https://u:p@bridge.simplefin.org/simplefin?next=evil",           # query
    "https://u:p@bridge.simplefin.org/simplefin#frag",                # fragment
    "https://u:p@bridge.simplefin.org/sim plefin",                    # whitespace
    "https://u:p@[::1]/simplefin",                                    # literal address
    "https://beta-bridge.simplefin.org/simplefin",                    # access URL without credentials
    "https://:p@beta-bridge.simplefin.org/simplefin",                 # empty username
    "",
])
def test_validate_access_url_rejections(url):
    with pytest.raises(SimpleFINError) as error:
        validate_bridge_url(url, SETTINGS, credentials=True)
    assert error.value.code == "PROVIDER_URL_REJECTED" and error.value.status == 422
    assert "evil" not in error.value.message and "simplefin.org" not in error.value.message


def test_claim_url_refuses_credentials():
    with pytest.raises(SimpleFINError):
        validate_bridge_url("https://u:p@beta-bridge.simplefin.org/claim/x", SETTINGS, credentials=False)
    with pytest.raises(SimpleFINError):
        validate_bridge_url(None, SETTINGS, credentials=False)  # type: ignore[arg-type]


def test_decode_setup_token_variants():
    assert decode_setup_token(token(CLAIM)) == CLAIM
    urlsafe = base64.urlsafe_b64encode(b"https://bridge.simplefin.org/claim/??>>").decode().rstrip("=")
    assert decode_setup_token(f"  {urlsafe}\n") == "https://bridge.simplefin.org/claim/??>>"
    for bad in ("not base64!", "", base64.b64encode(b"\xff\xfe").decode(), "café"):
        with pytest.raises(SimpleFINError) as error:
            decode_setup_token(bad)
        assert error.value.code == "PROVIDER_TOKEN_INVALID"


# --- Claim --------------------------------------------------------------------------------


def test_claim_posts_once_and_returns_access_url():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, text=ACCESS + "\n")

    assert client(handler).claim(token(CLAIM)) == ACCESS
    assert len(seen) == 1 and seen[0].method == "POST" and str(seen[0].url) == CLAIM
    assert seen[0].headers["content-length"] == "0" and "authorization" not in seen[0].headers


def test_claim_403_means_used_token():
    with pytest.raises(SimpleFINError) as error:
        client(lambda request: httpx.Response(403)).claim(token(CLAIM))
    assert error.value.code == "PROVIDER_TOKEN_USED" and error.value.reconnect_required and error.value.status == 409


@pytest.mark.parametrize("url", ["http://bridge.simplefin.org/claim", "https://bridge.simplefin.org.evil.example/claim",
                                 "https://bridge.simplefin.org@evil.example/claim"])
def test_claim_refuses_disallowed_claim_urls_without_a_request(url):
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("request sent")

    with pytest.raises(SimpleFINError) as error:
        client(handler).claim(token(url))
    assert error.value.code == "PROVIDER_URL_REJECTED"


@pytest.mark.parametrize("body", [b"https://u:p@evil.example/simplefin", b"\xff\xfe", b"not a url"])
def test_claim_rejects_unusable_access_urls(body):
    with pytest.raises(SimpleFINError) as error:
        client(lambda request: httpx.Response(200, content=body)).claim(token(CLAIM))
    assert error.value.code == "PROVIDER_DATA_INVALID" and "evil" not in error.value.message


def test_claim_does_not_follow_redirects():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.example/claim"})

    with pytest.raises(SimpleFINError) as error:
        client(handler).claim(token(CLAIM))
    assert error.value.code == "PROVIDER_UNAVAILABLE" and calls == [CLAIM]


def test_claim_response_size_is_bounded():
    with pytest.raises(SimpleFINError, match="too much data"):
        client(lambda request: httpx.Response(200, content=b"x" * (sf.MAX_CLAIM_BYTES + 1))).claim(token(CLAIM))


def test_declared_oversize_response_is_refused(monkeypatch):
    monkeypatch.setattr(sf, "MAX_ACCOUNTS_BYTES", 10)
    response = httpx.Response(200, content=b"{}" * 20)
    assert response.headers["content-length"] == "40"
    with pytest.raises(SimpleFINError, match="too much data"):
        client(lambda request: response).accounts(ACCESS)


def test_streamed_oversize_response_is_refused(monkeypatch):
    monkeypatch.setattr(sf, "MAX_ACCOUNTS_BYTES", 10)

    def chunks():
        yield b'{"accounts": '
        yield b"[]}"

    with pytest.raises(SimpleFINError, match="too much data"):
        client(lambda request: httpx.Response(200, content=chunks())).accounts(ACCESS)


# --- Accounts -----------------------------------------------------------------------------


def test_accounts_request_shape_and_auth():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return json_response({"errors": [], "accounts": []})

    read = client(handler).accounts(ACCESS, date(2026, 9, 1), date(2026, 9, 30), account_ids=["ACT-1", "ACT-2"])
    request = seen[0]
    assert request.method == "GET" and request.url.host == "beta-bridge.simplefin.org"
    assert request.url.path == "/simplefin/accounts" and request.url.userinfo == b""
    assert request.headers["authorization"] == "Basic " + base64.b64encode(b"demo-user:demo-pass").decode()
    params = request.url.params
    assert params["start-date"] == str(epoch(date(2026, 9, 1), 0))
    assert params["end-date"] == str(epoch(date(2026, 10, 1), 0))
    assert params.get_list("account") == ["ACT-1", "ACT-2"]
    assert "pending" not in params and "balances-only" not in params
    assert read.accounts == [] and read.transactions == [] and read.messages == []


def test_pending_and_balances_only_parameters_are_sent_only_when_wanted():
    seen = []

    def handler(request):
        seen.append(request.url)
        return json_response({"accounts": []})

    client(handler).accounts(ACCESS.replace("/simplefin", "/simplefin/"), pending=True, balances_only=True)
    assert seen[0].path == "/simplefin/accounts"
    assert seen[0].params["pending"] == "1" and seen[0].params["balances-only"] == "1"
    assert "start-date" not in seen[0].params


def test_single_read_refuses_more_than_sixty_days():
    with pytest.raises(ValueError, match="accounts_range"):
        client(lambda request: json_response({})).accounts(ACCESS, date(2026, 1, 1), date(2026, 3, 2))
    with pytest.raises(ValueError):
        client(lambda request: json_response({})).accounts(ACCESS, date(2026, 3, 1), date(2026, 2, 1))


def test_accounts_reject_disallowed_access_url():
    with pytest.raises(SimpleFINError) as error:
        client(lambda request: json_response({})).accounts("https://u:p@evil.example/simplefin")
    assert error.value.code == "PROVIDER_URL_REJECTED"


def test_normalization_signs_dates_and_status():
    payload = {"errors": ["  Example Bank needs attention at your bridge.  ", " ", "x" * 400],
               "accounts": [account()]}
    read = client(lambda request: json_response(payload)).accounts(ACCESS, date(2026, 9, 1), date(2026, 9, 30), pending=True)
    assert read.messages == ["Example Bank needs attention at your bridge.", "x" * sf.MAX_MESSAGE_LENGTH]
    assert read.skipped == 1
    [acct] = read.accounts
    assert acct.external_id == "ACT-1" and acct.name == "Everyday Checking"
    assert acct.account_type is None and acct.subtype is None and acct.mask is None
    assert acct.institution_name == "Example Bank" and acct.institution_id == "bank.example"
    assert acct.currency == "USD" and acct.balance == Decimal("1250.50")
    assert acct.balance_date == datetime(2026, 9, 30, 12, tzinfo=UTC)
    rows = {row.external_id: row for row in read.transactions}
    assert set(rows) == {"T-1", "T-2", "T-3", "T-4"}
    grocery = rows["T-1"]
    assert grocery.amount == Decimal("42.10") and grocery.status == "POSTED"
    assert grocery.transaction_date == date(2026, 9, 2) and grocery.posted_date == date(2026, 9, 2)
    assert grocery.merchant_name == "Neighborhood Grocer" and grocery.currency == "USD"
    assert grocery.account_external_id == "ACT-1" and grocery.provider_category is None
    payroll = rows["T-2"]
    assert payroll.amount == Decimal("-2500.00") and payroll.merchant_name is None
    assert payroll.transaction_date == date(2026, 9, 14) and payroll.posted_date == date(2026, 9, 15)
    assert rows["T-3"].status == "PENDING" and rows["T-3"].posted_date is None
    assert rows["T-3"].transaction_date == date(2026, 9, 29)
    assert rows["T-4"].status == "PENDING" and rows["T-4"].transaction_date == date(2026, 9, 28)


def test_custom_currency_and_missing_org_name():
    custom = account(currency="https://points.example/currency", name=" ", balance="-310.00", transactions=[],
                     org={"domain": "card.example", "id": "org-7"}, **{"balance-date": 0})
    read = client(lambda request: json_response({"accounts": [custom]})).accounts(ACCESS)
    [acct] = read.accounts
    assert acct.currency is None and acct.name == "Account" and acct.balance == Decimal("-310.00")
    assert acct.institution_name == "card.example" and acct.institution_id == "org-7" and acct.balance_date is None


@pytest.mark.parametrize("body", [b"not json", json.dumps({"accounts": [{"id": "A"}]}).encode(),
                                  json.dumps({"accounts": [account(balance="NaN")]}).encode()])
def test_malformed_account_data(body):
    with pytest.raises(SimpleFINError) as error:
        client(lambda request: httpx.Response(200, content=body)).accounts(ACCESS)
    assert error.value.code == "PROVIDER_DATA_INVALID"


@pytest.mark.parametrize(("status", "code", "http", "reconnect", "retryable"), [
    (402, "PROVIDER_PAYMENT_REQUIRED", 402, False, False),
    (403, "PROVIDER_RECONNECT_REQUIRED", 409, True, False),
    (401, "PROVIDER_RECONNECT_REQUIRED", 409, True, False),
    (429, "PROVIDER_RATE_LIMIT", 429, False, True),
    (500, "PROVIDER_UNAVAILABLE", 502, False, True),
    (503, "PROVIDER_UNAVAILABLE", 502, False, True),
    (404, "PROVIDER_UNAVAILABLE", 502, False, True),
])
def test_accounts_error_mapping(status, code, http, reconnect, retryable):
    with pytest.raises(SimpleFINError) as error:
        client(lambda request: httpx.Response(status, text="demo-pass")).accounts(ACCESS)
    assert isinstance(error.value, ProviderError)
    assert (error.value.code, error.value.status) == (code, http)
    assert error.value.reconnect_required is reconnect and error.value.retryable is retryable
    assert "demo-pass" not in error.value.message and "simplefin.org" not in error.value.message


def test_network_errors_are_transient():
    def handler(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(SimpleFINError) as error:
        client(handler).accounts(ACCESS)
    assert error.value.code == "PROVIDER_UNAVAILABLE" and error.value.retryable


# --- Window walking -----------------------------------------------------------------------


def test_date_windows():
    assert date_windows(date(2026, 1, 1), date(2026, 1, 1)) == [(date(2026, 1, 1), date(2026, 1, 2))]
    windows = date_windows(date(2026, 1, 1), date(2026, 5, 1))
    assert windows[0] == (date(2026, 1, 1), date(2026, 2, 15))
    assert windows[-1][1] == date(2026, 5, 2)
    assert all((after - first).days <= 45 for first, after in windows)
    assert all(windows[i][1] == windows[i + 1][0] for i in range(len(windows) - 1))
    with pytest.raises(ValueError):
        date_windows(date(2026, 2, 1), date(2026, 1, 1))


def test_accounts_range_walks_windows_and_merges():
    requests = []

    def handler(request: httpx.Request):
        start = int(request.url.params["start-date"])
        requests.append((start, int(request.url.params["end-date"]), request.url.params.get("pending")))
        index = len(requests)
        shared = {"id": "T-shared", "posted": epoch(date(2026, 3, 1)), "amount": f"-{index}.00", "description": "OVERLAP"}
        own = {"id": f"T-{index}", "posted": start + 3600, "amount": "-1.00", "description": "WINDOW"}
        undated = {"id": f"U-{index}", "posted": 0, "amount": "-1.00", "description": "UNDATED"}
        return json_response({"errors": ["Bridge note."], "accounts": [
            account(balance=str(100 * index), transactions=[shared, own, undated]),
        ]})

    read = client(handler).accounts_range(ACCESS, date(2026, 1, 1), date(2026, 5, 31), pending=True)
    assert len(requests) == 4
    assert requests[0][0] == epoch(date(2026, 1, 1), 0) and requests[-1][1] == epoch(date(2026, 6, 1), 0)
    assert all(end - start <= 45 * 86400 for start, end, _ in requests)
    assert all(pending == "1" for *_, pending in requests)
    [acct] = read.accounts
    assert acct.balance == Decimal("400")
    rows = {row.external_id: row for row in read.transactions}
    assert set(rows) == {"T-shared", "T-1", "T-2", "T-3", "T-4"}
    assert rows["T-shared"].amount == Decimal("4.00")
    assert read.messages == ["Bridge note."] and read.skipped == 4

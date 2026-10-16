"""SimpleFIN client, per the SimpleFIN protocol (https://www.simplefin.org/protocol.html).

A customer buys access at a SimpleFIN Bridge and pastes a *setup token*: the
base64 encoding of a one-time claim URL. POSTing to the claim URL returns an
*access URL* that embeds HTTP Basic credentials; that URL is the long-lived
credential the sync layer stores encrypted. ``GET {access}/accounts`` returns
accounts with their transactions.

Both URLs are user input, so every request passes the SSRF guard: HTTPS only,
the host must be in ``SIMPLEFIN_ALLOWED_HOSTS``, no redirects, short timeouts
and a bounded response size. Credentials travel in the ``Authorization`` header
of a URL rebuilt from validated parts, never in the request URL.

SimpleFIN does not report an account type. Normalized accounts carry
``account_type=None`` and the bridge's raw balance sign; the sync layer applies
the CREDIT/LOAN convention (balance = amount owed) once the customer confirms
the type. Nothing here reads or writes the database.
"""
import base64
import binascii
import os
import string
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from urllib.parse import unquote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ledger.providers.errors import ProviderError
from app.ledger.types import NormalizedAccount, NormalizedTransaction

DEFAULT_ALLOWED_HOSTS = ("beta-bridge.simplefin.org", "bridge.simplefin.org")
#: Bridges recommend at most 45 days per accounts request and warn above it.
MAX_WINDOW_DAYS = 45
MAX_CLAIM_BYTES = 4096
MAX_ACCOUNTS_BYTES = 20 * 1024 * 1024
MAX_MESSAGES = 20
MAX_MESSAGE_LENGTH = 300
TIMEOUT = httpx.Timeout(30, connect=5)
_FORBIDDEN_URL_CHARS = frozenset(string.whitespace) | {"\\"} | {chr(c) for c in range(32)} | {chr(127)}


class SimpleFINError(ProviderError):
    """A SimpleFIN setup, claim or read failed."""


def _host_entry(entry: str) -> tuple[str, int] | None:
    entry = entry.strip().lower()
    if not entry:
        return None
    host, _, port = entry.partition(":")
    return host, int(port) if port else 443


@dataclass(frozen=True)
class SimpleFINSettings:
    """``allowed_hosts`` holds ``(host, port)`` pairs; an entry without a port means 443."""

    allowed_hosts: frozenset[tuple[str, int]]

    @classmethod
    def load(cls) -> "SimpleFINSettings":
        raw = os.getenv("SIMPLEFIN_ALLOWED_HOSTS", "").strip()
        entries = raw.split(",") if raw else DEFAULT_ALLOWED_HOSTS
        try:
            hosts = frozenset(pair for entry in entries if (pair := _host_entry(entry)))
        except ValueError:
            raise ValueError("SIMPLEFIN_ALLOWED_HOSTS entries must be host or host:port") from None
        return cls(hosts)


@dataclass(frozen=True)
class BridgeURL:
    """A validated bridge URL without credentials, plus the Basic credentials it carried."""

    url: str
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)

    @property
    def auth(self) -> tuple[str, str] | None:
        return (self.username, self.password or "") if self.username is not None else None


def _rejected() -> SimpleFINError:
    return SimpleFINError("PROVIDER_URL_REJECTED", "This SimpleFIN bridge address is not allowed on this server.", 422)


def validate_bridge_url(url: str, settings: SimpleFINSettings, *, credentials: bool) -> BridgeURL:
    """Accept only ``https://[user:pass@]allowed-host[:port]/path``.

    ``credentials`` is True for an access URL (credentials required) and False
    for a claim URL (credentials refused). Queries and fragments are refused.
    """
    if not isinstance(url, str) or not url or any(ch in _FORBIDDEN_URL_CHARS for ch in url):
        raise _rejected()
    try:
        parts = urlsplit(url)
        port = 443 if parts.port is None else parts.port
    except ValueError:
        raise _rejected() from None
    host = parts.hostname or ""
    if parts.scheme != "https" or parts.query or parts.fragment or (host, port) not in settings.allowed_hosts:
        raise _rejected()
    userinfo, at, hostport = parts.netloc.rpartition("@")
    if hostport.lower() not in {host, f"{host}:{port}"}:
        raise _rejected()
    if credentials != bool(at) or (credentials and not parts.username):
        raise _rejected()
    netloc = host if port == 443 else f"{host}:{port}"
    rebuilt = f"https://{netloc}{parts.path}"
    if not credentials:
        return BridgeURL(rebuilt)
    return BridgeURL(rebuilt, unquote(parts.username or ""), unquote(parts.password or ""))


def decode_setup_token(token: str) -> str:
    """The claim URL a setup token encodes (standard or URL-safe base64)."""
    text = (token or "").strip()
    padded = (text + "=" * (-len(text) % 4)).encode("ascii", "replace")
    for altchars in (None, b"-_"):
        try:
            decoded = base64.b64decode(padded, altchars=altchars, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeError):
            continue
        if decoded:
            return decoded
    raise SimpleFINError("PROVIDER_TOKEN_INVALID", "This is not a SimpleFIN setup token.", 422)


# --- Response models (protocol "Account Set") ---------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False, populate_by_name=True)


class _Org(_Model):
    domain: str | None = None
    name: str | None = None
    id: str | None = None


class _Transaction(_Model):
    id: str = Field(min_length=1, max_length=200)
    posted: int = Field(ge=0)
    amount: Decimal
    description: str = ""
    transacted_at: int | None = Field(default=None, ge=0)
    pending: bool = False
    payee: str | None = None


class _Account(_Model):
    org: _Org
    id: str = Field(min_length=1, max_length=200)
    name: str = ""
    currency: str = ""
    balance: Decimal
    balance_date: int = Field(alias="balance-date", ge=0)
    transactions: list[_Transaction] = Field(default_factory=list)


class _AccountSet(_Model):
    errors: list[str] = Field(default_factory=list)
    accounts: list[_Account] = Field(default_factory=list)


@dataclass(frozen=True)
class SimpleFINRead:
    """Accounts and transactions from one or more reads.

    ``messages`` are the bridge's ``errors`` strings, which the protocol says
    to show the customer (for example a bank needing attention at the bridge).
    ``skipped`` counts transactions without any usable date.
    """

    accounts: list[NormalizedAccount]
    transactions: list[NormalizedTransaction]
    messages: list[str]
    skipped: int = 0


def _utc_date(seconds: int) -> date:
    return datetime.fromtimestamp(seconds, tz=UTC).date()


def _currency(value: str) -> str | None:
    """ISO 4217 codes only; the protocol's custom-currency URLs have no ledger equivalent."""
    value = value.strip().upper()
    return value if len(value) == 3 and value.isalpha() else None


def normalize_account(account: _Account) -> NormalizedAccount:
    return NormalizedAccount(
        external_id=account.id, name=account.name.strip() or "Account", account_type=None,
        institution_name=account.org.name or account.org.domain, institution_id=account.org.id or account.org.domain,
        currency=_currency(account.currency), balance=account.balance,
        balance_date=datetime.fromtimestamp(account.balance_date, tz=UTC) if account.balance_date else None,
    )


def normalize_transaction(row: _Transaction, account: _Account) -> NormalizedTransaction | None:
    """SimpleFIN deposits are positive, so the ledger amount is negated. None when undatable."""
    pending = row.pending or row.posted == 0
    when = row.transacted_at or row.posted
    if not when:
        return None
    return NormalizedTransaction(
        external_id=row.id, account_external_id=account.id, amount=-row.amount, transaction_date=_utc_date(when),
        description=row.description.strip(), status="PENDING" if pending else "POSTED",
        posted_date=None if pending else _utc_date(row.posted), currency=_currency(account.currency),
        merchant_name=(row.payee or "").strip() or None,
    )


def _epoch(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())


def date_windows(start: date, end: date, days: int = MAX_WINDOW_DAYS) -> list[tuple[date, date]]:
    """Split ``start``..``end`` (inclusive) into ``(first_day, day_after_last)`` spans of at most ``days``."""
    if end < start:
        raise ValueError("end precedes start")
    windows = []
    cursor = start
    stop = end + timedelta(days=1)
    while cursor < stop:
        upper = min(cursor + timedelta(days=days), stop)
        windows.append((cursor, upper))
        cursor = upper
    return windows


class SimpleFINClient:
    def __init__(self, settings: SimpleFINSettings | None = None, transport: httpx.BaseTransport | None = None):
        self.settings = settings or SimpleFINSettings.load()
        self.transport = transport

    def _send(self, method: str, target: BridgeURL, *, path: str = "", params: dict | None = None,
              limit: int, claim: bool = False) -> bytes:
        with httpx.Client(transport=self.transport, timeout=TIMEOUT, follow_redirects=False, trust_env=False) as client:
            try:
                with client.stream(method, target.url + path, params=params, auth=target.auth, content=b"" if method == "POST" else None,
                                   headers={"Accept": "application/json" if not claim else "text/plain"}) as response:
                    self._raise_for_status(response.status_code, claim)
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > limit:
                        raise SimpleFINError("PROVIDER_DATA_INVALID", "The SimpleFIN bridge returned too much data.")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body += chunk
                        if len(body) > limit:
                            raise SimpleFINError("PROVIDER_DATA_INVALID", "The SimpleFIN bridge returned too much data.")
                    return bytes(body)
            except httpx.HTTPError:
                raise SimpleFINError("PROVIDER_UNAVAILABLE", "The SimpleFIN bridge could not be reached. Try again later.") from None

    @staticmethod
    def _raise_for_status(status: int, claim: bool) -> None:
        if 200 <= status < 300:
            return
        if claim and status == 403:
            raise SimpleFINError("PROVIDER_TOKEN_USED", "This setup token was already used or revoked. Create a new one at your bridge.", 409)
        if status == 402:
            raise SimpleFINError("PROVIDER_PAYMENT_REQUIRED", "Your SimpleFIN subscription needs payment at your bridge.", 402)
        if status in {401, 403}:
            raise SimpleFINError("PROVIDER_RECONNECT_REQUIRED", "SimpleFIN access was revoked. Reconnect with a new setup token.", 409)
        if status == 429:
            raise SimpleFINError("PROVIDER_RATE_LIMIT", "The SimpleFIN bridge is limiting requests. Try again later.", 429)
        raise SimpleFINError("PROVIDER_UNAVAILABLE", "The SimpleFIN bridge could not complete this request. Try again later.")

    def claim(self, setup_token: str) -> str:
        """Exchange a setup token for the access URL. Each token works once."""
        claim_url = validate_bridge_url(decode_setup_token(setup_token), self.settings, credentials=False)
        body = self._send("POST", claim_url, limit=MAX_CLAIM_BYTES, claim=True)
        try:
            access_url = body.decode("utf-8").strip()
        except UnicodeError:
            access_url = ""
        try:
            validate_bridge_url(access_url, self.settings, credentials=True)
        except SimpleFINError:
            raise SimpleFINError("PROVIDER_DATA_INVALID", "The SimpleFIN bridge returned an unusable access address.") from None
        return access_url

    def accounts(self, access_url: str, start: date | None = None, end: date | None = None, *,
                 pending: bool = False, account_ids: list[str] | None = None, balances_only: bool = False) -> SimpleFINRead:
        """One ``/accounts`` read covering ``start``..``end`` (inclusive, at most ``MAX_WINDOW_DAYS``).

        ``pending=1`` is sent only when wanted: bridges treat the parameter's
        presence as true.
        """
        target = validate_bridge_url(access_url, self.settings, credentials=True)
        params: list[tuple[str, str]] = []
        if start is not None:
            stop = (end or start) + timedelta(days=1)
            if stop - start > timedelta(days=MAX_WINDOW_DAYS) or stop <= start:
                raise ValueError(f"A SimpleFIN read covers 1 to {MAX_WINDOW_DAYS} days; use accounts_range for longer spans.")
            params += [("start-date", str(_epoch(start))), ("end-date", str(_epoch(stop)))]
        if pending:
            params.append(("pending", "1"))
        if balances_only:
            params.append(("balances-only", "1"))
        params += [("account", account_id) for account_id in account_ids or []]
        path = "accounts" if target.url.endswith("/") else "/accounts"
        body = self._send("GET", target, path=path, params=params or None, limit=MAX_ACCOUNTS_BYTES)
        try:
            data = _AccountSet.model_validate_json(body)
        except ValidationError:
            raise SimpleFINError("PROVIDER_DATA_INVALID", "The SimpleFIN bridge returned unreadable account data.") from None
        accounts, transactions, skipped = [], [], 0
        for account in data.accounts:
            accounts.append(normalize_account(account))
            for row in account.transactions:
                normalized = normalize_transaction(row, account)
                if normalized is None:
                    skipped += 1
                else:
                    transactions.append(normalized)
        messages = [message.strip()[:MAX_MESSAGE_LENGTH] for message in data.errors if message.strip()][:MAX_MESSAGES]
        return SimpleFINRead(accounts, transactions, messages, skipped)

    def accounts_range(self, access_url: str, start: date, end: date, *, pending: bool = False,
                       account_ids: list[str] | None = None) -> SimpleFINRead:
        """Walk ``start``..``end`` (inclusive) in ``MAX_WINDOW_DAYS`` reads, oldest first.

        Accounts keep the newest read's balance; a transaction seen in two
        windows keeps its newest version. Bridges limit daily requests, so long
        ranges cost several of them.
        """
        accounts: dict[str, NormalizedAccount] = {}
        transactions: dict[tuple[str, str], NormalizedTransaction] = {}
        messages: list[str] = []
        skipped = 0
        for first, after in date_windows(start, end):
            read = self.accounts(access_url, first, after - timedelta(days=1), pending=pending, account_ids=account_ids)
            accounts.update((account.external_id, account) for account in read.accounts)
            transactions.update(((row.account_external_id, row.external_id), row) for row in read.transactions)
            messages += [message for message in read.messages if message not in messages]
            skipped += read.skipped
        return SimpleFINRead(list(accounts.values()), list(transactions.values()), messages[:MAX_MESSAGES], skipped)

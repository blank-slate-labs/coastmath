"""Plaid REST client over httpx, per https://plaid.com/docs/api/ (API version 2020-09-14).

The operator supplies ``PLAID_CLIENT_ID`` and ``PLAID_SECRET``; each linked
Item yields an access token that the sync layer stores encrypted. Plaid
already signs amounts the ledger's way (positive leaves the account) and
reports credit and loan balances as the amount owed.

Nothing here reads or writes the database. Access tokens, secrets and raw
responses are never logged or put in error messages; errors keep Plaid's
``error_code`` (an identifier, not user data) for diagnosis.
"""
import hashlib
import hmac
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx
import jwt
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ledger.providers.errors import ProviderError
from app.ledger.types import NormalizedAccount, NormalizedTransaction

API_VERSION = "2020-09-14"
CLIENT_NAME = "CoastMath"
#: Longest history Plaid offers for transactions (https://plaid.com/docs/api/link/#link-token-create-request-transactions-days-requested).
DAYS_REQUESTED = 730
SYNC_PAGE_SIZE = 500
MAX_SYNC_PAGES = 200
MAX_SYNC_RESTARTS = 3
#: Plaid recommends rejecting webhooks whose ``iat`` is more than five minutes old.
WEBHOOK_MAX_AGE_SECONDS = 5 * 60
TIMEOUT = httpx.Timeout(30, connect=5)

# https://plaid.com/docs/errors/item/ and https://plaid.com/docs/errors/invalid-input/
RECONNECT_ERROR_CODES = frozenset({
    "ITEM_LOGIN_REQUIRED", "PENDING_EXPIRATION", "PENDING_DISCONNECT", "ACCESS_NOT_GRANTED", "ITEM_LOCKED",
    "USER_SETUP_REQUIRED", "INVALID_CREDENTIALS", "INVALID_MFA", "INVALID_UPDATED_USERNAME", "INSUFFICIENT_CREDENTIALS",
    "NO_ACCOUNTS", "USER_PERMISSION_REVOKED", "INVALID_ACCESS_TOKEN", "ITEM_CONCURRENTLY_DELETED",
})
CONFIGURATION_ERROR_CODES = frozenset({
    "INVALID_API_KEYS", "UNAUTHORIZED_ENVIRONMENT", "UNAUTHORIZED_ROUTE_ACCESS", "INVALID_PRODUCT",
    "PRODUCTS_NOT_SUPPORTED", "INVALID_LINK_CUSTOMIZATION", "INVALID_WEBHOOK_VERIFICATION_KEY_ID",
})
TRANSIENT_ERROR_TYPES = frozenset({"API_ERROR", "INSTITUTION_ERROR"})
MUTATION_DURING_PAGINATION = "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"

# Plaid account types and subtypes (https://plaid.com/docs/api/accounts/#account-type-schema) to
# the ledger vocabulary. Subtype keys reuse app/ledger/balances.py SUGGESTED_TYPES where an
# equivalent exists. Subtypes whose tax treatment Plaid cannot settle
# (457b, thrift savings plan, pension, generic retirement, non-taxable brokerage) stay unmapped.
ACCOUNT_TYPES = {"depository": "DEPOSITORY", "credit": "CREDIT", "loan": "LOAN", "investment": "INVESTMENT",
                 "brokerage": "INVESTMENT", "other": "OTHER"}
SUBTYPES = {
    "depository": {"checking": "CHECKING", "savings": "SAVINGS", "cash management": "CASH_MANAGEMENT",
                   "money market": "MONEY_MARKET", "cd": "CD", "prepaid": "PREPAID", "hsa": "HSA"},
    "credit": {"credit card": "CREDIT_CARD"},
    "loan": {"mortgage": "MORTGAGE", "student": "STUDENT", "auto": "AUTO", "home equity": "HOME_EQUITY",
             "line of credit": "LINE_OF_CREDIT"},
    "investment": {"401k": "PLAN_401K", "roth 401k": "ROTH_401K", "403b": "PLAN_403B", "401a": "PLAN_401A",
                   "ira": "IRA", "roth": "ROTH", "sep ira": "SEP_IRA", "simple ira": "SIMPLE_IRA",
                   "brokerage": "BROKERAGE", "hsa": "HSA", "529": "PLAN_529"},
}
SUBTYPES["brokerage"] = SUBTYPES["investment"]


class PlaidError(ProviderError):
    """A Plaid call failed or a webhook did not verify."""


@dataclass(frozen=True)
class PlaidSettings:
    client_id: str
    secret: str = field(repr=False)
    environment: str
    country_codes: tuple[str, ...] = ("US",)
    redirect_uri: str | None = None
    webhook_url: str | None = None

    @classmethod
    def load(cls) -> "PlaidSettings":
        environment = os.getenv("PLAID_ENV", "sandbox").strip() or "sandbox"
        if environment not in {"sandbox", "production"}:
            raise ValueError("PLAID_ENV must be sandbox or production")
        codes = tuple(code.strip().upper() for code in os.getenv("PLAID_COUNTRY_CODES", "US").split(",") if code.strip())
        if not codes or any(len(code) != 2 or not code.isalpha() for code in codes):
            raise ValueError("PLAID_COUNTRY_CODES must be comma-separated ISO country codes")
        return cls(os.getenv("PLAID_CLIENT_ID", "").strip(), os.getenv("PLAID_SECRET", "").strip(), environment, codes,
                   os.getenv("PLAID_REDIRECT_URI", "").strip() or None, os.getenv("PLAID_WEBHOOK_URL", "").strip() or None)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.secret)

    @property
    def api_origin(self) -> str:
        return "https://sandbox.plaid.com" if self.environment == "sandbox" else "https://production.plaid.com"


# --- Response models --------------------------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)


class _ErrorBody(_Model):
    error_type: str | None = None
    error_code: str | None = None


class _LinkToken(_Model):
    link_token: str = Field(min_length=1)
    expiration: datetime | None = None


class _Exchange(_Model):
    access_token: str = Field(min_length=1)
    item_id: str = Field(min_length=1, max_length=255)


class _Balances(_Model):
    current: Decimal | None = None
    iso_currency_code: str | None = None
    last_updated_datetime: datetime | None = None


class _Account(_Model):
    account_id: str = Field(min_length=1, max_length=255)
    name: str = ""
    official_name: str | None = None
    mask: str | None = None
    type: str
    subtype: str | None = None
    balances: _Balances = Field(default_factory=_Balances)


class _Item(_Model):
    item_id: str = Field(min_length=1, max_length=255)
    institution_id: str | None = None
    institution_name: str | None = None


class _Accounts(_Model):
    accounts: list[_Account]
    item: _Item


class _Category(_Model):
    primary: str | None = None
    detailed: str | None = None


class _Transaction(_Model):
    transaction_id: str = Field(min_length=1, max_length=255)
    account_id: str = Field(min_length=1, max_length=255)
    amount: Decimal
    iso_currency_code: str | None = None
    posted_on: date = Field(alias="date")
    authorized_date: date | None = None
    pending: bool = False
    pending_transaction_id: str | None = None
    name: str | None = None
    merchant_name: str | None = None
    personal_finance_category: _Category | None = None


class _Removed(_Model):
    transaction_id: str = Field(min_length=1, max_length=255)
    account_id: str | None = None


class _SyncPage(_Model):
    added: list[_Transaction] = Field(default_factory=list)
    modified: list[_Transaction] = Field(default_factory=list)
    removed: list[_Removed] = Field(default_factory=list)
    next_cursor: str
    has_more: bool
    transactions_update_status: str | None = None


class _VerificationKey(_Model):
    model_config = ConfigDict(extra="allow")
    kid: str
    alg: str
    expired_at: int | None = None


class _VerificationKeyResponse(_Model):
    key: _VerificationKey


# --- Results -----------------------------------------------------------------------------


@dataclass(frozen=True)
class LinkToken:
    link_token: str = field(repr=False)
    expiration: datetime | None = None


@dataclass(frozen=True)
class PublicTokenExchange:
    item_id: str
    access_token: str = field(repr=False)


@dataclass(frozen=True)
class PlaidAccounts:
    item_id: str
    institution_id: str | None
    accounts: list[NormalizedAccount]


@dataclass(frozen=True)
class RemovedTransaction:
    """``account_external_id`` is None when Plaid omits it; the store then matches the ID alone."""

    external_id: str
    account_external_id: str | None


@dataclass(frozen=True)
class SyncResult:
    """One complete ``transactions/sync`` pass; persist ``next_cursor`` only after storing the rows."""

    added: list[NormalizedTransaction]
    modified: list[NormalizedTransaction]
    removed: list[RemovedTransaction]
    next_cursor: str = field(repr=False)
    update_status: str | None = None


# --- Normalization -------------------------------------------------------------------------


def map_account_type(plaid_type: str, plaid_subtype: str | None) -> tuple[str, str | None]:
    """Ledger ``(account_type, subtype)`` for a Plaid type and subtype; unknown subtypes map to None."""
    kind = (plaid_type or "").strip().lower()
    subtype = (plaid_subtype or "").strip().lower()
    return ACCOUNT_TYPES.get(kind, "OTHER"), SUBTYPES.get(kind, {}).get(subtype)


def _currency(code: str | None) -> str | None:
    return code.strip().upper() if code and code.strip() else None


def normalize_account(account: _Account, item: _Item) -> NormalizedAccount:
    account_type, subtype = map_account_type(account.type, account.subtype)
    return NormalizedAccount(
        external_id=account.account_id, name=(account.name or account.official_name or "Account").strip(),
        account_type=account_type, subtype=subtype, institution_name=item.institution_name,
        institution_id=item.institution_id, mask=account.mask, currency=_currency(account.balances.iso_currency_code),
        balance=account.balances.current, balance_date=account.balances.last_updated_datetime,
    )


def normalize_transaction(row: _Transaction) -> NormalizedTransaction:
    category = row.personal_finance_category
    return NormalizedTransaction(
        external_id=row.transaction_id, account_external_id=row.account_id, amount=row.amount,
        transaction_date=row.authorized_date or row.posted_on, description=(row.name or "").strip(),
        status="PENDING" if row.pending else "POSTED", posted_date=None if row.pending else row.posted_on,
        currency=_currency(row.iso_currency_code),
        provider_category=(category.detailed or category.primary) if category else None,
        merchant_name=(row.merchant_name or "").strip() or None, pending_external_id=row.pending_transaction_id,
    )


# --- Client --------------------------------------------------------------------------------

_WEBHOOK_KEYS: dict[tuple[str, str], dict[str, Any]] = {}
_WEBHOOK_KEYS_LOCK = threading.Lock()
_MAX_CACHED_KEYS = 32


def clear_webhook_key_cache() -> None:
    with _WEBHOOK_KEYS_LOCK:
        _WEBHOOK_KEYS.clear()


def _error_from_response(response: httpx.Response) -> PlaidError:
    try:
        body = _ErrorBody.model_validate(response.json())
    except (ValueError, ValidationError):
        body = _ErrorBody()
    code, kind = body.error_code, body.error_type
    if kind == "RATE_LIMIT_EXCEEDED" or response.status_code == 429:
        return PlaidError("PROVIDER_RATE_LIMIT", "Plaid is limiting requests. Try again later.", 429, code)
    if code in RECONNECT_ERROR_CODES:
        return PlaidError("PROVIDER_RECONNECT_REQUIRED", "This bank connection needs you to sign in again.", 409, code)
    if code == "ITEM_NOT_FOUND":
        return PlaidError("PROVIDER_NOT_FOUND", "Plaid no longer has this connection.", 404, code)
    if code in CONFIGURATION_ERROR_CODES or response.status_code in {401, 403}:
        return PlaidError("PROVIDER_CONFIGURATION", "The Plaid connection requires administrator attention.", 503, code)
    if kind in TRANSIENT_ERROR_TYPES or response.status_code >= 500:
        return PlaidError("PROVIDER_UNAVAILABLE", "Plaid or the bank is unavailable. Try again later.", 502, code)
    return PlaidError("PROVIDER_ERROR", "Plaid could not complete this request.", 502, code)


class PlaidClient:
    def __init__(self, settings: PlaidSettings | None = None, transport: httpx.BaseTransport | None = None):
        self.settings = settings or PlaidSettings.load()
        self.transport = transport

    def request(self, path: str, body: dict[str, Any]) -> Any:
        if not self.settings.configured:
            raise PlaidError("INTEGRATION_UNAVAILABLE", "Plaid is not configured on this server.", 503)
        # The origin comes from a constant; credentials never follow a redirect.
        with httpx.Client(base_url=self.settings.api_origin, transport=self.transport, timeout=TIMEOUT,
                          follow_redirects=False, trust_env=False) as client:
            try:
                response = client.post(path, json=body, headers={
                    "PLAID-CLIENT-ID": self.settings.client_id, "PLAID-SECRET": self.settings.secret,
                    "Plaid-Version": API_VERSION, "Accept": "application/json",
                })
            except httpx.HTTPError:
                raise PlaidError("PROVIDER_UNAVAILABLE", "Plaid could not be reached. Try again later.") from None
        if not response.is_success:
            raise _error_from_response(response)
        try:
            return response.json()
        except ValueError:
            raise PlaidError("PROVIDER_DATA_INVALID", "Plaid returned an unreadable response.") from None

    @staticmethod
    def parse(model: type[_Model], data: Any):
        try:
            return model.model_validate(data)
        except ValidationError:
            raise PlaidError("PROVIDER_DATA_INVALID", "Plaid returned incomplete or invalid data.") from None

    def create_link_token(self, client_user_id: str, *, access_token: str | None = None,
                          redirect_uri: str | None = None, language: str = "en") -> LinkToken:
        """A Link token for a new Item, or for update mode when ``access_token`` is given.

        ``client_user_id`` must be a stable, non-identifying ID (never an email).
        Update mode omits ``products``, as Plaid requires.
        """
        body: dict[str, Any] = {
            "client_name": CLIENT_NAME, "language": language, "country_codes": list(self.settings.country_codes),
            "user": {"client_user_id": client_user_id},
        }
        if access_token:
            body["access_token"] = access_token
        else:
            body["products"] = ["transactions"]
            body["transactions"] = {"days_requested": DAYS_REQUESTED}
        if self.settings.webhook_url:
            body["webhook"] = self.settings.webhook_url
        if redirect := redirect_uri or self.settings.redirect_uri:
            body["redirect_uri"] = redirect
        result = self.parse(_LinkToken, self.request("/link/token/create", body))
        return LinkToken(result.link_token, result.expiration)

    def exchange_public_token(self, public_token: str) -> PublicTokenExchange:
        result = self.parse(_Exchange, self.request("/item/public_token/exchange", {"public_token": public_token}))
        return PublicTokenExchange(result.item_id, result.access_token)

    def accounts(self, access_token: str) -> PlaidAccounts:
        result = self.parse(_Accounts, self.request("/accounts/get", {"access_token": access_token}))
        return PlaidAccounts(result.item.item_id, result.item.institution_id,
                             [normalize_account(account, result.item) for account in result.accounts])

    def sync_transactions(self, access_token: str, cursor: str | None = None) -> SyncResult:
        """Every change since ``cursor`` (None or empty: full history), following ``has_more``.

        Plaid asks callers to restart from the pass's first cursor on
        TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION, discarding the pages read so far.
        """
        for _ in range(MAX_SYNC_RESTARTS + 1):
            added: list[NormalizedTransaction] = []
            modified: list[NormalizedTransaction] = []
            removed: list[RemovedTransaction] = []
            page_cursor = cursor or ""
            try:
                for _ in range(MAX_SYNC_PAGES):
                    body: dict[str, Any] = {"access_token": access_token, "count": SYNC_PAGE_SIZE}
                    if page_cursor:
                        body["cursor"] = page_cursor
                    page = self.parse(_SyncPage, self.request("/transactions/sync", body))
                    added += [normalize_transaction(row) for row in page.added]
                    modified += [normalize_transaction(row) for row in page.modified]
                    removed += [RemovedTransaction(row.transaction_id, row.account_id) for row in page.removed]
                    page_cursor = page.next_cursor
                    if not page.has_more:
                        return SyncResult(added, modified, removed, page_cursor, page.transactions_update_status)
            except PlaidError as error:
                if error.provider_code == MUTATION_DURING_PAGINATION:
                    continue
                raise
            raise PlaidError("PROVIDER_DATA_INVALID", "Plaid returned an incomplete transaction list.")
        raise PlaidError("PROVIDER_UNAVAILABLE", "Plaid transactions kept changing during the update. Try again later.", 502,
                         MUTATION_DURING_PAGINATION)

    def remove_item(self, access_token: str) -> None:
        """Revoke the Item's access token. An Item Plaid no longer has counts as removed."""
        try:
            self.request("/item/remove", {"access_token": access_token})
        except PlaidError as error:
            if error.code != "PROVIDER_NOT_FOUND":
                raise

    def webhook_verification_key(self, key_id: str) -> dict[str, Any]:
        """The JWK for ``key_id``, cached per environment."""
        cache_key = (self.settings.environment, key_id)
        with _WEBHOOK_KEYS_LOCK:
            cached = _WEBHOOK_KEYS.get(cache_key)
        if cached is not None:
            return cached
        result = self.parse(_VerificationKeyResponse, self.request("/webhook_verification_key/get", {"key_id": key_id}))
        key = result.key.model_dump()
        with _WEBHOOK_KEYS_LOCK:
            if len(_WEBHOOK_KEYS) >= _MAX_CACHED_KEYS:
                _WEBHOOK_KEYS.clear()
            _WEBHOOK_KEYS[cache_key] = key
        return key

    def verify_webhook(self, body: bytes, verification_header: str | None, *, now: float | None = None) -> dict[str, Any]:
        """Verify a webhook's ``Plaid-Verification`` JWT and return its claims.

        Per https://plaid.com/docs/api/webhooks/webhook-verification/: ES256
        only, the key named by ``kid``, ``iat`` no older than five minutes and
        ``request_body_sha256`` equal to the SHA-256 of the raw body.
        """
        def refuse() -> PlaidError:
            return PlaidError("WEBHOOK_UNVERIFIED", "The webhook could not be verified.", 401)

        if not verification_header:
            raise refuse()
        try:
            header = jwt.get_unverified_header(verification_header)
        except jwt.PyJWTError:
            raise refuse() from None
        kid = header.get("kid")
        if header.get("alg") != "ES256" or not isinstance(kid, str) or not kid:
            raise refuse()
        try:
            jwk = self.webhook_verification_key(kid)
        except PlaidError:
            raise refuse() from None
        if jwk.get("expired_at") or jwk.get("alg") != "ES256":
            raise refuse()
        try:
            public_key = jwt.PyJWK({name: jwk[name] for name in ("kty", "crv", "x", "y") if name in jwk}, "ES256").key
            claims = jwt.decode(verification_header, public_key, algorithms=["ES256"],
                                options={"verify_iat": False, "require": ["iat"]})
        except (jwt.PyJWTError, KeyError, ValueError, TypeError):
            raise refuse() from None
        issued = claims.get("iat")
        current = time.time() if now is None else now
        if not isinstance(issued, int | float) or current - issued > WEBHOOK_MAX_AGE_SECONDS:
            raise refuse()
        expected = claims.get("request_body_sha256")
        actual = hashlib.sha256(body).hexdigest()
        if not isinstance(expected, str) or not hmac.compare_digest(expected, actual):
            raise refuse()
        return claims

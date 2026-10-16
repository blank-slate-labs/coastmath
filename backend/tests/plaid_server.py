"""A synthetic Plaid API behind ``httpx.MockTransport``: no real institutions, people or keys.

Shapes follow https://plaid.com/docs/api/. ``Plaid.pages`` holds the
``transactions/sync`` pages served in order from the cursor the caller sends.
"""
import base64
import hashlib
import json
import time

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from app.ledger.providers import plaid_adapter, plaid_client
from app.ledger.providers.plaid_client import PlaidClient, PlaidSettings

ITEM_ID = "item-synthetic-1"
ACCESS_TOKEN = "demo-plaid-access-0001"
PUBLIC_TOKEN = "demo-plaid-public-0001"
LINK_TOKEN = "demo-plaid-link-0001"


def txn(transaction_id: str, account_id: str = "acc-card", amount: float = 12.5, day: str = "2026-09-03", **extra):
    row = {"transaction_id": transaction_id, "account_id": account_id, "amount": amount, "iso_currency_code": "USD",
           "date": day, "authorized_date": None, "pending": False, "pending_transaction_id": None,
           "name": f"Synthetic {transaction_id}", "merchant_name": "Synthetic Shop",
           "personal_finance_category": {"primary": "GENERAL_MERCHANDISE", "detailed": "GENERAL_MERCHANDISE_OTHER"}}
    row.update(extra)
    return row


def b64(value: int) -> str:
    return base64.urlsafe_b64encode(value.to_bytes(32, "big")).rstrip(b"=").decode()


class Plaid:
    def __init__(self):
        self.item_id = ITEM_ID
        self.accounts = [
            {"account_id": "acc-card", "name": "Synthetic card", "mask": "4321", "type": "credit",
             "subtype": "credit card", "balances": {"current": 250.0, "iso_currency_code": "USD"}},
            {"account_id": "acc-check", "name": "Synthetic checking", "mask": "9876", "type": "depository",
             "subtype": "checking", "balances": {"current": 1200.5, "iso_currency_code": "USD",
                                                 "last_updated_datetime": None}},
        ]
        self.institution_name: str | None = "Synthetic Bank"
        #: cursor sent ("" for the first call) -> page body
        self.pages: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []
        #: path -> (status, error_type, error_code) to fail with
        self.failures: dict[str, tuple[int, str, str]] = {}
        self.private = ec.generate_private_key(ec.SECP256R1())
        numbers = self.private.public_key().public_numbers()
        self.jwk = {"alg": "ES256", "created_at": 1760000000, "crv": "P-256", "expired_at": None, "kid": "kid-1",
                    "kty": "EC", "use": "sig", "x": b64(numbers.x), "y": b64(numbers.y)}

    def page(self, cursor: str, *, added=(), modified=(), removed=(), next_cursor: str, has_more: bool = False,
             status: str = "HISTORICAL_UPDATE_COMPLETE") -> None:
        self.pages[cursor] = {"added": list(added), "modified": list(modified), "removed": list(removed),
                              "next_cursor": next_cursor, "has_more": has_more, "transactions_update_status": status,
                              "accounts": [], "request_id": "r"}

    def paths(self) -> list[str]:
        return [path for path, _ in self.calls]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content)
        self.calls.append((path, body))
        if path in self.failures:
            status, kind, code = self.failures[path]
            return httpx.Response(status, json={"error_type": kind, "error_code": code, "error_message": "x"})
        if path == "/link/token/create":
            return httpx.Response(200, json={"link_token": LINK_TOKEN, "expiration": "2026-10-11T16:00:00Z"})
        if path == "/item/public_token/exchange":
            return httpx.Response(200, json={"access_token": ACCESS_TOKEN, "item_id": self.item_id})
        if path == "/accounts/get":
            item = {"item_id": self.item_id, "institution_id": "ins_demo"}
            if self.institution_name:
                item["institution_name"] = self.institution_name
            return httpx.Response(200, json={"accounts": self.accounts, "item": item})
        if path == "/transactions/sync":
            page = self.pages.get(body.get("cursor", ""))
            if page is None:
                page = {"added": [], "modified": [], "removed": [], "next_cursor": body.get("cursor", ""),
                        "has_more": False, "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE"}
            return httpx.Response(200, json=page)
        if path == "/item/remove":
            return httpx.Response(200, json={"request_id": "r"})
        if path == "/webhook_verification_key/get":
            return httpx.Response(200, json={"key": self.jwk, "request_id": "r"})
        return httpx.Response(404, json={"error_type": "INVALID_REQUEST", "error_code": "NOT_FOUND"})

    def client(self) -> PlaidClient:
        return PlaidClient(PlaidSettings.load(), httpx.MockTransport(self.handler))

    def sign(self, body: bytes, *, iat: int | None = None) -> str:
        claims = {"iat": int(time.time()) if iat is None else iat, "request_body_sha256": hashlib.sha256(body).hexdigest()}
        return jwt.encode(claims, self.private, algorithm="ES256", headers={"kid": "kid-1"})


def install(monkeypatch, plaid: Plaid) -> None:
    monkeypatch.setenv("PLAID_CLIENT_ID", "demo-client-id")
    monkeypatch.setenv("PLAID_SECRET", "demo-secret-value")
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    plaid_client.clear_webhook_key_cache()
    monkeypatch.setattr(plaid_adapter, "make_client", plaid.client)

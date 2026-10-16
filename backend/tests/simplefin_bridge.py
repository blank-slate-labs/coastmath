"""A synthetic SimpleFIN bridge behind ``httpx.MockTransport``: no real institutions or people."""
import base64
from datetime import UTC, date, datetime, timedelta

import httpx

from app.ledger.providers import simplefin_adapter
from app.ledger.providers.simplefin_client import SimpleFINClient, SimpleFINSettings

HOST = "bridge.example"
CLAIM_URL = f"https://{HOST}/simplefin/claim/demo-token"
ACCESS_URL = f"https://demo-user:demo-pass@{HOST}/simplefin"
SETUP_TOKEN = base64.b64encode(CLAIM_URL.encode()).decode()


def epoch(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp())


class Bridge:
    def __init__(self, today: date):
        self.today = today
        self.accounts = [
            {"id": "ACT-card", "name": "Synthetic card", "org": {"name": "Synthetic Bank", "id": "org-1"}},
            {"id": "ACT-check", "name": "Synthetic checking", "org": {"name": "Synthetic Bank", "id": "org-1"}},
        ]
        self.balances = {"ACT-card": "-250.00", "ACT-check": "1200.50"}
        self.currency = "USD"
        # (account_id, txn_id, day, bridge amount: deposits positive)
        self.rows: list[tuple[str, str, date, str]] = []
        self.errors: list[str] = []
        self.status = 200
        self.claim_status = 200
        self.claims = 0
        self.reads: list[tuple[date, date]] = []
        self.access_url = ACCESS_URL
        self.balance_day = today - timedelta(days=1)

    def add(self, account: str, txn: str, days_ago: int, amount: str) -> None:
        self.rows.append((account, txn, self.today - timedelta(days=days_ago), amount))

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.claims += 1
            if self.claim_status != 200:
                return httpx.Response(self.claim_status)
            return httpx.Response(200, text=self.access_url)
        if self.status != 200:
            return httpx.Response(self.status)
        assert request.headers["authorization"].startswith("Basic ")
        start = datetime.fromtimestamp(int(request.url.params["start-date"]), tz=UTC).date()
        stop = datetime.fromtimestamp(int(request.url.params["end-date"]), tz=UTC).date()
        self.reads.append((start, stop - timedelta(days=1)))
        accounts = []
        for account in self.accounts:
            transactions = [{"id": txn, "posted": epoch(day), "amount": amount, "description": f"Synthetic {txn}",
                             "payee": "Synthetic Payee"}
                            for owner, txn, day, amount in self.rows
                            if owner == account["id"] and start <= day < stop]
            accounts.append({**account, "currency": self.currency, "balance": self.balances[account["id"]],
                             "balance-date": epoch(self.balance_day), "transactions": transactions})
        return httpx.Response(200, json={"errors": self.errors, "accounts": accounts})

    def client(self) -> SimpleFINClient:
        return SimpleFINClient(SimpleFINSettings.load(), httpx.MockTransport(self.handler))


def install(monkeypatch, bridge: Bridge) -> None:
    monkeypatch.setenv("SIMPLEFIN_ALLOWED_HOSTS", HOST)
    monkeypatch.setattr(simplefin_adapter, "make_client", bridge.client)

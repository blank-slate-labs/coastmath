"""Provider-neutral balance helpers and connection lifecycle rules."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.ledger import balances
from app.ledger import connections as lifecycle
from app.ledger.accounts import UNCONFIRMED_TYPE, counts_toward_spending
from app.ledger.providers.errors import ProviderError
from app.ledger.secrets import CredentialError
from app.models.financial_connection import FinancialConnection, FinancialSource, utcnow
from app.schemas.ledger_connections import LinkBalanceRequest
from tests.ledger_fixture import plugin_provider


def source(**values) -> FinancialSource:
    base = dict(provider="simplefin", account_type="DEPOSITORY", subtype="CHECKING", status="ACTIVE", currency="USD",
                balance=Decimal("10.00"), balance_updated_at=utcnow(), include_in_spending=None)
    return FinancialSource(**{**base, **values})


@pytest.mark.parametrize("raw,kind,expected", [
    (Decimal("-25.50"), "CREDIT", Decimal("25.50")), (Decimal("-25.50"), "LOAN", Decimal("25.50")),
    (Decimal("100.005"), "DEPOSITORY", Decimal("100.00")), (Decimal("-3"), UNCONFIRMED_TYPE, Decimal("-3.00")),
    (None, "CREDIT", None), (Decimal("NaN"), "DEPOSITORY", None), (Decimal("1e20"), "DEPOSITORY", None),
])
def test_signed_balance(raw, kind, expected):
    assert balances.signed_balance(raw, kind) == expected


def test_retype_balance_flips_only_raw_sign_providers_across_debt():
    row = source(account_type="CREDIT", balance=Decimal("-40.00"))
    balances.retype_balance(row, UNCONFIRMED_TYPE)
    assert row.balance == Decimal("40.00")
    row.account_type = "LOAN"
    balances.retype_balance(row, "CREDIT")
    assert row.balance == Decimal("40.00")
    row.account_type = "DEPOSITORY"
    balances.retype_balance(row, "LOAN")
    assert row.balance == Decimal("-40.00")
    file_row = source(provider="file", account_type="CREDIT", balance=Decimal("5"))
    balances.retype_balance(file_row, "DEPOSITORY")
    assert file_row.balance == Decimal("5")
    empty = source(account_type="CREDIT", balance=None)
    balances.retype_balance(empty, "DEPOSITORY")
    assert empty.balance is None


def test_unconfirmed_accounts_never_feed_spending_or_balances():
    row = source(account_type=UNCONFIRMED_TYPE, include_in_spending=True)
    assert not counts_toward_spending(row)
    assert balances.source_problem(row) == "Confirm this account's type before using its balance."
    now = utcnow()
    assert balances.source_problem(source(balance_updated_at=now - timedelta(days=8)), now).startswith("The reported")
    assert balances.source_problem(source(balance_updated_at=now - timedelta(days=8)), now - timedelta(days=2)) is None


def test_lifecycle_failure_mapping_and_backoff(monkeypatch):
    now = utcnow()
    row = FinancialConnection(provider="simplefin", created_at=now - timedelta(hours=1), last_checked_at=None)
    own = plugin_provider(monkeypatch, own_lifecycle=True)
    assert lifecycle.is_neutral(row) and not lifecycle.is_neutral(FinancialConnection(provider=own))
    assert lifecycle.backoff(row, now) == timedelta(hours=1)
    lifecycle.record_failure(row, CredentialError(), now)
    assert row.status == lifecycle.RECONNECT_REQUIRED and row.next_check_at is None
    lifecycle.record_failure(row, ProviderError("PROVIDER_DATA_INVALID", "Unreadable data."), now)
    assert row.status == lifecycle.RETRYING and row.next_check_at == now + timedelta(hours=1)
    lifecycle.record_failure(row, ProviderError("PROVIDER_TOKEN_USED", "Used."), now)
    assert row.status == lifecycle.RECONNECT_REQUIRED
    lifecycle.record_success(row, now, "x" * 600, timedelta(hours=12))
    assert row.status == lifecycle.ACTIVE and len(row.error) == 500
    assert not lifecycle.is_syncing(row, now)
    row.status, row.next_check_at = lifecycle.SYNCING, now + timedelta(minutes=1)
    assert lifecycle.is_syncing(row, now)
    lifecycle.revoke(FinancialConnection(provider="unknown", credentials_encrypted="v1:x"))
    lifecycle.revoke(FinancialConnection(provider="simplefin", credentials_encrypted=None))


def test_link_request_requires_one_reviewed_target():
    plan = str(uuid.uuid4())
    with pytest.raises(ValidationError, match="Choose one"):
        LinkBalanceRequest(plan_id=plan, source_revision=1)
    with pytest.raises(ValidationError, match="existing saved balance"):
        LinkBalanceRequest(plan_id=plan, source_revision=1, account_id=str(uuid.uuid4()))
    debt = {"name": "Synthetic loan", "principal_balance": 10, "interest_rate": 5, "monthly_payment": 1}
    assert LinkBalanceRequest(plan_id=plan, source_revision=1, new_liability=debt).new_liability
    with pytest.raises(ValidationError, match="finite"):
        LinkBalanceRequest.model_validate({"plan_id": plan, "source_revision": 1,
                                           "new_liability": {**debt, "extra_payment": float("inf")}})

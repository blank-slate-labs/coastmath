"""Shapes every provider adapter and file parser produces for the ledger store.

Sign convention: a positive ``amount`` leaves the account (purchases, payments,
transfers out) and a negative amount arrives (deposits, refunds, transfers in).
Plaid already signs amounts this way; SimpleFIN and OFX report the opposite,
so their adapters negate.

Dates are the institution's calendar dates. Never shift them through a time
zone; a provider timestamp converts to the calendar date it names.
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

TransactionStatus = Literal["POSTED", "PENDING"]

#: ``financial_sources.account_type`` vocabulary, shared by every provider.
ACCOUNT_TYPES = ("DEPOSITORY", "CREDIT", "LOAN", "INVESTMENT", "OTHER")


@dataclass(frozen=True)
class NormalizedAccount:
    """One account at a provider, or the target account of a file import.

    ``account_type`` is one of ``ACCOUNT_TYPES``, or None when the provider
    cannot say (SimpleFIN); the customer confirms it before the account feeds
    spending or balances. ``subtype`` uses the existing ``financial_sources``
    vocabulary (CHECKING, SAVINGS, CREDIT_CARD, PLAN_401K, ...) wherever an
    equivalent exists. ``balance`` is money held for DEPOSITORY and INVESTMENT
    accounts and the amount owed for CREDIT and LOAN accounts.
    """

    external_id: str
    name: str
    account_type: str | None
    subtype: str | None = None
    institution_name: str | None = None
    institution_id: str | None = None
    mask: str | None = None
    currency: str | None = None
    balance: Decimal | None = None
    balance_date: datetime | None = None
    active: bool = True


@dataclass(frozen=True)
class NormalizedTransaction:
    """One transaction in an account.

    ``external_id`` is stable for the same transaction across reads: the
    provider's ID, an OFX FITID or a CSV row key. The ledger scopes it to the
    account before storing it. ``provider_category`` keeps the provider's raw
    category text; the ledger maps it to canonical categories centrally.
    ``pending_external_id`` names the pending transaction a posted one replaces.
    """

    external_id: str
    account_external_id: str
    amount: Decimal
    transaction_date: date
    description: str
    status: TransactionStatus = "POSTED"
    posted_date: date | None = None
    currency: str | None = None
    provider_category: str | None = None
    merchant_name: str | None = None
    pending_external_id: str | None = None
    recurring_status: str | None = None

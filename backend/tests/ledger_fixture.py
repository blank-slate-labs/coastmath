"""Synthetic ledger rows for tests: no real institutions, accounts or people."""
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from app.ledger import provider_traits
from app.ledger.types import NormalizedTransaction
from app.models.financial_connection import (
    FinancialSource,
    FinancialSpendingFeed,
    FinancialTransaction,
)
from app.models.ledger import FinancialImport
from app.models.plan import Plan
from app.models.planning_client import PlanningClient
from app.models.user import User


def make_source(db, user, *, provider="file", environment="production", account_type="CREDIT",
                subtype="CREDIT_CARD", name="Synthetic card", external="acct-1", coverage_start=None,
                synced_at=None, **extra) -> FinancialSource:
    source = FinancialSource(
        id=uuid.uuid4(), user_id=user.id, provider=provider, environment=environment, provider_account_id=external,
        connection_ids=[], institution_name="Synthetic bank", name=name, account_type=account_type,
        subtype=subtype, status="ACTIVE", currency="USD", revision=1, transactions_coverage_start=coverage_start,
        transactions_synced_at=synced_at, fetched_at=datetime.now(UTC), **extra)
    db.add(source)
    db.flush()
    return source


def make_import(db, user, source, start: date, end: date, status="committed") -> FinancialImport:
    row = FinancialImport(id=uuid.uuid4(), user_id=user.id, source_id=source.id, filename="synthetic.csv",
                          file_sha256="0" * 64, format="csv", mapping={}, date_from=start, date_to=end,
                          status=status, created_at=datetime.now(UTC))
    db.add(row)
    db.flush()
    return row


def make_txn(db, user, source, amount, day: date, category=None, *, external=None, status="POSTED",
             description="Synthetic purchase", merchant=None, **extra) -> FinancialTransaction:
    row = FinancialTransaction(
        id=uuid.uuid4(), user_id=user.id, source_id=source.id, provider=source.provider,
        environment=source.environment, provider_transaction_id=external or uuid.uuid4().hex,
        amount=Decimal(str(amount)), currency="USD", description=description, merchant_name=merchant,
        provider_category=category, status=status, transaction_date=day, updated_at=datetime.now(UTC),
        **extra)
    db.add(row)
    db.flush()
    return row


def normalized(external, amount, day: date, **extra) -> NormalizedTransaction:
    return NormalizedTransaction(external_id=external, account_external_id="acct-1", amount=Decimal(str(amount)),
                                 transaction_date=day, description=extra.pop("description", "Synthetic purchase"),
                                 **extra)


def plugin_provider(monkeypatch, key="plugin", **traits) -> str:
    """Register a plug-in provider's ledger traits for one test (app.ledger.provider_traits)."""
    monkeypatch.setitem(provider_traits._TRAITS, key, provider_traits.ProviderTraits(environment=lambda: "sandbox", **traits))
    return key


def plan_with_feed(db, user, source_ids):
    client = PlanningClient(id=uuid.uuid4(), user_id=user.id, name="Synthetic household",
                            created_at=datetime.now(UTC))
    db.add(client)
    db.flush()
    plan = Plan(user_id=user.id, client_id=client.id, name="Ledger plan", birth_year=1985, life_expectancy=90,
                plan_type="NOW", currency="USD")
    db.add(plan)
    db.flush()
    feed = FinancialSpendingFeed(id=uuid.uuid4(), user_id=user.id, plan_id=plan.id,
                                 source_ids=[str(value) for value in source_ids])
    db.add(feed)
    db.commit()
    return plan, feed


def other_user(db):
    user = User(is_anonymous=True, settings={}, created_at=datetime.now(UTC))
    db.add(user)
    db.flush()
    return user

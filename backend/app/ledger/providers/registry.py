"""Which transaction providers exist and whether this deployment offers them now.

Descriptors are computed on each call from operator configuration, so a flag
change takes effect without a code change. File import, SimpleFIN and Plaid
register here. A plug-in provider registers itself from its own package
(``app.plugins``); this module never imports it.

``pull_sync`` providers are run by ``app.ledger.sync_worker`` through their
``adapter`` (``app.ledger.providers.base``).
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.feature_flags import plaid_enabled, simplefin_enabled, transactions_enabled
from app.ledger import secrets
from app.ledger.providers.plaid_adapter import PlaidAdapter
from app.ledger.providers.plaid_client import DAYS_REQUESTED, PlaidSettings
from app.ledger.providers.simplefin_adapter import HISTORY_DAYS, SimpleFINAdapter

LinkFlow = Literal["file", "token", "widget"]
Capability = Literal["transactions", "balances", "pending", "webhooks", "history"]


@dataclass(frozen=True)
class ProviderDescriptor:
    key: str
    label: str
    link_flow: LinkFlow
    capabilities: frozenset[str]
    offered: bool
    #: Why the provider is not offered; None when it is.
    reason: str | None = None
    pull_sync: bool = False
    #: Days of history a first sync requests, when the provider has a limit.
    history_days: int | None = None
    adapter: Any = field(default=None, compare=False, repr=False)


_FACTORIES: dict[str, Callable[[], ProviderDescriptor]] = {}


def register(key: str, factory: Callable[[], ProviderDescriptor]) -> None:
    """Add or replace a provider; ``factory`` runs on every lookup."""
    _FACTORIES[key] = factory


def descriptors() -> list[ProviderDescriptor]:
    return [factory() for factory in _FACTORIES.values()]


def descriptor(key: str) -> ProviderDescriptor | None:
    factory = _FACTORIES.get(key)
    return factory() if factory else None


def pull_providers() -> dict[str, ProviderDescriptor]:
    """Offered providers the ledger worker syncs, by key."""
    return {item.key: item for item in descriptors() if item.pull_sync and item.offered}


def _file() -> ProviderDescriptor:
    offered = transactions_enabled()
    return ProviderDescriptor(
        key="file", label="File import", link_flow="file", capabilities=frozenset({"transactions"}),
        offered=offered, reason=None if offered else "Transactions are unavailable in this release.")


def _simplefin() -> ProviderDescriptor:
    reason = None
    if not transactions_enabled():
        reason = "Transactions are unavailable in this release."
    elif not simplefin_enabled():
        reason = "SimpleFIN is not enabled on this server."
    elif not secrets.available():
        reason = "SimpleFIN needs an encryption key on this server."
    offered = reason is None
    return ProviderDescriptor(
        key="simplefin", label="SimpleFIN", link_flow="token",
        capabilities=frozenset({"transactions", "balances", "pending", "history"}), offered=offered, reason=reason,
        pull_sync=True, history_days=HISTORY_DAYS, adapter=SimpleFINAdapter())


def plaid_problem() -> str | None:
    """Why this deployment cannot offer Plaid now, or None."""
    if not transactions_enabled():
        return "Transactions are unavailable in this release."
    if not plaid_enabled():
        return "Plaid is not enabled on this server."
    try:
        settings = PlaidSettings.load()
    except ValueError:
        return "Plaid's configuration on this server is invalid."
    if not settings.configured:
        return "Plaid needs PLAID_CLIENT_ID and PLAID_SECRET on this server."
    if not secrets.available():
        return "Plaid needs an encryption key on this server."
    return None


def _plaid() -> ProviderDescriptor:
    reason = plaid_problem()
    return ProviderDescriptor(
        key="plaid", label="Plaid", link_flow="widget",
        capabilities=frozenset({"transactions", "balances", "pending", "webhooks", "history"}),
        offered=reason is None, reason=reason, pull_sync=True, history_days=DAYS_REQUESTED, adapter=PlaidAdapter())


register("file", _file)
register("simplefin", _simplefin)
register("plaid", _plaid)

"""What a plug-in provider declares to the shared ledger.

Built-in providers (file import, SimpleFIN, Plaid) need no entry. A plug-in
provider (``app.plugins``) registers its environment setting, category names
and storage conventions here, beside its descriptor in
``app.ledger.providers.registry``.
"""
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderTraits:
    #: The active environment ("sandbox" or "production"), read on each call.
    environment: Callable[[], str]
    #: The provider's category names mapped to canonical category IDs.
    categories: dict[str, str] = field(default_factory=dict)
    #: The plug-in runs its own connections; ``app.ledger.connections`` leaves them alone.
    own_lifecycle: bool = True
    #: Transaction IDs are stored as the provider sends them, without the account prefix.
    raw_transaction_ids: bool = False


_TRAITS: dict[str, ProviderTraits] = {}


def register(key: str, traits: ProviderTraits) -> None:
    _TRAITS[key] = traits


def traits(key: str) -> ProviderTraits | None:
    return _TRAITS.get(key)


def keys() -> tuple[str, ...]:
    return tuple(_TRAITS)


def own_lifecycle() -> frozenset[str]:
    return frozenset(key for key, value in _TRAITS.items() if value.own_lifecycle)

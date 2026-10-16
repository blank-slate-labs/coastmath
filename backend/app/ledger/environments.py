"""The active environment for each provider.

Sandbox and production rows share the ledger tables. Provider-neutral reads
include only rows whose ``(provider, environment)`` pair is active, so sample
institutions never mix with real accounts.
"""
import os

from sqlalchemy import and_, or_

from app.ledger import provider_traits

BUILT_IN = ("plaid", "simplefin", "file")


def providers() -> tuple[str, ...]:
    return provider_traits.keys() + BUILT_IN


def environment_for(provider: str) -> str:
    """Plaid follows ``PLAID_ENV`` (default sandbox) and a plug-in provider its
    own setting; SimpleFIN and file imports are always production data."""
    traits = provider_traits.traits(provider)
    if traits is not None:
        return traits.environment()
    if provider == "plaid":
        return os.getenv("PLAID_ENV", "sandbox").strip() or "sandbox"
    return "production"


def active_pairs() -> list[tuple[str, str]]:
    return [(provider, environment_for(provider)) for provider in providers()]


def active_filter(model):
    """SQL condition: ``model.provider``/``model.environment`` is an active pair."""
    return or_(*(and_(model.provider == provider, model.environment == environment)
                 for provider, environment in active_pairs()))

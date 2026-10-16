"""Provider registry: descriptors follow operator configuration; plug-in providers register themselves."""
import os

import pytest

from app.ledger import provider_traits
from app.ledger.providers import registry, simplefin_adapter
from app.ledger.providers.registry import ProviderDescriptor


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    # A plug-in provider reads its own <KEY>_* settings.
    plugin_settings = [name for name in os.environ
                       if any(name.startswith(f"{key.upper()}_") for key in provider_traits.keys())]  # noqa: SIM118 - a module function
    for name in ("TRANSACTIONS_ENABLED", "SIMPLEFIN_ENABLED", "LEDGER_ENCRYPTION_KEY", "SESSION_SECRET",
                 "PLAID_ENABLED", "PLAID_CLIENT_ID", "PLAID_SECRET", "PLAID_ENV", *plugin_settings):
        monkeypatch.delenv(name, raising=False)


def test_everything_is_off_by_default():
    found = {item.key: item for item in registry.descriptors()}
    assert set(found) >= {"file", "simplefin", "plaid"}
    assert not any(item.offered for item in found.values())
    assert found["file"].reason == found["simplefin"].reason == "Transactions are unavailable in this release."
    assert registry.pull_providers() == {}


def test_simplefin_needs_its_flag_and_an_encryption_key(monkeypatch):
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "true")
    assert registry.descriptor("file").offered
    assert registry.descriptor("simplefin").reason == "SimpleFIN is not enabled on this server."
    monkeypatch.setenv("SIMPLEFIN_ENABLED", "true")
    assert registry.descriptor("simplefin").reason == "SimpleFIN needs an encryption key on this server."
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", "synthetic-ledger-key-0123456789-abcdef")
    simplefin = registry.descriptor("simplefin")
    assert simplefin.offered and simplefin.reason is None and simplefin.pull_sync
    assert simplefin.link_flow == "token" and simplefin.history_days == 365 and simplefin.adapter.provider == "simplefin"
    assert set(registry.pull_providers()) == {"simplefin"}


def test_register_adds_and_replaces(monkeypatch):
    monkeypatch.setattr(registry, "_FACTORIES", dict(registry._FACTORIES))
    item = ProviderDescriptor(key="demo", label="Demo", link_flow="widget", capabilities=frozenset(), offered=True)
    registry.register("demo", lambda: item)
    assert registry.descriptor("demo") is item and registry.descriptor("missing") is None
    replaced = ProviderDescriptor(key="demo", label="Demo 2", link_flow="widget", capabilities=frozenset(), offered=False)
    registry.register("demo", lambda: replaced)
    assert registry.descriptor("demo").label == "Demo 2"


def test_simplefin_client_factory_uses_operator_settings(monkeypatch):
    monkeypatch.setenv("SIMPLEFIN_ALLOWED_HOSTS", "bridge.example")
    assert simplefin_adapter.make_client().settings.allowed_hosts == frozenset({("bridge.example", 443)})

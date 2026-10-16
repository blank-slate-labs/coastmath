"""Provider-neutral transaction ledger.

Everything here works for every provider and every deployment: file import,
SimpleFIN, Plaid and plug-in providers share one store, one taxonomy and one
month model. Provider-specific code lives in ``app.ledger.providers``; a
plug-in provider declares itself through ``app.ledger.providers.registry`` and
``app.ledger.provider_traits``. Modules in this package never import a plug-in.
"""

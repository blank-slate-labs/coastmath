"""Plan scenarios: complete plans that follow a Main plan.

A scenario is an ordinary plan (every reader, the engine, share and export use
it unchanged) with ``plans.parent_plan_id`` set to its Main plan. Whenever
Main is saved, a session hook (``hooks``) copies Main's changes into each
scenario in the same transaction, except values the scenario changed itself.
Overrides are inferred by a three-way comparison against ``plan_links.base``
(``sync``), so no write route has to record them.

- ``registry``: the inherited kinds, their models and inheritable columns.
- ``values``: canonical encoding and Main-to-scenario ID translation, shared
  with plain duplication.
- ``sync``: the merge, scenario creation links, and the inheritance API's
  read, reset, restore and detach operations.
- ``hooks``: SQLAlchemy session events that run the sync on commit.
"""

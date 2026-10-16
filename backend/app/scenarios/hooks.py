"""Session events that sync scenarios when their Main plan is saved.

Registered on the ``Session`` class and the plan-scoped mappers, so they
cover request sessions, the background financial balance sync, importers and
test sessions alike.

- Mapper ``after_insert``/``after_update``/``before_delete`` events record
  which plans (and which kinds) a flush changed, including rows removed by
  delete-orphan cascades, which never appear in ``Session.deleted``.
- ``before_commit`` syncs each changed plan's scenarios in the same
  transaction, each inside its own savepoint, so one scenario's failure never
  blocks Main's save or another scenario's sync.

Bulk statements (``Query.delete``) bypass the mapper; their callers report
the change with ``mark_plan_changed``.
"""
import uuid

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session, object_session

from app.models.plan import Plan
from app.scenarios.registry import MODEL_KINDS, PLAN_FIELDS, PLAN_KIND

TOUCHED = "scenario_sync_touched"
RUNNING = "scenario_sync_running"
# Every kind: a deleted row's ON DELETE SET NULL can change rows of any kind
# that referenced it without an ORM event.
ALL_KINDS = "*"


def mark_plan_changed(session: Session, plan_id: uuid.UUID, kind: str) -> None:
    """Record that ``kind`` rows (``ALL_KINDS``: any) of ``plan_id`` changed in this transaction."""
    if not session.info.get(RUNNING):  # The sync's own writes never schedule another sync.
        session.info.setdefault(TOUCHED, {}).setdefault(plan_id, set()).add(kind)


def _row_changed(_mapper, connection, target, *, inserted: bool = False, deleted: bool = False) -> None:
    session = object_session(target)
    if session is None or session.info.get(RUNNING):
        return
    state = inspect(target)
    if "plan_id" in state.dict:
        plan_id = state.dict["plan_id"]
    elif state.dict.get("plan") is not None:  # Inserted through the plan's collection.
        plan_id = state.dict["plan"].id
    elif inserted:
        plan_id = None  # Never set: a legacy shared account.
    else:  # Unloaded: read it with Core; the ORM must not load inside a flush.
        table = type(target).__table__
        row_id = state.identity[0] if state.identity else state.dict.get("id")
        plan_id = connection.execute(select(table.c.plan_id).where(table.c.id == row_id)).scalar()
    if plan_id is not None:  # None: a legacy shared account.
        mark_plan_changed(session, plan_id, ALL_KINDS if deleted else MODEL_KINDS[type(target)])


def _plan_updated(_mapper, _connection, target: Plan) -> None:
    session = object_session(target)
    attrs = inspect(target).attrs
    if session is not None and any(attrs[field].history.has_changes() for field in PLAN_FIELDS):
        mark_plan_changed(session, target.id, PLAN_KIND)


def _row_inserted(mapper, connection, target) -> None:
    _row_changed(mapper, connection, target, inserted=True)


def _row_deleted(mapper, connection, target) -> None:
    _row_changed(mapper, connection, target, deleted=True)


for _model in MODEL_KINDS:
    event.listen(_model, "after_insert", _row_inserted)
    event.listen(_model, "after_update", _row_changed)
    # Deletes are seen before the row is gone, while its plan can still be read.
    event.listen(_model, "before_delete", _row_deleted)
# A new plan has no scenarios; deleting a Main releases them first.
event.listen(Plan, "after_update", _plan_updated)


@event.listens_for(Session, "before_commit")
def _sync_scenarios(session: Session) -> None:
    if session.info.get(RUNNING) or session.in_nested_transaction():
        return
    # before_commit runs ahead of the commit's own flush.
    if session.new or session.dirty or session.deleted:
        session.flush()
    touched = session.info.pop(TOUCHED, None)
    if not touched:
        return
    session.info[RUNNING] = True
    from app.scenarios.sync import (  # noqa: PLC0415 - app.scenarios.sync imports this module
        sync_touched,
    )
    sync_touched(session, touched)


@event.listens_for(Session, "after_transaction_end")
def _reset(session: Session, transaction) -> None:
    if transaction.parent is None:
        session.info.pop(TOUCHED, None)
        session.info.pop(RUNNING, None)

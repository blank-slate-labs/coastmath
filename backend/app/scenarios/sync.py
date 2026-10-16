"""Scenario sync: Main's changes flow into a scenario except its own overrides.

For every inheritable field the sync compares three canonical values: the
link's base ``B`` (Main's value at the last sync, in the scenario's IDs),
Main's current value ``M`` (translated) and the scenario's value ``S``.

- ``M`` unmappable (it names a Main row the scenario removed): ``S`` and
  ``B`` stay as they are, so the field retries next time; it is reported in
  ``skipped``.
- ``S == B`` (inherited) and ``M != B``: ``S`` becomes ``M``.
- ``S != B`` (overridden): ``S`` is kept.
- Then ``B`` becomes ``M``. Setting a value back to Main's makes it inherited
  again.

Rows Main added are created with fresh IDs (all allocated before any is
written, so references between them translate). Rows Main deleted are
deleted from the scenario only when unchanged and unreferenced there;
otherwise they stay as the scenario's own. Rows the scenario deleted are
"removed": Main's later changes to them are ignored until restored. Whole
lists are compared and replaced as a unit. The sync is state-based and
idempotent: running it twice changes nothing the second time.
"""
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, union_all
from sqlalchemy.orm import Session

from app import errors
from app.access import plan_editable
from app.clock import utcnow
from app.models.financial_connection import FinancialBalanceLink, FinancialSpendingFeed
from app.models.plan import Plan
from app.models.plan_link import PlanLink
from app.models.user import User
from app.routers.helpers import load_plan_data
from app.safe_logging import exception_summary
from app.scenarios.hooks import ALL_KINDS
from app.scenarios.registry import (
    KINDS,
    LIST_KINDS,
    PLAN_COLUMNS,
    PLAN_FIELDS,
    PLAN_KIND,
    ROW_KIND_NAMES,
    ROW_KINDS,
    Kind,
)
from app.scenarios.values import IdentityMap, canon_column, decanon, display, strings_in

logger = logging.getLogger(__name__)

OK = "ok"
NEEDS_REVIEW = "needs_review"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def validation_error(message: str, field: str = "kind") -> HTTPException:
    return errors.validation_error(message, field)


def _canon_row(kind: Kind, row) -> dict[str, Any]:
    return {name: canon_column(column, getattr(row, name)) for name, column in kind.columns.items()}


def _canon_plan(plan: Plan) -> dict[str, Any]:
    return {name: canon_column(column, getattr(plan, name)) for name, column in PLAN_COLUMNS.items()}


def _list_items(kind: Kind, rows) -> list[dict[str, Any]]:
    """A whole list's content without row identities, in rank order."""
    items = [_canon_row(kind, row) for row in rows]
    return sorted(items, key=lambda item: (item.get(kind.rank) or 0, json.dumps(item, sort_keys=True)))


class _Sync:
    """One scenario's merge with its Main plan."""

    def __init__(self, db: Session, main: Plan, scenario: Plan):
        self.db, self.main, self.scenario = db, main, scenario
        self.links: dict[tuple[str, uuid.UUID], PlanLink] = {
            (link.kind, link.main_row_id): link
            for link in db.query(PlanLink).filter(PlanLink.scenario_plan_id == scenario.id).populate_existing().all()
        }
        self.main_rows: dict[str, dict[uuid.UUID, Any]] = {}
        self.scenario_rows: dict[str, dict[uuid.UUID, Any]] = {}
        self.skipped: list[dict] = []
        self.wrote = False
        self.idmap = IdentityMap({})
        self.other_ids: set[uuid.UUID] = set()

    # -- loading and identity -------------------------------------------------
    def load(self, kinds) -> None:
        for kind in kinds:
            self.main_rows[kind.name] = {row.id: row for row in kind.rows(self.db, self.main.id)}
            self.scenario_rows[kind.name] = {row.id: row for row in kind.rows(self.db, self.scenario.id)}
        # Other kinds' rows only need to exist to be referenced (one query).
        others = [kind for kind in ROW_KINDS if kind.name not in self.scenario_rows]
        self.other_ids: set[uuid.UUID] = set()
        if others:
            query = union_all(*(select(kind.model.id).where(kind.model.plan_id == self.scenario.id) for kind in others))
            self.other_ids = set(self.db.execute(query).scalars())

    def build_map(self, extra: dict[uuid.UUID, uuid.UUID] | None = None) -> IdentityMap:
        pairs = {self.main.id: self.scenario.id}
        known: set[uuid.UUID] = set()
        for (kind, main_id), link in self.links.items():
            if kind not in ROW_KIND_NAMES:
                continue
            known.add(main_id)
            rows = self.scenario_rows.get(kind, self.other_ids)
            exists = link.scenario_row_id is not None and link.scenario_row_id in rows
            if exists:
                pairs[main_id] = link.scenario_row_id
        for rows in self.main_rows.values():
            known.update(rows)
        pairs.update(extra or {})
        self.idmap = IdentityMap(pairs, known)
        return self.idmap

    def main_name(self, main_id: str) -> tuple[Kind | None, str]:
        """The kind and name of a Main row, for messages."""
        row_id = uuid.UUID(main_id)
        for name, rows in self.main_rows.items():
            if row_id in rows:
                return KINDS[name], KINDS[name].row_name(rows[row_id])
        for kind in ROW_KINDS:
            row = self.db.get(kind.model, row_id)
            if row is not None:
                return kind, kind.row_name(row)
        return None, "a removed item"

    def skip(self, kind: str, main_id, name: str, field: str | None, reason: str) -> None:
        self.skipped.append({"kind": kind, "parent_row_id": str(main_id), "name": name, "field": field, "reason": reason})

    def unmappable_reason(self, missing: set[str]) -> str:
        kind, name = self.main_name(sorted(missing)[0])
        noun = kind.noun if kind else "item"
        return f"It uses the {noun} “{name}”, which this scenario removed. Restore that {noun} to bring it in."

    # -- merge ----------------------------------------------------------------
    def merge_fields(self, kind_name: str, columns: dict, main_obj, target, link: PlanLink, name: str) -> None:
        base = dict(link.base or {})
        changed = False
        for field, column in columns.items():
            main_value, missing = self.idmap.translate(canon_column(column, getattr(main_obj, field)))
            if missing:
                self.skip(kind_name, link.main_row_id, name, field, self.unmappable_reason(missing))
                continue
            current = canon_column(column, getattr(target, field))
            if field in base and current == base[field] and main_value != base[field]:
                setattr(target, field, decanon(column, main_value))
                self.wrote = True
            if field not in base or base[field] != main_value:
                base[field] = main_value
                changed = True
        if changed:
            link.base = base

    def new_rows(self, kinds) -> list[tuple[Kind, Any, PlanLink, dict]]:
        """Main rows without a link, with their translated values; unmappable ones are skipped."""
        candidates: dict[uuid.UUID, tuple[Kind, Any, PlanLink]] = {}
        for kind in kinds:
            for main_id, row in self.main_rows[kind.name].items():
                if (kind.name, main_id) in self.links:
                    continue
                if kind.name == "spouse" and self.scenario_rows["spouse"]:
                    self.skip("spouse", main_id, kind.row_name(row), None,
                              "This scenario already has its own partner, so Main's partner was not added.")
                    continue
                link = PlanLink(scenario_plan_id=self.scenario.id, kind=kind.name, main_row_id=main_id,
                                scenario_row_id=uuid.uuid4(), base={})
                candidates[main_id] = (kind, row, link)
        while True:
            self.build_map({main_id: link.scenario_row_id for main_id, (_k, _r, link) in candidates.items()})
            blocked = {}
            for main_id, (kind, row, _link) in candidates.items():
                for field, column in kind.columns.items():
                    _value, missing = self.idmap.translate(canon_column(column, getattr(row, field)))
                    if missing:
                        blocked[main_id] = (field, missing)
                        break
            if not blocked:
                break
            for main_id, (field, missing) in blocked.items():
                kind, row, _link = candidates.pop(main_id)
                self.skip(kind.name, main_id, kind.row_name(row), field, "Not added. " + self.unmappable_reason(missing))
        result = []
        for kind, row, link in candidates.values():
            values = {field: self.idmap.translate(canon_column(column, getattr(row, field)))[0]
                      for field, column in kind.columns.items()}
            result.append((kind, row, link, values))
        return result

    def create_rows(self, created: list[tuple[Kind, Any, PlanLink, dict]]) -> None:
        for kind in ROW_KINDS:
            batch = [(link, values) for k, _row, link, values in created if k is kind]
            if not batch:
                continue
            relative = {}
            for link, values in batch:
                attrs = {field: decanon(kind.columns[field], value) for field, value in values.items()}
                if kind.name == "milestone":
                    # Anchors may be created in the same batch, after their dependents.
                    relative[link.scenario_row_id] = attrs.pop("relative_to_id", None)
                if "user_id" in kind.excluded and hasattr(kind.model, "user_id"):
                    attrs["user_id"] = self.scenario.user_id
                row = kind.model(id=link.scenario_row_id, plan_id=self.scenario.id, **attrs)
                self.db.add(row)
                self.scenario_rows[kind.name][row.id] = row
                link.base = values
                self.db.add(link)
                self.links[(kind.name, link.main_row_id)] = link
            self.db.flush()
            if any(relative.values()):
                for row_id, anchor in relative.items():
                    self.scenario_rows["milestone"][row_id].relative_to_id = anchor
                self.db.flush()
            self.wrote = True

    def sync_rows(self, kinds) -> None:
        for kind in kinds:
            main_rows, scenario_rows = self.main_rows[kind.name], self.scenario_rows[kind.name]
            for (name, main_id), link in list(self.links.items()):
                if name != kind.name or main_id not in main_rows:
                    continue
                if link.scenario_row_id is None:
                    continue
                if link.scenario_row_id not in scenario_rows:
                    # The scenario deleted its copy: Main's changes no longer apply.
                    link.scenario_row_id = None
                    continue
                main_row = main_rows[main_id]
                self.merge_fields(kind.name, kind.columns, main_row, scenario_rows[link.scenario_row_id], link,
                                  kind.row_name(main_row))
        self.db.flush()

    def sync_lists(self, kinds) -> None:
        for kind in kinds:
            main_items, missing = self.idmap.translate(_list_items(kind, kind.rows(self.db, self.main.id)))
            if missing:
                self.skip(kind.name, self.main.id, kind.label, None, self.unmappable_reason(missing))
                continue
            current_rows = kind.rows(self.db, self.scenario.id)
            link = self.links.get((kind.name, self.main.id))
            if link is None:
                link = PlanLink(scenario_plan_id=self.scenario.id, kind=kind.name, main_row_id=self.main.id,
                                scenario_row_id=self.scenario.id, base={})
                self.db.add(link)
                self.links[(kind.name, self.main.id)] = link
            elif _list_items(kind, current_rows) == link.base.get("items") and main_items != link.base.get("items"):
                self.replace_list(kind, current_rows, main_items)
            if link.base.get("items") != main_items:
                link.base = {"items": main_items}

    def replace_list(self, kind: Kind, current_rows, items: list[dict]) -> None:
        for row in current_rows:
            self.db.delete(row)
        self.db.flush()
        for item in items:
            self.db.add(kind.model(plan_id=self.scenario.id, **{
                field: decanon(kind.columns[field], value) for field, value in item.items()}))
        if kind.name == "priorities":
            # An open allocation editor on the scenario gets the 409 review.
            self.scenario.priorities_revision += 1
        self.db.flush()
        self.wrote = True

    def sync_plan(self) -> None:
        link = self.links.get((PLAN_KIND, self.main.id))
        if link is None:
            link = PlanLink(scenario_plan_id=self.scenario.id, kind=PLAN_KIND, main_row_id=self.main.id,
                            scenario_row_id=self.scenario.id, base={})
            self.db.add(link)
            self.links[(PLAN_KIND, self.main.id)] = link
        self.merge_fields(PLAN_KIND, PLAN_COLUMNS, self.main, self.scenario, link, self.main.name)

    # -- rows Main deleted ----------------------------------------------------
    def references(self, excluded: set[uuid.UUID]) -> set[str]:
        """Every ID string the scenario's rows and settings use, except rows in ``excluded``."""
        found: set[str] = set()
        for kind in KINDS.values():
            for row in kind.rows(self.db, self.scenario.id):
                if row.id in excluded:
                    continue
                for field, column in kind.columns.items():
                    found |= strings_in(canon_column(column, getattr(row, field)))
        for field, column in PLAN_COLUMNS.items():
            found |= strings_in(canon_column(column, getattr(self.scenario, field)))
        for link in self.db.query(FinancialBalanceLink).filter(FinancialBalanceLink.plan_id == self.scenario.id):
            found |= {str(value) for value in (link.account_id, link.liability_id) if value}
        for feed in self.db.query(FinancialSpendingFeed).filter(FinancialSpendingFeed.plan_id == self.scenario.id):
            found |= {str(value) for value in (feed.essential_expense_id, feed.discretionary_expense_id) if value}
        return found

    def remove_deleted(self, kinds) -> None:
        names = {kind.name for kind in kinds}
        gone = [link for (kind, main_id), link in self.links.items()
                if kind in names and main_id not in self.main_rows[kind]]
        candidates: dict[uuid.UUID, tuple[Kind, Any, PlanLink]] = {}
        changed: list[tuple[Kind, Any, PlanLink]] = []
        for link in gone:
            kind = KINDS[link.kind]
            row = self.scenario_rows[kind.name].get(link.scenario_row_id) if link.scenario_row_id else None
            if row is None:
                self.db.delete(link)
                del self.links[(link.kind, link.main_row_id)]
                continue
            base = link.base or {}
            unchanged = all(canon_column(column, getattr(row, field)) == base[field]
                            for field, column in kind.columns.items() if field in base)
            if unchanged:
                candidates[row.id] = (kind, row, link)
            else:
                changed.append((kind, row, link))
        if not gone:
            return
        deleting = set(candidates)
        while deleting:
            used = self.references(deleting)
            keep = {row_id for row_id in deleting if str(row_id) in used}
            if not keep:
                break
            deleting -= keep
        for kind, row, link in changed:
            self.keep(kind, row, link, "Main deleted it. This scenario changed it, so it was kept here.")
        for row_id, (kind, row, link) in candidates.items():
            if row_id not in deleting:
                self.keep(kind, row, link, "Main deleted it. Something else in this scenario uses it, so it was kept here.")
        for kind in reversed(ROW_KINDS):
            for row_id, (row_kind, row, link) in candidates.items():
                if row_kind is kind and row_id in deleting:
                    self.db.delete(row)
                    self.db.delete(link)
                    del self.links[(link.kind, link.main_row_id)]
                    del self.scenario_rows[kind.name][row_id]
                    self.wrote = True
            self.db.flush()

    def keep(self, kind: Kind, row, link: PlanLink, reason: str) -> None:
        self.skip(kind.name, link.main_row_id, kind.row_name(row), None, reason)
        self.db.delete(link)
        del self.links[(link.kind, link.main_row_id)]

    # -- run ------------------------------------------------------------------
    def run(self, kind_names: set[str] | None, *, recheck: bool = False) -> None:
        names = set(KINDS) | {PLAN_KIND} if kind_names is None else set(kind_names)
        self.wrote = recheck
        row_kinds = [kind for kind in ROW_KINDS if kind.name in names]
        self.load(row_kinds)
        created = self.new_rows(row_kinds)
        self.create_rows(created)
        self.build_map()
        self.sync_rows(row_kinds)
        self.sync_lists([kind for kind in LIST_KINDS if kind.name in names])
        if PLAN_KIND in names:
            self.sync_plan()
        self.remove_deleted(row_kinds)
        self.db.flush()
        self.record(names)

    def record(self, names: set[str]) -> None:
        previous = self.scenario.scenario_sync or {}
        kept = [item for item in previous.get("skipped") or [] if item.get("kind") not in names]
        review = previous.get("review")
        if self.wrote or "review" not in previous:
            review = review_problem(self.db, self.scenario)
        skipped = kept + self.skipped
        # A completed sync clears an earlier failure ("failed").
        self.scenario.scenario_sync = {
            "status": NEEDS_REVIEW if skipped or review else OK,
            "synced_at": _now(),
            "skipped": skipped,
            "review": review,
        }


def review_problem(db: Session, scenario: Plan) -> str | None:
    """Why the merged scenario can't be projected, using the projection's own checks."""
    db.flush()
    db.expire(scenario)
    try:
        load_plan_data(scenario.id, db.get(User, scenario.user_id), db)
    except HTTPException as exc:
        error = exc.detail.get("error", {}) if isinstance(exc.detail, dict) else {}
        return f"After Main's latest changes this scenario needs review: {error.get('message') or 'it cannot be projected'}"
    except Exception as exc:  # The check must never block Main's save.
        logger.warning("scenario review check failed for plan %s: %s", scenario.id, exception_summary(exc))
        return "After Main's latest changes this scenario could not be checked. Review it before relying on it."
    return None


def sync_scenario(db: Session, main: Plan, scenario: Plan, kinds: set[str] | None = None, *,
                  recheck: bool = False) -> None:
    """Merge Main's current state into the scenario (``kinds``: only those kinds).

    ``recheck`` repeats the projection check even when the merge changes nothing.
    """
    _Sync(db, main, scenario).run(kinds, recheck=recheck)


def sync_failed(scenario: Plan, main: Plan) -> None:
    previous = scenario.scenario_sync or {}
    scenario.scenario_sync = {
        **previous,
        "status": NEEDS_REVIEW,
        "failed": "Main's latest changes could not be applied to this scenario. Use Sync now to try again.",
    }


def sync_guarded(db: Session, main: Plan, scenario: Plan, kinds: set[str] | None = None) -> bool:
    """Sync inside a savepoint: a failure rolls back only this scenario and marks it for review."""
    try:
        with db.begin_nested():
            sync_scenario(db, main, scenario, kinds)
        return True
    except Exception as exc:
        logger.warning("scenario sync failed for plan %s: %s", scenario.id, exception_summary(exc))
        sync_failed(scenario, main)
        return False


def sync_touched(db: Session, touched: dict[uuid.UUID, set[str]]) -> None:
    """Sync every editable scenario of the Main plans changed in this transaction.

    Locks Main, then its scenarios in ID order; scenario writes never lock
    Main, so a Main save and a scenario save cannot deadlock.
    """
    with db.no_autoflush:
        parents = sorted({row[0] for row in db.query(Plan.parent_plan_id).filter(
            Plan.parent_plan_id.in_(list(touched))).all()})
    for main_id in parents:
        main = db.query(Plan).filter(Plan.id == main_id).with_for_update().populate_existing().one_or_none()
        if main is None or main.parent_plan_id is not None:
            continue
        scenarios = (
            db.query(Plan)
            .filter(Plan.parent_plan_id == main.id, Plan.user_id == main.user_id, Plan.client_id == main.client_id)
            .order_by(Plan.id).with_for_update().populate_existing().all()
        )
        owner = db.get(User, main.user_id)
        now = utcnow()
        for scenario in scenarios:
            # Archived or read-only scenarios catch up on their next sync.
            if plan_editable(scenario, owner, now):
                kinds = touched[main_id]
                sync_guarded(db, main, scenario, None if ALL_KINDS in kinds else kinds)


# ---------------------------------------------------------------------------
# Scenario creation and the inheritance API
# ---------------------------------------------------------------------------
def link_new_scenario(db: Session, main: Plan, scenario: Plan, pairs: dict[str, list[tuple[Any, Any]]]) -> None:
    """Record a freshly copied scenario's identities with the copied values as base."""
    db.flush()
    db.add(PlanLink(scenario_plan_id=scenario.id, kind=PLAN_KIND, main_row_id=main.id,
                    scenario_row_id=scenario.id, base=_canon_plan(scenario)))
    for kind in KINDS.values():
        rows = pairs.get(kind.name, [])
        if kind.whole_list:
            db.add(PlanLink(scenario_plan_id=scenario.id, kind=kind.name, main_row_id=main.id,
                            scenario_row_id=scenario.id, base={"items": _list_items(kind, [new for _old, new in rows])}))
            continue
        for old, new in rows:
            db.add(PlanLink(scenario_plan_id=scenario.id, kind=kind.name, main_row_id=old.id,
                            scenario_row_id=new.id, base=_canon_row(kind, new)))
    scenario.scenario_sync = {"status": OK, "synced_at": _now(), "skipped": [], "review": None}
    db.flush()


def parent_of(db: Session, scenario: Plan) -> Plan | None:
    if scenario.parent_plan_id is None:
        return None
    return db.query(Plan).filter(Plan.id == scenario.parent_plan_id, Plan.user_id == scenario.user_id).first()


def _field_entry(column, field: str, value, parent_value) -> dict:
    return {"field": field, "value": display(column, value), "parent_value": display(column, parent_value)}


def inheritance(db: Session, scenario: Plan) -> dict:
    """The scenario's inheritance state for ``GET /plans/{id}/inheritance``."""
    main = parent_of(db, scenario)
    record = scenario.scenario_sync or {}
    result = {
        "plan_id": scenario.id, "parent_plan_id": None, "parent_name": None, "status": OK,
        "synced_at": None, "plan_fields": [], "items": [], "skipped": [],
    }
    if main is None:
        return result
    state = _Sync(db, main, scenario)
    state.load(ROW_KINDS)
    idmap = state.build_map()
    result.update(parent_plan_id=main.id, parent_name=main.name, status=record.get("status") or OK,
                  synced_at=record.get("synced_at"))
    plan_link = state.links.get((PLAN_KIND, main.id))
    plan_base = plan_link.base if plan_link else {}
    for field, column in PLAN_COLUMNS.items():
        value = canon_column(column, getattr(scenario, field))
        if field in plan_base and value != plan_base[field]:
            parent_value = idmap.translate(canon_column(column, getattr(main, field)))[0]
            result["plan_fields"].append(_field_entry(column, field, value, parent_value))
    items = result["items"]
    for kind in ROW_KINDS:
        main_rows, scenario_rows = state.main_rows[kind.name], state.scenario_rows[kind.name]
        by_scenario_row = {link.scenario_row_id: link for (name, _id), link in state.links.items()
                           if name == kind.name and link.scenario_row_id is not None}
        for row in sorted(scenario_rows.values(), key=lambda r: (kind.row_name(r).lower(), str(r.id))):
            link = by_scenario_row.get(row.id)
            if link is None or link.main_row_id not in main_rows:
                items.append({"kind": kind.name, "row_id": row.id, "parent_row_id": None,
                              "name": kind.row_name(row), "state": "scenario_only", "fields": []})
                continue
            main_row, base = main_rows[link.main_row_id], link.base or {}
            fields = []
            for field, column in kind.columns.items():
                value = canon_column(column, getattr(row, field))
                if field in base and value != base[field]:
                    parent_value = idmap.translate(canon_column(column, getattr(main_row, field)))[0]
                    fields.append(_field_entry(column, field, value, parent_value))
            items.append({"kind": kind.name, "row_id": row.id, "parent_row_id": link.main_row_id,
                          "name": kind.row_name(row), "state": "changed" if fields else "inherited", "fields": fields})
        for (name, main_id), link in state.links.items():
            if name != kind.name or main_id not in main_rows:
                continue
            if link.scenario_row_id is None or link.scenario_row_id not in scenario_rows:
                items.append({"kind": kind.name, "row_id": None, "parent_row_id": main_id,
                              "name": kind.row_name(main_rows[main_id]), "state": "removed", "fields": []})
    for kind in LIST_KINDS:
        link = state.links.get((kind.name, main.id))
        current = _list_items(kind, kind.rows(db, scenario.id))
        inherited = link is not None and current == link.base.get("items")
        items.append({"kind": kind.name, "row_id": None, "parent_row_id": None, "name": kind.label,
                      "state": "inherited" if inherited else "changed", "fields": []})
    result["skipped"] = list(record.get("skipped") or [])
    for problem in (record.get("failed"), record.get("review")):
        if problem:
            result["skipped"].append({"kind": PLAN_KIND, "parent_row_id": str(main.id), "name": scenario.name,
                                      "field": None, "reason": problem})
    return result


def _checked_fields(available, fields: list[str] | None, overridden: list[str]) -> list[str]:
    if fields is None:
        return overridden
    unknown = [field for field in fields if field not in available]
    if unknown:
        raise validation_error(f"“{unknown[0]}” is not a field this scenario inherits from Main.", "fields")
    return list(dict.fromkeys(fields))


def _apply(state: _Sync, kind_name: str, columns: dict, main_obj, target, link: PlanLink, fields: list[str]) -> None:
    base = dict(link.base or {})
    for field in fields:
        column = columns[field]
        value, missing = state.idmap.translate(canon_column(column, getattr(main_obj, field)))
        if missing:
            kind, name = state.main_name(sorted(missing)[0])
            noun = kind.noun if kind else "item"
            raise validation_error(f"Restore the {noun} “{name}” first.", field)
        setattr(target, field, decanon(column, value))
        base[field] = value
    link.base = base


def reset(db: Session, scenario: Plan, kind_name: str, row_id: uuid.UUID | None, fields: list[str] | None,
          expected_revision: int | None) -> None:
    """Make the scenario's value(s) follow Main again."""
    main = require_main(db, scenario)
    state = _Sync(db, main, scenario)
    state.load(ROW_KINDS)
    state.build_map()
    if kind_name == PLAN_KIND:
        link = state.links.get((PLAN_KIND, main.id))
        if link is None:
            raise validation_error("This scenario has no record of Main's plan settings. Use Sync now first.")
        overridden = [field for field, column in PLAN_COLUMNS.items()
                      if field in link.base and canon_column(column, getattr(scenario, field)) != link.base[field]]
        _apply(state, PLAN_KIND, PLAN_COLUMNS, main, scenario, link, _checked_fields(PLAN_FIELDS, fields, overridden))
    elif kind_name in ROW_KIND_NAMES:
        kind = KINDS[kind_name]
        link = next((link for (name, _id), link in state.links.items()
                     if name == kind_name and row_id is not None and link.scenario_row_id == row_id), None)
        row = state.scenario_rows[kind_name].get(row_id) if row_id else None
        main_row = state.main_rows[kind_name].get(link.main_row_id) if link else None
        if row is None or main_row is None:
            raise validation_error("Only items that follow Main can be reset; this one exists only in this scenario.",
                                   "row_id")
        base = link.base or {}
        overridden = [field for field, column in kind.columns.items()
                      if field in base and canon_column(column, getattr(row, field)) != base[field]]
        _apply(state, kind_name, kind.columns, main_row, row, link, _checked_fields(kind.fields, fields, overridden))
    elif kind_name in KINDS:
        kind = KINDS[kind_name]
        if kind_name == "priorities":
            if expected_revision is None:
                raise validation_error("Resetting savings rules needs expected_revision.", "expected_revision")
            if scenario.priorities_revision != expected_revision:
                raise errors.api_error(
                    409, "CONFLICT",
                    "Allocation changed since you started editing. Review the latest rules before resetting; nothing was applied.",
                    [{"field": "expected_revision", "reason": "stale allocation revision"}],
                )
        items, missing = state.idmap.translate(_list_items(kind, kind.rows(db, main.id)))
        if missing:
            found, name = state.main_name(sorted(missing)[0])
            noun = found.noun if found else "item"
            raise validation_error(f"Restore the {noun} “{name}” first.")
        link = state.links.get((kind_name, main.id))
        if link is None:
            link = PlanLink(scenario_plan_id=scenario.id, kind=kind_name, main_row_id=main.id,
                            scenario_row_id=scenario.id, base={})
            db.add(link)
        state.replace_list(kind, kind.rows(db, scenario.id), items)
        link.base = {"items": items}
    else:
        raise validation_error(f"Unknown kind “{kind_name}”.")
    db.flush()
    sync_scenario(db, main, scenario, recheck=True)


def restore(db: Session, scenario: Plan, kind_name: str, parent_row_id: uuid.UUID) -> None:
    """Bring back a Main row the scenario removed, from Main's current values."""
    main = require_main(db, scenario)
    if kind_name not in ROW_KIND_NAMES:
        raise validation_error("Only removed rows can be restored.")
    kind = KINDS[kind_name]
    state = _Sync(db, main, scenario)
    state.load(ROW_KINDS)
    state.build_map()
    link = state.links.get((kind_name, parent_row_id))
    main_row = state.main_rows[kind_name].get(parent_row_id)
    removed = link is not None and (link.scenario_row_id is None
                                    or link.scenario_row_id not in state.scenario_rows[kind_name])
    if not removed or main_row is None:
        raise validation_error("That item was not removed from this scenario.", "parent_row_id")
    if kind_name == "spouse" and state.scenario_rows["spouse"]:
        raise validation_error("This scenario already has a partner. Remove it before restoring Main's.", "parent_row_id")
    values = {}
    for field, column in kind.columns.items():
        value, missing = state.idmap.translate(canon_column(column, getattr(main_row, field)))
        if missing:
            found, name = state.main_name(sorted(missing)[0])
            noun = found.noun if found else "item"
            raise validation_error(f"Restore the {noun} “{name}” first.", "parent_row_id")
        values[field] = value
    link.scenario_row_id = uuid.uuid4()
    attrs = {field: decanon(kind.columns[field], value) for field, value in values.items()}
    if hasattr(kind.model, "user_id"):
        attrs["user_id"] = scenario.user_id
    db.add(kind.model(id=link.scenario_row_id, plan_id=scenario.id, **attrs))
    link.base = values
    db.flush()
    sync_scenario(db, main, scenario, recheck=True)


def detach(db: Session, scenario: Plan) -> None:
    """The scenario keeps its current values and becomes an independent plan."""
    db.query(PlanLink).filter(PlanLink.scenario_plan_id == scenario.id).delete(synchronize_session=False)
    scenario.parent_plan_id = None
    scenario.scenario_sync = None


def release_scenarios(db: Session, main_id: uuid.UUID) -> None:
    """Before Main is deleted: its scenarios become independent plans."""
    scenario_ids = [row[0] for row in db.query(Plan.id).filter(Plan.parent_plan_id == main_id).all()]
    if scenario_ids:
        db.query(PlanLink).filter(PlanLink.scenario_plan_id.in_(scenario_ids)).delete(synchronize_session=False)
        db.query(Plan).filter(Plan.id.in_(scenario_ids)).update(
            {Plan.parent_plan_id: None, Plan.scenario_sync: None}, synchronize_session="fetch")
    # A deleted scenario's links go with it (explicit for databases without cascades).
    db.query(PlanLink).filter(PlanLink.scenario_plan_id == main_id).delete(synchronize_session=False)


def require_main(db: Session, scenario: Plan) -> Plan:
    main = parent_of(db, scenario)
    if main is None:
        raise validation_error("This plan is not a scenario.", "plan_id")
    return main

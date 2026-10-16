"""Canonical column values and plan identity translation.

Canonical values are what scenario sync compares and stores as a link's
``base``: ``Decimal`` (and floats in numeric columns) as normalized strings,
never floats, so stored money never looks changed through rounding; UUIDs as
strings; dates and datetimes as ISO strings; JSON settings as stored, with any
UUIDs inside as strings. Everything is JSON-serializable.

``IdentityMap`` maps one plan's row IDs to another plan's: plain duplication
uses ``remap`` on ORM values and ``copy_plan``; scenario sync uses
``translate`` on canonical values, which also reports references to rows
that have no counterpart (unmappable).
"""
import uuid
from collections.abc import Iterable
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, Float, Numeric, Uuid, inspect
from sqlalchemy.orm import Session

from app.models.plan import Plan


def _decimal_text(value: Any) -> str:
    number = value if isinstance(value, Decimal) else Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    return "0" if number == 0 else format(number.normalize(), "f")


def is_decimal_column(column) -> bool:
    return isinstance(column.type, Numeric) and not isinstance(column.type, Float)


def canon(value: Any) -> Any:
    """Canonical form of a value with no column type (JSON contents)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(canon(key)): canon(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canon(item) for item in value]
    return str(value)


def canon_column(column, value: Any) -> Any:
    if value is None:
        return None
    if is_decimal_column(column) and not isinstance(value, bool):
        return _decimal_text(value)
    return canon(value)


def decanon(column, value: Any) -> Any:
    """The ORM attribute value for a canonical value of ``column``."""
    if value is None:
        return None
    if is_decimal_column(column):
        return Decimal(value)
    if isinstance(column.type, Uuid):
        return uuid.UUID(value)
    if isinstance(column.type, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(column.type, Date):
        return date.fromisoformat(value)
    return deepcopy(value)


def display(column, value: Any) -> Any:
    """A canonical value for the inheritance API: numbers as JSON numbers."""
    if value is not None and is_decimal_column(column):
        number = Decimal(value)
        return int(number) if number == number.to_integral_value() else float(number)
    return value


def strings_in(value: Any) -> set[str]:
    """Every string, including dict keys, inside a canonical value."""
    found: set[str] = set()
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            found.add(item)
        elif isinstance(item, dict):
            found.update(str(key) for key in item)
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return found


class IdentityMap:
    """Row IDs of one plan mapped to another's.

    ``known`` lists every row ID of the source plan. A known ID without a
    mapping is unmappable; any other ID (a tax jurisdiction, a legacy
    account) refers outside the plan and passes through unchanged.
    """

    def __init__(self, pairs: dict[uuid.UUID, uuid.UUID], known: Iterable[uuid.UUID] = ()):
        self.ids = dict(pairs)
        self.text = {str(old): str(new) for old, new in self.ids.items()}
        self.known = {str(value) for value in known} | set(self.text)

    def remap(self, value: Any) -> Any:
        """Duplicate's mapping of an ORM value (UUIDs, and ID strings in JSON)."""
        if isinstance(value, uuid.UUID):
            return self.ids.get(value, value)
        if isinstance(value, dict):
            return {self.text.get(key, key): self.remap(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.remap(item) for item in value]
        if isinstance(value, str):
            return self.text.get(value, value)
        return deepcopy(value)

    def translate(self, value: Any) -> tuple[Any, set[str]]:
        """A canonical value in the target plan's IDs, and the unmappable IDs it uses."""
        missing: set[str] = set()

        def walk(item):
            if isinstance(item, str):
                if item in self.text:
                    return self.text[item]
                if item in self.known:
                    missing.add(item)
                return item
            if isinstance(item, dict):
                return {walk(key): walk(child) for key, child in item.items()}
            if isinstance(item, list):
                return [walk(child) for child in item]
            return item

        return walk(value), missing


def copy_row(row, identities: IdentityMap):
    """A new ORM row with every column remapped, except ``created_at``."""
    return type(row)(**{
        column.key: identities.remap(getattr(row, column.key))
        for column in inspect(type(row)).columns
        if column.key != "created_at"
    })


# Plan collections copied by duplication, in insertion order, with their
# scenario kinds (app.scenarios.registry).
PLAN_COLLECTIONS = (
    ("milestones", "milestone"), ("income_streams", "income"), ("real_assets", "real_asset"),
    ("expenses", "expense"), ("priorities", "priorities"), ("drawdown_order", "drawdown"),
    ("assumption_curves", "assumption_curve"), ("liabilities", "liability"),
    ("charity_entities", "charity"), ("residency_periods", "residency"),
)


def copy_plan(db: Session, source: Plan, accounts: list, *, client_id: uuid.UUID | None, name: str,
              parent_plan_id: uuid.UUID | None = None) -> tuple[Plan, dict[str, list[tuple[Any, Any]]]]:
    """Copy a plan with its accounts and children, allocating every identity first.

    Milestone, income and property references (including those in JSON
    settings) point inside the new plan. Returns the copy and, per scenario
    kind, the (source row, copied row) pairs.
    """
    children = {key: list(getattr(source, key)) for key, _kind in PLAN_COLLECTIONS}
    records = [source, *accounts, *[row for rows in children.values() for row in rows]]
    if source.spouse is not None:
        records.append(source.spouse)
    identities = IdentityMap({row.id: uuid.uuid4() for row in records})

    copied = copy_row(source, identities)
    copied.client_id = client_id
    if client_id:
        copied.snapshot_conditions = {}
    copied.name = name
    copied.baseline_plan_id = None
    copied.priorities_revision = 0
    # The copy is a new, active plan with its own window.
    copied.archived_at = copied.edit_notice_seen_at = copied.edit_grace_ends_at = None
    # Only scenario creation links the copy to a Main plan.
    copied.parent_plan_id = parent_plan_id
    copied.scenario_sync = None
    # Flush the parent before the children, whose foreign keys refer to it.
    db.add(copied)
    db.flush()
    pairs: dict[str, list[tuple[Any, Any]]] = {"account": []}
    for account in accounts:
        cloned_account = copy_row(account, identities)
        cloned_account.plan_id = copied.id
        db.add(cloned_account)
        pairs["account"].append((account, cloned_account))
    db.flush()
    for key, kind in PLAN_COLLECTIONS:
        rows = children[key]
        cloned_rows = [copy_row(row, identities) for row in rows]
        pairs[kind] = list(zip(rows, cloned_rows, strict=True))
        # Relative milestones can precede their anchors in display order.
        relative_ids = {}
        if key == "milestones":
            for row in cloned_rows:
                relative_ids[row.id] = row.relative_to_id
                row.relative_to_id = None
        setattr(copied, key, cloned_rows)
        db.flush()
        if relative_ids:
            for row in cloned_rows:
                row.relative_to_id = relative_ids[row.id]
            db.flush()
    pairs["spouse"] = []
    if source.spouse is not None:
        copied.spouse = copy_row(source.spouse, identities)
        pairs["spouse"].append((source.spouse, copied.spouse))
    return copied, pairs

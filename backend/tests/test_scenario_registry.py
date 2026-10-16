"""The scenario kind registry covers every plan-scoped table; canonical values are exact."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Uuid, inspect

from app.db import Base
from app.models.plan import Plan
from app.scenarios.registry import (
    KINDS,
    NOT_INHERITED,
    PLAN_EXCLUDED,
    PLAN_FIELDS,
    ROW_EXCLUDED,
    inherited_tables,
)
from app.scenarios.values import IdentityMap, canon, canon_column, decanon


def _plan_scoped_tables() -> set[str]:
    return {
        table.name for table in Base.metadata.sorted_tables
        if any(fk.column.table.name == "plans" for fk in table.foreign_keys)
    }


def test_every_plan_scoped_table_has_a_scenario_decision():
    scoped = _plan_scoped_tables()
    decided = inherited_tables() | set(NOT_INHERITED)
    assert scoped - decided == set(), "add a registry kind or a NOT_INHERITED entry with its reason"
    assert not set(NOT_INHERITED) & inherited_tables()
    assert set(NOT_INHERITED) <= scoped, "NOT_INHERITED lists a table that is not plan-scoped"


def test_inheritable_columns_exclude_identity_and_bookkeeping():
    assert set(PLAN_FIELDS).isdisjoint(PLAN_EXCLUDED)
    assert {"life_expectancy", "tax_settings", "spending_rules", "state_code", "plan_type"} <= set(PLAN_FIELDS)
    for kind in KINDS.values():
        assert set(kind.fields).isdisjoint(ROW_EXCLUDED), kind.name
        assert hasattr(kind.model, "plan_id"), kind.name
        # Every reference column holds a UUID, which is what translation maps.
        for column in inspect(kind.model).columns:
            if column.foreign_keys or column.key.endswith("_id"):
                assert isinstance(column.type, Uuid), (kind.name, column.key)
    # New columns are inherited without registry edits.
    assert "annual_amount" in KINDS["income"].fields and "growth_schedule" in KINDS["income"].fields
    assert "balance" in KINDS["account"].fields and "user_id" not in KINDS["account"].fields
    for column in inspect(Plan).columns:
        assert (column.key in PLAN_FIELDS) != (column.key in PLAN_EXCLUDED), column.key


def test_canonical_values_are_exact_and_json_ready():
    amount = KINDS["income"].columns["annual_amount"]
    assert canon_column(amount, Decimal("120000.00")) == canon_column(amount, 120000.0) == canon_column(amount, 120000) == "120000"
    assert canon_column(amount, Decimal("0.10")) == canon_column(amount, 0.1) == "0.1"
    assert canon_column(amount, Decimal("-0.00")) == "0"
    assert decanon(amount, "48000.5") == Decimal("48000.5")
    milestone = KINDS["income"].columns["start_milestone_id"]
    row_id = uuid.uuid4()
    assert decanon(milestone, canon_column(milestone, row_id)) == row_id
    trigger_date = KINDS["milestone"].columns["trigger_date"]
    assert decanon(trigger_date, canon_column(trigger_date, date(2030, 6, 1))) == date(2030, 6, 1)
    assert canon({"a": [uuid.UUID(int=1), Decimal("1.50")]}) == {"a": [str(uuid.UUID(int=1)), "1.5"]}


def test_translation_maps_ids_and_reports_unmappable_ones():
    linked, removed, outside = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    target = uuid.uuid4()
    idmap = IdentityMap({linked: target}, known={linked, removed})
    value = {"start_milestone_id": str(linked), str(linked): [str(outside)], "end": str(removed)}
    translated, missing = idmap.translate(value)
    assert translated == {"start_milestone_id": str(target), str(target): [str(outside)], "end": str(removed)}
    assert missing == {str(removed)}
    assert idmap.remap(linked) == target and idmap.remap(outside) == outside
    assert idmap.remap({str(linked): str(linked)}) == {str(target): str(target)}

"""Every value the API accepts for a checked column passes that column's check.

The SQLite suite builds tables from the models, so a value missing from a model
check fails here. tests/test_check_constraints_postgres.py keeps the model
checks equal to the migrated PostgreSQL ones.
"""
import re
import typing

import pytest
from sqlalchemy import CheckConstraint

import app.models  # noqa: F401 — registers every table
from app.db import Base
from app.schemas.account import AccountCreate, AccountUpdate
from app.schemas.assumption_curve import AssumptionCurveCreate, AssumptionCurveUpdate
from app.schemas.cash_flow_priority import CashFlowPriorityCreate
from app.schemas.charity import CharityEntityCreate, CharityEntityUpdate
from app.schemas.expense import ExpenseCreate, ExpenseUpdate
from app.schemas.income import IncomeCreate, IncomeUpdate
from app.schemas.liability import LiabilityCreate, LiabilityUpdate
from app.schemas.milestone import MilestoneCreate, MilestoneUpdate
from app.schemas.plan import PlanCreate, PlanUpdate
from app.schemas.real_asset import RealAssetCreate, RealAssetUpdate
from app.schemas.tax_jurisdiction import TaxJurisdictionCreate, TaxJurisdictionUpdate

# The request schemas whose fields are saved into each table's columns.
SAVED_BY = {
    "assumption_curves": (AssumptionCurveCreate, AssumptionCurveUpdate),
    "cash_flow_priorities": (CashFlowPriorityCreate,),
    "charity_entities": (CharityEntityCreate, CharityEntityUpdate),
    "current_accounts": (AccountCreate, AccountUpdate),
    "expenses": (ExpenseCreate, ExpenseUpdate),
    "income_streams": (IncomeCreate, IncomeUpdate),
    "liabilities": (LiabilityCreate, LiabilityUpdate),
    "milestones": (MilestoneCreate, MilestoneUpdate),
    "plans": (PlanCreate, PlanUpdate),
    "real_assets": (RealAssetCreate, RealAssetUpdate),
    "tax_jurisdictions": (TaxJurisdictionCreate, TaxJurisdictionUpdate),
}

_ENUM_CHECK = re.compile(r"^(?:\w+ IS NULL OR )?(\w+) IN \(([^)]*)\)$")


def enum_checks():
    """(table, column, allowed values) for every ``column IN (...)`` model check."""
    found = []
    for table in Base.metadata.sorted_tables:
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint):
                match = _ENUM_CHECK.match(" ".join(str(constraint.sqltext).split()))
                if match:
                    found.append((table.name, match.group(1), set(re.findall(r"'([^']*)'", match.group(2)))))
    # Table.constraints is a set; sort so every pytest-xdist worker collects the same order.
    return sorted(found, key=lambda check: (check[0], check[1], sorted(check[2])))


def literal_values(annotation) -> set[str]:
    if typing.get_origin(annotation) is typing.Literal:
        return set(typing.get_args(annotation))
    return set().union(*(literal_values(arg) for arg in typing.get_args(annotation)))


def test_the_enum_checks_are_found():
    found = {(table, column) for table, column, _ in enum_checks()}
    assert {("cash_flow_priorities", "priority_type"), ("income_streams", "tax_category")} <= found


@pytest.mark.parametrize(("table", "column", "allowed"), enum_checks(), ids=lambda v: v if isinstance(v, str) else "")
def test_api_values_pass_the_column_check(table, column, allowed):
    assert table in SAVED_BY, f"Add the schemas that save {table} to SAVED_BY"
    schemas = [schema for schema in SAVED_BY[table] if column in schema.model_fields]
    assert schemas, f"No schema in SAVED_BY[{table!r}] has a {column} field"
    for schema in schemas:
        accepted = literal_values(schema.model_fields[column].annotation)
        assert accepted, f"{schema.__name__}.{column} is not a Literal"
        assert accepted <= allowed, f"{schema.__name__}.{column} accepts {sorted(accepted - allowed)}, which {table} rejects"

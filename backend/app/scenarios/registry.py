"""Every plan-scoped table's scenario decision, in one place.

A *row kind* pairs each Main row with a scenario copy through a link and
merges it field by field. A *whole-list kind* is compared and replaced as one
ordered list: its rows are recreated on every save (residency periods through
``PUT /plans/{id}``) or replaced as a list (priorities, drawdown order), so
row identities carry no meaning. The plan row's own columns are reported as
``plan_fields``.

Inheritable columns are each model's mapped columns minus identity,
ownership and bookkeeping columns, so a column another change adds later is
inherited without editing this module. A new plan-scoped table needs a
decision here: ``tests/test_scenario_registry.py`` fails until it is either
a kind or listed in ``NOT_INHERITED`` with a reason.
"""
from dataclasses import dataclass, field
from functools import cached_property

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.account import CurrentAccount
from app.models.assumption_curve import AssumptionCurve
from app.models.cash_flow_priority import CashFlowPriority
from app.models.charity import CharityEntity
from app.models.drawdown_order import DrawdownOrder
from app.models.expense import Expense
from app.models.income import IncomeStream
from app.models.liability import Liability
from app.models.milestone import Milestone
from app.models.plan import Plan
from app.models.real_asset import RealAsset
from app.models.residency_period import ResidencyPeriod
from app.models.spouse import Spouse

PLAN_KIND = "plan"

# Identity, ownership and bookkeeping: never inherited on any row.
ROW_EXCLUDED = frozenset({"id", "plan_id", "user_id", "created_at"})

# The plan row's own identity, naming, ownership, concurrency counter,
# legacy condition snapshot, archive and edit-window state, and scenario
# bookkeeping.
PLAN_EXCLUDED = frozenset({
    "id", "user_id", "client_id", "name", "notes", "created_at", "baseline_plan_id",
    "priorities_revision", "snapshot_conditions", "archived_at", "edit_notice_seen_at",
    "edit_grace_ends_at", "parent_plan_id", "scenario_sync",
})

# Plan-scoped tables that scenarios do not inherit, and why.
NOT_INHERITED = {
    # Scenario bookkeeping itself.
    "plan_links": "Links belong to the scenario; they are never copied or merged.",
    # A connection's placement names the plan that receives an institution's
    # newly found accounts. It points at one plan by choice; the scenario
    # receives balances through the accounts it inherits from Main.
    "financial_connections": "Placement chooses one receiving plan; scenarios inherit the resulting accounts.",
    # Balance links tie a provider account to one plan's account or loan and
    # detect outside edits by the last applied balance. Main keeps its links;
    # copying them would make two plans apply the same provider balance.
    "financial_balance_links": "Main keeps its provider links; scenarios inherit the synced balances.",
    # One spending feed per plan keeps that plan's two spending expenses
    # current. Main's feed updates Main's expenses, which scenarios inherit.
    "financial_spending_feeds": "Main's feed updates Main's expenses, which scenarios inherit.",
}


@dataclass(frozen=True)
class Kind:
    name: str
    model: type
    # Singular word for messages ("Restore the milestone ... first.").
    noun: str
    whole_list: bool = False
    # Whole lists: the display label and the ordering column.
    label: str | None = None
    rank: str | None = None
    excluded: frozenset = field(default=ROW_EXCLUDED)

    @cached_property
    def columns(self) -> dict:
        return {column.key: column for column in inspect(self.model).columns if column.key not in self.excluded}

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(self.columns)

    def rows(self, db: Session, plan_id) -> list:
        """The plan's current rows, reloaded from the database."""
        query = db.query(self.model).filter(self.model.plan_id == plan_id).populate_existing()
        return query.order_by(self.model.id).all()

    def row_name(self, row) -> str:
        if self.model is AssumptionCurve:
            return row.curve_type.replace("_", " ").capitalize()
        if self.model is Spouse:
            return row.name or "Partner"
        return getattr(row, "name", None) or self.noun.capitalize()


# Row kinds in creation order: each kind's references point only at kinds
# before it (milestones first, then accounts, then rows that use both).
ROW_KINDS = (
    Kind("milestone", Milestone, "milestone"),
    Kind("account", CurrentAccount, "account"),
    Kind("income", IncomeStream, "income"),
    Kind("real_asset", RealAsset, "property"),
    Kind("expense", Expense, "expense"),
    Kind("liability", Liability, "debt"),
    Kind("assumption_curve", AssumptionCurve, "assumption"),
    Kind("charity", CharityEntity, "gift"),
    Kind("spouse", Spouse, "partner"),
)
LIST_KINDS = (
    Kind("priorities", CashFlowPriority, "savings rule", whole_list=True, label="Savings rules", rank="priority_rank"),
    Kind("drawdown", DrawdownOrder, "withdrawal step", whole_list=True, label="Withdrawal order", rank="rank"),
    Kind("residency", ResidencyPeriod, "residency period", whole_list=True, label="Residency", rank="rank"),
)
KINDS = {kind.name: kind for kind in (*ROW_KINDS, *LIST_KINDS)}
ROW_KIND_NAMES = frozenset(kind.name for kind in ROW_KINDS)
LIST_KIND_NAMES = frozenset(kind.name for kind in LIST_KINDS)
ALL_KIND_NAMES = frozenset({PLAN_KIND, *KINDS})
MODEL_KINDS = {kind.model: kind.name for kind in KINDS.values()}

PLAN_COLUMNS = {column.key: column for column in inspect(Plan).columns if column.key not in PLAN_EXCLUDED}
PLAN_FIELDS = tuple(PLAN_COLUMNS)


def inherited_tables() -> set[str]:
    return {kind.model.__tablename__ for kind in KINDS.values()} | {Plan.__tablename__}

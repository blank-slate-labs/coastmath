import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ExpenseCategory = Literal["essential", "discretionary"]
PayrollTaxTreatment = Literal["pre_tax", "after_tax"]


def omit_none(value) -> bool:
    """``exclude_if`` predicate that leaves a None field out of dumps."""
    return value is None


class PayrollTaxElections(BaseModel):
    """Which wage bases a payroll deduction reduces; omitted keys use the default.

    Defaults follow ``payroll_tax_treatment`` (coastmath.engine.payroll_elections):
    pre-tax reduces federal, state and local wages but not FICA wages;
    after-tax reduces none.
    """

    model_config = ConfigDict(extra="forbid")

    federal: bool | None = Field(default=None, exclude_if=omit_none)
    state: bool | None = Field(default=None, exclude_if=omit_none)
    local: bool | None = Field(default=None, exclude_if=omit_none)
    fica: bool | None = Field(default=None, exclude_if=omit_none)


# A percent at or above this is reported to older clients as "discretionary".
DISCRETIONARY_CATEGORY_THRESHOLD = 50.0


def category_for_discretionary_percent(percent: float) -> ExpenseCategory:
    """The legacy category that mirrors a discretionary percent.

    ``discretionary_percent`` decides the engine's split whenever it is set;
    ``category`` is kept in step only so clients that read it (including the
    native app) still see the larger share.
    """
    return "discretionary" if percent >= DISCRETIONARY_CATEGORY_THRESHOLD else "essential"


def sync_expense_category(values: dict, saved_percent: float | None = None) -> dict:
    """Keep ``category`` consistent with ``discretionary_percent`` in a write.

    - A percent in the write wins: ``category`` is set from it, replacing a
      conflicting category sent alongside.
    - A category-only write that disagrees with the saved percent comes from a
      client that edits only the category, so the percent is cleared and the
      category alone defines the share again (essential 0%, discretionary 100%).
    - Any other write leaves both fields as they are.
    """
    percent = values.get("discretionary_percent")
    if percent is not None:
        values["category"] = category_for_discretionary_percent(percent)
    elif (
        "category" in values
        and "discretionary_percent" not in values
        and saved_percent is not None
        and values["category"] != category_for_discretionary_percent(float(saved_percent))
    ):
        values["discretionary_percent"] = None
    return values


def validate_funding_order(
    account_ids: list[uuid.UUID] | None,
    legacy_account_id: uuid.UUID | None,
) -> None:
    """Require unique funding accounts, led by the single legacy account when both are set."""
    if account_ids is None:
        return
    if len(account_ids) != len(set(account_ids)):
        raise ValueError("specific_funding_source_ids must contain unique account IDs")
    if legacy_account_id is not None and account_ids and account_ids[0] != legacy_account_id:
        raise ValueError("specific_funding_source_id must match the first selected account")

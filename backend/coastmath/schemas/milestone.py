from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

MilestoneTriggerType = Literal[
    "age",
    "date",
    "net_worth",
    "expense_multiple",
    "relative",
    "conditions",
]
MilestoneMetric = Literal["liquid_net_worth", "net_worth"]


ConditionMetric = Literal[
    "net_worth", "liquid_net_worth", "account_balance", "total_debt",
    "annual_spending", "passive_income", "savings_rate",
]


class ConditionBase(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AgeCondition(ConditionBase):
    kind: Literal["age"]
    owner: Literal["self", "spouse"] = "self"
    age: float = Field(ge=0, le=130)


class YearCondition(ConditionBase):
    kind: Literal["year"]
    year: int = Field(ge=1, le=9999)


class DateCondition(ConditionBase):
    kind: Literal["date"]
    date: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    @model_validator(mode="after")
    def validate_date(self):
        date.fromisoformat(f"{self.date}-01")
        return self


class MilestoneCondition(ConditionBase):
    kind: Literal["milestone"]
    milestone_id: str = Field(min_length=1)
    offset_years: int = Field(default=0, ge=-100, le=100)


class MetricCondition(ConditionBase):
    kind: Literal["metric"]
    metric: ConditionMetric
    account_id: str | None = None
    comparator: Literal[">=", "<="]
    value_unit: Literal["dollars", "today_dollars", "percent", "multiple_of_metric"]
    value: float
    other_metric: ConditionMetric | None = None
    average_years: int = Field(default=1, ge=1, le=10)

    @model_validator(mode="after")
    def validate_metric_units(self):
        if "account_balance" in (self.metric, self.other_metric) and not self.account_id:
            raise ValueError("Account balance needs an account id")
        if self.value_unit == "multiple_of_metric":
            if self.other_metric is None:
                raise ValueError("A multiple needs a comparison metric")
            if (self.metric == "savings_rate") != (self.other_metric == "savings_rate"):
                raise ValueError("Comparison metrics must use the same units")
        elif self.other_metric is not None:
            raise ValueError("Comparison metric is only used with a multiple")
        elif (self.value_unit == "percent") != (self.metric == "savings_rate"):
            raise ValueError("Savings rate uses percent; money metrics use dollars")
        return self


MilestoneConditionItem = Annotated[
    AgeCondition | YearCondition | DateCondition | MilestoneCondition | MetricCondition,
    Field(discriminator="kind"),
]
TemporalCondition = Annotated[
    AgeCondition | YearCondition | DateCondition | MilestoneCondition,
    Field(discriminator="kind"),
]


class MilestoneDeadline(ConditionBase):
    kind: Literal["age", "year", "date", "milestone"]
    value: float | int | str
    owner: Literal["self", "spouse"] = "self"
    action: Literal["fire", "miss"]

    @model_validator(mode="after")
    def validate_value(self):
        field = {"age": "age", "year": "year", "date": "date", "milestone": "milestone_id"}[self.kind]
        payload = {"kind": self.kind, field: self.value}
        if self.kind == "age":
            payload["owner"] = self.owner
        parsed = TypeAdapter(TemporalCondition).validate_python(payload)
        normalized = getattr(parsed, field)
        if self.value != normalized:
            self.value = normalized
        return self


class MilestoneConditions(ConditionBase):
    combinator: Literal["all", "any"]
    items: list[MilestoneConditionItem] = Field(min_length=1, max_length=10)
    deadline: MilestoneDeadline | None = None


def condition_references(conditions: dict | None) -> tuple[set[str], set[str]]:
    milestones, accounts = set(), set()
    for item in (conditions or {}).get("items", []):
        if item["kind"] == "milestone":
            milestones.add(item["milestone_id"])
        if item.get("account_id"):
            accounts.add(item["account_id"])
    deadline = (conditions or {}).get("deadline")
    if deadline and deadline["kind"] == "milestone":
        milestones.add(str(deadline["value"]))
    return milestones, accounts

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Names the intake gives the items it creates. A later submission updates the
# item with the same name instead of adding another one.
RETIREMENT_MILESTONE = "Retirement"
TRAVEL_END_MILESTONE = "Travel ends"
RETIREMENT_SPENDING_EXPENSE = "Retirement spending"
TRAVEL_EXPENSE = "Travel"
CHARITY_ENTITY = "Charitable giving"


class PlanIntake(BaseModel):
    """Goals asked right after a plan is created. Every answer is optional;
    an omitted or null answer leaves the plan unchanged.

    Spending and travel are annual amounts in today's dollars (inflation-linked
    expenses). Charitable giving is a nominal annual amount, as charity entities are.
    The legacy target is a one-time amount for heirs in today's dollars, saved to
    the plan's estate settings.
    """

    model_config = ConfigDict(extra="forbid")

    retirement_age: int | None = Field(default=None, ge=18, le=120)
    retirement_spending: float | None = Field(default=None, gt=0, le=1e12)
    travel_budget: float | None = Field(default=None, gt=0, le=1e12)
    travel_until_age: int | None = Field(default=None, ge=18, le=120)
    charitable_giving: float | None = Field(default=None, gt=0, le=1e12)
    legacy_target: float | None = Field(default=None, gt=0, le=1e12)

    @model_validator(mode="after")
    def travel_end_needs_budget(self):
        if self.travel_until_age is not None and self.travel_budget is None:
            raise ValueError("Enter a travel budget to set when travel ends")
        return self

    def is_empty(self) -> bool:
        return all(value is None for value in self.model_dump().values())

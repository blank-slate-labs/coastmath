"""Builders for custom-regime test specs and inputs, and readers of their results."""
from __future__ import annotations

import uuid
from typing import Any

from coastmath.engine.intl.spec import RegimeSpec
from coastmath.engine.intl.types import Person, PersonYear, RegimeYearInputs
from coastmath.engine.types import AccountInfo, AssumptionData, IncomeData, PlanData


def flat_brackets(rate: float) -> list[dict[str, Any]]:
    return [{"lower": 0, "upper": None, "rate": rate}]


def brackets(*edges: tuple[float, float]) -> list[dict[str, Any]]:
    """`brackets((0, 0.1), (10_000, 0.2))` -> contiguous brackets from (lower, rate) pairs."""
    rows = []
    for index, (lower, rate) in enumerate(edges):
        upper = edges[index + 1][0] if index + 1 < len(edges) else None
        rows.append({"lower": lower, "upper": upper, "rate": rate})
    return rows


def layer(layer_id: str = "income_tax", **fields: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": layer_id,
        "label": layer_id.replace("_", " ").title(),
        "category": "income_national",
        "brackets": flat_brackets(0.1),
    }
    data.update(fields)
    return data


def make_spec(meta: dict[str, Any] | None = None, **sections: Any) -> RegimeSpec:
    base_meta: dict[str, Any] = {
        "country": "XX",
        "name": "Test",
        "base_year": 2026,
        "currency": "USD",
        "filing_unit": "individual",
    }
    base_meta.update(meta or {})
    return RegimeSpec.model_validate({"meta": base_meta, **sections})


def person(who: Person = "self", age: int = 50, alive: bool = True, **income: float) -> PersonYear:
    deductible = income.pop("deductible_contributions", 0.0)
    return PersonYear(
        person=who,
        age=age,
        alive=alive,
        income=dict(income),
        deductible_contributions=deductible,
    )


def inputs(spec: RegimeSpec, *people: PersonYear, **fields: Any) -> RegimeYearInputs:
    filing = fields.pop("filing", "couple" if len(people) > 1 else "single")
    return RegimeYearInputs(
        country="XX",
        year=fields.pop("year", 2026),
        people=tuple(people),
        filing=filing,
        custom_spec=spec,
        **fields,
    )


def line_amounts(result) -> dict[tuple[str, str | None], float]:
    """A regime result's line amounts keyed by (code, person)."""
    return {(line.code, line.person): line.amount for line in result.lines}


def cash(balance: float = 10_000, **extra: Any) -> AccountInfo:
    """A savings account named "Cash" for simulation plans."""
    return AccountInfo(balance=balance, account_type="savings", name="Cash", **extra)


def intl_plan(**overrides) -> PlanData:
    values = dict(
        plan_id=str(uuid.uuid4()), birth_year=1980, filing_status="single", life_expectancy=50, start_year=2026,
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0,
                                   stock_dividend_yield=0.0, cash_yield_rate=0.0),
    )
    values.update(overrides)
    return PlanData(**values)


def intl_job(amount=100_000, owner="self", **extra):
    return IncomeData(id=f"job-{owner}", name=f"Job {owner}", annual_amount=amount, owner=owner, **extra)

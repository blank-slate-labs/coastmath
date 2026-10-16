"""Builders for PIA-basis Social Security tests: engine plans and the API plan."""
import uuid

from httpx import AsyncClient

from coastmath.engine.types import AccountInfo, AssumptionData, IncomeData, PlanData


def plan(**changes):
    values = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1966,
        birth_month=1,
        life_expectancy=90,
        filing_status="single",
        start_year=2026,
        assumptions=AssumptionData(
            inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
            stock_dividend_yield=0, cash_yield_rate=0,
        ),
        accounts={"cash": AccountInfo(balance=500_000, account_type="checking")},
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0, "capital_gains_tax_rate": 0},
    )
    values.update(changes)
    return PlanData(**values)


def couple(**changes):
    values = dict(
        spouse_birth_year=1966, spouse_birth_month=1, spouse_life_expectancy=90,
        filing_status="married_filing_jointly",
    )
    values.update(changes)
    return plan(**values)


def pia_ss(owner, pia, claim, growth=0.0, pct=None, **extra):
    return IncomeData(
        id=f"{owner}_ss", name=f"{owner} SS", owner=owner, annual_amount=1.0,
        tax_category="social_security", claiming_age=claim, growth_rate=growth,
        ss_benefit_basis="pia", pia_monthly=pia, expected_benefit_percent=pct, **extra,
    )


async def pia_plan(client: AsyncClient) -> str:
    response = await client.post("/api/plans", json={
        "name": "PIA basis", "birth_year": 1966, "birth_month": 1,
        "plan_type": "FIXED_DATE", "start_date": "2026-01-01",
    })
    assert response.status_code == 201
    return response.json()["id"]


PIA_INCOME = {
    "name": "Retirement benefit", "annual_amount": 0, "growth_rate": 0,
    "tax_category": "social_security", "claiming_age": 70,
    "ss_benefit_basis": "pia", "pia_monthly": 2000, "expected_benefit_percent": 90,
}

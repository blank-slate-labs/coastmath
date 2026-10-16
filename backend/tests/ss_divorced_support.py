"""Builders for divorced-spouse and surviving-divorced-spouse Social Security tests."""
import uuid

from coastmath.engine.types import AccountInfo, AssumptionData, IncomeData, PlanData

DIVORCED = "self SS (divorced spouse)"
SURVIVOR = "self SS (surviving divorced spouse)"


def plan(**changes):
    values = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1960,
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


def ex(**changes):
    record = dict(
        pia_monthly=3_000, birth_year=1958, birth_month=1, marriage_years=12,
        divorce_year=2000, claim_age=67,
    )
    record.update(changes)
    return record


def pia_ss(owner="self", pia=1_000, claim=67, ex_spouse=None, **extra):
    return IncomeData(
        id=f"{owner}_ss", name=f"{owner} SS", owner=owner, annual_amount=1.0,
        tax_category="social_security", claiming_age=claim, growth_rate=0.0,
        ss_benefit_basis="pia", pia_monthly=pia, ex_spouse=ex_spouse, **extra,
    )

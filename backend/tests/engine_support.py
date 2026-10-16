"""Shared readers and builders for engine-level tests."""
from __future__ import annotations

import re
import uuid
from datetime import date
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    EstateSettingsData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
    ResidencyPeriodData,
    SimState,
)
from coastmath.engine.withdrawal_strategy import strategy_spending
from tests import financial_probes


def roth_converted(row) -> float:
    """Total moved into the account with id "roth" in one yearly snapshot."""
    return sum(t.amount for t in row.transfers if t.target_account_id == "roth")


def source(result, year: int, name: str) -> float:
    """Total of the income sources called `name` in `year` of a simulation result."""
    row = next(s for s in result.yearly_snapshots if s.year == year)
    return sum(i.amount for i in row.cash_flow.income_sources if i.name == name)


def fixture_to_plan_data(
    raw: dict, *, guess_social_security: bool = False, with_owner_and_category: bool = False,
) -> PlanData:
    """Convert standard_plan.json dict into a PlanData dataclass.

    ``guess_social_security`` marks an income as Social Security when the
    fixture says so or its name contains "social security" (the persona
    harness and the simulation tests load fixtures this way).
    ``with_owner_and_category`` keeps each account's ``owner`` (default
    "self") and each expense's ``category``, which are otherwise dropped."""
    accounts = {
        a["id"]: AccountInfo(
            balance=a["balance"],
            account_type=a["account_type"],
            owner=a.get("owner", "self") if with_owner_and_category else "self",
        )
        for a in raw.get("accounts", [])
    }

    milestones = [
        MilestoneData(
            id=m["id"],
            name=m["name"],
            trigger_type=m["trigger_type"],
            trigger_value=m.get("trigger_value"),
            trigger_date=m.get("trigger_date"),
        )
        for m in raw.get("milestones", [])
    ]

    income_streams = [
        IncomeData(
            id=inc["id"],
            name=inc["name"],
            annual_amount=inc["annual_amount"],
            start_milestone_id=inc.get("start_milestone_id"),
            end_milestone_id=inc.get("end_milestone_id"),
            growth_rate=inc.get("growth_rate", 0.0),
            withholding_percent=inc.get("withholding_percent") or 0.0,
            start_month=inc.get("start_month"),
            end_month=inc.get("end_month"),
            is_social_security=guess_social_security and bool(
                inc.get("is_social_security")
                or re.search(r"social security", inc.get("name", ""), re.IGNORECASE)
            ),
        )
        for inc in raw.get("income_streams", [])
    ]

    expenses = [
        ExpenseData(
            id=exp["id"],
            name=exp["name"],
            annual_amount=exp["annual_amount"],
            start_milestone_id=exp.get("start_milestone_id"),
            end_milestone_id=exp.get("end_milestone_id"),
            inflation_linked=exp.get("inflation_linked", True),
            is_payroll_deduction=exp.get("is_payroll_deduction", False),
            specific_funding_source_id=exp.get("specific_funding_source_id"),
            start_month=exp.get("start_month"),
            end_month=exp.get("end_month"),
            category=exp.get("category") if with_owner_and_category else None,
        )
        for exp in raw.get("expenses", [])
    ]

    priorities = [
        PriorityData(
            priority_rank=p["priority_rank"],
            target_account_id=p.get("target_account_id"),
            max_annual_amount=p.get("max_annual_amount"),
            priority_type=p.get("priority_type"),
        )
        for p in raw.get("priorities", [])
    ]

    drawdown_order = [
        DrawdownEntryData(
            rank=d["rank"],
            source_account_id=d.get("source_account_id"),
        )
        for d in raw.get("drawdown_order", [])
    ]

    assumptions = AssumptionData()
    for curve in raw.get("assumption_curves", []):
        if curve["curve_type"] == "inflation":
            assumptions.inflation_rate = curve["fixed_rate"]
        elif curve["curve_type"] == "market_return":
            assumptions.stock_growth_rate = curve["fixed_rate"]
        elif curve["curve_type"] == "bond_return":
            assumptions.bond_return_rate = curve["fixed_rate"]

    start_year = int(raw["start_date"][:4])

    spouse_birth_year = None
    spouse_life_expectancy = None
    if raw.get("spouse"):
        spouse_birth_year = raw["spouse"].get("birth_year")
        spouse_life_expectancy = raw["spouse"].get("life_expectancy")

    return PlanData(
        plan_id=raw["id"],
        birth_year=raw["birth_year"],
        filing_status=raw["filing_status"],
        life_expectancy=raw["life_expectancy"],
        start_year=start_year,
        milestones=milestones,
        income_streams=income_streams,
        expenses=expenses,
        priorities=priorities,
        drawdown_order=drawdown_order,
        assumptions=assumptions,
        accounts=accounts,
        spouse_birth_year=spouse_birth_year,
        spouse_life_expectancy=spouse_life_expectancy,
    )


def year_snapshot(result, year):
    return next(snapshot for snapshot in result.yearly_snapshots if snapshot.year == year)


def by_year(result):
    return {s.year: s for s in result.yearly_snapshots}


def contributed(snapshot, account_id):
    return sum(c.amount for c in snapshot.cash_flow.contributions if c.account_id == account_id)


def reconcile(result):
    """Net worth moves by growth, outside income, expenses and taxes (no leakage)."""
    prior = result.initial_snapshot.net_worth
    for snapshot in result.yearly_snapshots:
        external = sum(f.amount for f in snapshot.cash_flow.income_sources if f.source not in {"rmd", "sepp"})
        assert snapshot.net_worth == pytest.approx(
            prior + snapshot.investment_growth + external - snapshot.expenses - snapshot.taxes, abs=.01), snapshot.year
        assert snapshot.net_worth == pytest.approx(
            sum(snapshot.accounts.values()) + snapshot.real_assets_value - snapshot.liabilities_balance
            - snapshot.tax_balance - snapshot.unfunded_expenses, abs=.01), snapshot.year
        prior = snapshot.net_worth


def minimal_plan(**overrides) -> PlanData:
    """Build a minimal PlanData with sensible defaults, overridable."""
    defaults = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1990,
        filing_status="single",
        life_expectancy=90,
        start_year=2025,
        milestones=[],
        income_streams=[],
        expenses=[],
        priorities=[],
        drawdown_order=[],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
        accounts={},
    )
    defaults.update(overrides)
    return PlanData(**defaults)


def audit_plan(**kwargs):
    return PlanData(plan_id=str(uuid4()), birth_year=1980, filing_status='single', start_year=2026, life_expectancy=50,
        accounts={'cash': AccountInfo(100_000, 'checking')},
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0), **kwargs)


def strategy_plan(**overrides) -> PlanData:
    defaults = dict(
        plan_id=str(uuid.uuid4()), birth_year=1965, filing_status="single", life_expectancy=75,
        start_year=2026, income_streams=[], priorities=[],
        milestones=[MilestoneData(id="retire", name="Retire", trigger_type="age", trigger_value=63)],
        expenses=[ExpenseData(id="living", name="Living", annual_amount=50_000, inflation_linked=True)],
        accounts={"brok": AccountInfo(balance=1_500_000, account_type="taxable_brokerage", cost_basis=1_500_000)},
        drawdown_order=[DrawdownEntryData(rank=1, source_account_id="brok")],
        assumptions=AssumptionData(inflation_rate=0.02, stock_growth_rate=0.05, bond_return_rate=0.0),
    )
    defaults.update(overrides)
    return PlanData(**defaults)


def strategy_spend(spec, state, **kw):
    defaults = dict(year=2030, age=65, portfolio=1_000_000, inflation_factor=1.0, years_remaining=30)
    defaults.update(kw)
    return strategy_spending(spec, state, **defaults)


def premium_tax_example(code="CA", interest=20000, paid=0):
    return financial_probes.plan(
        birth_year=1986,
        life_expectancy=41,
        state_code=code,
        accounts={"cash": AccountInfo(10000, "checking")},
        income_streams=[IncomeData("p", "Wages", 100000)],
        tax_settings={
            "year_to_date": {"tax_year": 2026, "mortgage_interest": interest},
            "state_payroll_paid_year_to_date": {"California SDI": paid},
            "state_payroll_coverage": [
                {
                    "owner": "self",
                    "start_year": 2026,
                    "state_code": code,
                    "ca_sdi": code == "CA",
                    "wa_paid_leave": code == "WA",
                }
            ],
        },
    )


def wage_before_move_plan(initial: str, destination: str) -> PlanData:
    return PlanData(
        plan_id=str(uuid5(NAMESPACE_URL, f"residency-wages-{initial}-{destination}")),
        birth_year=1990,
        birth_month=1,
        filing_status="single",
        life_expectancy=37,
        start_year=2026,
        milestones=[
            MilestoneData(id="stop", name="Last paid wage month", trigger_type="date",
                          trigger_date="2026-05-01"),
            MilestoneData(id="move", name="Residency changes", trigger_type="date",
                          trigger_date="2026-06-01"),
        ],
        income_streams=[IncomeData(
            id="salary", name="Wages earned and received before move",
            annual_amount=120_000, growth_rate=0,
            end_milestone_id="stop", end_month=5,
        )],
        expenses=[],
        priorities=[PriorityData(priority_rank=1, target_account_id="cash")],
        drawdown_order=["cash"],
        assumptions=AssumptionData(
            inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
        ),
        accounts={"cash": AccountInfo(balance=100_000, account_type="checking")},
        tax_settings={"ca_exemption_eligible_owners": []},
        state_code=initial,
        residency_periods=[ResidencyPeriodData(
            state_code=destination, start_milestone_id="move",
        )],
    )


def hsa_row(owner="self", coverage="self_only", **kwargs):
    return dict(owner=owner, start_year=2025, coverage=coverage, **kwargs)


def hsa_state(rows, year=2026, ages=None):
    return SimState(year=year, accounts={
        "a": AccountInfo(0, "hsa", owner="self"),
        "b": AccountInfo(0, "hsa", owner="spouse"),
        "c": AccountInfo(0, "hsa", owner="self"),
    }, hsa_coverage=rows, owner_ages=ages or {"self": 40, "spouse": 40})


def lifecycle_household(**changes):
    args = dict(plan_id='00000000-0000-0000-0000-000000000001', birth_year=1950, birth_month=1, life_expectancy=76,
        spouse_birth_year=1960, spouse_birth_month=1, spouse_life_expectancy=70,
        start_year=2026, filing_status='married_filing_jointly',
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, cash_yield_rate=0, stock_dividend_yield=0),
        estate_settings=EstateSettingsData(household_lifecycle='last_survivor_calendar_year_end'),
        tax_settings={'mode':'flat','ordinary_income_tax_rate':0,'capital_gains_tax_rate':0},
        accounts={'cash':AccountInfo(balance=100000,account_type='checking')})
    args.update(changes)
    return PlanData(**args)


# A plan starting 2026-09-09: 114/365 of the year remain.
YTD_FRACTION = 114 / 365


def ytd_household(**overrides):
    values = dict(
        plan_id=str(uuid4()), birth_year=1990, spouse_birth_year=1992, start_year=2026,
        life_expectancy=40, filing_status="married_filing_jointly", state_code="TX",
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0),
        accounts={"cash": AccountInfo(balance=100_000, account_type="checking")},
        income_streams=[IncomeData(id="salary", name="Salary", annual_amount=180_000, growth_rate=0)],
        first_year_fraction=YTD_FRACTION,
    )
    return PlanData(**(values | overrides))


def active_requests(request, year):
    """Independent calendar oracle; does not call engine milestone functions."""
    boundaries = {m["id"]: date.fromisoformat(m["body"]["trigger_date"])
                  for m in request["milestones"]}
    when = date(year, 1, 1)
    return [p for p in request["priorities"] if p["body"]["allocation_mode"] == "amount"
            and (p["body"].get("start_milestone_id") is None
                 or boundaries[p["body"]["start_milestone_id"]] <= when)
            and (p["body"].get("end_milestone_id") is None
                 or when < boundaries[p["body"]["end_milestone_id"]])]

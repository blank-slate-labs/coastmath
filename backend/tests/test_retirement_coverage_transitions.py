"""Targeted annual cash/depletion oracles around retirement."""

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PriorityData,
)
from tests.engine_support import reconcile
from tests.financial_probes import plan


@pytest.mark.parametrize("month", [1, 6, 12])
@pytest.mark.parametrize("balance", [0, 1000, 100000])
@pytest.mark.parametrize("frequency", ["annual", "monthly"])
def test_midyear_retirement_hsa_and_tax_funding_conserve_dollars(
    month, balance, frequency
):
    p = plan(
        birth_year=1966,
        life_expectancy=61,
        accounts={
            "cash": AccountInfo(balance, "checking"),
            "h": AccountInfo(0, "hsa"),
            "ira": AccountInfo(10000, "traditional_ira"),
        },
        income_streams=[
            IncomeData(
                "p",
                "Pay until retirement",
                60000,
                end_milestone_id="retire",
                end_month=month,
            )
        ],
        milestones=[
            MilestoneData(
                "retire", "Retirement", "date", trigger_date=f"2026-{month:02d}-01"
            )
        ],
        expenses=[ExpenseData("e", "Spending", 50000)],
        priorities=[PriorityData(1, "h", 3000, "pre_tax_contribution")],
        drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "ira")],
        tax_settings={
            "cash_flow_frequency": frequency,
            "hsa_coverage": [
                {
                    "owner": "self",
                    "start_year": 2026,
                    "coverage": "self_only",
                    "eligible_months": list(range(1, month + 1)),
                    "payroll_funding": "cafeteria",
                }
            ],
        },
    )
    r = run_simulation(p)
    s = r.yearly_snapshots[0]
    reconcile(r)
    external = sum(x.amount for x in s.cash_flow.income_sources)
    assert external == pytest.approx(60000 * month / 12)
    # No returns: no date-of-growth assumption enters this independent oracle.
    assert s.net_worth == pytest.approx(
        balance + 10000 + external - 50000 - s.taxes, abs=0.02
    )
    assert s.accounts["h"] <= min(3000, 5400 * month / 12) + 0.01
    assert r.metadata.success == (s.unfunded_expenses <= 0.01)
    assert s.unfunded_expenses >= 0


@pytest.mark.parametrize("month", [1, 7, 12])
def test_social_security_start_month_cash_is_external_once(month):
    p = plan(
        birth_year=1960,
        life_expectancy=67,
        accounts={"cash": AccountInfo(10000, "checking")},
        income_streams=[
            IncomeData(
                "ss",
                "Social Security",
                24000,
                is_social_security=True,
                is_earned_income=False,
                start_milestone_id="claim",
                start_month=month,
            )
        ],
        milestones=[
            MilestoneData("claim", "Claim", "date", trigger_date=f"2026-{month:02d}-01")
        ],
        expenses=[],
        priorities=[],
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0},
    )
    r = run_simulation(p)
    s = r.yearly_snapshots[0]
    assert s.accounts["cash"] == pytest.approx(10000 + 24000 * (13 - month) / 12)
    reconcile(r)

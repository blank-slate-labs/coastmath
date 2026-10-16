"""A small retirement plan whose Monte Carlo trials both succeed and fail.

Shared by the trial-explorer tests and the frozen aggregate baseline in
``tests/fixtures/monte_carlo_trial_baseline.json``. Changing this plan changes
the baseline; regenerate it only from a commit whose aggregation is known good.
"""

from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    MilestoneData,
    PlanData,
)

BASELINE_RUNS = (
    # (name, run_monte_carlo keyword arguments)
    ("calibrated", {"n_trials": 40, "seed": 20261009, "block_size_range": (2, 6)}),
    ("raw_history_net_worth", {
        "n_trials": 25, "seed": 7, "block_size_range": (3, 7),
        "calibrate_to_plan": False, "failure_mode": "net_worth",
    }),
)


def trial_plan() -> PlanData:
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000001",
        birth_year=1966,
        birth_month=1,
        filing_status="single",
        life_expectancy=88,
        start_year=2026,
        assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.06, bond_return_rate=0.04),
        accounts={
            "brokerage": AccountInfo(700_000, "taxable_brokerage", cost_basis=500_000),
            "cash": AccountInfo(20_000, "checking"),
        },
        drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "brokerage")],
        expenses=[ExpenseData(id="living", name="Living", annual_amount=42_000)],
        milestones=[
            MilestoneData("age70", "Age 70", "age", trigger_value=70),
            MilestoneData("million", "Net worth $1M", "net_worth", trigger_value=1_000_000),
        ],
    )

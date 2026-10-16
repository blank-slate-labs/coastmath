"""Monte Carlo and crash stress tests agree with the deterministic projection.

Monte Carlo centers crypto and own-yield accounts on the deterministic
projection by scaling sampled dividend yields to the plan's yield, and the
market-crash preset loses the full drop in a partial opening year.

Expected values follow from the plan inputs, not from engine output.
"""

import uuid

import numpy as np
import pandas as pd
import pytest

from coastmath.engine.monte_carlo import calibrate_dividend_yields, run_monte_carlo
from coastmath.engine.scenario_stress import ScenarioParams, run_scenario_stress_test
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import AccountInfo, AssumptionData, PlanData

# ---------------------------------------------------------------------------
# Monte Carlo centers crypto and own-yield accounts on
# the deterministic projection. Calibration targets market return plus the
# plan's yield, so sampled yields are scaled to the plan's yield as well.
# ---------------------------------------------------------------------------


class TestMonteCarloDividendCalibration:
    # One historical year exactly at the plan's 7% total, 4% of it recorded
    # as dividends. Roth accounts keep dividends out of tax.
    HISTORY = pd.DataFrame({"year": [2000], "stock_return": [0.07], "bond_return": [0.0],
                            "inflation": [0.0], "dividend_yield": [0.04]})
    ACCOUNTS = {
        "plain": AccountInfo(100_000, "roth_ira"),
        "own_yield": AccountInfo(100_000, "roth_ira", investment_settings={"dividend_yield": 0.02}),
        "crypto": AccountInfo(100_000, "cryptocurrency", cost_basis=100_000),
    }

    @pytest.mark.parametrize(("plan_yield", "account", "expected"), [
        # Price 7% plus the account's own yield: none for crypto.
        (0.0, "plain", 107_000), (0.0, "own_yield", 109_000), (0.0, "crypto", 107_000),
        (0.02, "plain", 109_000), (0.02, "own_yield", 109_000), (0.02, "crypto", 107_000),
    ])
    def test_matches_the_deterministic_projection(self, plan_yield, account, expected):
        plan = PlanData(
            plan_id=str(uuid.uuid4()), birth_year=1980, filing_status="single", life_expectancy=47,
            start_year=2026, accounts={account: self.ACCOUNTS[account]},
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.07,
                                       bond_return_rate=0.0, stock_dividend_yield=plan_yield),
        )
        assert run_simulation(plan).yearly_snapshots[0].net_worth == pytest.approx(expected)
        result = run_monte_carlo(plan, n_trials=1, historical_data=self.HISTORY, max_workers=1, seed=1,
                                 block_size_range=(1, 1))
        assert result.percentile_curves.p50[0] == pytest.approx(expected)

    def test_scaling_keeps_unknown_years_and_valid_rows(self):
        sequence = np.array([[0.10, 0.0, 0.0, 0.04], [0.05, 0.0, 0.0, np.nan], [-0.99, 0.0, 0.0, 0.02]])
        scaled = calibrate_dividend_yields(sequence, np.array([0.06, 0.06, 0.06]), 0.02)
        assert scaled[0, 3] == pytest.approx(0.12)   # 0.04 x 0.06 / 0.02
        assert np.isnan(scaled[1, 3])                 # unrecorded stays unknown
        assert scaled[2, 3] == pytest.approx(0.01)    # capped at 1 + total return
        assert sequence[0, 3] == 0.04                 # input untouched


# ---------------------------------------------------------------------------
# The market-crash preset loses the full drop in a
# partial opening year (the UI defaults the crash to the plan's first year).
# ---------------------------------------------------------------------------


class TestCrashInPartialOpeningYear:
    def _plan(self, fraction, dividend_yield=0.0):
        return PlanData(
            plan_id=str(uuid.uuid4()), birth_year=1980, filing_status="single", life_expectancy=50,
            start_year=2026, first_year_fraction=fraction, accounts={"roth": AccountInfo(100_000, "roth_ira")},
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0,
                                       stock_dividend_yield=dividend_yield),
        )

    def _balances(self, plan, crash_year):
        result = run_scenario_stress_test(plan, "market_crash", ScenarioParams(start_year=crash_year,
                                                                               stock_drop_percent=35))
        return [s.accounts["roth"] for s in result["simulation_result"].yearly_snapshots[:2]]

    @pytest.mark.parametrize("fraction", [1.0, 0.25, 0.2411])
    def test_opening_year_crash_loses_the_full_drop(self, fraction):
        assert self._balances(self._plan(fraction), 2026) == pytest.approx([65_000, 65_000])

    def test_total_is_kept_with_a_dividend_yield(self):
        # Price and reinvested dividends together still lose 35% (Roth: no tax).
        assert self._balances(self._plan(0.25, dividend_yield=0.02), 2026)[0] == pytest.approx(65_000)

    def test_later_year_crash_is_a_full_year(self):
        assert self._balances(self._plan(0.25), 2027) == pytest.approx([100_000, 65_000])

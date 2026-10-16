"""Tests for Monte Carlo aggregation and result schemas."""

import uuid

import numpy as np
import pytest
from pydantic import ValidationError

from app.routers.monte_carlo_stateless import MonteCarloStatelessRequest
from coastmath.engine.monte_carlo import aggregate_results
from coastmath.schemas.monte_carlo import (
    FailureDetail,
    MonteCarloRequest,
    MonteCarloResult,
    MonteCarloTrialRequest,
    PercentileCurves,
    SuccessTargets,
)
from coastmath.schemas.simulation import SimMetadata, SimulationResult, YearSnapshot


def _make_trial(
    net_worths: list[float],
    start_year: int = 2025,
    start_age: int = 30,
    failure_year: int | None = None,
    liquid_balances: list[float] | None = None,
) -> SimulationResult:
    """Build a minimal SimulationResult from a net-worth trajectory.

    If *liquid_balances* is provided, each snapshot gets a single
    ``accounts`` entry with that balance.  Otherwise, ``accounts`` defaults
    to a single entry equal to ``net_worth`` (so liquid == net_worth).
    """
    plan_id = uuid.uuid4()
    if liquid_balances is None:
        liquid_balances = list(net_worths)
    snapshots = [
        YearSnapshot(
            year=start_year + i,
            age=start_age + i,
            net_worth=nw,
            accounts={"checking": liquid_balances[i]},
        )
        for i, nw in enumerate(net_worths)
    ]
    return SimulationResult(
        metadata=SimMetadata(
            plan_id=plan_id,
            start_year=start_year,
            end_year=start_year + len(net_worths),
            success=failure_year is None,
            failure_year=failure_year,
        ),
        yearly_snapshots=snapshots,
    )


# -------------------------------------------------------------------
# Schema tests
# -------------------------------------------------------------------


class TestSchemas:
    def test_failure_detail_fields(self):
        fd = FailureDetail(
            trial_index=0,
            failure_year=2040,
            failure_age=45,
            cause="net_worth_depleted",
            net_worth_at_failure=-5000.0,
        )
        assert fd.trial_index == 0
        assert fd.failure_year == 2040
        assert fd.cause == "net_worth_depleted"

    def test_percentile_curves_fields(self):
        pc = PercentileCurves(
            years=[2025, 2026],
            p10=[100.0, 200.0],
            p25=[150.0, 250.0],
            p50=[200.0, 300.0],
            p75=[250.0, 350.0],
            p90=[300.0, 400.0],
        )
        assert len(pc.years) == 2
        assert pc.p50 == [200.0, 300.0]

    def test_monte_carlo_request_defaults(self):
        req = MonteCarloRequest()
        assert req.n_trials == 1000
        assert req.block_size_min == 3
        assert req.block_size_max == 7
        assert req.failure_mode == "liquid_assets"

    def test_monte_carlo_trials_stop_at_1000(self):
        # More trials outlast Cloudflare's 100 s origin limit on production.
        assert MonteCarloRequest(n_trials=1000).n_trials == 1000
        with pytest.raises(ValidationError):
            MonteCarloRequest(n_trials=1001)
        with pytest.raises(ValidationError):
            MonteCarloTrialRequest(n_trials=5000, base_seed=1)
        assert MonteCarloStatelessRequest.model_fields["num_simulations"].metadata[-1].le == 1000

    def test_monte_carlo_request_custom(self):
        req = MonteCarloRequest(n_trials=500, block_size_min=2, block_size_max=10)
        assert req.n_trials == 500
        assert req.block_size_min == 2

    def test_monte_carlo_result_roundtrip(self):
        """Ensure MonteCarloResult serializes and deserializes correctly."""
        result = MonteCarloResult(
            success_rate=0.95,
            n_trials=100,
            percentile_curves=PercentileCurves(
                years=[2025], p10=[10.0], p25=[25.0],
                p50=[50.0], p75=[75.0], p90=[90.0],
            ),
            failure_analysis=[],
            median_final_net_worth=50.0,
            p10_final_net_worth=10.0,
            p90_final_net_worth=90.0,
        )
        data = result.model_dump()
        restored = MonteCarloResult.model_validate(data)
        assert restored.success_rate == 0.95
        assert restored.n_trials == 100


# -------------------------------------------------------------------
# Aggregation tests
# -------------------------------------------------------------------


class TestAggregateResults:
    def test_all_success(self):
        """All trials succeed with positive net worth."""
        trials = [
            _make_trial([100_000, 200_000, 300_000]),
            _make_trial([150_000, 250_000, 350_000]),
            _make_trial([120_000, 220_000, 320_000]),
        ]
        result = aggregate_results(trials, plan_years=3)

        assert result.n_trials == 3
        assert result.success_rate == 1.0
        assert len(result.failure_analysis) == 0
        assert len(result.percentile_curves.years) == 3
        assert len(result.percentile_curves.p50) == 3

    def test_failure_detection_net_worth_zero(self):
        """Trial with net_worth <= 0 is detected as failure (net_worth mode)."""
        trials = [
            _make_trial([100_000, 50_000, 200_000]),  # success
            _make_trial([100_000, -5_000, -10_000]),  # fails year 2
            _make_trial([100_000, 0, -1_000]),         # fails year 2 (exactly 0)
        ]
        result = aggregate_results(trials, plan_years=3, failure_mode="net_worth")

        assert result.n_trials == 3
        assert result.success_rate == pytest.approx(1 / 3)
        assert len(result.failure_analysis) == 2
        # Both failures should be in the second year
        for fd in result.failure_analysis:
            assert fd.failure_year == 2026
            assert fd.cause == "net_worth_depleted"

    def test_failure_detection_liquid_assets_default(self):
        """Default failure mode uses liquid assets, not net worth."""
        # Household with negative net worth but positive liquid assets
        # (e.g., $500k mortgage on $400k house with $200k liquid)
        trials = [
            _make_trial(
                net_worths=[-100_000, -50_000, 50_000],
                liquid_balances=[200_000, 150_000, 100_000],
            ),
        ]
        result = aggregate_results(trials, plan_years=3)  # default = liquid_assets

        assert result.success_rate == 1.0
        assert len(result.failure_analysis) == 0

    def test_failure_detection_liquid_assets_depleted(self):
        """Liquid assets mode detects failure when liquid balances hit zero."""
        trials = [
            _make_trial(
                net_worths=[200_000, 150_000, 100_000],   # net worth stays positive
                liquid_balances=[50_000, 0, -10_000],      # liquid depleted year 2
            ),
        ]
        result = aggregate_results(trials, plan_years=3)

        assert result.success_rate == 0.0
        assert len(result.failure_analysis) == 1
        assert result.failure_analysis[0].failure_year == 2026
        assert result.failure_analysis[0].cause == "liquid_assets_depleted"
        # net_worth_at_failure should still report the snapshot's net_worth
        assert result.failure_analysis[0].net_worth_at_failure == 150_000

    def test_leveraged_household_not_penalised(self):
        """A leveraged-but-cash-flow-positive household is not marked as failure.

        This is the core scenario motivating the configurable failure mode:
        negative net worth due to mortgage but positive liquid assets.
        """
        trials = [
            # Net worth negative throughout, but liquid assets stay positive
            _make_trial(
                net_worths=[-300_000, -250_000, -200_000],
                liquid_balances=[100_000, 120_000, 140_000],
            ),
            # Net worth positive, liquid positive — clearly fine
            _make_trial(
                net_worths=[500_000, 600_000, 700_000],
                liquid_balances=[500_000, 600_000, 700_000],
            ),
        ]
        # Default mode (liquid_assets) — both should pass
        result_liquid = aggregate_results(trials, plan_years=3)
        assert result_liquid.success_rate == 1.0

        # Legacy mode (net_worth) — first trial fails
        result_nw = aggregate_results(trials, plan_years=3, failure_mode="net_worth")
        assert result_nw.success_rate == 0.5
        assert result_nw.failure_analysis[0].cause == "net_worth_depleted"

    def test_failure_from_metadata(self):
        """Trial flagged as failed via metadata.failure_year."""
        trials = [
            _make_trial([100_000, 200_000, 300_000]),
            _make_trial(
                [100_000, 50_000, 10_000],
                failure_year=2027,
            ),
        ]
        result = aggregate_results(trials, plan_years=3)

        assert result.success_rate == 0.5
        assert len(result.failure_analysis) == 1
        assert result.failure_analysis[0].cause == "simulation_failure"
        assert result.failure_analysis[0].failure_year == 2027

    def test_percentile_ordering(self):
        """p10 <= p25 <= p50 <= p75 <= p90 for every year."""
        rng = np.random.default_rng(42)
        trials = [
            _make_trial((rng.uniform(50_000, 500_000, size=5)).tolist())
            for _ in range(50)
        ]
        result = aggregate_results(trials, plan_years=5)

        curves = result.percentile_curves
        for j in range(5):
            assert curves.p10[j] <= curves.p25[j]
            assert curves.p25[j] <= curves.p50[j]
            assert curves.p50[j] <= curves.p75[j]
            assert curves.p75[j] <= curves.p90[j]

    def test_final_net_worth_stats(self):
        """Median/p10/p90 final net worth are computed from the last year."""
        trials = [
            _make_trial([100_000, 200_000]),
            _make_trial([100_000, 400_000]),
            _make_trial([100_000, 300_000]),
        ]
        result = aggregate_results(trials, plan_years=2)

        # Final net worths: [200k, 400k, 300k]
        # p50 = 300k, p10 close to 200k, p90 close to 400k
        assert result.median_final_net_worth == pytest.approx(300_000, rel=0.01)
        assert result.p10_final_net_worth <= result.median_final_net_worth
        assert result.p90_final_net_worth >= result.median_final_net_worth

    def test_single_trial(self):
        """Works with a single trial."""
        trials = [_make_trial([500_000, 600_000, 700_000])]
        result = aggregate_results(trials, plan_years=3)

        assert result.n_trials == 1
        assert result.success_rate == 1.0
        # All percentiles should be the same value for a single trial
        assert result.percentile_curves.p10 == result.percentile_curves.p90

    def test_years_from_snapshots(self):
        """Year labels come from the first trial's snapshots."""
        trials = [
            _make_trial([100_000, 200_000], start_year=2030),
            _make_trial([150_000, 250_000], start_year=2030),
        ]
        result = aggregate_results(trials, plan_years=2)
        assert result.percentile_curves.years == [2030, 2031]



class TestOutcomeCategories:
    """Every trial lands in exactly one category; funding failure is never
    merged with target shortfalls."""

    def _result(self, final_net_worth: float, fail: bool = False, cuts: float = 0.0) -> SimulationResult:
        snaps = [
            YearSnapshot(year=2030 + i, age=60 + i, gross_income=0, taxes=0, expenses=0, net_cash_flow=0,
                         accounts={"cash": 0.0 if (fail and i == 2) else 100_000.0}, net_worth=final_net_worth,
                         flex_spending_reduction=cuts if i == 1 else 0.0)
            for i in range(3)
        ]
        return SimulationResult(
            metadata=SimMetadata(plan_id=uuid.uuid4(), start_year=2030, end_year=2032, success=not fail, failure_year=2032 if fail else None),
            yearly_snapshots=snaps,
        )

    def test_categories_partition_trials_and_targets_are_separate(self):
        results = [
            self._result(2_000_000),                     # met target
            self._result(500_000),                       # survived below target
            self._result(2_000_000, cuts=5_000),         # met target with cuts
            self._result(50_000, fail=True),             # funding failure
        ]
        out = aggregate_results(results, 3, failure_mode="liquid_assets",
                                success_targets=SuccessTargets(terminal_net_worth_min=1_000_000, count_spending_cuts_as_shortfall=True))
        cats = {c.key: c for c in out.outcome_categories}
        assert sum(c.count for c in cats.values()) == 4
        assert cats["met_targets"].count == 1 and cats["survived_below_target"].count == 1
        assert cats["survived_with_spending_cuts"].count == 1 and cats["funding_failure"].count == 1
        assert out.success_rate == pytest.approx(0.75) and out.funding_success_rate == pytest.approx(0.75)
        assert out.target_success_rate == pytest.approx(0.25)
        assert "nominal" in cats["met_targets"].definition
        assert out.definitions["success_rate"].startswith("Share of trials that funded all required spending")
        # Cuts not counted as shortfall: the cut trial counts toward the target rate.
        out2 = aggregate_results(results, 3, success_targets=SuccessTargets(terminal_net_worth_min=1_000_000))
        assert out2.target_success_rate == pytest.approx(0.5)
        assert {c.key: c.count for c in out2.outcome_categories}["survived_with_spending_cuts"] == 0

    def test_no_targets_leaves_target_rate_null(self):
        out = aggregate_results([self._result(1.0), self._result(1.0, fail=True)], 3)
        assert out.target_success_rate is None and out.success_targets is None
        assert {c.key: c.count for c in out.outcome_categories} == {"met_targets": 1, "survived_with_spending_cuts": 0, "survived_below_target": 0, "funding_failure": 1}

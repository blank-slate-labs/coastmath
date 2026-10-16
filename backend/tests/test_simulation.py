"""Pytest tests for the simulation engine (task 1.7.2).

Tests engine functions directly — no HTTP, no database.
"""

from __future__ import annotations

import pytest

from coastmath.engine.milestones import evaluate_milestones, is_event_active
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import calculate as calculate_tax
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    MilestoneData,
    PlanData,
    PriorityData,
    SimState,
)
from coastmath.engine.waterfall import allocate_surplus, execute_drawdown
from tests.engine_support import fixture_to_plan_data
from tests.fixtures import load_standard_plan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_plan(**overrides) -> PlanData:
    """Build a minimal PlanData with sensible defaults, overridden by kwargs."""
    defaults = dict(
        plan_id="00000000-0000-4000-8000-000000000001",
        birth_year=1990,
        filing_status="single",
        life_expectancy=90,
        start_year=2025,
    )
    defaults.update(overrides)
    return PlanData(**defaults)


# ===========================================================================
# 1. Milestone evaluation tests
# ===========================================================================

class TestMilestoneEvaluation:
    def test_age_milestone_triggers_at_correct_year(self):
        ms = [MilestoneData(id="ret", name="Retirement", trigger_type="age", trigger_value=65)]
        state = SimState(year=2055)
        birth_year = 1990  # age 65 in 2055

        triggered = evaluate_milestones(state, ms, year=2055, birth_year=birth_year)
        assert triggered == ["ret"]
        assert "ret" in state.triggered_milestones

        # Should NOT trigger one year early
        state2 = SimState(year=2054)
        triggered2 = evaluate_milestones(state2, ms, year=2054, birth_year=birth_year)
        assert triggered2 == []

    def test_date_milestone_triggers(self):
        ms = [MilestoneData(id="move", name="Move", trigger_type="date", trigger_date="2030-06-15")]
        state = SimState(year=2030)

        triggered = evaluate_milestones(state, ms, year=2030, birth_year=1990)
        assert triggered == ["move"]

        # Should not trigger in 2029
        state2 = SimState(year=2029)
        triggered2 = evaluate_milestones(state2, ms, year=2029, birth_year=1990)
        assert triggered2 == []

    def test_net_worth_milestone_triggers(self):
        ms = [MilestoneData(id="fi", name="FI", trigger_type="net_worth", trigger_value=1_000_000)]
        state = SimState(
            year=2040,
            accounts={"a1": AccountInfo(balance=1_000_000, account_type="taxable_brokerage")},
        )

        triggered = evaluate_milestones(state, ms, year=2040, birth_year=1990)
        assert triggered == ["fi"]

        # Below threshold
        state2 = SimState(
            year=2040,
            accounts={"a1": AccountInfo(balance=999_999, account_type="taxable_brokerage")},
        )
        triggered2 = evaluate_milestones(state2, ms, year=2040, birth_year=1990)
        assert triggered2 == []

    def test_liquid_net_worth_expense_multiple_trigger(self):
        milestone = MilestoneData(
            id="fi",
            name="Financial independence",
            trigger_type="expense_multiple",
            metric="liquid_net_worth",
            expense_multiple=20,
        )
        above = SimState(
            year=2040,
            accounts={"portfolio": AccountInfo(balance=2_000_001, account_type="taxable_brokerage")},
        )
        exact = SimState(
            year=2040,
            accounts={"portfolio": AccountInfo(balance=2_000_000, account_type="taxable_brokerage")},
        )

        assert evaluate_milestones(
            above, [milestone], year=2040, birth_year=1990, annual_expenses=100_000,
        ) == ["fi"]
        assert evaluate_milestones(
            exact, [milestone], year=2040, birth_year=1990, annual_expenses=100_000,
        ) == []

    def test_relative_milestones_use_base_trigger_year(self):
        milestones = [
            MilestoneData(
                id="fi",
                name="FI",
                trigger_type="date",
                trigger_date="2026-01-01",
            ),
            MilestoneData(
                id="self_retirement",
                name="Self retirement",
                trigger_type="relative",
                relative_to_id="fi",
                offset_years=0,
            ),
            MilestoneData(
                id="spouse_retirement",
                name="Spouse retirement",
                trigger_type="relative",
                relative_to_id="fi",
                offset_years=3,
            ),
        ]
        state = SimState(year=2026)

        first = evaluate_milestones(state, milestones, year=2026, birth_year=1990)
        later = evaluate_milestones(state, milestones, year=2029, birth_year=1990)

        assert first == ["fi", "self_retirement"]
        assert later == ["spouse_retirement"]
        assert state.triggered_milestone_years == {
            "fi": 2026,
            "self_retirement": 2026,
            "spouse_retirement": 2029,
        }

    def test_milestone_triggers_only_once(self):
        ms = [MilestoneData(id="ret", name="Retirement", trigger_type="age", trigger_value=65)]
        state = SimState(year=2055)

        first = evaluate_milestones(state, ms, year=2055, birth_year=1990)
        assert first == ["ret"]

        # Second call same year — already triggered, returns empty
        second = evaluate_milestones(state, ms, year=2055, birth_year=1990)
        assert second == []

    @pytest.mark.parametrize(
        "start_id, end_id, triggered, expected",
        [
            # No start → active from beginning
            (None, None, set(), True),
            # No start, end triggered → inactive
            (None, "end", {"end"}, False),
            # Start not triggered → inactive
            ("start", None, set(), False),
            # Start triggered, no end → active
            ("start", None, {"start"}, True),
            # Start triggered, end not triggered → active
            ("start", "end", {"start"}, True),
            # Both triggered → inactive
            ("start", "end", {"start", "end"}, False),
        ],
    )
    def test_is_event_active_combinations(self, start_id, end_id, triggered, expected):
        assert is_event_active(start_id, end_id, triggered) is expected


# ===========================================================================
# 2. Tax engine tests
# ===========================================================================

class TestTaxEngine:
    def test_single_filer_known_income(self):
        # $100k single: 2026 std deduction $16,100, taxable $83,900
        # 12400 * 0.10 = 1240.00
        # (50400 - 12400) * 0.12 = 4560.00
        # (83900 - 50400) * 0.22 = 7370.00
        # Total = 13170.00
        result = calculate_tax(gross_income=100_000, deductions=0, filing_status="single")
        assert result.federal == pytest.approx(13_170.0, abs=1.0)
        assert result.effective_rate == pytest.approx(13_170.0 / 100_000, abs=0.001)
        assert result.marginal_rate == 0.22

    def test_married_joint_known_income(self):
        # $160k MFJ: 2026 std deduction $32,200, taxable $127,800
        # 24800 * 0.10 = 2480.00
        # (100800 - 24800) * 0.12 = 9120.00
        # (127800 - 100800) * 0.22 = 5940.00
        # Total = 17540.00
        result = calculate_tax(
            gross_income=160_000, deductions=0, filing_status="married_filing_jointly"
        )
        assert result.federal == pytest.approx(17_540.0, abs=1.0)
        assert result.effective_rate == pytest.approx(17_540.0 / 160_000, abs=0.001)
        assert result.marginal_rate == 0.22

    def test_mixed_w2_and_self_employment_share_social_security_wage_base(self):
        result = calculate_tax(
            gross_income=300_000,
            deductions=0,
            filing_status="single",
            earned_income=300_000,
            w2_income=200_000,
            self_employment_income=100_000,
        )
        # 2026 Social Security base is $184,500. W-2 wages consume the base
        # first, so the SE income owes Medicare/Additional Medicare but no
        # extra Social Security tax. Sources are in `_sources` in `tax_brackets_2026.json`.
        expected_ss = 184_500 * 0.062
        expected_medicare = 200_000 * 0.0145 + 92_350 * 0.029
        expected_additional_medicare = 92_350 * 0.009
        assert result.fica_tax == pytest.approx(
            expected_ss + expected_medicare + expected_additional_medicare,
            abs=0.01,
        )

    def test_traditional_ira_drawdown_is_taxable_ordinary_income(self):
        """Deficit-funding IRA withdrawals must feed back into ordinary tax."""
        plan = make_plan(
            birth_year=1959,  # age 66 in 2025: no early-withdrawal penalty
            life_expectancy=67,
            start_year=2025,
            expenses=[
                ExpenseData(
                    id="living",
                    name="Living expenses",
                    annual_amount=50_000,
                    inflation_linked=False,
                ),
            ],
            accounts={
                "trad": AccountInfo(balance=100_000, account_type="traditional_ira"),
            },
            drawdown_order=[DrawdownEntryData(rank=1, source_account_id="trad")],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
        )

        snap = run_simulation(plan).yearly_snapshots[0]

        # The engine iterates tax-on-tax drawdowns: a $50k expense funded
        # from a pre-tax IRA requires about $53.3k of taxable distributions.
        # At 66 the filer also gets the 2025 $2,000 age-65 standard deduction
        # addition and the $6,000 senior deduction (2025-2028):
        # IRS 2025 values: $15,750 basic + $2,000 aged + $6,000 senior.
        # tax = 1,192.50 + 12% x (W - 23,750 - 11,925), W = 50,000 + tax.
        expected_tax = (1_192.50 + .12 * (50_000 - 23_750 - 11_925)) / (1 - .12)
        assert snap.federal_tax == pytest.approx(expected_tax, abs=2.0)
        assert snap.taxes == pytest.approx(snap.federal_tax, abs=0.01)
        assert snap.accounts["trad"] == pytest.approx(100_000 - 50_000 - expected_tax, abs=3.0)

    def test_zero_income_zero_tax(self):
        result = calculate_tax(gross_income=0, deductions=0, filing_status="single")
        assert result.federal == 0.0
        assert result.effective_rate == 0.0
        assert result.marginal_rate == 0.0

    def test_zero_capital_gains_unchanged(self):
        """Backward compat: capital_gains=0 produces the same result as before capital gains."""
        result = calculate_tax(gross_income=100_000, deductions=0, filing_status="single")
        assert result.capital_gains_tax == 0.0
        assert result.total_tax == result.federal

    def test_ltcg_single_low_income_zero_rate(self):
        """$30k ordinary + $10k LTCG, single. Taxable ordinary = $15k.
        All LTCG falls within 0% bracket (up to $48,350). CG tax = $0."""
        result = calculate_tax(
            gross_income=30_000, deductions=0, filing_status="single",
            capital_gains=10_000,
        )
        assert result.capital_gains_tax == pytest.approx(0.0, abs=1.0)

    def test_ltcg_uses_unused_standard_deduction(self):
        """Unused standard deduction offsets capital gains before LTCG rates."""
        result = calculate_tax(
            gross_income=0, deductions=0, filing_status="single",
            capital_gains=70_000,
        )
        # $70k gains - $16,100 standard deduction = $53,900 taxable gains.
        # First $49,450 at 0%, remaining $4,450 at 15%.
        assert result.capital_gains_tax == pytest.approx(667.50, abs=1.0)

    def test_capital_gains_count_for_social_security_provisional_income(self):
        """Capital gains are part of provisional income for taxable SS."""
        result = calculate_tax(
            gross_income=13_000,
            deductions=0,
            filing_status="single",
            social_security_income=24_000,
            capital_gains=100_000,
        )
        assert result.agi > 13_000
        assert result.agi == pytest.approx(33_400, abs=1.0)

    def test_ltcg_single_stacking(self):
        """$60k ordinary + $50k LTCG, single. Taxable ordinary = $43,900.
        First $5,550 LTCG at 0% (up to $49,450), remaining $44,450 at 15%.
        CG tax = 44450 * 0.15 = $6,667.50."""
        result = calculate_tax(
            gross_income=60_000, deductions=0, filing_status="single",
            capital_gains=50_000,
        )
        assert result.capital_gains_tax == pytest.approx(6_667.50, abs=1.0)

    def test_ltcg_high_income_20_percent(self):
        """$600k ordinary + $100k LTCG, single. Taxable ordinary = $585k.
        All LTCG beyond 15% bracket ($533,400), so 100% at 20%.
        CG tax = 100000 * 0.20 = $20,000."""
        result = calculate_tax(
            gross_income=600_000, deductions=0, filing_status="single",
            capital_gains=100_000,
        )
        assert result.capital_gains_tax == pytest.approx(20_000.0, abs=1.0)

    def test_ltcg_included_in_total_tax(self):
        """total_tax should include both federal and capital gains tax."""
        result = calculate_tax(
            gross_income=60_000, deductions=0, filing_status="single",
            capital_gains=50_000,
        )
        assert result.total_tax == pytest.approx(
            result.federal + result.capital_gains_tax, abs=1.0,
        )

    # ── State tax tests ──

    def test_state_none_backward_compat(self):
        """state_code=None produces state=0 and an unchanged federal tax."""
        result = calculate_tax(gross_income=100_000, deductions=0, filing_status="single")
        assert result.state == 0.0
        assert result.federal == pytest.approx(13_170.0, abs=1.0)
        assert result.total_tax == pytest.approx(result.federal, abs=1.0)

    def test_state_no_income_tax(self):
        """TX has no income tax — state should be 0."""
        result = calculate_tax(
            gross_income=100_000, deductions=0, filing_status="single",
            state_code="TX",
        )
        assert result.state == 0.0

    def test_state_california_known_income(self):
        """CA $100k single: AGI=$100k, state deduction=$5,706, state taxable=$94,294.
        CA brackets (progressive):
          11079 * 0.01 = 110.79
          (26264-11079) * 0.02 = 303.70
          (41452-26264) * 0.04 = 607.52
          (57542-41452) * 0.06 = 965.40
          (72724-57542) * 0.08 = 1214.56
          (94294-72724) * 0.093 = 2006.01
        Total = 5207.98
        """
        result = calculate_tax(
            gross_income=100_000, deductions=0, filing_status="single",
            state_code="CA",
        )
        assert result.state == pytest.approx(5_207.98, abs=2.0)
        assert result.total_tax == pytest.approx(result.federal + result.state, abs=1.0)

    def test_state_flat_rate(self):
        """IL flat 4.95%, no standard deduction. $100k AGI → $4,950."""
        result = calculate_tax(
            gross_income=100_000, deductions=0, filing_status="single",
            state_code="IL",
        )
        assert result.state == pytest.approx(4_950.0, abs=1.0)

    def test_state_included_in_total_tax(self):
        """total_tax = federal + state + cg_tax."""
        result = calculate_tax(
            gross_income=100_000, deductions=0, filing_status="single",
            state_code="CA", capital_gains=20_000,
        )
        assert result.total_tax == pytest.approx(
            result.federal + result.state + result.capital_gains_tax, abs=1.0,
        )

    def test_state_custom_brackets_override(self):
        """Custom brackets via settings override default state brackets."""
        custom = [{"min": 0, "max": 999999999, "rate": 0.10}]
        result = calculate_tax(
            gross_income=100_000, deductions=0, filing_status="single",
            state_code="CA",
            settings={"state_brackets": custom},
        )
        # CA standard deduction $5,706, so state taxable = $94,294
        # Custom flat 10% → $9,429.40
        assert result.state == pytest.approx(9_429.40, abs=1.0)

    # ── 4.8.1: specific bracket accuracy tests ──

    def test_single_filer_50k(self):
        """$50k single: 2026 std deduction $16,100, taxable $33,900.
        12400 * 0.10 = 1240.00
        (33900 - 12400) * 0.12 = 2580.00
        Total = 3820.00"""
        result = calculate_tax(gross_income=50_000, deductions=0, filing_status="single")
        assert result.federal == pytest.approx(3_820.0, abs=1.0)
        assert result.marginal_rate == 0.12

    def test_married_filer_150k(self):
        """$150k MFJ: 2026 std deduction $32,200, taxable $117,800.
        24800 * 0.10 = 2480.00
        (100800 - 24800) * 0.12 = 9120.00
        (117800 - 100800) * 0.22 = 3740.00
        Total = 15340.00"""
        result = calculate_tax(
            gross_income=150_000, deductions=0, filing_status="married_filing_jointly",
        )
        assert result.federal == pytest.approx(15_340.0, abs=1.0)
        assert result.marginal_rate == 0.22

    def test_salt_cap_limits_deduction(self):
        """SALT deductions use the OBBBA 2026 $40,400 cap.
        $100k single, $50k SALT + $5k charitable + $5k mortgage.
        Capped SALT = $40,400; charitable $5k less the 2026 0.5%-of-AGI floor
        ($500, 26 USC 170(b)(1)(I)) = $4,500 → total itemized = $49,900 > std $16,100.
        Taxable = $50,100."""
        result = calculate_tax(
            gross_income=100_000, deductions=0, filing_status="single",
            itemized_deductions={"salt": 50_000, "charitable": 5_000, "mortgage_interest": 5_000},
        )
        assert result.deduction_used == "itemized"
        assert result.deduction_amount == pytest.approx(49_900.0, abs=1.0)
        assert result.taxable_income == pytest.approx(50_100.0, abs=1.0)
        # Verify it's NOT using uncapped $60k
        assert result.taxable_income != pytest.approx(40_000.0, abs=1.0)

    # ── 4.8.2: Roth conversion increases tax ──

    def test_roth_conversion_increases_tax(self):
        """Roth conversion adds to AGI, increasing federal tax."""
        base = calculate_tax(gross_income=50_000, deductions=0, filing_status="single")
        with_conversion = calculate_tax(
            gross_income=50_000, deductions=0, filing_status="single",
            roth_conversions=50_000,
        )
        assert with_conversion.agi == pytest.approx(100_000.0, abs=1.0)
        assert with_conversion.federal > base.federal
        # $50k + $50k Roth = $100k AGI, same as test_single_filer_known_income
        assert with_conversion.federal == pytest.approx(13_170.0, abs=1.0)


# ===========================================================================
# 3. Waterfall allocation tests
# ===========================================================================

class TestWaterfallAllocation:
    def _make_state(self, accounts: dict[str, float]) -> SimState:
        return SimState(
            year=2025,
            accounts={
                aid: AccountInfo(balance=bal, account_type="savings")
                for aid, bal in accounts.items()
            },
        )

    def test_surplus_allocates_in_priority_order(self):
        state = self._make_state({"a": 0, "b": 0, "c": 0})
        priorities = [
            PriorityData(priority_rank=1, target_account_id="a", max_annual_amount=None),
            PriorityData(priority_rank=2, target_account_id="b", max_annual_amount=None),
        ]
        result = allocate_surplus(1000, priorities, state)
        # All surplus goes to rank-1 (unlimited)
        assert result["a"] == 1000
        assert "b" not in result
        assert state.get_balance("a") == 1000

    def test_capped_priority_stops_at_max(self):
        state = self._make_state({"a": 0, "b": 0})
        priorities = [
            PriorityData(priority_rank=1, target_account_id="a", max_annual_amount=5000),
            PriorityData(priority_rank=2, target_account_id="b", max_annual_amount=None),
        ]
        result = allocate_surplus(10_000, priorities, state)
        assert result["a"] == 5000
        assert result["b"] == 5000
        assert state.get_balance("a") == 5000
        assert state.get_balance("b") == 5000

    def test_remaining_surplus_to_unlimited(self):
        state = self._make_state({"a": 0, "b": 0, "c": 0})
        priorities = [
            PriorityData(priority_rank=1, target_account_id="a", max_annual_amount=2000),
            PriorityData(priority_rank=2, target_account_id="b", max_annual_amount=3000),
            PriorityData(priority_rank=3, target_account_id="c", max_annual_amount=None),
        ]
        result = allocate_surplus(20_000, priorities, state)
        assert result["a"] == 2000
        assert result["b"] == 3000
        assert result["c"] == 15_000


# ===========================================================================
# 4. Drawdown tests
# ===========================================================================

class TestDrawdown:
    def _make_state(self, accounts: dict[str, float]) -> SimState:
        return SimState(
            year=2025,
            accounts={
                aid: AccountInfo(balance=bal, account_type="savings")
                for aid, bal in accounts.items()
            },
        )

    def test_drawdown_in_rank_order(self):
        state = self._make_state({"a": 10_000, "b": 10_000})
        order = [
            DrawdownEntryData(rank=1, source_account_id="a"),
            DrawdownEntryData(rank=2, source_account_id="b"),
        ]
        result, _ = execute_drawdown(5000, order, state)
        assert result["a"] == 5000
        assert "b" not in result
        assert state.get_balance("a") == 5000
        assert state.get_balance("b") == 10_000

    def test_drawdown_stops_when_covered(self):
        state = self._make_state({"a": 3000, "b": 10_000})
        order = [
            DrawdownEntryData(rank=1, source_account_id="a"),
            DrawdownEntryData(rank=2, source_account_id="b"),
        ]
        result, _ = execute_drawdown(5000, order, state)
        assert result["a"] == 3000
        assert result["b"] == 2000
        assert state.failure_year is None

    def test_drawdown_skips_empty_accounts(self):
        state = self._make_state({"a": 0, "b": 10_000})
        order = [
            DrawdownEntryData(rank=1, source_account_id="a"),
            DrawdownEntryData(rank=2, source_account_id="b"),
        ]
        result, _ = execute_drawdown(5000, order, state)
        assert "a" not in result
        assert result["b"] == 5000
        assert state.failure_year is None

    def test_drawdown_sets_failure_year(self):
        state = self._make_state({"a": 1000, "b": 2000})
        order = [
            DrawdownEntryData(rank=1, source_account_id="a"),
            DrawdownEntryData(rank=2, source_account_id="b"),
        ]
        execute_drawdown(10_000, order, state)
        assert state.failure_year == 2025


# ===========================================================================
# 5. Full simulation loop tests
# ===========================================================================

class TestFullSimulation:
    @pytest.fixture
    def standard_plan(self) -> PlanData:
        return fixture_to_plan_data(load_standard_plan(), guess_social_security=True)

    def test_full_sim_standard_fixture(self, standard_plan):
        result = run_simulation(standard_plan)
        expected_years = (standard_plan.birth_year + standard_plan.life_expectancy) - standard_plan.start_year
        assert len(result.yearly_snapshots) == expected_years
        assert result.yearly_snapshots[0].year == 2025
        assert result.yearly_snapshots[-1].year == 2025 + expected_years - 1
        assert result.metadata.start_year == 2025
        assert result.metadata.success is True

    def test_net_worth_grows_early_years(self, standard_plan):
        result = run_simulation(standard_plan)
        year_0_nw = result.yearly_snapshots[0].net_worth
        year_5_nw = result.yearly_snapshots[5].net_worth
        assert year_5_nw > year_0_nw

    def test_retirement_milestone_triggers(self, standard_plan):
        result = run_simulation(standard_plan)
        retirement_ms_id = "00000000-0000-4000-8000-000000000020"
        # Retirement at age 65 → year 2055, index = 2055 - 2025 = 30
        snapshot_2055 = result.yearly_snapshots[30]
        assert snapshot_2055.year == 2055
        assert retirement_ms_id in snapshot_2055.milestones_triggered

    def test_sim_no_income_no_accounts(self):
        plan = make_plan()
        result = run_simulation(plan)
        assert len(result.yearly_snapshots) > 0
        for snap in result.yearly_snapshots:
            assert snap.net_worth == 0.0
            assert snap.gross_income == 0.0

"""Tests for charity engine integration (QCD, DAF, direct giving)."""

import uuid

import pytest

from coastmath.engine.simulator import (
    _QCD_ANNUAL_CAP,
    _process_charitable_contributions,
    _process_qcds,
    run_simulation,
)
from coastmath.engine.tax_engine import calculate as calculate_tax
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    CharityData,
    PlanData,
    SimState,
)

# ---------------------------------------------------------------------------
# Tax engine: QCD offset reduces taxable RMD income
# ---------------------------------------------------------------------------


class TestQcdReducesTaxableIncome:
    def test_qcd_offset_lowers_agi(self):
        """$50k RMD with $30k QCD → only $20k of RMD is taxable."""
        result_no_qcd = calculate_tax(
            gross_income=0,
            deductions=0,
            filing_status="single",
            rmd_income=50_000,
            qcd_offset=0,
        )
        result_with_qcd = calculate_tax(
            gross_income=0,
            deductions=0,
            filing_status="single",
            rmd_income=50_000,
            qcd_offset=30_000,
        )
        # AGI should be reduced by the QCD amount
        assert result_with_qcd.agi == pytest.approx(result_no_qcd.agi - 30_000)
        # Tax should be lower
        assert result_with_qcd.total_tax < result_no_qcd.total_tax

    def test_qcd_offset_capped_at_rmd(self):
        """QCD offset cannot exceed RMD income in the tax calc."""
        result = calculate_tax(
            gross_income=0,
            deductions=0,
            filing_status="single",
            rmd_income=20_000,
            qcd_offset=50_000,  # exceeds RMD
        )
        # AGI should be 0, not negative (offset capped at rmd_income)
        assert result.agi == pytest.approx(0.0)

    def test_qcd_zero_offset_backward_compat(self):
        """Default qcd_offset=0 doesn't change existing behavior."""
        result_default = calculate_tax(
            gross_income=100_000,
            deductions=0,
            filing_status="single",
            rmd_income=50_000,
        )
        result_explicit = calculate_tax(
            gross_income=100_000,
            deductions=0,
            filing_status="single",
            rmd_income=50_000,
            qcd_offset=0,
        )
        assert result_default.total_tax == pytest.approx(result_explicit.total_tax)
        assert result_default.agi == pytest.approx(result_explicit.agi)


# ---------------------------------------------------------------------------
# Simulator: _process_qcds helper
# ---------------------------------------------------------------------------


def _make_state_with_ira(ira_balance: float, ira_id: str = "ira1") -> SimState:
    """Create a SimState with a single traditional IRA."""
    return SimState(
        year=2030,
        accounts={
            ira_id: AccountInfo(
                balance=ira_balance,
                account_type="traditional_ira",
            ),
        },
    )


class TestProcessQcds:
    def test_basic_qcd_distribution(self):
        """QCD calculates amount but does NOT withdraw (RMD step already did)."""
        state = _make_state_with_ira(500_000)
        entities = [
            CharityData(id="c1", name="Charity A", entity_type="qcd", annual_amount=30_000),
        ]
        result = _process_qcds(state, entities, rmd_amount=50_000, triggered_milestones=set())
        assert result == pytest.approx(30_000)
        # Balance unchanged — RMD withdrawal already covers the IRA debit
        assert state.accounts["ira1"].balance == pytest.approx(500_000)

    def test_qcd_cap_108k(self):
        """$150k QCD request → capped at $108k (IRS 2025 limit)."""
        state = _make_state_with_ira(500_000)
        entities = [
            CharityData(id="c1", name="Big Charity", entity_type="qcd", annual_amount=150_000),
        ]
        result = _process_qcds(state, entities, rmd_amount=200_000, triggered_milestones=set())
        assert result == pytest.approx(_QCD_ANNUAL_CAP)
        # No withdrawal — RMD step already handled it
        assert state.accounts["ira1"].balance == pytest.approx(500_000)

    def test_qcd_excess_over_rmd_is_withdrawn(self):
        """Pub. 590-B: QCDs can exceed the RMD, up to cap and IRA funds."""
        state = _make_state_with_ira(500_000)
        entities = [
            CharityData(id="c1", name="Charity", entity_type="qcd", annual_amount=80_000),
        ]
        result = _process_qcds(state, entities, rmd_amount=50_000, triggered_milestones=set())
        assert result == pytest.approx(80_000)
        assert state.accounts["ira1"].balance == pytest.approx(470_000)

    def test_qcd_counts_toward_rmd(self):
        """QCD satisfies RMD requirement — the distributed amount counts."""
        state = _make_state_with_ira(500_000)
        entities = [
            CharityData(id="c1", name="Charity", entity_type="qcd", annual_amount=50_000),
        ]
        rmd_amount = 50_000
        qcd = _process_qcds(state, entities, rmd_amount=rmd_amount, triggered_milestones=set())
        # QCD equals RMD — no additional distribution needed
        assert qcd == pytest.approx(rmd_amount)

    def test_qcd_from_ira_only(self):
        """QCD only considers traditional IRA balances, not Roth or 401k."""
        state = SimState(
            year=2030,
            accounts={
                "roth1": AccountInfo(balance=200_000, account_type="roth_ira"),
                "k401": AccountInfo(balance=200_000, account_type="traditional_401k"),
                "ira1": AccountInfo(balance=100_000, account_type="traditional_ira"),
            },
        )
        entities = [
            CharityData(id="c1", name="Charity", entity_type="qcd", annual_amount=50_000),
        ]
        result = _process_qcds(state, entities, rmd_amount=80_000, triggered_milestones=set())
        assert result == pytest.approx(50_000)
        # No balance changes — RMD step already handled withdrawal
        assert state.accounts["ira1"].balance == pytest.approx(100_000)
        assert state.accounts["roth1"].balance == pytest.approx(200_000)
        assert state.accounts["k401"].balance == pytest.approx(200_000)

    def test_qcd_limited_by_ira_balance(self):
        """QCD without an RMD is limited by available IRA balance."""
        state = _make_state_with_ira(20_000)
        entities = [
            CharityData(id="c1", name="Charity", entity_type="qcd", annual_amount=50_000),
        ]
        result = _process_qcds(state, entities, rmd_amount=0, triggered_milestones=set())
        assert result == pytest.approx(20_000)  # limited by balance
        # With no RMD, the QCD is withdrawn directly from the IRA.
        assert state.accounts["ira1"].balance == pytest.approx(0)

    def test_qcd_allowed_when_rmd_zero(self):
        """QCDs are allowed even without RMD (ages 70.5-72 under SECURE 2.0)."""
        state = _make_state_with_ira(500_000)
        entities = [
            CharityData(id="c1", name="Charity", entity_type="qcd", annual_amount=30_000),
        ]
        result = _process_qcds(state, entities, rmd_amount=0, triggered_milestones=set())
        assert result == pytest.approx(30_000)
        # When RMD=0, QCD withdraws directly from IRA
        assert state.accounts["ira1"].balance == pytest.approx(470_000)

    def test_non_qcd_entities_ignored(self):
        """DAF and direct entities are not processed by _process_qcds."""
        state = _make_state_with_ira(500_000)
        entities = [
            CharityData(id="c1", name="DAF", entity_type="daf", annual_amount=30_000),
            CharityData(id="c2", name="Direct", entity_type="direct", annual_amount=20_000),
        ]
        result = _process_qcds(state, entities, rmd_amount=50_000, triggered_milestones=set())
        assert result == pytest.approx(0)
        assert state.accounts["ira1"].balance == pytest.approx(500_000)

    def test_multiple_qcd_entities_summed(self):
        """Multiple QCD entities are summed together."""
        state = _make_state_with_ira(500_000)
        entities = [
            CharityData(id="c1", name="Charity A", entity_type="qcd", annual_amount=20_000),
            CharityData(id="c2", name="Charity B", entity_type="qcd", annual_amount=15_000),
        ]
        result = _process_qcds(state, entities, rmd_amount=50_000, triggered_milestones=set())
        assert result == pytest.approx(35_000)

    def test_inactive_qcd_ignored(self):
        """QCD entity outside its milestone range is not processed."""
        state = _make_state_with_ira(500_000)
        # This entity requires milestone "m1" to be triggered
        entities = [
            CharityData(
                id="c1", name="Charity", entity_type="qcd",
                annual_amount=30_000, start_milestone_id="m1",
            ),
        ]
        # m1 not triggered
        result = _process_qcds(state, entities, rmd_amount=50_000, triggered_milestones=set())
        assert result == pytest.approx(0)

        # m1 triggered
        result = _process_qcds(state, entities, rmd_amount=50_000, triggered_milestones={"m1"})
        assert result == pytest.approx(30_000)


# ---------------------------------------------------------------------------
# DAF / direct giving: _process_charitable_contributions helper
# ---------------------------------------------------------------------------


def _daf_plan(**overrides) -> PlanData:
    """Build a minimal PlanData for DAF testing."""
    defaults = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1990,
        filing_status="single",
        life_expectancy=93,
        start_year=2025,
        milestones=[],
        income_streams=[],
        expenses=[],
        priorities=[],
        drawdown_order=[],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
        accounts={},
        charity_entities=[],
    )
    defaults.update(overrides)
    return PlanData(**defaults)


class TestDAFDeductionWithinAGILimit:
    """Full deduction when contribution is under 60% of AGI."""

    def test_full_deduction(self):
        state = SimState(
            year=2025,
            accounts={
                "chk": AccountInfo(balance=50_000, account_type="checking"),
            },
        )
        plan = _daf_plan(
            accounts={"chk": AccountInfo(balance=50_000, account_type="checking")},
            charity_entities=[
                CharityData(id="daf1", name="DAF", entity_type="daf", annual_amount=10_000),
            ],
        )
        # AGI=100k → limit=60k. Contribution=10k → fully deductible.
        result = _process_charitable_contributions(
            state, plan, gross_income=100_000, newly_triggered=set(),
        )
        assert result.allowable_deduction == pytest.approx(10_000)
        assert len(result.committed_carryforward) == 0  # no excess


class TestDAFDeductionExceedsAGILimit:
    """Excess over 60% AGI should carry forward."""

    def test_excess_carries_forward(self):
        state = SimState(
            year=2025,
            accounts={
                "chk": AccountInfo(balance=200_000, account_type="checking"),
            },
        )
        plan = _daf_plan(
            accounts={"chk": AccountInfo(balance=200_000, account_type="checking")},
            charity_entities=[
                CharityData(id="daf1", name="DAF", entity_type="daf", annual_amount=40_000),
            ],
        )
        # AGI=50k → limit=30k. Contribution=40k → 30k deductible, 10k carry.
        result = _process_charitable_contributions(
            state, plan, gross_income=50_000, newly_triggered=set(),
        )
        assert result.allowable_deduction == pytest.approx(30_000)
        assert len(result.committed_carryforward) == 1
        assert result.committed_carryforward[0] == (2025, pytest.approx(10_000))


class TestDAFCarryforwardExpires:
    """Unused carry-forward should expire after 5 years."""

    def test_expires_after_5_years(self):
        state = SimState(
            year=2031,
            accounts={
                "chk": AccountInfo(balance=100_000, account_type="checking"),
            },
            daf_carryforward=[
                (2025, 5_000),  # 6 years old → should expire
                (2026, 3_000),  # 5 years old → at limit, should survive
            ],
        )
        plan = _daf_plan(
            accounts={"chk": AccountInfo(balance=100_000, account_type="checking")},
            charity_entities=[],
        )
        result = _process_charitable_contributions(
            state, plan, gross_income=100_000, newly_triggered=set(),
        )
        # Only the 2026 entry (5 years old) should survive and be used
        assert result.allowable_deduction == pytest.approx(3_000)
        # The expired 2025 entry should be gone from both branches
        committed_years = [yr for yr, _ in result.committed_carryforward]
        assert 2025 not in committed_years
        preserved_years = [yr for yr, _ in result.preserved_carryforward]
        assert 2025 not in preserved_years


class TestDAFDeductsFromAccount:
    """Account balance should decrease by contribution amount."""

    def test_balance_decreases(self):
        state = SimState(
            year=2025,
            accounts={
                "chk": AccountInfo(balance=50_000, account_type="checking"),
            },
        )
        plan = _daf_plan(
            accounts={"chk": AccountInfo(balance=50_000, account_type="checking")},
            charity_entities=[
                CharityData(id="daf1", name="DAF", entity_type="daf", annual_amount=10_000),
            ],
        )
        _process_charitable_contributions(
            state, plan, gross_income=100_000, newly_triggered=set(),
        )
        assert state.accounts["chk"].balance == pytest.approx(40_000)

    def test_deducts_from_brokerage_if_checking_insufficient(self):
        state = SimState(
            year=2025,
            accounts={
                "chk": AccountInfo(balance=3_000, account_type="checking"),
                "brk": AccountInfo(balance=50_000, account_type="taxable_brokerage", cost_basis=50_000),
            },
        )
        plan = _daf_plan(
            accounts={
                "chk": AccountInfo(balance=3_000, account_type="checking"),
                "brk": AccountInfo(balance=50_000, account_type="taxable_brokerage", cost_basis=50_000),
            },
            charity_entities=[
                CharityData(id="daf1", name="DAF", entity_type="daf", annual_amount=10_000),
            ],
        )
        _process_charitable_contributions(
            state, plan, gross_income=100_000, newly_triggered=set(),
        )
        # 3k from checking, 7k from brokerage
        assert state.accounts["chk"].balance == pytest.approx(0)
        # Brokerage withdrawal also triggers capital gains tracking,
        # so just check it decreased
        assert state.accounts["brk"].balance < 50_000


class TestDirectGivingNoCarryForward:
    """Direct giving gets deduction but no carry-forward for excess."""

    def test_no_carryforward(self):
        state = SimState(
            year=2025,
            accounts={
                "chk": AccountInfo(balance=100_000, account_type="checking"),
            },
        )
        plan = _daf_plan(
            accounts={"chk": AccountInfo(balance=100_000, account_type="checking")},
            charity_entities=[
                CharityData(id="dir1", name="Red Cross", entity_type="direct", annual_amount=50_000),
            ],
        )
        # AGI=50k → limit=30k. 50k contributed, 30k deductible, 20k excess.
        # Direct giving should NOT carry forward the excess.
        result = _process_charitable_contributions(
            state, plan, gross_income=50_000, newly_triggered=set(),
        )
        assert result.allowable_deduction == pytest.approx(30_000)
        assert len(result.committed_carryforward) == 0
        assert len(result.preserved_carryforward) == 0


class TestCharitableDeductionInTaxEngine:
    """charitable_deduction param triggers itemizing when beneficial."""

    def test_charitable_deduction_backward_compat(self):
        """Default charitable_deduction=0 doesn't change behavior."""
        r1 = calculate_tax(gross_income=100_000, deductions=0, filing_status="single")
        r2 = calculate_tax(
            gross_income=100_000, deductions=0, filing_status="single",
            charitable_deduction=0,
        )
        assert r1.total_tax == pytest.approx(r2.total_tax)

    def test_large_charitable_triggers_itemizing(self):
        """A large charitable deduction should trigger itemizing."""
        r_no_charity = calculate_tax(
            gross_income=200_000, deductions=0, filing_status="single",
        )
        r_with_charity = calculate_tax(
            gross_income=200_000, deductions=0, filing_status="single",
            charitable_deduction=25_000,
        )
        # 25k > standard deduction (~15.7k) → should itemize
        assert r_with_charity.deduction_used == "itemized"
        assert r_with_charity.total_tax < r_no_charity.total_tax


# ---------------------------------------------------------------------------
# DAF carryforward follows contribution limits regardless of deduction election
# ---------------------------------------------------------------------------


class TestDAFCarryforwardElection:
    """IRS IRM 4.19.15.21.4.2 consumes usable carryover in standard years too."""

    def test_standard_deduction_consumes_available_carryforward(self):
        """Choosing the standard deduction does not bank eligible gifts."""
        state = SimState(
            year=2025,
            accounts={
                "chk": AccountInfo(balance=100_000, account_type="checking"),
            },
            daf_carryforward=[
                (2023, 2_000),  # prior carryforward
            ],
        )
        plan = _daf_plan(
            accounts={"chk": AccountInfo(balance=100_000, account_type="checking")},
            charity_entities=[
                # Small DAF — won't beat the standard deduction (~15.7k single)
                CharityData(id="daf1", name="DAF", entity_type="daf", annual_amount=5_000),
            ],
        )
        result = _process_charitable_contributions(
            state, plan, gross_income=100_000, newly_triggered=set(),
        )
        # The deduction is computed (for tax engine to evaluate)
        assert result.allowable_deduction == pytest.approx(7_000)  # 2k prior + 5k current

        # Current gifts use room first, then prior carryover.
        # Both fit under 60% AGI limit (60k), so all consumed, no excess
        assert len(result.committed_carryforward) == 0

        # The legacy alias follows the same statutory calculation.
        assert result.preserved_carryforward == []

        # Account withdrawal still happened (real money left)
        assert state.accounts["chk"].balance == pytest.approx(95_000)

        # state.daf_carryforward was NOT mutated by the function
        assert state.daf_carryforward == [(2023, 2_000)]

    def test_itemized_deduction_commits_fifo(self):
        """When itemizing wins (large charitable), FIFO consumption is identical
        to prior behavior."""
        state = SimState(
            year=2025,
            accounts={
                "chk": AccountInfo(balance=200_000, account_type="checking"),
            },
            daf_carryforward=[
                (2023, 5_000),
            ],
        )
        plan = _daf_plan(
            accounts={"chk": AccountInfo(balance=200_000, account_type="checking")},
            charity_entities=[
                # Large DAF — will beat standard deduction
                CharityData(id="daf1", name="DAF", entity_type="daf", annual_amount=30_000),
            ],
        )
        result = _process_charitable_contributions(
            state, plan, gross_income=200_000, newly_triggered=set(),
        )
        # 5k prior + 30k current = 35k total; AGI limit = 120k → fully deductible
        assert result.allowable_deduction == pytest.approx(35_000)

        # Committed: all consumed via FIFO, no excess
        assert len(result.committed_carryforward) == 0

        assert result.preserved_carryforward == result.committed_carryforward

    def test_expiry_pruned_in_both_branches(self):
        """Entries older than 5 years are pruned from BOTH committed and
        preserved carryforward lists."""
        state = SimState(
            year=2031,
            accounts={
                "chk": AccountInfo(balance=100_000, account_type="checking"),
            },
            daf_carryforward=[
                (2025, 8_000),  # 6 years old → expired
                (2026, 3_000),  # 5 years old → at limit, survives
                (2028, 4_000),  # 3 years old → survives
            ],
        )
        plan = _daf_plan(
            accounts={"chk": AccountInfo(balance=100_000, account_type="checking")},
            charity_entities=[
                CharityData(id="daf1", name="DAF", entity_type="daf", annual_amount=2_000),
            ],
        )
        result = _process_charitable_contributions(
            state, plan, gross_income=100_000, newly_triggered=set(),
        )
        # Expired 2025 entry should not appear in either branch
        committed_years = {yr for yr, _ in result.committed_carryforward}
        preserved_years = {yr for yr, _ in result.preserved_carryforward}
        assert 2025 not in committed_years
        assert 2025 not in preserved_years

        # Unexpired entries were all usable under the current limit.
        assert result.preserved_carryforward == []
        assert result.prior_carryforward == [(2026, 3_000), (2028, 4_000)]

    def test_no_daf_entities_empty_preserved(self):
        """Direct gifts consume current room before prior DAF carryovers."""
        state = SimState(
            year=2025,
            accounts={
                "chk": AccountInfo(balance=100_000, account_type="checking"),
            },
            daf_carryforward=[
                (2023, 1_500),
            ],
        )
        plan = _daf_plan(
            accounts={"chk": AccountInfo(balance=100_000, account_type="checking")},
            charity_entities=[
                # Only direct — no DAF
                CharityData(id="dir1", name="Direct", entity_type="direct", annual_amount=5_000),
            ],
        )
        result = _process_charitable_contributions(
            state, plan, gross_income=100_000, newly_triggered=set(),
        )
        # Prior DAF carryforward still used in deduction calc
        assert result.allowable_deduction == pytest.approx(6_500)  # 1.5k prior + 5k current

        # Committed: prior consumed via FIFO
        assert len(result.committed_carryforward) == 0

        assert result.preserved_carryforward == []



# ---------------------------------------------------------------------------
# 2026 charitable deduction rules and QCD eligibility
# ---------------------------------------------------------------------------

from coastmath.engine.simulator import qcd_eligible  # noqa: E402
from coastmath.engine.tax_engine import calculate  # noqa: E402
from coastmath.engine.types import DrawdownEntryData  # noqa: E402


class TestCharitableRules2026:
    def test_itemized_charitable_deduction_reduced_by_half_percent_floor(self):
        """26 USC 170(b)(1)(I): only the amount above 0.5% of AGI is deductible."""
        agi = 200_000.0
        itemizing = calculate(agi, 0, "married_filing_jointly", charitable_deduction=60_000,
                              itemized_deductions={"mortgage_interest": 10_000}, tax_year=2026)
        assert itemizing.deduction_used == "itemized"
        assert itemizing.deduction_amount == pytest.approx(10_000 + 60_000 - 0.005 * agi)
        pre_2026 = calculate(agi, 0, "married_filing_jointly", charitable_deduction=60_000,
                             itemized_deductions={"mortgage_interest": 10_000}, tax_year=2025)
        assert pre_2026.deduction_amount == pytest.approx(70_000)

    def test_non_itemizer_cash_deduction_applies_to_direct_gifts_only(self):
        """26 USC 170(p): $1,000/$2,000 for cash gifts when taking the standard deduction."""
        base = calculate(100_000, 0, "married_filing_jointly", tax_year=2026)
        with_direct = calculate(100_000, 0, "married_filing_jointly", charitable_deduction=5_000,
                                charitable_direct_cash=5_000, tax_year=2026)
        assert with_direct.deduction_used == "standard"
        assert with_direct.deduction_amount == pytest.approx(base.deduction_amount + 2_000)
        assert with_direct.federal < base.federal
        # A DAF-only contribution provides no non-itemizer deduction.
        daf_only = calculate(100_000, 0, "married_filing_jointly", charitable_deduction=5_000,
                             charitable_direct_cash=0, tax_year=2026)
        assert daf_only.deduction_amount == pytest.approx(base.deduction_amount)
        single = calculate(100_000, 0, "single", charitable_direct_cash=5_000, tax_year=2026)
        assert single.deduction_amount == pytest.approx(calculate(100_000, 0, "single", tax_year=2026).deduction_amount + 1_000)


class TestQcdEligibility:
    def test_age_threshold_depends_on_birth_month(self):
        assert qcd_eligible(70, birth_month=6) is True
        assert qcd_eligible(70, birth_month=7) is False
        assert qcd_eligible(71, birth_month=12) is True
        assert qcd_eligible(69, birth_month=1) is False
        assert qcd_eligible(70, birth_month=None) is False  # unknown month is conservative
        assert qcd_eligible(None, None) is True  # legacy callers

    def test_qcd_not_processed_before_seventy_and_a_half(self):
        plan = PlanData(
            plan_id=str(uuid.uuid4()), birth_year=1970, filing_status="single",
            life_expectancy=75, start_year=2035, milestones=[], income_streams=[],
            expenses=[], priorities=[],
            drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash")],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
            accounts={
                "ira": AccountInfo(balance=500_000, account_type="traditional_ira"),
                "cash": AccountInfo(balance=200_000, account_type="checking"),
            },
            charity_entities=[CharityData(id="q", name="QCD", entity_type="qcd", annual_amount=10_000)],
        )
        snaps = run_simulation(plan).yearly_snapshots
        by_year = {s.year: s for s in snaps}
        # 2035: age 65 -> no QCD, IRA untouched (no RMD yet either).
        assert by_year[2035].accounts["ira"] == pytest.approx(500_000)
        # Born January (unknown month -> treated as later half): eligible at 71 (2041).
        assert by_year[2040].accounts["ira"] == pytest.approx(500_000)
        assert by_year[2041].accounts["ira"] == pytest.approx(490_000)

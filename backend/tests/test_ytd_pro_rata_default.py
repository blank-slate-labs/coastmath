"""Mid-year plans without year-to-date history impute the pre-start share.

When ``tax_settings.year_to_date`` is absent and the plan starts mid-year, the
engine imputes the pre-start share of each income stream as history, treats
the pre-start share of the full-year liability as already paid, and labels
the opening snapshot ``ytd_imputed_pro_rata``. The year's tax lines keep the
entered-history convention: the full calendar-year liability. Expected
amounts come from the 2026 IRS tables, never from another planner's output.

Reference household: MFJ, $180,000 W-2, no other income, start
2026-09-09 (114/365 of the year remain).
  Standard deduction 2026 MFJ  32,200  -> taxable 147,800
  10% to 24,800 = 2,480; 12% to 100,800 = 9,120; 22% on 47,000 = 10,340
  Federal income tax           21,940
  FICA 7.65% x 180,000         13,770
  Full-year liability          35,710
  Post-start share x 114/365   11,153 (settled from post-start cash)
Before this change the engine taxed only the 114/365 of wages from zero
history with a full deduction: 2,402 federal + 4,301 FICA = 6,703.
"""

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    MilestoneData,
)
from tests.engine_support import YTD_FRACTION, ytd_household

FULL_YEAR_FEDERAL = 21_940
FULL_YEAR_FICA = 13_770
FULL_YEAR_TAX = FULL_YEAR_FEDERAL + FULL_YEAR_FICA
PRE_START_WAGES = 180_000 * (1 - YTD_FRACTION)
LABEL = "ytd_imputed_pro_rata"


def entered_history(**extra):
    return {"year_to_date": {"tax_year": 2026, "gross_income": PRE_START_WAGES,
                             "w2_income_by_owner": {"self": PRE_START_WAGES}, **extra}}


def test_midyear_start_without_history_reports_the_full_year_liability():
    result = run_simulation(ytd_household())
    opening, second = result.yearly_snapshots[:2]
    # Same lines the entered-history path reports for the same facts.
    entered = run_simulation(ytd_household(tax_settings=entered_history())).yearly_snapshots[0]
    assert opening.federal_tax == pytest.approx(entered.federal_tax, abs=.01)
    assert opening.fica_tax == pytest.approx(entered.fica_tax, abs=.01)
    assert opening.federal_tax == pytest.approx(FULL_YEAR_FEDERAL, abs=.01)
    assert opening.fica_tax == pytest.approx(FULL_YEAR_FICA, abs=.01)
    assert opening.taxes == pytest.approx(FULL_YEAR_TAX, abs=.01)
    assert opening.calendar_year_gross_income == pytest.approx(180_000, abs=.01)
    assert entered.calendar_year_gross_income == pytest.approx(180_000, abs=.01)
    # The post-start share is what settles from post-start cash.
    assert opening.post_start_taxes == pytest.approx(FULL_YEAR_TAX * YTD_FRACTION, abs=.01)
    assert opening.post_start_taxes == pytest.approx(11_153, abs=50)
    assert opening.cash_flow.tax_delta == pytest.approx(-opening.post_start_taxes, abs=.01)
    assert opening.tax_balance == pytest.approx(0, abs=.01)
    assert opening.warnings == [LABEL]
    assert opening.model_dump()["warnings"] == [LABEL]
    assert opening.model_dump()["post_start_taxes"] == pytest.approx(opening.post_start_taxes)
    assert opening.model_dump()["calendar_year_gross_income"] == pytest.approx(180_000, abs=.01)
    # The annual liability is divided by the imputed full-year income, not
    # the salary received after the plan start date.
    assert opening.effective_rate == pytest.approx(FULL_YEAR_TAX / 180_000, abs=.0001)
    assert entered.effective_rate == pytest.approx(FULL_YEAR_TAX / 180_000, abs=.0001)
    assert second.warnings == [] and second.post_start_taxes is None
    assert any(w.startswith("Midyear projection:") and "pro-rata" in w for w in result.metadata.warnings)


def test_pro_rata_cash_is_the_post_start_share():
    opening = run_simulation(ytd_household()).yearly_snapshots[0]
    post_start_wages = 180_000 * YTD_FRACTION
    # Zero withholding settles the post-start share in-year; no expenses or growth.
    assert opening.cash_flow.tax_withheld == 0
    assert opening.accounts["cash"] == pytest.approx(100_000 + post_start_wages - FULL_YEAR_TAX * YTD_FRACTION, abs=.01)


def test_post_start_realized_gain_tax_is_fully_settled_after_start():
    common = dict(
        accounts={"brokerage": AccountInfo(balance=100_000, account_type="taxable_brokerage",
                                           cost_basis=100_000)},
        expenses=[ExpenseData(id="living", name="Living", annual_amount=200_000,
                              inflation_linked=False)],
        drawdown_order=[DrawdownEntryData(rank=1, source_account_id="brokerage")],
    )
    base = ytd_household(**common)
    gain = ytd_household(plan_id=base.plan_id, accounts={"brokerage": AccountInfo(
        balance=100_000, account_type="taxable_brokerage", cost_basis=0,
    )}, expenses=common["expenses"], drawdown_order=common["drawdown_order"])
    no_gain = run_simulation(base).yearly_snapshots[0]
    with_gain = run_simulation(gain).yearly_snapshots[0]

    added_full_year_tax = with_gain.taxes - no_gain.taxes
    assert with_gain.capital_gains_tax > no_gain.capital_gains_tax
    assert added_full_year_tax == pytest.approx(with_gain.capital_gains_tax, abs=.01)
    assert with_gain.post_start_taxes - no_gain.post_start_taxes == pytest.approx(added_full_year_tax, abs=.01)
    assert no_gain.cash_flow.tax_delta - with_gain.cash_flow.tax_delta == pytest.approx(added_full_year_tax, abs=.01)


def test_later_years_match_a_january_start_to_the_cent():
    imputed = run_simulation(ytd_household()).yearly_snapshots
    january = run_simulation(ytd_household(first_year_fraction=1.0)).yearly_snapshots
    for later, reference in zip(imputed[1:4], january[1:4], strict=True):
        assert later.year == reference.year
        assert later.federal_tax == pytest.approx(reference.federal_tax, abs=.005)
        assert later.fica_tax == pytest.approx(reference.fica_tax, abs=.005)
        assert later.taxes == pytest.approx(reference.taxes, abs=.005)
        assert later.warnings == [] and later.post_start_taxes is None


def test_pre_start_share_follows_the_stream_window():
    # A job that starts in July has only July and August before a September
    # 9 start: 180,000 x (6/12 - 114/365) is imputed, not 180,000 x 251/365.
    plan = ytd_household(milestones=[MilestoneData(id="job", name="New job", trigger_type="date", trigger_date="2026-07-01")],
                income_streams=[IncomeData(id="salary", name="Salary", annual_amount=180_000,
                                           growth_rate=0, start_milestone_id="job", start_month=7)])
    opening = run_simulation(plan).yearly_snapshots[0]
    full_year_wages = 180_000 * 6 / 12
    taxable = full_year_wages - 32_200  # 57,800
    federal = 24_800 * .10 + (taxable - 24_800) * .12  # 2,480 + 3,960
    assert opening.federal_tax == pytest.approx(federal, abs=.01)
    assert opening.fica_tax == pytest.approx(full_year_wages * .0765, abs=.01)
    assert opening.warnings == [LABEL]


def test_social_security_history_is_included_in_full_year_tax_and_rate():
    streams = [
        IncomeData(id="salary", name="Salary", annual_amount=180_000, growth_rate=0),
        IncomeData(id="ss", name="Social Security", annual_amount=36_000, growth_rate=0,
                   is_social_security=True, is_earned_income=False, tax_category="social_security"),
    ]
    partial = run_simulation(ytd_household(income_streams=streams, birth_year=1958, life_expectancy=75)).yearly_snapshots[0]
    full_year = run_simulation(ytd_household(income_streams=streams, birth_year=1958, life_expectancy=75, first_year_fraction=1.0)).yearly_snapshots[0]

    assert partial.federal_tax == pytest.approx(full_year.federal_tax, abs=.01)
    assert partial.fica_tax == pytest.approx(full_year.fica_tax, abs=.01)
    assert partial.taxes == pytest.approx(full_year.taxes, abs=.01)
    assert partial.gross_income == pytest.approx((180_000 + 36_000) * YTD_FRACTION, abs=.01)
    assert partial.calendar_year_gross_income == pytest.approx(216_000, abs=.01)
    assert partial.effective_rate == pytest.approx(partial.taxes / 216_000, abs=.0001)
    assert partial.cash_flow.tax_delta == pytest.approx(-partial.post_start_taxes, abs=.01)


def test_state_and_local_liability_lines_stay_full_year():
    settings = {"state_payroll_coverage": [{
        "owner": "self", "state_code": "CA", "start_year": 2026, "ca_sdi": True,
    }]}
    local_tax = {"jurisdiction": "custom", "earned_income_rate": .01}
    partial = run_simulation(ytd_household(state_code="CA", local_tax=local_tax, tax_settings=settings)).yearly_snapshots[0]
    full_year = run_simulation(ytd_household(state_code="CA", local_tax=local_tax, tax_settings=settings,
                                    first_year_fraction=1.0)).yearly_snapshots[0]

    assert partial.state_tax > 0 and partial.local_tax > 0
    for field in ("federal_tax", "fica_tax", "state_tax", "local_tax", "taxes"):
        assert getattr(partial, field) == pytest.approx(getattr(full_year, field), abs=.01)
    assert partial.post_start_taxes == pytest.approx(partial.taxes * YTD_FRACTION, abs=.01)

    state_payroll_cost = next(flow.amount for flow in partial.cash_flow.expenses if flow.name == "California SDI")
    full_state_payroll_cost = next(flow.amount for flow in full_year.cash_flow.expenses if flow.name == "California SDI")
    assert state_payroll_cost == pytest.approx(full_state_payroll_cost * YTD_FRACTION, abs=.01)


def test_rmds_do_not_create_inferred_account_history():
    plan = ytd_household(
        birth_year=1950,
        spouse_birth_year=None,
        filing_status="single",
        life_expectancy=85,
        income_streams=[],
        accounts={
            "ira": AccountInfo(balance=1_000_000, account_type="traditional_ira"),
            "cash": AccountInfo(balance=100_000, account_type="checking"),
        },
    )
    opening = run_simulation(plan).yearly_snapshots[0]

    assert opening.gross_income > 0  # the modeled RMD starts with the projection
    assert opening.federal_tax > 0
    assert opening.warnings == [] and opening.post_start_taxes == pytest.approx(opening.taxes, abs=.01)
    assert opening.cash_flow.tax_delta == pytest.approx(-opening.taxes, abs=.01)


def test_zero_valued_explicit_history_suppresses_imputation():
    plan = ytd_household(tax_settings={"year_to_date": {
        "tax_year": 2026,
        "gross_income": 0,
        "social_security_income": 0,
        "w2_income_by_owner": {"self": 0},
        "tax_paid": 0,
    }})
    opening = run_simulation(plan).yearly_snapshots[0]

    assert opening.fica_tax == pytest.approx(180_000 * YTD_FRACTION * .0765, abs=.01)
    assert opening.federal_tax < FULL_YEAR_FEDERAL
    assert opening.calendar_year_gross_income == pytest.approx(opening.gross_income, abs=.01)
    assert opening.warnings == [] and opening.post_start_taxes == pytest.approx(opening.taxes, abs=.01)
    assert opening.cash_flow.tax_delta == pytest.approx(-opening.taxes, abs=.01)


def test_future_stream_imputes_nothing():
    # Nothing was earned before the start, so the opening year is unchanged
    # and keeps the zero-history warning.
    plan = ytd_household(milestones=[MilestoneData(id="job", name="New job", trigger_type="date", trigger_date="2026-11-01")],
                income_streams=[IncomeData(id="salary", name="Salary", annual_amount=180_000,
                                           growth_rate=0, start_milestone_id="job", start_month=11)])
    result = run_simulation(plan)
    opening = result.yearly_snapshots[0]
    assert opening.warnings == [] and opening.post_start_taxes == pytest.approx(opening.taxes, abs=.01)
    assert opening.fica_tax == pytest.approx(180_000 * 2 / 12 * .0765, abs=.01)
    assert any("missing history is zero" in w for w in result.metadata.warnings)


def test_entered_history_is_unchanged():
    # The same facts entered by hand keep the existing convention: the full
    # calendar-year liability is reported and the entered payments are
    # credited through the settlement, with no imputation label.
    result = run_simulation(ytd_household(tax_settings=entered_history(tax_paid=24_557)))
    opening = result.yearly_snapshots[0]
    assert opening.federal_tax == pytest.approx(FULL_YEAR_FEDERAL, abs=.01)
    assert opening.fica_tax == pytest.approx(FULL_YEAR_FICA, abs=.01)
    assert opening.calendar_year_gross_income == pytest.approx(180_000, abs=.01)
    assert opening.cash_flow.tax_delta == pytest.approx(24_557 - FULL_YEAR_TAX, abs=.01)
    assert opening.warnings == [] and opening.post_start_taxes == pytest.approx(FULL_YEAR_TAX - 24_557, abs=.01)
    assert not any(w.startswith("Midyear projection:") for w in result.metadata.warnings)


def test_january_start_is_unchanged():
    result = run_simulation(ytd_household(first_year_fraction=1.0))
    opening = result.yearly_snapshots[0]
    assert opening.federal_tax == pytest.approx(FULL_YEAR_FEDERAL, abs=.01)
    assert opening.fica_tax == pytest.approx(FULL_YEAR_FICA, abs=.01)
    assert opening.warnings == [] and opening.post_start_taxes is None
    assert not any(w.startswith("Midyear projection:") for w in result.metadata.warnings)

"""The served cash-flow Sankey graph (coastmath.engine.cash_flow_graph).

Engine runs check that every hub balances and that a paycheck's deductions
leave gross income before after-tax cash; synthetic breakdowns pin each
routing rule, including the cases a plan rarely produces.
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PlanData,
    PriorityData,
)
from coastmath.schemas.simulation import (
    CashFlowBreakdownSchema,
    NamedAmountSchema,
    TransferFlowSchema,
)

ZERO_GROWTH = AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0)


def flows(graph) -> dict[tuple[str, str], float]:
    return {(item.source, item.target): item.amount for item in graph.links}


def assert_well_formed(graph) -> None:
    ids = [item.id for item in graph.nodes]
    assert len(ids) == len(set(ids))
    totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for item in graph.links:
        assert item.source in ids and item.target in ids
        assert item.amount > 0
        totals[item.source][1] += item.amount
        totals[item.target][0] += item.amount
    for node in graph.nodes:
        incoming, outgoing = totals[node.id]
        if node.group == "hub":
            assert incoming == pytest.approx(outgoing, abs=1.0), node.id
        else:
            # Sources only send and destinations only receive, so the graph has no cycle.
            assert incoming == 0 or outgoing == 0, node.id


def worker_plan(**overrides) -> PlanData:
    values = dict(
        plan_id="00000000-0000-0000-0000-0000000000a1", birth_year=1980, filing_status="single",
        life_expectancy=48, start_year=2026, assumptions=ZERO_GROWTH,
        income_streams=[IncomeData("salary", "Salary", 100_000, growth_rate=0.0, withholding_percent=0.20)],
        accounts={
            "cash": AccountInfo(10_000, "checking", name="Checking"),
            "k401": AccountInfo(0, "traditional_401k", name="401(k)"),
            "brokerage": AccountInfo(0, "taxable", name="Brokerage"),
        },
        expenses=[
            ExpenseData("rent", "Rent", 30_000, inflation_linked=False, category="essential"),
            ExpenseData("health", "Health premium", 6_000, inflation_linked=False, category="essential",
                        is_payroll_deduction=True, tied_income_id="salary"),
        ],
        priorities=[
            PriorityData(1, target_account_id="k401", priority_type="income_percent", source_income_id="salary",
                         employee_rate=0.10, employer_match_rate=0.04),
            PriorityData(2, target_account_id="brokerage"),
        ],
        drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "brokerage")],
    )
    values.update(overrides)
    return PlanData(**values)


def test_paycheck_deductions_leave_gross_income_before_after_tax_cash():
    snap = run_simulation(worker_plan()).yearly_snapshots[1]
    cf = snap.cash_flow
    graph = cf.graph
    assert_well_formed(graph)
    links = flows(graph)
    names = {item.id: item.name for item in graph.nodes}

    # The deferral, the payroll-deducted premium and the year's tax all come out of pay.
    assert links[("hub:gross", "to:k401")] == pytest.approx(10_000)
    assert links[("hub:gross", "expense:Health premium")] == pytest.approx(6_000)
    assert links[("hub:gross", "tax:taxes")] == pytest.approx(snap.taxes)
    assert ("hub:cash", "tax:taxes") not in links
    # Employer money goes straight into the plan, outside gross pay.
    assert links[("employer:k401", "to:k401")] == pytest.approx(4_000)
    assert ("income:Employer Match: 401(k)", "hub:gross") not in links
    assert names["employer:k401"] == "Employer contributions"
    # Take-home pay: salary less the paycheck's deductions and tax.
    take_home = 100_000 - 10_000 - 6_000 - snap.taxes
    assert links[("hub:gross", "hub:cash")] == pytest.approx(take_home)
    assert links[("hub:cash", "expense:Rent")] == pytest.approx(30_000)
    cash_out = sum(amount for (source, _), amount in links.items() if source == "hub:cash")
    assert cash_out == pytest.approx(take_home, abs=1.0)
    assert names["hub:gross"] == "Gross income" and names["hub:cash"] == "After-tax cash"
    # The engine still reports the premium for the graph and the deduction total.
    assert [(row.name, row.source) for row in cf.payroll_expenses] == [("Health premium", "payroll")]
    assert cf.payroll_deductions == pytest.approx(16_000)


def test_withholding_and_refund_net_to_the_tax_actually_paid():
    over = run_simulation(worker_plan()).yearly_snapshots[1]
    under = run_simulation(worker_plan(income_streams=[
        IncomeData("salary", "Salary", 100_000, growth_rate=0.0, withholding_percent=0.0)])).yearly_snapshots[1]
    for snap in (over, under):
        assert flows(snap.cash_flow.graph)[("hub:gross", "tax:taxes")] == pytest.approx(snap.taxes)
        assert not any(item.id == "tax:refund" for item in snap.cash_flow.graph.nodes)
    assert over.cash_flow.tax_delta > 0 > under.cash_flow.tax_delta


def test_every_year_balances_from_paycheck_to_required_distributions():
    plan = PlanData(
        plan_id="00000000-0000-0000-0000-0000000000a2", birth_year=1958, filing_status="single",
        life_expectancy=78, start_year=2026,
        income_streams=[
            IncomeData("salary", "Salary", 90_000, end_milestone_id=None, growth_rate=0.0, withholding_percent=0.15),
            IncomeData("ss", "Social Security", 30_000, growth_rate=0.0, is_social_security=True, is_earned_income=False),
        ],
        accounts={
            "cash": AccountInfo(20_000, "checking", name="Checking"),
            "ira": AccountInfo(600_000, "traditional_ira", name="IRA"),
            "roth": AccountInfo(50_000, "roth_ira", name="Roth IRA"),
            "brokerage": AccountInfo(200_000, "taxable", cost_basis=100_000, name="Brokerage"),
        },
        expenses=[ExpenseData("living", "Living", 80_000, category="essential")],
        priorities=[PriorityData(1, target_account_id="brokerage")],
        drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "brokerage"), DrawdownEntryData(3, "ira"),
                        DrawdownEntryData(4, "roth")],
    )
    snapshots = run_simulation(plan).yearly_snapshots
    assert len(snapshots) == 10
    for snap in snapshots:
        assert_well_formed(snap.cash_flow.graph)
    rmd_years = [snap for snap in snapshots if any(row.source == "rmd" for row in snap.cash_flow.income_sources)]
    assert rmd_years
    rmd_node = next(item for item in rmd_years[0].cash_flow.graph.nodes if item.id == "income:RMD")
    assert rmd_node.group == "saving"


def breakdown(**values) -> CashFlowBreakdownSchema:
    return CashFlowBreakdownSchema(**values)


def row(name: str, amount: float, **values) -> NamedAmountSchema:
    return NamedAmountSchema(name=name, amount=amount, **values)


def test_tax_beyond_gross_income_comes_out_of_after_tax_cash():
    cf = breakdown(
        income_sources=[row("Dividends", 1_000)],
        drawdowns=[row("Brokerage", 50_000, account_id="b", account_name="Brokerage")],
        expenses=[row("Living", 47_000, category="essential")],
        tax_delta=-3_000,
    )
    links = flows(cf.graph)
    assert links[("hub:gross", "tax:taxes")] == pytest.approx(1_000)
    assert links[("hub:cash", "tax:taxes")] == pytest.approx(2_000)
    assert links[("from:b", "hub:cash")] == pytest.approx(50_000)
    assert ("hub:gross", "hub:cash") not in links
    assert_well_formed(cf.graph)


def test_pretax_distributions_join_gross_income_and_other_withdrawals_join_cash():
    cf = breakdown(
        drawdowns=[row("IRA", 40_000, category="pretax", account_id="ira", account_name="IRA"),
                   row("Roth IRA", 10_000, account_id="roth", account_name="Roth IRA")],
        expenses=[row("Living", 44_000, category="essential")],
        tax_delta=-6_000,
    )
    links = flows(cf.graph)
    assert links[("from:ira", "hub:gross")] == pytest.approx(40_000)
    assert links[("from:roth", "hub:cash")] == pytest.approx(10_000)
    assert links[("hub:gross", "tax:taxes")] == pytest.approx(6_000)
    assert links[("hub:gross", "hub:cash")] == pytest.approx(34_000)
    assert_well_formed(cf.graph)


def test_a_net_refund_enters_after_tax_cash():
    # Tax paid before the projection started exceeded the rest of the year's liability.
    cf = breakdown(income_sources=[row("Salary", 10_000)], expenses=[row("Living", 10_500, category="essential")],
                   tax_delta=500)
    links = flows(cf.graph)
    assert links[("tax:refund", "hub:cash")] == pytest.approx(500)
    assert not any(item.id == "tax:taxes" for item in cf.graph.nodes)
    assert_well_formed(cf.graph)


def test_estimated_payments_and_penalties_are_tax_flows():
    cf = breakdown(income_sources=[row("Consulting", 100_000)], estimated_tax_payments=12_000, tax_delta=-1_000,
                   underpayment_penalty=40, early_withdrawal_penalty=500,
                   drawdowns=[row("401(k)", 5_000, category="pretax", account_id="k", account_name="401(k)")],
                   expenses=[row("Living", 91_460, category="essential")])
    links = flows(cf.graph)
    assert links[("hub:gross", "tax:taxes")] == pytest.approx(13_000)
    assert links[("hub:cash", "tax:underpayment_penalty")] == pytest.approx(40)
    assert links[("hub:cash", "tax:early_withdrawal_penalty")] == pytest.approx(500)
    assert {item.group for item in cf.graph.nodes if item.id.startswith("tax:")} == {"tax"}
    assert_well_formed(cf.graph)


def test_state_payroll_premiums_are_withheld_from_pay_as_spending():
    cf = breakdown(income_sources=[row("Salary", 100_000)], tax_delta=-20_000,
                   expenses=[row("CA SDI", 1_300, category="state_payroll_tax"), row("Living", 78_700, category="essential")])
    links = flows(cf.graph)
    assert links[("hub:gross", "expense:CA SDI")] == pytest.approx(1_300)
    assert links[("hub:gross", "hub:cash")] == pytest.approx(78_700)
    # The ledger counts these premiums as spending, so the diagram does too.
    assert next(item for item in cf.graph.nodes if item.id == "expense:CA SDI").group == "spending"
    assert_well_formed(cf.graph)


def test_transfers_move_between_accounts_and_leftovers_balance_cash():
    cf = breakdown(
        income_sources=[row("Salary", 50_000)], expenses=[row("Living", 30_000, category="essential")], tax_delta=-5_000,
        transfers=[TransferFlowSchema(source_account_id="ira", target_account_id="roth", amount=20_000,
                                      source_account_name="IRA", target_account_name="Roth IRA")],
    )
    links = flows(cf.graph)
    assert links[("from:ira", "to:roth")] == pytest.approx(20_000)
    assert links[("hub:cash", "saving:surplus")] == pytest.approx(15_000)
    short = breakdown(income_sources=[row("Pension", 20_000)], expenses=[row("Living", 26_000, category="essential")])
    assert flows(short.graph)[("shortfall", "hub:cash")] == pytest.approx(6_000)
    assert_well_formed(cf.graph)
    assert_well_formed(short.graph)


def test_streams_sharing_a_name_keep_their_own_nodes():
    cf = breakdown(income_sources=[row("Salary", 60_000), row("Salary", 40_000)],
                   expenses=[row("Living", 100_000, category="essential")])
    links = flows(cf.graph)
    assert links[("income:Salary", "hub:gross")] == pytest.approx(60_000)
    assert links[("income:Salary#2", "hub:gross")] == pytest.approx(40_000)


def test_the_graph_is_serialized_with_the_breakdown():
    cf = breakdown(income_sources=[row("Salary", 1_000)], expenses=[row("Living", 1_000, category="essential")])
    data = cf.model_dump(mode="json")
    assert data["graph"]["links"][0] == {"source": "income:Salary", "target": "hub:gross", "amount": 1_000}
    assert "payroll_expenses" not in data

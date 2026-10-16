"""One year's cash flow as a Sankey graph: sources, two hubs, destinations.

Every client draws this graph as served, so the routing below is the single
definition of where a year's money went:

- **Gross income** collects income streams and distributions from pre-tax
  accounts (RMDs, a 72(t) series, traditional withdrawals), which are ordinary
  income (IRS Pub. 590-B, https://www.irs.gov/publications/p590b; Pub. 575,
  https://www.irs.gov/publications/p575).
- What a paycheck withholds leaves gross income before it reaches the
  household: payroll contributions (pre-tax and Roth deferrals), payroll-
  deducted expenses, state payroll premiums and the year's taxes. Elective
  deferrals and section 125 benefits are paid out of wages by the employer
  (26 U.S.C. 3121(v)(1)(A), 3121(a)(5)(G),
  https://www.law.cornell.edu/uscode/text/26/3121), and wage withholding is
  collected at the source (26 U.S.C. 3402,
  https://www.law.cornell.edu/uscode/text/26/3402).
- **After-tax cash** is what is left, plus withdrawals from cash, Roth and
  taxable accounts and any net refund. It pays spending, after-tax saving and
  penalties; anything left over or missing balances it.
- Employer contributions never enter gross pay; they go straight into the
  plan account.

Taxes are the cash paid toward the year's tax: withholding and estimated
payments less the balance at filing (``tax_delta``, refund positive). The split
between withholding and settlement is payment timing, shown by the tax tools
rather than here. Taxes come out of gross income first and out of after-tax
cash only when gross income cannot cover them (for example capital-gains tax
on a brokerage sale), so every hub balances by construction.

Node ids are stable from year to year (``income:Salary``, ``to:<account id>``),
so a client can animate one year into another.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol

Group = Literal["income", "tax", "saving", "spending", "shortfall", "hub"]

GROSS = "hub:gross"
CASH = "hub:cash"
GROSS_NAME = "Gross income"
CASH_NAME = "After-tax cash"
#: Smallest amount drawn as a flow; smaller rows are rounding residue.
MIN_FLOW = 0.005
#: A cash-hub imbalance up to this many dollars is rounding, not a surplus.
RESIDUAL_TOLERANCE = 1.0
#: Income rows that are distributions from the household's own pre-tax accounts.
DISTRIBUTION_SOURCES = frozenset({"rmd", "sepp"})


class _Row(Protocol):
    name: str
    amount: float
    category: str | None
    account_id: str | None
    account_name: str | None
    source: str | None


class _Transfer(Protocol):
    source_account_id: str
    target_account_id: str
    amount: float
    source_account_name: str | None
    target_account_name: str | None


class _Breakdown(Protocol):
    income_sources: list[_Row]
    tax_withheld: float
    tax_delta: float
    early_withdrawal_penalty: float
    expenses: list[_Row]
    payroll_expenses: list[_Row]
    contributions: list[_Row]
    transfers: list[_Transfer]
    drawdowns: list[_Row]
    estimated_tax_payments: float
    underpayment_penalty: float


@dataclass
class FlowNode:
    id: str
    name: str
    group: Group


@dataclass
class FlowLink:
    source: str
    target: str
    amount: float


@dataclass
class FlowGraph:
    nodes: list[FlowNode] = field(default_factory=list)
    links: list[FlowLink] = field(default_factory=list)


def taxes_paid(flow: _Breakdown) -> float:
    """Net cash paid toward the year's tax; negative for a net refund."""
    return flow.tax_withheld + (flow.estimated_tax_payments or 0.0) - flow.tax_delta


def build_cash_flow_graph(flow: _Breakdown) -> FlowGraph:
    nodes: dict[str, FlowNode] = {}
    amounts: dict[tuple[str, str], float] = {}
    income_ids: dict[str, int] = {}

    def node(node_id: str, name: str, group: Group) -> str:
        nodes.setdefault(node_id, FlowNode(node_id, name, group))
        return node_id

    def link(source: str, target: str, amount: float) -> None:
        if amount >= MIN_FLOW:
            amounts[(source, target)] = amounts.get((source, target), 0.0) + amount

    def income_node(name: str, group: Group) -> str:
        # Two streams may share a name; each keeps its own node.
        count = income_ids.get(name, 0) + 1
        income_ids[name] = count
        return node(f"income:{name}" if count == 1 else f"income:{name}#{count}", name, group)

    def account_label(row: _Row) -> tuple[str, str]:
        return row.account_id or row.name, row.account_name or row.name

    def into_account(row: _Row) -> str:
        key, name = account_label(row)
        return node(f"to:{key}", name, "saving")

    def out_of_account(row: _Row) -> str:
        key, name = account_label(row)
        return node(f"from:{key}", name, "saving")

    gross = node(GROSS, GROSS_NAME, "hub")
    cash = node(CASH, CASH_NAME, "hub")

    # Money in. Employer income rows are deposited below without passing through pay.
    for row in flow.income_sources:
        if row.source != "employer" and row.amount > 0:
            link(income_node(row.name, "saving" if row.source in DISTRIBUTION_SOURCES else "income"), gross, row.amount)
    for row in flow.drawdowns:
        link(out_of_account(row), gross if row.category == "pretax" else cash, row.amount)

    # Out of pay before the household sees it, in paycheck order, then out of cash.
    # Nodes are created in that order too, so destinations paid from pay list first.
    for row in flow.contributions:
        if row.source == "employer":
            key, _ = account_label(row)
            link(node(f"employer:{key}", "Employer contributions", "income"), into_account(row), row.amount)
    paycheck = [(into_account(row), row.amount) for row in flow.contributions if row.source == "payroll"]
    paycheck += [(node(f"expense:{row.name}", row.name, "spending"), row.amount) for row in flow.payroll_expenses or ()]
    # State payroll premiums (CA SDI, WA Paid Leave) are withheld from pay; the ledger counts them
    # as spending, not tax, so they keep the spending colour.
    paycheck += [(node(f"expense:{row.name}", row.name, "spending"), row.amount)
                 for row in flow.expenses if row.category == "state_payroll_tax"]
    taxes = taxes_paid(flow)
    if taxes > 0:
        paycheck.append((node("tax:taxes", "Taxes", "tax"), taxes))
    else:
        link(node("tax:refund", "Tax refund", "tax"), cash, -taxes)
    from_cash = [(node(f"expense:{row.name}", row.name, "spending"), row.amount)
                 for row in flow.expenses if row.category != "state_payroll_tax"]
    from_cash += [(into_account(row), row.amount) for row in flow.contributions if row.source not in ("employer", "payroll")]
    from_cash.append((node("tax:early_withdrawal_penalty", "Early withdrawal penalty", "tax"), flow.early_withdrawal_penalty or 0.0))
    from_cash.append((node("tax:underpayment_penalty", "Underpayment penalty", "tax"), flow.underpayment_penalty or 0.0))

    remaining = _total(amounts, target=gross)
    for target, amount in paycheck:
        if amount < MIN_FLOW:
            continue
        from_pay = min(amount, max(remaining, 0.0))
        remaining -= from_pay
        link(gross, target, from_pay)
        link(cash, target, amount - from_pay)
    link(gross, cash, remaining)
    for target, amount in from_cash:
        link(cash, target, amount)

    # Account-to-account moves (conversions, rebalancing) bypass both hubs.
    for transfer in flow.transfers:
        link(node(f"from:{transfer.source_account_id}", transfer.source_account_name or transfer.source_account_id, "saving"),
             node(f"to:{transfer.target_account_id}", transfer.target_account_name or transfer.target_account_id, "saving"),
             transfer.amount)

    residual = _total(amounts, target=cash) - _total(amounts, source=cash)
    if residual > RESIDUAL_TOLERANCE:
        link(cash, node("saving:surplus", "Unallocated surplus", "saving"), residual)
    elif residual < -RESIDUAL_TOLERANCE:
        link(node("shortfall", "Shortfall", "shortfall"), cash, -residual)

    used = {end for pair in amounts for end in pair}
    return FlowGraph(
        nodes=[item for item in nodes.values() if item.id in used],
        links=[FlowLink(source, target, amount) for (source, target), amount in amounts.items()],
    )


def _total(amounts: dict[tuple[str, str], float], *, source: str | None = None, target: str | None = None) -> float:
    pairs: Iterable[tuple[tuple[str, str], float]] = amounts.items()
    return sum(amount for (start, end), amount in pairs
               if (source is None or start == source) and (target is None or end == target))

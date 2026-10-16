import type { Article } from "../help_types";
import { Callout, DataTable, Figure, HelpLink, Ledger, Steps, UIPath } from "../help_kit";
import { Waterfall } from "../help_charts";

const workingYear = [
  { label: "Salary", value: 120000, color: "blue" as const },
  { label: "401(k) deferral", value: -12000, color: "cyan" as const },
  { label: "Taxes", value: -24110, color: "orange" as const },
  { label: "Spending", value: -67329, color: "magenta" as const },
  { label: "Saved to brokerage", value: 16561, color: "cyan" as const, total: true },
];

const article: Article = {
  intro: (
    <>
      <p>
        The Cash flow panel on the Overview tab follows one year’s money. Income flows into gross
        income. What a paycheck takes leaves from there: workplace deferrals, expenses paid through
        payroll and the year’s taxes. The rest becomes after-tax cash, which pays spending and funds
        your savings rules. Withdrawals from cash, Roth and taxable accounts flow into after-tax
        cash. If it still can’t cover the year, the gap shows as a shortfall.
      </p>
      <p>
        Amounts are future (nominal) dollars for that year, even when the rest of the Overview shows
        today’s dollars. A first year that starts after January 1 covers only the months from the
        start date.
      </p>
    </>
  ),
  sections: [
    {
      id: "open-a-year",
      title: "Open a year",
      body: (
        <>
          <Steps>
            <li>
              On the Overview, choose the year on the net worth chart, with the ‹ and › buttons on
              the year ledger, or on the age bar that pins to the top as you scroll.
            </li>
            <li>
              Find the <em>Cash flow</em> panel below the chart. Its header names the year, your age
              and, for a partial first year, the dates and share of the year it covers.
            </li>
            <li>
              Switch between <em>Diagram</em> and <em>List</em>. Narrow screens open the list, which
              groups the flows by where they start.
            </li>
            <li>
              Hover over a band or node for its amount and share, or choose <em>Show data table</em>{" "}
              for every flow with its <em>From</em>, <em>To</em>, <em>Amount</em> and <em>Share</em>
              .
            </li>
          </Steps>
          <p>
            <em>Share</em> is a flow’s share of everything that entered the year: income, employer
            contributions, withdrawals and any net tax refund.
          </p>
        </>
      ),
    },
    {
      id: "how-the-flows-connect",
      title: "How the flows connect",
      body: (
        <>
          <DataTable
            caption="Nodes in the cash-flow diagram"
            columns={[
              { key: "node", label: "Node" },
              { key: "in", label: "Money in" },
              { key: "out", label: "Money out" },
            ]}
            rows={[
              {
                node: "Gross income",
                in: "Each income source: pay, Social Security, pensions, taxable dividends and interest, and withdrawals from pre-tax accounts, required distributions included",
                out: "Workplace deferrals (pre-tax and Roth) to their accounts, expenses and state premiums paid through payroll, the year’s taxes, and the rest to after-tax cash",
              },
              {
                node: "After-tax cash",
                in: "Gross income after deferrals and taxes, withdrawals from cash, Roth and taxable accounts, a net tax refund, any shortfall",
                out: "Each expense, deposits (savings rules, reinvested dividends), early withdrawal and underpayment penalties, tax that gross income couldn’t cover, unallocated surplus",
              },
            ]}
            note="Employer contributions go straight to their account and pass through neither hub. An account shows up on the right when it receives money and on the left when money is withdrawn from it. Transfers and conversions between accounts appear as their own account-to-account flows; they aren’t income or spending."
          />
          <p>
            Band colors mark five groups: income, taxes, savings and investments, spending, and
            shortfall. A flow passes through more than one node, so the groups overlap. Don’t add
            them together.
          </p>
          <p>
            <em>Taxes</em> is the tax paid for the year: withholding and estimated payments, plus
            the balance owed or less the refund at settlement. It leaves gross income the way a
            paycheck withholds it. Tax that gross income can’t cover, such as capital gains tax on a
            brokerage sale, comes out of after-tax cash. How it splits between withholding and
            settlement is in <HelpLink to="tax-payments-and-settlement" />.
          </p>
        </>
      ),
    },
    {
      id: "trace-a-working-year",
      title: "Trace a working year",
      body: (
        <>
          <Figure
            title="Where a $120,000 salary went in 2026"
            caption="18% withholding, a 10% traditional 401(k) deferral and $67,329 of spending, including $19,329 of mortgage payments. The 4% employer match, $4,800, goes straight to the 401(k) and never passes through gross income or after-tax cash."
            table={{
              columns: [
                { key: "label", label: "Step" },
                { key: "value", label: "Amount", format: "usd" },
              ],
              rows: workingYear.map((step) => ({ label: step.label, value: step.value })),
            }}
          >
            <Waterfall
              steps={workingYear}
              label="Waterfall of a 2026 salary: $120,000 less a $12,000 401(k) deferral, $24,110 of taxes and $67,329 spending leaves $16,561 saved to brokerage"
            />
          </Figure>
          <p>
            The deferral and the year’s $24,110 tax, $14,930 federal income tax plus $9,180 payroll
            tax, leave gross income, so $83,890 reaches after-tax cash. $21,600 of the tax was
            withheld and $2,510 was owed at settlement. The $16,561 left after spending is the
            year’s net cash flow; a rule sending remaining surplus to brokerage took all of it.
          </p>
          <p>
            Beside the diagram, <em>Surplus allocation</em> lists each savings rule in order with
            its deposit. A rule that received nothing says why: no surplus remained, an earlier rule
            used it, a contribution limit or income limit applied, or the rule is outside its
            milestone window. <em>Edit income allocation</em> opens the rules; see{" "}
            <HelpLink to="savings-rules" />.
          </p>
        </>
      ),
    },
    {
      id: "trace-a-retirement-year",
      title: "Trace a retirement year",
      body: (
        <>
          <p>
            In a year when income doesn’t cover spending and tax, net cash flow is negative and
            withdrawals fill the gap in your withdrawal order. The panel beside the diagram becomes{" "}
            <em>Funded from accounts</em> and lists each withdrawal.
          </p>
          <Ledger
            title="Example: 2048, age 68"
            rows={[
              { label: "Social Security", value: 57483 },
              {
                op: "−",
                label: "Spending",
                value: 111302,
                detail: "Household costs, travel and mortgage payments",
              },
              {
                op: "−",
                label: "Tax owed at settlement",
                value: 8719,
                detail: "Nothing was withheld",
              },
              { op: "=", label: "Net cash flow", value: -62538 },
              { op: "→", label: "Withdrawal from the traditional 401(k)", value: 62538 },
            ]}
            note="The same household, retired at 60 and claiming Social Security at 67."
          />
          <p>
            The withdrawal is sized to cover the tax it creates. A withdrawal from a pre-tax account
            is ordinary income, so it enters gross income and its tax leaves from there: the
            diagram’s gross income is $120,021, the Social Security plus the 401(k) withdrawal, the
            same as the year ledger’s <em>Income</em>. Withdrawals from cash, Roth and taxable
            accounts enter after-tax cash instead. Never add the ledger’s <em>Income</em> and{" "}
            <em>Withdrawals</em> together.
          </p>
          <Callout kind="where">
            <p>
              The order accounts are drawn in is set in <UIPath steps={["Drawdown order"]} />; see{" "}
              <HelpLink to="withdrawal-order" />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "when-the-numbers-look-wrong",
      title: "When the numbers look wrong",
      body: (
        <>
          <ul>
            <li>
              <strong>A shortfall node appears.</strong> After-tax cash couldn’t be covered even
              after withdrawals. The amount is spending that went unpaid that year; see{" "}
              <HelpLink to="unfunded-expenses" />.
            </li>
            <li>
              <strong>A withdrawal matches an equal unallocated surplus.</strong> This is a year
              repaying spending left unpaid in an earlier year: the surplus is deposited, then
              withdrawn to clear the carried shortfall.
            </li>
            <li>
              <strong>Spending is larger than your expenses.</strong> Spending also includes loan
              payments, property costs, health coverage and charitable gifts. State payroll premiums
              count as spending, not taxes.
            </li>
            <li>
              <strong>An expense leaves gross income.</strong> Expenses paid through payroll, such
              as insurance premiums, come out of pay before after-tax cash; see{" "}
              <HelpLink to="payroll-deductions" />.
            </li>
            <li>
              <strong>The first year looks small.</strong> It covers only the months after the start
              date; the year ledger shows the full-year pace.
            </li>
          </ul>
        </>
      ),
    },
  ],
};

export default article;

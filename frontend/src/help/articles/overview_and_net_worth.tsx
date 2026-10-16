import type { Article } from "../help_types";
import { Callout, DataTable, Formula, HelpLink, Ledger, Op, Steps, UIPath, V } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        The Overview tab shows one steady-return projection of your plan. Its net worth line reads
        each year at December 31, starting from the balances on your plan’s start date. Choosing a
        year on the chart also sets the year ledger beside it, the cash-flow diagram and the marker
        on the income and taxes chart below.
      </p>
      <p>
        In net worth, pre-tax accounts count at their full balance, homes and other real assets
        count at their projected value, and spending the plan couldn’t pay is subtracted like a
        debt.
      </p>
    </>
  ),
  sections: [
    {
      id: "what-the-overview-shows",
      title: "What the overview shows",
      body: (
        <>
          <ul>
            <li>
              <strong>Net worth</strong>: the projection line, with milestones and events marked on
              it and listed in a strip below. <em>Show data table</em> lists net worth, income,
              expenses, taxes and cash flow for every year.
            </li>
            <li>
              <strong>The year ledger</strong>: the selected year’s <em>Year-end balances</em> (each
              account, real assets, debts, investment growth) and its <em>Cash flow</em> (income,
              withdrawals, taxes, spending, net cash flow).
            </li>
            <li>
              <strong>Cash flow</strong>: where that year’s money came from and went; see{" "}
              <HelpLink to="cash-flow-view" />.
            </li>
            <li>
              <strong>Income &amp; taxes</strong>: calendar-year gross income and full-year taxes,
              with effective and marginal rates below.
            </li>
            <li>
              <strong>Estate</strong>: what the estate is worth after debts, estate tax and
              settlement costs at the end of the plan; see{" "}
              <HelpLink to="estate-tax-and-net-estate" />.
            </li>
          </ul>
          <p>
            When the projection relies on simplifications that affect your plan, a{" "}
            <em>Model assumptions and limitations</em> list appears below the ledger. Read it before
            relying on the affected years.
          </p>
          <h3>Choose a year</h3>
          <Steps>
            <li>
              Click or tap a year on the net worth chart. Hovering previews a year without selecting
              it.
            </li>
            <li>
              Step one year at a time with the ‹ and › buttons on the ledger, or with the arrow keys
              after focusing the chart.
            </li>
            <li>
              Further down the page, use the age bar that pins to the top once the chart scrolls out
              of view.
            </li>
          </Steps>
        </>
      ),
    },
    {
      id: "what-counts-toward-net-worth",
      title: "What counts toward net worth",
      body: (
        <>
          <Formula result="Net worth">
            <V>Cash and investments</V>
            <Op>+</Op>
            <V>Real assets</V>
            <Op>−</Op>
            <V>Debts</V>
            <Op>−</Op>
            <V>Unfunded spending carried</V>
          </Formula>
          <ul>
            <li>
              <strong>Cash and investments</strong> is every account’s year-end balance: checking,
              savings, brokerage, retirement accounts, HSAs and 529 plans. Traditional balances are
              not reduced for the income tax due when they’re withdrawn. Surplus that no allocation
              rule takes and that has no cash account to go to is kept as unallocated cash, which
              also counts.
            </li>
            <li>
              <strong>Real assets</strong> are homes and other property at their projected value. A
              sold asset leaves, and its proceeds arrive in an account; see{" "}
              <HelpLink to="homes-and-real-assets" />.
            </li>
            <li>
              <strong>Debts</strong> are remaining loan balances after the year’s payments; see{" "}
              <HelpLink to="mortgages-and-loans" />.
            </li>
            <li>
              <strong>Unfunded spending carried</strong> is spending the plan couldn’t pay, carried
              until later cash repays it; see <HelpLink to="unfunded-expenses" />.
            </li>
          </ul>
          <p>
            Each year’s income tax is settled within that year, so year-end net worth carries no tax
            bill or refund.
          </p>
          <Ledger
            title="Example: net worth at the end of 2026"
            rows={[
              {
                label: "Cash and investments",
                value: 298069,
                detail: "Checking $20,000 · Traditional 401(k) $176,257 · Brokerage $101,812",
              },
              {
                op: "+",
                label: "Real assets",
                value: 412000,
                detail: "Home, opening value $400,000, growing 3% a year",
              },
              {
                op: "−",
                label: "Debts",
                value: 245550,
                detail: "Mortgage, opening balance $250,000",
              },
              { op: "−", label: "Unfunded spending carried", value: 0 },
              {
                op: "=",
                label: "Net worth",
                value: 464519,
                detail: "Up $64,519 from $400,000 on January 1",
              },
            ]}
            note="A 46-year-old saving from a $120,000 salary, projected in future dollars with 6% stock growth."
          />
          <Callout kind="boundary">
            <p>
              Net worth is not an after-tax figure. To see what heirs would receive after estate tax
              and, optionally, their income tax on inherited pre-tax balances, read the Estate card.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "year-ledger-rates",
      title: "Rates and figures in the year ledger",
      body: (
        <>
          <DataTable
            caption="Year ledger figures that are calculated rather than copied"
            columns={[
              { key: "row", label: "Row" },
              { key: "meaning", label: "Meaning" },
            ]}
            rows={[
              {
                row: "Change",
                meaning:
                  "Net worth minus the previous year-end’s, or minus opening net worth in the first year.",
              },
              {
                row: "Investment growth",
                meaning:
                  "Balance growth from returns, dividends and interest, including growth on money deposited or withdrawn during the year.",
              },
              {
                row: "Withdrawal rate",
                meaning: "Withdrawals ÷ cash and investments at the start of the year.",
              },
              {
                row: "Effective rate",
                meaning:
                  "Full-year taxes ÷ calendar-year gross income, including taxable withdrawals, employer contributions and realized gains.",
              },
              {
                row: "Marginal rate",
                meaning:
                  "The federal ordinary-income bracket your taxable income reaches. It excludes state tax.",
              },
              {
                row: "Net cash flow",
                meaning:
                  "Cash left over, or needed, after taxes and spending and before savings rules and withdrawals.",
              },
              {
                row: "Savings rate excl. payroll",
                meaning:
                  "Positive net cash flow ÷ income; a year without a surplus shows 0%. Checkup’s rate adds payroll contributions.",
              },
              {
                row: "Partial year",
                meaning:
                  "In a first year that starts after January 1, the share of the year covered, with full-year income and spending paces.",
              },
            ]}
          />
          <p>
            To see how <em>Spending</em>, <em>Effective tax rate</em> and{" "}
            <em>Savings rate excl. payroll</em> are defined, open{" "}
            <UIPath steps={["Overview", "Overview display preferences"]} /> at the bottom of the
            tab.
          </p>
        </>
      ),
    },
    {
      id: "dollars-shown",
      title: "Future dollars and today’s dollars",
      body: (
        <>
          <p>
            The <em>Future dollars</em> and <em>Today’s $</em> switch above the net worth chart
            changes the dollars on the net worth chart, the year ledger, the income and taxes chart,
            and the annual and printable reports. Today’s dollars are dollars of the plan’s start
            year, deflated by your inflation assumption; see{" "}
            <HelpLink to="todays-and-future-dollars" />.
          </p>
          <p>
            The cash-flow diagram, the Tax tools tab, the Estate card and recorded actual balances
            always show future (nominal) dollars. The cash-flow header adds “nominal” while today’s
            dollars are on.
          </p>
        </>
      ),
    },
    {
      id: "compare-with-a-baseline",
      title: "Compare with a baseline",
      body: (
        <>
          <p>
            <em>Keep forecast for comparison</em> freezes the current projection as a dashed
            baseline. Edit the plan and the chart shows both lines; the header states the difference
            in net worth in the last year both cover. <em>Compare with another plan…</em> draws one
            of your other saved plans as the baseline instead. The comparison clears when you reload
            or switch plans; <em>Stop comparing</em> clears it now. For a lasting comparison, see{" "}
            <HelpLink to="compare-plans" />.
          </p>
        </>
      ),
    },
    {
      id: "plan-status",
      title: "Plan status under the plan name",
      body: (
        <>
          <p>
            When a projection needs attention, a label appears under the plan name with an
            explanation below it:
          </p>
          <ul>
            <li>
              <strong>Spending unfunded from</strong> a year: cash and investments ran out and some
              spending went unpaid. See <HelpLink to="unfunded-expenses" />.
            </li>
            <li>
              <strong>Net worth negative from</strong> a year: spending stays funded, but debts
              exceed everything owned.
            </li>
            <li>
              <strong>Projection invalid from</strong> a year: a balance grew beyond any plausible
              value, usually from a loan rate, growth rate or payment entry. Don’t rely on any
              figure until it’s fixed.
            </li>
          </ul>
          <p>
            A funded plan shows no label. It means spending is paid in every year of this one
            projection with steady returns, not that the plan is likely to succeed; see{" "}
            <HelpLink to="plan-vs-chance-of-success" />.
          </p>
        </>
      ),
    },
  ],
};

export default article;

import type { Article } from "../help_types";
import { Callout, DataTable, Formula, HelpLink, Ledger, Op, UIPath, V } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        The wellness scorecard grades nine ratios from your plan’s projection against two thresholds
        each. A ratio at or past the better threshold grades Strong, one between the two grades
        Fair, and one short of both grades Needs attention. Every figure reads a value the
        projection already reports; the scorecard never changes the projection.
      </p>
    </>
  ),
  sections: [
    {
      id: "metrics",
      title: "What each metric reads",
      body: (
        <>
          <DataTable
            caption="Scorecard metrics"
            columns={[
              { key: "metric", label: "Metric" },
              { key: "definition", label: "Definition" },
              { key: "year", label: "Year it reads" },
              { key: "bands", label: "Fair / Strong" },
              { key: "source", label: "Threshold source" },
            ]}
            rows={[
              {
                metric: "Savings rate",
                definition:
                  "Payroll contributions (yours and your employer’s) plus the year’s positive surplus ÷ gross income. Payroll expenses such as premiums don’t count. Only while someone has earned income.",
                year: "First plan year",
                bands: "10% / 20% or more",
                source: "CoastMath planning threshold",
              },
              {
                metric: "Emergency fund",
                definition: "Opening checking and savings balances ÷ monthly essential spending.",
                year: "First plan year",
                bands: "3 / 6 months or more",
                source: "CoastMath planning threshold",
              },
              {
                metric: "Debt payments to income",
                definition:
                  "Scheduled loan payments ÷ gross income. Only when a loan has a payment due.",
                year: "First plan year",
                bands: "36% / 20% or less",
                source:
                  "36%: the maximum total debt ratio for manually underwritten conforming mortgages. 20%: CoastMath planning threshold",
              },
              {
                metric: "Savings to income",
                definition:
                  "Account balances (cash, taxable, tax-deferred and tax-free; 529s excluded) ÷ earned income for a full year. Home equity and debt don’t count. Only while someone has earned income.",
                year: "Plan start",
                bands: "Half the age target / the age target",
                source:
                  "Age targets: a published savings-by-age guideline. Half: CoastMath planning threshold",
              },
              {
                metric: "Withdrawal rate at retirement",
                definition:
                  "Withdrawals, required distributions and 72(t) payments ÷ liquid balances at the start of the year.",
                year: "First full year after retirement",
                bands: "5% / 4% or less",
                source: "4%: historical safe-withdrawal research. 5%: CoastMath planning threshold",
              },
              {
                metric: "Guaranteed income coverage",
                definition:
                  "Social Security, pensions, annuities and country benefits ÷ essential spending.",
                year: "First full year of guaranteed income after retirement",
                bands: "50% / 100% or more",
                source: "CoastMath planning threshold",
              },
              {
                metric: "Pre-tax share at retirement",
                definition:
                  "Tax-deferred balances ÷ invested balances (tax-deferred, tax-free and taxable; cash and 529s excluded).",
                year: "First full year after retirement",
                bands: "75% / 50% or less",
                source: "CoastMath planning threshold",
              },
              {
                metric: "Funded years",
                definition:
                  "Share of projection years before the first year with unfunded spending.",
                year: "First shortfall, or the last plan year",
                bands: "90% / 100%",
                source: "CoastMath planning threshold",
              },
              {
                metric: "Financial independence",
                definition: "The year of the CoastMath financial independence estimate.",
                year: "That year",
                bands: "Retirement year + 5 / the retirement year or earlier",
                source: "CoastMath planning threshold",
              },
            ]}
            note="A metric whose inputs the plan doesn’t have is left off the scorecard."
          />
        </>
      ),
    },
    {
      id: "definitions",
      title: "Essential spending, retirement and the first year",
      body: (
        <>
          <ul>
            <li>
              <strong>Essential spending</strong> counts essential and uncategorized expenses, the
              essential part of an expense with a discretionary percent, loan payments, property
              costs and health coverage. Discretionary expenses, gifts and taxes don’t count.
            </li>
            <li>
              <strong>Retirement</strong> is your first milestone whose name mentions retirement and
              not a partner, the same milestone the Success odds tab uses. The retirement metrics
              read the first full calendar year after it, against balances at that year’s start. If
              the milestone is already in the past, they read the first plan year against opening
              balances, and Financial independence is left off.
            </li>
            <li>
              <strong>A partial first year</strong> is scaled to a full year wherever a year’s flow
              is set against a balance or an annual target: monthly essential spending, earned
              income for savings to income and a first-year withdrawal rate. Ratios of two flows in
              the same year need no scaling.
            </li>
            <li>
              <strong>Liquid</strong> follows each account’s liquid setting: a withdrawal-locked
              account, or one you exclude, isn’t liquid and isn’t counted in savings to income or
              the withdrawal rate.
            </li>
          </ul>
          <Callout kind="boundary">
            <p>Insurance coverage, estate documents and Success odds results aren’t graded.</p>
          </Callout>
        </>
      ),
    },
    {
      id: "age-target",
      title: "The age target for savings",
      body: (
        <>
          <p>
            The target multiple of income is 1× at 30, 3× at 40, 6× at 50, 8× at 60 and 10× at 67,
            straight-line between those ages and from 0× at 25. It stays at 10× after 67. At 25 and
            younger the metric is left off.
          </p>
          <Formula result="Savings to income">
            <V>Opening account balances</V>
            <Op>÷</Op>
            <V>Earned income for a full year</V>
          </Formula>
        </>
      ),
    },
    {
      id: "example",
      title: "Worked example",
      body: (
        <>
          <p>
            A 46-year-old starts a plan in January 2026 with a $100,000 salary, $40,000 of essential
            and $10,000 of discretionary expenses, a $20,000 car loan at $500 a month, $30,000 in
            checking, $200,000 in a traditional 401(k) and $100,000 in a brokerage account.
          </p>
          <Ledger
            title="Emergency fund"
            rows={[
              { label: "Checking balance", value: 30000 },
              {
                op: "÷",
                label: "Monthly essential spending: ($40,000 + $6,000 loan payments) ÷ 12",
                value: 3833,
              },
              {
                op: "=",
                label: "Months covered",
                value: 7.8,
                format: "num",
                digits: 1,
                detail: "Strong: 6 months or more",
              },
            ]}
          />
          <Ledger
            title="Savings to income"
            rows={[
              { label: "Account balances", value: 330000 },
              { op: "÷", label: "Salary", value: 100000 },
              {
                op: "=",
                label: "Multiple",
                value: 3.3,
                format: "num",
                digits: 1,
                detail: "Fair: the target at 46 is 4.8×, half of it 2.4×",
              },
            ]}
          />
          <p>Debt payments are $6,000 ÷ $100,000 = 6% of income, which is Strong.</p>
        </>
      ),
    },
    {
      id: "where",
      title: "Where the scorecard appears",
      body: (
        <>
          <Callout kind="where">
            <p>
              <UIPath steps={["Checkup", "Wellness scorecard"]} /> groups the metrics under
              Needs attention, Fair and Strong. Select a metric to open the plan section that
              drives it. It refreshes with each projection.
            </p>
          </Callout>
          <p>
            For the estimate behind Financial independence, see{" "}
            <HelpLink to="financial-independence-estimate" />; for shortfall years, see{" "}
            <HelpLink to="unfunded-expenses" />.
          </p>
        </>
      ),
    },
  ],
};

export default article;

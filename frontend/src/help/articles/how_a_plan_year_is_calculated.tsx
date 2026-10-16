import type { Article } from "../help_types";
import { Callout, DataTable, Figure, HelpLink, Ledger } from "../help_kit";
import { Waterfall } from "../help_charts";

/* Example figures: a single filer who turns 75 in 2027, reproduced from one engine run with fixed
   inputs. */
const walk = [
  { label: "Social Security", value: 30900, color: "blue" as const },
  { label: "RMD", value: 24871, color: "blue" as const },
  { label: "Federal tax", value: -1578, color: "orange" as const },
  { label: "Spending", value: -72100, color: "magenta" as const },
  { label: "Shortfall", value: -17907, total: true },
  { label: "Withdrawals", value: 17907, color: "cyan" as const },
];

const stageRows = [
  {
    stage: "Events",
    what: "Milestones reached this year take effect, and so do household changes such as a partner’s death.",
    more: <HelpLink to="milestones" />,
  },
  {
    stage: "Growth",
    what: "Opening balances earn the year’s returns, and brokerage dividends are taxed and reinvested. Checking and savings don’t earn interest. Property appreciates.",
    more: <HelpLink to="investment-growth" />,
  },
  {
    stage: "Required",
    what: "Required minimum distributions, qualified charitable distributions and any 72(t) series come out of their accounts.",
    more: <HelpLink to="required-minimum-distributions" />,
  },
  {
    stage: "Income",
    what: "Pay, Social Security, pensions and other income arrive for the months they’re active. Payroll deductions, workplace contributions and withholding come out.",
    more: <HelpLink to="wages-and-raises" />,
  },
  {
    stage: "Spending",
    what: "Expenses (after any flexible spending cuts), health coverage, gifts, loan payments and property costs are due. Scheduled property sales close.",
    more: <HelpLink to="expenses" />,
  },
  {
    stage: "Cash flow",
    what: "Roth conversions and transfers run. Money left over follows your allocation rules; a shortfall is withdrawn in your withdrawal order.",
    more: <HelpLink to="withdrawal-order" />,
  },
  {
    stage: "Taxes",
    what: "Tax is figured on the year’s final income, including the withdrawals that paid it, then reconciled with what was withheld.",
    more: <HelpLink to="how-taxes-are-calculated" />,
  },
  {
    stage: "Year end",
    what: "Balances, net worth and taxes are recorded. Amounts that track inflation, raises and benefit adjustments step up for next year.",
    more: <HelpLink to="todays-and-future-dollars" />,
  },
];

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath projects your plan one calendar year at a time, from your plan’s start date to the
        last year the plan covers. Every year runs through the same eight stages in the same order,
        and each stage starts from the balances the one before it left.
      </p>
      <p>
        The order explains most results that look surprising at first: why a required distribution
        arrives before a shortfall is funded, why a withdrawal can raise that year’s tax, and why a
        raise shows up in January.
      </p>
    </>
  ),
  sections: [
    {
      id: "the-eight-stages",
      title: "The eight stages",
      body: (
        <>
          <DataTable
            caption="One plan year, in order"
            columns={[
              { key: "stage", label: "Stage" },
              { key: "what", label: "What happens" },
              { key: "more", label: "Details" },
            ]}
            rows={stageRows}
          />
          <p>
            A stage only sees what earlier stages produced. Required distributions are taken before
            income and spending are counted, so an RMD reduces the shortfall that later withdrawals
            have to cover. Allocation rules only receive money that’s left after spending; moving
            money from one account to another takes a transfer or Roth conversion rule.
          </p>
        </>
      ),
    },
    {
      id: "one-year-start-to-finish",
      title: "One year, start to finish",
      body: (
        <>
          <p>
            A single filer turns 75 in 2027. The plan started in 2026 with $20,000 in checking, a
            $300,000 brokerage account holding $200,000 of basis, and a $600,000 traditional IRA.
            Social Security pays $30,000 a year, and spending is $70,000 a year in 2026 dollars. The
            plan assumes 6% stock growth and 3% inflation, and withdraws from checking, then
            brokerage, then the IRA.
          </p>
          <Figure
            title="Where the 2027 spending came from"
            caption="Social Security and spending are 3% higher than in 2026 because both follow the plan’s inflation."
            table={{
              columns: [
                { key: "step", label: "Step" },
                { key: "amount", label: "Amount", format: "usd" },
              ],
              rows: walk.map((step) => ({ step: step.label, amount: step.value })),
            }}
          >
            <Waterfall
              steps={walk}
              label="Waterfall of 2027: Social Security and the RMD, less federal tax and spending, leave a shortfall that withdrawals cover."
            />
          </Figure>
          <Ledger
            title="The 2027 year, stage by stage"
            rows={[
              {
                label: "Social Security",
                value: 30900,
                detail: "Income stage; this year’s benefit after a 3% adjustment",
              },
              {
                op: "+",
                label: "Required minimum distribution",
                value: 24871,
                detail: "Required stage; December 31, 2026 IRA balance ÷ 24.6",
              },
              {
                op: "−",
                label: "Federal income tax",
                value: 1578,
                detail: "Taxes stage; figured after the withdrawals below",
              },
              {
                op: "−",
                label: "Spending",
                value: 72100,
                detail: "Spending stage; $70,000 in 2026 dollars",
              },
              { op: "=", label: "Shortfall", value: -17907 },
              {
                op: "→",
                label: "Withdrawn from checking",
                value: 2756,
                detail: "Cash flow stage; checking is first in the order",
              },
              {
                op: "→",
                label: "Withdrawn from brokerage",
                value: 15150,
                detail: "Realizes about $6,150 of long-term gain",
              },
            ]}
            note="Figures are rounded to the dollar. There is no state tax in this example."
          />
          <p>
            The withdrawal realizes a gain that is taxed at 0% at this income. It still raises the
            year’s tax: the gain counts toward the income that decides how much Social Security is
            taxable, so about $5,230 more of the benefit is taxed. Without the sale, the year’s
            federal tax would be about $1,005 instead of $1,578. That’s why the tax is settled after
            the withdrawals, not before.
          </p>
        </>
      ),
    },
    {
      id: "timing-inside-a-year",
      title: "Timing inside a year",
      body: (
        <>
          <p>
            Amounts you enter are annual, and CoastMath counts them for the months they’re active.
            An income that ends at a milestone reached in May counts for January through April. A
            milestone set by age takes effect in your birth month.
          </p>
          <ul>
            <li>
              <strong>Opening balances</strong> earn the full year’s return.
            </li>
            <li>
              <strong>Money that moves during the year</strong> (contributions, withdrawals and
              required distributions) is treated as moving in equal monthly amounts, so it earns
              about half a year’s return. That’s why an account that pays out an RMD ends the year
              slightly lower than its opening balance plus a full year of growth minus the RMD.
            </li>
            <li>
              <strong>Inflation, raises and benefit adjustments</strong> take effect each January.
              An amount entered in today’s dollars is converted to each year’s dollars with the
              plan’s inflation.
            </li>
            <li>
              <strong>The first year</strong> covers only the months from your start date to
              December 31. See <HelpLink to="first-plan-year" />.
            </li>
          </ul>
        </>
      ),
    },
    {
      id: "taxes-and-withdrawals",
      title: "Why taxes and withdrawals are settled together",
      body: (
        <>
          <p>
            A withdrawal from a pre-tax account is taxable income, and a brokerage sale can realize
            a gain. Either can raise the year’s tax, and the extra tax needs cash of its own.
            CoastMath figures the year’s tax on its final income, then withdraws whatever the
            additional tax requires, so the withdrawals and the tax they create agree when the year
            closes.
          </p>
          <p>
            Withholding is compared with the final tax. A balance due is paid from that year’s cash,
            using the withdrawal order if needed. A refund is available that year and follows your
            allocation rules like other money left over. See{" "}
            <HelpLink to="tax-payments-and-settlement" />.
          </p>
          <Callout kind="boundary">
            <p>
              CoastMath settles each year’s federal and state income tax within that year. It
              doesn’t model quarterly estimated-payment timing or underpayment penalties.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "when-accounts-run-short",
      title: "When the accounts can’t cover a year",
      body: (
        <>
          <p>
            If the withdrawal order runs out before a shortfall is covered, CoastMath sells property
            you’ve marked for automatic sale, other property before a primary residence. Anything
            still unpaid is recorded as an unfunded expense, and the first year that happens is the
            plan’s failure year. Each later year, CoastMath tries to pay it by withdrawing from your
            accounts in the withdrawal order; the failure year stays on record even if it’s repaid.
            See <HelpLink to="unfunded-expenses" />.
          </p>
        </>
      ),
    },
    {
      id: "what-each-year-records",
      title: "What each year records",
      body: (
        <>
          <p>
            At year end CoastMath records every account balance, property values, loan balances,
            taxes by type and the year’s money flows. Net worth is accounts plus property, minus
            loan balances and any unfunded expenses. The year also records its inflation factor,
            which is how results convert to today’s dollars. See{" "}
            <HelpLink to="overview-and-net-worth" /> and <HelpLink to="cash-flow-view" />.
          </p>
          <Callout kind="where">
            <p>
              To trace a single year, open the cash-flow view and choose the year. Each flow there
              comes from one of the stages above.
            </p>
          </Callout>
        </>
      ),
    },
  ],
};

export default article;

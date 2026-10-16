import type { Article } from "../help_types";
import {
  Callout,
  Figure,
  Formula,
  HelpLink,
  KeyFigures,
  Ledger,
  Op,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";
import { Waterfall } from "../help_charts";

/* Engine output: single filer, 2026, $100,000 net profit, no other income, zero inflation,
   solo 401(k) employer contribution requested at 20% of profit. See the sources record. */
const steps = [
  { label: "Net profit", value: 100000, color: "blue" as const },
  { label: "Half of SE tax", value: -7064.78, color: "orange" as const },
  { label: "Solo 401(k)", value: -18587.05, color: "cyan" as const },
  { label: "AGI", value: 74348.18, total: true },
  { label: "Standard deduction", value: -16100, color: "gray" as const },
  { label: "QBI deduction", value: -11649.64, color: "gray" as const },
  { label: "Taxable income", value: 46598.54, total: true },
];

const article: Article = {
  intro: (
    <>
      <p>
        You enter net business profit. CoastMath counts it as ordinary income and charges
        self-employment tax on 92.35 percent of it. It deducts the employer-equivalent half of that
        tax from AGI and applies a simplified 20 percent qualified business income (QBI) deduction.
      </p>
      <p>
        A solo 401(k) can take employee deferrals and an employer contribution from the same profit.
        Both are held to the limits for the self-employed, and both are paid out of the business’s
        cash.
      </p>
    </>
  ),
  sections: [
    {
      id: "what-you-enter",
      title: "What you enter",
      body: (
        <>
          <p>
            Business income is a <strong>Salary</strong> income with <strong>Self-employed</strong>{" "}
            checked under <UIPath steps={["Growth and tax settings"]} />. Its amount, growth and
            timing work exactly like a salary’s; see <HelpLink to="wages-and-raises" />.
          </p>
          <Callout kind="entry">
            <p>
              Enter net profit after business expenses and before self-employment tax, the figure a
              sole proprietor’s business schedule reports. Don’t subtract self-employment tax, the
              QBI deduction or your own retirement contributions; CoastMath calculates each of them.
            </p>
          </Callout>
          <p>
            Each business income belongs to one person. Self-employment tax, its Social Security
            limit and the contribution limits are figured for that person, alongside any wages the
            same person earns.
          </p>
        </>
      ),
    },
    {
      id: "self-employment-tax",
      title: "Self-employment tax",
      body: (
        <>
          <Formula
            result="Self-employment tax"
            note="The Social Security rate applies only up to the wage base left after that person’s W-2 wages. The Additional Medicare Tax applies to combined wages and self-employment earnings above the filing-status threshold."
          >
            <V>Net profit</V>
            <Op>×</Op>
            <V>92.35%</V>
            <Op>×</Op>
            <V>(Social Security rate + Medicare rate)</V>
          </Formula>
          <p>
            Each rate is the employee and employer share combined. If 92.35 percent of the profit is
            under $400, the person owes no self-employment tax; that floor is applied per person.
            The rates, the wage base and the Additional Medicare Tax threshold are in{" "}
            <HelpLink to="payroll-and-other-federal-taxes" />.
          </p>
          <p>
            Half of the Social Security and Medicare parts of the tax is deducted in figuring AGI.
            The Additional Medicare Tax isn’t part of that deduction. Self-employment tax itself is
            always figured on the full profit: neither this deduction nor a retirement contribution
            lowers it.
          </p>
        </>
      ),
    },
    {
      id: "qbi-deduction",
      title: "The qualified business income deduction",
      body: (
        <>
          <Formula result="QBI deduction">
            <V>20%</V>
            <Op>×</Op>
            <V>the smaller of QBI and taxable income before this deduction</V>
          </Formula>
          <p>
            QBI is net profit minus the deductible half of self-employment tax and minus the
            traditional solo 401(k) contributions made from that business. Roth contributions don’t
            reduce it. The taxable income used for the limit is after the standard or itemized
            deduction and excludes long-term capital gains and qualified dividends. The QBI
            deduction lowers taxable income, not AGI, so it doesn’t change any AGI-based threshold.
          </p>
          <Callout kind="boundary">
            <p>
              CoastMath applies the 20 percent calculation at every income level. Above the income
              threshold, the law limits the deduction by W-2 wages paid and property held by the
              business and phases it out for specified service businesses. Neither limit is modeled,
              so at high incomes the deduction can be overstated. The $400 minimum deduction for a
              small active business isn’t applied either.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "retirement-contributions",
      title: "Retirement contributions from business income",
      body: (
        <>
          <p>
            A payroll rule funds a solo 401(k) from business income. Choose{" "}
            <strong>Payroll percent of income</strong>, the business income as{" "}
            <strong>Source income</strong> and a 401(k) owned by the same person as the destination.
            Both percentages apply to net profit:
          </p>
          <ul>
            <li>
              <strong>Employee contribution (%)</strong> is an elective deferral. It shares the
              employee limit, including catch-up contributions, with any other 401(k) the person
              contributes to. It can’t exceed that person’s wages and profit for the year.
            </li>
            <li>
              <strong>Employer contribution (% of income)</strong> is the business’s profit-sharing
              contribution. It’s capped at 20 percent of net profit minus the deductible half of
              self-employment tax. With a 25 percent plan rate, that’s the rate the self-employed
              can actually use. Employee and employer money together stay within the overall annual
              limit.
            </li>
            <li>
              Your business is a separate employer from any W-2 job, so a solo 401(k) funded from
              business income has its own overall annual limit. Employee deferrals still share one
              limit across all your plans.
            </li>
          </ul>
          <KeyFigures
            caption="2026 limits used for solo 401(k) contributions"
            items={[
              {
                label: "Employee deferral limit",
                value: 24500,
                detail: "plus catch-up contributions at 50 and older",
              },
              {
                label: "Employer contribution cap",
                value: "20%",
                detail: "of net profit minus half of self-employment tax",
              },
              {
                label: "Overall annual limit",
                value: 72000,
                detail: "employee and employer, excluding catch-ups; never more than earnings",
              },
            ]}
          />
          <p>
            Unlike a W-2 employer match, the employer contribution comes out of the profit you
            entered, so it lowers cash. Traditional contributions, employee and employer, are
            deducted in figuring AGI and reduce QBI. Roth contributions leave cash with no
            deduction.
          </p>
          <Callout kind="where">
            <p>
              <UIPath
                steps={[
                  "Income allocation",
                  "Payroll contributions and account transfers",
                  "Add payroll or transfer rule",
                ]}
              />
              . Catch-up and Roth catch-up rules are in{" "}
              <HelpLink to="contributions-and-employer-match" />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "worked-example",
      title: "Worked example",
      body: (
        <>
          <p>
            A single filer has $100,000 of net profit in 2026 and no other income. A payroll rule
            asks for an employer contribution of 20 percent of income into a traditional solo
            401(k).
          </p>
          <Ledger
            title="Self-employment tax and the contribution limit"
            rows={[
              { label: "Net profit", value: 100000, format: "usd_cents" },
              { op: "×", label: "Earnings factor", value: 0.9235, format: "pct", digits: 2 },
              { op: "=", label: "Self-employment earnings", value: 92350, format: "usd_cents" },
              {
                op: "→",
                label: "Self-employment tax",
                value: 14129.55,
                format: "usd_cents",
                detail: "15.3% of earnings, all below the wage base",
              },
              { op: "→", label: "Deductible half", value: 7064.78, format: "usd_cents" },
              {
                op: "→",
                label: "Employer contribution",
                value: 18587.05,
                format: "usd_cents",
                detail: "20% × ($100,000 − $7,064.78); the requested $20,000 is capped",
              },
            ]}
          />
          <Figure
            title="From net profit to taxable income"
            caption="Taxable income before the QBI deduction is $58,248.18, less than QBI of $74,348.18, so the deduction is 20% of $58,248.18."
            table={{
              columns: [
                { key: "step", label: "Step" },
                { key: "amount", label: "Amount", format: "usd_cents" },
              ],
              rows: steps.map((step) => ({ step: step.label, amount: step.value })),
            }}
          >
            <Waterfall
              format="usd"
              steps={steps}
              label="Waterfall from $100,000 of net profit to $46,598.54 of taxable income"
            />
          </Figure>
          <p>
            Federal income tax on $46,598.54 is $5,343.83, against $8,235 without the contribution.
            Self-employment tax is $14,129.55 in both cases. The contribution moves $18,587.05 from
            cash to the 401(k), and year-end net worth is $2,891.17 higher: the income tax saved.
          </p>
        </>
      ),
    },
    {
      id: "where-it-shows",
      title: "Where it shows up",
      body: (
        <>
          <p>
            Self-employment tax is part of payroll tax in the year’s tax detail;{" "}
            <HelpLink to="tax-analytics" /> explains that view. In the year’s cash flow, business
            profit is income, and traditional solo 401(k) contributions appear as payroll deductions
            before net pay. The employer contribution never appears as extra income.
          </p>
        </>
      ),
    },
    {
      id: "not-modeled",
      title: "What isn’t modeled",
      body: (
        <>
          <Callout kind="boundary">
            <ul>
              <li>SEP and SIMPLE IRAs. Payroll rules fund only 401(k) accounts and HSAs.</li>
              <li>
                The self-employed health insurance deduction. Premiums you enter as expenses aren’t
                deducted.
              </li>
              <li>
                The optional methods for figuring self-employment earnings, and special rules for
                church employees and ministers.
              </li>
              <li>
                Business entities. S corporation salary and distributions, partnership allocations
                and separate business returns aren’t represented; enter wages and profit as the
                income streams they are.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
    {
      id: "common-surprises",
      title: "Common surprises",
      body: (
        <>
          <Symptoms
            rows={[
              {
                symptom: "The employer contribution is smaller than the percentage you entered.",
                check:
                  "It’s capped at 20% of profit after half of self-employment tax, and by the overall limit.",
                next: "Expected. Add employee deferrals to contribute more.",
              },
              {
                symptom: "Payroll tax didn’t fall after adding a solo 401(k).",
                check: "Self-employment tax is figured on the full profit.",
                next: "Expected; contributions lower income tax only.",
              },
              {
                symptom: "Self-employment tax is lower than 15.3% of profit.",
                check:
                  "The tax applies to 92.35% of profit, and wages use up the Social Security base first.",
                next: (
                  <>
                    See <HelpLink to="payroll-and-other-federal-taxes" />.
                  </>
                ),
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

import type { Article } from "../help_types";
import {
  Callout,
  Formula,
  HelpLink,
  Ledger,
  Op,
  Steps,
  Symptoms,
  UIPath,
  V,
  hostedPart,
} from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath estimates financial independence as the first year that starts with enough money
        to cover 25 years of spending. The test runs at each year-end: CoastMath takes your account
        balances, subtracts your debts, and checks whether the result is more than 25 times that
        year’s spending. If it is, the estimate lands in the following year. The estimate is a
        marker only. It never changes the projection, and nothing can start or stop at it until you
        turn it into a milestone of your own.
      </p>
    </>
  ),
  sections: [
    {
      id: "the-test",
      title: "What the estimate tests",
      body: (
        <>
          <Formula
            result="Estimate lands the next year when"
            note="Both sides are measured in the same year’s dollars, so no inflation adjustment is needed. The balance must be strictly greater than the target; equal isn’t enough."
          >
            <V>Year-end balances of all accounts</V>
            <Op>−</Op>
            <V>Year-end debt</V>
            <Op>&gt;</Op>
            <V>25</V>
            <Op>×</Op>
            <V>That year’s spending</V>
          </Formula>
          <ul>
            <li>
              <strong>Accounts</strong> include every account at its full balance: cash, taxable,
              retirement accounts before tax, HSAs and education savings.
            </li>
            <li>
              <strong>Property value isn’t counted</strong>, but every loan is subtracted, including
              a mortgage on your home. If your debts exceed your account balances, the estimate
              can’t be reached.
            </li>
            <li>
              <strong>Spending</strong> counts every expense paid in the year:
              <ul>
                <li>Essential, discretionary and uncategorized expenses</li>
                <li>Loan payments</li>
                <li>Property tax, maintenance and insurance</li>
                <li>Health coverage</li>
                <li>Charitable gifts</li>
              </ul>
              Taxes aren’t spending. If the plan starts partway through a year, that first year’s
              spending is scaled up to a full year.
            </li>
          </ul>
          <p>
            Because the test uses year-end figures, the earliest possible estimate is the plan’s
            second year. Crossing the line in the last projected year produces no estimate, because
            the following year isn’t projected.
          </p>
        </>
      ),
    },
    {
      id: "example",
      title: "Worked example",
      body: (
        <>
          <p>
            This plan starts in January 2026. It has $1,500,000 in savings, a $150,000 salary,
            $50,000 a year of living expenses and a $120,000 loan paid at $1,000 a month without
            interest. To keep the numbers simple, there is no investment growth and no tax.
          </p>
          <Ledger
            title="Year-end checks"
            rows={[
              { label: "Spending each year: $50,000 living + $12,000 loan payments", value: 62000 },
              { op: "×", label: "Multiple", value: 25, format: "num" },
              { op: "=", label: "Target", value: 1550000 },
              {
                label: "End of 2026: $1,588,000 in accounts − $108,000 loan",
                value: 1480000,
                detail: "Below the target",
              },
              {
                label: "End of 2027: $1,676,000 in accounts − $96,000 loan",
                value: 1580000,
                detail: "Above the target",
              },
              { op: "→", label: "Estimate lands in", value: 2028, format: "year" },
            ]}
          />
          <p>
            A “Financial independence (multiple of expenses)” milestone set to 25× and “Liquid
            accounts minus debt” takes effect in 2028 in the same plan. If the salary is set to end
            at that milestone, the last paycheck is in December 2027.
          </p>
        </>
      ),
    },
    {
      id: "where-it-shows",
      title: "Where the estimate appears",
      body: (
        <>
          <p>
            The estimate is listed first under <UIPath steps={["Milestones"]} /> as “Financial
            independence (CoastMath estimate)”. The listing shows “25× expenses (liquid)”, followed
            by the year it is reached or “not reached in projection”. The estimate also marks the
            Overview net-worth chart, and it appears in the printable report and in the summary you
            share. When the estimate is never reached, the chart notes “Financial independence is
            not reached within this plan.”
          </p>
          <p>
            The estimate doesn’t appear on the Success odds tab. Only milestones are tracked across
            trials there (see <HelpLink to="milestones#across-trials" />
            ).
          </p>
        </>
      ),
    },
    {
      id: "hide-or-replace",
      title: "Hide the estimate or make it your own milestone",
      body: (
        <>
          <h3>Replace it with your own milestone</h3>
          <Steps>
            <li>
              Next to the estimate under <strong>Milestones</strong>, select <strong>Edit</strong>.
            </li>
            <li>
              The form opens as “Make the FI estimate your milestone”, already set to{" "}
              <strong>Financial independence (multiple of expenses)</strong>, 25× and{" "}
              <strong>Liquid accounts minus debt</strong>. Change the multiple or the balance
              measured if you want to.
            </li>
            <li>Save the form. The new milestone replaces the estimate everywhere.</li>
          </Steps>
          <p>
            With the same settings, your milestone lands in the same year as the estimate. As a
            milestone, you can end a salary at it, start withdrawals or spending at it, or base
            relative milestones on it, and the Success odds tab reports its timing. Any milestone of
            this trigger type replaces the estimate. If you have more than one, the first one in the
            list is treated as your financial independence date.
          </p>
          <h3>Hide it</h3>
          <p>
            Select <strong>Remove</strong> to hide the estimate for this plan. To bring it back,
            select <strong>Restore the CoastMath financial independence estimate</strong>.
          </p>
          <Callout kind="entry">
            <p>
              Hiding is saved in this browser only.
              {hostedPart("financial-independence-estimate.hide-elsewhere", "")}
            </p>
          </Callout>
          {hostedPart("financial-independence-estimate.iphone", null)}
        </>
      ),
    },
    {
      id: "reading-it",
      title: "Why the estimate may differ from what you expect",
      body: (
        <>
          <Symptoms
            rows={[
              {
                symptom: "The estimate is later than the year you cross 25× your living expenses.",
                check:
                  "Do loan payments, property costs or health coverage make spending higher than living expenses alone?",
                next: "All of these count as spending. Debt is also subtracted from the balance.",
              },
              {
                symptom: "The estimate is a year after the net-worth chart crosses the target.",
                check: "The year-end values.",
                next: "This is expected: the estimate lands in the year after the test passes.",
              },
              {
                symptom: "The estimate is earlier than an after-tax view would suggest.",
                check: "How much is in pre-tax retirement accounts?",
                next: "Balances aren’t reduced for future tax. In your own milestone, a higher multiple moves the date later.",
              },
              {
                symptom: "Salary continues after the estimated year.",
                check: "What is the salary’s end milestone?",
                next: "Nothing can end at the estimate. Replace the estimate with your own milestone, then choose it as the salary’s End milestone.",
              },
            ]}
          />
          <p>
            Nothing about the estimate is a guarantee or a recommendation. It is one fixed threshold
            applied to your projection. <HelpLink to="overview-and-net-worth" /> shows how the same
            year appears on the Overview.
          </p>
        </>
      ),
    },
  ],
};
export default article;

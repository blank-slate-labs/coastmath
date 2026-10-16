import type { Article } from "../help_types";
import { Callout, HelpLink, Ledger, Steps, UIPath } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        Track actuals keeps a dated record of your real net worth: cash and investments, property,
        and debt on a given day. Each record appears as a <em>Recorded</em> point on the Overview’s
        net worth chart, beside the projected line, so you can see whether reality is ahead of or
        behind the plan.
      </p>
      <p>
        A record doesn’t change your plan. The projection still starts from the balances saved in
        the plan, so to re-base it, update those balances too.
      </p>
    </>
  ),
  sections: [
    {
      id: "record-your-balances",
      title: "Record your balances",
      body: (
        <>
          <Steps>
            <li>
              Open <UIPath steps={["Track actuals"]} />.
            </li>
            <li>
              Set <em>Record date</em>. It can’t be later than today.
            </li>
            <li>
              Enter <em>Cash and investments ($)</em>, <em>Property and other assets ($)</em> and{" "}
              <em>Total debt ($)</em> as totals on that date.
            </li>
            <li>
              Choose <em>Record progress</em>.
            </li>
          </Steps>
          <Ledger
            title="Example: a record on December 31, 2026"
            rows={[
              { label: "Cash and investments", value: 305000 },
              { op: "+", label: "Property and other assets", value: 410000 },
              { op: "−", label: "Total debt", value: 244000 },
              { op: "=", label: "Recorded net worth", value: 471000 },
            ]}
            note="The plan from the overview example projects $464,519 at the end of 2026, so this household is $6,481 ahead."
          />
          <Callout kind="entry">
            <p>
              Enter what the accounts, property and loans were actually worth on the record date, in
              dollars of that day. Enter debt as a positive number; it’s subtracted. Include every
              account in cash and investments, including retirement accounts at their full balance,
              as net worth does in the projection.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "compare-with-the-projection",
      title: "Compare with the projection",
      body: (
        <>
          <p>
            On the Overview’s net worth chart, each record is a dot at its calendar year. The chart
            marks each year at December 31, so a record from June sits against that year’s year-end
            projection; allow for half a year of saving and growth. Hover over a dot for its date
            and breakdown. Records from years outside the plan’s years aren’t drawn.
          </p>
          <p>
            Records are stored in the dollars you entered and are never adjusted for inflation.
            Compare them with the chart set to <em>Future dollars</em>; in <em>Today’s $</em>, the
            projected line is deflated but the dots aren’t.
          </p>
          <p>
            Records belong to your account, not to one plan, so every plan’s chart shows the same
            dots. When comparing two plans, the dots stay the same and only the projections differ.
          </p>
        </>
      ),
    },
    {
      id: "review-and-correct-records",
      title: "Review and correct records",
      body: (
        <>
          <p>
            Track actuals charts your recorded net worth over time and lists every record, newest
            first, with its date, <em>Recorded net worth</em> and source. A record can’t be edited:
            choose <em>Delete</em>, then record it again with the right values.
          </p>
        </>
      ),
    },
    {
      id: "update-the-plan",
      title: "Bring the plan up to date",
      body: (
        <>
          <p>
            Recording progress and updating the plan are separate steps. A plan set to{" "}
            <em>Now (starts today)</em> projects from today using whatever balances are saved in it,
            so balances you haven’t updated are treated as today’s. A plan with a{" "}
            <em>Fixed date</em> treats its saved balances as the balances on that date.
          </p>
          <Steps>
            <li>
              Record your actual balances in <UIPath steps={["Track actuals"]} />, so the comparison
              with the old projection is kept.
            </li>
            <li>
              Update each account’s balance in <UIPath steps={["Accounts"]} />, and property values
              and loan balances in <UIPath steps={["Property and debt"]} />.
            </li>
            <li>The projection recalculates from the new balances. Check the Overview again.</li>
          </Steps>
          <p>
            How saved balances and the start date set the first year is in{" "}
            <HelpLink to="opening-balances-and-cost-basis" /> and <HelpLink to="first-plan-year" />.
            To keep the old projection for comparison after updating, copy the plan first; see{" "}
            <HelpLink to="compare-plans" />.
          </p>
          <Callout kind="boundary">
            <p>
              Records hold totals only, not individual account balances, and CoastMath doesn’t
              import them from your bank or brokerage.
            </p>
          </Callout>
        </>
      ),
    },
  ],
};

export default article;

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
import { LineChart } from "../help_charts";

/* Single adult, household of one, benchmark $12,000, plan $11,000, 2026 rules. Engine output; see the sources record. */
const creditCurve: [number, number, number][] = [
  [15000, 0, 11000],
  [15649, 0, 11000],
  [15650, 11000, 0],
  [20000, 11000, 0],
  [25000, 10835, 165],
  [30000, 10140, 860],
  [35000, 9385, 1615],
  [40000, 8556, 2444],
  [45000, 7688, 3312],
  [50000, 7020, 3980],
  [55000, 6522, 4478],
  [60000, 6024, 4976],
  [62600, 5765, 5235],
  [62601, 0, 11000],
  [70000, 0, 11000],
  [80000, 0, 11000],
];

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath charges your marketplace premium as a household expense, reduced by an advance
        premium tax credit estimated from income you expect. When the year’s taxes are computed, it
        recalculates the credit on your final modified AGI and settles the difference with that
        year’s tax bill or refund: a refund if you were owed more, a repayment if you received too
        much.
      </p>
      <p>
        For 2026 the credit follows the original law: the enhanced credits of 2021–2025 expired, so
        no credit is available above 400% of the poverty line, and there is no cap on repaying
        excess advance credit.
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
            Marketplace coverage is one policy for the household’s adults. You enter two annual
            premiums for the covered adults under 65 at their ages in the plan’s first year, in
            today’s dollars. Leave out a partner already on Medicare:
          </p>
          <ul>
            <li>
              <strong>Benchmark premium</strong>: the second-lowest-cost silver plan for the covered
              adults, before any credit. The credit is sized from this figure.
            </li>
            <li>
              <strong>Your plan’s premium</strong>: the gross premium of the plan you pick. This is
              what you pay, less the credit.
            </li>
          </ul>
          <p>
            Both premiums grow each year with medical cost inflation (plan inflation when that field
            is blank). With age rating on, they also rise with each adult’s age along the federal
            default age curve, which triples a premium between ages 21 and 64. Children’s premiums
            aren’t added; dependents you enter only increase the household size used for the poverty
            line. A partner who isn’t on the policy still counts in the household.
          </p>
          <p>
            Coverage runs from the start milestone’s month (or the plan’s start) through the month
            before the end milestone, and each adult leaves the marketplace in the month before
            their 65th-birthday month, when Medicare begins. The premium then drops to the remaining
            adult’s share.
          </p>
          <Callout kind="entry">
            <p>
              Enter premiums before any credit. A net premium from a marketplace quote already
              includes a credit that CoastMath will subtract again. Remove any separate
              health-insurance expense so the premium isn’t counted twice.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              <UIPath steps={["Health coverage", "Marketplace (ACA) coverage before Medicare"]} />.{" "}
              <strong>Advance premium tax credit (% of estimate)</strong> sets how much of the
              estimated credit is applied during the year; the default is 100%.{" "}
              <strong>Poverty guideline region</strong> selects the Alaska or Hawaii guideline.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-the-credit-is-calculated",
      title: "How the credit is calculated",
      body: (
        <>
          <Formula result="Premium tax credit">
            <V>Benchmark premium</V>
            <Op>−</Op>
            <V>Applicable percentage</V>
            <Op>×</Op>
            <V>MAGI</V>
          </Formula>
          <p>
            The credit can’t be negative and can’t exceed your plan’s premium, so choosing a plan
            cheaper than the benchmark can reduce the net premium to zero but never below it.
          </p>
          <ul>
            <li>
              <strong>MAGI</strong> is adjusted gross income plus the untaxed part of Social
              Security benefits. It includes IRA withdrawals, Roth conversions and realized capital
              gains; pre-tax payroll and HSA contributions reduce it.
            </li>
            <li>
              <strong>Poverty line</strong>: 2026 coverage uses the 2025 guideline for your
              household size. Later years index it with plan inflation.
            </li>
            <li>
              <strong>Applicable percentage</strong> rises with income as a share of the poverty
              line, from 2.10% to 9.96%, interpolated within each band. At 300% to 400% of the
              poverty line it is 9.96%.
            </li>
            <li>
              Below 100% of the poverty line the credit is zero and the full premium is charged,
              with a warning. CoastMath doesn’t model Medicaid.
            </li>
          </ul>
          <KeyFigures
            caption="2026 figures"
            items={[
              { label: "Poverty line, household of 1", value: 15650 },
              {
                label: "Poverty line, household of 2",
                value: 21150,
                detail: "+$5,500 per additional person",
              },
              {
                label: "No credit above, household of 1",
                value: 62600,
                detail: "400% of the poverty line",
              },
              {
                label: "Applicable percentage",
                value: "2.10%–9.96%",
                detail: "By income as a share of the poverty line",
              },
            ]}
          />
          <Ledger
            title="Example: one adult with $45,000 of MAGI"
            rows={[
              { label: "MAGI", value: 45000 },
              { op: "÷", label: "Poverty line, household of 1", value: 15650 },
              {
                op: "=",
                label: "Income as a share of the poverty line",
                value: 2.8754,
                format: "pct",
              },
              {
                label: "Applicable percentage",
                value: 0.095812,
                format: "pct",
                digits: 2,
                detail: "Between 8.44% at 250% and 9.96% at 300%",
              },
              { label: "Benchmark premium", value: 12000 },
              { op: "−", label: "Expected contribution (9.58% × $45,000)", value: 4312 },
              { op: "=", label: "Premium tax credit", value: 7688 },
              { label: "Your plan’s premium", value: 11000 },
              {
                op: "=",
                label: "Net premium for the year",
                value: 3312,
                detail: "$11,000 − $7,688",
              },
            ]}
          />
          <Figure
            title="Credit and net premium by MAGI, one adult, 2026"
            caption="Benchmark $12,000, plan $11,000. At $62,601 the credit falls from $5,765 to zero."
            table={{
              columns: [
                { key: "magi", label: "MAGI", format: "usd" },
                { key: "credit", label: "Credit", format: "usd" },
                { key: "net", label: "Net premium", format: "usd" },
              ],
              rows: creditCurve.map(([magi, credit, net]) => ({ magi, credit, net })),
            }}
          >
            <LineChart
              label="Premium tax credit and net premium by MAGI for one adult in 2026"
              xFormat="num"
              series={[
                {
                  id: "credit",
                  label: "Premium tax credit",
                  color: "cyan",
                  points: creditCurve.map(([magi, credit]) => [magi, credit]),
                },
                {
                  id: "net",
                  label: "Net premium you pay",
                  color: "magenta",
                  points: creditCurve.map(([magi, , net]) => [magi, net]),
                },
              ]}
              markers={[{ x: 62600, label: "400% of poverty line" }]}
            />
          </Figure>
        </>
      ),
    },
    {
      id: "advance-credit-and-reconciliation",
      title: "Advance credit and year-end reconciliation",
      body: (
        <>
          <p>
            A marketplace sets your advance credit from an income estimate made before the year
            starts. CoastMath does the same:
          </p>
          <ul>
            <li>
              <strong>First plan year</strong>: the estimate is{" "}
              <strong>Last year’s modified AGI</strong> if you entered it (the field sits under
              Medicare premiums and shows while IRMAA surcharges are on); otherwise it is the year’s
              income before the withdrawals that fund spending.
            </li>
            <li>
              <strong>Later years</strong>: the estimate is the previous year’s final MAGI.
            </li>
          </ul>
          <p>
            The premium paid during the year is your plan’s premium minus the advance share of the
            estimated credit, and that amount is what appears in spending. After the year’s
            withdrawals, conversions and gains are known, the credit is recalculated on final MAGI.
            The difference, final credit minus advance credit, is added to the year’s tax
            settlement: a positive difference is a refund, a negative one is owed in full. It isn’t
            part of total taxes, and the credit is never counted as income.
          </p>
          <Ledger
            title="Example: spending funded from a traditional IRA"
            rows={[
              { label: "Last year’s modified AGI (the estimate)", value: 40000 },
              { label: "Advance credit applied to premiums", value: 8556 },
              { label: "Premium paid during the year", value: 2444, detail: "$11,000 − $8,556" },
              {
                label: "Final MAGI after IRA withdrawals",
                value: 47181,
                detail: "Withdrawals for $40,000 of living costs, premiums and taxes",
              },
              { label: "Final credit on that MAGI", value: 7301 },
              {
                op: "=",
                label: "Repaid with the year’s taxes",
                value: -1255,
                detail: "$7,301 − $8,556",
              },
            ]}
            note="One adult aged 60, benchmark $12,000, plan $11,000, no other income. The next year’s estimate starts from $47,181, so it matches and nothing is repaid."
          />
          <p>
            Setting the advance percentage below 100% raises the premium you pay during the year and
            moves the rest of the credit to the tax settlement. At 0%, the whole credit arrives as a
            refund. See <HelpLink to="tax-payments-and-settlement" /> for how a settlement is
            funded.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Tax tools", "Health coverage"]} /> shows each year’s income as a
              share of the poverty line, the gross premium and the final credit. Premiums paid
              appear as <strong>Health coverage</strong> in spending; the repayment or refund
              appears in the year’s tax settlement.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "what-isnt-modeled",
      title: "What isn’t modeled",
      body: (
        <>
          <Callout kind="boundary">
            <ul>
              <li>
                The credit is computed for the year from annual MAGI. A year with some coverage
                months is prorated by month, but income isn’t split by month.
              </li>
              <li>
                Premiums are one household policy scaled by age. State age curves, children’s
                premiums and changes in which plan is the benchmark aren’t modeled.
              </li>
              <li>
                A married couple filing separately gets no credit, because the credit requires a
                joint return. The exception for victims of domestic abuse or abandonment isn’t
                modeled.
              </li>
              <li>
                Medicaid and CHIP eligibility, employer-coverage affordability tests, and the rules
                for people who aren’t lawfully present aren’t modeled.
              </li>
              <li>
                Later years keep the 2026 applicable percentages and the 400% limit. A future law
                change isn’t anticipated.
              </li>
              <li>
                Excluded foreign income isn’t part of CoastMath’s MAGI. Tax-exempt interest is
                included only as municipal bond interest set on a brokerage account (see{" "}
                <HelpLink to="investment-growth#income-tax-character" />
                ).
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
    {
      id: "reading-the-result",
      title: "Reading the result",
      body: (
        <>
          <Symptoms
            rows={[
              {
                symptom: "The credit drops to zero in one year and the premium jumps.",
                check: (
                  <>
                    Income as a share of the poverty line in{" "}
                    <UIPath steps={["Tax tools", "Health coverage"]} />. Above 400%, no credit
                    applies.
                  </>
                ),
                next: (
                  <>
                    Look for a Roth conversion, capital gain or large IRA withdrawal that year. See{" "}
                    <HelpLink to="roth-conversions" />.
                  </>
                ),
              },
              {
                symptom:
                  "A tax bill appears in the first year of retirement even though taxes look low.",
                check:
                  "Whether final MAGI exceeded the estimate. The repayment is in the tax settlement, not total taxes.",
                next: (
                  <>
                    Enter <strong>Last year’s modified AGI</strong> close to what you’ll actually
                    report, or lower the advance percentage.
                  </>
                ),
              },
              {
                symptom: "The full premium is charged at a very low income.",
                check: "Whether income fell below 100% of the poverty line; a warning says so.",
                next: "CoastMath doesn’t model Medicaid. Treat those years’ premiums as an upper bound.",
              },
              {
                symptom: "Health costs appear twice.",
                check: (
                  <>
                    An insurance expense in <HelpLink to="expenses">Expenses</HelpLink> alongside
                    modeled coverage.
                  </>
                ),
                next: "Remove the separate expense.",
              },
            ]}
          />
          <p>
            Medicare costs after 65 are covered in <HelpLink to="medicare-and-irmaa" />.
          </p>
        </>
      ),
    },
  ],
};
export default article;

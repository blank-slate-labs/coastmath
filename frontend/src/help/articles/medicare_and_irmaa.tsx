import type { Article } from "../help_types";
import {
  Callout,
  DataTable,
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
import { Timeline } from "../help_charts";

const article: Article = {
  intro: (
    <>
      <p>
        From the month each person turns 65, CoastMath adds Medicare premiums to household spending:
        the Part B standard premium, any income-related surcharge (IRMAA) on Parts B and D, and the
        Part D, Medigap or Advantage premiums you enter. The surcharge tier comes from the
        household’s modified AGI two years earlier, compared with the thresholds for the filing
        status on that earlier return.
      </p>
      <p>
        For the plan’s first two years, that earlier income predates the projection, so CoastMath
        uses the prior-year figures you enter.
      </p>
    </>
  ),
  sections: [
    {
      id: "what-you-enter",
      title: "What you enter",
      body: (
        <>
          <ul>
            <li>
              <strong>Part B</strong> and <strong>Part D drug coverage</strong> switch those
              premiums and their surcharges on or off. Part B uses the published standard premium;
              you don’t enter it.
            </li>
            <li>
              <strong>Part D plan premium</strong> and <strong>Medigap or Advantage premium</strong>{" "}
              are monthly amounts per person, in today’s dollars.
            </li>
            <li>
              <strong>Apply income-related surcharges (IRMAA)</strong> turns the surcharge on. Below
              it, <strong>Last year’s modified AGI</strong> and{" "}
              <strong>Modified AGI two years ago</strong> set the first two years’ tiers, with the
              filing status of each of those returns.
            </li>
          </ul>
          <p>
            Part A is assumed premium-free. If someone will pay a Part A premium, or their Medicare
            starts after 65, set that person’s <strong>Medical cost method</strong> to{" "}
            <strong>Coverage premiums + optional budget</strong>. Enter their{" "}
            <strong>Medicare-covered quarters for Part A</strong>, counting a spouse’s record if it
            qualifies them: with 40 or more there is no premium, with 30 to 39 the reduced premium
            applies, and with fewer the full premium applies.{" "}
            <strong>Other Part A premium ($ per month)</strong> is added on top, so leave it at 0
            when you enter quarters. Those per-person settings, with{" "}
            <strong>Medicare starts at age</strong>, replace the shared Medicare choices for that
            person.
          </p>
          <KeyFigures
            caption="2026 Medicare premiums, per person per month"
            items={[
              { label: "Part B standard premium", value: 202.9, format: "usd_cents" },
              { label: "Part A, fewer than 30 quarters of work", value: 565 },
              { label: "Part A, 30–39 quarters", value: 311 },
            ]}
          />
          <Callout kind="entry">
            <p>
              Enter the Medigap or Advantage and Part D premiums per person per month, not for the
              couple. Remove any Medicare premium you’ve also entered as an expense.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              <UIPath steps={["Health coverage", "Medicare premiums from age 65"]} /> for shared
              choices; <UIPath steps={["Health coverage", "IRMAA tax-return status"]} /> for the
              lookback filing statuses;{" "}
              <UIPath steps={["Health coverage", "Primary person healthcare"]} /> and{" "}
              <UIPath steps={["Health coverage", "Partner healthcare"]} /> for per-person settings.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-premiums-are-calculated",
      title: "How premiums are calculated",
      body: (
        <>
          <Formula result="Annual Medicare premium, per person">
            <V>
              (Part B + Part B surcharge + Part D surcharge + Part D plan + Medigap or Advantage)
            </V>
            <Op>×</Op>
            <V>Months enrolled</V>
          </Formula>
          <p>
            The surcharge tier is set once for the household from the lookback MAGI, and each
            enrolled person pays it. MAGI here is adjusted gross income, including IRA withdrawals,
            Roth conversions and realized capital gains.
          </p>
          <DataTable
            caption="2026 IRMAA tiers, per person per month"
            columns={[
              { key: "single", label: "MAGI, individual return" },
              { key: "joint", label: "MAGI, joint return" },
              { key: "b", label: "Part B total", format: "usd_cents" },
              { key: "d", label: "Part D surcharge", format: "usd_cents" },
            ]}
            rows={[
              { single: "$109,000 or less", joint: "$218,000 or less", b: 202.9, d: 0 },
              {
                single: "Over $109,000 – $137,000",
                joint: "Over $218,000 – $274,000",
                b: 284.1,
                d: 14.5,
              },
              {
                single: "Over $137,000 – $171,000",
                joint: "Over $274,000 – $342,000",
                b: 405.8,
                d: 37.5,
              },
              {
                single: "Over $171,000 – $205,000",
                joint: "Over $342,000 – $410,000",
                b: 527.5,
                d: 60.4,
              },
              {
                single: "Over $205,000 – $500,000",
                joint: "Over $410,000 – $750,000",
                b: 649.2,
                d: 83.3,
              },
              { single: "Above $500,000", joint: "Above $750,000", b: 689.9, d: 91 },
            ]}
            note="Married filing separately and lived with your spouse at any time that year: $109,000 or less pays the standard premium; up to $391,000 pays $649.20 for Part B and $83.30 for Part D; above that, $689.90 and $91.00. Separate filers who lived apart all year use the individual column. The Part D surcharge is added to your plan’s premium."
          />
          <p>
            In later years, the Part B premium, the surcharge amounts and the published Part A
            premium grow from their 2026 values at your medical cost inflation (plan inflation when
            blank). The income thresholds index with plan inflation, except that the top thresholds
            of $500,000 and $750,000 stay fixed through 2027, as the law requires. Part D, Medigap
            and Advantage premiums you enter grow at medical cost inflation.
          </p>
          <Ledger
            title="Example: a couple two years after a $300,000 income year"
            rows={[
              {
                label: "Part B standard, 2 people × 12 months",
                value: 4869.6,
                format: "usd_cents",
                detail: "$202.90 a month each",
              },
              {
                op: "+",
                label: "Part B surcharge, tier 2",
                value: 4869.6,
                format: "usd_cents",
                detail: "$202.90 a month each",
              },
              {
                op: "+",
                label: "Part D surcharge, tier 2",
                value: 900,
                format: "usd_cents",
                detail: "$37.50 a month each",
              },
              {
                op: "+",
                label: "Part D plan premiums",
                value: 960,
                format: "usd_cents",
                detail: "$40 a month each",
              },
              {
                op: "+",
                label: "Medigap premiums",
                value: 3600,
                format: "usd_cents",
                detail: "$150 a month each",
              },
              { op: "=", label: "Medicare premiums for 2028", value: 15199.2, format: "usd_cents" },
            ]}
            note="Both 68 in 2028, filing jointly, 2026 MAGI of $300,000, no inflation. In 2029 the lookback is 2027, with no income, and the total falls to $9,429.60."
          />
        </>
      ),
    },
    {
      id: "two-year-lookback",
      title: "The two-year lookback",
      body: (
        <>
          <p>
            Each year’s tier uses MAGI from the tax year two years earlier. From the plan’s third
            year on, that is the projected MAGI CoastMath computed for that year. For the first two
            years it is what you entered:
          </p>
          <ul>
            <li>
              <strong>First plan year</strong> uses <strong>Modified AGI two years ago</strong>.
            </li>
            <li>
              <strong>Second plan year</strong> uses <strong>Last year’s modified AGI</strong>.
            </li>
          </ul>
          <p>
            A blank field falls back to the current year’s income, with a warning. The thresholds
            are those for the filing status on the lookback return. For the first two years that is
            the status you enter; afterwards it is the projected status for that year. A surviving
            partner’s first premiums after a death therefore still use the joint thresholds of the
            last joint return.
          </p>
          <Figure
            title="Which tax year sets each year’s surcharge, plan starting 2026"
            caption="Income in any projected year first affects premiums two years later."
            table={{
              columns: [
                { key: "premium", label: "Premium year", format: "year" },
                { key: "income", label: "Income year used", format: "year" },
                { key: "source", label: "Source" },
              ],
              rows: [
                { premium: 2026, income: 2024, source: "Modified AGI two years ago" },
                { premium: 2027, income: 2025, source: "Last year’s modified AGI" },
                { premium: 2028, income: 2026, source: "Projected" },
                { premium: 2029, income: 2027, source: "Projected" },
              ],
            }}
          >
            <Timeline
              label="Lookback from income year to premium year for a plan starting in 2026"
              unit="year"
              from={2024}
              to={2030}
              spans={[
                { from: 2024, to: 2026, label: "Entered: two years ago", color: "gray", row: 0 },
                { from: 2025, to: 2027, label: "Entered: last year", color: "gray", row: 1 },
                { from: 2026, to: 2028, label: "Projected 2026 income", color: "blue", row: 2 },
                { from: 2027, to: 2029, label: "Projected 2027 income", color: "blue", row: 3 },
              ]}
              events={[{ at: 2026, label: "Plan starts" }]}
            />
          </Figure>
          <p>
            Because of the lag, a Roth conversion or large sale at 63 already counts toward premiums
            at 65. See <HelpLink to="roth-conversions" />.
          </p>
        </>
      ),
    },
    {
      id: "first-medicare-year",
      title: "The first Medicare year",
      body: (
        <>
          <p>
            Medicare starts in the month of each person’s 65th birthday, or at the per-person start
            age you set, and that year’s premiums cover the remaining months. Someone born in July
            pays six months of Part B, $1,217.40 at the 2026 standard premium. For a couple, each
            person enrolls on their own birthday; a younger partner can stay on marketplace
            coverage, described in <HelpLink to="marketplace-health-coverage" />, until their own
            65th-birthday month.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Tax tools", "Health coverage"]} /> lists each year’s Part B and D
              premiums and the surcharge with its tier. All premiums are part of the{" "}
              <strong>Health coverage</strong> line in spending.
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
                Requests for a lower surcharge after a life-changing event, such as retirement,
                aren’t modeled. The tier always follows the lookback return.
              </li>
              <li>
                Late-enrollment penalties for Part B or D, the Part B deductible and coinsurance
                aren’t included. Put expected cost-sharing in an out-of-pocket budget; see{" "}
                <HelpLink to="medical-costs-and-long-term-care" />.
              </li>
              <li>
                Only municipal bond interest set on a brokerage account counts as tax-exempt
                interest in CoastMath’s MAGI (see{" "}
                <HelpLink to="investment-growth#income-tax-character" />
                ); other tax-exempt interest isn’t included.
              </li>
              <li>
                Premiums are annual amounts. A change in tier takes effect for the whole calendar
                year.
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
                symptom: "A surcharge appears in a year when income is low.",
                check:
                  "The income two years earlier: a conversion, home sale or last working year.",
                next: (
                  <>
                    The surcharge lasts one year per high-income year. See{" "}
                    <HelpLink to="roth-conversions" />.
                  </>
                ),
              },
              {
                symptom: "The first two years show a surcharge you don’t pay.",
                check:
                  "Whether the prior-year MAGI fields are blank; the warning says current income was used.",
                next: "Enter both prior-year MAGI amounts and their filing statuses.",
              },
              {
                symptom: "The tier changes the year after a partner dies.",
                check:
                  "The filing status of the lookback return. Individual-return thresholds are lower than joint ones.",
                next: (
                  <>
                    See <HelpLink to="death-of-a-partner" />.
                  </>
                ),
              },
            ]}
          />
          <p>
            Part B, Part D and Part A premiums, including surcharges, are qualified medical expenses
            for a health savings account; see <HelpLink to="hsa" />.
          </p>
        </>
      ),
    },
  ],
};
export default article;

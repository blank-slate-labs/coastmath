import type { Article } from "../help_types";
import {
  Callout,
  DataTable,
  Figure,
  Formula,
  Frac,
  HelpLink,
  Ledger,
  Op,
  Pair,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";
import { BarChart } from "../help_charts";

const years = [2026, 2027, 2028];
const salary = [30247, 123600, 127308];
const spending = [15123, 61800, 63654];

const article: Article = {
  intro: (
    <>
      <p>
        Your projection starts on a start date: today for a Now plan, or the date you choose for a
        Fixed date plan. The balances you enter are the balances on that date. The first calendar
        year runs only from the start date to December 31, so income, spending and investment growth
        in that year are scaled to the share of the year that remains.
      </p>
      <p>
        From the second year on, every year is a full calendar year. Amounts that grow step up a
        full year’s growth each January, even when the first year was short.
      </p>
    </>
  ),
  sections: [
    {
      id: "now-or-fixed-date",
      title: "Now and fixed-date plans",
      body: (
        <>
          <Pair
            left={{
              title: "Now (starts today)",
              body: (
                <p>
                  The start date is your local calendar date each time the projection runs. Balances
                  are read as today’s balances, and the first year shrinks as the year goes on. On
                  January 1 the start year becomes the new year and the first year is a full year
                  again.
                </p>
              ),
            }}
            right={{
              title: "Fixed date",
              body: (
                <p>
                  The start date stays where you set it, including a date in the past or the future.
                  Use it to keep a forecast from a known date, such as the day you retire or the
                  date of your last statements. The date can’t be earlier than your birth month.
                </p>
              ),
            }}
          />
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "Plan type"]} /> switches between Now and Fixed date;{" "}
              <UIPath steps={["Plan details", "Start date"]} /> appears for a fixed-date plan.
            </p>
          </Callout>
          <Callout kind="entry">
            <p>
              Each plan has its own accounts, so enter balances as of this plan’s start date. An
              older plan whose section reads <strong>Household accounts</strong> shares balances
              with your other such plans.
            </p>
          </Callout>
          <Callout kind="entry">
            <p>
              Amounts you enter are in dollars of the plan’s first calendar year. In a Now plan that
              year moves with the calendar, so on January 1 the same entries are read as the new
              year’s dollars. See <HelpLink to="todays-and-future-dollars" />.
            </p>
          </Callout>
          <p>
            Your birth month sets the month of age-based milestones and the earliest allowed start
            date. When it isn’t set, CoastMath assumes January. Set it in{" "}
            <UIPath steps={["Plan details", "Birth month"]} />.
          </p>
        </>
      ),
    },
    {
      id: "first-year-fraction",
      title: "How the first year is sized",
      body: (
        <>
          <p>CoastMath measures the first year in days, counting the start date itself.</p>
          <Formula result="First-year fraction">
            <Frac
              num={<V>Days from the start date through December 31</V>}
              den={<V>Days in that calendar year</V>}
            />
          </Formula>
          <Ledger
            title="Example: a plan that starts October 1, 2026"
            rows={[
              { label: "Days from October 1 through December 31", value: 92, format: "num" },
              { op: "÷", label: "Days in 2026", value: 365, format: "num" },
              { op: "=", label: "First-year fraction", value: 0.2521, format: "pct", digits: 1 },
            ]}
          />
          <p>A plan that starts on January 1 has a fraction of 100% and no partial year.</p>
        </>
      ),
    },
    {
      id: "what-the-fraction-scales",
      title: "What the fraction scales",
      body: (
        <>
          <p>
            Income and expenses count only for the part of the year after the start date. An item
            that also has its own start or end month counts only where its months overlap that
            period. Price growth compounds for the same fraction of a year, and dividend and cash
            yields are scaled by it.
          </p>
          <Formula result="First-year growth rate">
            <V>(1 + annual rate)</V>
            <Op>^</Op>
            <V>first-year fraction</V>
            <Op>−</Op>
            <V>1</V>
          </Formula>
          <Ledger
            title="Example: first-year growth on a $500,000 brokerage balance at 7%"
            rows={[
              { label: "Balance on October 1, 2026", value: 500000 },
              {
                op: "×",
                label: "Growth for 25.2% of a year at 7%",
                value: 0.0172,
                format: "pct",
                digits: 2,
              },
              { op: "=", label: "Growth through December 31", value: 8600 },
            ]}
            note="The next year compounds a full 7% on the December 31 balance."
          />
          <Figure
            title="Salary and living expenses in the example plan"
            caption="Salary of $120,000 and living expenses of $60,000 a year, both entered for 2026 and rising 3% a year. The first bar covers October through December only."
            table={{
              columns: [
                { key: "year", label: "Year" },
                { key: "salary", label: "Salary", format: "usd" },
                { key: "spending", label: "Living expenses", format: "usd" },
              ],
              rows: years.map((year, i) => ({
                year: String(year),
                salary: salary[i],
                spending: spending[i],
              })),
            }}
          >
            <BarChart
              categories={years}
              stacked={false}
              label="Salary and living expenses by year, 2026 to 2028, with a partial first year"
              series={[
                { id: "salary", label: "Salary", color: "blue", values: salary },
                { id: "spending", label: "Living expenses", color: "magenta", values: spending },
              ]}
            />
          </Figure>
          <p>
            In 2027 the salary is $123,600 and expenses are $61,800: a full 3% step on the entered
            amounts, not a partial one. Amounts step up once each January regardless of when the
            plan started.
          </p>
          <p>
            Some rules need a whole year’s figure, so CoastMath converts the partial year to a
            full-year pace for them. A milestone set as a multiple of annual expenses uses the
            full-year spending pace. Roth IRA contribution eligibility uses a full-year estimate of
            income unless you enter the income you had earlier in the year.
          </p>
        </>
      ),
    },
    {
      id: "first-year-taxes",
      title: "First-year taxes and earlier income",
      body: (
        <>
          <p>
            Tax is always figured for the whole calendar year, with the full standard deduction and
            brackets. Until you enter earlier history, CoastMath estimates income from active plan
            streams and treats the matching share of tax as already paid, so only the months after
            the start date settle from the plan. The year panel labels the estimate{" "}
            <strong>estimated pro rata</strong>. Earlier contributions, withdrawals and deductions
            stay zero until entered.
          </p>
          <DataTable
            caption="First-year tax in the example plan, single filer, no state tax"
            columns={[
              { key: "item", label: "" },
              { key: "without", label: "No earlier history (estimated pro rata)", format: "usd" },
              { key: "with", label: "$90,000 earlier wages, $20,000 tax paid", format: "usd" },
            ]}
            rows={[
              { item: "Wages taxed for 2026", without: 120000, with: 120247 },
              { item: "Federal income tax", without: 17570, with: 17624 },
              { item: "Social Security and Medicare tax", without: 9180, with: 9199 },
              { item: "Total 2026 tax", without: 26750, with: 26823 },
              { item: "Treated as paid before October 1", without: 20008, with: 20000 },
              { item: "Paid from the plan in 2026", without: 6742, with: 6823 },
            ]}
            note="2026 federal figures: $16,100 standard deduction; 10% to $12,400, 12% to $50,400 and 22% to $105,700 of taxable income. Without history, 273/365 of the salary and of the tax fall before October 1."
          />
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "Earlier this tax year"]} /> takes the income, taxes
              paid, contributions and withdrawals from January 1 to the start date. The tax year
              must be the plan’s first year. While it’s empty, the Overview shows a notice with{" "}
              <strong>Review tax history</strong>.
            </p>
          </Callout>
          <Callout kind="entry">
            <p>
              Amounts from earlier in the year aren’t added to your balances. The balances you enter
              already include them.
            </p>
          </Callout>
          <p>
            For how the balance due or refund is paid in the plan, see{" "}
            <HelpLink to="tax-payments-and-settlement" />.
          </p>
        </>
      ),
    },
    {
      id: "where-it-shows",
      title: "Where the partial year shows",
      body: (
        <>
          <p>
            On the Overview, the year panel labels the first year with its period, such as “Oct 1 –
            Dec 31”. It adds <strong>Partial year</strong> (the fraction),{" "}
            <strong>Full-year income pace</strong> and <strong>Full-year spending pace</strong>,
            which divide the period’s amounts by the fraction. The cash-flow diagram notes the
            partial year and the share of the year its amounts cover.
          </p>
          <Symptoms
            rows={[
              {
                symptom: "First-year income and spending are a fraction of what you entered",
                check: "The start date and the Partial year row on the Overview",
                next: "Expected. Compare the full-year pace rows with your annual amounts.",
              },
              {
                symptom: "The first year’s tax doesn’t match your pay stubs",
                check: "Whether Earlier this tax year is filled in",
                next: "Enter income and taxes paid since January 1; until then they are estimated pro rata.",
              },
              {
                symptom: "The second year jumps well above the first",
                check: "Whether the first year is partial",
                next: "Expected: the second year is a full year plus one year of growth.",
              },
              {
                symptom: "The first year keeps getting shorter, or resets in January",
                check: "Plan type",
                next: "A Now plan starts today. Choose Fixed date to keep a start date.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

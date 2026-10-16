import type { Article } from "../help_types";
import {
  Callout,
  DataTable,
  Figure,
  Formula,
  Frac,
  HelpLink,
  Ledger,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";
import { LineChart } from "../help_charts";

// A $24,000 fixed nominal payment with 3% plan inflation, from the plan's start year (2026).
const fixedTodays: [number, number][] = [
  [2026, 24000],
  [2027, 23301],
  [2028, 22622],
  [2029, 21963],
  [2030, 21324],
  [2031, 20703],
  [2032, 20100],
  [2033, 19514],
  [2034, 18946],
  [2035, 18394],
  [2036, 17858],
  [2037, 17338],
  [2038, 16833],
  [2039, 16343],
  [2040, 15867],
  [2041, 15405],
  [2042, 14956],
  [2043, 14520],
  [2044, 14097],
  [2045, 13687],
];
const fixedFuture: [number, number][] = fixedTodays.map(([year]) => [year, 24000]);

const article: Article = {
  intro: (
    <>
      <p>
        Every amount you enter is in dollars of your plan’s first calendar year. CoastMath projects
        in future dollars: each year’s amounts are what they would be in that year after the growth
        and inflation you set. <strong>Today’s $</strong> converts each year’s results back to
        first-year dollars by dividing by the plan’s cumulative inflation up to that year.
      </p>
      <p>
        The choice changes only what you see. It never changes a saved input or the projection
        itself.
      </p>
    </>
  ),
  sections: [
    {
      id: "what-you-enter",
      title: "What your entries mean",
      body: (
        <>
          <p>
            An income or expense is entered in first-year dollars even if it begins decades later.
            Its growth setting then decides how it moves in future dollars:
          </p>
          <DataTable
            caption="Growth settings and how each amount looks"
            columns={[
              { key: "setting", label: "Setting" },
              { key: "future", label: "In future dollars" },
              { key: "today", label: "In Today’s $" },
            ]}
            rows={[
              {
                setting: "Rises with plan inflation (the expense default)",
                future: "Rises with plan inflation each January",
                today: "Stays at the amount you entered",
              },
              {
                setting: "Custom rate per year",
                future:
                  "Compounds at your rate from the first year, so a later expense is carried forward to its start",
                today: "Rises by roughly your rate minus inflation",
              },
              {
                setting: "Fixed nominal amount, or an income growth rate of 0",
                future: "Stays at the amount you entered",
                today: "Shrinks each year by inflation",
              },
            ]}
            note="An income with a blank growth rate follows the wage growth assumption if one is set, otherwise plan inflation. Social Security with a blank rate follows the Social Security COLA assumption, otherwise plan inflation."
          />
          <Callout kind="entry">
            <p>
              A growth cap is in future dollars unless you tick{" "}
              <strong>Cap rises with inflation (entered in today’s dollars)</strong>. Account
              balances are the balances on the start date.
            </p>
          </Callout>
          <Callout kind="entry">
            <p>
              In a Now plan the first year is the current calendar year. On January 1 it moves
              forward, and every amount you entered is read as the new year’s dollars without being
              adjusted. See <HelpLink to="first-plan-year#now-or-fixed-date" />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-the-conversion-works",
      title: "How Today’s $ is calculated",
      body: (
        <>
          <Formula
            result="Today’s $ in a year"
            note="The inflation factor is 1 in the plan’s first year. Each January it grows by that past year’s plan inflation rate, a full step even after a partial first year."
          >
            <Frac
              num={<V>Future dollars in that year</V>}
              den={<V>Inflation factor for that year</V>}
            />
          </Formula>
          <p>
            The factor is the same one that raises inflation-linked entries, so an expense that
            rises with plan inflation shows the same amount every year in Today’s $.
          </p>
          <Ledger
            title="Example: a $60,000 living expense in 2036, 3% inflation, plan starting 2026"
            rows={[
              { label: "Amount entered, in 2026 dollars", value: 60000 },
              {
                op: "×",
                label: "Inflation factor for 2036 (1.03 for each of 10 years)",
                value: 1.3439,
                format: "num",
                digits: 4,
              },
              { op: "=", label: "Future dollars in 2036", value: 80635 },
              {
                op: "÷",
                label: "Inflation factor for 2036",
                value: 1.3439,
                format: "num",
                digits: 4,
              },
              { op: "=", label: "Today’s $ in 2036", value: 60000 },
            ]}
          />
          <Figure
            title="A $24,000 fixed nominal payment, 2026–2045"
            caption="Plan inflation of 3% a year. A payment that doesn’t rise with inflation buys less each year, so it declines in Today’s $."
            table={{
              columns: [
                { key: "year", label: "Year" },
                { key: "future", label: "Future dollars", format: "usd" },
                { key: "today", label: "Today’s $ (2026)", format: "usd" },
              ],
              rows: fixedTodays.map(([year, value]) => ({
                year: String(year),
                future: 24000,
                today: value,
              })),
            }}
          >
            <LineChart
              step
              yMin={0}
              label="A fixed $24,000 payment in future dollars and in 2026 dollars, 2026 to 2045"
              series={[
                { id: "future", label: "Future dollars", color: "magenta", points: fixedFuture },
                { id: "today", label: "Today’s $ (2026)", color: "gray", points: fixedTodays },
              ]}
            />
          </Figure>
          <p>
            The rate is your plan’s <strong>Inflation</strong> assumption, 3% unless you change it.
            With an age-based inflation curve, each year uses the curve’s rate at your age that
            year. Federal tax brackets and similar thresholds use the published 2026 amounts and
            then rise with plan inflation, so in Today’s $ they stay roughly level; see{" "}
            <HelpLink to="federal-brackets-and-deductions" />.
          </p>
        </>
      ),
    },
    {
      id: "where-each-basis-applies",
      title: "Where each basis applies",
      body: (
        <>
          <Callout kind="where">
            <p>
              Switch between <strong>Future dollars</strong> and <strong>Today’s $</strong> in the
              header of the Overview’s net worth chart, or with{" "}
              <UIPath steps={["Exports", "Dollars"]} />. It’s one setting for all your plans,
              remembered in this browser, and starts on Today’s $.
            </p>
          </Callout>
          <DataTable
            caption="Dollar basis by view"
            columns={[
              { key: "view", label: "View" },
              { key: "basis", label: "Basis" },
            ]}
            rows={[
              {
                view: "Overview: net worth chart, year panel, tax chart",
                basis: "Follows the setting; labeled with the first year, such as “2026 dollars”",
              },
              {
                view: "Exports: annual table, printable report, CSV and JSON downloads",
                basis: "Follows the setting",
              },
              {
                view: "Overview: cash-flow diagram",
                basis: "Always future dollars; marked “nominal” when Today’s $ is on",
              },
              { view: "Success odds", basis: "Future dollars" },
              {
                view: "Historical Stress Test, Tax tools, Track actuals",
                basis: "Future dollars",
              },
            ]}
          />
          <p>
            The first year is the same on both bases. For how each view is read, see{" "}
            <HelpLink to="overview-and-net-worth" /> and <HelpLink to="reports-and-exports" />.
          </p>
        </>
      ),
    },
    {
      id: "limits",
      title: "What the conversion doesn’t do",
      body: (
        <>
          <Callout kind="boundary">
            <p>
              Today’s $ always divides by your plan’s inflation assumption. It doesn’t use a
              different inflation path, such as the historical inflation replayed in the stress
              test, and it doesn’t convert amounts in the views that stay in future dollars.
            </p>
          </Callout>
          <Symptoms
            rows={[
              {
                symptom: "An expense shows the same amount every year",
                check: "Whether Today’s $ is on and the expense rises with plan inflation",
                next: "Expected. Switch to Future dollars to see it grow.",
              },
              {
                symptom: "A payment you entered as fixed shrinks over time",
                check: "Amount growth is Fixed nominal amount",
                next: "Expected in Today’s $: inflation erodes it.",
              },
              {
                symptom: "The cash-flow diagram and the year panel disagree",
                check: "Whether Today’s $ is on",
                next: "The diagram is in future dollars. Compare it with the Future dollars view.",
              },
              {
                symptom: "Changing the setting didn’t change your inputs",
                check: "The amounts in your plan sections",
                next: "Expected. Inputs always stay in first-year dollars.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

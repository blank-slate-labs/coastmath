import type { Article } from "../help_types";
import {
  Callout,
  DataTable,
  Figure,
  Formula,
  HelpLink,
  Ledger,
  Op,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";
import { LineChart } from "../help_charts";

/* $12,000 a year entered at plan start (2026), 3% plan inflation, under the three growth settings.
   Engine output; see the sources record. */
const growthRows: [number, number, number, number][] = [
  [2026, 12000.0, 12000, 12000.0],
  [2027, 12360.0, 12000, 12600.0],
  [2028, 12730.8, 12000, 13230.0],
  [2029, 13112.72, 12000, 13891.5],
  [2030, 13506.11, 12000, 14586.08],
  [2031, 13911.29, 12000, 15315.38],
  [2032, 14328.63, 12000, 16081.15],
  [2033, 14758.49, 12000, 16885.21],
  [2034, 15201.24, 12000, 17729.47],
  [2035, 15657.28, 12000, 18000.0],
  [2036, 16127.0, 12000, 18000.0],
  [2037, 16610.81, 12000, 18000.0],
  [2038, 17109.13, 12000, 18000.0],
  [2039, 17622.4, 12000, 18000.0],
  [2040, 18151.08, 12000, 18000.0],
  [2041, 18695.61, 12000, 18000.0],
  [2042, 19256.48, 12000, 18000.0],
  [2043, 19834.17, 12000, 18000.0],
  [2044, 20429.2, 12000, 18000.0],
  [2045, 21042.07, 12000, 18000.0],
  [2046, 21673.33, 12000, 18000.0],
  [2047, 22323.53, 12000, 18000.0],
  [2048, 22993.24, 12000, 18000.0],
  [2049, 23683.04, 12000, 18000.0],
  [2050, 24393.53, 12000, 18000.0],
  [2051, 25125.34, 12000, 18000.0],
];

const growthFigure = (
  <Figure
    title="A $12,000 expense under each growth setting, 2026–2051"
    caption="Plan inflation is 3%. The custom rate is 5% with a fixed $18,000 cap, reached in 2035."
    table={{
      columns: [
        { key: "year", label: "Year", format: "year" },
        { key: "inflation", label: "Rises with plan inflation", format: "usd" },
        { key: "custom", label: "Custom 5%, capped at $18,000", format: "usd" },
        { key: "fixed", label: "Fixed nominal amount", format: "usd" },
      ],
      rows: growthRows.map(([year, inflation, fixed, custom]) => ({
        year,
        inflation,
        custom,
        fixed,
      })),
    }}
  >
    <LineChart
      label="Annual amount of a $12,000 expense from 2026 to 2051 under inflation-linked, custom capped and fixed growth"
      step
      series={[
        {
          id: "inflation",
          label: "Rises with plan inflation",
          color: "magenta",
          points: growthRows.map(([year, value]) => [year, value]),
        },
        {
          id: "custom",
          label: "Custom 5%, capped at $18,000",
          color: "blue",
          points: growthRows.map(([year, , , value]) => [year, value]),
        },
        {
          id: "fixed",
          label: "Fixed nominal amount",
          color: "gray",
          points: growthRows.map(([year, , value]) => [year, value]),
        },
      ]}
    />
  </Figure>
);

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath charges each expense in every year it’s active, at the amount you entered grown to
        that year by its growth setting. An expense set to repeat is charged only in its first
        active year and every interval after it. In the year a start or end milestone is reached,
        the charge covers only the active months.
      </p>
      <p>
        Expenses are paid from the year’s cash flow; any shortfall is withdrawn from your accounts
        in drawdown order. Expenses aren’t tax-deductible unless they are pre-tax payroll
        deductions.
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
            Each expense has a name, an amount, a category (essential, discretionary or a custom
            split), a growth setting and an optional schedule. <strong>Amount frequency</strong> can
            be weekly, biweekly (every two weeks), semimonthly (twice a month), monthly, quarterly
            or annual; a new expense starts as monthly. CoastMath multiplies the amount by 52, 26,
            24, 12, 4 or 1, and every calculation below works on that annual amount. The frequency
            is saved with the expense, so the form reopens in it and the expense list shows the
            amount in it. An expense that repeats every few years is listed by its yearly charge.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Expenses", "Add expense"]} />. Growth, repeats, funding accounts and
              milestones are under <UIPath steps={["Advanced: growth, funding and timing"]} />.
              Without a start or end milestone, an expense runs from plan start through plan end.
            </p>
          </Callout>
          <Callout kind="entry">
            <p>
              Enter inflation-linked and custom-growth amounts in dollars of your plan’s start year,
              even when the expense begins decades later. CoastMath grows them from the start year.
              Only a fixed nominal amount is charged exactly as entered.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-amounts-grow",
      title: "Each growth setting compounds from the plan’s start year",
      body: (
        <>
          <Formula result="Charge in a year">
            <V>Entered annual amount</V>
            <Op>×</Op>
            <V>growth since plan start</V>
            <Op>×</Op>
            <V>change per occurrence</V>
            <Op>×</Op>
            <V>share of the year active</V>
          </Formula>
          <ul>
            <li>
              <strong>Rises with plan inflation</strong> multiplies by cumulative plan inflation,
              which steps up each January. The first plan year uses the amount as entered.
            </li>
            <li>
              <strong>Custom rate per year</strong> multiplies by (1 + rate) for each year since
              plan start, whether or not the expense was active in those years. It replaces
              inflation linking. An optional growth cap limits the grown amount to the cap each
              year; with <em>Cap rises with inflation</em> checked, the cap itself grows with plan
              inflation. A negative rate shrinks the amount.
            </li>
            <li>
              <strong>Fixed nominal amount</strong> never changes, so its value in today’s dollars
              falls with inflation.
            </li>
          </ul>
          {growthFigure}
          <Ledger
            title="Example: tuition that starts in September 2036"
            rows={[
              { label: "Entered amount, 2026 dollars", value: 20000 },
              {
                op: "×",
                label: "Custom growth at 5% for 10 years",
                value: 1.6288946,
                format: "num",
                digits: 4,
                detail: "1.05 raised to the power 10",
              },
              { op: "=", label: "Full-year amount in 2036", value: 32578 },
              { op: "×", label: "Active months, September–December", value: "4 ÷ 12" },
              { op: "=", label: "Charged in 2036", value: 10859 },
            ]}
            note="From 2037 the full-year amount applies, growing 5% a year. A graduation milestone in June 2040 limits that year to January–May."
          />
        </>
      ),
    },
    {
      id: "repeating-and-one-time",
      title: "Repeating and one-time expenses",
      body: (
        <>
          <p>
            With <em>Repeats every few years</em> on, an expense is charged in its first active year
            and then every <em>Repeat every (years)</em> after it, with nothing in between. The
            interval counts from the year the expense first becomes active, not from plan start. The
            amount still grows from plan start, so a replacement ten years out costs ten years’ more
            inflation.
          </p>
          <p>
            <em>Change per occurrence</em> multiplies each later charge by (1 + change) once per
            earlier occurrence, on top of the growth setting. Use it for costs that step up or down
            with each replacement.
          </p>
          <DataTable
            caption="Two repeating expenses, 3% plan inflation, plan start 2026"
            columns={[
              { key: "year", label: "Year", format: "year" },
              { key: "what", label: "Expense" },
              { key: "amount", label: "Charged", format: "usd" },
            ]}
            rows={[
              {
                year: 2026,
                what: "Car: $35,000 fixed, every 8 years, +10% per occurrence",
                amount: 35000,
              },
              {
                year: 2031,
                what: "Roof: $25,000 inflation-linked, every 10 years from a January 2031 milestone",
                amount: 28982,
              },
              { year: 2034, what: "Car, second occurrence", amount: 38500 },
              { year: 2041, what: "Roof, second occurrence", amount: 38949 },
              { year: 2042, what: "Car, third occurrence", amount: 42350 },
            ]}
            note="The roof’s first charge is $25,000 grown by five years of inflation, although the expense only starts in 2031."
          />
          <p>
            For a one-time purchase, turn on repeats, give it a start milestone for the purchase
            date and set an interval longer than the rest of the plan (up to 100 years). It’s
            charged once.
          </p>
          <Callout kind="entry">
            <p>
              A repeating or one-time charge follows the same partial-year rule as any other
              expense. If its start milestone is reached in July and no start month is set, only six
              months of the amount are charged: a $40,000 inflation-linked purchase in 2030, grown
              to $45,020 at 3% from a 2026 plan start, is charged as $22,510. Set{" "}
              <em>Start Month</em> to January to charge the whole amount in the milestone’s year.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "start-and-end-timing",
      title: "Start and end timing",
      body: (
        <>
          <p>
            An expense becomes active in the year its start milestone is reached and stops in the
            year its end milestone is reached. Months only matter in those boundary years:
          </p>
          <ul>
            <li>
              In the start year, charges begin in <em>Start Month</em>. If it’s blank, they begin in
              the month the milestone is reached: the birthday month for an age milestone, the
              date’s month for a date milestone, and January for other milestone types.
            </li>
            <li>
              In the end year, charges run through <em>End Month</em>. If it’s blank, they stop
              after the month before the milestone is reached.
            </li>
            <li>
              A start or end month without the matching milestone has no effect. Months aren’t a
              seasonal schedule.
            </li>
          </ul>
          <p>
            A plan that starts partway through a year also charges only the remaining months of its
            first year; see <HelpLink to="first-plan-year" />.
          </p>
        </>
      ),
    },
    {
      id: "categories-and-funding",
      title: "Categories and how expenses are paid",
      body: (
        <>
          <p>
            The category matters in one calculation: <HelpLink to="flexible-spending" /> can reduce
            discretionary spending after weak market years, raise it after new portfolio highs if
            you ask it to, and never touches essential spending. Cash you choose to spend at year
            end is added as discretionary “Leftover spending”. Choose <em>Essential</em> (0% can be
            cut), <em>Discretionary</em> (100%) or <em>Custom</em>, which sets the discretionary
            share from 0 to 100% with a slider or a number: groceries might be 30% discretionary,
            travel 90%. A custom split is listed as “30% flexible”, and spending totals that leave
            out essential or discretionary expenses count each part separately. The categories are
            otherwise treated the same.
          </p>
          <p>
            Apps that show only essential or discretionary label a split expense by its larger part:
            50% or more is discretionary.
          </p>
          <ul>
            <li>
              <strong>General cash flow</strong> (the default): the year’s income pays expenses
              first, and any shortfall is withdrawn in the order described in{" "}
              <HelpLink to="withdrawal-order" />.
            </li>
            <li>
              <strong>Fund from a specific account</strong>: only the selected accounts pay this
              expense, in the order you list them within each account type; your drawdown order
              decides which type goes first. If they run short, the remainder is reported as
              unfunded. These expenses are outside flexible spending rules.
            </li>
            <li>
              <strong>Payroll Deduction</strong>: the amount comes out of the chosen paycheck while
              that income is active. Pre-tax deductions lower taxable wages; see{" "}
              <HelpLink to="payroll-deductions" />.
            </li>
          </ul>
          <Callout kind="entry">
            <p>
              With <UIPath steps={["Health coverage", "Model health coverage costs"]} /> on,
              premiums and your medical budgets are added to spending as a separate{" "}
              <em>Health coverage</em> line. Don’t also enter them as expenses, or they are counted
              twice.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "where-results-show",
      title: "Where the results show up",
      body: (
        <>
          <p>
            Each year’s cash flow lists every charged expense by name, in future dollars, alongside
            health coverage, loan payments and gifts. A repeating expense appears only in the years
            it’s charged. Switching the display to today’s dollars divides each amount by cumulative
            inflation; see <HelpLink to="todays-and-future-dollars" />.
          </p>
          <Callout kind="boundary">
            <p>
              A custom growth rate is one constant rate; it doesn’t follow a changing inflation
              assumption. Expenses aren’t itemized deductions, and there’s no seasonal or
              month-by-month schedule inside a year.
            </p>
          </Callout>
          <Symptoms
            rows={[
              {
                symptom: "An expense is smaller than expected in its first year",
                check:
                  "Whether its start milestone is reached mid-year, or the plan starts mid-year",
                next: "Set Start Month to January if the whole amount belongs in that year.",
              },
              {
                symptom: "A repeating expense appears in the wrong years",
                check: "The first year the expense was active; the interval counts from there",
                next: "Change the start milestone rather than the interval.",
              },
              {
                symptom: "A later expense starts much higher than entered",
                check: "Its growth setting",
                next: "That’s growth from plan start. Enter the amount in plan-start dollars, or choose a fixed nominal amount.",
              },
              {
                symptom: "Medical costs look doubled",
                check: "Expenses named for premiums or medical bills while health coverage is on",
                next: "Remove the duplicate expenses.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};

export default article;

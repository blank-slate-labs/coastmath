import type { Article } from "../help_types";
import { Callout, DataTable, Figure, HelpLink, KeyFigures, Ledger, UIPath } from "../help_kit";
import { LineChart } from "../help_charts";

/* Engine interpolation of the curve 50 → 3%, 60 → 5%, 70 → 2.5% at whole ages (see the sources record). */
const curvePoints: [number, number][] = [
  [45, 0.03],
  [46, 0.03],
  [47, 0.03],
  [48, 0.03],
  [49, 0.03],
  [50, 0.03],
  [51, 0.034],
  [52, 0.03752],
  [53, 0.04057],
  [54, 0.04316],
  [55, 0.04531],
  [56, 0.04704],
  [57, 0.04836],
  [58, 0.04928],
  [59, 0.04982],
  [60, 0.05],
  [61, 0.04973],
  [62, 0.04892],
  [63, 0.04759],
  [64, 0.04576],
  [65, 0.04344],
  [66, 0.04064],
  [67, 0.03738],
  [68, 0.03368],
  [69, 0.02955],
  [70, 0.025],
  [71, 0.025],
  [72, 0.025],
  [73, 0.025],
  [74, 0.025],
  [75, 0.025],
];

const article: Article = {
  intro: (
    <>
      <p>
        Five plan-wide rates drive every projection: inflation, stock price growth, stock dividend
        yield, bond return and bond allocation. Each is an annual nominal rate. You can keep a rate
        fixed or give it a curve that changes with your age. An account can override its own stock
        growth, dividend yield and bond share.
      </p>
      <p>
        Inflation does the most work. It indexes spending you enter in today’s dollars. It also
        drives Social Security’s default cost-of-living increase, the default raise on pay, and the
        federal tax brackets and limits after 2026.
      </p>
    </>
  ),
  sections: [
    {
      id: "defaults",
      title: "The rates and their defaults",
      body: (
        <>
          <KeyFigures
            caption="Plan defaults when you haven’t saved a rate"
            items={[
              { label: "Inflation", value: 0.03, format: "pct" },
              {
                label: "Stock price growth",
                value: 0.07,
                format: "pct",
                detail: "Excludes dividends",
              },
              { label: "Stock dividend yield", value: 0, format: "pct" },
              { label: "Bond return", value: 0.04, format: "pct" },
              { label: "Bond allocation", value: 0, format: "pct", detail: "All-stock portfolio" },
            ]}
          />
          <p>
            With the defaults, every investment account is 100% stocks growing 7% a year with no
            dividend. The 4% bond return has no effect until you set a bond allocation above zero.
          </p>
          <Callout kind="entry">
            <p>
              <strong>Stock price growth excludes dividends.</strong> The total stock return is
              price growth plus the dividend yield. For a 7% total return with a 2% yield, enter 5%
              growth and 2% yield. Entering 7% and 2% models a 9% total return.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              <UIPath steps={["Assumptions"]} /> in the plan builder. Rows marked “(default)” have
              no saved value. Rates are percentages per year. Inflation, wage growth, stock growth
              and bond return accept −99% to 100%. Dividend yield and bond allocation accept 0% to
              100%.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "what-each-moves",
      title: "Which amounts each assumption moves",
      body: (
        <>
          <DataTable
            caption="What each rate changes"
            columns={[
              { key: "rate", label: "Assumption" },
              { key: "moves", label: "Moves" },
              { key: "not", label: "Doesn’t move" },
            ]}
            rows={[
              {
                rate: "Inflation",
                moves:
                  "Expenses set to rise with inflation. Income with a blank growth rate: pay and Social Security. Growth caps marked to rise with inflation. Property tax and maintenance entered in dollars. Health costs without their own medical inflation rate. Federal brackets, deductions and contribution limits from 2027. The today’s-dollars display.",
                not: "Account balances. Expenses and incomes with a fixed rate or a fixed dollar amount.",
              },
              {
                rate: "Stock price growth",
                moves:
                  "The stock share of every investment account: retirement accounts, brokerage, HSA, 529 and Other.",
                not: "Checking and savings, which don’t grow. Accounts with their own stock growth.",
              },
              {
                rate: "Stock dividend yield",
                moves:
                  "Dividends on the stock share. They’re reinvested in every account and taxed only in a brokerage account.",
                not: "The bond share. Accounts with their own dividend yield.",
              },
              {
                rate: "Bond return",
                moves:
                  "The bond share of every investment account, including accounts with their own settings.",
                not: "An all-stock account.",
              },
              {
                rate: "Bond allocation",
                moves: "The mix of every investment account between stock and bond rates.",
                not: "Accounts with their own bond allocation.",
              },
            ]}
          />
          <p>
            All rates are nominal: CoastMath never subtracts inflation from a return. The
            today’s-dollars view divides each year’s results by cumulative inflation afterwards. See{" "}
            <HelpLink to="todays-and-future-dollars" />.
          </p>
          <Ledger
            title="Example: a $60,000 expense that rises with 3% inflation"
            rows={[
              { label: "First plan year", value: 60000 },
              { op: "×", label: "1 + inflation", value: 1.03, format: "num", digits: 2 },
              { op: "=", label: "Second year", value: 61800 },
              { op: "×", label: "1 + inflation", value: 1.03, format: "num", digits: 2 },
              { op: "=", label: "Third year", value: 63654 },
            ]}
            note="Each January the amount steps up by that year’s inflation rate, including after a partial first year."
          />
          <h3>Wage growth and Social Security COLA</h3>
          <p>
            Pay with a blank growth rate rises each January by the wage-growth rate. Social Security
            with a blank growth rate rises by the cost-of-living rate. Unless those rates are set,
            both follow that year’s inflation. Other income with a blank rate, such as a pension,
            stays at the same nominal amount. A growth rate entered on the income, including 0,
            always takes precedence.
          </p>
          <Callout kind="boundary">
            <p>
              CoastMath doesn’t set a COLA rate, so blank-rate benefits track inflation. Wage growth
              is set in
              <UIPath steps={["Assumptions"]} />. See <HelpLink to="wages-and-raises" />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "custom-curves",
      title: "Rates that change with age",
      body: (
        <>
          <p>
            Choose a curve instead of a fixed rate and enter at least two age points. Each year uses
            the value at your age in that calendar year. Between points the curve bends smoothly. It
            never goes above or below the two points on either side. Before the first point and
            after the last one, the rate stays at that point’s value.
          </p>
          <Figure
            title="An inflation curve with points at 50, 60 and 70"
            caption="The curve flattens at the 5% point rather than overshooting it. Before 50 and after 70 it holds the end values."
            table={{
              columns: [
                { key: "age", label: "Age" },
                { key: "rate", label: "Inflation", format: "pct", digits: 2 },
              ],
              rows: curvePoints.map(([age, rate]) => ({ age, rate })),
            }}
          >
            <LineChart
              xFormat="age"
              yFormat="pct"
              yMin={0}
              yMax={0.06}
              label="Inflation by age for a curve through 3% at 50, 5% at 60 and 2.5% at 70"
              series={[{ id: "curve", label: "Inflation", color: "gray", points: curvePoints }]}
              markers={[
                { x: 50, label: "3%" },
                { x: 60, label: "5%" },
                { x: 70, label: "2.5%" },
              ]}
            />
          </Figure>
          <p>
            Curves follow the primary person’s age. The one exception is a partner’s pay or Social
            Security with a blank growth rate, which uses the partner’s age on a wage-growth or COLA
            curve. A bond allocation curve is held between 0% and 100%.
          </p>
          <Callout kind="entry">
            <p>
              Ages must be distinct whole numbers from 0 to 130. The editor notes linear
              interpolation; the projection uses the smooth curve described here. At the points
              themselves the two agree exactly.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "federal-figures",
      title: "Published federal figures through 2026",
      body: (
        <>
          <p>
            Federal tax brackets, the standard deduction, contribution limits and other federal
            dollar thresholds use the published 2026 amounts in 2026. From 2027 they grow each year
            by your inflation rate, counted by calendar year. A plan that starts after 2026 first
            indexes the 2026 amounts through the intervening years with your inflation rate.
          </p>
          <p>
            Your own amounts work differently: they’re in dollars of the plan’s first year, and
            inflation starts applying the following January.
          </p>
          <Callout kind="boundary">
            <p>
              After 2026, thresholds grow with your inflation assumption, not with the separate
              price index each law uses, and they aren’t rounded the way published amounts are.
              Future law changes aren’t modeled.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "account-overrides",
      title: "Account-level overrides",
      body: (
        <>
          <p>
            An investment account can replace up to three plan rates with fixed values: stock price
            growth, stock dividend yield and bond allocation. A blank field keeps following the
            plan, including its curves. The bond return always comes from the plan.
          </p>
          <Callout kind="where">
            <p>
              <UIPath
                steps={[
                  "Accounts",
                  "Investment assumptions (optional)",
                  "Use fixed settings for this account",
                ]}
              />
              . Checking and savings accounts don’t show this section.
            </p>
          </Callout>
          <Callout kind="boundary">
            <p>
              An account’s own stock growth and dividend yield replace the varying market returns
              too. That account keeps the same stock rates in every success-odds trial and every
              historical replay. Only its bond share varies. See <HelpLink to="chance-of-success" />
              .
            </p>
          </Callout>
          <p>
            How the rates combine inside an account, including dividends and mid-year contributions,
            is in <HelpLink to="investment-growth" />.
          </p>
        </>
      ),
    },
  ],
};
export default article;

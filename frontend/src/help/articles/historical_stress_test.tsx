import type { Article } from "../help_types";
import { Callout, DataTable, Formula, HelpLink, Op, UIPath, V } from "../help_kit";
import { ExampleReplays } from "../figures/historical_stress_test";

const article: Article = {
  intro: (
    <>
      <p>
        The historical stress test runs your plan once with actual market history in place of your
        assumed rates. Your first plan year gets the stock return, bond return and inflation of the
        start year you pick, and each later plan year gets the next calendar year’s. The result is
        one projection, directly comparable with your steady-return forecast.
      </p>
      <p>
        Every other input stays as you entered it. Unlike <HelpLink to="chance-of-success" />,
        nothing is shuffled or adjusted to your assumptions: the replay uses history as recorded.
      </p>
      <p>
        The same panel runs hypothetical presets: a job loss, a market crash, both at once, a new
        child, or a multi-year market downturn you shape yourself. See{" "}
        <HelpLink to="historical-stress-test#hypothetical-presets" />. Neither kind of test changes
        your saved plan.
      </p>
    </>
  ),
  sections: [
    {
      id: "what-comes-from-history",
      title: "What comes from history",
      body: (
        <>
          <p>Each plan year takes three figures from its historical year, 1928 through 2024:</p>
          <ul>
            <li>
              <strong>Stocks:</strong> the U.S. large-company total return, including dividends. It
              is split into dividends and price growth using that year’s recorded dividend yield, so
              brokerage dividend income follows history too.
            </li>
            <li>
              <strong>Bonds:</strong> the U.S. Treasury bond return.
            </li>
            <li>
              <strong>Inflation:</strong> the December-to-December change in consumer prices.
            </li>
          </ul>
          <p>
            Historical inflation replaces your inflation assumption everywhere it applies: rising
            expenses, blank-rate raises and Social Security increases, and federal brackets and
            limits after 2026. Your bond allocation, property appreciation and all entered amounts
            stay the same.
          </p>
          <Callout kind="boundary">
            <p>
              An account with its own fixed stock growth or dividend yield keeps those rates in the
              replay; only its bond share follows history. See{" "}
              <HelpLink to="market-and-inflation-assumptions#account-overrides" />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "mapping-plan-years",
      title: "How plan years map to history",
      body: (
        <>
          <p>
            The mapping is one to one and in order. If your plan outlasts the data, the sequence
            continues from 1928. From that point the replay is a stitched scenario rather than one
            continuous period, and the result says so.
          </p>
          <DataTable
            caption="Preset periods for a 35-year plan starting in 2026"
            columns={[
              { key: "preset", label: "Preset" },
              { key: "years", label: "Historical years used" },
              { key: "wraps", label: "Continues from 1928 in" },
            ]}
            rows={[
              { preset: "1928 — Great Depression", years: "1928–1962", wraps: "—" },
              { preset: "1966 — Stagflation Era", years: "1966–2000", wraps: "—" },
              { preset: "1973 — Oil Crisis", years: "1973–2007", wraps: "—" },
              { preset: "2000 — Dot-Com Crash", years: "2000–2024, then 1928–1937", wraps: "2051" },
              {
                preset: "2007 — Global Financial Crisis",
                years: "2007–2024, then 1928–1944",
                wraps: "2044",
              },
              { preset: "2020 — COVID Crash", years: "2020–2024, then 1928–1957", wraps: "2031" },
            ]}
            note="Custom Year accepts any start from 1928 to 2024."
          />
          <p>
            A partial first year compounds its historical return over only the months modeled, like
            any first year. See <HelpLink to="first-plan-year" />.
          </p>
        </>
      ),
    },
    {
      id: "reading-the-result",
      title: "What the result shows",
      body: (
        <>
          <p>
            The replay line is drawn against the steady-return forecast. Alongside it you get the
            lowest year-end net worth, the lowest year-end cash and investments, and the net worth
            difference from the forecast in its final year. The outcome reads <em>Survived</em> when
            spending is funded every year and net worth stays positive, <em>Survived, but</em> when
            spending is funded but net worth turns negative, and
            <em> Failed</em> when spending goes unpaid. All amounts are nominal dollars.
          </p>
          <ExampleReplays />
          <DataTable
            caption="Example plan across the presets"
            columns={[
              { key: "preset", label: "Start year" },
              { key: "outcome", label: "Outcome" },
              { key: "low", label: "Lowest cash and investments", format: "usd" },
              { key: "end", label: "Net worth in 2060", format: "usd" },
            ]}
            rows={[
              { preset: "1928", outcome: "Funded", low: 617477, end: 3088829 },
              { preset: "1966", outcome: "Runs out in 2055, age 89", low: 0, end: -1032167 },
              { preset: "1973", outcome: "Funded", low: 724428, end: 2639229 },
              { preset: "2000", outcome: "Funded", low: 739625, end: 912695 },
              { preset: "2007", outcome: "Funded", low: 851929, end: 2452975 },
              { preset: "2020", outcome: "Funded", low: 741344, end: 2543838 },
            ]}
            note="$1,000,000 in a brokerage account at 60, $40,000 of spending rising with inflation, 40% bonds, plan default rates. The steady-return forecast ends at $771,797."
          />
          <p>
            A replay that starts with a crash isn’t always the worst one. Here 1928 recovers while
            1966 fails. From 1966 through 1981 prices nearly tripled, raising spending, while stocks
            and bonds both lost value after inflation. From 1928 through 1942 prices ended slightly
            lower.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Historical Stress Test", "Scenario"]} />, then{" "}
              <strong>Run Stress Test</strong>. Editing the plan clears the result.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "hypothetical-presets",
      title: "Hypothetical presets",
      body: (
        <>
          <p>
            A hypothetical preset changes one part of your plan from a start year you choose, then
            runs the steady projection. Every input and year the preset doesn’t touch keeps your own
            entries and assumptions. The event begins in January of the start year, or in the plan’s
            first month when that is the start year.
          </p>
          <DataTable
            caption="What each preset changes"
            columns={[
              { key: "preset", label: "Preset" },
              { key: "change", label: "What changes" },
              { key: "defaults", label: "Defaults" },
            ]}
            rows={[
              {
                preset: "Job loss",
                change:
                  "The chosen person’s wages and self-employment income stop for the months entered, then resume at the entered share of the previous amount for the rest of the plan. Contributions tied to that pay follow it.",
                defaults: "6 months, 80%",
              },
              {
                preset: "Market crash",
                change:
                  "Stocks lose the entered percentage in the start year, dividends included; in a partial first year the whole drop falls in the months modeled. Bonds, inflation and every other year keep your assumptions.",
                defaults: "35% drop",
              },
              {
                preset: "Market downturn",
                change:
                  "A decline over several years, an optional recovery, and optional bond and inflation rates for the decline years. See the next section.",
                defaults: "3 years, 45% decline, 3-year recovery",
              },
              {
                preset: "Tech bust: job loss + crash",
                change: "Both of the above in the same year.",
                defaults: "6 months, 80%, 35% drop",
              },
              {
                preset: "New child",
                change:
                  "A child born in the start year: an essential expense in today’s dollars that rises with inflation for 18 years, and the child tax credit through age 16.",
                defaults: "$18,000 a year",
              },
            ]}
          />
          <Callout kind="boundary">
            <ul>
              <li>
                Severance and unemployment benefits aren’t modeled. Reduced pay also applies to that
                person’s later wage streams.
              </li>
              <li>An account with its own fixed stock growth keeps it in the crash year.</li>
              <li>
                A new child doesn’t change marketplace household size, health premiums or filing
                status.
              </li>
            </ul>
          </Callout>
          <Callout kind="where">
            <p>
              <UIPath steps={["Historical Stress Test", "Scenario", "Hypothetical"]} />, set the
              start year and preset fields, then <strong>Run Stress Test</strong>.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "custom-market-downturn",
      title: "Custom market downturn",
      body: (
        <>
          <p>
            The market downturn preset spreads a stock decline over one to ten years from the start
            year, then lets stocks climb back. You set:
          </p>
          <ul>
            <li>
              <strong>Years of decline</strong> (1–10) and <strong>Total stock decline (%)</strong>{" "}
              (1–90): the cumulative peak-to-trough loss in stocks’ total return, dividends
              included.
            </li>
            <li>
              <strong>Recovery years</strong> (0–10): how long stocks take to return to their level
              before the downturn. Zero returns to your own assumptions the year after the trough.
            </li>
            <li>
              <strong>Bond return (%/yr)</strong> (−50 to 50) and <strong>Inflation (%/yr)</strong>{" "}
              (−10 to 30): annual rates for the decline years only.
            </li>
          </ul>
          <Callout kind="entry">
            <p>
              Leave bond return or inflation blank to keep your plan’s assumption for those years.
            </p>
          </Callout>
          <p>
            Every decline year loses the same share, so the yearly losses compound to exactly the
            total you enter. Each recovery year earns the same return, chosen so stocks end the
            recovery back at their pre-downturn level. That is the level stocks started from, not
            where your assumed growth would have taken them.
          </p>
          <Formula result="Stock return in each decline year">
            <V>(1 − total decline)</V>
            <Op>^</Op>
            <V>1 ÷ years of decline</V>
            <Op>−</Op>
            <V>1</V>
          </Formula>
          <Formula result="Stock return in each recovery year">
            <V>(1 − total decline)</V>
            <Op>^</Op>
            <V>−1 ÷ recovery years</V>
            <Op>−</Op>
            <V>1</V>
          </Formula>
          <DataTable
            caption="Three tough years: a 45% decline over 3 years with a 3-year recovery"
            columns={[
              { key: "year", label: "Year of the shock" },
              { key: "phase", label: "Phase" },
              { key: "stock", label: "Stock return", format: "pct", digits: 2 },
              {
                key: "index",
                label: "Stock level at year-end (start = 100)",
                format: "num",
                digits: 1,
              },
            ]}
            rows={[
              { year: "1", phase: "Decline", stock: -0.1807, index: 81.9 },
              { year: "2", phase: "Decline", stock: -0.1807, index: 67.1 },
              { year: "3", phase: "Decline", stock: -0.1807, index: 55.0 },
              { year: "4", phase: "Recovery", stock: 0.2205, index: 67.1 },
              { year: "5", phase: "Recovery", stock: 0.2205, index: 81.9 },
              { year: "6", phase: "Recovery", stock: 0.2205, index: 100.0 },
            ]}
          />
          <p>
            Your bond return, inflation and dividend split assumptions stay in place through the
            recovery. In the decline years a bond or inflation rate you enter replaces your
            assumption: inflation then drives expenses, raises, Social Security increases and
            federal indexing for those years, as in a historical replay. Years past the end of your
            plan are dropped. When the downturn starts in a partial first year, that year’s whole
            share of the decline falls in the months modeled, as in the market crash preset. After a
            run, a chart traces the stock level through the decline and recovery.
          </p>
          <Callout kind="boundary">
            <ul>
              <li>
                The shock applies to every account through its own stock and bond mix; you can’t
                pick accounts. An account with its own fixed stock growth keeps it.
              </li>
              <li>
                One fixed path, not a range of outcomes. Interest on cash, property values and loan
                rates keep your assumptions.
              </li>
            </ul>
          </Callout>
          <Callout kind="where">
            <p>
              <UIPath steps={["Historical Stress Test", "Scenario", "Market downturn"]} />.{" "}
              <strong>Three tough years</strong>, <strong>Lost decade</strong>,{" "}
              <strong>Stagflation</strong> and <strong>Crash and rebound</strong> fill the fields
              with a starting shape you can edit.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "not-modeled",
      title: "What isn’t modeled",
      body: (
        <>
          <ul>
            <li>
              Changes within a year. Each year gets one annual return, so a low point inside a year
              can be lower than the year-end balances shown.
            </li>
            <li>
              Historical tax law, interest rates on your loans, or property values. Only the three
              market series change.
            </li>
            <li>Other markets, or histories before 1928.</li>
          </ul>
        </>
      ),
    },
  ],
};
export default article;

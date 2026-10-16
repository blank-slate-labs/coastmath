import type { Article } from "../help_types";
import { Callout, Figure, Formula, HelpLink, Ledger, Op, Symptoms, UIPath, V } from "../help_kit";
import { LineChart } from "../help_charts";

/* Share of each discretionary expense kept, by drawdown (percent), for rules −10% → 10% and
   −20% → 30% with a 75% floor. Engine output; see the sources record. */
const keptRows: [number, number, number][] = [
  [-30, 0.75, 0.75],
  [-29, 0.75, 0.75],
  [-28, 0.75, 0.75],
  [-27, 0.75, 0.75],
  [-26, 0.75, 0.75],
  [-25, 0.75, 0.75],
  [-24, 0.75, 0.75],
  [-23, 0.75, 0.75],
  [-22, 0.75, 0.75],
  [-21, 0.75, 0.75],
  [-20, 0.75, 0.75],
  [-19, 0.9, 0.75],
  [-18, 0.9, 0.75],
  [-17, 0.9, 0.76],
  [-16, 0.9, 0.78],
  [-15, 0.9, 0.8],
  [-14, 0.9, 0.82],
  [-13, 0.9, 0.84],
  [-12, 0.9, 0.86],
  [-11, 0.9, 0.88],
  [-10, 0.9, 0.9],
  [-9, 1, 1],
  [-8, 1, 1],
  [-7, 1, 1],
  [-6, 1, 1],
  [-5, 1, 1],
  [-4, 1, 1],
  [-3, 1, 1],
  [-2, 1, 1],
  [-1, 1, 1],
  [0, 1, 1],
];

const keptFigure = (
  <Figure
    title="Share of each discretionary expense kept, by drawdown from the all-time high"
    caption="Rules: at −10%, reduce 10%; at −20%, reduce 30%. The 75% floor overrides the 30% reduction. Plotted at whole percents."
    table={{
      columns: [
        { key: "perf", label: "Drawdown (%)", format: "num" },
        { key: "step", label: "Kept, step", format: "pct", digits: 0 },
        { key: "linear", label: "Kept, linear", format: "pct", digits: 0 },
      ],
      rows: keptRows.map(([perf, step, linear]) => ({ perf, step, linear })),
    }}
  >
    <LineChart
      label="Share of discretionary spending kept as the drawdown deepens from 0% to −30%, for step and linear interpolation"
      xFormat="num"
      yFormat="pct"
      yMin={0.7}
      yMax={1}
      series={[
        { id: "step", label: "Step", color: "magenta", points: keptRows.map(([x, y]) => [x, y]) },
        {
          id: "linear",
          label: "Linear",
          color: "gray",
          points: keptRows.map(([x, , y]) => [x, y]),
        },
      ]}
    />
  </Figure>
);

const article: Article = {
  intro: (
    <>
      <p>
        Flexible spending rules cut your discretionary expenses in a year that follows weak
        investment performance. CoastMath measures the performance of your own portfolio over
        completed years, finds the reduction your thresholds call for, and applies it to the
        discretionary part of every expense, never below the spending floor. Essential spending and
        all other outflows are paid in full.
      </p>
      <p>
        A reduction lasts one year. Each year is measured again, and spending returns to its full
        planned amount as soon as performance is back above your first threshold. Nothing cut is
        made up later.
      </p>
      <p>
        Two opt-in settings extend the rules. <em>Upside points</em> raise discretionary spending
        when the portfolio finishes above its earlier high, and{" "}
        <em>Unallocated cash at year end</em> can count cash your saving rules left over as extra
        discretionary spending. You can also choose which kinds of spending the multiplier applies
        to. With none of these set, the rules behave exactly as described in the first two
        paragraphs.
      </p>
    </>
  ),
  sections: [
    {
      id: "what-gets-reduced",
      title: "What the rules apply to",
      body: (
        <>
          <p>
            By default, only the discretionary part of expenses paid from general cash flow: all of
            a <em>Discretionary</em> expense, or the share set by a <em>Custom</em> split. A $10,000
            expense that is 40% discretionary keeps its $6,000 essential part; a 20% reduction cuts
            $800 from the other $4,000. These are never reduced:
          </p>
          <ul>
            <li>essential expenses, and the essential part of a custom split</li>
            <li>expenses funded from specific accounts, and payroll deductions</li>
            <li>health coverage, loan payments, charitable gifts and taxes</li>
          </ul>
          <p>
            The rules apply from the year the start milestone is reached until the year the end
            milestone is reached, or for the whole plan if neither is set. Categories are set on
            each expense; see <HelpLink to="expenses" />.
          </p>
          <p>
            Under <em>Apply flex rules to</em> you can add two more kinds of spending. Each year the
            multiplier is applied in a fixed order:
          </p>
          <ol>
            <li>
              <strong>Ordinary expenses</strong> (selected by default): the discretionary part of
              each expense, as above.
            </li>
            <li>
              <strong>Withdrawal-strategy spending</strong>: the amount a{" "}
              <HelpLink to="withdrawal-strategies" /> rule sets for the year. The rule’s minimum and
              maximum still bound the result, and a reduction never takes spending below your
              planned essential expenses. Expenses the rule leaves running are handled as in the
              first step.
            </li>
            <li>
              <strong>Leftover spending</strong>: the cash counted as spending under{" "}
              <em>Unallocated cash at year end</em>, described below.
            </li>
          </ol>
          <p>
            Every run uses this order: the main projection, each <HelpLink to="chance-of-success" />{" "}
            trial and each stress-test period.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Flexible spending", "Enable flex spending rules"]} />, then{" "}
              <em>Save spending</em>.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-performance-is-measured",
      title: "How performance is measured",
      body: (
        <>
          <p>
            Each year’s return is the growth of your investment accounts taken together, before that
            year’s deposits and withdrawals, so saving and spending don’t count as gains or losses.
            Checking and savings balances are excluded. The year being spent is never included: the
            measure uses completed years only.
          </p>
          <p>
            <strong>Trailing return</strong> compounds the last one to five completed years, set by{" "}
            <em>Trailing lookback period (years)</em>:
          </p>
          <Formula result="Trailing return">
            <V>(1 + return₁)</V>
            <Op>×</Op>
            <V>…</V>
            <Op>×</Op>
            <V>(1 + returnₙ)</V>
            <Op>−</Op>
            <V>1</V>
          </Formula>
          <p>
            <strong>Drawdown from all-time high</strong> chains every completed year’s return into
            an index that starts at 1 in the plan’s first year, and compares the latest value with
            the highest the index has reached:
          </p>
          <Formula result="Drawdown">
            <V>Index after the last completed year</V>
            <Op>÷</Op>
            <V>Highest index so far</V>
            <Op>−</Op>
            <V>1</V>
          </Formula>
          <p>
            Until enough years have completed (one for the drawdown measure, the lookback length for
            trailing return), no reduction applies. The high-water mark is set within the
            projection, not by market history before your plan starts.
          </p>
        </>
      ),
    },
    {
      id: "thresholds-and-the-floor",
      title: "Thresholds, interpolation and the floor",
      body: (
        <>
          <p>
            Each threshold pairs a performance level with a reduction that applies when performance
            falls below it. With more than one threshold:
          </p>
          <ul>
            <li>
              <strong>Step</strong> uses the reduction of the deepest threshold crossed.
            </li>
            <li>
              <strong>Linear</strong> scales the reduction in proportion to where performance falls
              between two adjacent thresholds.
            </li>
            <li>
              Beyond the deepest threshold, its reduction applies in both modes; above the
              shallowest, there is none.
            </li>
          </ul>
          <Formula
            result="Share kept"
            note="The floor is a share of each expense’s own planned discretionary amount, not of total spending."
          >
            <V>the larger of</V>
            <V>(1 − reduction)</V>
            <Op>and</Op>
            <V>Spending floor</V>
          </Formula>
          {keptFigure}
          <Callout kind="entry">
            <p>
              Thresholds are negative percentages for losses: −10 means a 10% decline. A reduction
              larger than 100% minus the floor has no further effect; with the default 80% floor, no
              discretionary expense is cut by more than 20%.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "raising-spending",
      title: "Raising spending after new highs",
      body: (
        <>
          <p>
            Upside points are available with the drawdown measure. Each point pairs a gain with an
            increase: when the portfolio finishes above its earlier high by at least that gain,
            discretionary spending rises by that increase. They sit beside your reduction thresholds
            and do not change them.
          </p>
          <p>
            The comparison is against the high reached <em>before</em> the latest completed year, so
            a year that sets a new high counts as a gain over the old one:
          </p>
          <Formula result="Gain over the earlier high">
            <V>Index after the last completed year</V>
            <Op>÷</Op>
            <V>Highest index before that year</V>
            <Op>−</Op>
            <V>1</V>
          </Formula>
          <ul>
            <li>
              The neutral point is zero. At or below the earlier high there is no increase, so
              spending is never raised while the portfolio is recovering to a previous peak.
            </li>
            <li>
              <strong>Step</strong> uses the increase of the highest point the gain has reached.{" "}
              <strong>Linear</strong> rises from no increase at a zero gain to the first point’s
              increase, then scales between adjacent points. Above the last point, its increase
              holds in both modes.
            </li>
            <li>
              The year being spent is never included, and deposits and withdrawals do not move the
              index, exactly as for reductions.
            </li>
            <li>
              Each point is a gain above 0% and up to 1,000%, with an increase from 0% to 200%.
              Thresholds can’t repeat, and you can set up to ten points.
            </li>
          </ul>
          <Ledger
            title="Spending in 2028 with upside points"
            rows={[
              {
                label: "Index after 2026 (+10%)",
                value: 1.1,
                format: "num",
                digits: 4,
                detail: "The earlier high",
              },
              { op: "→", label: "Index after 2027 (+12%)", value: 1.232, format: "num", digits: 4 },
              { op: "=", label: "Gain over the earlier high", value: 0.12, format: "pct" },
              {
                op: "→",
                label: "Increase, linear between 5% → 10% and 20% → 30%",
                value: 0.1933,
                format: "pct",
                detail: "10% + (7 ÷ 15) × (30% − 10%)",
              },
              { label: "Travel as planned", value: 20000 },
              { op: "×", label: "Share spent", value: 1.1933, format: "pct" },
              { op: "=", label: "Travel in 2028", value: 23867 },
            ]}
            note="Housing stays at $40,000. In 2027 the gain over the starting level of 1.0 was 10%, so travel was $23,333. With a 0% return in 2028, the index is level with its high in 2029 and travel is back to $20,000."
          />
          <p>
            Any increase is listed separately from reductions in each year’s results, so a year
            shows one or the other.
          </p>
        </>
      ),
    },
    {
      id: "spending-the-leftover",
      title: "Spending the leftover",
      body: (
        <>
          <p>
            By default, cash your saving rules don’t allocate in a year is deposited to the account
            that catches the remainder. Choosing <em>Spend it as extra discretionary spending</em>{" "}
            counts that cash as spending instead. It appears as “Leftover spending” in the year’s
            cash flow and in the spending totals, and it earns no growth because it never reaches an
            account.
          </p>
          <ul>
            <li>
              <strong>Only the year’s own residual is spent.</strong> That is income and other
              inflows after taxes, expenses, loan payments and every saving rule you have funded. A
              rule with a cap is funded to its cap first.
            </li>
            <li>
              <strong>Existing balances are never touched.</strong> Nothing is withdrawn to create
              leftover, and account balances you already hold, including accounts with a withdrawal
              lock, are not spent.
            </li>
            <li>
              <strong>A year with no residual spends nothing.</strong> If bills exceed income there
              is no leftover, and the shortfall is handled by withdrawals as usual. Leftover is
              never created by borrowing against the plan.
            </li>
            <li>
              <strong>A part-year start</strong> spends only the residual of the months simulated.
            </li>
          </ul>
          <p>
            The leftover is held as cash until the year’s taxes are settled, and it is spent last. A
            refund for the year is added to the held cash and spent once, with the rest. A bill for
            the year is paid from the held cash before anything is spent, and only a bill larger
            than the held cash is withdrawn. If you set a delay in tax settlement, a refund or bill
            for a year arrives in the later year as ordinary cash and is treated like that year’s
            other cash flow, so it can be spent or can reduce what is spent in that year.
          </p>
          <Ledger
            title="Leftover in a year with a $10,000 saving rule"
            rows={[
              { label: "Salary", value: 90000 },
              { op: "−", label: "Income tax at a flat 20%", value: 18000 },
              { op: "−", label: "Housing", value: 40000 },
              { op: "−", label: "Saved by the rule, capped at", value: 10000 },
              {
                op: "=",
                label: "Leftover spending",
                value: 22000,
                detail: "The year’s spending is $62,000; net worth rises only by the $10,000 saved",
              },
            ]}
          />
          <p>
            With <em>Leftover spending</em> selected under <em>Apply flex rules to</em>, the
            multiplier scales the leftover: at 70%, 70% of it is spent and the remaining 30% is
            saved as usual. A multiplier above 100% never spends more than is available, so the
            whole leftover is spent and nothing more.
          </p>
        </>
      ),
    },
    {
      id: "worked-example",
      title: "Worked example",
      body: (
        <>
          <p>
            A portfolio returns +12%, −15% and +4% in 2026–2028. The rules use the drawdown measure
            with the thresholds in the chart above, linear interpolation and a 75% floor. Travel is
            a $20,000 discretionary expense; housing is a $40,000 essential one.
          </p>
          <Ledger
            title="Spending in 2029"
            rows={[
              {
                label: "Index after 2026",
                value: 1.12,
                format: "num",
                digits: 4,
                detail: "The all-time high",
              },
              {
                op: "→",
                label: "Index after 2028",
                value: 0.99008,
                format: "num",
                digits: 4,
                detail: "1.12 × 0.85 × 1.04",
              },
              { op: "=", label: "Drawdown", value: -0.116, format: "pct" },
              {
                op: "→",
                label: "Reduction, linear between −10% and −20%",
                value: 0.132,
                format: "pct",
                detail: "10% + (1.6 ÷ 10) × (30% − 10%)",
              },
              { label: "Travel as planned", value: 20000 },
              { op: "×", label: "Share kept", value: 0.868, format: "pct" },
              { op: "=", label: "Travel in 2029", value: 17360 },
            ]}
            note="Housing stays at $40,000. In 2028 the drawdown after 2027 alone was −15%, so travel was $16,000 (a 20% cut). With returns of 5% from 2029, travel is back to $20,000 in 2030."
          />
        </>
      ),
    },
    {
      id: "where-it-shows",
      title: "Where the effect shows up",
      body: (
        <>
          <p>
            Reduced expenses appear at their reduced amounts in the year’s cash flow. With a fixed
            return assumption, every projected year has the same return, so a rule either never
            fires or fires every year once the lookback fills. The rules matter most in runs where
            returns vary: each path in <HelpLink to="chance-of-success" /> and each period in{" "}
            <HelpLink to="historical-stress-test" /> applies them to its own returns.
          </p>
          <Callout kind="boundary">
            <p>
              Unless you add upside points, the rules only cut. They never adjust spending to a
              withdrawal rate. Essential expenses are never reduced, and missed spending isn’t made
              up later. A strategy’s own spending and the leftover are flexed only when you select
              them under <em>Apply flex rules to</em>.
            </p>
          </Callout>
          <Symptoms
            rows={[
              {
                symptom: "The rules never reduce anything in the main projection",
                check: "Whether your return assumption is fixed and above your first threshold",
                next: "Look at success odds or the historical stress test, where returns vary.",
              },
              {
                symptom: "A cut is smaller than the reduction you entered",
                check: "The spending floor",
                next: "Lower the floor to allow deeper cuts.",
              },
              {
                symptom: "No cut in the year after a crash",
                check: "The lookback length and the rule’s start milestone",
                next: "A longer lookback waits for more completed years and can dilute one bad year.",
              },
              {
                symptom: "Spending never rises above plan",
                check:
                  "Whether you set upside points, use the drawdown measure and the portfolio finishes above its earlier high",
                next: "A year level with its high, or a recovery below it, gives no increase.",
              },
              {
                symptom: "Leftover spending is lower than the cash left after saving",
                check:
                  "Whether leftover is selected under Apply flex rules to, and the year’s tax settlement",
                next: "A reduction saves the unspent share; a bill or delayed settlement changes what is left.",
              },
              {
                symptom: "An expense you consider optional isn’t reduced",
                check: "Its category and funding",
                next: "Mark it Discretionary and fund it from general cash flow.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};

export default article;

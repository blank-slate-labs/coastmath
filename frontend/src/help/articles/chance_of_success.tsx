import type { Article } from "../help_types";
import { Callout, DataTable, HelpLink, KeyFigures, Ledger, UIPath } from "../help_kit";
import { ExampleFan } from "../figures/chance_of_success";

const article: Article = {
  intro: (
    <>
      <p>
        The Success odds tab reruns your whole plan many times, 1,000 by default. Each run, or
        trial, replaces the steady assumed returns with a different sequence of stock returns, bond
        returns and inflation drawn from U.S. market history since 1928. Everything else in the plan
        is the same in every trial.
      </p>
      <p>
        The funding success rate is the share of trials that paid every year’s spending and never
        ran out of cash and investments. It’s a count of simulated outcomes, not a forecast
        probability.
      </p>
    </>
  ),
  sections: [
    {
      id: "what-varies",
      title: "What varies between trials",
      body: (
        <>
          <p>
            Each year of a trial takes three rates from one historical year: the U.S. stock total
            return, the U.S. Treasury bond return and consumer price inflation. The stock return is
            split into dividends and price growth using that year’s recorded dividend yield, so
            dividend income varies too.
          </p>
          <p>These follow the sampled rates in every trial:</p>
          <ul>
            <li>
              Stock and bond growth in every investment account, blended by its bond allocation.
            </li>
            <li>Inflation of your expenses and today’s-dollar amounts.</li>
            <li>Raises on pay and Social Security increases with a blank growth rate.</li>
            <li>Federal brackets, deductions and limits after 2026.</li>
            <li>
              Anything that reacts to those results: taxes, withdrawals, flexible-spending cuts, and
              milestones triggered by net worth.
            </li>
          </ul>
          <p>These stay fixed in every trial:</p>
          <ul>
            <li>Life expectancy, milestone ages and dates, and every entered amount and rate.</li>
            <li>Bond allocation, including a curve.</li>
            <li>
              Home and property appreciation, loan rates, and a medical inflation rate you set.
            </li>
            <li>
              An account’s own fixed stock growth and dividend yield. Only that account’s bond share
              varies.
            </li>
            <li>Tax law as modeled.</li>
          </ul>
        </>
      ),
    },
    {
      id: "how-sequences-are-built",
      title: "How a trial’s market history is built",
      body: (
        <>
          <p>
            By default a trial strings together blocks of consecutive historical years, each block 3
            to 7 years long and starting at a random year from 1928 to 2024. Blocks keep real runs
            of good and bad years, and the three rates in a year always come from the same
            historical year. Other sampling methods are described in the next section.
          </p>
          <p>
            By default each sampled rate is then calibrated to your plan. Every year of the history
            is shifted by the same factor so that its long-run compound rate equals your assumption
            for that year. Year-to-year swings keep their historical size and order. For stocks, the
            target is your price growth plus your dividend yield.
          </p>
          <Ledger
            title="Example: 1931 stocks, calibrated to a 7% total return"
            rows={[
              {
                label: "1 + 1931 stock return",
                value: 0.5619,
                format: "num",
                digits: 4,
                detail: "A 43.81% loss",
              },
              {
                op: "×",
                label: "1 + your stock total return",
                value: 1.07,
                format: "num",
                digits: 4,
              },
              {
                op: "÷",
                label: "1 + historical compound stock return, 1928–2024",
                value: 1.0994,
                format: "num",
                digits: 4,
              },
              {
                op: "=",
                label: "1 + calibrated return",
                value: 0.5469,
                format: "num",
                digits: 4,
                detail: "A 45.31% loss in that trial year",
              },
            ]}
            note="Bond returns and inflation are shifted the same way against their own historical averages of 4.74% and 3.04% a year."
          />
          <p>
            Turn calibration off to use unadjusted history. Its compound stock return is about 10% a
            year, well above the 7% default, so the success rate usually rises. The example plan
            below goes from 69.1% calibrated to 90.9% uncalibrated.
          </p>
          <DataTable
            caption="Run settings"
            columns={[
              { key: "setting", label: "Setting" },
              { key: "default", label: "Default" },
              { key: "effect", label: "Effect" },
            ]}
            rows={[
              {
                setting: "Trials",
                default: "1,000",
                effect: "Choose 100, 500 or 1,000. More trials steady the rate.",
              },
              {
                setting: "Random seed",
                default: "42",
                effect:
                  "The same seed and plan give the same result. Leave it blank for a fresh random run.",
              },
              {
                setting: "Minimum and maximum block length",
                default: "3 and 7 years",
                effect: "Block bootstrap only. Longer blocks keep longer historical runs together.",
              },
              {
                setting: "Failure definition",
                default: "Liquid assets depleted / spending unfunded",
                effect: "See below.",
              },
              {
                setting: "Calibrate sampled returns to this plan’s assumptions",
                default: "On",
                effect: "Off samples raw history.",
              },
            ]}
          />
          <Callout kind="where">
            <p>
              <UIPath steps={["Success odds", "Run settings and success criteria"]} />. Changing the
              plan or a setting clears the last result; run it again after the forecast updates.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "sampling-methods",
      title: "Sampling methods and return sources",
      body: (
        <>
          <p>
            <strong>Sampling method</strong> chooses how historical years are lined up in a trial.
            Every method uses the 97 years from 1928 to 2024, takes all rates in a year from the
            same historical year, and is calibrated to your plan unless you turn calibration off.
          </p>
          <DataTable
            caption="Sampling methods"
            columns={[
              { key: "method", label: "Method" },
              { key: "how", label: "How years are chosen" },
            ]}
            rows={[
              {
                method: "Block bootstrap",
                how: "The default. Blocks of a random length between the minimum and maximum, each from a random start year. A block that runs past 2024 continues from 1928.",
              },
              {
                method: "Moving blocks",
                how: "Blocks of one fixed length (5 years unless you change it). A block never runs past 2024, so the last years of history are drawn less often.",
              },
              {
                method: "Historical sequences",
                how: "One trial per start year, replaying history in order. When history runs out you choose: loop back to 1928, use only start years with enough data for the whole plan, or switch to a random year. With the switch you can repeat each start year up to 100 times. The trial count is the number of start years times the repeats, so the Trials setting doesn’t apply.",
              },
              {
                method: "Random start year, then in order",
                how: "A random start year, then history in order, switching to another random year when it runs out.",
              },
              {
                method: "Random independent years",
                how: "Every plan year draws its own historical year, so runs of good and bad years are broken up.",
              },
            ]}
          />
          <p>
            <strong>Return sources</strong> let you replace any of stock total return, stock
            dividend yield, bond return and inflation with a normal distribution you set by mean and
            standard deviation, in percent. A normal variable is drawn fresh each year,
            independently of the other variables and of history; the historical variables still come
            from the sampled year together. Draws are limited to a −100% return and a yield of zero
            or more, and calibration doesn’t adjust them. When all four are normal, the sampling
            method has no effect.
          </p>
          <p>
            A normal mean is an average yearly return, not a compound rate. Ups and downs lower
            compound growth, so a 10% mean with an 18% standard deviation compounds at about 8.5% a
            year. Your plan’s assumed rates are compound rates, so a normal mean equal to your
            assumption grows more slowly than the steady forecast. Set the mean higher if you want
            the two to match on average.
          </p>
          <p>
            <strong>Separate crypto return distribution</strong> gives cryptocurrency accounts their
            own yearly normal return in place of the stock price return, even when the account sets
            its own fixed growth rate. Crypto pays no dividends, so the draw is the whole return.
            Without it, crypto accounts grow like the stock price return.
          </p>
          <p>
            Each trial still reruns exactly from the run’s seed and the trial number, whichever
            method you choose. For historical sequences, a rerun trial shows the historical year it
            started from.
          </p>
        </>
      ),
    },
    {
      id: "how-success-is-counted",
      title: "How success is counted",
      body: (
        <>
          <p>A trial fails in the first year that either happens:</p>
          <ul>
            <li>Spending can’t be fully paid from the withdrawal order.</li>
            <li>
              The failure test is met at year end. The default test is that cash and investment
              balances total zero or less. The net-worth test uses total net worth instead, which
              adds property and subtracts debt.
            </li>
          </ul>
          <p>
            The funding success rate counts every trial that never fails. Two optional targets
            narrow success further and appear as a separate target success rate:
          </p>
          <ul>
            <li>
              <strong>Final net worth target:</strong> the trial must end at or above this amount,
              in dollars of the final year. It starts at the plan’s <strong>Leave to heirs</strong>{" "}
              amount from <UIPath steps={["Partner and estate"]} />, inflated to that year.
            </li>
            <li>
              <strong>Count flexible-spending cuts as a shortfall:</strong> a trial whose
              flexible-spending rules cut spending in any year doesn’t count as meeting targets.
            </li>
          </ul>
          <p>
            Each trial lands in one outcome category: met all targets, survived with spending cuts,
            survived below target, or funding failure. Failure analysis groups failed trials by
            cause with their average age at failure.
          </p>
          <p>
            <strong>Outcome detail</strong> adds two breakdowns. Failed trials are early, mid or
            late by the share of plan years completed before the failure year: early before a third
            of the plan, late from two thirds, by default. Funded trials compare final net worth
            with net worth at the end of the year your retirement milestone happens, or of the first
            plan year when there isn’t one or it never happens. Choose that milestone under{" "}
            <strong>Retirement milestone</strong>; left on automatic, it is the first milestone
            whose name mentions retirement and not a partner. Both amounts are in today’s dollars of
            that trial’s own inflation. Below 25% is a thin margin, above 200% a wide margin, and
            anything between a moderate margin. You can change all four cut-offs and the milestone
            under <strong>Outcome detail</strong> in the run settings.
          </p>
          <p>
            <strong>Extra percentile charts</strong> add the same percentile bands as the net worth
            chart for net worth without real assets, spending, taxes or income, in nominal dollars.
          </p>
          <Callout kind="boundary">
            <p>
              A trial that runs out keeps going to the end of the plan with its unpaid spending
              subtracted from net worth. It isn’t rescued by later good years, and it’s counted
              once.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "reading-percentiles",
      title: "Reading the percentile chart",
      body: (
        <>
          <p>
            The chart ranks all trials’ net worth separately in each year. The median line is the
            middle value in each year, not one trial’s path, and a trial can sit near the top one
            year and near the bottom later. The 10th percentile is the value that 10% of trials fall
            below. Amounts are nominal dollars of each year.
          </p>
          <ExampleFan
            title="Example plan: net worth across 1,000 trials"
            caption="$1,000,000 in a brokerage account at 60, $40,000 of spending rising with inflation, 40% bonds, plan default rates. The steady-return projection is funded through the plan’s end; 69.1% of trials are. Negative values are unpaid spending after money runs out."
          />
          <KeyFigures
            caption="Example plan results"
            items={[
              { label: "Funding success rate", value: 0.691, format: "pct" },
              {
                label: "Failed trials",
                value: "309 of 1,000",
                detail: "Average age at failure 87",
              },
              { label: "Median final net worth, 2060", value: 1384414 },
              { label: "Steady-return projection, 2060", value: 771797 },
            ]}
          />
          <p>
            The median ending above or below the steady projection is normal. See{" "}
            <HelpLink to="plan-vs-chance-of-success" />.
          </p>
        </>
      ),
    },
    {
      id: "explore-trials",
      title: "Exploring individual trials",
      body: (
        <>
          <p>
            The percentile chart can’t show what one bad but funded trial looks like, or which
            trials reached a milestone late. The trial explorer below it lists every trial on its
            own.
          </p>
          <ul>
            <li>
              <strong>Histogram:</strong> each bar counts the trials whose final net worth falls in
              its range, with failed trials at the bottom in red. Select a bar to list only those
              trials, and select it again to clear it. The two outer bars also hold the few most
              extreme trials, so the rest stay readable.
            </li>
            <li>
              <strong>Outcome:</strong> all trials, funded, failed or, when a target is set, one
              outcome category.
            </li>
            <li>
              <strong>Milestone timing:</strong> trials that reached a milestone by an age, after an
              age or never. Ages are yours in the year the milestone happened.
            </li>
            <li>
              <strong>Order:</strong> by trial number, or by final net worth from lowest or highest.
            </li>
          </ul>
          <p>
            Each row shows the trial’s outcome, final net worth, failure year and a small net worth
            line. Select a row to rerun that trial. It uses the same market history as in the run,
            so the result matches the row exactly. You see its net worth for every year against the
            median of all trials, plus its key years: peak net worth, the largest one-year fall,
            milestones reached, the failure year and the final year.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Success odds", "Explore individual trials"]} />. Rerunning a trial
              needs the unchanged plan and settings. After an edit the run clears; run it again
              first.
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
              With historical sources, returns and inflation outside the range of U.S. history since
              1928, or any history other than U.S. stocks, Treasury bonds and consumer prices.
            </li>
            <li>
              Links between normal variables. Each normal draw is independent, so a bad stock year
              is no more likely to come with high inflation.
            </li>
            <li>Uncertain lifespans. Every trial ends at the plan’s life expectancy.</li>
            <li>
              Changes in tax law, benefit rules or your own behavior beyond the flexible-spending
              rules you set.
            </li>
            <li>
              Swings within a year. Each year gets one return, and failure is checked at year end.
            </li>
          </ul>
          <p>
            To replay one specific historical period instead of random blocks, use the{" "}
            <HelpLink to="historical-stress-test" />.
          </p>
        </>
      ),
    },
  ],
};
export default article;

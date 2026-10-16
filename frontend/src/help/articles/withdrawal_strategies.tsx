import type { Article } from "../help_types";
import { Callout, DataTable, Figure, HelpLink, Ledger, Steps, UIPath } from "../help_kit";
import { LineChart } from "../help_charts";

const ages = [65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83];
const constantDollar = ages.map(() => 40000);
const guytonKlinger = [
  40000, 40000, 39389, 34627, 34627, 34627, 34627, 34627, 34627, 34595, 34595, 34595, 34595, 34595,
  34595, 34595, 34595, 34595, 34595,
];
const vanguard = [
  40000, 39000, 38025, 37074, 36148, 35244, 34363, 33504, 32666, 31849, 31053, 30277, 29520, 29796,
  31286, 32850, 34100, 34402, 36122,
];
const lifeExpectancy = [
  43668, 42676, 39514, 35461, 40506, 42106, 41968, 28081, 28920, 24833, 26915, 29662, 30814, 33433,
  38128, 42430, 42237, 44168, 48978,
];
const constantPercent = [
  40000, 37698, 33834, 29446, 32597, 32862, 31788, 32881, 32637, 26898, 28103, 29857, 30035, 31421,
  34549, 37074, 35796, 36114, 38843,
];
const points = (values: number[]) => ages.map((age, i) => [age, values[i]] as [number, number]);

const article: Article = {
  intro: (
    <>
      <p>
        A withdrawal strategy sets your yearly spending from the portfolio instead of from your
        ordinary expenses. You can use one two ways: save it on your plan, so the projection, chance
        of success and reports spend by it, or run the comparison, which reruns your plan once for
        each withdrawal rule you pick and sets each rule’s spending path and survival beside your
        plan’s own spending.
      </p>
      <p>
        The comparison never changes your plan, and it ignores any strategy saved on it: its
        baseline is always your own expenses.
      </p>
    </>
  ),
  sections: [
    {
      id: "saving-a-strategy",
      title: "Saving a strategy on your plan",
      body: (
        <>
          <Callout kind="where">
            <p>
              <UIPath steps={["Flexible spending", "Set spending with a withdrawal strategy"]} />,
              then <em>Save spending</em>.
            </p>
          </Callout>
          <Steps>
            <li>
              Choose a Method. Only that method’s settings appear; each starts at the value the rule
              is usually quoted with, and every one can be changed.
            </li>
            <li>
              Choose a Start: the plan’s start, a milestone or an age. Before it, your plan spends
              its own expenses; once it starts, the strategy stays on.
            </li>
            <li>
              Optionally tick Minimum or Maximum and give each an amount in today’s dollars or as a
              % of portfolio.
            </li>
            <li>Choose how Other income is used (below), and save.</li>
          </Steps>
          <p>
            Unticking <em>Set spending with a withdrawal strategy</em> and saving keeps your choices
            but returns the plan to its own expenses. A milestone that starts a saved strategy can’t
            be deleted until you change the start.
          </p>
        </>
      ),
    },
    {
      id: "running-a-comparison",
      title: "Running a comparison",
      body: (
        <>
          <Callout kind="where">
            <p>
              <UIPath steps={["Success odds", "Compare withdrawal strategies"]} />
            </p>
          </Callout>
          <Steps>
            <li>Set the Initial withdrawal rate (%), from 0.1 to 20. It starts at 4.</li>
            <li>
              Choose when withdrawals start: a milestone under Withdrawals start at milestone, or a
              whole age under …or at age. The milestone defaults to one whose name contains “retir”.
            </li>
            <li>
              Optionally set Monte Carlo trials per rule (up to 500; 0 skips them) and a Seed, so a
              rerun gives the same result.
            </li>
            <li>Tick the Rules to compare and select Compare withdrawal rules.</li>
          </Steps>
        </>
      ),
    },
    {
      id: "the-rules",
      title: "How each rule sets spending",
      body: (
        <>
          <p>
            Every rule works from the portfolio: the total of all your account balances at the start
            of the year, before that year’s growth. In the first year every rule except the
            life-expectancy rule spends the initial rate times that portfolio. Spending never
            exceeds the portfolio.
          </p>
          <DataTable
            caption="The rules, as the comparison applies them"
            columns={[
              { key: "rule", label: "Rule" },
              { key: "later", label: "Each later year" },
            ]}
            rows={[
              {
                rule: "Constant dollar",
                later:
                  "Last year’s spending plus the year’s inflation, whatever the portfolio did.",
              },
              {
                rule: "Constant percentage",
                later: "The initial rate times this year’s portfolio.",
              },
              {
                rule: "Guyton-Klinger guardrails",
                later:
                  "Last year’s spending plus inflation, except no raise after a year of negative portfolio return while the withdrawal rate is above the initial rate. Then cut 10% if the withdrawal rate is above 120% of the initial rate, unless 15 or fewer plan years remain, or raise 10% if it is below 80% of it.",
              },
              {
                rule: "Vanguard dynamic spending",
                later:
                  "The initial rate times this year’s portfolio, held between 2.5% below and 5% above last year’s spending plus inflation.",
              },
              {
                rule: "IRS life-expectancy percentage",
                later:
                  "This year’s portfolio ÷ the IRS life-expectancy factor for your age: the Single Life Table before 72, the Uniform Lifetime Table from 72. Also used in the first year.",
              },
              {
                rule: "Fixed amount (saved only)",
                later:
                  "The amount you enter, in today’s dollars, so it rises with inflation. Untick Raise with inflation each year to hold the first year’s dollar amount. Also used in the first year.",
              },
              {
                rule: "1/N (saved only)",
                later:
                  "This year’s portfolio ÷ the years left in the plan, this year included. The final year spends what is left. Also used in the first year.",
              },
              {
                rule: "Variable percentage withdrawal (saved only)",
                later:
                  "This year’s portfolio × a percentage that spends it evenly over the years left at an assumed real return, withdrawn at the start of each year. The return blends a stock return (5% by default) and a bond return (1.9%) by your plan’s bond allocation for the year, so the percentage rises as the years left shrink. Also used in the first year.",
              },
              {
                rule: "Kitces ratchet (saved only)",
                later:
                  "Last year’s spending plus inflation. When the portfolio is at least 150% of its starting value plus inflation, spending also rises 10%, at most once every three years counted from the start. Spending is never cut by the rule.",
              },
              {
                rule: "Clyatt 95% rule (saved only)",
                later:
                  "The larger of the initial rate times this year’s portfolio and 95% of last year’s spending.",
              },
            ]}
          />
          <p>
            The comparison offers the first five rules with their built-in settings; a saved
            strategy offers all ten, with every setting editable.
          </p>
          <p>
            All five react differently to the same bad year. With a 4% rate, a $1,000,000 portfolio
            that falls to $800,000 after a −15% year, 3% inflation and ages 65 to 66:
          </p>
          <DataTable
            caption="Year-two spending after the portfolio falls to $800,000"
            columns={[
              { key: "rule", label: "Rule" },
              { key: "y1", label: "Year one", format: "usd" },
              { key: "y2", label: "Year two", format: "usd" },
            ]}
            rows={[
              { rule: "Constant dollar", y1: 40000, y2: 41200 },
              { rule: "Constant percentage", y1: 40000, y2: 32000 },
              { rule: "Guyton-Klinger guardrails", y1: 40000, y2: 36000 },
              { rule: "Vanguard dynamic spending", y1: 40000, y2: 40170 },
              { rule: "IRS life-expectancy percentage", y1: 43668, y2: 36364 },
              { rule: "Fixed amount: $40,000", y1: 40000, y2: 41200 },
              { rule: "1/N: 30 years left", y1: 33333, y2: 27586 },
              { rule: "Variable percentage: 30 years left, 60% stocks", y1: 54122, y2: 44116 },
              { rule: "Kitces ratchet", y1: 40000, y2: 41200 },
              { rule: "Clyatt 95% rule", y1: 40000, y2: 38000 },
            ]}
            note="The life-expectancy rule divides by 22.9 at 65 and 22.0 at 66. The variable percentage is 5.41% with 30 years left and 5.51% with 29."
          />
          <Ledger
            title="Guyton-Klinger in year two"
            rows={[
              { label: "Last year’s spending", value: 40000 },
              {
                label: "Withdrawal rate on $800,000",
                value: 0.05,
                format: "pct",
                detail: "Above 4% after a losing year, so no inflation raise",
              },
              { label: "Upper guardrail: 120% × 4%", value: 0.048, format: "pct" },
              {
                op: "×",
                label: "Cut, because 5.0% is above 4.8%",
                value: 0.9,
                format: "num",
                digits: 2,
              },
              { op: "=", label: "Year-two spending", value: 36000 },
            ]}
          />
        </>
      ),
    },
    {
      id: "bounds-and-income",
      title: "Minimums, maximums and other income",
      body: (
        <>
          <p>
            A saved strategy can have a Minimum, a Maximum or both. Each is either today’s dollars,
            raised with your plan’s inflation, or a % of portfolio, a share of the year’s starting
            portfolio. The method’s own rule runs first, then the minimum, then the maximum, so the
            maximum wins if the two conflict. The bounded amount is what the next year’s rule treats
            as last year’s spending. Spending still never exceeds the portfolio.
          </p>
          <Ledger
            title="Clyatt 95% rule with a 4.5% maximum, year two"
            rows={[
              { label: "95% of last year’s $40,000", value: 38000 },
              {
                label: "4% of the $800,000 portfolio",
                value: 32000,
                detail: "The rule keeps the larger: $38,000",
              },
              { label: "Maximum: 4.5% of $800,000", value: 36000 },
              { op: "=", label: "Year-two spending, and next year’s “last year”", value: 36000 },
            ]}
          />
          <DataTable
            caption="Other income"
            columns={[
              { key: "choice", label: "Choice" },
              { key: "meaning", label: "What the strategy amount means" },
            ]}
            rows={[
              {
                choice: "Income covers the strategy amount first; surplus is saved",
                meaning:
                  "The amount is the year’s ordinary spending, as in the comparison. Income pays for it first; only a shortfall is withdrawn, and income above it is saved by your income allocation rules.",
              },
              {
                choice: "Spend the withdrawal plus all net income",
                meaning:
                  "The amount is what leaves the portfolio. You spend it plus your income after taxes and fixed costs, so nothing is saved. Required distributions count toward the amount; any part of them above it is reinvested. In a year the rule starts partway through, the income left over from the months before it is saved as your plan would save it, and only the rule’s prorated amount is added to spending.",
              },
            ]}
          />
          <p>
            Either way, tax on the withdrawal is paid on top of it through your drawdown order, so
            the amount you choose is what you get to spend. Fixed costs that your income can’t cover
            are still withdrawn, even beyond the strategy amount.
          </p>
        </>
      ),
    },
    {
      id: "how-a-rule-is-simulated",
      title: "How a rule is simulated against your plan",
      body: (
        <>
          <p>
            A saved strategy and a comparison rerun are simulated the same way. Before the start
            point, the run is identical to your plan without a strategy. From the start, the rule’s
            amount replaces your ordinary expenses, prorated in a partial year. In the year a rule
            starts, your own expenses run until its start month (the milestone’s month, or your
            birthday month for a start age) and the rule’s amount covers the remaining months. These
            keep running as planned on top of it: payroll deductions, expenses paid from specific
            accounts, loan payments, property costs, charitable gifts and health coverage.
          </p>
          <p>
            Unless you choose to spend the withdrawal plus all net income, the rule sets spending,
            not the withdrawal. Income, required distributions and Social Security still come in
            first, and any shortfall is withdrawn through your drawdown order with its taxes,
            exactly as in <HelpLink to="withdrawal-order" />. A plan fails under a rule the same way
            it fails on its own.
          </p>
          <p>
            A saved strategy also applies in every <HelpLink to="chance-of-success" /> trial,
            reacting to that trial’s returns. In the comparison, the deterministic run uses your
            plan’s assumptions. When you ask for Monte Carlo trials, every rule, and your own plan,
            is run through the same set of simulated market histories, so their success rates are
            comparable. As with <HelpLink to="chance-of-success" />, the rates are estimates.
          </p>
          <Callout kind="boundary">
            <p>
              Flexible spending rules have no effect on the expenses a rule replaces. To flex the
              rule’s own amount, select <em>Withdrawal-strategy spending</em> under{" "}
              <em>Apply flex rules to</em> in <HelpLink to="flexible-spending" />: reductions and
              upside increases then scale the amount, the rule’s minimum and maximum still bound it,
              and a reduction never goes below your planned essential expenses.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "reading-the-results",
      title: "Reading the results",
      body: (
        <>
          <p>
            The chart shows each rule’s spending in today’s dollars, with your plan’s spending
            dashed. Today’s dollars remove your plan’s assumed inflation. A partial first year is
            shown at its annual rate.
          </p>
          <DataTable
            caption="Comparison columns"
            columns={[
              { key: "col", label: "Column" },
              { key: "meaning", label: "What it measures" },
            ]}
            rows={[
              {
                col: "Starting spending (nominal $)",
                meaning: "Spending in the first year the rule applies",
              },
              {
                col: "Median real spending, Lowest real",
                meaning: "Across the years from the start, in today’s dollars",
              },
              {
                col: "Largest real cut",
                meaning: "The deepest fall from an earlier peak, in today’s dollars",
              },
              {
                col: "Years below plan",
                meaning: "Years the rule spent less than your plan’s expenses",
              },
              { col: "Deterministic", meaning: "Survives, or the year the run first fails" },
              {
                col: "Monte Carlo success",
                meaning: "Share of trials that never fail, when trials were requested",
              },
            ]}
          />
          <Figure
            title="Real spending by rule: $1,000,000 at 65, 4% rate, market history from 2000"
            caption="A 60/40 portfolio in a qualified Roth IRA, so taxes don’t intervene, run through the returns and inflation of 2000–2018. Every rule survives. The life-expectancy rule drops at 72 when its divisor moves from the Single Life Table (18.0 at 71) to the Uniform Lifetime Table (27.4 at 72)."
            table={{
              columns: [
                { key: "age", label: "Age", format: "age" },
                { key: "cd", label: "Constant dollar", format: "usd" },
                { key: "cp", label: "Constant percentage", format: "usd" },
                { key: "gk", label: "Guyton-Klinger", format: "usd" },
                { key: "vd", label: "Vanguard dynamic", format: "usd" },
                { key: "le", label: "Life-expectancy percentage", format: "usd" },
              ],
              rows: ages.map((age, i) => ({
                age,
                cd: constantDollar[i],
                cp: constantPercent[i],
                gk: guytonKlinger[i],
                vd: vanguard[i],
                le: lifeExpectancy[i],
              })),
            }}
          >
            <LineChart
              label="Real spending by age for four withdrawal rules"
              xFormat="age"
              step
              series={[
                {
                  id: "cd",
                  label: "Constant dollar",
                  color: "gray",
                  points: points(constantDollar),
                },
                { id: "gk", label: "Guyton-Klinger", color: "blue", points: points(guytonKlinger) },
                { id: "vd", label: "Vanguard dynamic", color: "cyan", points: points(vanguard) },
                {
                  id: "le",
                  label: "Life-expectancy percentage",
                  color: "magenta",
                  points: points(lifeExpectancy),
                },
              ]}
            />
          </Figure>
          <p>
            In that history the guardrails rule cut once, at 68, and then held about $34,600 a year;
            the dynamic rule sat on its 2.5% floor for twelve years; constant percentage (in the
            data view) fell as low as $26,898.
          </p>
        </>
      ),
    },
    {
      id: "not-modeled",
      title: "What isn’t modeled",
      body: (
        <>
          <Callout kind="boundary">
            <ul>
              <li>
                Changing a rule’s settings in the comparison: it always uses the 10% guardrail step,
                the 120% and 80% guardrails, the 15-year window and the −2.5% and +5% dynamic
                limits. A saved strategy can change all of them.
              </li>
              <li>
                A strategy applied to only some accounts, or that ignores your income entirely.
              </li>
              <li>
                Spending a year’s leftover surplus later. Under the default choice, surplus is
                saved; <em>Unallocated cash at year end</em> in{" "}
                <HelpLink to="flexible-spending#spending-the-leftover" /> spends it in the year it
                arises instead.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
  ],
};

export default article;

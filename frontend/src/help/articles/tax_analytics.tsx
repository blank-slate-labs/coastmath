import type { Article } from "../help_types";
import { Callout, HelpLink, Ledger, Steps, UIPath } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        The Tax tools tab breaks down the tax your projection already calculated, year by year, and
        holds the tools that change it: Roth conversion rules, a bracket-filling strategy
        comparison, health coverage costs and early-withdrawal payment series. Every figure is in
        future (nominal) dollars for its year.
      </p>
      <p>
        Income and taxes over the whole plan, with effective and marginal rates, are charted on the
        Overview tab under <em>Income &amp; taxes</em>. The Tax tools tab is where you read one year
        in detail.
      </p>
    </>
  ),
  sections: [
    {
      id: "the-five-views",
      title: "The five views",
      body: (
        <>
          <p>
            Choose a view at the top of <UIPath steps={["Tax tools"]} />:
          </p>
          <ul>
            <li>
              <strong>Annual tax breakdown</strong>: one year’s taxes by component, its rates and
              its deduction.
            </li>
            <li>
              <strong>Conversion scenarios</strong>: add or remove fixed annual Roth conversion
              rules.
            </li>
            <li>
              <strong>Strategy comparisons</strong>: suggestions, and tests of bracket-filling
              conversions or gain harvesting against your plan as it is.
            </li>
            <li>
              <strong>Health coverage</strong>: marketplace premiums and credits, Medicare premiums
              and surcharges, by year.
            </li>
            <li>
              <strong>Early withdrawals</strong>: set up a substantially equal periodic payment
              series; see <HelpLink to="sepp-72t" />.
            </li>
          </ul>
          <p>
            The last four views also show <em>Review household accounts</em>, since each depends on
            which accounts exist and who owns them.
          </p>
        </>
      ),
    },
    {
      id: "annual-tax-breakdown",
      title: "Read one year’s taxes",
      body: (
        <>
          <Steps>
            <li>
              Open <UIPath steps={["Tax tools", "Annual tax breakdown"]} />.
            </li>
            <li>
              Pick the year in <em>Tax year</em>. It starts at the plan’s first year.
            </li>
            <li>
              Read the components. <em>Total taxes</em> is the sum of federal ordinary tax
              (including any alternative minimum tax), capital gains tax, state tax, local tax,
              payroll tax, net investment income tax and early withdrawal penalties.
            </li>
            <li>
              Below the components, check which deduction the year used and the standard deduction
              available.
            </li>
          </Steps>
          <Ledger
            title="Example: 2026 taxes on a $120,000 salary"
            rows={[
              {
                label: "Federal ordinary tax",
                value: 14930,
                detail:
                  "Single filer in Texas with a 10% traditional 401(k) deferral and the standard deduction",
              },
              { op: "+", label: "Payroll tax", value: 9180, detail: "7.65% of wages" },
              { op: "=", label: "Total taxes", value: 24110 },
              {
                op: "÷",
                label: "Income and realized taxable distributions/gains",
                value: 124800,
                detail: "Salary plus the $4,800 employer match",
              },
              { op: "=", label: "Effective rate", value: 0.193, format: "pct" },
            ]}
            note="Marginal rate for the year: 22%."
          />
          <p>
            <strong>Effective rate</strong> divides full-year taxes, penalties included, by
            calendar-year gross income, including taxable withdrawals, employer contributions,
            realized gains, dividends and the taxable amount of Roth conversions.
          </p>
          <p>
            <strong>Marginal rate</strong> is the federal ordinary-income bracket your taxable
            income reaches. It doesn’t add state tax, payroll tax, or the extra tax a dollar can
            cause by making Social Security taxable or by crossing a phase-out.
          </p>
          <p>
            Amounts here are rounded to thousands of dollars ($24k for the example’s total); the
            Overview year ledger’s <em>Tax breakdown</em> shows whole dollars.{" "}
            <em>Deduction and marginal-rate history</em> lists every year’s rate and deduction, and
            the <em>Deduction Comparison</em> chart shows the standard and itemized amounts year by
            year, with a count of the years you itemize. How each component is computed is in{" "}
            <HelpLink to="how-taxes-are-calculated" />.
          </p>
          <Callout kind="boundary">
            <p>
              In flat tax mode, brackets and deductions aren’t used, so the deduction, marginal-rate
              and comparison details are unavailable and strategy comparisons are turned off.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "conversion-scenarios",
      title: "Add a conversion rule",
      body: (
        <>
          <p>
            <em>Manual Roth conversions</em> adds a rule that converts up to a fixed amount each
            year from a traditional IRA or 401(k) to a Roth account with the same owner.
          </p>
          <Steps>
            <li>
              Open <UIPath steps={["Tax tools", "Conversion scenarios"]} />.
            </li>
            <li>
              Choose the <em>Traditional source</em>, then the <em>Roth destination</em>.
            </li>
            <li>
              Enter the <em>Annual conversion cap ($)</em> and choose <em>Add conversion rule</em>.
            </li>
          </Steps>
          <p>
            This changes your plan, not a copy: the rule is saved in the plan and the whole
            projection recalculates. Existing conversion and gain-harvesting rules are listed above
            the form; <em>Remove conversion</em> or <em>Remove rule</em> deletes one. To see what a
            conversion costs, compare the recalculated plan against a kept baseline: the annual
            breakdown then states the tax change across the years both projections share. How
            conversions are taxed is in <HelpLink to="roth-conversions" />.
          </p>
        </>
      ),
    },
    {
      id: "strategy-comparisons",
      title: "Compare bracket-filling strategies",
      body: (
        <>
          <p>
            <em>Tax strategy comparison</em> runs your full projection once for each bracket you
            test and once without a new rule, then ranks them on one objective.
          </p>
          <Steps>
            <li>
              Open <UIPath steps={["Tax tools", "Strategy comparisons"]} />.
            </li>
            <li>
              Under <em>Strategy</em>, choose <em>Roth conversions to fill an income bracket</em> or{" "}
              <em>Capital-gain harvesting to fill a capital-gains bracket</em>, then the accounts.
            </li>
            <li>
              Optionally limit the years with <em>Convert from</em> and <em>Convert until</em>, and
              set a <em>MAGI cap</em> in today’s dollars.
            </li>
            <li>
              Pick an <em>Objective</em>: end net worth, net estate, lifetime income taxes, or
              lifetime taxes plus health coverage.
            </li>
            <li>
              Tick the bracket ceilings to test and choose <em>Compare strategies</em>.
            </li>
          </Steps>
          <p>
            Each row shows the objective, its change against the baseline, the amount converted or
            harvested, lifetime taxes, health costs, net estate, and the number of years with a
            Medicare surcharge or a lost premium tax credit. The top result is marked{" "}
            <em>best tested</em>: the best of the candidates you chose, not the best possible
            strategy. A candidate that makes the plan run short says so.
          </p>
          <p>
            <em>Apply</em> saves that candidate as a rule in your plan and recalculates; remove it
            under <em>Manual Roth conversions</em>. <em>What this comparison does not do</em> lists
            the simplifications, such as bracket room being measured before the year’s withdrawals.
          </p>
        </>
      ),
    },
    {
      id: "suggestions",
      title: "Suggestions",
      body: (
        <>
          <p>
            <em>Find suggestions</em>, above the comparison, runs your projection once as it is and
            once for each change below that fits your plan. Nothing is saved.
          </p>
          <ul>
            <li>
              <strong>Max 401(k)</strong>: a payroll rule filling the remaining deferral limit, for
              each person with wages and a 401(k) whose rules don’t already reach it.
            </li>
            <li>
              <strong>Backdoor Roth</strong>: Backdoor Roth turned on for a Roth IRA rule, or a new
              one added ahead of your last catch-all savings rule, when the first full year’s income
              less payroll deductions reaches the Roth phase-out start. See{" "}
              <HelpLink to="backdoor-roth" />.
            </li>
            <li>
              <strong>Max HSA</strong>: a payroll rule filling the HSA limit, unless coverage for
              the year is marked ineligible.
            </li>
            <li>
              <strong>Roth conversions</strong>: bracket-filling conversions to 12%, 22% and 24% for
              the whole plan, from the largest funded pre-tax account to a Roth account of the same
              person. Only the best of the three is listed.
            </li>
            <li>
              <strong>0% gain harvesting</strong>: a harvesting rule for each taxable brokerage
              account with gains over a known cost basis.
            </li>
          </ul>
          <p>
            End-of-plan net worth counts pre-tax balances after income tax at the heirs’ income tax
            rate in Partner and estate, or 24% when it is zero. A change is listed only when that
            net worth is at least as high and either it rises or lifetime taxes fall, and a plan
            that lasts still lasts. Each row shows the change in lifetime taxes and in end net
            worth, in future dollars, and links to the article on that strategy. Plans with flat tax
            rates get no conversion or harvesting suggestions.
          </p>
        </>
      ),
    },
    {
      id: "health-coverage",
      title: "Health coverage costs",
      body: (
        <>
          <p>
            With health coverage turned on in your plan, this view totals marketplace premiums
            before credits, premium tax credits, and Medicare premiums and surcharges over the plan,
            and counts the years with an income-related surcharge. A table lists each year’s income
            relative to the poverty line, premium, credit, Medicare Part B and D, surcharge and
            total cost. The credit uses that year’s projected income; the Medicare surcharge uses
            income from two years earlier. See <HelpLink to="marketplace-health-coverage" /> and{" "}
            <HelpLink to="medicare-and-irmaa" />.
          </p>
        </>
      ),
    },
  ],
};

export default article;

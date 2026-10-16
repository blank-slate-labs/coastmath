import type { Article } from "../help_types";
import { Callout, DataTable, Figure, HelpLink, KeyFigures, Ledger, UIPath } from "../help_kit";
import { BarChart } from "../help_charts";

const article: Article = {
  intro: (
    <>
      <p>
        Payroll contributions come out of a named earned income before spending, and each one is
        capped at the owner’s remaining legal limit for the year. A request above the limit isn’t
        lost: the excess stays in pay and flows to your surplus rules. Employer money is either a
        fixed percentage of that income or a matching formula on what the employee actually defers,
        and either way it’s trimmed by the combined employee-and-employer limit.
      </p>
      <p>
        Limits are the 2026 figures. Later years scale them with your plan’s inflation assumption.
      </p>
    </>
  ),
  sections: [
    {
      id: "payroll-rules",
      title: "Setting up payroll contributions",
      body: (
        <>
          <p>
            Payroll rules fund a workplace plan, a 401(k), 403(b), 457(b) or 401(a), or an HSA from
            one earned income that belongs to the account’s owner. A 401(a) takes only the employer
            contribution. There are three kinds:
          </p>
          <ul>
            <li>
              <strong>Payroll percent of income:</strong> <em>Employee contribution (%)</em> applied
              to that year’s pay from the source income, and an <em>Employer contribution</em> that
              is either a <em>Fixed percent of pay</em> or a <em>Matching formula</em> (see{" "}
              <a href="#matching-formula">below</a>). For a 401(k), 403(b) or 401(a), pay above the
              IRS compensation limit ($360,000 in 2026) doesn’t count. In a partial first year,
              that’s the pay for the months modeled, and pay earned earlier in the year uses up the
              compensation limit first.
            </li>
            <li>
              <strong>Payroll annual amount / remaining room:</strong> a dollar amount in{" "}
              <em>Annual maximum</em>, prorated in a partial first year, or, if blank, whatever
              legal room is left for the year.
            </li>
            <li>
              <strong>Mega backdoor Roth:</strong> after-tax contributions from W-2 wages, converted
              to a Roth 401(k) at once, up to the employee-plus-employer room left. See{" "}
              <HelpLink to="backdoor-roth" />.
            </li>
          </ul>
          <p>
            Rules run in list order, and one paycheck can’t fund two rules: each rule draws on pay
            the earlier rules left.
          </p>
          <p>
            <em>Contribution limit</em> on a payroll or surplus rule can be set to{" "}
            <em>Lower plan limit</em> for a plan that caps contributions below the IRS limit. The{" "}
            <em>Plan annual limit</em> is in today’s dollars and rises with the IRS limits; it caps
            the year’s contributions to that account, counted the same way as its IRS limit. The IRS
            limit still applies when it’s lower.
          </p>
          <p>
            <em>Max 401(k)</em> (or <em>Max 403(b)</em>, <em>Max 457(b)</em>) adds a remaining-room
            rule for that plan, funded by its owner’s largest earned income.
          </p>
          <Callout kind="where">
            <p>
              <UIPath
                steps={[
                  "Income allocation",
                  "Payroll contributions and account transfers",
                  "Add payroll or transfer rule",
                ]}
              />
              . A 401(k) can’t be a surplus destination; an older surplus rule for one shows{" "}
              <em>Use payroll for this 401(k)</em>.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "matching-formula",
      title: "Matching formulas",
      body: (
        <>
          <p>
            A fixed percent of pay is paid whether or not the employee contributes. A matching
            formula pays only on deferrals. Each tier matches a percentage of what the employee
            defers on the next slice of pay, in order, so “100% of the first 3%, then 50% of the
            next 2%” is two tiers. The match uses the deferral actually deposited, after every
            limit, as a share of the year’s plan pay.
          </p>
          <DataTable
            caption="100% of the first 3% of pay, then 50% of the next 2%, on $100,000 of pay"
            columns={[
              { key: "deferral", label: "Employee deferral" },
              { key: "match", label: "Employer match", format: "usd" },
            ]}
            rows={[
              { deferral: "None", match: 0 },
              { deferral: "2%", match: 2000 },
              { deferral: "4%", match: 3500 },
              { deferral: "6% or more", match: 4000 },
            ]}
          />
          <ul>
            <li>
              <strong>Nonelective contribution (% of pay):</strong> added to the match whether or
              not the employee defers. With the formula above and 3% nonelective, an employee who
              defers nothing still receives $3,000.
            </li>
            <li>
              <strong>Annual employer cap:</strong> limits the year’s match plus nonelective money.
              It’s in today’s dollars, rises with your inflation assumption and is prorated in a
              partial first year.
            </li>
            <li>
              <strong>True up the match at year end:</strong> on by default, the match uses the
              whole year’s deferrals. Turned off, each pay period is matched on its own deferral, so
              when deferrals reach the annual limit early, the rest of the year’s paychecks get no
              match.
            </li>
          </ul>
          <Ledger
            title="Example: $225,000 salary, 15% deferral, 100% match on the first 6%"
            rows={[
              { label: "Deferral requested", value: 33750, detail: "15% × $225,000" },
              {
                op: "→",
                label: "Deposited, limited to the employee limit",
                value: 24500,
                detail: "Reached in September",
              },
              {
                label: "Match with a year-end true-up",
                value: 13500,
                detail: "6% × $225,000: the year’s deferral is 10.9% of pay",
              },
              {
                label: "Match each pay period",
                value: 10125,
                detail: "9 months × 6% of $18,750; none for October–December",
              },
            ]}
          />
          <Callout kind="boundary">
            <p>
              Pay periods are modeled as equal months of the source income’s active months.
              Deferrals run at the elected rate from the first month until the year’s deposited
              amount is used up, and a partial last month is matched on its own deferral. Deferrals
              already made before a mid-year plan start aren’t part of the match.
            </p>
          </Callout>
          <p>
            <strong>Roth employer contributions</strong> puts the employer money in the owner’s Roth
            401(k), 403(b) or 457(b) of the same plan type instead of the rule’s account. Saving the
            rule needs that Roth account to exist for the same person; a 401(a) has none. The money
            is taxed as described below.
          </p>
        </>
      ),
    },
    {
      id: "tax-treatment",
      title: "How contributions are taxed",
      body: (
        <>
          <ul>
            <li>
              <strong>Traditional 401(k), employee:</strong> excluded from taxable wages; payroll
              taxes still apply.
            </li>
            <li>
              <strong>Roth 401(k), employee:</strong> comes out of taxed pay.
            </li>
            <li>
              <strong>Employer, to a Traditional 401(k):</strong> never taxed or counted as cash
              pay.
            </li>
            <li>
              <strong>Employer, to a Roth 401(k):</strong> taxed as income in the year it’s made,
              though it isn’t cash pay and isn’t subject to payroll taxes. The projection warns when
              this happens. This applies both to a rule that funds a Roth 401(k) directly and to a
              matching formula with <em>Roth employer contributions</em> checked: on $100,000 of pay
              in the 22% bracket, a $6,000 Roth match adds $1,320 of federal income tax and no
              payroll tax.
            </li>
          </ul>
          <p>
            HSA payroll contributions follow the rules in <HelpLink to="hsa" />. When the source
            income is self-employment income, the “employer” contribution is paid out of your own
            business profit and, for a 401(k), is limited to 20% of that profit after the deductible
            half of self-employment tax; see <HelpLink to="self-employment-income" />.
          </p>
        </>
      ),
    },
    {
      id: "limits-2026",
      title: "The 2026 limits",
      body: (
        <>
          <KeyFigures
            caption="Per person, 2026"
            items={[
              {
                label: "401(k) employee limit",
                value: 24500,
                detail: "Traditional and Roth combined",
              },
              { label: "Catch-up, age 50 or older", value: 8000 },
              {
                label: "Catch-up, ages 60–63",
                value: 11250,
                detail: "Replaces the age-50 catch-up",
              },
              {
                label: "Employee plus employer",
                value: 72000,
                detail:
                  "Includes after-tax contributions; catch-up not counted; never more than pay",
              },
              { label: "IRA limit", value: 7500, detail: "Traditional and Roth combined" },
              { label: "IRA catch-up, age 50 or older", value: 1100 },
              { label: "Roth catch-up wage threshold", value: 150000, detail: "Prior-year wages" },
            ]}
          />
          <Figure
            title="401(k) employee limit by age, 2026"
            caption="Age is the age reached during the calendar year."
            table={{
              columns: [
                { key: "age", label: "Age" },
                { key: "base", label: "Employee limit", format: "usd" },
                { key: "catch", label: "Catch-up", format: "usd" },
                { key: "total", label: "Total", format: "usd" },
              ],
              rows: [
                { age: "Under 50", base: 24500, catch: 0, total: 24500 },
                { age: "50–59", base: 24500, catch: 8000, total: 32500 },
                { age: "60–63", base: 24500, catch: 11250, total: 35750 },
                { age: "64 and older", base: 24500, catch: 8000, total: 32500 },
              ],
            }}
          >
            <BarChart
              label="401(k) employee limit and catch-up by age band, 2026"
              categories={["Under 50", "50–59", "60–63", "64+"]}
              series={[
                {
                  id: "base",
                  label: "Employee limit",
                  color: "cyan",
                  values: [24500, 24500, 24500, 24500],
                },
                { id: "catch", label: "Catch-up", color: "gray", values: [0, 8000, 11250, 8000] },
              ]}
            />
          </Figure>
          <DataTable
            caption="Roth IRA income phase-out, 2026 modified AGI"
            columns={[
              { key: "status", label: "Filing status" },
              { key: "from", label: "Phase-out starts", format: "usd" },
              { key: "to", label: "No contribution at", format: "usd" },
            ]}
            rows={[
              { status: "Single, head of household", from: 153000, to: 168000 },
              {
                status: "Married filing jointly, qualifying surviving spouse",
                from: 242000,
                to: 252000,
              },
              { status: "Married filing separately", from: 0, to: 10000 },
            ]}
            note="Inside the range the Roth IRA limit falls proportionally, rounded up to the next $10, with a $200 minimum."
          />
          <p>
            A traditional IRA contribution is deductible in full unless the owner or their spouse is
            covered by a workplace plan. CoastMath counts someone as covered in any year their
            401(k), 403(b) or 401(a) receives an employee or employer contribution; a 457(b) doesn’t
            count. A covered household’s deduction then phases out over the ranges below, measured
            on modified AGI figured before the IRA deduction, so Roth conversions count. The full
            contribution is still deposited, and only the deductible part lowers taxable income.
          </p>
          <DataTable
            caption="Traditional IRA deduction phase-out, 2026 modified AGI"
            columns={[
              { key: "who", label: "Who is covered" },
              { key: "from", label: "Phase-out starts", format: "usd" },
              { key: "to", label: "No deduction at", format: "usd" },
            ]}
            rows={[
              { who: "Single or head of household, covered", from: 81000, to: 91000 },
              { who: "Married filing jointly, contributor covered", from: 129000, to: 149000 },
              { who: "Married filing jointly, only the spouse covered", from: 242000, to: 252000 },
              { who: "Married filing separately, either spouse covered", from: 0, to: 10000 },
            ]}
            note="Inside the range the deductible amount falls proportionally, rounded up to the next $10, with a $200 minimum. Spouses filing separately who lived apart all year use the single range. The nondeductible part isn’t tracked as basis, so it’s taxed again when withdrawn or converted."
          />
          <p>
            IRA contributions also can’t exceed the owner’s earned income for the year; on a joint
            return the couple’s combined earnings count. HSA limits are in <HelpLink to="hsa" />,
            and Roth IRAs funded through a converted nondeductible contribution are in{" "}
            <HelpLink to="backdoor-roth" />.
          </p>
        </>
      ),
    },
    {
      id: "how-limits-are-enforced",
      title: "How limits are enforced",
      body: (
        <>
          <ul>
            <li>
              <strong>Shared per owner.</strong> All of one person’s 401(k)s and 403(b)s share one
              employee limit, and all their IRAs share one IRA limit, across every rule that funds
              them. A 457(b) has its own employee limit and catch-ups, and employer money paid into
              it counts toward that limit, though not toward its catch-up.
            </li>
            <li>
              <strong>Earlier this year counts.</strong> Contributions you enter as already made
              this tax year use up room without adding to the opening balance.
            </li>
            <li>
              <strong>Employee money first.</strong> Employer money is cut only to keep employee
              (without catch-up) plus employer within the combined limit, and within pay. A 25%
              employer rate on $200,000 of pay requests $50,000; with $24,500 of employee deferrals,
              $47,500 is deposited.
            </li>
            <li>
              <strong>Where the excess goes.</strong> The part of an employee request above the
              limit stays in pay and joins the year’s surplus. Employer money above the limit isn’t
              deposited anywhere.
            </li>
          </ul>
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "Earlier this tax year"]} /> takes employee and
              employer contributions already made to each account.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "roth-catch-up",
      title: "Catch-up contributions for higher earners",
      body: (
        <>
          <p>
            From 2026, someone whose prior-year wages exceeded $150,000 can make catch-up
            contributions only to a Roth 401(k). CoastMath checks the owner’s projected wages from
            the previous plan year against the threshold, indexed by plan inflation. In the plan’s
            first year it has no prior-year wages, so it uses that year’s projected wages. A plan
            that starts mid-year annualizes its first year’s projected wages. For the second year’s
            test, year-to-date wages you enter replace the annualized months before the start.
          </p>
          <Ledger
            title="Example: first plan year, age 61, $200,000 salary, plan starting January 1, 2026"
            rows={[
              { label: "Rule 1: Traditional 401(k), 15% of salary", value: 30000 },
              {
                op: "→",
                label: "Deposited, limited to the regular employee limit",
                value: 24500,
                detail: "Catch-up can go only to a Roth 401(k) this year",
              },
              {
                label: "Rule 2: Roth 401(k), remaining room",
                value: 11250,
                detail: "$35,750 limit at 61, less $24,500 already deferred",
              },
              {
                label: "Employer contribution, 5% of salary",
                value: 10000,
                detail: "Deposited in the Traditional 401(k)",
              },
              { op: "=", label: "Employee contributions for the year", value: 35750 },
            ]}
          />
          <p>
            Without the Roth rule, the $5,500 left of the first request stays in pay. For someone
            earning $120,000 with a 30% request, the first year likewise stops at $24,500; from the
            second year, prior-year wages are under the threshold and the full $35,750 goes to the
            traditional account.
          </p>
          <Callout kind="boundary">
            <p>
              The wage test uses projected wages from all of the owner’s income streams, not only
              the employer that sponsors the plan, and actual wage history before the plan start
              isn’t used. Changing employers mid-career isn’t modeled.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "later-years",
      title: "Limits in later years",
      body: (
        <>
          <p>
            After 2026, every dollar limit above, the phase-out starting points and the Roth
            catch-up wage threshold grow with your plan’s inflation assumption each year. The
            phase-out ranges keep their 2026 widths, and the married-filing-separately range isn’t
            indexed.
          </p>
          <Callout kind="boundary">
            <p>
              Future limits are estimates. The IRS rounds each year’s increase down to set
              increments; CoastMath doesn’t round, so projected limits can run slightly ahead of the
              published ones.
            </p>
          </Callout>
          <Callout kind="boundary">
            <p>
              Vesting, forfeitures and nondiscrimination limits aren’t modeled. Use{" "}
              <em>Lower plan limit</em> for a plan’s own contribution cap and a matching formula for
              its match.
            </p>
          </Callout>
        </>
      ),
    },
  ],
};
export default article;

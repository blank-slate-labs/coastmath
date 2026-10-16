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
  hostedPart,
} from "../help_kit";
import { LineChart } from "../help_charts";

/* Engine output for a $120,000 salary entered in 2026, recipient born July 1976, 3% inflation,
   no wage-growth assumption, ending at an age-55 milestone. See the sources record. */
const blankGrowth: [number, number][] = [
  [2026, 120000],
  [2027, 123600],
  [2028, 127308],
  [2029, 131127.24],
  [2030, 135061.06],
  [2031, 69556.44],
  [2032, 0],
  [2033, 0],
];
const zeroGrowth: [number, number][] = [
  [2026, 120000],
  [2027, 120000],
  [2028, 120000],
  [2029, 120000],
  [2030, 120000],
  [2031, 60000],
  [2032, 0],
  [2033, 0],
];

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath reads each income as an annual amount in plan-start-year dollars. Every January
        after the first plan year it applies that income’s growth rate, then pays the share of the
        year the income is active. Pay marked as earned income is taxed as wages: it’s ordinary
        income, and it’s subject to Social Security and Medicare tax.
      </p>
      <p>
        Three settings decide most results: the growth rate (blank, zero or a number mean different
        things), the start and end milestones, and whether the income is earned.
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
            Each income stream takes a name, an amount with a frequency, a recipient (you or your
            partner) and optional timing. <strong>Amount frequency</strong> can be weekly, biweekly
            (every two weeks), semimonthly (twice a month), monthly, quarterly or annual. CoastMath
            multiplies the amount by 52, 26, 24, 12, 4 or 1 and calculates with that annual amount.
            The frequency is saved with the income: the form reopens in it and the income list shows
            the amount in it, such as $2.5K/mo. Switching the frequency only changes how the amount
            is shown, to the cent; the annual amount changes only when you edit the amount.
          </p>
          <p>
            Choose <strong>Hourly (rate × hours)</strong> to enter an{" "}
            <strong>Hourly rate ($)</strong> and <strong>Hours per week</strong> instead. The annual
            amount is the rate × the weekly hours × 52 paid weeks, to the cent, and the income keeps
            its rate and hours: the form reopens in them and the list shows them, such as $25.50/hr
            × 30 hrs/wk. Switching to another frequency keeps the annual amount.
          </p>
          <Callout kind="entry">
            <p>
              Enter gross pay, before any paycheck deductions, in today’s dollars. Health premiums
              and other paycheck deductions go in as expenses marked as payroll deductions, and
              401(k) contributions go in as payroll rules. Entering take-home pay instead would
              count those deductions twice.
            </p>
          </Callout>
          <p>
            The <strong>Salary</strong> income type is earned income, for wages and for business
            profit. Checking
            <strong> Self-employed</strong> under <UIPath steps={["Growth and tax settings"]} />{" "}
            switches the income to self-employment tax. That treatment is explained in{" "}
            <HelpLink to="self-employment-income" />. The <strong>Other</strong> type asks for a tax
            category instead; those categories are covered in{" "}
            <HelpLink to="pensions-and-other-income" />.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Income streams", "Add income"]} />. Growth, withholding and the tax
              checkboxes are under <UIPath steps={["Growth and tax settings"]} /> in the same form.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-pay-grows",
      title: "How pay grows",
      body: (
        <>
          <Formula result="Pay this year">
            <V>Amount entered</V>
            <Op>×</Op>
            <V>Growth factor</V>
            <Op>×</Op>
            <V>Share of the year active</V>
          </Formula>
          <p>
            The growth factor is 1 in the first plan year. Each January after that, it’s multiplied
            by one plus that year’s rate. The factor steps by a full year’s rate even when the first
            plan year was partial.
          </p>
          <ul>
            <li>
              <strong>Blank Growth rate.</strong> Pay follows the plan’s wage-growth assumption at
              the recipient’s age. Without one, it follows each year’s inflation assumption, so the
              amount stays level in today’s dollars.
            </li>
            <li>
              <strong>0.</strong> The amount is fixed in nominal dollars and loses purchasing power
              with inflation.
            </li>
            <li>
              <strong>Any other rate.</strong> The rate compounds every year, regardless of
              inflation.
            </li>
          </ul>
          <p>
            A <strong>Growth cap</strong> stops growth at a dollar amount per year. With{" "}
            <strong>Cap rises with inflation</strong> checked, the cap is in today’s dollars and
            indexed with plan inflation.
          </p>
          <Figure
            title="A $120,000 salary with a blank and a zero growth rate"
            caption="3% inflation, no wage-growth assumption. The recipient was born in July, and a retirement milestone at 55 ends pay after June 2031."
            table={{
              columns: [
                { key: "year", label: "Year", format: "year" },
                { key: "blank", label: "Blank growth rate", format: "usd" },
                { key: "zero", label: "Growth rate 0", format: "usd" },
              ],
              rows: blankGrowth.map(([year, blank], i) => ({
                year,
                blank,
                zero: zeroGrowth[i][1],
              })),
            }}
          >
            <LineChart
              step
              label="Salary by year with a blank growth rate and with a growth rate of zero"
              series={[
                { id: "blank", label: "Blank growth rate", color: "blue", points: blankGrowth },
                { id: "zero", label: "Growth rate 0", color: "gray", points: zeroGrowth },
              ]}
              markers={[{ x: 2031, label: "Retire at 55" }]}
            />
          </Figure>
          <p>
            Growth compounds from the plan’s start year, even for a job that begins later. That
            keeps a future salary entered in today’s dollars worth the same in real terms when it
            starts.
          </p>
          <Ledger
            title="Example: a job that starts four years in"
            rows={[
              { label: "Amount entered, today’s dollars", value: 80000 },
              {
                op: "×",
                label: "Growth factor for 2030",
                value: 1.12550881,
                format: "num",
                digits: 4,
                detail: "3% inflation for 2026 through 2029",
              },
              { op: "=", label: "Pay in 2030", value: 90040.7, format: "usd_cents" },
            ]}
          />
          <Callout kind="where">
            <p>
              Set the rate in <UIPath steps={["Assumptions", "Wage growth"]} />
              {hostedPart("wages-and-raises.iphone", "")}. It applies to every earned income with a
              blank Growth rate.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "growth-schedules",
      title: "Growth schedules",
      body: (
        <>
          <p>
            A growth schedule replaces the yearly growth step in the calendar years you choose. Each
            segment has a start year, an optional end year and one kind of change. Years no segment
            covers keep the Growth rate (or, when it’s blank, wage growth). Segments must be in year
            order and can’t overlap, so every segment except the last needs an end year.
          </p>
          <DataTable
            caption="Kinds of change"
            columns={[
              { key: "kind", label: "Change type" },
              { key: "effect", label: "Each covered year" },
            ]}
            rows={[
              { kind: "Percent per year", effect: "The amount changes by that percent." },
              {
                kind: "Inflation plus or minus",
                effect:
                  "The amount changes by the prior year’s inflation plus or minus the points you enter. In a Monte Carlo trial, that trial’s inflation is used.",
              },
              {
                kind: "Dollar change per year",
                effect:
                  "The amount changes by a fixed dollar amount, in today’s or nominal dollars.",
              },
              {
                kind: "Set amount",
                effect:
                  "The amount is the value you enter, in today’s or nominal dollars. Growth after the segment continues from it.",
              },
            ]}
          />
          <Ledger
            title="Example: a $100,000 salary with a three-segment schedule"
            note="3% inflation, blank Growth rate. Segments: 3% a year in 2027–2028, set to $120,000 nominal in 2029, then inflation minus 1 point from 2030."
            rows={[
              { label: "2026, first plan year", value: 100000 },
              { op: "→", label: "2027, +3%", value: 103000 },
              { op: "→", label: "2028, +3%", value: 106090 },
              { op: "→", label: "2029, set amount", value: 120000 },
              { op: "→", label: "2030, inflation 3% − 1 point", value: 122400 },
              { op: "=", label: "2031, inflation 3% − 1 point", value: 124848 },
            ]}
          />
          <Callout kind="entry">
            <p>
              A segment that covers the first plan year changes it only when it sets the amount;
              growth begins the next January. A percent or dollar change never takes the amount
              below zero. The Growth cap still applies to the scheduled amount, and contributions,
              employer match, salary-based pensions and Social Security covered earnings all use it.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              Add segments under{" "}
              <UIPath steps={["Growth and tax settings", "Growth schedule (optional)"]} /> in the
              income form. Social Security benefits and formula pensions don’t take a schedule.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "when-pay-starts-and-stops",
      title: "When pay starts and stops",
      body: (
        <>
          <p>
            With no milestones, an income runs from the plan start through the end of the plan. A
            <strong> Start milestone</strong> or <strong>End milestone</strong> limits it to the
            years between them. In the form, both open from the one-line timing summary, with months
            under <strong>Start and end months</strong>. In the year a milestone is reached,
            CoastMath pays whole months:
          </p>
          <ul>
            <li>
              Pay starts in the <strong>Start month</strong> you pick, or in the month the milestone
              is reached.
            </li>
            <li>
              Pay runs through the <strong>End month</strong> you pick, or through the month before
              the milestone is reached.
            </li>
            <li>
              An age milestone is reached in the plan owner’s birth month (later for a fractional
              age), a date milestone in its own month, and a relative milestone in the month of the
              milestone it follows. Milestones based on net worth or savings are reached in January.
            </li>
          </ul>
          <Ledger
            title="Example: the retirement year in the chart above"
            rows={[
              { label: "Amount entered", value: 120000 },
              {
                op: "×",
                label: "Growth factor for 2031",
                value: 1.15927407,
                format: "num",
                digits: 4,
                detail: "five years at 3%",
              },
              { op: "=", label: "Full-year pay", value: 139112.89, format: "usd_cents" },
              {
                op: "×",
                label: "Months paid ÷ 12",
                value: 0.5,
                format: "num",
                digits: 2,
                detail: "January through June; the age milestone falls in July",
              },
              { op: "=", label: "Pay in 2031", value: 69556.44, format: "usd_cents" },
            ]}
          />
          <p>
            A one-time payment such as a signing bonus works the same way: use one milestone as both
            the start and the end, and set <strong>Start month</strong> and{" "}
            <strong>End month</strong> to the same month. The amount is still annual, so one month
            pays one-twelfth of it. A $120,000 amount set to March of 2027 pays $10,000. A recurring
            bonus can be part of the salary or its own income with the same milestones; both are
            taxed as wages.
          </p>
          <p>
            In a first plan year that starts partway through the year, only the remaining months
            count. See
            <> </>
            <HelpLink to="first-plan-year" />. Income also stops when its recipient dies, as
            described in <HelpLink to="death-of-a-partner" />.
          </p>
          <Callout kind="entry">
            <p>
              Months only apply to the year a milestone is reached. Without a milestone,{" "}
              <strong>Start month</strong> and
              <strong> End month</strong> do nothing, and they never create a seasonal pattern that
              repeats every year.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-wages-are-taxed",
      title: "How wages are taxed",
      body: (
        <>
          <p>
            Wages are ordinary income for federal, state and local income tax. Employee Social
            Security and Medicare tax are figured for each person separately, with that person’s
            wages applied against the Social Security wage base;{" "}
            <HelpLink to="payroll-and-other-federal-taxes" /> gives the rates. Most pre-tax paycheck
            deductions lower wages for income tax but not for Social Security and Medicare tax, as
            explained in <HelpLink to="payroll-deductions" />.
          </p>
          <p>
            <strong>Tax withholding (% of gross)</strong> sets aside that share of the pay during
            the year and credits it against the year’s actual tax. Leaving it blank settles the
            whole liability at tax time. For how the difference becomes a refund or a balance due,
            see <HelpLink to="tax-payments-and-settlement" />.
          </p>
          <p>
            Earned income is also the compensation that limits IRA and 401(k) contributions. Each
            person’s contributions are limited to that person’s wages and business profit for the
            year. On a joint return, IRA contributions can use the couple’s combined earnings. See
            <> </>
            <HelpLink to="contributions-and-employer-match" />.
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
                Pay schedules within a year. Each year’s pay is one annual amount, prorated by whole
                months only in milestone years.
              </li>
              <li>
                The Social Security earnings test. Wages earned while claiming benefits early don’t
                reduce or delay the benefit in the projection.
              </li>
              <li>
                Stock compensation, commissions and variable pay as separate kinds of income. Enter
                them as wages with the timing and growth you expect.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
    {
      id: "common-surprises",
      title: "Common surprises",
      body: (
        <>
          <Symptoms
            rows={[
              {
                symptom: "Salary rises every year though you left growth blank.",
                check: "A blank rate follows wage growth, or inflation when none is set.",
                next: <>Enter 0 for a fixed nominal salary, or a specific rate.</>,
              },
              {
                symptom: "A future job pays more in its first year than the amount you entered.",
                check: "Growth compounds from the plan’s start year.",
                next: "Enter the amount in today’s dollars, or set growth to 0 and enter the nominal amount.",
              },
              {
                symptom: "Pay in the retirement year is less than you expected.",
                check:
                  "An age milestone pays through the month before the plan owner’s birth month.",
                next: (
                  <>
                    Set <strong>End month</strong> to the last month you’ll be paid.
                  </>
                ),
              },
              {
                symptom: "Start or end months have no effect.",
                check: "Months need a start or end milestone.",
                next: "Add the milestone, or use a date milestone for a calendar month.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

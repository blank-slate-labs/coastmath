import type { Article } from "../help_types";
import {
  Callout,
  DataTable,
  Figure,
  Formula,
  HelpLink,
  KeyFigures,
  Ledger,
  Op,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";
import { LineChart } from "../help_charts";

/* Taxable benefits for a single filer with $30,000 of benefits, by other income. Each point is the
   engine's result; 19,000 and 43,706 are the two kinks. See the sources record. */
const taxablePoints: [number, number][] = [
  [0, 0],
  [5000, 0],
  [10000, 0],
  [15000, 2500],
  [19000, 4500],
  [20000, 5350],
  [25000, 9600],
  [30000, 13850],
  [35000, 18100],
  [40000, 22350],
  [43706, 25500],
  [50000, 25500],
  [60000, 25500],
  [70000, 25500],
];
const capPoints: [number, number][] = taxablePoints.map(([x]) => [x, 25500]);

const claimRows = [
  { age: "62", months: "60 early", share: 0.7, annual: 16800 },
  { age: "63", months: "48 early", share: 0.75, annual: 18000 },
  { age: "64", months: "36 early", share: 0.8, annual: 19200 },
  { age: "65", months: "24 early", share: 0.866667, annual: 20800 },
  { age: "66", months: "12 early", share: 0.933333, annual: 22400 },
  { age: "67", months: "At full retirement age", share: 1, annual: 24000 },
  { age: "68", months: "12 late", share: 1.08, annual: 25920 },
  { age: "69", months: "24 late", share: 1.16, annual: 27840 },
  { age: "70", months: "36 late", share: 1.24, annual: 29760 },
];

const article: Article = {
  intro: (
    <>
      <p>
        A Social Security stream is sized one of two ways. With <strong>Benefit amount</strong>,
        CoastMath pays the annual amount you enter, starting in the year its owner reaches the
        claiming age you choose; the claiming-age adjustment is applied only when you use the
        built-in estimate. With <strong>PIA</strong>, you enter your monthly benefit at full
        retirement age and CoastMath applies the reduction or delayed credits for the claim date
        itself, adds spousal benefits when both partners use PIA, and can compute survivor benefits.
        Either way the benefit is in today’s dollars and rises every January with the plan’s
        inflation assumption, as a stand-in for the cost-of-living adjustment.
      </p>
      <p>
        Each year, the federal tax calculation decides how much of the year’s benefits is taxable,
        from 0% up to 85%, using the combined-income test for your filing status.
      </p>
    </>
  ),
  sections: [
    {
      id: "working-and-benefits",
      title: "Working while collecting benefits",
      body: (
        <>
          <p>
            Before full retirement age, earnings above the annual exempt amount reduce benefits. In
            the year you reach full retirement age, only earnings before that month count, with the
            higher exempt amount. Fully withheld months increase your retirement benefit from full
            retirement age. For PIA-based survivor benefits, those months also adjust the survivor’s
            age reduction at survivor full retirement age; the reduced-worker limit still applies.
            Any increase in your own benefit reduces the survivor top-up in the same month.
          </p>
          <p>
            CoastMath allocates a worker’s withholding proportionally across their own benefit and
            spousal payments on their record. In the first claiming year, benefits after employment
            ends are protected as an approximation of the monthly grace rule. Self-employment
            services are not measured.
          </p>
          <p>
            With PIA basis, choose “Current record” under “My PIA reflects…” to estimate increases
            from future covered wages and self-employment earnings. Enter covered years to date.
            CoastMath infers equal historical earnings years and zeros for the rest of 35, then
            replaces low years with higher projected years. Increases take effect the following
            January and flow through spousal and survivor benefits. “Assumes I keep working” keeps
            the entered PIA unchanged.
          </p>
        </>
      ),
    },
    {
      id: "what-you-enter",
      title: "What you enter",
      body: (
        <>
          <p>
            Add one income stream per person with the <strong>Social Security</strong> income type.
            The fields that matter:
          </p>
          <ul>
            <li>
              <strong>Benefit basis</strong>: <strong>Benefit amount</strong> or{" "}
              <strong>PIA</strong>. See <a href="#pia-basis">Benefits sized from your PIA</a> for
              the second.
            </li>
            <li>
              <strong>Annual amount</strong>, with Benefit amount basis (or a monthly or other
              amount, chosen with <strong>Amount frequency</strong>): the benefit you expect at your
              claiming age, in today’s dollars. This is the amount CoastMath pays. It already
              includes any early-claiming reduction or delayed credits.
            </li>
            <li>
              <strong>Income recipient</strong> (plans with a partner):{" "}
              <strong>Primary person</strong> or <strong>Partner</strong>. The claiming age follows
              that person’s birth year and month.
            </li>
            <li>
              <strong>Claiming age</strong>: 62 through 70. Benefits start in the year the recipient
              turns that age. Leave it blank to start at plan start, or pick a{" "}
              <strong>Start milestone</strong> to override it.
            </li>
            <li>
              <strong>Growth rate</strong>, under <strong>Growth and tax settings</strong>: leave it
              blank to follow the plan’s Social Security COLA assumption, or inflation without one.
            </li>
          </ul>
          <Callout kind="entry">
            <p>
              With Benefit amount basis, enter the claimed benefit, not your full-retirement-age
              amount, unless you plan to claim at full retirement age. If you type a
              full-retirement-age figure and choose 62, CoastMath still pays the full figure from
              62. To have the reduction applied for you, use PIA basis or the estimate below.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              <UIPath steps={["Income streams", "Add income", "Social Security"]} />, then{" "}
              <strong>Claiming age</strong> and <strong>Estimate method</strong>.
            </p>
          </Callout>
          <h3>The built-in estimate</h3>
          <p>
            With Benefit amount basis, the estimate fills in the amount for you.{" "}
            <strong>From monthly PIA</strong> takes your primary insurance amount (your monthly
            benefit at full retirement age, from your Social Security record) and fills{" "}
            <strong>Annual amount</strong> with the claimed annual benefit. Saving keeps only that
            annual amount; changing the claiming age later doesn’t re-run the estimate.
          </p>
          <Formula result="Annual amount">
            <V>Monthly PIA</V>
            <Op>×</Op>
            <V>12</V>
            <Op>×</Op>
            <V>Claiming factor</V>
            <Op>×</Op>
            <V>Expected benefit %</V>
          </Formula>
          <Ledger
            title="Example: $2,000 PIA, born 1962, claiming at 64"
            rows={[
              { label: "Monthly PIA at full retirement age", value: 2000 },
              { op: "×", label: "Months", value: 12, format: "num" },
              {
                op: "×",
                label: "Claiming factor at 64",
                value: 0.8,
                format: "pct",
                detail: "36 months before full retirement age of 67",
              },
              {
                op: "×",
                label: "Expected benefit",
                value: 0.9,
                format: "pct",
                detail: "Your own planning assumption",
              },
              { op: "=", label: "Annual amount saved to the stream", value: 17280 },
            ]}
          />
          <p>
            The claiming factor follows the statutory schedule: a reduction of five-ninths of 1% for
            each of the first 36 months before full retirement age and five-twelfths of 1% for each
            earlier month, and a credit of two-thirds of 1% for each month you wait past full
            retirement age, up to 70. Full retirement age is 66 for people born 1943–1954, rises by
            two months per birth year from 1955, and is 67 for people born in 1960 or later.
          </p>
          <DataTable
            caption="Claiming factor and annual benefit on a $2,000 PIA, full retirement age 67"
            columns={[
              { key: "age", label: "Claiming age" },
              { key: "months", label: "Months from full retirement age" },
              { key: "share", label: "Share of PIA", format: "pct", digits: 1 },
              { key: "annual", label: "Annual amount", format: "usd" },
            ]}
            rows={claimRows}
          />
          <p>
            <strong>From current annual income</strong> is a rough sketch for when you don’t have
            your record: it applies fixed replacement rates to one year’s income, capped at the
            $184,500 taxable maximum, adjusts for claiming age and caps the result at the maximum
            benefit ($4,152 a month at full retirement age in 2026). It doesn’t read your earnings
            history.
          </p>
          <p>
            <strong>Expected benefit (%)</strong> is a planning haircut applied after the claiming
            factor, for example 80% if you want to plan for reduced benefits. It isn’t a statutory
            calculation.
          </p>
        </>
      ),
    },
    {
      id: "pia-basis",
      title: "Benefits sized from your PIA",
      body: (
        <>
          <p>
            With <strong>Benefit basis</strong> set to <strong>PIA</strong>, enter{" "}
            <strong>PIA per month at full retirement age ($)</strong> from your Social Security
            record, in today’s dollars, and <strong>Expected benefit paid (%)</strong>. A claiming
            age is required. The projection computes the benefit from these every time it runs, so
            changing the claiming age changes the benefit as well as the start date. The form shows
            the first-year benefit at the claiming age as a preview.
          </p>
          <Formula result="Own benefit, in today’s dollars">
            <V>Monthly PIA</V>
            <Op>×</Op>
            <V>12</V>
            <Op>×</Op>
            <V>Claiming factor for the first payment month</V>
            <Op>×</Op>
            <V>Expected benefit %</V>
          </Formula>
          <Ledger
            title="Example: $2,000 PIA, born January 1966, claiming at 70, 90% expected"
            rows={[
              { label: "Monthly PIA at full retirement age", value: 2000 },
              { op: "×", label: "Months", value: 12, format: "num" },
              {
                op: "×",
                label: "Claiming factor at 70",
                value: 1.24,
                format: "pct",
                detail: "36 months of delayed credits past 67",
              },
              { op: "×", label: "Expected benefit", value: 0.9, format: "pct" },
              {
                op: "=",
                label: "Paid in 2036, the first full year",
                value: 26784,
                detail: "With 0% inflation",
              },
            ]}
          />
          <p>
            The claiming factor uses the month payments actually start: the claiming age in the
            recipient’s birth month, or a <strong>Start month</strong> or{" "}
            <strong>Start milestone</strong> you set instead. A start milestone must fall on a fixed
            age or date. The benefit then grows from plan start like any Social Security stream; see{" "}
            <a href="#claiming-and-cola">When payments start and how they grow</a>.
          </p>
          <h3>Spousal benefits</h3>
          <p>
            When both partners have one active PIA-basis stream, a partner whose PIA is less than
            half of the other’s also receives the difference as a spousal benefit, listed as a
            separate income line named after their stream with “(spousal)”.
          </p>
          <ul>
            <li>
              It starts when both partners have claimed. Claiming your own benefit also files for
              the spousal benefit, but it can’t begin before the other partner claims.
            </li>
            <li>
              If it starts before your full retirement age, it’s reduced by twenty-five
              thirty-sixths of 1% for each of the first 36 months early and five-twelfths of 1% for
              each earlier month. Waiting past full retirement age adds no credits to it.
            </li>
            <li>
              Your expected benefit percentage applies to it, and it stops when the other partner
              dies.
            </li>
          </ul>
          <Ledger
            title="Example: PIAs of $3,000 and $1,000, both born 1966, both claiming at 64"
            rows={[
              { label: "Half of the higher PIA", value: 1500 },
              { op: "−", label: "Lower earner’s own PIA", value: 1000 },
              { op: "=", label: "Monthly spousal amount at full retirement age", value: 500 },
              { op: "×", label: "Spousal factor, 36 months early", value: 0.75, format: "pct" },
              { op: "×", label: "Months", value: 12, format: "num" },
              { op: "=", label: "Spousal benefit for the year", value: 4500 },
              { op: "+", label: "Own benefit: $1,000 × 12 × 80%", value: 9600 },
              { op: "=", label: "Lower earner’s Social Security in 2030", value: 14100 },
            ]}
          />
          <p>
            Survivor benefits for a PIA-basis couple are calculated from both PIAs when the survivor
            option is on; see <HelpLink to="survivor-social-security#pia-basis" />.
          </p>
          <Callout kind="where">
            <p>
              <UIPath
                steps={["Income streams", "Add income", "Social Security", "Benefit basis"]}
              />
              . Set it on both partners’ streams for spousal and PIA-based survivor benefits.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "claiming-and-cola",
      title: "When payments start and how they grow",
      body: (
        <>
          <p>
            A claiming age starts payments in the recipient’s birth month of the year they reach
            that age; with no birth month on file, in January. Set birth months in{" "}
            <UIPath steps={["Plan details", "Birth month"]} /> and{" "}
            <UIPath steps={["Partner and estate", "Partner birth month"]} />. A{" "}
            <strong>Start month</strong> on the stream overrides the birth month. If the claiming
            age is already behind you when the plan starts, the benefit is paid from the plan’s
            start.
          </p>
          <p>
            The amount you enter is in plan-start-year dollars. Each January after the first plan
            year, it grows by one year of the plan’s Social Security COLA assumption, or of its
            inflation assumption when no COLA is set. A <strong>Growth rate</strong> on the stream
            replaces that with a fixed rate; enter 0 for a benefit fixed in nominal dollars.
          </p>
          <p>
            Growth compounds from the plan’s start, including the years before you claim, so a
            benefit estimate stated in today’s dollars is carried forward to the dollars of the year
            it is paid.
          </p>
          <Ledger
            title="Example: a partner’s $24,000 benefit in today’s dollars, partner born March 1964, claiming at 67, 2.5% inflation"
            rows={[
              { label: "Annual amount entered (2026 dollars)", value: 24000 },
              {
                op: "×",
                label: "Five January increases, 2027–2031",
                value: 1.131408,
                format: "num",
                digits: 6,
                detail: "1.025 to the fifth power",
              },
              { op: "=", label: "Full-year rate in 2031", value: 27153.8, format: "usd_cents" },
              { op: "×", label: "March through December", value: "10 of 12 months" },
              { op: "=", label: "Paid in 2031", value: 22628.16, format: "usd_cents" },
              {
                op: "→",
                label: "Paid in 2032, after one more increase",
                value: 27832.64,
                format: "usd_cents",
              },
            ]}
          />
          <Callout kind="where">
            <p>
              <UIPath steps={["Assumptions", "Inflation"]} /> sets the plan-wide rate; each stream’s{" "}
              <UIPath steps={["Growth and tax settings", "Growth rate"]} /> overrides it. See{" "}
              <HelpLink to="todays-and-future-dollars" /> for how the projection shows nominal and
              today’s-dollar values.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "compare-claiming-ages",
      title: "Compare claiming ages",
      body: (
        <>
          <p>
            The <strong>Social Security</strong> view reruns the whole plan with each person’s own
            benefit claimed at every whole age from 62 to 70, in their birth month. With two
            partners whose ages can change, it runs every pair, up to 81 projections, plus the plan
            as saved. Everything else stays as you entered it: other income, spending, accounts,
            returns, inflation and tax settings. Taxes, withdrawals, the earnings test and spousal,
            survivor and former-spouse benefits are recalculated in each run.
          </p>
          <p>
            Runs are ranked by end net worth after tax: pre-tax balances left at the end are reduced
            by the heir income tax rate in your estate settings, or 24% when none is set. Runs in
            which the plan succeeds rank ahead of runs in which it fails. Lifetime Social Security
            is the household’s total received, after the earnings test; the cumulative chart shows
            where a later claim catches up with an earlier one.
          </p>
          <p>
            With <strong>Benefit amount</strong>, the amount you entered is taken as the benefit at
            the planned claiming age and rescaled by the change in the claiming factor. With{" "}
            <strong>PIA</strong>, CoastMath sizes each benefit from the new claim date, so spousal
            and survivor amounts follow both ages.
          </p>
          <Ledger
            title="Example: $24,000 entered at 67, born 1960 or later"
            rows={[
              { label: "Annual amount entered, claiming at 67", value: 24000 },
              {
                op: "×",
                label: "Claiming factor at 70 ÷ factor at 67",
                value: 1.24,
                format: "num",
                digits: 2,
              },
              { op: "=", label: "Annual amount at 70", value: 29760 },
              { op: "→", label: "At 62: × 0.70", value: 16800 },
            ]}
          />
          <p>
            A person’s age isn’t varied when their benefit has already started, when they have more
            than one Social Security stream, when the stream starts at a milestone without a fixed
            date (a net worth or condition milestone), or when no age from 62 to 70 is still ahead.
          </p>
          <Callout kind="consequence">
            <p>
              <strong>Use these ages</strong> sets the stream’s claiming age and clears its start
              milestone and Start month; with Benefit amount it also saves the rescaled amount.
            </p>
          </Callout>
          <Callout kind="boundary">
            <p>
              Claim months other than the birth month, ages after 70 and Monte Carlo runs for each
              age aren’t compared.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "taxable-benefits",
      title: "How much of each benefit is taxed",
      body: (
        <>
          <p>
            Every year, CoastMath runs the federal combined-income test on the household’s total
            benefits. Combined income is all other income in adjusted gross income, including
            capital gains, dividends, withdrawals and Roth conversions, plus half of the year’s
            benefits. Up to a lower threshold nothing is taxable; between the thresholds up to 50%
            is; above the upper threshold up to 85% is.
          </p>
          <KeyFigures
            caption="Combined-income thresholds (fixed in law, not indexed for inflation)"
            items={[
              { label: "Single, head of household", value: "$25,000 / $34,000" },
              { label: "Married filing jointly", value: "$32,000 / $44,000" },
              {
                label: "Married filing separately, lived together",
                value: "$0",
                detail: "Up to 85% taxable from the first dollar",
              },
              {
                label: "Married filing separately, lived apart all year",
                value: "$25,000 / $34,000",
              },
            ]}
          />
          <Formula
            result="Taxable benefits above the upper threshold"
            note="Between the thresholds, the taxable amount is the lesser of 50% of benefits and 50% of combined income above the lower threshold. The tier amount is $4,500 for single filers and $6,000 for joint filers."
          >
            <Op>min</Op>
            <V>85% of benefits</V>
            <Op>,</Op>
            <V>min(50% of benefits, tier amount)</V>
            <Op>+</Op>
            <V>85% × (combined income − upper threshold)</V>
          </Formula>
          <Ledger
            title="Example: married filing jointly, $40,000 of benefits, $30,000 of IRA withdrawals"
            rows={[
              { label: "Other income", value: 30000 },
              { op: "+", label: "Half of benefits", value: 20000 },
              { op: "=", label: "Combined income", value: 50000 },
              { label: "Lesser of half of benefits or $6,000", value: 6000 },
              {
                op: "+",
                label: "85% of combined income above $44,000",
                value: 5100,
                detail: "85% × $6,000",
              },
              {
                op: "=",
                label: "Taxable benefits",
                value: 11100,
                detail: "Below the 85% cap of $34,000",
              },
              { op: "→", label: "Adjusted gross income", value: 41100 },
            ]}
          />
          <Figure
            title="Taxable benefits by other income: single filer, $30,000 of benefits"
            caption="Each extra dollar of other income adds 50 cents, then 85 cents, of taxable benefits until 85% of benefits is taxable."
            table={{
              columns: [
                { key: "other", label: "Other income", format: "usd" },
                { key: "taxable", label: "Taxable benefits", format: "usd" },
              ],
              rows: taxablePoints.map(([other, taxable]) => ({ other, taxable })),
            }}
          >
            <LineChart
              label="Taxable Social Security benefits rise from zero at $10,000 of other income to the $25,500 cap at about $43,700"
              xFormat="num"
              series={[
                { id: "taxable", label: "Taxable benefits", color: "blue", points: taxablePoints },
                { id: "cap", label: "85% of benefits", color: "gray", points: capPoints },
              ]}
            />
          </Figure>
          <p>
            The taxable share is added to adjusted gross income, so it can raise the rate on other
            income and push capital gains into a higher bracket; see{" "}
            <HelpLink to="how-taxes-are-calculated" />. Because the test runs on the final income
            for the year, a withdrawal or Roth conversion that raises combined income also raises
            taxable benefits in the same year.
          </p>
          <p>
            With <strong>Married filing separately</strong>, check{" "}
            <strong>Lived apart from spouse for the entire tax year</strong> under Plan details to
            use the single thresholds; otherwise the zero threshold applies in every year.
          </p>
        </>
      ),
    },
    {
      id: "state-tax",
      title: "State income tax on benefits",
      body: (
        <>
          <p>
            State tax starts from federal adjusted gross income, which already contains the taxable
            share of benefits. For California, CoastMath subtracts that share, so benefits aren’t
            taxed by the state. See <HelpLink to="state-and-local-income-tax" /> for how each state
            is modeled.
          </p>
          <Callout kind="boundary">
            <p>
              Other states’ Social Security exclusions aren’t applied. In a state that exempts
              benefits, other than California, the projection includes the federally taxable share
              in state taxable income and can overstate state tax.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "where-it-shows",
      title: "Where the result shows up",
      body: (
        <>
          <p>
            Each benefit appears as income under its stream’s name in the year’s cash flow, and
            funds spending before any withdrawal. The taxable share isn’t shown as its own line; it
            is part of the year’s federal taxable income and tax. A survivor benefit adjustment,
            when you turn one on, appears as a separate income line; see{" "}
            <HelpLink to="survivor-social-security" />.
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
                Spousal benefits for Benefit amount streams: a partner’s stream pays only the amount
                entered for it. Spousal benefits need PIA basis on both streams; survivor benefits
                are a separate opt-in.
              </li>
              <li>
                Child and parent benefits, and the family maximum. Divorced-spouse benefits are
                covered in <HelpLink to="survivor-social-security#former-spouse" />.
              </li>
              <li>
                Claiming in a particular month by age: the claiming age is a whole year, and
                payments start in the birth month.
              </li>
              <li>
                Tax-exempt interest other than municipal bond interest set on a brokerage account,
                which the law adds to combined income (see{" "}
                <HelpLink to="investment-growth#income-tax-character" />
                ).
              </li>
              <li>
                Medicare premiums withheld from benefits: premiums are projected as expenses; see{" "}
                <HelpLink to="medicare-and-irmaa" />.
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
                symptom: "The first year’s benefit is smaller than the annual amount.",
                check: "The recipient’s birth month and the stream’s Start month.",
                next: "Payments start in the birth month, so the claiming year is partial.",
              },
              {
                symptom: "The benefit is much larger than your statement shows.",
                check: "Whether growth compounded from plan start to claiming.",
                next: "Enter today’s dollars, or set Growth rate to 0 for a fixed nominal amount.",
              },
              {
                symptom: "Changing the claiming age didn’t change the amount.",
                check: "With Benefit amount basis, the claiming age only moves the start year.",
                next: "Switch the stream to PIA basis, or re-run Estimate from PIA and save.",
              },
              {
                symptom: "A Roth conversion raised tax by more than its bracket rate.",
                check: "Taxable benefits in the conversion year.",
                next: "Each converted dollar can add 50 or 85 cents of taxable benefits.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};

export default article;

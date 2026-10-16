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
  UIPath,
  V,
} from "../help_kit";
import { LineChart } from "../help_charts";

const over = "and over";

const senior = [
  {
    id: "single",
    label: "Single, 65 or older",
    color: "blue" as const,
    points: [
      [0, 6000],
      [75000, 6000],
      [175000, 0],
      [300000, 0],
    ] as [number, number][],
  },
  {
    id: "joint-both",
    label: "Joint, both 65 or older",
    color: "orange" as const,
    points: [
      [0, 12000],
      [150000, 12000],
      [250000, 0],
      [300000, 0],
    ] as [number, number][],
  },
  {
    id: "joint-one",
    label: "Joint, one 65 or older",
    color: "cyan" as const,
    points: [
      [0, 6000],
      [150000, 6000],
      [250000, 0],
      [300000, 0],
    ] as [number, number][],
  },
];

const article: Article = {
  intro: (
    <>
      <p>
        A 2026 plan year uses the brackets and deductions published for 2026, and a 2025 year uses
        the 2025 figures. Every later year starts from the 2026 figures and grows them by your
        plan’s own inflation assumption, compounded each calendar year. Amounts that the law fixes
        in dollars stay fixed. Temporary provisions end in the year the law ends them.
      </p>
      <p>
        The rates themselves never change. CoastMath assumes current law continues unless you enter
        your own brackets or standard deduction to model a possible change in law.
      </p>
    </>
  ),
  sections: [
    {
      id: "brackets-for-2026",
      title: "Brackets for 2026",
      body: (
        <>
          <DataTable
            caption="2026 federal ordinary income brackets (taxable income up to)"
            columns={[
              { key: "rate", label: "Rate" },
              { key: "single", label: "Single", format: "usd" },
              { key: "joint", label: "Married filing jointly", format: "usd" },
              { key: "separate", label: "Married filing separately", format: "usd" },
            ]}
            rows={[
              { rate: "10%", single: 12400, joint: 24800, separate: 12400 },
              { rate: "12%", single: 50400, joint: 100800, separate: 50400 },
              { rate: "22%", single: 105700, joint: 211400, separate: 105700 },
              { rate: "24%", single: 201775, joint: 403550, separate: 201775 },
              { rate: "32%", single: 256225, joint: 512450, separate: 256225 },
              { rate: "35%", single: 640600, joint: 768700, separate: 384350 },
              { rate: "37%", single: over, joint: over, separate: over },
            ]}
            note="Each rate applies only to the income inside its band. Head of household has its own, wider lower brackets."
          />
          <p>
            Ordinary income fills these brackets. Qualified dividends and long-term gains sit on top
            and use the separate 0, 15 and 20 percent thresholds in{" "}
            <HelpLink to="capital-gains-and-dividends" />.
          </p>
        </>
      ),
    },
    {
      id: "standard-deduction",
      title: "Standard deduction and the age 65 addition",
      body: (
        <>
          <KeyFigures
            caption="2026 standard deduction"
            items={[
              { label: "Single or married filing separately", value: 16100 },
              { label: "Married filing jointly", value: 32200 },
              { label: "Head of household", value: 24150 },
              {
                label: "Added per person 65 or older",
                value: "$2,050 / $1,650",
                detail: "Unmarried / each married spouse",
              },
            ]}
          />
          <p>
            A person counts as 65 in the calendar year they turn 65, based on birth year. A spouse’s
            age counts only on a joint return. In the year a partner dies, the joint return still
            includes their addition.
          </p>
          <Callout kind="boundary">
            <p>
              The additional amount for blindness and the rules for a dependent’s standard deduction
              are not modeled.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "senior-deduction",
      title: "The senior deduction, 2025 through 2028",
      body: (
        <>
          <p>
            For tax years 2025 through 2028, each person 65 or older also gets a $6,000 senior
            deduction. You get it whether you itemize or take the standard deduction. Each person’s
            $6,000 is reduced by 6% of modified AGI above $75,000, or $150,000 on a joint return.
            Modified AGI here is adjusted gross income including gains. These amounts are fixed in
            the law and do not index. Married couples must file jointly to claim it, so a
            married-filing-separately plan gets none. From 2029 the deduction ends.
          </p>
          <Figure
            title="2026 senior deduction by modified AGI"
            caption="On a joint return both spouses’ amounts reach zero at $250,000 whether one or both qualify."
            table={{
              columns: [
                { key: "magi", label: "Modified AGI", format: "usd" },
                { key: "single", label: "Single, 65+", format: "usd" },
                { key: "both", label: "Joint, both 65+", format: "usd" },
                { key: "one", label: "Joint, one 65+", format: "usd" },
              ],
              rows: [
                { magi: 75000, single: 6000, both: 12000, one: 6000 },
                { magi: 125000, single: 3000, both: 12000, one: 6000 },
                { magi: 150000, single: 1500, both: 12000, one: 6000 },
                { magi: 175000, single: 0, both: 9000, one: 4500 },
                { magi: 200000, single: 0, both: 6000, one: 3000 },
                { magi: 250000, single: 0, both: 0, one: 0 },
              ],
            }}
          >
            <LineChart
              series={senior}
              xFormat="usd"
              yFormat="usd"
              label="Senior deduction falls from $6,000 per person by 6% of modified AGI above $75,000 single or $150,000 joint, reaching zero at $175,000 single and $250,000 joint"
            />
          </Figure>
          <Ledger
            title="Example: single, age 67, $95,000 of pension income in 2026"
            rows={[
              { label: "Standard deduction", value: 16100 },
              { op: "+", label: "Addition for age 65 or older", value: 2050 },
              {
                op: "+",
                label: "Senior deduction",
                value: 4800,
                detail: "$6,000 − 6% × ($95,000 − $75,000)",
              },
              { op: "=", label: "Total deduction", value: 22950 },
              { label: "Taxable income", value: 72050, detail: "$95,000 − $22,950" },
              { op: "=", label: "Federal income tax", value: 10563 },
            ]}
          />
        </>
      ),
    },
    {
      id: "how-later-years-are-indexed",
      title: "How later years are indexed",
      body: (
        <>
          <Formula result="Threshold in a later year">
            <V>2026 figure</V>
            <Op>×</Op>
            <V>(1 + inflation 2026)</V>
            <Op>×</Op>
            <V>(1 + inflation 2027)</V>
            <Op>×</Op>
            <V>…</V>
          </Formula>
          <p>
            Each year’s factor is the inflation rate your plan uses for the prior calendar year,
            from a fixed rate or a curve (see <HelpLink to="market-and-inflation-assumptions" />
            ). The factor follows calendar years, not the plan’s start date. A plan starting in 2030
            applies 2026 through 2029 inflation to its first year, and a partial first year still
            uses full-year figures. In success-odds and historical runs, the thresholds follow each
            simulated path’s inflation.
          </p>
          <Ledger
            title="Example: joint standard deduction at 3% inflation"
            rows={[
              { label: "2026, published", value: 32200 },
              { op: "×", label: "1 + 2026 inflation", value: 1.03, format: "num", digits: 2 },
              { op: "=", label: "2027", value: 33166 },
              { op: "×", label: "1 + 2027 inflation", value: 1.03, format: "num", digits: 2 },
              { op: "=", label: "2028", value: 34161 },
            ]}
            note="Amounts are not rounded to the $25 or $50 steps that published tables use."
          />
          <DataTable
            caption="What indexes and what stays fixed"
            columns={[
              { key: "item", label: "Amount" },
              { key: "rule", label: "Later years" },
            ]}
            rows={[
              {
                item: "Ordinary brackets, standard deduction and age 65 addition",
                rule: "Grow with plan inflation",
              },
              { item: "Capital gains 0% and 15% thresholds", rule: "Grow with plan inflation" },
              {
                item: "Alternative minimum tax exemption, phase-out start and 28% threshold",
                rule: "Grow with plan inflation",
              },
              { item: "Social Security wage base", rule: "Grows with plan inflation" },
              {
                item: "State and local tax cap",
                rule: "Rises 1% a year through 2029, then $10,000 from 2030",
              },
              { item: "Senior deduction", rule: "Fixed; ends after 2028" },
              {
                item: "Net investment income tax and Additional Medicare Tax thresholds",
                rule: "Fixed",
              },
              { item: "Social Security taxation thresholds", rule: "Fixed" },
              {
                item: "$3,000 capital loss limit; $1,000 / $2,000 charitable deduction for non-itemizers",
                rule: "Fixed",
              },
            ]}
          />
          <Callout kind="boundary">
            <p>
              Published figures index by a chained consumer price measure, and the Social Security
              wage base follows national average wages. CoastMath uses your plan’s inflation
              assumption for all of them, so later-year thresholds match the published ones only
              when that assumption does.
            </p>
          </Callout>
          <p>
            Income that grows exactly with inflation keeps roughly the same real federal income tax,
            except where a fixed threshold applies. Income that grows faster moves into higher
            brackets. A flat nominal income is taxed less each year: $100,000 of joint wages owes
            $7,640 of federal income tax in 2026, $7,509 in 2027 and $7,374 in 2028 at 3% inflation.
          </p>
        </>
      ),
    },
    {
      id: "child-tax-credit",
      title: "Child tax credit",
      body: (
        <>
          <p>
            Each child under 17 at the end of a tax year earns a $2,200 credit in 2026. After 2026
            the amount grows with your plan’s inflation assumption, rounded down to a multiple of
            $100. It shrinks by $50 for each $1,000, or part of $1,000, of modified AGI above
            $400,000 on a joint return or $200,000 otherwise. Those thresholds are fixed in dollars.
          </p>
          <p>
            The credit reduces federal income tax, including tax on capital gains, but never below
            zero. It doesn’t reduce payroll tax or the net investment income tax.
          </p>
          <Callout kind="boundary">
            <p>
              The refundable portion paid when the credit exceeds your income tax, and the $500
              credit for other dependents, are not modeled. Flat tax mode applies no credit.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "Children’s birth years"]} />, one year per child,
              separated by commas.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "custom-brackets",
      title: "Your own brackets and standard deduction",
      body: (
        <>
          <p>
            Custom federal brackets replace the ordinary-income brackets for every filing status,
            including after a change of filing status. A custom standard deduction replaces the
            basic amount; the age 65 addition and the senior deduction still apply. Capital gains
            rates and thresholds, the net investment income tax, the alternative minimum tax and
            credits follow current law. Roth conversions that fill a bracket and a tax target set to
            a bracket use your brackets, matched by rate. A saved target or conversion rule whose
            rate your brackets lack fills only brackets taxed at or below it, with a warning.
          </p>
          <p>
            Enter amounts in today’s dollars. By default they grow with your plan’s inflation from
            the plan’s start, like your other amounts; uncheck{" "}
            <strong>Grow custom federal amounts with inflation</strong> to keep them fixed in every
            year. Leave the last bracket’s upper bound blank for a top bracket with no limit.
          </p>
          <Ledger
            title="Example: single, $100,000 of wages in 2026"
            rows={[
              { label: "Wages", value: 100000 },
              { op: "−", label: "Custom standard deduction", value: 10000 },
              { op: "=", label: "Taxable income", value: 90000 },
              { label: "10% on the first $50,000", value: 5000 },
              { op: "+", label: "30% on the next $40,000", value: 12000 },
              { op: "=", label: "Federal income tax", value: 17000 },
            ]}
            note="Brackets: 10% up to $50,000, then 30%."
          />
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "Tax law assumptions"]} />. Blank fields follow
              current law.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "law-changes",
      title: "Scheduled law changes",
      body: (
        <>
          <p>
            The figures reflect the 2025 tax law known as the One Big Beautiful Bill Act, which made
            the current rate schedule permanent. CoastMath applies the changes that law schedules:
            the senior deduction stops after 2028, and the state and local tax cap drops back to
            $10,000 in 2030. To model a different schedule, enter your own; see{" "}
            <HelpLink to="federal-brackets-and-deductions#custom-brackets" />.
          </p>
          <Callout kind="boundary">
            <p>
              The same law’s 2025–2028 deductions for tips, overtime pay and car-loan interest are
              not modeled. Of the federal credits, only the child tax credit is; see{" "}
              <HelpLink to="federal-brackets-and-deductions#child-tax-credit" />.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "Filing status"]} /> sets the table.{" "}
              <UIPath steps={["Tax tools", "Annual tax breakdown"]} /> shows each year’s standard
              deduction and the deduction used; the marginal rate there is the bracket from these
              tables.
            </p>
          </Callout>
        </>
      ),
    },
  ],
};
export default article;

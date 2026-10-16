import type { Article } from "../help_types";
import {
  Callout,
  DataTable,
  Figure,
  HelpLink,
  KeyFigures,
  Ledger,
  Symptoms,
  UIPath,
} from "../help_kit";
import { LineChart } from "../help_charts";

const cap = [
  {
    id: "most",
    label: "Single, joint or head of household",
    color: "blue" as const,
    points: [
      [0, 40400],
      [505000, 40400],
      [606333.33, 10000],
      [700000, 10000],
    ] as [number, number][],
  },
  {
    id: "separate",
    label: "Married filing separately",
    color: "orange" as const,
    points: [
      [0, 20200],
      [252500, 20200],
      [303166.67, 5000],
      [700000, 5000],
    ] as [number, number][],
  },
];

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath itemizes state and local taxes, mortgage interest on your primary residence and
        gifts to charity, plus medical expenses when you turn them on. Each year it adds them up,
        applies the federal limits, and compares the total with your standard deduction. It uses
        whichever is larger. You don’t choose; the comparison repeats every year, so a plan can
        itemize while a mortgage is large and switch to the standard deduction later.
      </p>
      <p>
        Medical expenses count only with{" "}
        <UIPath steps={["Plan details", "Deduct medical expenses"]} /> checked.
      </p>
    </>
  ),
  sections: [
    {
      id: "what-coastmath-itemizes",
      title: "What CoastMath itemizes",
      body: (
        <>
          <DataTable
            caption="Itemized deductions and where each amount comes from"
            columns={[
              { key: "item", label: "Deduction" },
              { key: "source", label: "Amount used" },
              { key: "limit", label: "Limit" },
            ]}
            rows={[
              {
                item: "State and local income tax",
                source:
                  "The state and local income tax CoastMath computes for the same year, plus required employee payments for California disability insurance and Washington paid leave",
                limit: "Shares the state and local tax cap",
              },
              {
                item: "Property tax",
                source:
                  "Property tax on every property in the plan, for the part of the year you own it",
                limit: "Shares the state and local tax cap",
              },
              {
                item: "Mortgage interest",
                source:
                  "Interest paid that year on loans linked to a property marked as your primary residence",
                limit: "None applied",
              },
              {
                item: "Charitable gifts",
                source:
                  "Cash gifts and donor-advised fund contributions from your giving plan, plus unused fund contributions carried from earlier years",
                limit: "60% of AGI; from 2026, only the part above 0.5% of AGI counts",
              },
              {
                item: "Gifts of appreciated shares",
                source:
                  "Market value of shares given from a brokerage account, plus unused share gifts carried from earlier years",
                limit: "30% of AGI, counted before cash gifts within the 60% limit",
              },
              {
                item: "Medical expenses (optional)",
                source:
                  "Modeled health coverage and care costs, less HSA reimbursements and premiums deducted as self-employed",
                limit: "Only the part above 7.5% of AGI",
              },
            ]}
          />
          <p>
            State income tax is the tax for the year itself, not the prior year’s payments. Adjusted
            gross income here includes realized gains. Charitable limits, carryforwards and
            qualified charitable distributions are covered in <HelpLink to="charitable-giving" />.
          </p>
          <Callout kind="where">
            <p>
              Property tax is <UIPath steps={["Property and debt", "Annual property tax ($)"]} /> or{" "}
              <strong>Property tax (% of value)</strong>. Mortgage interest counts only when the
              loan’s <strong>Linked real asset</strong> has <strong>Primary residence</strong>{" "}
              checked. Amounts already paid this year go in{" "}
              <UIPath steps={["Plan details", "Earlier this tax year"]} />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "state-and-local-tax-cap",
      title: "The state and local tax cap",
      body: (
        <>
          <KeyFigures
            caption="2026 cap on state and local taxes"
            items={[
              { label: "Cap", value: 40400, detail: "$20,200 married filing separately" },
              {
                label: "Phase-down starts at modified AGI",
                value: 505000,
                detail: "$252,500 married filing separately",
              },
              { label: "Reduction", value: "30%", detail: "Of modified AGI above the start" },
              { label: "Floor", value: 10000, detail: "$5,000 married filing separately" },
            ]}
          />
          <p>
            The cap and the phase-down start both rise 1% a year through 2029. From 2030 the cap is
            a flat $10,000 ($5,000 married filing separately), as scheduled in current law. These
            steps come from the statute, not your inflation assumption.
          </p>
          <Figure
            title="2026 cap on state and local taxes by modified AGI"
            caption="Above about $606,000 of modified AGI ($303,000 married filing separately) the cap sits at its floor."
            table={{
              columns: [
                { key: "magi", label: "Modified AGI", format: "usd" },
                { key: "most", label: "Single, joint, head of household", format: "usd" },
              ],
              rows: [
                { magi: 505000, most: 40400 },
                { magi: 550000, most: 26900 },
                { magi: 600000, most: 11900 },
                { magi: 606334, most: 10000 },
              ],
            }}
          >
            <LineChart
              series={cap}
              xFormat="usd"
              yFormat="usd"
              label="State and local tax cap of $40,400 falls by 30% of modified AGI above $505,000 to a $10,000 floor; half those amounts when married filing separately"
            />
          </Figure>
          <Ledger
            title="Example: joint return, modified AGI $600,000"
            rows={[
              { label: "2026 cap", value: 40400 },
              { op: "−", label: "30% × ($600,000 − $505,000)", value: 28500 },
              { op: "=", label: "Cap this year", value: 11900 },
            ]}
          />
        </>
      ),
    },
    {
      id: "standard-or-itemized",
      title: "Standard or itemized",
      body: (
        <>
          <p>
            CoastMath itemizes only when the itemized total is larger than your standard deduction,
            including any age 65 addition. From 2026, the standard side also counts the deduction
            non-itemizers get for cash gifts to public charities: up to $1,000, or $2,000 on a joint
            return. Donor-advised fund contributions don’t qualify for it. The senior deduction is
            added either way.
          </p>
          <Ledger
            title="Example: joint return, $300,000 of wages, 2026"
            rows={[
              { label: "State income tax", value: 18000 },
              { op: "+", label: "Property tax", value: 12000 },
              { op: "=", label: "State and local taxes, under the $40,400 cap", value: 30000 },
              { op: "+", label: "Mortgage interest", value: 20000 },
              {
                op: "+",
                label: "Charitable gifts above the floor",
                value: 8500,
                detail: "$10,000 − 0.5% × $300,000",
              },
              { op: "=", label: "Itemized total", value: 58500 },
              { label: "Standard deduction", value: 32200 },
              { op: "→", label: "Deduction used: itemized", value: 58500 },
            ]}
            note="Both spouses are under 65, so there is no age addition or senior deduction. Taxable income is $241,500."
          />
          <Callout kind="where">
            <p>
              <UIPath steps={["Tax tools", "Annual tax breakdown"]} /> shows the deduction used and
              the standard deduction for the selected year. <strong>Deduction Comparison</strong>{" "}
              below it charts both across the plan.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "what-isnt-itemized",
      title: "What isn’t itemized",
      body: (
        <>
          <Callout kind="boundary">
            <ul>
              <li>
                Medical and dental expenses, including amounts above 7.5% of AGI and long-term care
                premiums.
              </li>
              <li>
                The acquisition-debt limit on mortgage interest. Loan origination and refinancing
                history aren’t collected, so interest on any loan linked to your primary residence
                is deducted in full. The plan shows a warning when this applies.
              </li>
              <li>
                Mortgage interest on second homes and loans not linked to a primary residence.
              </li>
              <li>
                The 2026 overall limit that reduces itemized deductions for taxpayers in the 37%
                bracket. Itemizers in that bracket see a slightly larger deduction than the law
                allows.
              </li>
              <li>
                Investment interest, casualty and gambling losses, the sales tax election, and gifts
                of property rather than cash.
              </li>
            </ul>
          </Callout>
          <p>
            Under the alternative minimum tax, capped state and local taxes are added back. See{" "}
            <HelpLink to="payroll-and-other-federal-taxes#alternative-minimum-tax" />.
          </p>
        </>
      ),
    },
    {
      id: "reading-the-result",
      title: "Reading the result",
      body: (
        <>
          <Symptoms
            rows={[
              {
                symptom: "The deduction used is standard despite a mortgage.",
                check:
                  "Whether the loan’s linked property is marked as the primary residence, and the itemized total against the standard deduction.",
                next: "Link the loan to the home. With the higher standard deduction, many itemized totals still fall short.",
              },
              {
                symptom: "State tax counts for less than you pay.",
                check: "Modified AGI above the phase-down start.",
                next: "The cap falls by 30% of the excess, to $10,000 at most incomes above about $606,000.",
              },
              {
                symptom: "A plan switches from itemized to standard partway through.",
                check: "The year the mortgage balance falls, a move to a lower-tax state, or 2030.",
                next: "Expected: the comparison repeats each year, and the cap drops to $10,000 in 2030.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

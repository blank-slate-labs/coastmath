import type { Article } from "../help_types";
import { Callout, Figure, Formula, HelpLink, Ledger, Op, Symptoms, UIPath, V } from "../help_kit";
import { BarChart } from "../help_charts";

/* $9,000 a month from July 2040 for 36 months, 4% LTC inflation from a 2026 plan start, 25% covered.
   Engine output; see the sources record. */
const ltcYears = ["2040", "2041", "2042", "2043"];
const ltcNet = [70132.9, 145876.42, 151711.48, 78889.97];
const ltcCovered = [23377.63, 48625.47, 50570.49, 26296.66];

const ltcFigure = (
  <Figure
    title="Long-term-care cost by year: your share and the covered share"
    caption="Care runs July 2040 through June 2043, so the first and last years hold six months each."
    table={{
      columns: [
        { key: "year", label: "Year" },
        { key: "net", label: "Paid from your plan", format: "usd" },
        { key: "covered", label: "Covered", format: "usd" },
        { key: "gross", label: "Gross cost", format: "usd" },
      ],
      rows: ltcYears.map((year, index) => ({
        year,
        net: ltcNet[index],
        covered: ltcCovered[index],
        gross: Math.round((ltcNet[index] + ltcCovered[index]) * 100) / 100,
      })),
    }}
  >
    <BarChart
      label="Long-term-care cost from 2040 to 2043, split into the 75% paid from the plan and the 25% covered"
      categories={ltcYears}
      series={[
        { id: "net", label: "Paid from your plan", color: "magenta", values: ltcNet },
        { id: "covered", label: "Covered", color: "gray", values: ltcCovered },
      ]}
    />
  </Figure>
);

const article: Article = {
  intro: (
    <>
      <p>
        With health coverage turned on, CoastMath adds each person’s medical budget and any
        long-term-care budget to spending, together with premiums, as one <em>Health coverage</em>{" "}
        amount. Every budget is entered in plan-start dollars and grows at medical inflation from
        the plan’s start year. For long-term care, only the share you don’t mark as covered is paid
        from your plan.
      </p>
      <p>
        These costs are always paid in full; flexible spending rules never reduce them. They aren’t
        deducted on your tax return.
      </p>
    </>
  ),
  sections: [
    {
      id: "choose-a-method",
      title: "Choose a medical cost method for each person",
      body: (
        <>
          <Callout kind="where">
            <p>
              <UIPath steps={["Health coverage", "Model health coverage costs"]} />, then{" "}
              <em>Medical cost method</em> under <em>Primary person healthcare</em> (and{" "}
              <em>Partner healthcare</em>). Save with <em>Save health coverage</em>.
            </p>
          </Callout>
          <ul>
            <li>
              <strong>Use shared settings</strong>: premiums only, from the plan’s marketplace and
              Medicare settings. No out-of-pocket or long-term-care budget.
            </li>
            <li>
              <strong>Coverage premiums + optional budget</strong>: premiums from this person’s own
              marketplace and Medicare choices, plus{" "}
              <em>Out-of-pocket budget ($ per year, optional)</em> for every year the person is
              alive in the plan, including years before Medicare.
            </li>
            <li>
              <strong>Itemized medical budget</strong>: one annual amount that replaces this
              person’s premiums and out-of-pocket costs. It starts in the birthday month of{" "}
              <em>Medical budget starts at age</em> and stops before the birthday month of the
              optional end age.
            </li>
            <li>
              <strong>Off</strong>: no medical costs for this person.
            </li>
          </ul>
          <p>
            How premiums are calculated is covered in <HelpLink to="marketplace-health-coverage" />{" "}
            and <HelpLink to="medicare-and-irmaa" />.
          </p>
          <Callout kind="entry">
            <p>
              A blank out-of-pocket budget means unknown: CoastMath models premiums only and warns
              that the estimate is incomplete. Enter 0 for no out-of-pocket cost.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "medical-inflation",
      title: "How medical budgets grow",
      body: (
        <>
          <Formula result="Cost in a year">
            <V>Entered annual amount</V>
            <Op>×</Op>
            <V>(1 + medical inflation)</V>
            <sup>years since plan start</sup>
            <Op>×</Op>
            <V>share of the year covered</V>
          </Formula>
          <p>
            The rate is the person’s <em>Medical inflation (% per year, optional)</em> if set,
            otherwise the plan’s <em>Medical cost inflation (% per year, optional)</em>, otherwise
            plan inflation. Growth counts from the plan’s start year even for a budget that begins
            later.
          </p>
          <Ledger
            title="Example: $7,200 a year from 65 at 5% medical inflation, birthday in April, plan start 2026"
            rows={[
              { label: "Entered annual amount", value: 7200 },
              { op: "×", label: "Months at 65 or older in 2026, April–December", value: "9 ÷ 12" },
              { op: "=", label: "Cost in 2026", value: 5400 },
              { label: "Full year in 2027", value: 7560, detail: "$7,200 × 1.05" },
              { label: "Full year in 2031", value: 9189, detail: "$7,200 × 1.05⁵" },
            ]}
          />
        </>
      ),
    },
    {
      id: "long-term-care",
      title: "Long-term care: gross cost and covered share",
      body: (
        <>
          <p>
            Turn on <em>Include a long-term-care budget</em> after choosing any method other than{" "}
            <em>Use shared settings</em>; choose <em>Off</em> to model care without other medical
            costs. You enter a monthly cost, a duration in months and a start, either a calendar
            year and month or a number of months before the end of the person’s modeled lifetime.
          </p>
          <Formula
            result="Paid from your plan"
            note="Months in care this year stop at the earlier of the duration’s end and the person’s death."
          >
            <V>Monthly cost</V>
            <Op>×</Op>
            <V>growth since the reference year</V>
            <Op>×</Op>
            <V>months in care this year</V>
            <Op>×</Op>
            <V>(1 − covered share)</V>
          </Formula>
          <p>
            Care costs grow at <em>LTC inflation (% per year, optional)</em> if you enter it,
            otherwise at that person’s medical inflation. The monthly cost is in dollars of the
            plan’s start year unless you set <em>LTC amount reference year</em>; a different
            reference year requires an LTC inflation rate.
          </p>
          {ltcFigure}
          <Ledger
            title="Example: $9,000 a month at 4% LTC inflation, starting July 2040, 25% covered"
            rows={[
              { label: "Monthly cost, 2026 dollars", value: 9000 },
              {
                op: "×",
                label: "Growth for 14 years at 4%",
                value: 1.7316765,
                format: "num",
                digits: 4,
              },
              { op: "=", label: "Monthly cost in 2040", value: 15585 },
              { op: "×", label: "Months in care, July–December", value: 6, format: "num" },
              { op: "=", label: "Gross cost, 2040", value: 93511 },
              { op: "−", label: "Covered share, 25%", value: 23378 },
              { op: "=", label: "Paid from your plan, 2040", value: 70133 },
            ]}
          />
          <Callout kind="boundary">
            <p>
              The covered share is your assumption. CoastMath doesn’t model a long-term-care
              policy’s benefit triggers, waiting period or daily maximum, Medicaid eligibility or
              spend-down, or selling a home to pay for care. Enter policy premiums as an expense.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "taxes-and-hsas",
      title: "Taxes and HSAs",
      body: (
        <>
          <p>
            Medical costs are deducted only when you check{" "}
            <UIPath steps={["Plan details", "Deduct medical expenses"]} />. Then every modeled cost
            counts as a medical expense: premiums after the premium tax credit (marketplace,
            Medicare Parts A, B and D, IRMAA and Medigap), out-of-pocket and itemized budgets, and
            net long-term care. Costs an HSA reimbursed tax free that year are left out. The part
            above 7.5% of AGI joins your other itemized deductions, and CoastMath itemizes only if
            the total beats the standard deduction; see <HelpLink to="itemized-deductions" />.
          </p>
          <Ledger
            title="Example: $30,000 of medical costs on $60,000 of wages, single"
            rows={[
              { label: "Medical costs", value: 30000 },
              { op: "−", label: "7.5% of AGI", value: 4500 },
              {
                op: "=",
                label: "Itemized medical deduction",
                value: 25500,
                detail: "Beats the $16,100 standard deduction",
              },
            ]}
          />
          <p>
            With self-employment income, the same setting deducts premiums above the line instead,
            up to your net business profit (profit less the deductible half of self-employment tax
            and self-employed retirement contributions). That lowers AGI, which raises any premium
            tax credit and so lowers the premium; CoastMath repeats the two calculations until they
            agree. Premiums deducted this way aren’t itemized too.
          </p>
          <Callout kind="boundary">
            <ul>
              <li>
                Months you could join an employer-subsidized health plan; the self-employed
                deduction assumes none, and the plan shows a warning.
              </li>
              <li>
                Long-term care insurance premiums, health premiums paid through payroll and other
                medical costs you enter as ordinary expenses.
              </li>
              <li>State medical deductions; only the federal deduction is applied.</li>
            </ul>
          </Callout>
          <p>
            Your modeled medical costs, including the net long-term-care cost, also set how much an
            HSA can pay tax-free each year; see <HelpLink to="hsa" />.
          </p>
        </>
      ),
    },
    {
      id: "where-results-show",
      title: "Where the results show up",
      body: (
        <>
          <p>
            Each year’s cash flow shows one <em>Health coverage</em> line: premiums after credits,
            medical budgets and net long-term care, for both people. It’s treated as essential
            spending. The yearly total also appears in the <em>Total cost</em> column of the health
            coverage table; see <HelpLink to="tax-analytics" />.
          </p>
          <Symptoms
            rows={[
              {
                symptom: "No out-of-pocket costs appear",
                check: "Whether the person uses shared settings, or the budget is blank",
                next: "Choose Coverage premiums + optional budget and enter an amount, or 0.",
              },
              {
                symptom: "The long-term-care toggle is missing",
                check: "The person’s medical cost method",
                next: "Choose any method other than Use shared settings.",
              },
              {
                symptom: "Care costs are much higher than entered",
                check: "Growth from the plan’s start year to the care years",
                next: "That’s medical or LTC inflation; set LTC amount reference year and its inflation rate if your figure is for a later year.",
              },
              {
                symptom: "Care costs stop before the duration ends",
                check: "The person’s modeled lifetime",
                next: "Costs end at death.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};

export default article;

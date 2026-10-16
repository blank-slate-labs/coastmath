import type { Article } from "../help_types";
import { Callout, Figure, Formula, HelpLink, Ledger, Op, Symptoms, UIPath, V } from "../help_kit";
import { BarChart } from "../help_charts";

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath figures each year’s total tax after that year’s withdrawals. It then subtracts
        what was already paid: withholding from income and any taxes you entered as paid earlier in
        the first year. The difference is settled in the same plan year. A refund is cash that year,
        and a balance due is paid that year from cash or withdrawals. Nothing carries into the next
        year.
      </p>
      <p>
        Withholding therefore changes how a year’s cash flow is split between tax withheld and a
        refund or balance due. It doesn’t change balances, net worth or total tax.
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
            <strong>Tax withholding (% of gross)</strong> on an income stream sets aside that share
            of the stream’s pay for the months it’s active. For a plan that starts partway through a
            year, enter taxes already paid that year under <strong>Earlier this tax year</strong>.
          </p>
          <Callout kind="where">
            <p>
              <UIPath
                steps={[
                  "Income streams",
                  "Growth and tax settings",
                  "Tax withholding (% of gross)",
                ]}
              />{" "}
              and{" "}
              <UIPath
                steps={[
                  "Plan details",
                  "Earlier this tax year",
                  "Total taxes already paid, including payroll tax",
                ]}
              />
              .
            </p>
          </Callout>
          <Callout kind="entry" title="Withholding covers the whole tax bill">
            <p>
              Withholding is compared with the year’s total tax: federal income tax, payroll tax,
              state and local tax, and the net investment income tax. A percentage that covers only
              income tax leaves a balance due roughly equal to the payroll tax. A blank percentage
              means nothing is withheld.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-settlement-works",
      title: "How the year is settled",
      body: (
        <>
          <Formula
            result="Refund (+) or balance due (−)"
            note="A difference between the advance and final Marketplace credit is included here too."
          >
            <V>Tax withheld</V>
            <Op>+</Op>
            <V>Taxes paid earlier this year</V>
            <Op>−</Op>
            <V>The year’s total tax</V>
          </Formula>
          <Ledger
            title="Example: single filer in Texas, 2026, $100,000 salary, 15% withheld"
            rows={[
              { label: "Tax withheld from salary", value: 15000 },
              { op: "−", label: "Federal income tax", value: 13170 },
              { op: "−", label: "Payroll tax", value: 7650 },
              { op: "=", label: "Balance due, paid in 2026", value: -5820 },
            ]}
          />
          <Figure
            title="Withholding and settlement for the same $100,000 salary"
            caption="Total tax is $20,820 in every case, and year-end net worth is the same."
            table={{
              columns: [
                { key: "case", label: "Withholding" },
                { key: "withheld", label: "Withheld", format: "usd" },
                { key: "settled", label: "Settled at year end", format: "usd" },
              ],
              rows: [
                { case: "None", withheld: 0, settled: 20820 },
                { case: "15%", withheld: 15000, settled: 5820 },
                { case: "30%", withheld: 30000, settled: -9180 },
              ],
            }}
          >
            <BarChart
              label="Tax withheld and settled at year end at 0%, 15% and 30% withholding; a 30% rate produces a $9,180 refund, shown below zero"
              categories={["None", "15%", "30%"]}
              series={[
                {
                  id: "withheld",
                  label: "Withheld during the year",
                  color: "orange",
                  values: [0, 15000, 30000],
                },
                {
                  id: "settled",
                  label: "Paid (refunded) at settlement",
                  color: "gray",
                  values: [20820, 5820, -9180],
                },
              ]}
            />
          </Figure>
          <p>
            A balance due comes out of the year’s cash flow. If that isn’t enough, it comes from
            withdrawals in your drawdown order. A withdrawal from a pre-tax account adds to the tax,
            so the tax is figured again with that withdrawal included. A refund follows your income
            allocation rules. It first fills any fixed-amount rule that was short that year, then
            goes to rules that take what’s left. Anything remaining goes to your cash account.
          </p>
        </>
      ),
    },
    {
      id: "same-year-timing",
      title: "Why no bill lands the following year",
      body: (
        <>
          <p>
            A real balance due for one year is paid by the next April. CoastMath settles it in the
            year the income is earned. So the tax on your last working year shows up in that year,
            and the year after retirement starts without a bill from the year before. A large Roth
            conversion or sale is taxed in the year you make it.
          </p>
          <Callout kind="boundary">
            <p>
              The April payment date isn’t modeled. <strong>Tax balance carried</strong> in Tax
              Analytics stays at $0 in plans built in the planner, because nothing is carried.
              Quarterly estimated payments and the underpayment penalty are optional; see the next
              section.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "estimated-tax-payments",
      title: "Estimated tax payments and the underpayment penalty",
      body: (
        <>
          <p>
            Federal tax is due as income is earned, through withholding or quarterly estimated
            payments. Plans with large Roth conversions, gain harvesting, self-employment or
            retirement income often have little withholding, and could owe an underpayment penalty.
            You choose whether CoastMath models this:
          </p>
          <ul>
            <li>
              <strong>Not modeled</strong> (the default): no estimates and no penalty.
            </li>
            <li>
              <strong>Pay the balance when filing</strong>: no estimates. If withholding falls short
              of the required annual payment, the penalty is estimated and paid with that year’s
              tax.
            </li>
            <li>
              <strong>Pay safe-harbor estimates</strong>: four equal payments bring withholding up
              to the required annual payment, so there’s no penalty.
            </li>
            <li>
              <strong>Pay projected federal tax in estimates</strong>: four equal payments cover the
              federal tax that isn’t withheld, so nothing federal is left to pay at filing.
            </li>
          </ul>
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "Estimated tax payments"]} />. Enter last year’s
              federal tax and adjusted gross income for the first plan year if you know them; later
              years use the year before in the plan.
            </p>
          </Callout>
          <Formula
            result="Required annual payment"
            note="110% instead of 100% when last year’s adjusted gross income was over $150,000, or $75,000 married filing separately. Without last year’s tax, only the 90% share applies; without its income, 110% is assumed."
          >
            <V>the smaller of</V>
            <V>90% × this year’s federal tax</V>
            <Op>and</Op>
            <V>100% × last year’s federal tax</V>
          </Formula>
          <p>
            <strong>Federal tax</strong> here is federal income tax, including the alternative
            minimum tax, plus self-employment tax, the net investment income tax and the 0.9%
            Additional Medicare Tax, after credits. Payroll tax on wages and state and local tax
            don’t count. Because one withholding percentage covers the whole bill, withholding first
            pays the payroll tax on wages; the rest is shared between federal and state tax in
            proportion to each. Withholding counts as paid evenly on the four due dates: April 15,
            June 15, September 15 and January 15.
          </p>
          <p>
            A quarter that falls short accrues interest at the IRS underpayment rate (7% at the end
            of 2026; later years keep the latest rate) until it’s paid or until April 15 of the next
            year. There’s no penalty when the federal tax left after withholding is under $1,000, or
            when last year’s federal tax was $0. The penalty isn’t deductible. It’s included in the
            year’s taxes and shown separately.
          </p>
          <Ledger
            title="Example: the same $100,000 Texas salary, 15% withheld, 2026"
            rows={[
              { label: "Federal income tax", value: 13170 },
              { label: "Required annual payment (90%)", value: 11853 },
              {
                op: "−",
                label: "Withholding toward federal tax",
                detail: "$15,000 withheld less $7,650 payroll tax",
                value: 7350,
              },
              { op: "=", label: "Safe-harbor estimates, four payments of $1,125.75", value: 4503 },
            ]}
            note="With Pay the balance when filing, the plan instead pays an underpayment penalty of about $207 and still owes $5,820 at filing."
          />
          <Callout kind="where">
            <p>
              <UIPath steps={["Overview", "Cash flow"]} /> shows{" "}
              <strong>Estimated tax payments</strong> and <strong>Underpayment penalty</strong>{" "}
              beside withholding; <strong>Tax Owed</strong> is then the balance left at filing.{" "}
              <UIPath steps={["Tax tools", "Annual tax breakdown"]} /> lists the estimates, the
              required annual payment and the penalty for each year.
            </p>
          </Callout>
          <Callout kind="boundary">
            <p>
              State estimated tax and state penalties, the annualized income method for uneven
              income, penalty waivers, farming and fishing rules, interest after April 15 and
              interest on refunds aren’t modeled. Every strategy still settles the year’s remaining
              balance in that plan year.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "first-year",
      title: "The first plan year",
      body: (
        <>
          <p>
            The first year’s tax covers the whole calendar year. It includes income you entered as
            earned before the plan’s start date. Taxes paid before the start date are credited
            against that full-year tax. While that history is blank, the Overview shows{" "}
            <strong>Review tax history</strong>, and earlier income with its matching tax share is
            estimated pro rata from active plan streams. See <HelpLink to="first-plan-year" />.
          </p>
        </>
      ),
    },
    {
      id: "amounts-settled-elsewhere",
      title: "Credits and additional taxes",
      body: (
        <>
          <p>
            <strong>Marketplace premium credit.</strong> If the advance credit you entered differs
            from the credit on the year’s final income, the difference is part of that year’s
            settlement: extra credit adds to a refund, and excess advance credit is repaid with the
            balance due. See <HelpLink to="marketplace-health-coverage" />.
          </p>
          <p>
            <strong>Early-withdrawal additional tax.</strong> The 10% additional tax on retirement
            withdrawals before 59½, and the 20% on HSA withdrawals before 65 that aren’t for medical
            costs, are paid out of the withdrawal when it’s made. The withdrawal is enlarged to
            cover it. The amount is counted in the year’s total taxes and shown as{" "}
            <strong>Early withdrawal penalty</strong>. It’s never part of the refund or balance due.
            See <HelpLink to="early-withdrawals" />.
          </p>
        </>
      ),
    },
    {
      id: "where-results-show",
      title: "Where the result shows up",
      body: (
        <>
          <Callout kind="where">
            <p>
              <UIPath steps={["Overview", "Cash flow"]} /> shows <strong>Tax Withholding</strong>,
              then <strong>Tax Refund</strong> or <strong>Tax Owed</strong> for the selected year.{" "}
              <UIPath steps={["Tax tools", "Annual tax breakdown"]} /> shows the liability line by
              line.
            </p>
          </Callout>
          <Symptoms
            rows={[
              {
                symptom: "A large Tax Owed every working year",
                check: "Tax withholding on each income stream",
                next: "Expected if withholding is blank or excludes payroll tax. Balances are unaffected; raise the percentage for a realistic cash-flow view.",
              },
              {
                symptom: "A refund that doesn’t appear as cash",
                check: "Income allocation rules",
                next: "The refund was saved by those rules. Check the Cash flow contributions for that year.",
              },
              {
                symptom: "The first year’s tax looks too high or too low",
                check: "Earlier this tax year",
                next: "Enter income and taxes paid before the start date.",
              },
              {
                symptom: "No tax bill in the year after retirement",
                check: "The last working year",
                next: "Expected: that year’s balance was settled in the same year.",
              },
              {
                symptom: "An underpayment penalty in a year",
                check: "Estimated tax payments and withholding",
                next: "Choose safe-harbor estimates, or raise withholding on income streams.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

import type { Article } from "../help_types";
import { Callout, Figure, Formula, HelpLink, Ledger, Op, Symptoms, UIPath, V } from "../help_kit";
import { Waterfall } from "../help_charts";

const waterfall = [
  { label: "Total income", value: 164000, color: "blue" as const },
  { label: "Pre-tax contributions", value: -20000, color: "cyan" as const },
  { label: "Adjusted gross income", value: 0, total: true },
  { label: "Standard deduction", value: -32200, color: "gray" as const },
  { label: "Taxable income", value: 0, total: true },
];

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath prepares a full calendar-year return for every plan year. Income becomes adjusted
        gross income, then taxable income. Ordinary income runs through the federal brackets.
        Qualified dividends and long-term gains are taxed on top of it at 0, 15 or 20 percent.
        Payroll tax, the net investment income tax, any alternative minimum tax, and state and local
        income tax are added to reach the year’s total tax.
      </p>
      <p>
        The calculation runs after the year’s income, required distributions, conversions and sales
        are known. It runs again once contributions and shortfall withdrawals settle, so the tax
        always reflects the year’s final income, including any withdrawals made to pay the tax
        itself.
      </p>
    </>
  ),
  sections: [
    {
      id: "from-income-to-taxable-income",
      title: "From income to taxable income",
      body: (
        <>
          <p>Income that counts toward the return:</p>
          <ul>
            <li>
              Wages, self-employment profit, pensions, annuities and other income streams, at their
              taxable amounts.
            </li>
            <li>
              Dividends and realized gains in taxable brokerage and crypto accounts, and bond
              interest in a brokerage account that sets a bond income yield. Municipal bond interest
              is left out, but it still counts toward the taxation of Social Security (see{" "}
              <HelpLink to="investment-growth#income-tax-character" />
              ).
            </li>
            <li>
              Traditional-account withdrawals and required distributions, less any qualified
              charitable distributions. Roth conversions, and the taxable part of any non-qualified
              Roth or HSA withdrawal, count too.
            </li>
            <li>
              The taxable share of Social Security, set each year by your other income and filing
              status (see <HelpLink to="social-security" />
              ).
            </li>
          </ul>
          <p>
            Adjustments come off next: pre-tax payroll contributions, pre-tax contributions funded
            from surplus (only the deductible part of a traditional IRA contribution when a
            workplace plan phases it out; see <HelpLink to="contributions-and-employer-match" />
            ), the deductible half of self-employment tax, and up to $3,000 of net capital loss
            ($1,500 if married filing separately). The result is adjusted gross income. CoastMath
            then subtracts the larger of your standard deduction or your itemized deductions, plus
            the senior deduction for anyone 65 or older through 2028 and any qualified business
            income deduction. What remains is taxable income.
          </p>
          <Formula result="Taxable income">
            <V>Total income</V>
            <Op>−</Op>
            <V>Adjustments</V>
            <Op>−</Op>
            <V>Standard or itemized deduction</V>
            <Op>−</Op>
            <V>Senior and business deductions</V>
          </Formula>
          <Figure
            title="Example: a married couple’s 2026 return, income to taxable income"
            caption="Wages $150,000, qualified dividends $4,000 and a $10,000 long-term gain; $20,000 of pre-tax 401(k) deferrals; both spouses 45; filing jointly."
            table={{
              columns: [
                { key: "step", label: "Step" },
                { key: "amount", label: "Amount", format: "usd" },
              ],
              rows: [
                { step: "Total income", amount: 164000 },
                { step: "Pre-tax contributions", amount: -20000 },
                { step: "Adjusted gross income", amount: 144000 },
                { step: "Standard deduction", amount: -32200 },
                { step: "Taxable income", amount: 111800 },
              ],
            }}
          >
            <Waterfall
              steps={waterfall}
              label="Total income of $164,000 less $20,000 of pre-tax contributions gives adjusted gross income of $144,000; less the $32,200 standard deduction gives taxable income of $111,800"
            />
          </Figure>
          <p>
            Brackets, deductions and how they index in later years are in{" "}
            <HelpLink to="federal-brackets-and-deductions" />. The itemize-or-not comparison is in{" "}
            <HelpLink to="itemized-deductions" />.
          </p>
        </>
      ),
    },
    {
      id: "ordinary-income-then-gains",
      title: "Ordinary income first, then gains on top",
      body: (
        <>
          <p>
            Taxable income has two layers. Qualified dividends and long-term gains form the
            preferential layer. Everything else is ordinary and fills the brackets from the bottom.
            The preferential layer starts where ordinary income ends. How much of it falls in the 0,
            15 or 20 percent band depends on that starting point, not on its own size. When
            deductions exceed ordinary income, the unused deduction reduces the preferential layer.
          </p>
          <Ledger
            title="Example, continued: the 2026 federal tax"
            rows={[
              {
                label: "Ordinary taxable income",
                value: 97800,
                detail: "$111,800 taxable income less $14,000 of dividends and gains",
              },
              { op: "→", label: "10% on the first $24,800", value: 2480 },
              { op: "+", label: "12% on the next $73,000", value: 8760 },
              { op: "=", label: "Ordinary income tax", value: 11240 },
              { label: "Dividends and gains, stacked from $97,800", value: 14000 },
              { op: "→", label: "0% on $1,100 up to the $98,900 threshold", value: 0 },
              { op: "+", label: "15% on the remaining $12,900", value: 1935 },
              { op: "=", label: "Capital gains tax", value: 1935 },
              {
                op: "+",
                label: "Payroll tax",
                value: 11475,
                detail: "6.2% Social Security and 1.45% Medicare on $150,000 of wages",
              },
              { op: "=", label: "Total tax for the year", value: 24650 },
            ]}
            note="No state was selected, so state and local tax are zero. The alternative minimum tax does not apply at this income."
          />
          <p>
            Details, including loss carryforwards and the net investment income tax, are in{" "}
            <HelpLink to="capital-gains-and-dividends" />.
          </p>
        </>
      ),
    },
    {
      id: "other-taxes-in-the-total",
      title: "Other taxes in the total",
      body: (
        <>
          <ul>
            <li>
              <strong>Payroll tax.</strong> Social Security and Medicare tax on wages,
              self-employment tax on business profit, and the 0.9% Additional Medicare Tax. See{" "}
              <HelpLink to="payroll-and-other-federal-taxes" />.
            </li>
            <li>
              <strong>Alternative minimum tax.</strong> Only the amount by which the minimum tax
              exceeds your regular federal tax is added. See{" "}
              <HelpLink to="payroll-and-other-federal-taxes#alternative-minimum-tax" />.
            </li>
            <li>
              <strong>Net investment income tax.</strong> 3.8% on investment income once modified
              AGI passes a fixed threshold.
            </li>
            <li>
              <strong>State and local income tax.</strong> Each state starts from federal adjusted
              gross income, including gains, removes Treasury interest, adds municipal interest from
              bonds not marked in-state, and applies its own deduction and brackets. Local taxes
              follow their own jurisdiction. See <HelpLink to="state-and-local-income-tax" />. The
              state and local income tax the plan computes also feeds your federal itemized
              deduction for state and local taxes.
            </li>
            <li>
              <strong>Early withdrawal penalties</strong> are included in total taxes in results.
              See <HelpLink to="early-withdrawals" />.
            </li>
          </ul>
          <p>
            The only federal credit CoastMath figures on its own is the child tax credit, which
            reduces federal income tax (see{" "}
            <HelpLink to="federal-brackets-and-deductions#child-tax-credit" />
            ). Credits you enter yourself are applied as described below. The premium tax credit for
            marketplace coverage reduces your health premiums instead (see{" "}
            <HelpLink to="marketplace-health-coverage" />
            ).
          </p>
        </>
      ),
    },
    {
      id: "your-own-adjustments",
      title: "Deductions, credits and surcharges you enter",
      body: (
        <>
          <p>
            Use adjustments for tax items the plan doesn’t model, such as an education or energy
            credit or a deduction you expect to claim. Each one is an annual tax-return amount for
            the years you choose.
          </p>
          <ul>
            <li>
              <strong>Above-the-line deduction.</strong> Lowers adjusted gross income on the returns
              you choose. A federal-only deduction is added back for state tax; a state-only one
              changes only state tax.
            </li>
            <li>
              <strong>Itemized deduction.</strong> Joins your federal itemized total and helps only
              when itemizing beats the standard deduction. It never lowers adjusted gross income and
              is allowed under the alternative minimum tax. A state itemized deduction counts only
              in states that use the state deduction rules (see{" "}
              <HelpLink to="state-and-local-income-tax#state-deduction-rules" />
              ).
            </li>
            <li>
              <strong>Credit.</strong> Reduces federal income tax (regular tax, minimum tax and
              capital gains tax) or state income tax, never payroll tax, self-employment tax or the
              net investment income tax, and never below zero. A <strong>refundable</strong>{" "}
              credit’s remainder is paid to you: it lowers the year’s total tax and arrives as cash
              when the year’s tax settles.
            </li>
            <li>
              <strong>Surcharge.</strong> A percentage of the base you pick (ordinary taxable
              income, all taxable income, capital gains, or the income tax itself), added before
              credits, with an optional yearly maximum.
            </li>
          </ul>
          <p>
            Each adjustment applies once, every year or every few years, from the plan start, a year
            or a milestone, through an end year or milestone (inclusive). A milestone that is never
            reached never starts an adjustment, and one that never ends it leaves it open. Amounts
            in today’s dollars rise with your inflation assumption. A start or end inside a year
            still applies the whole amount for that tax year, and the plan’s first partial year
            isn’t prorated. Items marked as yours or your partner’s stop after the return for the
            year of that person’s death.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "Tax adjustments and scheduled changes"]} />.{" "}
              <UIPath steps={["Tax tools", "Annual tax breakdown"]} /> totals include them.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "scheduled-changes",
      title: "Tax settings that change later",
      body: (
        <>
          <p>
            A scheduled change replaces the tax mode, the flat income tax and capital gains rates,
            or the state deduction rules choice from a year or from the year a milestone is reached.
            It lasts until a later change replaces the same setting. When two changes start in the
            same year, the one lower in the list wins. A change dated before the plan starts is
            already in effect, and a milestone that is never reached never applies.
          </p>
          <p>
            Every part of that year’s calculation uses the same settings: withholding on
            withdrawals, conversion and harvesting limits, the tax target and the final tax
            settlement. Withholding rates, settlement timing and the tax target themselves stay
            fixed for the whole plan.
          </p>
        </>
      ),
    },
    {
      id: "effective-and-marginal-rates",
      title: "Effective and marginal rates",
      body: (
        <>
          <p>
            <strong>Effective rate</strong> is total taxes, including early withdrawal penalties,
            divided by the year’s income and realized distributions and gains. That denominator
            includes the full Social Security benefit, not just its taxable share. It also includes
            required distributions before any charitable offset, employer contributions to workplace
            accounts and the taxable amount of Roth conversions. In the example, $24,650 ÷ $164,000
            = 15.0%.
          </p>
          <p>
            <strong>Marginal rate</strong> is the federal ordinary bracket that your last dollar of
            ordinary taxable income falls in: 12% in the example. It leaves out state tax, the
            capital gains rate, the net investment income tax, and phase-ins such as the taxation of
            Social Security or the senior deduction phase-out. The next dollar of income can
            therefore cost more than the marginal rate shows. A year whose taxable income is all
            gains shows a 0% marginal rate even when those gains are taxed at 15%.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Overview", "Income & taxes"]} /> charts gross income, total taxes and
              both rates by year. <UIPath steps={["Tax tools", "Annual tax breakdown"]} /> lists
              each component for a selected year, the deduction used and the standard deduction
              available, in future (nominal) dollars.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "what-isnt-modeled",
      title: "What isn’t modeled",
      body: (
        <>
          <Callout kind="boundary">
            <ul>
              <li>
                Other federal credits, unless you enter them as adjustments: the refundable part of
                the child tax credit, the credit for other dependents, the child and dependent care
                credit, education credits, the foreign tax credit and energy credits. CoastMath
                doesn’t check an entered credit’s eligibility, income limits or carryforward.
              </li>
              <li>The 2025–2028 deductions for tips, overtime pay and car-loan interest.</li>
              <li>
                Short-term gains: every realized gain is long-term. Dividends in a taxable account
                are qualified unless the account sets a lower qualified share.
              </li>
              <li>
                Tax-exempt interest other than municipal bond interest set on a brokerage account,
                and the dependent (kiddie tax) rules.
              </li>
            </ul>
          </Callout>
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
                symptom: "Tax in a year when income is below the standard deduction.",
                check: (
                  <>
                    The <UIPath steps={["Tax tools", "Annual tax breakdown"]} /> payroll and state
                    lines.
                  </>
                ),
                next: "Payroll tax applies from the first dollar of wages; some states have small or no standard deductions.",
              },
              {
                symptom: "Marginal rate shows 12% but gains cost 15%.",
                check: "Whether the year has qualified dividends or long-term gains.",
                next: (
                  <>
                    The marginal rate is the ordinary bracket only; gains follow their own
                    thresholds (see <HelpLink to="capital-gains-and-dividends#how-gains-stack" />
                    ).
                  </>
                ),
              },
              {
                symptom: "Effective rate looks low in retirement.",
                check: "How much of the income is Social Security or charitable distributions.",
                next: "The denominator counts the full benefit and gross required distributions, so the rate is lower than tax ÷ taxable income.",
              },
              {
                symptom: "Total tax differs from the tax paid in a year.",
                check: (
                  <>
                    The <strong>Tax balance carried</strong> line.
                  </>
                ),
                next: (
                  <>
                    Liability and payment timing differ; see{" "}
                    <HelpLink to="tax-payments-and-settlement" />.
                  </>
                ),
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

import type { Article } from "../help_types";
import { Callout, DataTable, HelpLink, Ledger, Symptoms, UIPath } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        Pensions, annuities, rental income and other unearned income are income streams with{" "}
        <strong>Earned income</strong> unchecked. Taxable categories enter federal and state income
        tax, and none is subject to payroll tax. The tax category you choose decides whether it
        counts toward the net investment income tax and how some local taxes treat it.
      </p>
      <p>
        Timing works as it does for wages. Growth doesn’t: an unearned income with a blank Growth
        rate never grows.
      </p>
    </>
  ),
  sections: [
    {
      id: "pension-formula",
      title: "Salary-linked pensions",
      body: (
        <>
          <p>
            For a qualified pension, choose a Benefit formula: flat annual benefit, final average
            pay or career average pay. Salary-linked benefits multiply the selected average nominal
            salary by service years and Benefit percent per service year. Service accrues by active
            salary months before pension payments start. Final average pay uses the last selected
            number of calendar years with service, weighted by active months; career average pay
            weights all modeled service.
          </p>
          <p>
            Service years before plan use the salary’s plan-start pay where earlier pay is unknown.
            Flat annual benefit is entered in today’s dollars and follows plan inflation until
            payments start. The annual benefit freezes at commencement; Pension COLA applies
            afterward. Blank Pension COLA means no increase. Formula benefits ignore the stream’s
            Growth rate and Growth cap.
          </p>
        </>
      ),
    },
    {
      id: "one-time-and-repeat",
      title: "One-time and repeating payments",
      body: (
        <>
          <p>
            Set Payment frequency to Once and enter the full payment in the annual entry unit. The
            full amount arrives in the start month, with growth from plan start until payment.
            Recurring payments can Repeat every (years), counting from the first active calendar
            year. A one-time bonus or RSU vest uses employment income and incurs wage and payroll
            taxes. Later share-sale gains are outside this income stream.
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
            Add the income with the <strong>Other</strong> income type and choose an{" "}
            <strong>Income tax treatment</strong>. The form requires a choice. The amount,
            frequency, recipient, milestones, months and withholding work as they do for a salary;
            see
            <> </>
            <HelpLink to="wages-and-raises" />.
          </p>
          <Callout kind="entry">
            <p>
              Enter taxable payments in their taxable category and any tax-free portion as a
              separate Nontaxable cash receipt. CoastMath does not calculate an annuity exclusion
              ratio automatically.
            </p>
          </Callout>
          <p>
            Social Security has its own income type, claiming age and taxation rules; see
            <> </>
            <HelpLink to="social-security" />. An older unearned income saved without a category
            keeps the investment-income treatment until you choose one, and the projection shows a
            warning.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Income streams", "Add income", "Growth and tax settings"]} />
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "tax-categories",
      title: "How each tax category is taxed",
      body: (
        <>
          <DataTable
            caption="Income tax treatment for unearned income"
            columns={[
              { key: "category", label: "Income tax treatment" },
              { key: "use", label: "Typical income" },
              { key: "niit", label: "Net investment income tax" },
            ]}
            rows={[
              {
                category: "Nontaxable cash receipt",
                use: "Cash gifts, after-tax inheritances and generally life insurance death proceeds",
                niit: "Excluded",
              },
              {
                category: "Qualified pension or retirement distribution",
                use: "Employer pensions and payouts from workplace retirement plans",
                niit: "Excluded",
              },
              {
                category: "Nonqualified annuity taxable income",
                use: "The taxable part of an annuity bought with after-tax money",
                niit: "Included",
              },
              {
                category: "Investment income",
                use: "Net rental income, royalties, interest received outside an account",
                niit: "Included",
              },
              {
                category: "Other ordinary income excluded from NIIT",
                use: "Unemployment benefits, taxable alimony, other taxable income",
                niit: "Excluded",
              },
            ]}
            note="Taxable categories enter ordinary income. Nontaxable cash receipts enter cash flow only. None is subject to Social Security or Medicare tax."
          />
          <p>
            Investment income entered here is taxed at ordinary rates, not at the rates for
            qualified dividends and long-term gains. Dividends and gains from accounts you track are
            figured separately; see
            <> </>
            <HelpLink to="capital-gains-and-dividends" />. Rental income is investment income for
            the net investment income tax unless the rental is a trade or business you work in.
          </p>
          <p>
            Some local taxes read the category. Michigan city income taxes exclude pension and
            annuity income. Philadelphia’s school income tax applies to investment income and
            annuities. Local taxes on earned income ignore all four categories. See{" "}
            <HelpLink to="state-and-local-income-tax" />.
          </p>
        </>
      ),
    },
    {
      id: "growth-and-cola",
      title: "Growth and cost-of-living adjustments",
      body: (
        <>
          <p>
            For unearned income, a blank Growth rate and 0 both mean the payment is fixed in nominal
            dollars. Unlike wages, a blank rate doesn’t follow inflation. For a pension with a
            cost-of-living adjustment, enter its COLA as the Growth rate. A{" "}
            <strong>Growth cap</strong> limits a COLA that stops at a set payment.
          </p>
          <Callout kind="entry">
            <p>
              A growth rate compounds from the plan’s start year, not from the year payments start.
              If a pension statement quotes the first payment and a COLA, divide the quoted payment
              by (1 + COLA) raised to the number of years from the plan start to the first payment.
              With no COLA, enter the quoted payment and leave the rate blank.
            </p>
          </Callout>
          <Ledger
            title="Example: $30,000 a year from 65 with a 2% COLA, starting in 2041"
            rows={[
              { label: "Quoted first-year payment", value: 30000, format: "usd_cents" },
              {
                op: "÷",
                label: "1.02 raised to 15 years (2026 to 2041)",
                value: 1.34586834,
                format: "num",
                digits: 4,
              },
              { op: "=", label: "Amount to enter", value: 22290.44, format: "usd_cents" },
              {
                op: "→",
                label: "Paid in 2041, July through December",
                value: 15000,
                format: "usd_cents",
              },
              { op: "→", label: "Paid in 2042, after one COLA", value: 30600, format: "usd_cents" },
            ]}
            note="Plan starts January 2026; the plan owner was born in July 1976, so the age-65 milestone is reached in July 2041. Entering $30,000 with a 2% rate would pay at $40,376.05 a year in 2041 instead."
          />
        </>
      ),
    },
    {
      id: "timing",
      title: "When payments start and stop",
      body: (
        <>
          <p>
            A pension usually starts at a milestone. In that year, payments begin in the{" "}
            <strong>Start month</strong>, or in the month the milestone is reached. Age milestones
            use the plan owner’s age. For a partner’s pension, use a date milestone, or a milestone
            set to the plan owner’s age in that year.
          </p>
          <p>
            Every income stops when its recipient dies. CoastMath has no joint-and-survivor option
            for a pension or annuity. To model a survivor benefit, add a second income owned by the
            survivor, starting at a date milestone for the year the benefit would begin. See{" "}
            <HelpLink to="death-of-a-partner" /> for when each person’s income ends.
          </p>
        </>
      ),
    },
    {
      id: "tax-free-income",
      title: "Tax-free income",
      body: (
        <>
          <Callout kind="boundary">
            <p>
              Choose <strong>Nontaxable cash receipt</strong> for tax-free cash. It increases cash
              flow without entering AGI, MAGI or payroll tax. Gifts, after-tax inheritances and life
              insurance death proceeds generally qualify; later earnings on that property can be
              taxable. Inherited retirement accounts use the inherited-account settings.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "not-modeled",
      title: "What else isn’t modeled",
      body: (
        <>
          <Callout kind="boundary">
            <ul>
              <li>
                The exclusion ratio for annuities and the recovery of after-tax pension
                contributions. Enter the taxable portion.
              </li>
              <li>
                Government and military pension exclusions. Private pension and retirement-income
                exclusions apply automatically in 23 states; see{" "}
                <HelpLink to="state-and-local-income-tax" />.
              </li>
              <li>
                Buying an annuity with an account balance, and choosing between a lump sum and a
                pension. Enter the payments you expect as income.
              </li>
              <li>
                Depreciation, passive loss limits and rental expenses on an income stream. To model
                them, enter the rental as a property instead (see{" "}
                <HelpLink to="homes-and-real-assets#rental-property" />
                ).
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
                symptom: "A pension stays flat though you left growth blank.",
                check: "Blank growth means no growth for unearned income.",
                next: "Enter the COLA as the Growth rate.",
              },
              {
                symptom: "A pension with a COLA starts higher than its quoted amount.",
                check: "The rate compounds from the plan’s start year.",
                next: (
                  <>
                    Discount the quoted payment as in{" "}
                    <a href="#growth-and-cola">the example above</a>.
                  </>
                ),
              },
              {
                symptom: "A net investment income tax appears on rental or annuity income.",
                check: "Investment income and nonqualified annuities count toward it.",
                next: (
                  <>
                    Check the category; see <HelpLink to="capital-gains-and-dividends" />.
                  </>
                ),
              },
              {
                symptom: "A partner’s pension stops earlier than expected.",
                check: "Income ends when its recipient dies.",
                next: "Add a survivor income owned by the other person.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

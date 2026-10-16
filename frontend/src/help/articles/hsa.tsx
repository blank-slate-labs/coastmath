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
import { Timeline } from "../help_charts";

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath limits HSA contributions by the coverage you declare for each person and month,
        deducts them from federal taxable income, and grows the balance untaxed. A withdrawal is
        tax-free up to the year’s modeled qualified medical costs; anything beyond that is taxable
        income, plus a 20% additional tax on the share of the year before 65.
      </p>
    </>
  ),
  sections: [
    {
      id: "coverage-and-limits",
      title: "Coverage sets the contribution limit",
      body: (
        <>
          <KeyFigures
            caption="2026 HSA limits"
            items={[
              { label: "Self-only coverage", value: 4400 },
              { label: "Family coverage", value: 8750, detail: "Shared by spouses" },
              { label: "Catch-up from age 55", value: 1000, detail: "Per person, not indexed" },
              {
                label: "Minimum plan deductible",
                value: "$1,700 / $3,400",
                detail: "Self-only / family",
              },
            ]}
          />
          <p>
            You declare eligibility as HSA periods: for each person, a range of years, the coverage
            (self-only high-deductible plan, family plan, or not eligible) and the eligible months
            within each year. CoastMath then applies:
          </p>
          <ul>
            <li>
              <strong>Monthly proration.</strong> The base limit and the catch-up each accrue
              one-twelfth per eligible month.
            </li>
            <li>
              <strong>One family limit.</strong> In a month when either spouse has family coverage,
              the family limit is shared between both spouses’ HSAs. Each person’s catch-up can go
              only into their own HSA.
            </li>
            <li>
              <strong>Employer money counts.</strong> Employer contributions use the same limit,
              after your own contributions that year.
            </li>
            <li>
              <strong>Indexing.</strong> After 2026, the base limits grow with plan inflation; the
              $1,000 catch-up stays fixed, as in law.
            </li>
          </ul>
          <Ledger
            title="Example: self-only coverage January–June, age 56"
            rows={[
              { label: "Self-only limit, 6 of 12 months", value: 2200, detail: "$4,400 × 6 ÷ 12" },
              { op: "+", label: "Catch-up, 6 of 12 months", value: 500, detail: "$1,000 × 6 ÷ 12" },
              { op: "=", label: "Contribution limit for the year", value: 2700 },
            ]}
          />
          <Ledger
            title="Example: family coverage, both spouses 57"
            rows={[
              { label: "Family limit", value: 8750 },
              { op: "+", label: "Your catch-up", value: 1000 },
              { op: "+", label: "Partner’s catch-up", value: 1000 },
              { op: "=", label: "Household limit", value: 10750 },
              { op: "−", label: "Contributed to your HSA", value: 7750 },
              {
                op: "=",
                label: "Room left in your partner’s HSA",
                value: 3000,
                detail: "$2,000 of family limit + their own $1,000 catch-up",
              },
            ]}
          />
          <p>
            With no HSA period for a year, each owner gets the self-only limit plus the catch-up
            from 55, every year, and a warning says eligibility is unspecified. If Health coverage
            enrolls that owner in Medicare, contributions stop from the enrollment month, and the
            enrollment year’s limit is prorated to the months before it. A family limit is never
            inferred from marriage, and a partner’s catch-up needs the partner’s birth date.
          </p>
          <Callout kind="entry">
            <p>
              Enrolling in any part of Medicare ends HSA eligibility from its first month; age alone
              doesn’t. Mark those months, and any month without a qualifying plan, as not eligible.
              From 2026, bronze and catastrophic marketplace plans count as HSA-compatible.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              <UIPath
                steps={["Plan details", "Health savings & work coverage", "Add HSA period"]}
              />
              . Contributions themselves come from payroll rules or surplus rules in{" "}
              <HelpLink to="contributions-and-employer-match" /> and <HelpLink to="savings-rules" />
              .
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-contributions-are-taxed",
      title: "How contributions are taxed",
      body: (
        <>
          <DataTable
            caption="Tax treatment of HSA contributions"
            columns={[
              { key: "route", label: "Contribution" },
              { key: "federal", label: "Federal income tax" },
              { key: "fica", label: "Payroll taxes" },
              { key: "ca", label: "California" },
            ]}
            rows={[
              {
                route: "Payroll, section 125 salary reduction",
                federal: "Excluded",
                fica: "Excluded",
                ca: "Taxed",
              },
              {
                route: "Payroll, direct or funding unknown",
                federal: "Deducted",
                fica: "Taxed",
                ca: "Taxed",
              },
              {
                route: "Surplus rule after spending",
                federal: "Deducted",
                fica: "Taxed",
                ca: "Taxed",
              },
              {
                route: "Employer contribution",
                federal: "Excluded",
                fica: "Excluded",
                ca: "Taxed",
              },
            ]}
            note="California doesn’t follow the federal HSA rules, so CoastMath adds every HSA contribution back to California income for a resident. Other states follow the federal treatment in CoastMath."
          />
          <p>
            Because contributions lower adjusted gross income, they also lower the income used for
            the premium tax credit and, two years later, for Medicare surcharges. Growth inside the
            account is never taxed federally.
          </p>
          <p>
            The payroll funding choice is <strong>Employee HSA funding</strong> on each HSA period;{" "}
            <HelpLink to="payroll-deductions" /> covers its effect on pay.
          </p>
        </>
      ),
    },
    {
      id: "withdrawals",
      title: "Tax-free and taxable withdrawals",
      body: (
        <>
          <p>
            Each year, CoastMath totals the qualified medical costs it models for the household
            under Health coverage:
          </p>
          <ul>
            <li>Medicare premiums: Part A, Part B, Part D plans and income-related surcharges.</li>
            <li>Out-of-pocket and itemized medical budgets.</li>
            <li>Long-term care costs, after the covered share.</li>
          </ul>
          <p>
            Marketplace premiums don’t qualify, and neither does the Medigap or Advantage premium
            field, because it may hold a Medigap premium. When an HSA is in your withdrawal order,
            its withdrawals reimburse the remaining qualified costs first, tax-free. Beyond them, a
            withdrawal is taxable income, and before 65 it also owes the 20% additional tax, which
            CoastMath pays out of the withdrawal.
          </p>
          <Formula result="Taxable HSA withdrawal">
            <V>HSA withdrawal</V>
            <Op>−</Op>
            <V>Qualified medical costs not yet reimbursed this year</V>
          </Formula>
          <Ledger
            title="Example: $12,000 needed from the HSA at 62"
            rows={[
              {
                label: "Qualified medical costs this year",
                value: 8000,
                detail: "Reimbursed tax-free",
              },
              {
                op: "+",
                label: "Taxable withdrawal",
                value: 5000,
                detail: "$4,000 still needed ÷ (1 − 20%)",
              },
              { op: "=", label: "Total withdrawn", value: 13000 },
              { op: "−", label: "20% additional tax", value: 1000 },
              { op: "=", label: "Cash for spending", value: 12000 },
            ]}
            note="The $5,000 is also ordinary income on that year’s return. The same need at 66 withdraws $12,000, of which $4,000 is taxable and no additional tax applies."
          />
          <p>
            The additional tax is prorated by month in the year you turn 65: it applies to the share
            of withdrawals made before your 65th-birthday month.
          </p>
          <Callout kind="entry">
            <p>
              An expense set to <strong>Fund from a specific account</strong> with your HSA as the
              source is treated as a qualified medical expense and withdrawn tax-free, whatever its
              amount. Use that only for spending that qualifies, and don’t also model the same costs
              under Health coverage.
            </p>
          </Callout>
          <Figure
            title="HSA rules by age"
            caption="Contributions stop at Medicare enrollment when you mark those months as not eligible, or when Health coverage models Medicare and no HSA period is entered."
            table={{
              columns: [
                { key: "rule", label: "Rule" },
                { key: "from", label: "From age", format: "age" },
                { key: "to", label: "Until age", format: "age" },
              ],
              rows: [
                { rule: "Contributions while eligible", from: 40, to: 65 },
                { rule: "$1,000 catch-up", from: 55, to: 65 },
                { rule: "Non-medical withdrawals: income plus 20%", from: 40, to: 65 },
                { rule: "Non-medical withdrawals: income only", from: 65, to: 90 },
              ],
            }}
          >
            <Timeline
              label="HSA contribution and withdrawal rules by age for someone who enrolls in Medicare at 65"
              from={40}
              to={90}
              spans={[
                { from: 40, to: 65, label: "Contributions while eligible", color: "cyan", row: 0 },
                { from: 55, to: 65, label: "Catch-up", color: "cyan", row: 1 },
                { from: 40, to: 65, label: "Non-medical: income + 20%", color: "orange", row: 2 },
                { from: 65, to: 90, label: "Non-medical: income only", color: "gray", row: 2 },
              ]}
              events={[
                { at: 55, label: "Catch-up starts" },
                { at: 65, label: "Medicare" },
              ]}
            />
          </Figure>
        </>
      ),
    },
    {
      id: "after-65-and-at-death",
      title: "After 65 and at death",
      body: (
        <>
          <p>
            An HSA has no required distributions. After 65, Medicare premiums keep qualifying, so an
            HSA in the withdrawal order can pay them tax-free for as long as the balance lasts; see{" "}
            <HelpLink to="medicare-and-irmaa" />.
          </p>
          <p>
            When a partner dies, their HSA passes to the surviving partner and keeps its tax
            treatment; see <HelpLink to="death-of-a-partner" />. At the end of the plan, a remaining
            HSA balance is counted with traditional IRA and 401(k) balances as income your heirs
            will owe tax on at the heir tax rate you set, unless a partner survives; see{" "}
            <HelpLink to="estate-tax-and-net-estate" />.
          </p>
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
                Reimbursing medical costs from earlier years. Qualified costs count only in the year
                they occur.
              </li>
              <li>
                The last-month rule and its testing period, the disability exception to the 20%
                additional tax, and checks that your plan’s deductible qualifies.
              </li>
              <li>
                California’s tax on interest, dividends and gains inside an HSA. Only contributions
                are added back.
              </li>
              <li>
                A beneficiary’s deduction for the decedent’s medical bills paid within a year of
                death.
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
                symptom: "HSA withdrawals are taxed even though you have medical costs.",
                check:
                  "Whether those costs are modeled under Health coverage, and whether they’re marketplace or Medigap premiums.",
                next: (
                  <>
                    Model the costs there; see <HelpLink to="medical-costs-and-long-term-care" />.
                  </>
                ),
              },
              {
                symptom: "HSA contributions continue after 65.",
                check: "Whether an HSA period marks Medicare months as not eligible.",
                next: "Add an HSA period with Not eligible for HSA contributions from your Medicare start.",
              },
              {
                symptom: "A couple’s contributions stop at the self-only limit.",
                check: "Whether an HSA period declares Family HDHP coverage for those years.",
                next: "Add a Family HDHP period, for both spouses if both have an HSA; a partner left unspecified gets no room.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

import type { Article } from "../help_types";
import { Callout, DataTable, HelpLink, Ledger, Pair, Steps, Symptoms, UIPath } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        A payroll deduction is an expense tied to one earned income. It comes out of that pay, only
        in the months that pay is received. Its payroll tax treatment sets which wages it lowers:
        pre-tax lowers the wages subject to federal, state and local income tax, and after-tax
        lowers none. You can change each of those, and Social Security and Medicare wages,
        separately.
      </p>
      <p>
        Retirement and HSA contributions taken from pay are set up as payroll rules instead. Among
        those rules, only an HSA contribution made through a cafeteria plan lowers payroll-tax
        wages.
      </p>
    </>
  ),
  sections: [
    {
      id: "set-up",
      title: "Enter a payroll deduction",
      body: (
        <>
          <Steps>
            <li>
              Open <UIPath steps={["Expenses", "Add expense"]} /> and enter the amount. The form
              starts with a monthly amount.
            </li>
            <li>
              Open <UIPath steps={["Advanced: growth, funding and timing"]} /> and check{" "}
              <strong>Payroll Deduction</strong>.
            </li>
            <li>
              Under <strong>Deduct from income</strong>, choose the income it comes out of. Only
              earned income is listed.
            </li>
            <li>
              Choose <strong>Pre-tax</strong> or <strong>After-tax</strong> under{" "}
              <strong>Payroll tax treatment</strong>.
            </li>
            <li>
              Optionally, change the boxes under <strong>Reduces taxable wages for</strong>. They
              start at the treatment’s defaults.
            </li>
          </Steps>
          <Callout kind="entry">
            <p>
              Enter the salary itself gross, before this deduction. The deduction is then subtracted
              once. Choose Pre-tax only for deductions your employer takes before income tax, such
              as health, dental and vision premiums under a cafeteria plan. CoastMath applies the
              treatment you pick; it doesn’t check whether a benefit qualifies.
            </p>
          </Callout>
          <p>
            A payroll deduction can’t also be funded from a specific account. It grows like any
            other expense: with plan inflation by default, or at a custom or fixed rate, compounding
            from the plan’s start year. Flexible spending rules never cut it. See{" "}
            <HelpLink to="expenses" /> for the growth options.
          </p>
        </>
      ),
    },
    {
      id: "what-each-deduction-lowers",
      title: "What each kind of deduction lowers",
      body: (
        <>
          <DataTable
            caption="Effect of each paycheck deduction on a W-2 salary"
            columns={[
              { key: "kind", label: "Deduction" },
              { key: "income", label: "Income-taxable wages" },
              { key: "payroll", label: "Social Security and Medicare wages" },
              { key: "cash", label: "Take-home pay" },
            ]}
            rows={[
              {
                kind: "Payroll deduction, Pre-tax",
                income: "Lower",
                payroll: "Unchanged",
                cash: "Lower",
              },
              {
                kind: "Payroll deduction, Pre-tax with Social Security and Medicare checked",
                income: "Lower",
                payroll: "Lower",
                cash: "Lower",
              },
              {
                kind: "Payroll deduction, After-tax",
                income: "Unchanged",
                payroll: "Unchanged",
                cash: "Lower",
              },
              {
                kind: "Traditional 401(k) contribution",
                income: "Lower",
                payroll: "Unchanged",
                cash: "Lower",
              },
              {
                kind: "Roth 401(k) contribution",
                income: "Unchanged",
                payroll: "Unchanged",
                cash: "Lower",
              },
              {
                kind: "HSA contribution, section 125 salary reduction",
                income: "Lower",
                payroll: "Lower",
                cash: "Lower",
              },
              {
                kind: "HSA contribution, direct or funding unknown",
                income: "Lower",
                payroll: "Unchanged",
                cash: "Lower",
              },
            ]}
            note="Contributions come from payroll rules in Income allocation. How HSA money is funded is set per HSA period in Plan details."
          />
          <p>
            The pre-tax reduction lowers adjusted gross income. It therefore lowers federal and
            state income tax, and every threshold that uses AGI or MAGI, such as the taxable share
            of Social Security, premium tax credits and IRMAA. Local taxes that start from taxable
            wages use the lower amount too.
          </p>
          <Callout kind="where">
            <p>
              Payroll rules are in{" "}
              <UIPath
                steps={["Income allocation", "Payroll contributions and account transfers"]}
              />
              . HSA funding is <strong>Employee HSA funding</strong> in{" "}
              <UIPath steps={["Plan details", "Health savings & work coverage"]} />. Limits and
              employer money are covered in <HelpLink to="contributions-and-employer-match" /> and{" "}
              <HelpLink to="hsa" />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "choose-which-taxes",
      title: "Choose which taxes a deduction lowers",
      body: (
        <>
          <p>
            The four boxes under <strong>Reduces taxable wages for</strong> are federal income tax,
            state income tax, local income tax, and Social Security and Medicare. Only boxes that
            differ from the treatment’s defaults are saved, so an expense you never change keeps
            following its treatment.
          </p>
          <DataTable
            caption="Typical elections"
            columns={[
              { key: "kind", label: "Deduction" },
              { key: "boxes", label: "Boxes to check" },
            ]}
            rows={[
              {
                kind: "Health, dental or vision premium through a section 125 cafeteria plan",
                boxes: "All four",
              },
              {
                kind: "Retirement deferral entered as an expense (401(k)-style)",
                boxes: "Federal, state and local; not Social Security and Medicare",
              },
              {
                kind: "Pennsylvania resident’s retirement deferral",
                boxes:
                  "Federal only: Pennsylvania and its local earned income taxes include deferrals",
              },
              {
                kind: "New Jersey resident’s 403(b) or 457 deferral",
                boxes: "Uncheck state: New Jersey excludes only 401(k) deferrals",
              },
              {
                kind: "Union dues, after-tax insurance, charitable payroll giving",
                boxes: "None (After-tax)",
              },
            ]}
            note="Retirement contributions entered as payroll rules already follow these state rules; the elections apply to payroll deduction expenses."
          />
          <p>
            Unchecking <strong>Federal income tax</strong> while keeping{" "}
            <strong>State income tax</strong> checked subtracts the amount from the state base only,
            and the reverse adds it back to the state base. Lower Social Security and Medicare wages
            lower the payroll tax and any local tax measured on Medicare wages.
          </p>
        </>
      ),
    },
    {
      id: "pre-tax-and-after-tax",
      title: "Pre-tax and after-tax compared",
      body: (
        <>
          <p>
            A single filer earns $100,000 in 2026 and has $6,000 a year of health premiums deducted
            from pay. Nothing else is entered.
          </p>
          <Pair
            left={{
              title: "Pre-tax",
              body: (
                <Ledger
                  title="Federal income tax"
                  rows={[
                    { label: "Wages", value: 100000 },
                    { op: "−", label: "Pre-tax deduction", value: 6000 },
                    { op: "−", label: "Standard deduction", value: 16100 },
                    { op: "=", label: "Taxable income", value: 77900 },
                    { op: "→", label: "Income tax", value: 11850 },
                  ]}
                />
              ),
            }}
            right={{
              title: "After-tax",
              body: (
                <Ledger
                  title="Federal income tax"
                  rows={[
                    { label: "Wages", value: 100000 },
                    { op: "−", label: "After-tax deduction", value: 0, detail: "not subtracted" },
                    { op: "−", label: "Standard deduction", value: 16100 },
                    { op: "=", label: "Taxable income", value: 83900 },
                    { op: "→", label: "Income tax", value: 13170 },
                  ]}
                />
              ),
            }}
          />
          <p>
            Pre-tax treatment saves $1,320: the $6,000 comes off the top of the 22 percent bracket.
            Social Security and Medicare tax is $7,650 either way, and pay after the deduction is
            $94,000 either way.
          </p>
        </>
      ),
    },
    {
      id: "when-deductions-stop",
      title: "When deductions start and stop",
      body: (
        <>
          <p>
            A deduction applies only in the months its income is paid. If it has its own milestones,
            it applies only in the months when both the deduction and the income are active. When a
            job ends mid-year, its deductions end with it. When the income stops for good, the
            deduction stops too; it doesn’t become an ordinary expense paid from savings.
          </p>
          <Ledger
            title="Example: the year pay ends in June"
            rows={[
              { label: "Deduction entered, today’s dollars", value: 6000 },
              {
                op: "×",
                label: "Inflation factor for 2031",
                value: 1.15927407,
                format: "num",
                digits: 4,
                detail: "five years at 3%",
              },
              {
                op: "×",
                label: "Months the salary is paid ÷ 12",
                value: 0.5,
                format: "num",
                digits: 2,
              },
              { op: "=", label: "Deduction in 2031", value: 3477.82, format: "usd_cents" },
            ]}
            note="The salary in this example ends at a retirement milestone reached in July 2031, as in the example in Wages, raises and work income."
          />
          <p>
            For how a salary’s months are set, see{" "}
            <HelpLink to="wages-and-raises#when-pay-starts-and-stops">
              when pay starts and stops
            </HelpLink>
            .
          </p>
        </>
      ),
    },
    {
      id: "where-it-shows",
      title: "Where deductions show up",
      body: (
        <>
          <p>
            Payroll deductions count in the year’s expenses. The year’s cash flow shows each one
            leaving gross income before after-tax cash, as workplace deferrals do. See{" "}
            <HelpLink to="cash-flow-view" />.
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
                Whether a deduction qualifies for each exclusion. CoastMath applies the treatment
                and boxes you choose.
              </li>
              <li>
                Flexible spending accounts and dependent care accounts as accounts. A contribution
                to one is just a pre-tax deduction; reimbursements aren’t tracked.
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
                symptom: "Payroll tax didn’t fall after marking a premium pre-tax.",
                check: "Pre-tax lowers income-taxable wages only by default.",
                next: (
                  <>
                    Check <strong>Social Security and Medicare</strong> under{" "}
                    <strong>Reduces taxable wages for</strong> for a cafeteria-plan premium.
                  </>
                ),
              },
              {
                symptom: "A deduction disappears in retirement.",
                check: "Deductions stop with the income they’re tied to.",
                next: (
                  <>
                    Add a regular expense for costs that continue, such as retiree health premiums.
                  </>
                ),
              },
              {
                symptom: "The income you want isn’t in the Deduct from income list.",
                check: (
                  <>
                    Only earned income is listed: a <strong>Salary</strong>, or{" "}
                    <strong>Other</strong> income with <strong>Earned income</strong> checked.
                  </>
                ),
                next: "Deduct from wages or business income, or enter a regular expense.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

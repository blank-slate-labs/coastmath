import type { Article } from "../help_types";
import {
  Callout,
  Figure,
  Formula,
  Frac,
  HelpLink,
  Ledger,
  Op,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";
import { BarChart } from "../help_charts";

const loanYears = Array.from({ length: 30 }, (_, i) => i + 1);
const interestByYear = [
  17900, 17673, 17431, 17175, 16903, 16615, 16308, 15983, 15637, 15271, 14881, 14468, 14029, 13563,
  13068, 12543, 11985, 11393, 10765, 10097, 9389, 8637, 7838, 6990, 6090, 5135, 4120, 3043, 1900,
  685,
];
const principalByYear = [
  3684, 3911, 4152, 4409, 4681, 4969, 5276, 5601, 5947, 6313, 6703, 7116, 7555, 8021, 8516, 9041,
  9599, 10191, 10819, 11486, 12195, 12947, 13746, 14593, 15493, 16449, 17464, 18541, 19684, 20898,
];

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath amortizes every loan one month at a time. By default, each month’s interest is
        one-twelfth of the annual rate on the balance (simple and daily interest are also
        available), and the rest of the payment reduces the principal. Payments are essential
        spending every year until the balance reaches zero. If you set a payoff milestone, CoastMath
        pays the remaining balance in one lump sum in that month.
      </p>
    </>
  ),
  sections: [
    {
      id: "what-you-enter",
      title: "What you enter",
      body: (
        <>
          <Callout kind="where">
            <p>
              <UIPath steps={["Property and debt", "Add loan or debt"]} />. To see a saved loan’s
              schedule, open its <strong>Edit … / schedule</strong> button.
            </p>
          </Callout>
          <p>
            <strong>Principal balance ($)</strong> is what you owe today.{" "}
            <strong>Interest rate (% per year)</strong> is the annual rate.{" "}
            <strong>Payment type</strong> sets how the monthly payment is determined:
          </p>
          <ul>
            <li>
              <strong>Fixed</strong>: a level payment. Enter <strong>Monthly payment ($)</strong>,
              or leave it blank and enter <strong>Remaining term (months)</strong>. CoastMath then
              calculates the payment that retires today’s balance over that term and saves it
              rounded to the cent. If you enter both, the payment you entered is used.
            </li>
            <li>
              <strong>Percent of balance</strong>: each month’s payment is a fraction of that
              month’s balance, for example 0.02 for 2%. The payment shrinks as the balance falls.
            </li>
            <li>
              <strong>Custom</strong>: a fixed monthly amount with no term.
            </li>
          </ul>
          <Callout kind="entry">
            <p>
              Enter the loan as it stands at the plan start: the current balance and the months
              left, not the original amount and term. A loan can’t start in a future year.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "amortization",
      title: "How each payment is split",
      body: (
        <>
          <Formula
            result="Level monthly payment"
            note="r is the annual rate ÷ 12 and n is the months remaining. Used for a Fixed loan when you enter a term but no payment. With a 0% rate, it is the balance divided by the number of months."
          >
            <V>Balance</V>
            <Op>×</Op>
            <Frac
              num={
                <>
                  r × (1 + r)<sup>n</sup>
                </>
              }
              den={
                <>
                  (1 + r)<sup>n</sup> − 1
                </>
              }
            />
          </Formula>
          <Ledger
            title="Example: $300,000 at 6% over 360 months, first month"
            rows={[
              { label: "Monthly payment", value: 1798.65, format: "usd_cents" },
              { op: "−", label: "Interest: $300,000 × 6% ÷ 12", value: 1500, format: "usd_cents" },
              { op: "=", label: "Principal repaid", value: 298.65, format: "usd_cents" },
            ]}
          />
          <p>
            Interest is charged on the balance that remains, so each payment leaves a slightly
            smaller balance and next month’s interest is a little lower. The payment stays the same,
            so more of it goes to principal each month. Early on, most of the payment is interest.
            Near the end, almost all of it is principal.
          </p>
          <Figure
            title="Interest and principal paid each year on a $300,000, 6%, 30-year mortgage"
            caption="The yearly total is $21,584 throughout ($1,798.65 × 12)."
            wide
            table={{
              columns: [
                { key: "year", label: "Loan year" },
                { key: "interest", label: "Interest", format: "usd" },
                { key: "principal", label: "Principal", format: "usd" },
              ],
              rows: loanYears.map((year, i) => ({
                year,
                interest: interestByYear[i],
                principal: principalByYear[i],
              })),
            }}
          >
            <BarChart
              label="Stacked yearly interest and principal: interest falls from $17,900 in year 1 to $685 in year 30 as principal rises from $3,684 to $20,898"
              categories={loanYears}
              series={[
                { id: "interest", label: "Interest", color: "orange", values: interestByYear },
                { id: "principal", label: "Principal", color: "cyan", values: principalByYear },
              ]}
            />
          </Figure>
          <p>
            If a payment is smaller than the month’s interest, the unpaid interest is added to the
            balance, and the debt grows. Only the payment itself counts as money spent. If the plan
            starts partway through a year, the first year includes only the remaining months.
          </p>
        </>
      ),
    },
    {
      id: "interest-methods",
      title: "Interest methods",
      body: (
        <>
          <p>
            <strong>Interest method</strong> sets how interest accrues. Payments, the payoff date
            and the interest paid all follow it.
          </p>
          <ul>
            <li>
              <strong>Monthly amortization</strong> (the default): interest is one-twelfth of the
              annual rate on the balance each month. If a payment doesn’t cover the month’s
              interest, the unpaid part is added to the balance and earns interest.
            </li>
            <li>
              <strong>Simple interest on principal</strong>: interest is one-twelfth of the annual
              rate on the principal only. Unpaid interest is still owed and counts as debt, but it
              never earns interest; each payment covers it before any principal. When payments
              always cover the interest, the schedule matches monthly amortization.
            </li>
            <li>
              <strong>Daily accrual (actual/365)</strong>: interest compounds every day at the
              annual rate ÷ 365 over each calendar month’s actual days, so a 31-day month costs more
              than February. A Fixed loan entered with a term gets the level payment for an average
              month of daily compounding, which is slightly higher than the monthly-amortization
              payment.
            </li>
          </ul>
          <Ledger
            title="Example: $10,000 at 12% with a $50 monthly payment, first year"
            rows={[
              { label: "Interest on principal: $10,000 × 12% ÷ 12 × 12 months", value: 1200 },
              { op: "−", label: "Payments: $50 × 12", value: 600 },
              {
                op: "=",
                label: "Unpaid simple interest owed at year end",
                value: 600,
                detail:
                  "The principal stays $10,000; with monthly amortization the unpaid interest would compound into the balance instead.",
              },
            ]}
          />
        </>
      ),
    },
    {
      id: "repeating-loans",
      title: "Repeating a loan",
      body: (
        <>
          <p>
            A loan you take out again and again, such as a car loan every 7 years, can repeat. Set{" "}
            <strong>Take it again every (years)</strong> under <strong>Repeat this loan</strong>. In
            January of every that many years after the plan start, CoastMath adds a new loan with
            the same balance, payment, extra payment, rate, interest method and offset account, in
            today’s dollars grown with inflation to that year. Each repeat is a separate loan, so it
            can overlap the one before it if that loan is not yet paid off.
          </p>
          <p>
            Repeats stop after the <strong>Last repeat year</strong> or once the{" "}
            <strong>Stop repeating at milestone</strong> milestone is reached; a milestone reached
            later in a year still lets that January’s repeat start. Without either, the loan repeats
            until the plan ends.
          </p>
          <Callout kind="boundary">
            <p>
              Repeats don’t carry the original loan’s linked property, payoff milestone or
              forgiveness. Only the money owed and its payments are modeled; the car or other
              purchase itself is not.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "extra-payments",
      title: "Extra payments",
      body: (
        <>
          <p>
            <strong>Extra payment ($/year, spread monthly)</strong> is an annual amount. CoastMath
            divides it by 12 and adds it to every monthly payment, so all of it goes to principal.
            The loan ends sooner and less interest is charged. After the last payment, the money
            that went to the loan becomes surplus, which your <HelpLink to="savings-rules" /> direct
            into accounts.
          </p>
          <Ledger
            title="Example: the same mortgage with $6,000 a year extra ($500 a month)"
            rows={[
              {
                label: "Total interest, scheduled payments only",
                value: 347516,
                detail: "The 30-year schedule",
              },
              {
                op: "−",
                label: "Total interest with the extra payment",
                value: 187220,
                detail: "Paid off after 17 years and 8 months",
              },
              { op: "=", label: "Interest avoided", value: 160296 },
            ]}
          />
        </>
      ),
    },
    {
      id: "paying-off-early",
      title: "Paying a loan off early",
      body: (
        <>
          <p>
            A <strong>Payoff milestone</strong> pays the loan off in the month that milestone takes
            effect. Regular payments continue until that month. Then the remaining balance is paid
            as a lump sum, and no further payments are made. The lump sum is essential spending: it
            is paid from that year’s income first, then from withdrawals in your withdrawal order.
            You can’t choose a separate source account for it.
          </p>
          <p>
            The month depends on the milestone’s type (see{" "}
            <HelpLink to="milestones#when-in-the-year" />
            ):
          </p>
          <ul>
            <li>
              <strong>Age</strong> milestones take effect in your birth month.
            </li>
            <li>
              <strong>Date</strong> milestones take effect in the month of their date.
            </li>
            <li>
              <strong>Net-worth and financial independence</strong> milestones take effect in
              January. With one of these, CoastMath pays off the whole balance at the start of the
              year, with no regular payments.
            </li>
          </ul>
          <Ledger
            title="Example: the $300,000 mortgage paid off with a July 2028 date milestone (plan starts January 2026)"
            rows={[
              {
                label: "Six scheduled payments, January–June",
                value: 10791.9,
                format: "usd_cents",
                detail: "$8,746.73 interest and $2,045.17 principal",
              },
              { op: "+", label: "Balance paid off in July", value: 290359.57, format: "usd_cents" },
              { op: "=", label: "Loan payments in 2028", value: 301151.47, format: "usd_cents" },
            ]}
            note="The payoff year shows one large loan payment. From 2029 on, the loan has no payments."
          />
          <p>
            Selling a property also pays off every loan linked to it; see{" "}
            <HelpLink to="selling-a-home#proceeds" />.
          </p>
        </>
      ),
    },
    {
      id: "debt-forgiveness",
      title: "Debt forgiveness",
      body: (
        <>
          <p>
            A lender can cancel part or all of a loan. On the loan’s form, choose{" "}
            <strong>Part or all of this loan is forgiven once</strong>, then pick a calendar year or
            a milestone. Leave <strong>Amount forgiven</strong> blank to forgive whatever balance
            remains, including unpaid simple interest, or enter a smaller amount. The event runs
            once, at the start of that year. No cash arrives: the balance simply drops, and later
            payments and interest follow the lower balance.
          </p>
          <p>
            Forgiven debt is taxable income by default, added to that year’s ordinary income. An
            exclusion applies only when you declare one: choose{" "}
            <strong>I declare an exclusion</strong>, pick the basis and, optionally, the excluded
            amount. CoastMath records what you declare. It does not decide whether you qualify, so
            confirm an exclusion with a tax professional first.
          </p>
          <Ledger
            title="Example: $40,000 forgiven in a single year"
            rows={[
              { label: "Balance forgiven", value: 40000 },
              { op: "−", label: "Amount you declare excluded", value: 15000 },
              { op: "=", label: "Added to that year’s ordinary income", value: 25000 },
            ]}
            note="With the default treatment and no exclusion, the whole $40,000 is added to income."
          />
          <ul>
            <li>
              A milestone that is already reached when the plan starts, or never reached, does not
              trigger forgiveness. A start-of-plan warning says so.
            </li>
            <li>
              If the loan is already paid off, or the forgiveness year is before the plan starts,
              nothing happens.
            </li>
            <li>
              Forgiven interest is taxed with the forgiven principal; the exclusion for interest
              that would have been deductible isn’t modeled.
            </li>
          </ul>
        </>
      ),
    },
    {
      id: "offset-accounts",
      title: "Offset accounts",
      body: (
        <>
          <p>
            If you choose an <strong>Offset account</strong>, interest is charged only on the part
            of the loan balance that exceeds that account’s balance. The account keeps its money.
            Because the payment stays the same while the interest falls, more of each payment goes
            to principal. If the account holds at least as much as you owe, no interest is charged.
          </p>
          <p>
            CoastMath uses one offset balance for the whole year. That balance includes the year’s
            investment growth but not the surplus saved into the account that year.
          </p>
        </>
      ),
    },
    {
      id: "interest-and-taxes",
      title: "Mortgage interest and taxes",
      body: (
        <>
          <p>
            Interest on a loan whose <strong>Linked real asset</strong> is marked Primary residence
            counts as mortgage interest. You get a deduction for it only if you itemize (see{" "}
            <HelpLink to="itemized-deductions" />
            ). Interest on any other loan is never deducted: a second-home mortgage, a car loan, a
            student loan or unsecured debt. The deduction counts only interest that was actually
            paid. Interest added to the balance isn’t included.
          </p>
          <Callout kind="boundary">
            <p>
              CoastMath deducts all interest on a primary-residence loan and doesn’t apply the
              acquisition-debt limit ($750,000, or $375,000 married filing separately). It can’t
              tell when a loan was taken out, what it paid for or whether it was refinanced.
              Whenever a primary-residence loan charges interest, the projection shows a warning
              that federal tax may be understated.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "reading-the-results",
      title: "Where loans show up",
      body: (
        <>
          <p>
            Each year’s payments appear in the cash-flow view as one essential expense per loan,
            under the loan’s name. In net worth, the remaining balance is subtracted.{" "}
            <strong>Show amortization schedule</strong> lists each loan year from the plan start.
          </p>
          <Symptoms
            rows={[
              {
                symptom: "The schedule doesn’t match the projection.",
                check:
                  "Does the loan have an offset account, a payoff milestone or a linked property that sells? Does the plan start partway through a year?",
                next: "The schedule uses only the saved balance, rate, payment and extra payment, over full years. The projection includes the other items.",
              },
              {
                symptom: "A 30-year loan shows a year 31 with a few dollars.",
                check: "Was the payment calculated from the term?",
                next: "The saved payment is rounded to the cent, so a tiny balance remains for one month. Enter the payment rounded up to remove it.",
              },
              {
                symptom: "The balance grows.",
                check: "Is the payment less than a month’s interest?",
                next: "Unpaid interest is added to the balance. Raise the payment.",
              },
              {
                symptom: "The loan continues after the home is sold.",
                check: "Is the loan linked to that property?",
                next: "Set Linked real asset.",
              },
            ]}
          />
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
                <strong>Missed payments.</strong> CoastMath assumes every scheduled payment is made.
                If a year can’t fund its payments, the gap is recorded as unfunded spending and the
                plan fails. Loan balances after that point still assume the payments were made.
              </li>
              <li>
                <strong>Loans that start later.</strong> Apart from repeats of a loan you already
                have, refinances, new mortgages and draws on a home equity line of credit can’t be
                entered with a future start. To model a refinance, pay the old loan off with a
                payoff milestone and add the new payment as an expense starting at the same
                milestone. Interest paid through such an expense isn’t deducted.
              </li>
              <li>
                <strong>Loan terms beyond the basics.</strong> Adjustable rates, escrow, mortgage
                insurance, balloon payments and deferment periods aren’t modeled. Enter property tax
                and insurance on the property itself.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
  ],
};
export default article;

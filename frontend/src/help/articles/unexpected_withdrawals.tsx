import type { Article } from "../help_types";
import { Callout, HelpLink, Symptoms, UIPath } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        A withdrawal appears whenever a year’s outflows exceed its cash inflows, or when something
        is set to be paid straight from an account. Outflows include taxes, payroll contributions,
        loan payments, property costs and health coverage as well as your expenses, so a year can
        draw on savings while you’re still working.
      </p>
      <p>
        Start with the year’s cash flow: select the year on <UIPath steps={["Overview"]} /> and
        compare Income, Taxes and Spending with Net cash flow. A negative net cash flow is covered
        by withdrawals in your drawdown order.
      </p>
    </>
  ),
  sections: [
    {
      id: "likely-causes",
      title: "Likely causes, most common first",
      body: (
        <>
          <h3>Spending plus taxes is more than take-home pay</h3>
          <p>
            Tax on the year’s income is settled in the same year, so withholding you enter changes
            timing, not the total. If Spending plus Taxes exceeds Income, the difference is
            withdrawn, starting with the first account in your order. When that account is checking
            or savings, the “withdrawal” is simply cash you saved earlier being spent.
          </p>
          <h3>A one-time or recurring expense lands in that year</h3>
          <p>
            Expenses tied to a milestone, a start or end month, or a recurrence every few years can
            push a single year negative. So can a loan paid off at a milestone, which pays the
            remaining balance that year.
          </p>
          <h3>An expense is paid from a specific account</h3>
          <p>
            An expense with Fund from a specific account set is withdrawn from those accounts every
            year it’s active, even in a year with a surplus. See <HelpLink to="withdrawal-order" />.
          </p>
          <h3>Payroll contributions leave too little pay</h3>
          <p>
            401(k) deferrals and payroll HSA contributions come out of pay before spending. If
            what’s left doesn’t cover spending, the gap is withdrawn, which in effect funds the
            contributions from savings. Savings rules that use surplus never cause a withdrawal;
            they fund only what is left over.
          </p>
          <h3>A tax bill from a conversion, gain harvest or withdrawal</h3>
          <p>
            Roth conversions and gain harvesting add taxable income without adding cash, so their
            tax is paid from the year’s cash flow. Withdrawals from traditional accounts and
            brokerage gains add tax too, which is paid by withdrawing a little more. Early
            withdrawals also carry the additional tax described in{" "}
            <HelpLink to="early-withdrawals" />.
          </p>
          <h3>Marketplace credit is repaid at reconciliation</h3>
          <p>
            When Marketplace coverage is on, the advance premium credit is based on an estimate of
            income. If the year’s final income is higher, including income from the withdrawals
            themselves, part of the credit is repaid with that year’s tax, and the repayment is
            withdrawn too. See <HelpLink to="marketplace-health-coverage" />.
          </p>
          <h3>Gifts and distributions paid from an account</h3>
          <p>
            Charitable gifts and qualified charitable distributions funded from an account are
            listed with the year’s withdrawals. Required distributions and 72(t) payments are
            counted as income, not withdrawals, but their tax is still due; see{" "}
            <HelpLink to="required-minimum-distributions" /> and <HelpLink to="sepp-72t" />.
          </p>
          <h3>An earlier shortfall is being repaid</h3>
          <p>
            If a past year couldn’t be fully funded, later years withdraw to pay that amount back
            once they have cash or balances to cover it. See <HelpLink to="unfunded-expenses" />.
          </p>
        </>
      ),
    },
    {
      id: "symptoms",
      title: "Symptoms and where to check",
      body: (
        <>
          <Symptoms
            rows={[
              {
                symptom: "Withdrawals while you’re still working",
                check: "Overview year details: Income vs Taxes and Spending",
                next: "The gap between them is the withdrawal; spending, contributions or income that year change it",
              },
              {
                symptom: "A withdrawal from checking or savings every year",
                check: "Net cash flow for those years",
                next: "That is saved cash being spent; nothing is taxed",
              },
              {
                symptom: "A withdrawal in a year with a surplus",
                check: "Expenses with Fund from a specific account",
                next: "Set the expense back to General cash flow (default) if it should be paid from income",
              },
              {
                symptom: "A spike in one year",
                check: "Expenses and debts with milestones, months or recurrence",
                next: "Confirm the timing and amount",
              },
              {
                symptom: "Withdrawals rise in a conversion year",
                check: "Tax tools › Annual tax breakdown",
                next: "The conversion’s tax is paid from cash flow; see Roth conversions",
              },
              {
                symptom: "Withdrawals rise in a Marketplace year",
                check: "Health coverage settings and the year’s taxes",
                next: "Credit repayment is added to the tax bill",
              },
              {
                symptom: "An “early withdrawal” warning",
                check: "Drawdown order: is a traditional account first?",
                next: "Withdrawals before 59½ from traditional accounts carry the additional tax",
              },
              {
                symptom: "An account you excluded is being drawn",
                check: "Expenses and gifts funded from that account",
                next: "Those draw even when the account isn’t in the drawdown order",
              },
            ]}
          />
          <Callout kind="where">
            <p>
              Which accounts paid is shown in <HelpLink to="cash-flow-view" />. The order is in{" "}
              <UIPath steps={["Drawdown order"]} />; a traditional account first shows the warning
              “Traditional account first: early withdrawals may incur a penalty.”
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "related-calculations",
      title: "How each cause is calculated",
      body: (
        <>
          <ul>
            <li>
              The order, gross-up and tax settlement: <HelpLink to="withdrawal-order" />
            </li>
            <li>
              The additional tax and Roth ordering: <HelpLink to="early-withdrawals" />
            </li>
            <li>
              Payroll contributions: <HelpLink to="contributions-and-employer-match" /> and{" "}
              <HelpLink to="savings-rules" />
            </li>
            <li>
              Conversion taxes: <HelpLink to="roth-conversions" />
            </li>
            <li>
              When tax is paid: <HelpLink to="tax-payments-and-settlement" />
            </li>
          </ul>
        </>
      ),
    },
  ],
};

export default article;

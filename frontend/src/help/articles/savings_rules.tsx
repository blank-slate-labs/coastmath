import type { Article } from "../help_types";
import { Callout, Figure, HelpLink, Ledger, Steps, UIPath } from "../help_kit";
import { Waterfall } from "../help_charts";

const article: Article = {
  intro: (
    <>
      <p>
        Surplus is what’s left in a year after payroll deductions, taxes withheld, spending and loan
        payments. Your allocation rules send it to accounts from the top of the list down; each rule
        takes what it asks for, up to its limits, and passes the rest on. Whatever no rule takes
        goes to your first checking account, then savings, then taxable brokerage.
      </p>
      <p>
        Rules run only in years with a surplus. In a shortfall year, money comes out of accounts
        instead; see <HelpLink to="withdrawal-order" />. A rule set to{" "}
        <em>Withdraw if surplus is short</em> is the exception: it runs first and draws from your
        accounts when the surplus is short (see <HelpLink to="savings-rules#withdraw-if-short" />
        ).
      </p>
    </>
  ),
  sections: [
    {
      id: "add-a-rule",
      title: "Add a rule",
      body: (
        <>
          <Steps>
            <li>
              Open <UIPath steps={["Income allocation"]} /> and, under <em>After spending</em>,
              choose <em>Add allocation</em>.
            </li>
            <li>
              Pick the <em>Destination account</em>. Any account except a 401(k) can receive
              surplus; 401(k)s are funded from pay (see{" "}
              <HelpLink to="contributions-and-employer-match" />
              ).
            </li>
            <li>
              Choose how much in <em>Allocate</em>: <em>Percentage of surplus</em>,{" "}
              <em>Cash amount per year</em> or <em>Remaining surplus</em>.
            </li>
            <li>
              Optionally set <em>Annual maximum ($; optional)</em> and{" "}
              <em>Stop at account balance ($; optional)</em>.
            </li>
            <li>
              Order the rules with <em>Move up</em> and <em>Move down</em>, then choose{" "}
              <em>Save allocation</em>. The projection recalculates.
            </li>
          </Steps>
        </>
      ),
    },
    {
      id: "how-much-a-rule-takes",
      title: "How much each rule takes",
      body: (
        <>
          <ul>
            <li>
              <strong>Percentage of surplus</strong> is a share of the year’s whole surplus, before
              any rule runs. Two rules at 60% and 40% split the same amount. Percentages over 100%
              in total are allowed; earlier rules are filled first.
            </li>
            <li>
              <strong>Cash amount per year</strong> is a fixed dollar amount, prorated in a partial
              first year.
            </li>
            <li>
              <strong>Remaining surplus</strong> is everything still unallocated when the rule is
              reached.
            </li>
          </ul>
          <p>
            A rule deposits the smallest of: what it asks for, the surplus still available, its
            annual maximum, the owner’s remaining legal contribution room, and the gap to its
            balance target. Money a limit blocks stays available to the next rule.
          </p>
          <Figure
            title="A $30,000 surplus through three rules"
            caption="Rule 1: 20% to an emergency fund at $18,000, stopping at $20,000. Rule 2: remaining surplus to a Roth IRA, capped by the $7,500 limit for someone under 50 with enough earned income. Rule 3: $12,000 per year to brokerage. The last $8,500 goes to checking."
            table={{
              columns: [
                { key: "step", label: "Step" },
                { key: "requested", label: "Requested", format: "usd" },
                { key: "deposited", label: "Deposited", format: "usd" },
              ],
              rows: [
                { step: "1. Emergency fund", requested: 6000, deposited: 2000 },
                { step: "2. Roth IRA", requested: 28000, deposited: 7500 },
                { step: "3. Brokerage", requested: 12000, deposited: 12000 },
                { step: "Leftover to Checking", requested: 8500, deposited: 8500 },
              ],
            }}
          >
            <Waterfall
              label="Surplus of $30,000 allocated to four destinations"
              steps={[
                { label: "Surplus", value: 30000, color: "blue" },
                { label: "Emergency fund", value: -2000, color: "cyan" },
                { label: "Roth IRA", value: -7500, color: "cyan" },
                { label: "Brokerage", value: -12000, color: "cyan" },
                { label: "Checking (leftover)", value: -8500, color: "gray" },
              ]}
            />
          </Figure>
          <Callout kind="entry">
            <p>
              Dollar amounts, annual maximums and balance targets are nominal: they don’t rise with
              inflation, so a fixed amount buys less each year. A balance target is an absolute
              balance, not an annual amount.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "debt-payments",
      title: "Pay down a loan with surplus",
      body: (
        <>
          <p>
            With at least one loan in the plan, <em>Add debt payment</em> creates a rule that sends
            surplus to that loan. Choose the <em>Loan to pay down</em>. The rule pays up to the
            loan’s remaining principal, after the rules above it, and never more than the balance.
            An <em>Annual maximum</em> or a percentage still limits it.
          </p>
          <ul>
            <li>
              The payment comes out of cash and lowers principal once. It is in addition to the
              loan’s scheduled payment, and interest keeps accruing on what remains.
            </li>
            <li>
              Once the loan is paid off, the rule reports that it is already paid off and passes the
              surplus on.
            </li>
            <li>
              The extra payment is not tax-deductible. Mortgage and other interest deductions follow
              the lower balance in later years.
            </li>
          </ul>
          <Callout kind="entry">
            <p>
              A debt rule has no balance target, because the loan’s own balance is the limit.
              Duplicating a plan carries the rule over to the copied loan.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "withdraw-if-short",
      title: "Fund a rule even when surplus is short",
      body: (
        <>
          <p>
            Contribution, payroll and debt payment rules use only surplus by default, as described
            above. With <em>Withdraw if surplus is short</em> ticked, the rule runs before every
            other rule after spending, in list order among the withdraw-if-short rules, and keeps it
            funded when the surplus falls short.
          </p>
          <ul>
            <li>
              The rule first takes surplus. Whatever it still needs is withdrawn through your
              withdrawal order, after the year’s spending shortfall has been covered, so a goal
              never takes money your spending needs.
            </li>
            <li>
              It never withdraws from its own destination, or from the same person’s accounts that
              share its contribution limit, such as a traditional IRA to fund a Roth IRA. Locked
              accounts are skipped and a cash reserve’s protected balance is left alone;
              early-withdrawal penalties and Roth ordering apply as they do to any withdrawal.
            </li>
            <li>
              Tax on the withdrawal is settled in the same year and, like any tax bill, paid from
              your withdrawal order.
            </li>
            <li>
              With <em>Remaining surplus</em>, a withdraw-if-short rule asks for its tightest limit:
              annual maximum, contribution limit, balance target or loan balance. Without any of
              these it takes only the surplus left.
            </li>
          </ul>
          <p>
            Withdraw if surplus is short removes only the need for surplus. Contribution limits, the
            earned-income requirement for IRAs, the Roth IRA income phase-out, plan limits, annual
            maximums, balance targets and milestone windows still apply. An IRA rule for someone
            with no earned income still contributes nothing.
          </p>
          <p>
            Withdrawals can raise your modified AGI, so the Roth IRA income limit is checked again
            after the year’s spending withdrawals and after the withdrawal for the rule itself. If
            that withdrawal lowers the limit, only the part still allowed goes into the Roth IRA and
            the rest of the cash stays in your cash account. CoastMath checks once rather than
            searching for the smaller withdrawal that might have allowed a little more.
          </p>
          <Ledger
            title="Example: $3,000 withdraw-if-short rule, $2,000 in savings, no surplus"
            rows={[
              { label: "Amount the rule asks for", value: 3000 },
              { op: "−", label: "Withdrawn from savings", value: 2000 },
              { op: "=", label: "Rule funding shortfall", value: 1000 },
            ]}
          />
          <p>
            What neither the surplus nor your accounts can cover is reported as the year’s{" "}
            <em>Rule funding shortfall</em> in the year details and the annual report, and the
            rule’s entry says it could not be fully funded. A shortfall is not unfunded spending: it
            doesn’t reduce net worth and doesn’t count as a plan failure, in a single projection or
            in Monte Carlo.
          </p>
          <p>
            Payroll rules already come out of pay before spending, so their deferrals are funded
            either way; pay and contribution limits still cap them, and a shortfall in spending is
            then withdrawn from your accounts.
          </p>
          <Callout kind="entry">
            <p>
              Conversions, gain harvests and transfers move money from their own source account, so
              they have no funding choice.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "reduce-employer-contribution",
      title: "Prorate the employer contribution",
      body: (
        <>
          <p>
            A <em>Payroll percent of income</em> rule that doesn’t withdraw if surplus is short and
            uses a flat employer rate can set{" "}
            <em>Prorate employer contribution if the deferral is cut</em>. When rules above it leave
            too little pay for the deferral you elected, the employer amount is cut in the same
            proportion as the deferral. A deferral cut by a contribution limit does not cut the
            employer amount. A matching formula already follows the actual deferral, so the option
            changes nothing there.
          </p>
        </>
      ),
    },
    {
      id: "transfers",
      title: "Move money between accounts",
      body: (
        <>
          <p>
            A transfer rule moves money from one account to another instead of spending it. It can
            take money from checking, savings, brokerage or crypto, or from a retirement account,
            into checking, savings or brokerage. Selling taxable holdings realizes the gain. A
            retirement account distribution counts as income, and the 10% early-withdrawal penalty
            applies where it does. Any withholding is subtracted, and the destination receives the
            net amount.
          </p>
          <ul>
            <li>
              A traditional retirement account can roll over to another traditional account with the
              same owner. A rollover is not taxed and not penalized.
            </li>
            <li>
              Moving traditional money into a Roth account is a conversion; use{" "}
              <HelpLink to="roth-conversions" />.
            </li>
            <li>
              Money cannot be transferred into a Roth IRA, HSA or 529 account. Those accounts take
              contributions, which keep their yearly limits.
            </li>
            <li>
              Inherited accounts cannot be rolled over, and a Roth account can distribute only to
              cash or brokerage.
            </li>
          </ul>
          <p>Combinations that are not allowed are explained in the editor and are not saved.</p>
          <p>
            <strong>Transfer timing</strong> is <strong>Once a year</strong> by default: the year’s
            amount moves after the year’s growth. <strong>Monthly</strong> moves one-twelfth of the
            annual maximum at the end of each month the rule is active, counting only the months
            after a start milestone and before an end milestone in the years they are reached. Money
            moved earlier in the year stops growing in the source and grows in the destination for
            the rest of the year. A monthly rule without a maximum moves the whole balance at the
            end of its first active month.
          </p>
        </>
      ),
    },
    {
      id: "leftover-surplus",
      title: "Where unallocated surplus goes",
      body: (
        <>
          <p>
            Without a final <em>Remaining surplus</em> rule, leftover money goes to the first
            Checking account, else the first Savings account, else the first Taxable Brokerage
            account. With none of these, CoastMath keeps it as <em>Unallocated cash</em>, which is
            spent first in a later shortfall. The editor names the current destination and the first
            year’s leftover amount.
          </p>
          <Callout kind="entry">
            <p>
              Checking and savings earn nothing, so surplus left to pile up there doesn’t grow. Add
              a last <em>Remaining surplus</em> rule to send it somewhere invested.
            </p>
          </Callout>
          <p>
            If the year’s tax settles as a refund, the refund goes back through your{" "}
            <em>Cash amount per year</em> and <em>Remaining surplus</em> rules that still have room,
            then to the default destination.
          </p>
        </>
      ),
    },
    {
      id: "tax-effects",
      title: "What changes when you save",
      body: (
        <>
          <p>
            Surplus sent to a Traditional IRA or an HSA is deducted from that year’s taxable income.
            Deposits to a taxable brokerage account add cost basis. Roth IRA rules respect the
            income phase-out and earned-income limit, and a Roth IRA rule can be marked{" "}
            <em>Backdoor Roth</em> (see <HelpLink to="backdoor-roth" />
            ). How each account treats the money later is in <HelpLink to="account-types" />.
          </p>
        </>
      ),
    },
    {
      id: "why-a-rule-got-nothing",
      title: "When a rule gets less than it asked for",
      body: (
        <>
          <p>
            The cash-flow view’s <em>Surplus allocation</em> list shows what each rule received that
            year, what limited it, and why a rule got nothing: no surplus, earlier rules used it
            all, the contribution limit or income eligibility, no earned income, the account’s
            ownership, or its balance target. A withdraw-if-short rule that ran short says so even
            when it got part of its amount. <em>Review rule</em> opens that rule. See{" "}
            <HelpLink to="cash-flow-view" />.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Income allocation"]} /> also flags a rule that got nothing in the
              first year, with the same reason.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "conflicting-edits",
      title: "If the rules changed elsewhere",
      body: (
        <>
          <p>
            Saving replaces the whole list, including rules added from the tax tools. If the list
            was saved elsewhere since you started editing, for example in another tab, Save is
            blocked and <em>Review the latest saved rules</em> lists them. Choose{" "}
            <em>Keep my draft after reviewing these rules</em> or{" "}
            <em>Use latest rules and discard my draft</em>, then save. An unsaved draft survives a
            reload in the same browser tab.
          </p>
        </>
      ),
    },
  ],
};
export default article;

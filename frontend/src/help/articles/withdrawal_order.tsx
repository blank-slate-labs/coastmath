import type { Article } from "../help_types";
import { Callout, DataTable, Figure, Formula, HelpLink, Ledger, Op, UIPath, V } from "../help_kit";
import { Waterfall } from "../help_charts";

const article: Article = {
  intro: (
    <>
      <p>
        When a year’s income doesn’t cover its spending, taxes, loan payments and other outflows,
        CoastMath withdraws the difference from the accounts in your drawdown order, top to bottom,
        emptying each account before it moves to the next. Accounts that aren’t in the order are
        never used to cover a shortfall.
      </p>
      <p>
        Each withdrawal is sized so that what remains after any additional tax on it covers the gap.
        The income tax the withdrawals create is settled in the same year, by withdrawing more from
        the same order until the tax is paid.
      </p>
    </>
  ),
  sections: [
    {
      id: "default-order",
      title: "The default order and how to change it",
      body: (
        <>
          <p>
            You don’t have to set an order. Each account you add is placed into it by type, ahead of
            the first account whose type comes later in this list, so an order you’ve rearranged
            keeps its shape:
          </p>
          <DataTable
            caption="Where a new account is placed"
            columns={[
              { key: "rank", label: "Position" },
              { key: "types", label: "Account types" },
            ]}
            rows={[
              { rank: "1", types: "Checking, Savings" },
              { rank: "2", types: "Taxable Brokerage" },
              { rank: "3", types: "Traditional 401(k), Traditional IRA" },
              { rank: "4", types: "Roth 401(k), Roth IRA" },
              { rank: "5", types: "HSA" },
              { rank: "6", types: "Other" },
              { rank: "Not added", types: "529 Plan" },
            ]}
            note="Accounts of the same type keep the order in which you added them."
          />
          <Callout kind="where">
            <p>
              <UIPath steps={["Drawdown order"]} />. Drag an account to move it, remove it with ×,
              or add an account that isn’t listed. If a traditional account is first, the section
              warns that early withdrawals may incur a penalty.
            </p>
          </Callout>
          <Callout kind="entry">
            <p>
              Removing an account from the order is how you exclude it: it keeps growing and can
              still pay an expense you assign to it, but it never covers a general shortfall. An
              account in the order has no protected minimum; it is drawn to zero before the next one
              is touched.
            </p>
          </Callout>
          <p>
            If your plan has no checking, savings or brokerage account, surplus from earlier years
            is held as generated cash. That cash is always spent first, ahead of your saved order.
          </p>
        </>
      ),
    },
    {
      id: "what-a-withdrawal-costs",
      title: "What each withdrawal costs in tax",
      body: (
        <>
          <DataTable
            caption="How a withdrawal is taxed, by account type"
            columns={[
              { key: "type", label: "Account type" },
              { key: "tax", label: "Taxed as" },
            ]}
            rows={[
              { type: "Checking, Savings", tax: "Nothing" },
              {
                type: "Taxable Brokerage",
                tax: "The gain share of the sale, at long-term capital gains rates",
              },
              {
                type: "Traditional 401(k), Traditional IRA",
                tax: "Ordinary income, plus a 10% additional tax on the part of the year before the owner reaches 59½",
              },
              {
                type: "Roth 401(k), Roth IRA",
                tax: "Contributions first, then conversions, then earnings; only unqualified earnings are income",
              },
              {
                type: "HSA",
                tax: "Untaxed up to the year’s modeled medical costs; the rest is ordinary income, plus 20% before 65",
              },
              {
                type: "529 Plan",
                tax: "Untaxed up to the year’s qualified education expenses; beyond them, the earnings share is ordinary income plus 10%",
              },
              { type: "Other", tax: "Nothing" },
            ]}
          />
          <p>
            A brokerage sale realizes gain in proportion to the account’s unrealized gain, using
            average cost. All gains are treated as long-term.
          </p>
          <Formula result="Realized gain">
            <V>Amount sold</V>
            <Op>×</Op>
            <V>(1 − cost basis ÷ balance)</V>
          </Formula>
          <p>
            When a withdrawal carries an additional tax, it is grossed up so the amount left after
            that tax covers the gap. Income tax isn’t part of this gross-up; it is settled once the
            year’s income is known.
          </p>
          <Formula
            result="Withdrawal"
            note="The additional-tax rate is 10% for a traditional account before 59½, prorated when you reach 59½ during the year. Roth withdrawals are sized against their own ordering."
          >
            <V>Amount needed</V>
            <Op>÷</Op>
            <V>(1 − additional-tax rate)</V>
          </Formula>
          <p>
            Once the withdrawals are made, CoastMath recalculates the year’s tax on the final
            income. If the withdrawals raised it, the extra tax is funded by withdrawing more from
            the same order, which is recalculated again until the tax is paid. If they lowered it,
            the refund is saved by your savings rules.
          </p>
        </>
      ),
    },
    {
      id: "worked-example",
      title: "Worked example: an $80,000 year with no income",
      body: (
        <>
          <p>
            A single 62-year-old in 2026 spends $80,000 and has no income. The order is Checking
            ($10,000), Brokerage ($50,000, cost basis $30,000), Traditional IRA ($400,000), Roth
            IRA. No growth is assumed, so the arithmetic is visible.
          </p>
          <Figure
            title="Where the $80,000 comes from"
            caption="The brokerage sale realizes a $20,000 gain, taxed at 0% because taxable income stays within the 0% capital gains bracket. The IRA withdrawal pays its own income tax."
            table={{
              columns: [
                { key: "step", label: "Step" },
                { key: "amount", label: "Amount", format: "usd" },
              ],
              rows: [
                { step: "Checking", amount: 10000 },
                { step: "Brokerage", amount: 50000 },
                { step: "Traditional IRA", amount: 20433 },
                { step: "Income tax", amount: -433 },
                { step: "Spending covered", amount: 80000 },
              ],
            }}
          >
            <Waterfall
              label="Withdrawals by account, less income tax, equal spending covered"
              steps={[
                { label: "Checking", value: 10000, color: "cyan" },
                { label: "Brokerage", value: 50000, color: "cyan" },
                { label: "Traditional IRA", value: 20433, color: "cyan" },
                { label: "Income tax", value: -433, color: "orange" },
                { label: "Spending covered", value: 80000, color: "magenta", total: true },
              ]}
            />
          </Figure>
          <Ledger
            title="The IRA withdrawal settles its own tax"
            rows={[
              { label: "Still needed after cash and brokerage", value: 20000 },
              { label: "Traditional IRA withdrawal", value: 20433.33, format: "usd_cents" },
              { op: "−", label: "Standard deduction", value: 16100, detail: "Single filer, 2026" },
              { op: "=", label: "Taxable ordinary income", value: 4333.33, format: "usd_cents" },
              { op: "×", label: "Rate in the 10% bracket", value: 0.1, format: "pct", digits: 0 },
              {
                op: "=",
                label: "Income tax paid from the withdrawal",
                value: 433.33,
                format: "usd_cents",
              },
            ]}
            note="$20,433.33 − $433.33 = $20,000. At 57 the same year needs $22,987.50 from the IRA: $2,298.75 of additional tax and $688.75 of income tax."
          />
        </>
      ),
    },
    {
      id: "fill-a-tax-target",
      title: "Filling a tax target before following the order",
      body: (
        <>
          <p>
            With a tax target set and <strong>Fill the tax target first</strong> turned on, a year
            that needs withdrawals takes them in two passes. The first pass walks your order but
            only uses accounts whose withdrawals create taxable income: traditional accounts, where
            every dollar is ordinary income, and brokerage accounts with an unrealized gain, where
            the gain share of each sale counts. It takes from each only as much as keeps the year’s
            income within the target, measured on the final tax picture, so the extra taxable Social
            Security or lost deductions a withdrawal causes count too. The second pass funds
            whatever is still needed from your order exactly as above.
          </p>
          <p>
            Cash, Roth and HSA accounts, accounts that are locked, and accounts whose withdrawals
            would carry the early-withdrawal penalty that year are skipped in the first pass. The
            tax the withdrawals create is settled afterwards by the order, as usual.
          </p>
          <Ledger
            title="Example: the same $80,000 year with a 12% bracket target"
            rows={[
              { label: "Traditional IRA, first pass", value: 66500 },
              { op: "−", label: "Standard deduction", value: 16100, detail: "Single filer, 2026" },
              { op: "=", label: "Taxable income: the top of the 12% bracket", value: 50400 },
              { label: "Brokerage, second pass: rest of spending", value: 13500 },
              { op: "+", label: "Brokerage: federal income tax", value: 5800 },
              { op: "=", label: "Brokerage withdrawals", value: 19300 },
            ]}
            note="A single 62-year-old with no income, a brokerage account with no unrealized gain first in the order and a traditional IRA second. Without the target the whole year comes from the brokerage account and no tax is due; with it, $66,500 of the IRA is spent at 10% and 12% instead of waiting for later, larger required distributions."
          />
          <p>
            The target can be a federal bracket, a taxable income or MAGI amount in today’s dollars,
            a Medicare IRMAA tier, or a share of the poverty line in years with Marketplace
            coverage. Extra ceilings for the net investment income tax threshold, the first IRMAA
            tier and a poverty-line share in coverage years each also apply when checked; the
            tightest one sets the year’s room. The IRMAA ceilings use the ranges projected for two
            years later, the premium year that income sets, and apply once someone reaches 65 by
            then. Bracket and taxable income targets count capital gains and qualified dividends, so
            a brokerage sale’s gain uses the same room as IRA income.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "Tax target"]} /> sets the target and ceilings.{" "}
              <UIPath steps={["Drawdown order", "Fill the tax target first"]} /> turns on the first
              pass.
            </p>
          </Callout>
          <p>
            Roth conversion and gain harvest rules can share the same target; see{" "}
            <HelpLink to="roth-conversions#plan-tax-target" />. Harvests run before the withdrawals
            and conversions after them, so each uses the room the earlier ones left.
          </p>
        </>
      ),
    },
    {
      id: "cash-reserve",
      title: "Protecting a cash reserve",
      body: (
        <>
          <p>
            By default, checking and savings are spent in whatever place they hold in the order. If
            you want an emergency fund kept for last, turn on a cash reserve. Choose the checking or
            savings accounts that hold it and the amount to protect, in today’s dollars. The amount
            rises with inflation and cannot exceed what those accounts actually hold.
          </p>
          <p>
            With a reserve on, the normal order skips the protected part of those accounts. Balances
            above the reserve are spent as usual. Only when every other account in the order is
            empty, locked or otherwise unavailable does CoastMath spend the reserve, in the order
            you list the reserve accounts. Required distributions, specific funding sources and
            locks work as before, and a locked reserve account stays locked.
          </p>
          <Ledger
            title="Example: a $70,000 shortfall with a $20,000 reserve"
            rows={[
              {
                label: "Checking above the reserve",
                value: 10000,
                detail: "$30,000 balance less the $20,000 reserve",
              },
              { op: "+", label: "Brokerage, no unrealized gain", value: 50000 },
              {
                op: "+",
                label: "Reserve, last resort",
                value: 10000,
                detail: "Half of the protected $20,000",
              },
              { op: "=", label: "Shortfall covered", value: 70000 },
            ]}
            note="Checking first in the order, then brokerage. No other accounts, no growth and no tax on the sale."
          />
          <Callout kind="where">
            <p>
              <UIPath steps={["Tax tools", "Early withdrawals", "Cash reserve"]} />. With it off,
              nothing changes.
            </p>
          </Callout>
          <p>
            With <strong>Invest cash above the reserve each year</strong> also checked, CoastMath
            moves cash the reserve accounts hold above the reserve into your allocation rules at the
            end of each year, after spending and other rules are funded. The cash fills contribution
            rules in their order, up to what each still lacks for the year: its annual maximum,
            fixed amount and contribution limits. Percentage rules, debt payment rules and rules
            that pay into a reserve account don’t take part. Locked reserve accounts aren’t drawn.
            Moving the cash isn’t taxed; a deductible contribution it funds is deducted like any
            other, and the moves appear as transfers.
          </p>
        </>
      ),
    },
    {
      id: "specific-funding-sources",
      title: "Expenses paid from specific accounts",
      body: (
        <>
          <p>
            An expense can name the accounts that pay it. That expense is then withdrawn from those
            accounts every year it’s active, whether or not income that year would have covered it,
            and it is left out of the general shortfall. Tax treatment is the same as for any
            withdrawal from that account, except that HSA money spent this way is treated as a
            qualified medical expense.
          </p>
          <p>
            When you select several accounts, CoastMath uses them by account type, in the order
            those types first appear in your drawdown order, and within a type in the order you
            listed them. Types that aren’t in your drawdown order follow checking, savings,
            brokerage, HSA, traditional IRA, traditional 401(k), Roth IRA, Roth 401(k), 529 and
            other.
          </p>
          <Callout kind="where">
            <p>
              <UIPath
                steps={[
                  "Expenses",
                  "Advanced: growth, funding and timing",
                  "Fund from a specific account",
                ]}
              />
              . Leaving it at “General cash flow (default)” funds the expense from income and the
              drawdown order.
            </p>
          </Callout>
          <Callout kind="entry">
            <p>
              Selecting accounts restricts the expense to them. If they run out, the rest of that
              expense is unfunded and stays unfunded: it isn’t drawn from other accounts, and later
              years don’t repay it. Expenses saved before several accounts could be selected fall
              back to general cash flow until you change their selection; the form says which rule
              applies.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "withdrawal-locks",
      title: "Accounts you can’t withdraw from yet",
      body: (
        <>
          <p>
            Some money can’t be touched until later: deferred compensation paid only after you leave
            your employer, a workplace plan with no in-service withdrawals, a trust or lump sum
            available at a set age, or a CD that matures in a given year. Set{" "}
            <strong>Withdrawals available</strong> on the account to keep the projection from
            spending it early.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Accounts", "Edit", "Withdrawals available"]} />. Choose Any time (the
              default), From age, From milestone or From year. The account list shows the lock, such
              as “Locked until 62”.
            </p>
          </Callout>
          <DataTable
            caption="When a locked account opens"
            columns={[
              { key: "rule", label: "Available" },
              { key: "opens", label: "First year withdrawals are allowed" },
            ]}
            rows={[
              {
                rule: "From age",
                opens:
                  "The year the owner is at or past that age for more than half the year, the same rule used for 59½. A partner’s account uses the partner’s age; a joint account uses yours.",
              },
              { rule: "From milestone", opens: "The year the milestone is reached" },
              { rule: "From year", opens: "January of that year" },
            ]}
            note="Born in January to July, a lock at 62 opens the year you turn 62; born in August to December, it opens the year after. Without a birth month, July is assumed."
          />
          <p>
            While an account is locked, it is skipped in the drawdown order and can’t pay an expense
            assigned to it, a transfer, a Roth conversion, a gain harvest, a 72(t) payment, a
            charitable gift or a qualified charitable distribution beyond its required distribution.
            Contributions and growth continue as usual. From the year it opens, it behaves exactly
            like any other account.
          </p>
          <Callout kind="entry">
            <p>
              Required minimum distributions still come out of a locked account. The legal
              requirement overrides the lock.
            </p>
          </Callout>
          <p>
            A locked balance counts toward net worth but isn’t liquid. If the other accounts run out
            first, the gap is unfunded exactly as described below, and it is repaid once the account
            opens. In Monte Carlo, a trial fails under the liquid-assets test when the accounts you
            can withdraw from reach zero, even if a locked account still holds money. Financial
            independence milestones measured on liquid net worth also leave locked balances out.
          </p>
          <p>
            Household accounts are shared by your plans, but milestones belong to one plan. In a
            plan that doesn’t have the lock’s milestone, the account is available any time and the
            projection shows a warning. A milestone used by a lock can’t be deleted until you change
            the lock.
          </p>
        </>
      ),
    },
    {
      id: "when-accounts-run-out",
      title: "When the accounts run out",
      body: (
        <>
          <p>
            If every account in the order is empty and a gap remains, the remainder is recorded as
            unfunded and the plan fails in that year. Property marked Auto-liquidate on depletion is
            sold first, into its liquidation target account, before a gap is left unfunded.
          </p>
          <p>
            An unfunded amount from general cash flow carries forward as a debt that reduces net
            worth. Each later year tries to repay it from the drawdown order; the plan’s first
            failure year still stands. See <HelpLink to="unfunded-expenses" />.
          </p>
          <Callout kind="where">
            <p>
              Select a year on <UIPath steps={["Overview"]} />: the year details list Withdrawals,
              the withdrawal rate and any Early withdrawal penalties.{" "}
              <HelpLink to="cash-flow-view" /> shows which accounts paid.
            </p>
          </Callout>
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
                Proportional withdrawals across several accounts and per-account floors. Each
                account is emptied in turn, except the reserve described above.
              </li>
              <li>
                A separate order per partner, or an order that changes over time. For bracket-based
                withdrawals, use a tax target (above); for bracket-based moves between accounts, use{" "}
                <HelpLink to="roth-conversions" /> rules.
              </li>
              <li>
                Tax withholding on withdrawals and estimated payments. Tax is settled within the
                year it arises.
              </li>
              <li>
                Penalty exceptions other than the ones CoastMath applies; see{" "}
                <HelpLink to="early-withdrawals" />.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
  ],
};

export default article;

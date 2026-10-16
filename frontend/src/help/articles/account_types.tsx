import type { Article } from "../help_types";
import { Callout, DataTable, HelpLink, Ledger, Pair, UIPath } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        An account’s type decides three things in every projection year: whether the balance earns
        investment returns, whether money going in reduces taxable income, and how much of a
        withdrawal is taxed. Owner matters too, because the owner’s age sets catch-up limits, the
        age-59½ penalty line and required distributions.
      </p>
      <p>
        Checking and savings hold cash at 0%. Every other type grows at your investment assumptions,
        and only a taxable brokerage account pays tax on dividends each year.
      </p>
    </>
  ),
  sections: [
    {
      id: "at-a-glance",
      title: "Each account type at a glance",
      body: (
        <>
          <DataTable
            caption="How CoastMath treats each account type"
            columns={[
              { key: "type", label: "Account type" },
              { key: "growth", label: "Growth" },
              { key: "going_in", label: "Money going in" },
              { key: "coming_out", label: "Money coming out" },
            ]}
            rows={[
              {
                type: "Checking, Savings",
                growth: "None (0%)",
                going_in: "No deduction",
                coming_out: "Untaxed",
              },
              {
                type: "Traditional 401(k), Traditional 403(b)",
                growth: "Investment return; dividends reinvested untaxed",
                going_in: "Payroll only; excluded from taxable wages",
                coming_out:
                  "Ordinary income; 10% additional tax before 59½; required distributions",
              },
              {
                type: "Roth 401(k), Roth 403(b)",
                growth: "Investment return, untaxed",
                going_in: "Payroll only; no deduction",
                coming_out: "Untaxed once qualified; otherwise earnings share taxed",
              },
              {
                type: "Traditional 457(b)",
                growth: "Investment return; dividends reinvested untaxed",
                going_in: "Payroll only; excluded from taxable wages; its own limit",
                coming_out: "Ordinary income; no 10% additional tax; required distributions",
              },
              {
                type: "Roth 457(b)",
                growth: "Investment return, untaxed",
                going_in: "Payroll only; no deduction; its own limit",
                coming_out:
                  "Untaxed once qualified; otherwise earnings share taxed, with no 10% additional tax",
              },
              {
                type: "401(a)",
                growth: "Investment return; dividends reinvested untaxed",
                going_in: "Employer contributions only",
                coming_out:
                  "Ordinary income; 10% additional tax before 59½; required distributions",
              },
              {
                type: "Traditional IRA",
                growth: "Investment return; dividends reinvested untaxed",
                going_in: "Deducted from taxable income; income limits apply with a workplace plan",
                coming_out:
                  "Ordinary income; 10% additional tax before 59½; required distributions",
              },
              {
                type: "Roth IRA",
                growth: "Investment return, untaxed",
                going_in: "No deduction; income limits apply",
                coming_out: "Contributions first, untaxed; earnings taxed until qualified",
              },
              {
                type: "Taxable Brokerage",
                growth: "Investment return; dividends taxed each year",
                going_in: "No deduction; adds cost basis",
                coming_out: "Gain share taxed at capital gains rates",
              },
              {
                type: "HSA",
                growth: "Investment return, untaxed",
                going_in: "Deducted, payroll or surplus",
                coming_out: "Untaxed up to modeled medical costs",
              },
              {
                type: "529 Plan",
                growth: "Investment return, untaxed",
                going_in: "No deduction",
                coming_out: "Untaxed",
              },
              {
                type: "Other",
                growth: "Investment return, untaxed",
                going_in: "No deduction",
                coming_out: "Untaxed",
              },
            ]}
            note="Labels match the Account Type menu. The sections below give the rule behind each cell."
          />
          <Callout kind="where">
            <p>
              <UIPath steps={["Accounts", "Add account", "Account Type"]} />. The menu groups
              employer plans, IRAs, taxable and cash accounts, and other types. Choosing a 457(b),
              401(a), 529 Plan or Other shows a one-line note on how the projection treats it.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "growth-and-dividends",
      title: "Growth and dividends",
      body: (
        <>
          <p>
            At the start of each year, every investment account grows by its stock and bond mix: the
            stock share earns <em>Stock price growth</em> plus <em>Stock dividend yield</em>, and
            the bond share earns <em>Bond return</em>. Dividends are reinvested in the same account.
            Only in a taxable brokerage account are they income that year, taxed as qualified
            dividends, and each reinvested dollar adds a dollar of cost basis. Price growth is
            unrealized until you sell.
          </p>
          <Pair
            left={{
              title: "Taxable Brokerage",
              body: (
                <Ledger
                  title="One year, $100,000 opening balance"
                  rows={[
                    { label: "Opening balance", value: 100000 },
                    { op: "+", label: "Price growth at 7%", value: 7000 },
                    {
                      op: "+",
                      label: "Dividends at 2%, reinvested",
                      value: 2000,
                      detail: "Taxed this year; adds $2,000 of basis",
                    },
                    { op: "=", label: "Year-end balance", value: 109000 },
                  ]}
                />
              ),
            }}
            right={{
              title: "Traditional IRA",
              body: (
                <Ledger
                  title="One year, $100,000 opening balance"
                  rows={[
                    { label: "Opening balance", value: 100000 },
                    { op: "+", label: "Price growth at 7%", value: 7000 },
                    {
                      op: "+",
                      label: "Dividends at 2%, reinvested",
                      value: 2000,
                      detail: "Not taxed; taxed only when withdrawn",
                    },
                    { op: "=", label: "Year-end balance", value: 109000 },
                  ]}
                />
              ),
            }}
          />
          <p>
            The balances match; the difference is the tax bill. The default dividend yield is 0%, so
            unless you set one, a brokerage account’s whole return is price growth and it creates no
            tax until you sell.
          </p>
          <p>
            Checking and savings don’t grow. Contributions made through the year earn part of a
            year’s growth, and money withdrawn through the year gives up the growth it would have
            earned; see <HelpLink to="investment-growth" />.
          </p>
          <Callout kind="entry">
            <p>
              To give one account its own return, open{" "}
              <UIPath steps={["Accounts", "Edit", "Investment assumptions (optional)"]} /> and check{" "}
              <em>Use fixed settings for this account</em>. Stock price growth, dividend yield and
              bond allocation can be fixed per account; blank fields keep the plan’s values, and
              bonds always earn the plan’s bond return.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "contributions",
      title: "Money going in",
      body: (
        <>
          <p>
            Employer plans, the 401(k), 403(b), 457(b) and 401(a), are funded only by payroll rules
            tied to an earned income. Every other type can receive surplus through your{" "}
            <HelpLink to="savings-rules">income allocation rules</HelpLink>; HSAs can be funded
            either way.
          </p>
          <ul>
            <li>
              <strong>Traditional 401(k), 403(b) and 457(b) and HSA payroll contributions</strong>{" "}
              come out of pay before income tax. HSA payroll contributions also skip payroll taxes
              only when you mark the funding as a cafeteria plan.
            </li>
            <li>
              <strong>401(a)</strong> plans take employer contributions only. Set an employer rate
              on a payroll rule; an employee rate isn’t accepted.
            </li>
            <li>
              <strong>Traditional IRA and HSA contributions from surplus</strong> are deducted from
              taxable income. When the owner or their spouse contributes to a workplace plan that
              year, the IRA deduction phases out with income; see{" "}
              <HelpLink to="contributions-and-employer-match" />. The full contribution is still
              deposited.
            </li>
            <li>
              <strong>Roth 401(k), 403(b), 457(b) and Roth IRA contributions</strong> are made with
              taxed money. An employer contribution to a Roth workplace plan is taxed as income in
              the year it’s made.
            </li>
            <li>
              <strong>Taxable Brokerage deposits</strong> add to cost basis dollar for dollar.
            </li>
            <li>
              <strong>529 Plan, Other, Checking and Savings deposits</strong> have no tax effect.
            </li>
          </ul>
          <p>
            Annual limits apply per owner to workplace plans, IRAs and HSAs. A person’s 401(k)s and
            403(b)s share one employee limit. A 457(b) has its own limit and catch-ups, so someone
            with a 457(b) and a 401(k) or 403(b) can defer up to twice the limit; employer money
            paid into a 457(b) counts toward its limit. Limits, catch-ups and employer contributions
            are in <HelpLink to="contributions-and-employer-match" />.
          </p>
        </>
      ),
    },
    {
      id: "withdrawals",
      title: "Money coming out",
      body: (
        <>
          <p>
            Withdrawals happen when an expense is funded from a specific account, when a shortfall
            is covered in your <HelpLink to="withdrawal-order">drawdown order</HelpLink>, or as a
            required distribution.
          </p>
          <ul>
            <li>
              <strong>Traditional 401(k), 403(b), 401(a) and IRA:</strong> the full withdrawal is
              ordinary income. The share of the year before the owner turns 59½ also pays the 10%
              additional tax, unless the account is inherited or funds an active
              substantially-equal-payment series (see <HelpLink to="early-withdrawals" />
              ). Required distributions start at the owner’s{" "}
              <HelpLink to="required-minimum-distributions">required beginning age</HelpLink>.
            </li>
            <li>
              <strong>Traditional 457(b):</strong> ordinary income and required distributions like a
              401(k), but no 10% additional tax at any age. CoastMath treats every 457(b) as a
              government employer’s plan, whose early withdrawals aren’t penalized.
            </li>
            <li>
              <strong>Taxable Brokerage:</strong> the gain share of a sale, the withdrawal times one
              minus basis ÷ balance, is a capital gain taxed at long-term rates; a sale below basis
              realizes a loss. See <HelpLink to="opening-balances-and-cost-basis" />.
            </li>
            <li>
              <strong>Roth IRA:</strong> all of one owner’s Roth IRAs are treated as one.
              Withdrawals come from regular contributions first, then conversions oldest first, then
              earnings. Earnings are taxed, and can be penalized, until the account is qualified:
              owner 59½ or older and five years after the first Roth contribution year.
            </li>
            <li>
              <strong>Roth 401(k), 403(b) and 457(b):</strong> each withdrawal before qualification
              is part basis and part earnings, in proportion to the account. A Roth 457(b) still
              needs the five years and age 59½ to qualify, but its taxed earnings carry no 10%
              additional tax.
            </li>
            <li>
              <strong>HSA:</strong> untaxed up to the year’s modeled qualified medical costs; the
              rest is income, plus 20% before 65. See <HelpLink to="hsa" />.
            </li>
            <li>
              <strong>529 Plan:</strong> untaxed and never penalized. See{" "}
              <HelpLink to="education-529" />.
            </li>
            <li>
              <strong>Other, Checking and Savings:</strong> untaxed.
            </li>
          </ul>
          <Callout kind="entry">
            <p>
              A Roth account with no history entered is treated as having no contribution basis, and
              its five-year clock starts at the plan start. Enter the history under{" "}
              <UIPath steps={["Accounts", "Edit", "Retirement account tax history"]} /> to get
              untaxed early withdrawals of contributions.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "ownership",
      title: "Ownership",
      body: (
        <>
          <p>
            Each account belongs to the <em>Primary person</em>, the <em>Partner</em>, or, except
            for IRAs, workplace plans and HSAs, <em>Joint</em>. The owner’s age sets that account’s
            catch-up limits, the 59½ penalty line and the start of required distributions; joint
            accounts use the primary person’s age. When a partner dies, their accounts pass to the
            survivor (see <HelpLink to="death-of-a-partner" />
            ).
          </p>
          <Callout kind="boundary">
            <p>
              Joint and inherited accounts don’t receive IRA, workplace plan or HSA contributions; a
              rule that targets one funds nothing and says so.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "liquid-net-worth",
      title: "Liquid net worth",
      body: (
        <>
          <p>
            Liquid net worth is account balances minus debt. It sets when liquid-net-worth
            milestones are reached and the financial independence estimate, and the Monte Carlo test
            that marks a trial failed when liquid accounts run out. By default every account counts
            unless withdrawals from it are locked that year. <strong>Liquid net worth</strong> in
            the account form overrides that: <strong>Always count it as liquid</strong> includes the
            account even while it is locked, and <strong>Never count it as liquid</strong> leaves it
            out every year. Total net worth always includes the account, and the override doesn’t
            change how it is withdrawn.
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
              <li>Interest on checking and savings. Cash balances stay flat.</li>
              <li>
                A cryptocurrency account type. Imported crypto accounts become Taxable Brokerage;
                fixed account settings (bond allocation and dividend yield at 0%) come closest to a
                holding with no income.
              </li>
              <li>
                Nonqualified dividends and bond interest by default. Dividends are all qualified,
                and a brokerage account’s bond share earns its return as price growth, taxed only on
                sale, unless the account sets a qualified share or bond income yield (see{" "}
                <HelpLink to="investment-growth#income-tax-character" />
                ).
              </li>
              <li>Short-term gains. Every realized gain is long-term.</li>
              <li>
                Nondeductible traditional IRA basis. The part of a contribution that isn’t
                deductible is taxed again when it’s withdrawn or converted.
              </li>
              <li>
                The early-withdrawal exceptions other than inheritance and substantially equal
                payments, such as leaving an employer in the year you turn 55.
              </li>
              <li>
                A 457(b) from a nonprofit employer, whose money can’t be rolled over and stays the
                employer’s until paid. Every 457(b) is treated as a government plan, and money
                rolled into one from another plan type isn’t tracked separately.
              </li>
              <li>
                The 457(b) catch-up for the three years before the plan’s retirement age, and the
                403(b) catch-up for 15 years of service with one employer.
              </li>
              <li>
                Required employee contributions to a 401(a), such as those a government employer
                picks up before tax.
              </li>
              <li>
                Separate employers. Each person’s 401(k)s and 401(a)s share one annual limit on
                total employee and employer money, as if one employer offered them; 403(b)s have
                their own.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
  ],
};
export default article;

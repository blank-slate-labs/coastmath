import type { Article } from "../help_types";
import { Callout, Figure, Formula, HelpLink, Ledger, Op, UIPath, V, hostedPart } from "../help_kit";
import { BarChart } from "../help_charts";

const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/* Growth to December 31 on $1,000 deposited at the end of each month at 7% a year: 1,000 × (1.07^(k/12) − 1). */
const depositGrowth = [
  63.98, 58.0, 52.05, 46.14, 40.26, 34.41, 28.59, 22.81, 17.06, 11.34, 5.65, 0,
];

const article: Article = {
  intro: (
    <>
      <p>
        Every investment account grows once a year at a blend of the stock and bond rates, weighted
        by its bond allocation. The stock share also earns the dividend yield, which is reinvested.
        The opening balance grows for the whole year. Money added or withdrawn during the year earns
        growth only for the months it is invested.
      </p>
      <p>Checking and savings accounts don’t grow and earn no interest.</p>
    </>
  ),
  sections: [
    {
      id: "blend",
      title: "How the stock and bond blend works",
      body: (
        <>
          <Formula
            result="Price growth"
            note="The rates come from the plan’s assumptions for that year, or from the account’s own settings where it has them."
          >
            <V>Balance</V>
            <Op>×</Op>(<V>bond share</V>
            <Op>×</Op>
            <V>bond return</V>
            <Op>+</Op>
            <V>stock share</V>
            <Op>×</Op>
            <V>stock price growth</V>)
          </Formula>
          <Formula result="Dividends">
            <V>Balance</V>
            <Op>×</Op>
            <V>stock share</V>
            <Op>×</Op>
            <V>dividend yield</V>
          </Formula>
          <Ledger
            title="Example: $100,000 brokerage account for a full year"
            rows={[
              { label: "Opening balance", value: 100000 },
              { op: "+", label: "Bond growth", value: 1600, detail: "40% bonds × 4% bond return" },
              {
                op: "+",
                label: "Stock price growth",
                value: 4200,
                detail: "60% stocks × 7% price growth",
              },
              {
                op: "+",
                label: "Reinvested dividends",
                value: 1200,
                detail: "60% stocks × 2% dividend yield",
              },
              { op: "=", label: "Balance on December 31", value: 107000 },
              {
                op: "→",
                label: "Cost basis after reinvestment",
                value: 101200,
                detail: "Starting basis $100,000 plus the taxed dividends",
              },
            ]}
            note="No other income, spending or contributions. The $1,200 of dividends is taxed as qualified dividends in the same year."
          />
          <p>
            The account is rebalanced to its bond allocation every year: each year’s growth applies
            the current allocation to the whole balance. A bond allocation that changes with age
            takes effect the same way. See{" "}
            <HelpLink to="market-and-inflation-assumptions#custom-curves" />.
          </p>
        </>
      ),
    },
    {
      id: "bond-location",
      title: "Bond allocation across accounts",
      body: (
        <>
          <p>
            By default every investment account holds the plan’s bond share. Switch{" "}
            <strong>Bond location</strong> to
            <strong> To all investment accounts together</strong> and the plan’s bond share becomes
            a target for all pooled accounts combined. Each year CoastMath takes that share of their
            opening balances, places those bond dollars in the accounts in your order (pre-tax first
            by default, then Roth and 529, then taxable brokerage and Other) and holds stocks in the
            rest. Accounts in the same group share the bonds in proportion to their balances.
          </p>
          <Ledger
            title="Example: 40% bonds across a $600,000 IRA and a $400,000 brokerage account"
            rows={[
              {
                label: "Bonds needed",
                value: 400000,
                detail: "40% × $1,000,000 of opening balances",
              },
              {
                op: "→",
                label: "IRA bond share",
                value: 2 / 3,
                format: "pct",
                digits: 1,
                detail: "$400,000 of bonds fit in the $600,000 IRA",
              },
              { op: "→", label: "Brokerage bond share", value: 0, format: "pct", digits: 1 },
              {
                op: "=",
                label: "IRA on December 31",
                value: 630000,
                detail: "$400,000 × 4% + $200,000 × 7%",
              },
              {
                op: "=",
                label: "Brokerage on December 31",
                value: 428000,
                detail: "All stock at 7%",
              },
            ]}
            note="Stock price growth 7%, bond return 4%, no dividends, contributions or spending. Total growth is $58,000 either way; with each account at 40% bonds the IRA ends at $634,800 and the brokerage account at $423,200."
          />
          <p>
            An account with its own bond allocation or bond glide path keeps it, and its bonds count
            toward the target. Checking, savings and HSA accounts are never pooled; an HSA keeps the
            plan’s bond share. If the target exceeds the pooled balances, every flexible account
            holds only bonds.
          </p>
          <p>
            An account’s <strong>Bond glide path</strong> sets its bond share by calendar year or by
            the owner’s age (the primary person for a joint account). Values change in a straight
            line between points and stay constant before the first and after the last. A glide path
            replaces the account’s fixed bond allocation.
          </p>
          <Callout kind="boundary">
            <p>
              The split is decided from opening balances each year and applied as if the accounts
              were rebalanced for free: no trades, costs or realized gains are modeled. Money added
              during the year grows at its account’s split for that year, so year-end shares can
              drift from the target.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              The household setting is in <UIPath steps={["Assumptions", "Bond location"]} />; a
              glide path is in{" "}
              <UIPath
                steps={["Accounts", "Investment assumptions (optional)", "Bond glide path"]}
              />
              .
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "dividends",
      title: "Dividends and where they’re taxed",
      body: (
        <>
          <p>
            Dividends are reinvested in the account that earned them unless a brokerage account pays
            them out (below). The tax treatment depends on the account:
          </p>
          <ul>
            <li>
              <strong>Taxable brokerage.</strong> The year’s dividends are taxed on that year’s
              return, as qualified dividends unless the account says otherwise (see{" "}
              <HelpLink to="investment-growth#income-tax-character" />
              ), and the reinvested amount adds to cost basis. A later sale therefore realizes less
              gain.
            </li>
            <li>
              <strong>Retirement accounts, HSA, 529 and Other.</strong> Dividends are reinvested
              with no tax in the year. They’re taxed only as part of the account’s withdrawals, if
              at all.
            </li>
          </ul>
          <p>
            The dividend yield applies only to the stock share. By default, bonds earn their total
            return as price growth, with no separate interest income.
          </p>
          <p>
            A taxable brokerage account can instead pay its income out: uncheck{" "}
            <strong>Reinvest dividends and interest</strong> in its fixed settings. The dividends
            and bond interest earned on the opening balance are then taxed exactly as before but go
            to the year’s cash flow, like other income, instead of buying more shares, and they
            don’t add to cost basis. In the first example, the $1,200 of dividends reaches cash and
            the account ends the year at $105,800 with its basis still $100,000. Income earned
            during the year on that year’s new contributions is paid to cash as well.
          </p>
          <Callout kind="boundary">
            <p>
              Unless a brokerage account sets a bond income yield, its bond interest isn’t taxed
              yearly. Bond returns there are treated as unrealized gains until you sell, which can
              understate each year’s ordinary income. The projection shows a warning when a
              brokerage account holds bonds without a bond income yield. See{" "}
              <HelpLink to="capital-gains-and-dividends" />.
            </p>
          </Callout>
          <Callout kind="boundary">
            <p>
              Checking and savings balances stay at their dollar amount: no interest is credited or
              taxed. Money that has to earn a return needs to be in an investment account.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "income-tax-character",
      title: "Ordinary dividends and bond interest in a brokerage account",
      body: (
        <>
          <p>
            A taxable brokerage account can say how its income is taxed, under the account’s fixed
            settings in <strong>Advanced: how dividends and bond income are taxed</strong>. Every
            field is optional; blank keeps the default.
          </p>
          <ul>
            <li>
              <strong>Qualified dividends (%).</strong> The share of stock dividends taxed at the 0,
              15 or 20 percent capital-gains rates. Default 100%. The rest, such as REIT and
              money-market fund distributions, is ordinary income: it fills the ordinary brackets,
              is taxed by the state and counts toward the net investment income tax. State rules for
              qualified dividends, such as North Dakota’s 40% exclusion, apply only to the qualified
              share.
            </li>
            <li>
              <strong>Bond income yield (%).</strong> Yearly interest as a share of the account’s
              bond holdings. Default 0. It comes out of the bond return rather than being added to
              it, so the balance is unchanged. The interest is taxed each year and reinvested, which
              raises cost basis, so a later sale realizes less gain.
            </li>
            <li>
              <strong>Bond income mix (%).</strong> What kind of interest that is, adding up to
              100%. Blank means all Other.
              <ul>
                <li>
                  <strong>Treasury</strong>: federal ordinary income and net investment income, but
                  exempt from state and local income tax.
                </li>
                <li>
                  <strong>Municipal</strong>: no federal income tax and no net investment income
                  tax. It still counts toward the income that decides how much Social Security is
                  taxed, the marketplace premium credit and Medicare’s income-related premiums
                  (IRMAA). States tax it unless you check <strong>In-state municipal bonds</strong>.
                </li>
                <li>
                  <strong>Other</strong> (corporate and similar bonds): ordinary income for federal
                  and state tax, and net investment income.
                </li>
              </ul>
            </li>
          </ul>
          <Ledger
            title="Example: the $100,000 account with a 3.5% bond income yield"
            rows={[
              { label: "Opening balance", value: 100000 },
              {
                op: "+",
                label: "Bond price growth",
                value: 200,
                detail: "40% bonds × (4% bond return − 3.5% income)",
              },
              {
                op: "+",
                label: "Reinvested bond interest",
                value: 1400,
                detail: "40% bonds × 3.5%, taxed this year",
              },
              {
                op: "+",
                label: "Stock price growth",
                value: 4200,
                detail: "60% stocks × 7% price growth",
              },
              {
                op: "+",
                label: "Reinvested dividends",
                value: 1200,
                detail: "60% stocks × 2% dividend yield",
              },
              { op: "=", label: "Balance on December 31", value: 107000 },
              {
                op: "→",
                label: "Cost basis after reinvestment",
                value: 102600,
                detail: "Starting basis $100,000 plus the taxed dividends and interest",
              },
            ]}
            note="The balance matches the first example; only the tax and the cost basis differ."
          />
          <p>
            The settings have no effect in retirement accounts, HSAs, 529 plans or Other accounts,
            whose income is not taxed as it is earned.
          </p>
          <Callout kind="boundary">
            <ul>
              <li>Each account is set separately; there is no plan-wide default.</li>
              <li>
                Not modeled: the foreign tax credit, the 20% deduction for qualified REIT dividends,
                original-issue and market discount, the alternative minimum tax on private-activity
                bond interest, and state rules beyond the single in-state choice.
              </li>
              <li>
                A MAGI cap on Roth conversions or gain harvesting counts municipal interest only in
                years with marketplace coverage.
              </li>
              {hostedPart("investment-growth.imports", null)}
            </ul>
          </Callout>
        </>
      ),
    },
    {
      id: "fees",
      title: "Account fees",
      body: (
        <>
          <p>
            An investment account can set an <strong>Annual fee (%)</strong> in its fixed settings:
            the fund expense ratio plus any advisory fee, from 0 to 5% a year. Blank means no fee.
            Each year the fee is the rate times the balance on January 1, taken out after that
            year’s growth. A partial first year charges the same share of the rate. Money added
            during the year pays no fee until the next January. Checking and savings accounts never
            pay one, and a fee never takes a balance below zero.
          </p>
          <Formula result="Fee">
            <V>Opening balance</V>
            <Op>×</Op>
            <V>annual fee</V>
          </Formula>
          <Ledger
            title="Example: the $100,000 brokerage account with a 1% fee"
            rows={[
              { label: "Opening balance", value: 100000 },
              {
                op: "+",
                label: "Growth and reinvested dividends",
                value: 7000,
                detail: "As in the first example",
              },
              { op: "−", label: "Annual fee", value: 1000, detail: "1% × $100,000" },
              { op: "=", label: "Balance on December 31", value: 106000 },
              {
                op: "→",
                label: "Cost basis after reinvestment",
                value: 101200,
                detail: "Unchanged by the fee",
              },
            ]}
            note="Taxes are the same as without the fee: it isn’t deductible."
          />
          <p>
            Over decades the drag compounds. $100,000 in an all-stock Roth IRA at 7% a year grows to
            $761,226 after 30 years. With a 1% fee it reaches $574,349, about 25% less. The fees
            themselves total $79,058; the rest is growth those dollars would have earned.
          </p>
          <p>
            Two more fee types can be added to the same account, alone or together with the rate:
          </p>
          <ul>
            <li>
              <strong>Annual fee ($):</strong> a flat yearly fee in today’s dollars that rises with
              your inflation assumption, charged when the account starts the year with a balance and
              prorated in a partial first year. On the example account, $250 leaves $106,750.
            </li>
            <li>
              <strong>Fee on gains (%):</strong> a share of the year’s growth, price change plus
              dividends and interest. A year with a loss pays none. On the example account, 10% of
              the $7,000 of growth is $700, leaving $106,300.
            </li>
          </ul>
          <Callout kind="boundary">
            <ul>
              <li>
                Investment and advisory fees are not tax-deductible, so a fee never lowers taxable
                income.
              </li>
              <li>
                In a brokerage account the fee lowers the balance but not the cost basis. In
                practice, a fee paid by selling shares can realize a small gain or loss; that is not
                modeled.
              </li>
              <li>Each account is set separately; there is no plan-wide default.</li>
            </ul>
          </Callout>
        </>
      ),
    },
    {
      id: "mid-year-cash-flows",
      title: "Contributions and withdrawals during the year",
      body: (
        <>
          <p>
            Cash flows during the year are spread over the months they cover, at the end of each
            month. A contribution earns growth from its month to December 31. A withdrawal gives up
            the growth its money would have earned after it left. Both use the account’s own blend
            and dividend yield, compounded monthly at the equivalent of the annual rate.
          </p>
          <Figure
            title="Growth by December 31 on $1,000 deposited at the end of each month"
            caption="All-stock account at 7% a year. January’s deposit has 11 months to grow; December’s has none."
            table={{
              columns: [
                { key: "month", label: "Month deposited" },
                { key: "growth", label: "Growth by December 31", format: "usd_cents" },
              ],
              rows: months.map((month, index) => ({ month, growth: depositGrowth[index] })),
            }}
          >
            <BarChart
              categories={months}
              yFormat="usd"
              label="Growth by December 31 on each month’s $1,000 deposit at 7% a year"
              series={[{ id: "growth", label: "Growth", color: "cyan", values: depositGrowth }]}
            />
          </Figure>
          <Ledger
            title="Example: saving $12,000 during the year"
            rows={[
              { label: "Contributions, $1,000 at the end of each month", value: 12000 },
              {
                op: "×",
                label: "Average growth to December 31",
                value: 0.0317,
                format: "pct",
                digits: 2,
              },
              { op: "=", label: "Growth on the year’s contributions", value: 380 },
            ]}
            note="About half a year’s growth. The opening balance still grows the full 7%."
          />
          <Ledger
            title="Example: withdrawing $40,000 during the year"
            rows={[
              { label: "Opening balance, all stocks", value: 1000000 },
              { op: "+", label: "Full-year growth at 7%", value: 70000 },
              { op: "−", label: "Withdrawals spread over 12 months", value: 40000 },
              {
                op: "−",
                label: "Growth the withdrawn money didn’t earn",
                value: 1268,
                detail: "$40,000 × 3.17%",
              },
              { op: "=", label: "Balance on December 31", value: 1028732 },
            ]}
          />
          <p>
            Payroll contributions tied to a job that starts or ends mid-year grow only from the
            months that pay is received. A withdrawal that funds an expense with its own start or
            end month follows that expense’s months. Required distributions use the same month-end
            timing.
          </p>
        </>
      ),
    },
    {
      id: "first-year",
      title: "A partial first year",
      body: (
        <>
          <p>
            The first plan year runs from the plan’s start date to December 31. Balances grow for
            that share of the year: the annual rate is compounded over the fraction, and dividends
            are the annual yield times the fraction. From the next January every year is a full
            year. See <HelpLink to="first-plan-year" />.
          </p>
          <Ledger
            title="Example: $100,000 in an all-stock IRA, plan starting October 1"
            rows={[
              {
                label: "Share of the year modeled",
                value: 0.252,
                format: "pct",
                detail: "92 of 365 days",
              },
              {
                op: "→",
                label: "Growth rate for the partial year",
                value: 0.0172,
                format: "pct",
                digits: 2,
                detail: "1.07 raised to the power 0.252, minus 1",
              },
              { op: "=", label: "Balance on December 31 of the first year", value: 101720 },
              { op: "×", label: "Next year, full 7%", value: 1.07, format: "num", digits: 2 },
              { op: "=", label: "Balance on December 31 of the second year", value: 108840 },
            ]}
          />
        </>
      ),
    },
    {
      id: "where-it-shows",
      title: "Where growth shows up",
      body: (
        <>
          <p>
            The overview’s year ledger and the net worth chart’s tooltip show an{" "}
            <strong>Investment growth</strong> line for each year. It is the change in investment
            balances from market movement, including growth on that year’s contributions and net of
            growth given up by withdrawals and account fees. When an account has a fee, the ledger
            also shows the year’s <strong>Investment fees</strong>. Taxable dividends appear as
            income and again as a reinvested contribution in the year’s cash flow. Bond interest in
            a brokerage account with a bond income yield appears the same way, as{" "}
            <strong>Taxable-Account Bond Interest</strong> and
            <strong> Reinvested bond interest</strong>.
          </p>
          <Callout kind="where">
            <p>
              Change an account’s own rates in{" "}
              <UIPath steps={["Accounts", "Investment assumptions (optional)"]} />. Plan-wide rates
              are in <UIPath steps={["Assumptions"]} />. See <HelpLink to="cash-flow-view" /> to
              trace a year’s dividends and contributions.
            </p>
          </Callout>
        </>
      ),
    },
  ],
};
export default article;

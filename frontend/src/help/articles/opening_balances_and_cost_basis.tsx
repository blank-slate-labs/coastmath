import type { Article } from "../help_types";
import { Callout, Figure, Formula, HelpLink, Ledger, Op, UIPath, V } from "../help_kit";
import { LineChart } from "../help_charts";

const years = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
const balance = [
  100000, 107000, 114490, 122504, 131080, 140255, 150073, 160578, 171819, 183846, 196715,
];
const basis = [60000, 62000, 64140, 66430, 68880, 71501, 74307, 77308, 80520, 83956, 87633];

const article: Article = {
  intro: (
    <>
      <p>
        The balance you enter for an account is its value on the plan’s start date, and the
        projection’s first year grows from there. For a taxable brokerage account you can also enter
        cost basis. CoastMath tracks basis as a single average: a sale realizes the gain share of
        the account, reinvested dividends and new deposits add basis, and price growth doesn’t.
      </p>
      <p>
        Leave basis blank and CoastMath assumes the account has no embedded gain on the start date,
        so early sales are tax-free until the account grows.
      </p>
    </>
  ),
  sections: [
    {
      id: "opening-balances",
      title: "What the opening balance means",
      body: (
        <>
          <p>
            With plan type <em>Now (starts today)</em>, balances are as of today and the first year
            covers the rest of this calendar year. With <em>Fixed date</em>, they’re as of the start
            date you choose. Either way, enter current market value, not what you paid, and not net
            of the tax you’d owe on withdrawal. Contributions and withdrawals made earlier in the
            same tax year are already in the balance; enter them separately only so limits and taxes
            see them (see <HelpLink to="first-plan-year" />
            ).
          </p>
          <Callout kind="entry">
            <p>
              Balances can’t be negative. Money you owe belongs under{" "}
              <UIPath steps={["Property and debt"]} />.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              <UIPath steps={["Accounts", "Edit", "Balance ($)"]} />. The form says whether the
              account is a <em>Household account</em> shared across your plans, where an edit
              changes every plan, or an account for this plan only.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "blank-or-entered-basis",
      title: "Blank basis and entered basis",
      body: (
        <>
          <p>
            Cost basis applies only to Taxable Brokerage accounts; tax-deferred and tax-free
            accounts don’t need it.
          </p>
          <ul>
            <li>
              <strong>Blank:</strong> basis equals the opening balance. The account starts with no
              unrealized gain or loss, and later price growth builds a gain from there.
            </li>
            <li>
              <strong>Entered:</strong> the amount is used as is. Zero means the whole balance is
              gain. More than the balance means an unrealized loss, and a sale realizes part of it.
            </li>
          </ul>
          <Callout kind="entry">
            <p>
              Blank is not zero. If you know the account holds large gains, enter the basis: blank
              understates the tax on every sale until later growth catches up.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "gain-on-a-sale",
      title: "How a sale’s gain is calculated",
      body: (
        <>
          <Formula
            result="Realized gain"
            note="Basis then falls by the same share of the account that was sold."
          >
            <V>Withdrawal</V>
            <Op>×</Op>
            <V>(1 − basis ÷ balance)</V>
          </Formula>
          <Ledger
            title="Example: $20,000 sale from a $100,000 account with $60,000 basis"
            rows={[
              { label: "Balance", value: 100000 },
              { label: "Cost basis", value: 60000 },
              {
                op: "×",
                label: "Gain share, 1 − 60,000 ÷ 100,000",
                value: 0.4,
                format: "pct",
                digits: 0,
              },
              { op: "=", label: "Realized gain on $20,000", value: 8000 },
              {
                op: "→",
                label: "Basis after the sale",
                value: 48000,
                detail: "$60,000 × (1 − 20,000 ÷ 100,000)",
              },
            ]}
          />
          <p>
            Had the basis been $120,000, the same sale would realize a $4,000 loss. Losses offset
            gains, and unused losses carry forward. Every realized gain is taxed at long-term rates;
            see <HelpLink to="capital-gains-and-dividends" />.
          </p>
        </>
      ),
    },
    {
      id: "what-changes-basis",
      title: "What raises and lowers basis",
      body: (
        <>
          <ul>
            <li>
              <strong>Raises it dollar for dollar:</strong> surplus deposits, transfers in, and
              reinvested dividends, which are taxed in the year paid.
            </li>
            <li>
              <strong>Leaves it alone:</strong> price growth.
            </li>
            <li>
              <strong>Lowers it:</strong> each sale, by the share of the account sold.
            </li>
          </ul>
          <Figure
            title="Balance and cost basis of a $100,000 account with $60,000 basis"
            caption="Price growth of 5% and a 2% dividend yield, no deposits or sales. The gap between the lines is unrealized gain."
            table={{
              columns: [
                { key: "year", label: "Years from start", format: "num" },
                { key: "balance", label: "Balance", format: "usd" },
                { key: "basis", label: "Cost basis", format: "usd" },
              ],
              rows: years.map((year, i) => ({ year, balance: balance[i], basis: basis[i] })),
            }}
          >
            <LineChart
              label="Balance and cost basis over ten years"
              xFormat="num"
              series={[
                {
                  id: "balance",
                  label: "Balance",
                  color: "cyan",
                  points: years.map((year, i) => [year, balance[i]] as [number, number]),
                },
                {
                  id: "basis",
                  label: "Cost basis",
                  color: "gray",
                  points: years.map((year, i) => [year, basis[i]] as [number, number]),
                },
              ]}
            />
          </Figure>
        </>
      ),
    },
    {
      id: "updating-balances",
      title: "Updating balances later",
      body: (
        <>
          <p>
            Editing a balance resets that account’s starting point for the whole projection. It
            doesn’t record a sale or a contribution, so nothing is taxed or counted toward a limit.
          </p>
          <Callout kind="entry">
            <p>
              Update basis whenever you update the balance of a brokerage account with entered
              basis. A new balance with the old basis moves the whole difference into unrealized
              gain or loss. A blank basis follows the new balance automatically.
            </p>
          </Callout>
          <p>
            Roth accounts keep a separate record of contributions and conversions for early
            withdrawals; see <HelpLink to="account-types#withdrawals" />.
          </p>
        </>
      ),
    },
    {
      id: "not-modeled",
      title: "What isn’t modeled",
      body: (
        <Callout kind="boundary">
          <ul>
            <li>Tax lots and lot selection. Every sale uses average basis.</li>
            <li>Short-term holding periods and wash sales.</li>
            <li>Basis in a traditional IRA from nondeductible contributions.</li>
          </ul>
        </Callout>
      ),
    },
  ],
};
export default article;

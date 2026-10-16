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
  Steps,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";
import { BracketBar } from "../help_charts";

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath taxes realized gains and dividends from taxable accounts at the long-term capital
        gains rates of 0, 15 and 20 percent. They are stacked on top of your ordinary taxable
        income. Every realized gain is treated as long-term and every dividend as qualified, unless
        a brokerage account sets a lower qualified share; the rest is ordinary income. Gains use
        average cost basis. Realized losses offset gains, then up to $3,000 of ordinary income a
        year, and the rest carries forward. Above a fixed income threshold, the 3.8% net investment
        income tax applies as well.
      </p>
    </>
  ),
  sections: [
    {
      id: "where-gains-and-dividends-come-from",
      title: "Where gains and dividends come from",
      body: (
        <>
          <p>
            <strong>Sales.</strong> A gain is realized whenever money leaves a taxable brokerage or
            crypto account: a withdrawal to cover a shortfall, a gift funded from the account, or a
            transfer out. Each sale carries the account’s average gain.
          </p>
          <Formula result="Realized gain">
            <V>Amount sold</V>
            <Op>×</Op>
            <V>(1 − Cost basis ÷ Balance)</V>
          </Formula>
          <p>
            Basis falls in proportion to the share sold. A sale when the balance is below basis
            realizes a loss. Contributions and reinvested dividends add to basis dollar for dollar.
            A blank cost basis is treated as equal to the opening balance, so the existing holding
            carries no gain until it grows (see <HelpLink to="opening-balances-and-cost-basis" />
            ).
          </p>
          <p>
            <strong>Dividends.</strong> Each year the stock share of a taxable brokerage balance
            pays the dividend yield. The dividend is taxed as a qualified dividend and reinvested,
            which adds to basis, unless the account pays its income out to cash (see{" "}
            <HelpLink to="investment-growth#dividends" />
            ). Crypto pays no dividend. Bond returns are treated as price growth, so bonds generate
            no separate interest income, and checking and savings balances earn none.
          </p>
          <p>
            <strong>Property sales.</strong> The taxable gain on a home or other property, after any
            home-sale exclusion, joins the year’s long-term gains (see{" "}
            <HelpLink to="selling-a-home" />
            ).
          </p>
          <p>
            Retirement accounts and HSAs never produce capital gains; their withdrawals are ordinary
            income or tax-free.
          </p>
        </>
      ),
    },
    {
      id: "how-gains-stack",
      title: "How gains stack on ordinary income",
      body: (
        <>
          <DataTable
            caption="2026 long-term capital gains rates (taxable income up to)"
            columns={[
              { key: "status", label: "Filing status" },
              { key: "zero", label: "0% up to", format: "usd" },
              { key: "fifteen", label: "15% up to", format: "usd" },
            ]}
            rows={[
              { status: "Single", zero: 49450, fifteen: 545500 },
              { status: "Married filing jointly", zero: 98900, fifteen: 613700 },
              { status: "Married filing separately", zero: 49450, fifteen: 306850 },
              { status: "Head of household", zero: 66200, fifteen: 579600 },
            ]}
            note="Gains above the 15% limit are taxed at 20%. Later years grow these thresholds with your plan’s inflation assumption."
          />
          <p>
            The thresholds apply to total taxable income, with ordinary income counted first. Gains
            fill whatever 0% room ordinary income leaves, then the 15% band. When deductions exceed
            ordinary income, the unused deduction reduces the gains before any rate applies.
          </p>
          <Figure
            title="Example: single filer, $40,000 of ordinary taxable income and a $30,000 long-term gain in 2026"
            caption="The gray bar is ordinary income, taxed at ordinary rates. Only the gain is taxed at these rates."
            table={{
              columns: [
                { key: "layer", label: "Layer" },
                { key: "from", label: "From", format: "usd" },
                { key: "to", label: "To", format: "usd" },
                { key: "rate", label: "Rate" },
              ],
              rows: [
                { layer: "Ordinary taxable income", from: 0, to: 40000, rate: "Ordinary brackets" },
                { layer: "Gain in the 0% band", from: 40000, to: 49450, rate: "0%" },
                { layer: "Gain in the 15% band", from: 49450, to: 70000, rate: "15%" },
              ],
            }}
          >
            <BracketBar
              brackets={[
                { rate: 0, upTo: 49450 },
                { rate: 0.15, upTo: 545500 },
                { rate: 0.2, upTo: null },
              ]}
              start={40000}
              segments={[{ label: "Long-term gain", amount: 30000, color: "blue" }]}
              max={100000}
              label="A $30,000 gain stacked from $40,000 of ordinary taxable income: $9,450 falls below the $49,450 zero-rate limit and $20,550 is taxed at 15%"
            />
          </Figure>
          <Ledger
            title="Example, continued"
            rows={[
              { label: "Gain in the 0% band", value: 9450, detail: "$49,450 − $40,000" },
              { label: "Gain in the 15% band", value: 20550 },
              { op: "×", label: "Rate", value: 0.15, format: "pct", digits: 0 },
              { op: "=", label: "Capital gains tax", value: 3082.5, format: "usd_cents" },
            ]}
          />
          <p>
            The marginal rate in results is the ordinary bracket only. A year with gains in the 15%
            band can show a 12% marginal rate.
          </p>
        </>
      ),
    },
    {
      id: "losses-and-carryforward",
      title: "Losses and the carryforward",
      body: (
        <>
          <p>
            Each year CoastMath nets realized gains against realized losses and any loss carried in.
            A net loss reduces ordinary income by up to $3,000 ($1,500 married filing separately),
            and the remainder carries to the next year without expiring. Losses never offset
            qualified dividends. When taxable income is too small to absorb the full $3,000, the
            unused part stays in the carryforward. Losses on a primary residence or personal-use
            property are not deductible.
          </p>
          <Ledger
            title="Example: single, $80,000 of wages, a $20,000 carryforward, $5,000 of realized gains and $2,000 of dividends in 2026"
            rows={[
              { label: "Realized gains", value: 5000 },
              { op: "−", label: "Loss carried in", value: 20000 },
              { op: "=", label: "Net capital loss", value: -15000 },
              { op: "→", label: "Deducted from ordinary income", value: 3000 },
              { op: "→", label: "Carried to 2027", value: 12000 },
              { label: "Qualified dividends, still taxed", value: 2000 },
              { op: "×", label: "15% rate", value: 0.15, format: "pct", digits: 0 },
              { op: "=", label: "Capital gains tax", value: 300 },
            ]}
          />
          <Callout kind="entry">
            <p>
              Enter losses you already carry as a positive amount in{" "}
              <UIPath
                steps={[
                  "Plan details",
                  "Earlier this tax year",
                  "Capital loss carried from prior tax years ($)",
                ]}
              />
              . Gains or losses already realized this year go in{" "}
              <strong>Realized capital gains (negative for losses)</strong> on the same form.
            </p>
          </Callout>
          <p>
            The remaining carryforward for each year appears as{" "}
            <strong>Capital loss carryforward</strong> in the{" "}
            <UIPath steps={["Overview", "Income & taxes"]} /> tooltip.
          </p>
        </>
      ),
    },
    {
      id: "net-investment-income-tax",
      title: "Net investment income tax",
      body: (
        <>
          <KeyFigures
            caption="Net investment income tax"
            items={[
              { label: "Rate", value: "3.8%" },
              {
                label: "Single or head of household",
                value: 200000,
                detail: "Modified AGI threshold",
              },
              { label: "Married filing jointly", value: 250000 },
              { label: "Married filing separately", value: 125000 },
            ]}
          />
          <p>
            The tax is 3.8% of the smaller of net investment income or modified AGI above the
            threshold. The thresholds are fixed in the law and don’t grow with inflation, so more
            years cross them as nominal income rises.
          </p>
          <p>
            Investment income counts realized gains (including a taxable home-sale gain), dividends,
            taxable bond interest (not municipal interest), and income streams whose{" "}
            <strong>Income tax treatment</strong> is <strong>Investment income</strong> or{" "}
            <strong>Nonqualified annuity taxable income</strong>. Wages, self-employment income,
            Social Security, retirement-account withdrawals, Roth conversions, and streams marked{" "}
            <strong>Qualified pension or retirement distribution</strong> or{" "}
            <strong>Other ordinary income excluded from NIIT</strong> are not investment income.
            They still raise modified AGI, though, so a conversion can expose gains to the tax.
          </p>
          <Ledger
            title="Example: single, $180,000 of wages and a $50,000 long-term gain in 2026"
            rows={[
              { label: "Modified AGI", value: 230000 },
              { op: "−", label: "Threshold", value: 200000 },
              {
                op: "=",
                label: "Excess",
                value: 30000,
                detail: "Smaller than the $50,000 of investment income",
              },
              { op: "×", label: "Rate", value: 0.038, format: "pct", digits: 1 },
              { op: "=", label: "Net investment income tax", value: 1140 },
            ]}
          />
        </>
      ),
    },
    {
      id: "gain-harvesting",
      title: "Harvesting gains to fill a bracket",
      body: (
        <>
          <p>
            A gain-harvesting rule sells and immediately rebuys appreciated holdings in one taxable
            brokerage account each year. The sale realizes gain up to the top of a capital gains
            band you choose, usually 0%. The balance doesn’t change; basis rises by the gain
            realized, which shrinks the taxable gain on later sales. There is no wash-sale limit on
            gains.
          </p>
          <Steps>
            <li>
              Open <UIPath steps={["Tax tools", "Strategy comparisons"]} /> and set{" "}
              <strong>Strategy</strong> to{" "}
              <strong>Capital-gain harvesting to fill a capital-gains bracket</strong>.
            </li>
            <li>
              Choose the <strong>Taxable account</strong>, when it runs (
              <strong>Convert from</strong> and <strong>Convert until</strong>), an optional{" "}
              <strong>MAGI cap</strong> in today’s dollars and the{" "}
              <strong>Capital-gains bracket ceilings to test</strong>.
            </li>
            <li>
              Select <strong>Compare strategies</strong>, then <strong>Apply</strong> the row you
              want to keep.
            </li>
          </Steps>
          <p>
            Room is measured from the year’s ordinary taxable income, including conversions and
            gains already realized, before the year’s shortfall withdrawals. The harvest counts its
            own effect on that income: the extra gain can make more Social Security taxable and
            shrink the senior deduction, so the rule realizes less. A withdrawal later in the same
            year can still push part of the harvested gain above the ceiling. A higher modified AGI
            from harvesting can also affect the net investment income tax, Social Security taxation,
            premium credits and Medicare surcharges. The comparison table reports lifetime taxes,
            health costs, net estate, and the years with Medicare surcharges or lost premium credits
            for each candidate.
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
                Short-term gains and holding periods; lot selection, first-in-first-out or specific
                identification; wash sales.
              </li>
              <li>
                Fund capital-gain distributions. Non-qualified dividends, bond interest and
                municipal interest are modeled only when a brokerage account sets them (see{" "}
                <HelpLink to="investment-growth#income-tax-character" />
                ).
              </li>
              <li>
                The 28% rate for collectibles. The 25% rate on depreciation recapture applies only
                to rental property sales (see <HelpLink to="selling-a-home#tax-on-the-sale" />
                ).
              </li>
              <li>
                Harvesting losses on purpose, and harvesting gains in crypto accounts. Crypto sales
                otherwise follow the same rules as brokerage sales.
              </li>
            </ul>
          </Callout>
          <Symptoms
            rows={[
              {
                symptom: "A withdrawal from brokerage produces much less gain than expected.",
                check: "The account’s cost basis entry.",
                next: "A blank basis counts the whole opening balance as basis; enter the actual basis.",
              },
              {
                symptom: "Gains are taxed although income looks under the 0% limit.",
                check: "Ordinary taxable income, including conversions and required distributions.",
                next: "Gains start where ordinary taxable income ends, not at zero.",
              },
              {
                symptom: "The carryforward shrinks although no gains were realized.",
                check: "The year’s ordinary income.",
                next: "Up to $3,000 a year is used against ordinary income automatically.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

import type { Article } from "../help_types";
import { Callout, Figure, HelpLink, KeyFigures, Ledger, Symptoms, UIPath } from "../help_kit";
import { Waterfall } from "../help_charts";

const article: Article = {
  intro: (
    <>
      <p>
        At the end of the projection, CoastMath values everything that’s left and settles the
        estate. Debts and unpaid bills come off first, then your settlement costs, an optional state
        estate tax, and federal estate tax on the amount above the exemption. What remains is the{" "}
        <strong>net estate</strong>. Separately, CoastMath estimates the income tax your heirs will
        owe on inherited pre-tax accounts.
      </p>
      <p>
        If your partner survives you, the estate passes under the unlimited marital deduction. No
        estate tax or heirs’ income tax is charged, and the survivor’s later estate isn’t projected.
      </p>
    </>
  ),
  sections: [
    {
      id: "when-the-estate-is-valued",
      title: "When the estate is valued",
      body: (
        <>
          <p>
            The estate is valued at the end of the plan’s final year, in that year’s dollars. By
            default the plan ends in the year you reach your life expectancy. Set{" "}
            <strong>Plan ends</strong> to <strong>At the last survivor’s longevity age</strong> to
            follow the household until the second death. The estate is then settled at that death,
            with no marital deduction.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Partner and estate"]} /> holds every setting below. The result is the{" "}
              <strong>Estate</strong> card on the <UIPath steps={["Overview"]} />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "federal-exemption",
      title: "Federal exemption and rate",
      body: (
        <>
          <KeyFigures
            caption="Federal estate tax, 2026"
            items={[
              { label: "Basic exclusion per person", value: 15000000 },
              {
                label: "Rate on the taxable estate above it",
                value: 0.4,
                format: "pct",
                digits: 0,
              },
            ]}
          />
          <p>
            After 2026 the exclusion grows with your plan’s inflation assumption. The law indexes it
            to a published price index, so later projected amounts are estimates. With{" "}
            <strong>Override the federal estate exemption</strong>, the amount you enter is used as
            is, in the year of death, with no indexing. Lifetime taxable gifts don’t reduce the
            exemption, because gifts aren’t modeled.
          </p>
        </>
      ),
    },
    {
      id: "how-it-is-calculated",
      title: "How the estate is settled",
      body: (
        <>
          <ul>
            <li>
              <strong>Settlement costs</strong> are your fixed amount plus your percentage of the
              gross estate. They’re deducted before any tax.
            </li>
            <li>
              <strong>State estate tax</strong>, when you turn it on, is your flat rate on the
              amount above your state exemption. Your exemption isn’t indexed. The state tax is
              deducted before the federal tax, as federal law allows.
            </li>
            <li>
              <strong>Federal estate tax</strong> is 40% of what’s left above the exemption, plus
              any unused exemption carried over from a partner.
            </li>
            <li>
              <strong>529 accounts</strong> aren’t part of the gross estate. They’re added back
              after estate tax, since they pass to the account’s successor owner.
            </li>
            <li>
              <strong>Charitable bequest</strong> is your percentage of the estate after settlement
              costs. It is deducted before estate tax and shown on its own line.
            </li>
            <li>
              <strong>Selling costs on real assets</strong> are your percentage of the property’s
              value. They reduce net estate but not the taxable estate.
            </li>
          </ul>
          <Ledger
            title="Example: $1,000,000 estate with $400,000 of property, a 10% bequest, 6% selling costs and a $500,000 exemption override"
            rows={[
              { label: "Gross estate", value: 1000000 },
              { op: "−", label: "Charitable bequest", value: 100000, detail: "10% of the estate" },
              {
                op: "−",
                label: "Federal estate tax",
                value: 160000,
                detail: "40% × ($900,000 − $500,000)",
              },
              { op: "−", label: "Selling costs", value: 24000, detail: "6% of $400,000" },
              { op: "=", label: "Net estate", value: 716000 },
            ]}
          />
          <Ledger
            title="Example: death in 2026, no surviving partner"
            rows={[
              { label: "Gross estate", value: 20000000 },
              {
                op: "−",
                label: "Settlement costs",
                value: 400000,
                detail: "2% of the gross estate",
              },
              { op: "=", label: "Estate before tax", value: 19600000 },
              {
                op: "−",
                label: "State estate tax",
                value: 2112000,
                detail: "12% above a $2,000,000 state exemption",
              },
              {
                op: "−",
                label: "Federal estate tax",
                value: 995200,
                detail: "40% × ($19,600,000 − $2,112,000 − $15,000,000)",
              },
              { op: "=", label: "Net estate", value: 16492800 },
              {
                op: "−",
                label: "Heirs’ income tax on a $1,000,000 IRA",
                value: 194400,
                detail: "30% × ($1,000,000 − $352,000 of estate tax attributable to it)",
              },
              { op: "=", label: "Net to heirs after their income tax", value: 16298400 },
            ]}
            note="The state rate, state exemption, settlement percentage and heirs’ rate are inputs, not a particular state’s law."
          />
          <Figure
            title="From gross estate to what heirs keep, same example"
            table={{
              columns: [
                { key: "step", label: "Step" },
                { key: "value", label: "Amount", format: "usd" },
              ],
              rows: [
                { step: "Gross estate", value: 20000000 },
                { step: "Settlement costs", value: -400000 },
                { step: "State estate tax", value: -2112000 },
                { step: "Federal estate tax", value: -995200 },
                { step: "Net estate", value: 16492800 },
                { step: "Heirs’ income tax", value: -194400 },
                { step: "Net to heirs", value: 16298400 },
              ],
            }}
          >
            <Waterfall
              label="Gross estate of $20 million reduced by settlement costs, state and federal estate tax and heirs’ income tax to $16.3 million"
              steps={[
                { label: "Gross estate", value: 20000000, color: "gray", total: true },
                { label: "Settlement", value: -400000, color: "magenta" },
                { label: "State tax", value: -2112000, color: "orange" },
                { label: "Federal tax", value: -995200, color: "orange" },
                { label: "Net estate", value: 16492800, color: "gray", total: true },
                { label: "Heirs’ tax", value: -194400, color: "orange" },
                { label: "Net to heirs", value: 16298400, color: "gray", total: true },
              ]}
            />
          </Figure>
        </>
      ),
    },
    {
      id: "portability-and-marital-deduction",
      title: "Portability and the marital deduction",
      body: (
        <>
          <p>
            When your partner dies first and{" "}
            <strong>Elect portability of a deceased partner’s unused exemption</strong> is checked,
            their exemption for their death year is added to yours. It stays at that amount.
            CoastMath assumes everything passed to you, so their whole exemption was unused. In the
            example above, a partner who died in 2026 would add $15,000,000. The federal tax would
            be $0, and net estate would rise to $17,488,000. With an override, the overridden amount
            is used for both exemptions.
          </p>
          <p>
            When your partner is alive at the end of the plan, the marital deduction applies and the
            Estate card shows the estate tax as deferred. Settlement costs are still deducted.
          </p>
          <p>
            When you both die in the same year, the household leaves two estates. Each gets its own
            federal exemption, and its own state exemption if state estate tax is on, with or
            without portability. CoastMath assumes the assets divide so that both exemptions are
            used.
          </p>
        </>
      ),
    },
    {
      id: "what-heirs-pay",
      title: "Basis step-up and what heirs pay",
      body: (
        <>
          <ul>
            <li>
              <strong>Traditional IRA and 401(k) balances</strong> are taxed to heirs at your{" "}
              <strong>Heirs’ income tax rate on inherited pre-tax accounts</strong>. The rate
              applies after deducting the federal estate tax attributable to those balances. At 0%,
              no heirs’ tax is estimated.
            </li>
            <li>
              <strong>HSA balances</strong> are treated the same way, since a beneficiary other than
              a spouse owes income tax on them. A surviving partner’s inherited HSA stays an HSA.
            </li>
            <li>
              <strong>Roth balances</strong> pass without income tax.
            </li>
            <li>
              <strong>Taxable accounts and property</strong> count at market value, and no tax on
              their unrealized gains is estimated while step-up is on. Turn step-up off and enter{" "}
              <strong>Heirs’ capital gains rate on inherited taxable gains</strong> to charge that
              rate on the unrealized gain in brokerage and crypto accounts, as if heirs sold
              everything with your basis. Not applied when a surviving partner inherits.
            </li>
          </ul>
          <p>
            If your partner dies during the plan,{" "}
            <strong>Step up cost basis on partner-owned taxable accounts at their death</strong>{" "}
            resets the basis of their brokerage and crypto accounts to market value. You then sell
            those accounts with less taxable gain. Joint accounts keep their basis unless you check{" "}
            <strong>Also step up joint taxable accounts at the first death</strong>: then the
            deceased partner’s half steps up, so the basis becomes half the old basis plus half the
            market value. If you live in a community property state at that death (Arizona,
            California, Idaho, Louisiana, Nevada, New Mexico, Texas, Washington or Wisconsin), the
            whole joint account steps up to market value. For how the survivor’s taxes and accounts
            change, see <HelpLink to="death-of-a-partner" />.
          </p>
          <Callout kind="boundary">
            <ul>
              <li>Lifetime gifts, generation-skipping transfer tax and state inheritance taxes.</li>
              <li>
                Graduated state estate tax brackets and exemption cliffs; the state tax is one flat
                rate.
              </li>
              <li>
                The heirs’ ten-year withdrawal schedule and their own brackets; one effective rate
                stands in for both.
              </li>
              <li>
                Community property held outside joint accounts; only joint accounts get the
                community-property step-up.
              </li>
              <li>Deducting selling costs as estate administration expenses.</li>
              <li>
                Estate tax at the surviving partner’s later death when the marital deduction
                applies.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
    {
      id: "reading-the-estate-card",
      title: "Reading the Estate card",
      body: (
        <>
          <p>
            The card reconciles <strong>Total assets</strong> down to <strong>Net estate</strong> in
            future dollars. It shows each deduction, exemption and tax. When heirs inherit pre-tax
            balances, it adds <strong>Heirs’ income tax on inherited pre-tax balances</strong> and{" "}
            <strong>Net to heirs after their income tax</strong>.{" "}
            <strong>What this estimate leaves out</strong> lists the limits above. Charitable
            bequests aren’t deducted; lifetime giving is covered in{" "}
            <HelpLink to="charitable-giving" />.
          </p>
          <Symptoms
            rows={[
              {
                symptom: "Federal estate tax is $0 on a large estate",
                check: "Whether a partner survives to the plan’s end",
                next: "Expected: the marital deduction defers it. Use the last-survivor horizon to settle at the second death.",
              },
              {
                symptom: "Heirs’ income tax shows $0",
                check: "Heirs’ income tax rate",
                next: "Enter an effective rate for your heirs.",
              },
              {
                symptom: "The exemption is larger than $15,000,000",
                check: "Year of death",
                next: "Expected: it grows with inflation after 2026, and a partner’s unused exemption may be added.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

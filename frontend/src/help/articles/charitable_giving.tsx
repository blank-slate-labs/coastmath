import type { Article } from "../help_types";
import {
  Callout,
  Formula,
  HelpLink,
  KeyFigures,
  Ledger,
  Op,
  Pair,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath models three kinds of giving. Direct cash gifts and donor-advised fund
        contributions are paid from checking, savings and then taxable brokerage, and count toward
        your itemized deductions up to 60% of AGI, less a floor of 0.5% of AGI. Direct gifts can
        instead be deducted without itemizing, up to a small fixed cap. Either kind can instead be
        paid with appreciated shares from a brokerage account, whose gain is never taxed and whose
        deduction is limited to 30% of AGI.
      </p>
      <p>
        Qualified charitable distributions go straight from a traditional IRA to charity. They count
        toward that year’s required distribution and are left out of income, so they are never
        deducted.
      </p>
    </>
  ),
  sections: [
    {
      id: "what-you-enter",
      title: "What you enter",
      body: (
        <>
          <p>
            Each gift has a giving type, an annual amount and optional start and end milestones. The
            full amount is given in every year from the year the start milestone is reached up to,
            but not including, the year the end milestone is reached. There is no partial-year
            proration.
          </p>
          <Callout kind="entry">
            <p>
              Gift amounts are nominal: the same dollar amount every active year, with no inflation
              adjustment. To keep a gift’s real value, enter separate gifts for later periods at
              higher amounts.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              <UIPath steps={["Charitable giving", "Add giving"]} />, then choose{" "}
              <em>Direct cash gift</em>, <em>Donor-advised fund contribution</em> or{" "}
              <em>Qualified charitable distribution (IRA)</em>.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-gifts-are-paid",
      title: "How cash gifts and fund contributions are paid",
      body: (
        <>
          <p>
            Direct gifts and fund contributions are paid in cash from checking first, then savings,
            then taxable brokerage accounts, whatever your drawdown order. They never come from
            retirement accounts. The part brokerage would cover is paid from the year’s leftover
            income first, so a year with a surplus sells nothing. Only the part the year can’t cover
            sells brokerage holdings, which realizes a share of the account’s gains, like any other
            brokerage withdrawal. If those accounts can’t cover the full amount, CoastMath gives
            what they hold, warns you, and deducts only what was paid.
          </p>
          <p>
            A contribution to a donor-advised fund leaves your plan when it’s made. The fund’s
            balance and its later grants aren’t tracked.
          </p>
        </>
      ),
    },
    {
      id: "appreciated-shares",
      title: "Gifts of appreciated shares",
      body: (
        <>
          <p>
            Set <em>Paid with</em> to <em>Appreciated shares</em> and pick the brokerage account in{" "}
            <em>Shares from</em>. Each year the gift’s amount leaves that account at market value,
            with the same share of its cost basis, so no gain is realized. CoastMath tracks one
            average basis per account rather than tax lots, so it can’t pick the highest-gain lots;
            every gift carries the account’s average gain. If the account holds less than the gift,
            the rest is paid in cash as above, with a warning.
          </p>
          <p>
            Shares are deducted at market value, up to 30% of AGI. Cash gifts then share what is
            left of the 60% limit: 60% of AGI minus the shares allowed. The part of a share gift
            over 30% carries forward five years, separately from cash, and is used after the next
            year’s share gifts.
          </p>
          <Ledger
            title="Example: $40,000 of shares and a $50,000 cash fund contribution on $100,000 of AGI"
            rows={[
              {
                label: "Shares, up to 30% of AGI",
                value: 30000,
                detail: "$10,000 carried forward as shares",
              },
              {
                op: "+",
                label: "Cash, up to 60% of AGI less the shares",
                value: 30000,
                detail: "$20,000 carried forward as cash",
              },
              { op: "−", label: "Floor: 0.5% of AGI", value: 500 },
              { op: "=", label: "Itemized charitable deduction", value: 59500 },
            ]}
          />
          <Callout kind="boundary">
            <p>
              Gifted shares are assumed held more than a year. Not modeled: electing to deduct
              shares at basis under the 50% limit, shares worth less than their basis (deduct their
              value, but sell them to use the loss instead), and gifts of other property.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "deduction-limits",
      title: "Deduction limits and the itemizing test",
      body: (
        <>
          <KeyFigures
            caption="2026 federal rules for cash gifts"
            items={[
              {
                label: "Itemized limit",
                value: 0.6,
                format: "pct",
                digits: 0,
                detail: "of AGI, for cash to public charities and donor-advised funds",
              },
              {
                label: "Itemized floor",
                value: 0.005,
                format: "pct",
                digits: 1,
                detail: "of AGI, subtracted from the allowed amount",
              },
              {
                label: "Deduction without itemizing",
                value: "$1,000 / $2,000",
                detail: "Single / married filing jointly; direct gifts only; not indexed",
              },
              {
                label: "Carryforward",
                value: "5 years",
                detail: "For amounts above the 60% limit",
              },
            ]}
          />
          <Formula
            result="Itemized charitable deduction"
            note="AGI is the year’s final AGI, after withdrawals, conversions and capital gains, and after any QCD exclusion."
          >
            <V>the smaller of</V>
            <V>(this year’s gifts + carryforward)</V>
            <Op>and</Op>
            <V>60% × AGI</V>
            <Op>−</Op>
            <V>0.5% × AGI</V>
          </Formula>
          <p>
            CoastMath then adds your other itemized deductions and itemizes only if the total beats
            the standard deduction plus the non-itemizer charitable deduction you would give up.
            When you don’t itemize, direct gifts up to the cap are deducted on top of the standard
            deduction; fund contributions don’t qualify.
          </p>
          <Ledger
            title="Example: a $70,000 fund contribution on $100,000 of AGI, single filer, no inflation"
            rows={[
              { label: "Contribution in 2026", value: 70000 },
              { op: "→", label: "Limit: 60% of AGI", value: 60000 },
              { op: "−", label: "Floor: 0.5% of AGI", value: 500 },
              { op: "=", label: "Itemized charitable deduction, 2026", value: 59500 },
              { op: "→", label: "Carried forward to 2027", value: 10000 },
              { op: "−", label: "Floor in 2027", value: 500 },
              {
                op: "=",
                label: "Charitable deduction if itemizing, 2027",
                value: 9500,
                detail: "Below the $16,100 standard deduction, so the standard deduction is used",
              },
            ]}
            note="The $10,000 carryforward is used up in 2027 even though the standard deduction wins, as the tax rules require. A second $30,000 contribution in 2027 would instead be deducted together with it: $39,500."
          />
          <h3>Carryforward order</h3>
          <p>
            Each year’s gifts use the 60% limit first; carried amounts then fill the remaining room,
            oldest first, and expire after five years. A year you take the standard deduction still
            uses up whatever would have fit.
          </p>
          <Callout kind="boundary">
            <p>
              Only the donor-advised fund share of an amount over the 60% limit is carried forward.
              The excess from direct cash gifts is dropped. Not modeled: gifts to private
              foundations and their lower limits, carrying forward amounts lost to the 0.5% floor,
              and the cap on the tax value of itemized deductions in the top bracket.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "qualified-charitable-distributions",
      title: "Qualified charitable distributions",
      body: (
        <>
          <KeyFigures
            caption="2026 QCD rules"
            items={[
              {
                label: "Annual limit per IRA owner",
                value: 111000,
                detail: "Grows with your plan’s inflation assumption in later years",
              },
              { label: "Eligible from", value: "Age 70½", detail: "Traditional IRAs only" },
            ]}
          />
          <p>
            A QCD entry is a household amount. CoastMath splits it across IRA owners who are
            eligible that year, each up to the annual limit. An owner born January–June is eligible
            from the year they turn 70; one born July–December, from the year they turn 71. For each
            owner, the gift is taken from that year’s required distribution first, then from their
            remaining traditional IRA balance. A 401(k) can’t make a QCD.
          </p>
          <Pair
            left={{
              title: "Up to the required distribution",
              body: (
                <p>
                  The QCD replaces that part of the required distribution. It’s excluded from income
                  and the cash you receive from the distribution falls by the same amount.
                </p>
              ),
            }}
            right={{
              title: "Beyond the required distribution",
              body: (
                <p>
                  An extra, untaxed IRA withdrawal goes to charity. It doesn’t reduce taxable income
                  from other sources.
                </p>
              ),
            }}
          />
          <Ledger
            title="Example: a $15,000 QCD at 75, traditional IRA of $500,000 at the prior year end"
            rows={[
              {
                label: "Required distribution",
                value: 20325,
                detail: "$500,000 ÷ 24.6, the distribution period at 75",
              },
              { op: "−", label: "QCD, taken from the required distribution", value: 15000 },
              { op: "=", label: "Taxable part of the distribution", value: 5325 },
              { op: "+", label: "Pension", value: 40000 },
              { op: "=", label: "AGI", value: 45325, detail: "Without the QCD: $60,325" },
            ]}
            note="With a $30,000 QCD instead, the whole $20,325 distribution and $9,675 more from the IRA go to charity, and AGI is the $40,000 pension."
          />
          <p>
            Before an owner is eligible, a QCD entry does nothing for them; it isn’t turned into a
            cash gift. See <HelpLink to="required-minimum-distributions" /> for how the distribution
            itself is set.
          </p>
        </>
      ),
    },
    {
      id: "where-results-show",
      title: "Where the results show up",
      body: (
        <>
          <p>
            Each gift appears in the year’s cash flow under its name, and QCDs as{" "}
            <em>QCD to charity</em>. Flexible spending rules never reduce them. The deduction and
            whether you itemized appear with the year’s tax detail; see{" "}
            <HelpLink to="itemized-deductions" />.
          </p>
          <Symptoms
            rows={[
              {
                symptom: "A gift doesn’t lower your tax",
                check:
                  "Whether total itemized deductions beat the standard deduction, and the 0.5% floor",
                next: "Compare itemized deductions with the standard deduction in that year’s tax detail.",
              },
              {
                symptom: "A QCD is missing or smaller than entered",
                check: "Each owner’s age, traditional IRA balance and the annual limit",
                next: "Enter the rest as a direct gift if you plan to give it in cash.",
              },
              {
                symptom: "A gift is paid only in part",
                check: "Checking, savings and brokerage balances that year",
                next: "Move cash into those accounts or lower the gift.",
              },
              {
                symptom: "The gift’s real value shrinks over time",
                check: "Amounts are nominal",
                next: "Split the gift into later entries at higher amounts.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};

export default article;

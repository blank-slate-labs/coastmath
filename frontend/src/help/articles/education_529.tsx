import type { Article } from "../help_types";
import { Callout, Figure, HelpLink, Ledger, Steps, UIPath } from "../help_kit";
import { BarChart } from "../help_charts";

const article: Article = {
  intro: (
    <>
      <p>
        A 529 Plan account grows at your investment assumptions without tax. Withdrawals are tax
        free up to the year’s qualified education expenses: expenses you fund from the 529, plus
        expenses marked as qualified education. The earnings share of any other withdrawal is
        ordinary income plus a 10% additional tax. CoastMath tracks your contributions as the
        account’s basis to find that share.
      </p>
      <p>
        New 529 accounts stay out of the drawdown order, so ordinary shortfalls in retirement never
        draw on them unless you add them.
      </p>
    </>
  ),
  sections: [
    {
      id: "set-up",
      title: "Fund tuition from a 529",
      body: (
        <>
          <Steps>
            <li>
              Add the account: <UIPath steps={["Accounts", "Add account"]} />, <em>Account Type</em>{" "}
              <em>529 Plan</em>, with today’s balance. Enter <em>Total contributions</em> if you
              know them; blank treats the whole balance as contributions.
            </li>
            <li>
              To keep saving, add a rule in <UIPath steps={["Income allocation"]} /> with the 529 as{" "}
              <em>Destination account</em>; see <HelpLink to="savings-rules" />.
            </li>
            <li>
              Add the education expense in <UIPath steps={["Expenses"]} />, with start and end
              milestones for the school years. In <em>Advanced: growth, funding and timing</em>,
              check <em>Qualified education expense</em> if the 529 may pay it through the drawdown
              order rather than as a selected account.
            </li>
            <li>
              In the expense’s <em>Advanced: growth, funding and timing</em>, use{" "}
              <em>Fund from a specific account</em> to select the 529, then a backup account such as
              checking.
            </li>
            <li>
              Open <UIPath steps={["Drawdown order"]} />, add the 529 and place it above the backup
              account’s type.
            </li>
          </Steps>
          <Callout kind="entry" title="Only selected accounts pay">
            <p>
              An expense funded from specific accounts is paid only from those accounts. If the 529
              alone is selected and runs out, the rest of the bill is unfunded, even in a year with
              surplus, and the plan counts as failing that year.
            </p>
          </Callout>
          <Callout kind="entry">
            <p>
              Among selected accounts of different types, the drawdown order decides which pays
              first; types not listed in it, including a 529 by default, come last. With the 529 and
              checking selected but the 529 not listed, checking pays the whole bill and the 529
              keeps growing. Listing the 529 also lets it cover ordinary shortfalls when it comes up
              in the order.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-it-is-calculated",
      title: "How the balance and withdrawals are calculated",
      body: (
        <>
          <p>
            The 529 grows at the start of each year like any investment account. Tuition is
            withdrawn through the year, so the dollars withdrawn don’t earn the whole year’s growth;
            CoastMath removes that unearned growth when it takes each withdrawal.
          </p>
          <Ledger
            title="Example: $25,000 of tuition from a $67,416 529 in one year, 6% growth"
            rows={[
              { label: "Opening balance", value: 67416 },
              { op: "+", label: "Growth at 6%", value: 4045 },
              { op: "−", label: "Tuition withdrawals", value: 25000, detail: "Untaxed" },
              {
                op: "−",
                label: "Growth not earned on money withdrawn during the year",
                value: 680,
              },
              { op: "=", label: "Year-end balance", value: 45781 },
            ]}
          />
          <Figure
            title="Who pays $25,000 of annual tuition: a $60,000 529, then checking"
            caption="The 529 starts two years before college with $60,000 and grows at 6%. It’s listed above checking in the drawdown order, and both accounts are selected for the expense."
            table={{
              columns: [
                { key: "year", label: "Year" },
                { key: "plan", label: "From the 529", format: "usd" },
                { key: "checking", label: "From checking", format: "usd" },
              ],
              rows: [
                { year: "College year 1", plan: 25000, checking: 0 },
                { year: "College year 2", plan: 25000, checking: 0 },
                { year: "College year 3", plan: 23577, checking: 1423 },
                { year: "College year 4", plan: 0, checking: 25000 },
              ],
            }}
          >
            <BarChart
              label="Tuition funded from the 529 and from checking in four college years"
              categories={["Year 1", "Year 2", "Year 3", "Year 4"]}
              series={[
                {
                  id: "plan",
                  label: "From the 529",
                  color: "cyan",
                  values: [25000, 25000, 23577, 0],
                },
                {
                  id: "checking",
                  label: "From checking",
                  color: "gray",
                  values: [0, 0, 1423, 25000],
                },
              ]}
            />
          </Figure>
        </>
      ),
    },
    {
      id: "taxes",
      title: "Taxes on withdrawals",
      body: (
        <>
          <p>
            Each year CoastMath adds up the qualified education expenses: every expense funded from
            a 529, and every expense marked <em>Qualified education expense</em>. Withdrawals for an
            expense funded from the 529 are always tax free. Other 529 withdrawals, such as a
            shortfall the drawdown order covers, are tax free until the year’s marked expenses are
            used up.
          </p>
          <p>
            Beyond that, a withdrawal is part contributions and part earnings, in proportion to the
            account’s balance. The earnings share is ordinary income for the year, and a 10%
            additional tax on it is paid from the withdrawal, which is grossed up so the rest still
            covers the bill.
          </p>
          <Ledger
            title="Example: $10,000 needed from a $100,000 529 with $40,000 of contributions, no qualified expenses"
            rows={[
              { label: "Earnings share of the balance", value: "60%" },
              { label: "Withdrawal", value: 10638, detail: "$10,000 ÷ (1 − 10% × 60%)" },
              { op: "−", label: "Additional tax: 10% of the $6,383 earnings share", value: 638 },
              { op: "=", label: "Left to pay the bill", value: 10000 },
            ]}
          />
          <p>
            The $6,383 of earnings is added to ordinary income that year. The account’s contribution
            basis falls by the contributions share, $4,255. A warning names the year.
          </p>
          <p>
            Optionally, <UIPath steps={["Plan details", "State deduction for 529 contributions"]} />{" "}
            subtracts the year’s 529 contributions from state taxable income, up to the state’s cap,
            in the states CoastMath has verified: Massachusetts ($1,000, or $2,000 joint), Michigan
            ($5,000 or $10,000, less qualified withdrawals), Missouri ($8,000 or $16,000), New York
            ($5,000 or $10,000) and South Carolina (no annual cap). It assumes contributions go to
            your own state’s plan.
          </p>
          <p>
            A 529 isn’t part of your gross estate for estate tax, though it counts in net worth and
            passes to heirs; see <HelpLink to="estate-tax-and-net-estate" />.
          </p>
          <Callout kind="boundary">
            <ul>
              <li>
                Exceptions to the 10% additional tax (scholarships, death or disability) and the
                education tax credits.
              </li>
              <li>
                State deductions in other states, credits instead of deductions, per-beneficiary
                caps and recapture of earlier deductions.
              </li>
              <li>
                Rollovers from a 529 to a Roth IRA, transfers out of a 529, and changes of
                beneficiary.
              </li>
              <li>Contribution limits and gift-tax elections. CoastMath applies no annual cap.</li>
              <li>Financial aid.</li>
            </ul>
          </Callout>
        </>
      ),
    },
  ],
};
export default article;

import type { Article } from "../help_types";
import { Callout, Figure, HelpLink, Ledger, Symptoms, UIPath } from "../help_kit";
import { LineChart } from "../help_charts";

const carried: [number, number][] = [
  [2026, 0],
  [2027, 0],
  [2028, 55189],
  [2029, 115189],
  [2030, 96159],
  [2031, 76678],
  [2032, 57197],
  [2033, 37716],
  [2034, 18235],
  [2035, 0],
  [2036, 0],
];

const article: Article = {
  intro: (
    <>
      <p>
        A plan runs short in a year when income, plus every account your withdrawal order can draw
        from, can’t pay that year’s spending and taxes. CoastMath doesn’t cut the spending. It
        records the unpaid amount as unfunded spending, carries it forward, and subtracts it from
        net worth until later cash repays it.
      </p>
      <p>
        The first year this happens is the plan’s failure year. It stays the failure year even if
        the plan recovers, and the Overview shows <em>Spending unfunded from</em> that year under
        the plan name.
      </p>
    </>
  ),
  sections: [
    {
      id: "how-a-shortfall-is-carried",
      title: "How a shortfall is carried",
      body: (
        <>
          <p>
            Each year, after income, spending and savings rules, CoastMath withdraws what’s needed
            in your withdrawal order. Whatever is still uncovered is added to the unfunded balance.
            Every year after that, once the year’s own spending is paid, it tries to repay the whole
            carried balance the same way, so surplus a later year deposits goes straight back out to
            clear it. Homes and other property with <em>Auto-liquidate on depletion</em> turned on
            are sold at that point to cover it, other property before a primary home.
          </p>
          <Figure
            title="Unfunded spending carried at each year-end"
            caption="A 60-year-old spends $60,000 a year from $120,000 of savings until a $90,000 pension starts at 64. Savings run out in 2028; each pension year’s surplus repays the balance until it clears in 2035. The plan’s failure year stays 2028."
            table={{
              columns: [
                { key: "year", label: "Year", format: "year" },
                { key: "carried", label: "Unfunded spending carried", format: "usd" },
              ],
              rows: carried.map(([year, value]) => ({ year, carried: value })),
            }}
          >
            <LineChart
              series={[
                {
                  id: "carried",
                  label: "Unfunded spending carried",
                  color: "magenta",
                  points: carried,
                  area: true,
                },
              ]}
              step
              markers={[
                { x: 2028, label: "Failure year" },
                { x: 2030, label: "Pension starts" },
              ]}
              label="Unfunded spending carried from 2026 to 2036: zero until 2028, peaking at $115,189 in 2029, then falling to zero by 2035 as pension surpluses repay it"
            />
          </Figure>
          <p>
            While a balance is carried it lowers net worth, so net worth can be negative with no
            debts at all: in 2029 it’s −$115,189. It also counts against the estate at the end of
            the plan.
          </p>
        </>
      ),
    },
    {
      id: "restricted-shortfalls",
      title: "Shortfalls from expenses paid from specific accounts",
      body: (
        <>
          <p>
            An expense set to <em>Fund from a specific account</em> draws only from the accounts you
            selected, in their listed order. If they can’t cover it, the rest goes unpaid and
            CoastMath doesn’t fall back to your other accounts. That unpaid amount is never repaid
            from other accounts or from later cash, so it stays in net worth for the rest of the
            plan. It also sets the failure year, even when other accounts hold plenty.
          </p>
          <Ledger
            title="Example: $15,000 of travel funded only from checking"
            rows={[
              { label: "Checking at the end of 2040", value: 32924 },
              {
                op: "−",
                label: "Unfunded spending carried",
                value: 160058,
                detail: "Travel checking couldn’t pay from 2027 to 2037",
              },
              { op: "=", label: "Net worth", value: -127134 },
            ]}
            note="The same plan as above, with the travel expense added. Checking refills from 2036, but the unpaid travel stays."
          />
          <Callout kind="where">
            <p>
              The setting is in an expense’s{" "}
              <UIPath
                steps={[
                  "Expenses",
                  "Advanced: growth, funding and timing",
                  "Fund from a specific account",
                ]}
              />
              . <em>General cash flow (default)</em> pays the expense from income and your full
              withdrawal order.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "find-the-cause",
      title: "Find the cause",
      body: (
        <>
          <p>
            Start at the failure year: select it on the Overview’s net worth chart. The year ledger
            shows <em>Unfunded spending</em> in red, and the cash-flow diagram shows a{" "}
            <em>Shortfall</em> flowing into after-tax cash. Then look at what changed that year or
            just before, in rough order of how often it’s the cause:
          </p>
          <ol>
            <li>
              Income stopped at a retirement milestone before other income started, and savings
              couldn’t bridge the gap.
            </li>
            <li>A large expense started or recurred, or spending grows faster than income.</li>
            <li>
              An account holding money isn’t in your withdrawal order, so it’s never drawn. New
              accounts are added automatically except 529 plans.
            </li>
            <li>The expense is paid from specific accounts that ran dry, as described above.</li>
            <li>
              A home or other property holds the value, but <em>Auto-liquidate on depletion</em> is
              off and no sale is scheduled; see <HelpLink to="selling-a-home" />.
            </li>
            <li>
              An account paying a substantially equal periodic payment series gives only its
              scheduled payment until the series ends.
            </li>
          </ol>
          <Symptoms
            rows={[
              {
                symptom: (
                  <>
                    <em>Spending unfunded from</em> a year under the plan name
                  </>
                ),
                check: "The failure year’s cash flow: which income ended or which expense started",
                next: (
                  <>
                    Adjust the timing, spending or savings; see <HelpLink to="withdrawal-order" />
                  </>
                ),
              },
              {
                symptom: "The status stays after the balance is repaid",
                check: (
                  <>
                    <em>Unfunded spending</em> in later years of the year ledger
                  </>
                ),
                next: "Expected: a past failure stays the failure year. Fix the first year that ran short",
              },
              {
                symptom: "A shortfall while other accounts still hold money",
                check: (
                  <>
                    The expense’s funding accounts, and <UIPath steps={["Drawdown order"]} />
                  </>
                ),
                next: "Add accounts to the expense or the withdrawal order, or switch the expense to general cash flow",
              },
              {
                symptom: (
                  <>
                    <em>Net worth negative from</em> a year, but no unfunded spending
                  </>
                ),
                check: "Debts against cash, investments and property in that year",
                next: (
                  <>
                    Spending is funded; debts exceed assets. See{" "}
                    <HelpLink to="mortgages-and-loans" />
                  </>
                ),
              },
              {
                symptom: "A withdrawal and an equal unallocated surplus in the same year",
                check: "Whether an unfunded balance was carried into that year",
                next: (
                  <>
                    That pair is the repayment; see <HelpLink to="cash-flow-view" />
                  </>
                ),
              },
            ]}
          />
          <Callout kind="boundary">
            <p>
              Unpaid spending isn’t charged interest, and no borrowing is modeled to cover it. Loan
              payments count as made in a shortfall year, adding to the unpaid amount, so debt
              balances after the failure year fall as if every payment were made.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "shortfalls-and-chance-of-success",
      title: "Shortfalls and success odds",
      body: (
        <>
          <p>
            The failure year belongs to this one steady-return projection.{" "}
            <HelpLink to="chance-of-success" /> reruns the plan across many return sequences and
            counts how many run short, so a plan can be funded here and still fail in some trials,
            or the reverse; see <HelpLink to="plan-vs-chance-of-success" />.
          </p>
        </>
      ),
    },
  ],
};

export default article;

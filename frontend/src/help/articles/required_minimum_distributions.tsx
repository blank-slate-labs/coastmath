import type { Article } from "../help_types";
import {
  Callout,
  DataTable,
  Figure,
  Formula,
  HelpLink,
  Ledger,
  Op,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";
import { LineChart } from "../help_charts";

/* Engine run: born 1953, single, $500,000 traditional IRA, 5% growth, no inflation (see sources record). */
const rmdByAge: [number, number][] = [
  [73, 18868],
  [74, 19832],
  [75, 20760],
  [76, 21730],
  [77, 22644],
  [78, 23696],
  [79, 24793],
  [80, 25937],
  [81, 26990],
  [82, 28226],
  [83, 29346],
  [84, 30678],
  [85, 31861],
  [86, 33071],
  [87, 34305],
  [88, 35300],
  [89, 36565],
  [90, 37531],
  [91, 38469],
  [92, 39367],
  [93, 40214],
  [94, 40562],
];

const uniformTable: [string, number][] = [
  ["72", 27.4],
  ["73", 26.5],
  ["74", 25.5],
  ["75", 24.6],
  ["76", 23.7],
  ["77", 22.9],
  ["78", 22.0],
  ["79", 21.1],
  ["80", 20.2],
  ["85", 16.0],
  ["90", 12.2],
  ["95", 8.9],
  ["100", 6.4],
  ["105", 4.6],
  ["110", 3.5],
  ["115", 2.9],
  ["120 and older", 2.0],
];

const article: Article = {
  intro: (
    <>
      <p>
        Once an account owner reaches their required age, CoastMath takes a required minimum
        distribution from each of their traditional IRAs and traditional 401(k)s every year. The
        amount is the account’s balance on December 31 of the prior year divided by the Uniform
        Lifetime Table distribution period for the owner’s age that year.
      </p>
      <p>
        The distribution comes out before the year’s income and spending are settled. It pays that
        year’s bills first, and anything you don’t spend is saved by your allocation rules. Its full
        amount is ordinary income, less any part a qualified charitable distribution covers.
      </p>
    </>
  ),
  sections: [
    {
      id: "when-rmds-start",
      title: "When distributions start and which accounts owe them",
      body: (
        <>
          <p>
            The start age comes from the owner’s birth year. The first distribution is taken in the
            calendar year the owner reaches that age, and every year after.
          </p>
          <DataTable
            caption="Required age by birth year"
            columns={[
              { key: "born", label: "Owner born" },
              { key: "age", label: "First distribution year" },
            ]}
            rows={[
              { born: "1950 or earlier", age: "Already required in every plan year" },
              { born: "1951 through 1959", age: "The year the owner turns 73" },
              { born: "1960 or later", age: "The year the owner turns 75" },
            ]}
          />
          <p>
            Traditional IRAs and traditional 401(k)s owe distributions. Roth IRAs and Roth 401(k)s
            don’t while the owner is alive, and neither do HSAs, brokerage or cash accounts.
            Accounts you inherited follow the beneficiary rules instead, described in{" "}
            <HelpLink to="inherited-accounts" />.
          </p>
          <p>
            Each account uses its owner’s age. An account owned by your partner starts on your
            partner’s birth year and uses your partner’s age for the divisor. If the plan models a
            partner’s death, the accounts pass to the survivor and follow the survivor’s age from
            then on (see <HelpLink to="death-of-a-partner" />
            ).
          </p>
          <p>
            To model a possible change in law, enter a different start age, from 70 to 80, for you
            or your partner. It replaces the age from the table above for that person’s own
            accounts, including the distribution owed in the year a partner dies. Accounts you
            inherited keep the beneficiary rules, which use the deceased owner’s age under current
            law. The table starts at 72, so 70 and 71 use 29.2 and 28.3 on its basis: joint life
            with a beneficiary ten years younger.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "Tax law assumptions"]} />,{" "}
              <strong>Primary person RMD start age</strong> and{" "}
              <strong>Partner RMD start age</strong>. Blank follows current law.
            </p>
          </Callout>
          <Callout kind="boundary">
            <p>
              Delaying the first distribution to April 1 of the following year isn’t modeled;
              CoastMath always takes it in the year the owner reaches the age. Neither is the
              still-working exception that lets some employees delay 401(k) distributions until they
              retire.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-the-amount-is-set",
      title: "How the amount is calculated",
      body: (
        <>
          <Formula result="Required distribution">
            <V>Account balance on December 31 of the prior year</V>
            <Op>÷</Op>
            <V>Distribution period for the owner’s age this year</V>
          </Formula>
          <p>
            The balance is the account’s value at the end of the previous plan year, before this
            year’s growth. The owner’s age is the age they reach during the calendar year.
          </p>
          <p>
            In the plan’s first year, CoastMath rebuilds the prior year-end balance from the opening
            balance you entered: withdrawals you record as already taken this year are added back
            and contributions already made are removed. Those withdrawals also count toward the
            first year’s distribution, so only the rest comes out. Market movement since December 31
            isn’t known and is ignored.
          </p>
          <Callout kind="where">
            <p>
              Record this year’s earlier withdrawals in{" "}
              <UIPath steps={["Plan details", "Earlier this tax year"]} />.
            </p>
          </Callout>
          <Ledger
            title="Example: first distribution, owner turns 73 in 2026"
            rows={[
              { label: "Traditional IRA balance on December 31, 2025", value: 500000 },
              {
                op: "÷",
                label: "Distribution period at 73",
                value: 26.5,
                format: "num",
                digits: 1,
              },
              { op: "=", label: "Required distribution for 2026", value: 18868 },
            ]}
          />
          <p>
            Each account is calculated separately and each pays its own amount. With several IRAs,
            the total matches the combined balance divided by the same period; the difference is
            only which account the money leaves.
          </p>
          <DataTable
            caption="Uniform Lifetime Table, selected ages"
            columns={[
              { key: "age", label: "Age" },
              { key: "period", label: "Distribution period", format: "num", digits: 1 },
            ]}
            rows={uniformTable.map(([age, period]) => ({ age, period }))}
            note="CoastMath uses every age in the table; 2.0 applies at 120 and older."
          />
          <p>
            When the owner’s spouse is the account’s only beneficiary for the whole year and is more
            than 10 years younger, the law allows the Joint and Last Survivor table, which gives a
            longer period and a smaller distribution. CoastMath uses it only when you say so: open
            the traditional IRA or 401(k) and check{" "}
            <strong>Spouse is the sole beneficiary of this account</strong>. Without that, or when
            the spouse is 10 years younger or less, or the plan has no spouse, the Uniform Lifetime
            table above applies. The period is looked up from both people’s ages in the year, and a
            partner’s own account uses the partner’s age with the owner as the younger spouse.
          </p>
          <Ledger
            title="Example: owner turns 75, spouse (the sole beneficiary) turns 62, $500,000 balance"
            rows={[
              { label: "Balance on December 31 of the prior year", value: 500000 },
              {
                op: "÷",
                label: "Joint and Last Survivor period at ages 75 and 62",
                value: 26.8,
                format: "num",
                digits: 1,
              },
              { op: "=", label: "Required distribution", value: 18656.72, format: "usd_cents" },
            ]}
            note="The Uniform Lifetime period at 75 is 24.6, which would require $20,325.20."
          />
          <Callout kind="boundary">
            <p>
              CoastMath cannot tell who your beneficiaries are, so the choice is yours. Check the
              box only if your spouse is the sole beneficiary all year. A spouse who is exactly 10
              years younger does not qualify.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "timing-within-the-year",
      title: "When in the year it comes out",
      body: (
        <>
          <p>
            Distributions are taken in the year’s required stage, after balances grow and before
            income, spending and savings. CoastMath treats the distribution as paid in equal monthly
            amounts over the year, so each month’s payment stops earning from the date it leaves the
            account. The account ends the year at its grown balance, less the distributions and the
            growth they would have earned.
          </p>
          <p>
            The cash counts as income for the year. It pays that year’s spending alongside wages and
            benefits before any other account is drawn on, so a year with a large distribution often
            needs no other withdrawals.
          </p>
          <Figure
            title="Required distributions by age, $500,000 IRA at 73"
            caption="Owner born 1953, 5% annual growth and no inflation. The distribution keeps rising because the divisor falls faster than the balance."
            table={{
              columns: [
                { key: "age", label: "Age" },
                { key: "rmd", label: "Required distribution", format: "usd" },
              ],
              rows: rmdByAge.map(([age, rmd]) => ({ age, rmd })),
            }}
          >
            <LineChart
              label="Required distribution by age from 73 to 94, rising from $18,868 to $40,562"
              xFormat="age"
              step
              series={[
                { id: "rmd", label: "Required distribution", color: "blue", points: rmdByAge },
              ]}
            />
          </Figure>
        </>
      ),
    },
    {
      id: "unspent-distributions",
      title: "What happens to a distribution you don’t spend",
      body: (
        <>
          <p>
            A required distribution can’t be left in the account or converted to Roth. When it’s
            more than the year’s spending and taxes need, the excess is surplus: your allocation
            rules save it in order, and anything left over goes to the default destination shown
            under the rules. A Roth conversion in the same year comes out of the balance that
            remains after the distribution.
          </p>
          <Ledger
            title="Example: owner at 76 spends $8,000"
            rows={[
              { label: "Balance on December 31 of the prior year", value: 515010 },
              {
                op: "÷",
                label: "Distribution period at 76",
                value: 23.7,
                format: "num",
                digits: 1,
              },
              { op: "=", label: "Required distribution", value: 21730 },
              { op: "−", label: "Federal income tax for the year", value: 358 },
              { op: "−", label: "Spending", value: 8000 },
              {
                op: "=",
                label: "Saved to a brokerage account by the allocation rule",
                value: 13372,
              },
            ]}
            note="Single filer, no other income. The tax is on the distribution less the standard deduction and the additional deduction at 65."
          />
          <Callout kind="where">
            <p>
              Choose where surplus goes in{" "}
              <UIPath steps={["Income allocation", "After spending"]} />. See{" "}
              <HelpLink to="savings-rules" />.
            </p>
          </Callout>
          <p>
            The tax on a distribution is settled with the rest of the year’s tax, as described in{" "}
            <HelpLink to="tax-payments-and-settlement" />.
          </p>
        </>
      ),
    },
    {
      id: "charitable-distributions",
      title: "Qualified charitable distributions",
      body: (
        <>
          <p>
            A qualified charitable distribution from a traditional IRA counts toward that owner’s
            required distribution for the year, and the part it covers isn’t taxed. It offsets only
            the giving owner’s IRA distribution: never a 401(k) distribution, and never a partner’s.
            A gift larger than the owner’s required distribution comes out of that owner’s
            traditional IRAs as an additional withdrawal, still untaxed. Eligibility, the annual
            limit and how to set it up are in <HelpLink to="charitable-giving" />.
          </p>
        </>
      ),
    },
    {
      id: "where-it-shows-up",
      title: "Where to see it and common surprises",
      body: (
        <>
          <p>
            The overview chart marks the year “RMDs begin” from your own birth year. Each year’s
            cash flow lists the distributions as “RMD” income, which also includes distributions
            from inherited accounts.
          </p>
          <Symptoms
            rows={[
              {
                symptom: "Distributions start years before or after you expect.",
                check: "The account’s owner, and that person’s birth year.",
                next: "A partner’s accounts follow the partner’s age. Correct the owner under Accounts if it’s wrong.",
              },
              {
                symptom: "The distribution is larger than your custodian’s figure.",
                check:
                  "Whether your spouse is your sole beneficiary and more than 10 years younger, or you’re still working.",
                next: "Both can lower the legal minimum. Check the spouse-beneficiary box on the account for the first; the still-working delay isn’t modeled.",
              },
              {
                symptom: "No distribution from a Roth 401(k).",
                check: "The account type.",
                next: "Expected: Roth accounts owe nothing while the owner is alive.",
              },
              {
                symptom: "An “RMD” appears well before 73.",
                check: "Whether the account is marked as inherited.",
                next: "Inherited accounts follow the beneficiary rules at any age.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};

export default article;

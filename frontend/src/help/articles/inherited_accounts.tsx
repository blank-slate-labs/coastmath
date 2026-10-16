import type { Article } from "../help_types";
import { Callout, DataTable, Figure, Formula, HelpLink, Ledger, Op, UIPath, V } from "../help_kit";
import { BarChart, Timeline } from "../help_charts";

/* Engine run: $300,000 inherited traditional IRA, owner died 2024, beneficiary born 1974, 5% growth (see sources record). */
const years = [2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034];
const afterRbd = [8746, 9191, 9658, 10149, 10666, 11209, 11781, 12381, 351381];
const beforeRbd = [0, 0, 0, 0, 0, 0, 0, 0, 455062];

const article: Article = {
  intro: (
    <>
      <p>
        An IRA or 401(k) you mark as inherited follows the beneficiary rules, not the owner rules,
        at any age. Most adult children and other non-spouse heirs of owners who died in 2020 or
        later must empty the account by the end of the 10th year after the death. If the owner had
        already reached their required beginning date, they must also take a distribution each year
        before then. Spouses and other eligible designated beneficiaries can instead stretch
        distributions over their life expectancy.
      </p>
      <p>
        CoastMath takes each year’s required amount in the year’s required stage, with owners’ own
        distributions. It counts as income for that year and is never penalized as an early
        withdrawal.
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
            Inherited treatment applies to traditional and Roth IRAs and 401(k)s. It starts when you
            enter the year the original owner died; without that year, CoastMath treats the account
            as your own.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Accounts", "Edit", "Retirement account tax history"]} />
            </p>
          </Callout>
          <DataTable
            caption="Inherited-account settings"
            columns={[
              { key: "field", label: "Setting" },
              { key: "use", label: "How CoastMath uses it" },
            ]}
            rows={[
              {
                field: "Year original owner died (inherited accounts only)",
                use: "Starts the schedule. Distributions begin the next year; the ten-year deadline counts from this year.",
              },
              {
                field: "Beneficiary relationship to original owner",
                use: "Surviving spouse, other eligible designated beneficiary, or other individual beneficiary.",
              },
              {
                field: "Distribution election",
                use: "The beneficiary’s default, life expectancy, the ten-year election, or, for a spouse, treating the account as the spouse’s own after the year of death.",
              },
              {
                field: "Original owner’s birth year",
                use: "Sets the owner’s remaining life expectancy and, for a spouse, the year the owner would have reached the required age.",
              },
              {
                field: "Death relative to the required beginning date",
                use: "On or after means annual distributions under the ten-year rule and the owner’s life expectancy as a floor. Traditional accounts only.",
              },
              {
                field: "Beneficiary was the original owner’s minor child",
                use: "Life expectancy distributions until 21, then the account must be empty by the 10th year after.",
              },
              {
                field: "Unpaid original-owner RMD in year of death ($)",
                use: "Taken in the year of death, when that year is part of the plan.",
              },
            ]}
          />
          <p>
            The beneficiary is the account’s owner in the plan, and their age each year drives the
            schedule. An inherited account can’t receive contributions.
          </p>
          <Callout kind="entry">
            <p>
              If you don’t know whether the owner died on or after the required beginning date,
              leave it as Unknown: CoastMath assumes before, which means no annual distributions
              under the ten-year rule. A missing birth year means a spouse starts in the year after
              death and the owner’s life expectancy isn’t considered. The projection shows a warning
              until both are filled in.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "beneficiary-schedules",
      title: "Which schedule applies",
      body: (
        <>
          <DataTable
            caption="Default schedule by beneficiary"
            columns={[
              { key: "who", label: "Beneficiary" },
              { key: "before", label: "Owner died before the required beginning date" },
              { key: "after", label: "Owner died on or after it" },
            ]}
            rows={[
              {
                who: "Other individual, death in 2020 or later",
                before: "Nothing required until the 10th year after death, then the whole balance.",
                after:
                  "Annual life expectancy distributions, then the whole balance in the 10th year.",
              },
              {
                who: "Other individual, death before 2020",
                before: "Annual life expectancy distributions, no deadline.",
                after: "Annual life expectancy distributions, no deadline.",
              },
              {
                who: "Eligible designated beneficiary",
                before:
                  "Annual life expectancy distributions, no deadline, or the ten-year election.",
                after: "Annual life expectancy distributions, no deadline.",
              },
              {
                who: "Minor child of the owner",
                before:
                  "Life expectancy distributions, then empty by the 10th year after turning 21.",
                after: "The same.",
              },
              {
                who: "Surviving spouse",
                before:
                  "Life expectancy distributions starting the later of the year after death or the year the owner would have reached the required age.",
                after: "Life expectancy distributions starting the year after death.",
              },
            ]}
            note="Eligible designated beneficiaries are the surviving spouse, a minor child, a disabled or chronically ill person, and anyone no more than 10 years younger than the owner."
          />
          <p>
            A spouse who chooses to treat the account as their own is switched to owner rules from
            the year after death: required distributions start at the spouse’s own required age and
            use the Uniform Lifetime Table, as described in{" "}
            <HelpLink to="required-minimum-distributions" />.
          </p>
        </>
      ),
    },
    {
      id: "annual-amount",
      title: "How the annual amount is calculated",
      body: (
        <>
          <Formula result="Annual distribution">
            <V>Account balance on December 31 of the prior year</V>
            <Op>÷</Op>
            <V>Remaining life expectancy</V>
          </Formula>
          <p>
            Life expectancy comes from the Single Life Table. A beneficiary other than a spouse
            looks up their age in the year after the death once, then subtracts one for each later
            year. A spouse looks up their current age every year. When the owner died on or after
            the required beginning date, CoastMath also works out the owner’s remaining life
            expectancy (the owner’s age in the year of death, less one for each year since) and uses
            whichever is longer. Once the divisor reaches 1, the whole balance comes out.
          </p>
          <Ledger
            title="Example: non-spouse beneficiary, owner died in 2024 at 80"
            rows={[
              {
                label: "Beneficiary’s life expectancy at 51, the age in 2025",
                value: 35.3,
                format: "num",
                digits: 1,
              },
              { op: "−", label: "Years since 2025", value: 1, format: "num" },
              {
                op: "=",
                label: "Divisor for 2026",
                value: 34.3,
                format: "num",
                digits: 1,
                detail: "Longer than the owner’s 9.2 (11.2 at 80, less 2 years), so it applies",
              },
              { label: "Inherited IRA balance on December 31, 2025", value: 300000 },
              { op: "÷", label: "Divisor for 2026", value: 34.3, format: "num", digits: 1 },
              { op: "=", label: "Required distribution for 2026", value: 8746 },
            ]}
          />
          <p>
            For deaths from 2020 on, annual distributions under the ten-year rule begin in 2025; no
            distribution was required for 2021 through 2024. The divisor still counts down from the
            year after the death, so a 2021 death uses a divisor already reduced by three years in
            2025.
          </p>
        </>
      ),
    },
    {
      id: "ten-year-deadline",
      title: "The ten-year deadline",
      body: (
        <>
          <p>
            The account must be empty by December 31 of the 10th year after the year of death. In
            that year CoastMath distributes the entire remaining balance, including that year’s
            growth, as one distribution. For a traditional account the whole amount is ordinary
            income in that single year.
          </p>
          <Timeline
            label="Ten-year window for a 2024 death: annual distributions 2025 to 2033, account emptied in 2034"
            unit="year"
            from={2024}
            to={2035}
            spans={[
              {
                from: 2025,
                to: 2034,
                label: "Annual distributions (owner died on or after the required beginning date)",
                color: "blue",
                row: 0,
              },
              {
                from: 2025,
                to: 2034,
                label: "No minimum (owner died before it)",
                color: "gray",
                row: 1,
              },
            ]}
            events={[
              { at: 2024, label: "Owner dies" },
              { at: 2034, label: "Account must be empty" },
            ]}
          />
          <Figure
            title="Distributions from a $300,000 inherited IRA, owner died in 2024"
            caption="5% annual growth, no other withdrawals from the account. Without annual distributions, the balance keeps growing and comes out in one year."
            table={{
              columns: [
                { key: "year", label: "Year" },
                { key: "after", label: "On or after the required beginning date", format: "usd" },
                { key: "before", label: "Before it", format: "usd" },
              ],
              rows: years.map((year, i) => ({ year, after: afterRbd[i], before: beforeRbd[i] })),
            }}
          >
            <BarChart
              label="Yearly distributions 2026 to 2034 for each case; both end with a final distribution in 2034"
              categories={years}
              stacked={false}
              series={[
                { id: "after", label: "Owner died on or after", color: "blue", values: afterRbd },
                { id: "before", label: "Owner died before", color: "gray", values: beforeRbd },
              ]}
            />
          </Figure>
          <Callout kind="boundary">
            <p>
              CoastMath takes only what the rules require. It doesn’t spread the balance over the
              window on its own; the account is drawn earlier only if your drawdown order uses it to
              fund spending (see <HelpLink to="withdrawal-order" />
              ).
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "inherited-roth",
      title: "Inherited Roth accounts",
      body: (
        <>
          <p>
            A Roth owner never has a required beginning date, so an inherited Roth account has no
            annual distributions under the ten-year rule: an individual beneficiary must only empty
            it by the 10th year. Eligible designated beneficiaries still take life expectancy
            distributions, and a spouse can treat it as their own, which ends required
            distributions.
          </p>
          <p>
            Distributions are tax-free once five years have passed since the original owner’s first
            Roth contribution. Before that, contributions and conversions come out first and
            tax-free; earnings are taxed but never penalized. An inherited Roth IRA keeps its own
            contribution history, separate from your own Roth IRAs.
          </p>
          <Callout kind="entry">
            <p>
              For an inherited Roth IRA, enter the original owner’s first Roth contribution year
              under “Enter Roth contribution and conversion history”. If it’s blank, the five-year
              clock starts at the plan’s start.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "limits-of-the-model",
      title: "What isn’t modeled",
      body: (
        <>
          <Callout kind="boundary">
            <ul>
              <li>Accounts inherited by an estate, trust or other non-individual beneficiary.</li>
              <li>
                A beneficiary of an inherited account dying within the plan; a plan that models it
                can’t be calculated.
              </li>
              <li>
                Taking more than the minimum on a schedule you choose, other than through your
                drawdown order.
              </li>
            </ul>
          </Callout>
          <p>
            When the plan models your partner’s death, their retirement accounts become the
            survivor’s own and follow owner rules; the settings here are for accounts you already
            hold as a beneficiary. See <HelpLink to="death-of-a-partner" />. Distributions appear in
            each year’s cash flow as “RMD” income.
          </p>
        </>
      ),
    },
  ],
};

export default article;

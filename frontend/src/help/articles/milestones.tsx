import type { Article } from "../help_types";
import { Callout, DataTable, Figure, HelpLink, Ledger, Symptoms, UIPath } from "../help_kit";
import { Timeline } from "../help_charts";

// Month positions as fractions of a year: June starts 5/12 of the way through.
const june = 5 / 12;

const article: Article = {
  intro: (
    <>
      <p>
        A milestone is a moment in your plan, set by an age, a date, a net-worth level, a financial
        independence test, combined conditions or an offset from another milestone. CoastMath checks
        milestones at the start of every projection year, before anything else happens that year.
        Once a milestone is reached, it stays reached. Incomes, expenses, loans and rules that start
        or end at a milestone follow it, and the month it takes effect decides how much of that year
        they run.
      </p>
    </>
  ),
  sections: [
    {
      id: "trigger-types",
      title: "Trigger types",
      body: (
        <>
          <Callout kind="where">
            <p>
              <UIPath steps={["Milestones", "Add milestone"]} />. <strong>Retirement</strong> and{" "}
              <strong>Partner retirement</strong> take only an age; Partner retirement takes the
              partner’s age and saves it as yours. <strong>Custom</strong> takes a name and a{" "}
              <strong>Trigger Type</strong>.
            </p>
          </Callout>
          <DataTable
            caption="When each trigger type takes effect"
            columns={[
              { key: "type", label: "Trigger Type" },
              { key: "year", label: "Year it takes effect" },
              { key: "month", label: "Month" },
            ]}
            rows={[
              {
                type: "Age",
                year: "The year you reach that age",
                month:
                  "Your birth month, or later for a fractional age: 59.5 falls six months after it",
              },
              {
                type: "Date",
                year: "The date’s year",
                month: "The date’s month; the day is ignored",
              },
              {
                type: "Net worth reaches",
                year: "The year after net worth first reaches the amount",
                month: "January",
              },
              {
                type: "Financial independence (multiple of expenses)",
                year: "The year after the balance first exceeds the multiple of that year’s spending",
                month: "January",
              },
              {
                type: "Conditions",
                year: "The first year all or any conditions hold, or a fire deadline is reached",
                month: "Latest required month for All; earliest qualifying month for Any",
              },
              {
                type: "Relative to another milestone",
                year: "The other milestone’s year plus the offset",
                month: "The other milestone’s month for an age or date base; otherwise January",
              },
            ]}
          />
          <Callout kind="entry">
            <ul>
              <li>
                <strong>Age</strong> is always the plan owner’s age. If no birth month is set,
                January is used. For a partner’s age, use a Date milestone.
              </li>
              <li>
                <strong>Net Worth ($)</strong> is in nominal (future) dollars. It includes property,
                minus debt.
              </li>
              <li>
                <strong>Offset (years)</strong> is a whole number of years, from −100 to 100.
              </li>
            </ul>
          </Callout>
          <p>
            Net-worth and financial independence milestones depend on how the projection turns out,
            so CoastMath tests them against the balance at the end of the previous year.{" "}
            <HelpLink to="financial-independence-estimate" /> explains that test in detail. A
            negative offset works only from a milestone with a fixed date, such as an age or date
            milestone. CoastMath can’t place a milestone before a net-worth or financial
            independence milestone, because that year isn’t known in advance, and the projection
            reports an error.
          </p>
        </>
      ),
    },
    {
      id: "combined-conditions",
      title: "Combine conditions and set a deadline",
      body: (
        <>
          <p>
            Choose <strong>Conditions</strong> under <strong>Trigger Type</strong>, then match{" "}
            <strong>All conditions</strong> or <strong>Any condition</strong>. Add up to ten age,
            year, date, milestone or metric conditions. For example, combine your age of 50 with
            liquid net worth at least 25 times annual spending averaged over three years.
          </p>
          <p>
            Balances and debt use the opening balances of the projection year. Annual spending is
            the completed year’s expenses before taxes, annualized for a partial first year. Passive
            income includes investment income (including realized gains), pensions, annuities,
            Social Security and rent, excluding wages and self-employment. Savings rate is
            contributions, including employer contributions and saved surplus but excluding
            reinvested income and transfers, divided by gross income. Both income metrics use the
            most recently completed simulated year.
          </p>
          <p>
            <strong>Today's dollars</strong> grows your threshold with cumulative plan inflation.{" "}
            <strong>Multiple of metric</strong> compares against the average of the selected metric
            over up to the specified number of completed simulated years. Early in a projection,
            only available years count; a metric with no completed year cannot satisfy the
            condition. Savings rates use percent, so enter 20 for 20%.
          </p>
          <p>
            <strong>Set a deadline</strong> using an age, year, date or another milestone.{" "}
            <strong>Fire if not reached</strong> makes the milestone take effect at that deadline.{" "}
            <strong>Mark missed if not reached</strong> permanently leaves it unreached; items tied
            to its start never begin. Conditions are checked in the deadline year before it is
            marked missed. A missed milestone counts as unreached on the Success odds tab.
          </p>
          <Callout kind="boundary">
            <p>
              Age and date conditions preserve their month. All conditions takes the latest required
              month; Any condition takes the earliest qualifying month. Financial conditions use
              January because balances are evaluated at year start. A negative milestone offset can
              anticipate a fixed age or date milestone; it cannot predict a future financial
              threshold. A partner’s age condition needs a partner profile.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "when-in-the-year",
      title: "When in the year a milestone takes effect",
      body: (
        <>
          <p>
            In the year a milestone takes effect, an item that <strong>starts</strong> at it begins
            in the milestone’s month. An item that <strong>ends</strong> at it runs through the
            month before. If you set a start or end month on the item, that month is used instead.
            In other years the item runs the full year or not at all.
          </p>
          <Ledger
            title="Example: salary ending at a Retirement milestone at age 60, birth month June"
            rows={[
              { label: "Annual salary", value: 120000 },
              { op: "×", label: "January through May", value: "5 ÷ 12" },
              { op: "=", label: "Salary in the retirement year", value: 50000 },
              { label: "Annual travel budget starting at Retirement", value: 24000 },
              { op: "×", label: "June through December", value: "7 ÷ 12" },
              { op: "=", label: "Travel in the retirement year", value: 14000 },
            ]}
          />
          <Figure
            title="Items tied to three linked milestones, for someone born in June 1975"
            caption="Retirement is at age 60. “Two years before retirement” and “Downsize” are relative milestones with offsets of −2 and +5. Move Retirement, and the other two milestones and every item attached to them move with it."
            table={{
              columns: [
                { key: "year", label: "Year" },
                { key: "salary", label: "Salary", format: "usd" },
                { key: "bridge", label: "Bridge ($12,000 a year)", format: "usd" },
                { key: "travel", label: "Travel ($24,000 a year)", format: "usd" },
              ],
              rows: [
                { year: 2033, salary: 120000, bridge: 7000, travel: 0 },
                { year: 2034, salary: 120000, bridge: 12000, travel: 0 },
                { year: 2035, salary: 50000, bridge: 5000, travel: 14000 },
                { year: 2036, salary: 0, bridge: 0, travel: 24000 },
                { year: 2040, salary: 0, bridge: 0, travel: 10000 },
                { year: 2041, salary: 0, bridge: 0, travel: 0 },
              ],
            }}
          >
            <Timeline
              label="Salary runs until June 2035; a bridge expense runs from June 2033 to June 2035; travel runs from June 2035 to June 2040"
              unit="year"
              from={2030}
              to={2042}
              spans={[
                { from: 2030, to: 2035 + june, label: "Salary", color: "blue", row: 0 },
                { from: 2033 + june, to: 2035 + june, label: "Bridge", color: "magenta", row: 1 },
                { from: 2035 + june, to: 2040 + june, label: "Travel", color: "magenta", row: 1 },
              ]}
              events={[
                { at: 2033 + june, label: "Two years before" },
                { at: 2035 + june, label: "Retirement" },
                { at: 2040 + june, label: "Downsize" },
              ]}
            />
          </Figure>
          <p>
            Because net-worth and financial independence milestones take effect in January, a salary
            that ends at one of them stops at the start of that year and pays nothing in it. An age
            milestone in January works the same way: an item ending at it has nothing left to run in
            that year.
          </p>
        </>
      ),
    },
    {
      id: "before-the-plan-starts",
      title: "Milestones reached before the plan starts",
      body: (
        <>
          <p>
            A milestone that falls before the plan starts is in effect from the first year. This
            covers an age you’ve already passed, a past date, or a negative offset that lands in the
            past. Items that start at it run the whole first year. Items that end at it never run.
            In the milestone list, it shows “reached <em>year</em>, before the plan starts in{" "}
            <em>year</em>; already in effect”.
          </p>
        </>
      ),
    },
    {
      id: "what-attaches",
      title: "What can follow a milestone",
      body: (
        <>
          <p>These can start and end at milestones:</p>
          <ul>
            <li>Income streams</li>
            <li>Expenses</li>
            <li>Savings rules</li>
            <li>The flexible spending rule</li>
            <li>Charitable giving</li>
            <li>Marketplace health coverage</li>
          </ul>
          <p>
            A loan’s <strong>Payoff milestone</strong> pays it off (see{" "}
            <HelpLink to="mortgages-and-loans#paying-off-early" />
            ). An item with no start milestone begins when the plan starts. An item with no end
            milestone runs until the plan ends. An item whose start milestone is never reached never
            begins. When an income or expense has a start milestone that falls after its end
            milestone, or an end milestone that is reached while its start never is, the projection
            warns that it never runs.
          </p>
          <h3>Switch a milestone off</h3>
          <p>
            To try a plan without a milestone but keep its settings and links, edit it and clear{" "}
            <strong>Active</strong>. A switched-off milestone is listed as inactive and never takes
            effect, and it never misses a deadline. Everything that refers to it treats it as never
            reached: an item that starts at it never begins, an item that ends at it runs to the
            plan end, a relative milestone based on it never takes effect, a condition on it is
            never met and a deadline set by it never arrives. Check <strong>Active</strong> again to
            restore it.
          </p>
          <Callout kind="entry">
            <p>
              Deleting a milestone unlinks it from incomes, expenses, savings rules and loans. An
              item that started at it then starts at the plan start, and one that ended at it runs
              to the plan end. A relative milestone based on the deleted one never takes effect. You
              can’t delete a milestone that bounds the flexible spending rule until you change that
              rule.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "across-trials",
      title: "Milestones in Success odds",
      body: (
        <>
          <p>
            Age, date and relative-to-date milestones fall in the same year in every trial.
            Net-worth and financial independence milestones depend on returns, so each trial reaches
            them in a different year, or never. The <strong>Milestone timing</strong> table under{" "}
            <UIPath steps={["Success odds"]} /> shows how often each milestone was reached. It also
            shows the 10th-percentile, median and 90th-percentile years among the trials that
            reached it. See <HelpLink to="chance-of-success" />.
          </p>
        </>
      ),
    },
    {
      id: "common-surprises",
      title: "Common surprises",
      body: (
        <>
          <Symptoms
            rows={[
              {
                symptom: "A net-worth milestone lands a year after the chart crosses the amount.",
                check: "The year-end net worth on the Overview chart.",
                next: "This is expected: the milestone takes effect the following January.",
              },
              {
                symptom: "Salary still appears in the retirement year.",
                check: "Your birth month.",
                next: "Pay runs through the month before your birthday month. Set an End month on the income to change this.",
              },
              {
                symptom: "An expense tied to a milestone never appears.",
                check: "Is that milestone listed as “not reached in projection”?",
                next: "Lower the threshold, or use an age or date milestone.",
              },
              {
                symptom: "A relative milestone lands in January instead of its base’s month.",
                check: "Is its base a net-worth or financial independence milestone?",
                next: "This is expected: those bases always take effect in January.",
              },
              {
                symptom: "An income never stops, or an expense never starts.",
                check: "Is the milestone it ends or starts at listed as inactive?",
                next: "Edit the milestone and check Active.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

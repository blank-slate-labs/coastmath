import type { Article } from "../help_types";
import {
  Callout,
  DataTable,
  Formula,
  HelpLink,
  KeyFigures,
  Ledger,
  Op,
  UIPath,
  V,
} from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        Plan accuracy scores how complete your plan’s inputs are, from 0 to 100. Each check looks
        for an input that moves the whole projection when it is missing. Checks that don’t fit your
        plan are left out of the score. Review items flag assumptions and events that look unusual.
        They are listed, but they never change the score.
      </p>
    </>
  ),
  sections: [
    {
      id: "checks",
      title: "What each check looks for",
      body: (
        <>
          <DataTable
            caption="Completeness checks"
            columns={[
              { key: "check", label: "Check" },
              { key: "weight", label: "Weight", format: "num" },
              { key: "passes", label: "Passes when" },
              { key: "applies", label: "Applies to" },
            ]}
            rows={[
              {
                check: "Account balances",
                weight: 20,
                passes: "Your accounts add up to more than $0.",
                applies: "Every plan",
              },
              {
                check: "Expenses",
                weight: 20,
                passes: "At least one expense is more than $0.",
                applies: "Every plan",
              },
              {
                check: "Your Social Security",
                weight: 15,
                passes: "A switched-on Social Security income stream is yours.",
                applies: "Plans taxed in the US",
              },
              {
                check: "Partner’s Social Security",
                weight: 15,
                passes: "A switched-on Social Security income stream is your partner’s.",
                applies: "US plans with a partner",
              },
              {
                check: "Salary ends",
                weight: 10,
                passes: "Every salary has an End milestone that is reached in the projection.",
                applies: "Plans with recurring employment or self-employment income",
              },
              {
                check: "Coverage before Medicare",
                weight: 10,
                passes:
                  "Health coverage costs are modeled with marketplace coverage, or an itemized medical budget, for each person who needs it.",
                applies:
                  "US plans where someone is younger than their Medicare age when the household’s last salary ends",
              },
            ]}
          />
          <ul>
            <li>
              <strong>Salary</strong> means recurring pay above $0 that starts in the projection.
              One-time pay and switched-off streams are skipped. An End milestone that is never
              reached leaves the salary running to the end of the plan, so it doesn’t pass.
            </li>
            <li>
              <strong>Coverage before Medicare</strong> uses the year the household’s last salary
              ends, or the plan’s first year when nobody has one. Anyone younger than 65 that year,
              or a later Medicare start age you set for them, needs coverage. With marketplace
              coverage, a partner needs <strong>Partner is covered on the same policy</strong> left
              on.
            </li>
          </ul>
          <Callout kind="boundary">
            <p>
              Health insurance entered as an ordinary expense doesn’t count as coverage. The check
              reads only <UIPath steps={["Plan", "Health coverage"]} />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "score",
      title: "How the score is calculated",
      body: (
        <>
          <Formula
            result="Plan accuracy"
            note="Rounded to the nearest whole number, halves up. A plan with no applicable checks scores 100."
          >
            <V>Weight of passing checks</V>
            <Op>÷</Op>
            <V>Weight of applicable checks</V>
            <Op>×</Op>
            <V>100</V>
          </Formula>
          <Ledger
            title="Example: one account, a salary with no end, nothing else"
            rows={[
              { label: "Account balances passes", value: 20, format: "num" },
              {
                op: "+",
                label: "Expenses, Your Social Security and Salary ends fail",
                value: 45,
                format: "num",
              },
              { op: "=", label: "Applicable weight", value: 65, format: "num" },
              { op: "→", label: "Score: 20 ÷ 65 × 100", value: 31, format: "num" },
            ]}
            note="Single person with a $100,000 brokerage account entered without basis and a $120,000 salary. Coverage before Medicare doesn’t apply while the salary never ends. The blank basis is a review item."
          />
        </>
      ),
    },
    {
      id: "review-items",
      title: "Review items",
      body: (
        <>
          <KeyFigures
            items={[
              {
                label: "Stock return above inflation",
                value: 0.08,
                format: "pct",
                digits: 0,
                detail: "Flagged above this in any projected year",
              },
              {
                label: "Inflation",
                value: 0.01,
                format: "pct",
                digits: 0,
                detail: "Flagged below this in any projected year",
              },
            ]}
          />
          <ul>
            <li>
              <strong>Stock return over 8% after inflation:</strong> the stock return is price
              growth plus dividend yield. It is compared with inflation as (1 + return) ÷ (1 +
              inflation) − 1. Exactly 8% isn’t flagged. Both thresholds are CoastMath’s planning
              choices, not rules.
            </li>
            <li>
              <strong>Inflation under 1%:</strong> exactly 1% isn’t flagged.
            </li>
            <li>
              <strong>Never runs:</strong> an income stream or expense whose Start milestone is
              never reached, or is reached after its End milestone. Streams that start at a
              switched-off milestone are skipped.
            </li>
            <li>
              <strong>Missed milestone:</strong> a milestone with a deadline set to miss that the
              projection doesn’t reach in time.
            </li>
            <li>
              <strong>Social Security is $0:</strong> a benefit entered as an amount of $0.
            </li>
            <li>
              <strong>Basis assumed equal to balance:</strong> a taxable brokerage or crypto account
              with a balance and a blank cost basis.
            </li>
          </ul>
          <Callout kind="entry">
            <p>
              A blank cost basis is projected as equal to the balance, so no gain is taxed on the
              opening position. Enter the real basis if the account holds gains.
            </p>
          </Callout>
          <p>
            Assumption checks cover every projected year, so an age-based curve is flagged in the
            years it crosses a threshold. Milestone items come from one projection of the saved plan
            (see <HelpLink to="milestones" />
            ).
          </p>
        </>
      ),
    },
    {
      id: "where",
      title: "Where it appears",
      body: (
        <>
          <Callout kind="where">
            <p>
              <UIPath steps={["Checkup", "Plan accuracy"]} /> lists missing inputs first, by weight,
              then review items. Each one opens the editor section that changes it. The score
              reloads after every saved change.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "what-it-is-not",
      title: "What the score doesn’t measure",
      body: (
        <>
          <p>
            The score isn’t a probability and doesn’t judge your plan’s outcome. A plan that runs
            out of money can score 100, and a plan with no Social Security can succeed. It counts
            only whether the inputs above are entered. For outcomes, see{" "}
            <HelpLink to="chance-of-success" />.
          </p>
        </>
      ),
    },
  ],
};
export default article;

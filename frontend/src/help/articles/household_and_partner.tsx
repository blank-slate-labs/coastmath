import type { Article } from "../help_types";
import { Callout, DataTable, HelpLink, Steps, UIPath } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        A two-person plan needs four things: a joint or separate filing status, a partner profile
        with birth year and life expectancy, an owner on every account, and a recipient on every
        income stream. CoastMath then applies each person’s own age and limits to what they own and
        earn, and computes one household tax return each year.
      </p>
    </>
  ),
  sections: [
    {
      id: "set-up",
      title: "Set up a two-person plan",
      body: (
        <>
          <Steps>
            <li>
              In <strong>Plan details</strong>, choose <strong>Filing status</strong>. For{" "}
              <strong>Married Filing Separately</strong>, also check{" "}
              <strong>Lived apart from spouse for the entire tax year</strong> if it applies; it
              changes how Social Security is taxed. Enter <strong>Children’s birth years</strong>{" "}
              for the child tax credit; see{" "}
              <HelpLink to="federal-brackets-and-deductions#child-tax-credit" />.
            </li>
            <li>
              In <strong>Partner and estate</strong>, check <strong>Plan includes a partner</strong>{" "}
              (already checked when the plan was created with{" "}
              <strong>Planning with a partner</strong>) and enter{" "}
              <strong>Partner birth year</strong>, <strong>Partner birth month</strong> and{" "}
              <strong>Partner life expectancy (age)</strong>. Click{" "}
              <strong>Save estate settings</strong>.
            </li>
            <li>
              In <strong>Accounts</strong>, set <strong>Owner</strong> on each account to{" "}
              <strong>Primary person</strong>, <strong>Partner</strong> or <strong>Joint</strong>.
            </li>
            <li>
              In <strong>Income streams</strong>, set <strong>Income recipient</strong> on each
              salary, pension and Social Security stream to <strong>Primary person</strong> or{" "}
              <strong>Partner</strong>.
            </li>
            <li>
              Back in <strong>Partner and estate</strong>, choose the <strong>Plan ends</strong> and{" "}
              <strong>Filing status after partner’s death</strong>; see{" "}
              <HelpLink to="death-of-a-partner" />.
            </li>
          </Steps>
          <Callout kind="entry">
            <p>
              A blank <strong>Partner birth month</strong> is treated as January. The birth month
              sets when the partner’s Social Security starts at a claiming age, when Medicare begins
              and, with the default horizon, the month of their modeled death.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              Your own birth month and life expectancy are <strong>Birth month</strong> and{" "}
              <strong>Longevity age</strong> in <UIPath steps={["Plan details"]} />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "what-each-person-controls",
      title: "What depends on each person",
      body: (
        <>
          <p>
            Ownership decides whose age and limits apply. CoastMath tracks each partner’s age every
            year from their birth year.
          </p>
          <DataTable
            caption="Rules applied per person"
            columns={[
              { key: "rule", label: "Rule" },
              { key: "follows", label: "Follows" },
            ]}
            rows={[
              {
                rule: "IRA, 401(k) and HSA contribution limits and catch-ups",
                follows:
                  "The account owner’s age and earned income; on a joint return, IRAs can use the couple’s combined earned income",
              },
              {
                rule: "Required minimum distributions",
                follows: "The account owner’s age and birth year",
              },
              { rule: "Early-withdrawal penalty before 59½", follows: "The account owner’s age" },
              {
                rule: "Social Security claiming age and start",
                follows: "The income recipient’s age and birth month",
              },
              { rule: "Social Security payroll tax wage base", follows: "Each earner’s own wages" },
              { rule: "Income that stops at death", follows: "The income recipient" },
            ]}
          />
          <p>
            Joint accounts can’t hold IRAs or 401(k)s and don’t receive retirement-account
            contributions. For rules that need an age, a joint account uses yours.
          </p>
          <p>
            See <HelpLink to="contributions-and-employer-match" />,{" "}
            <HelpLink to="required-minimum-distributions" /> and <HelpLink to="social-security" />{" "}
            for each rule.
          </p>
        </>
      ),
    },
    {
      id: "filing-status-and-tax",
      title: "How filing status affects tax",
      body: (
        <>
          <p>
            Each year CoastMath computes one federal return, one state return and any local return
            for the household, with all income entered in the plan. The filing status selects the
            brackets, standard deduction, capital-gains thresholds, Social Security taxation
            thresholds and other status-dependent limits. Taxes that apply per person, such as the
            Social Security payroll tax, are computed per person first.
          </p>
          <p>
            Add a Filing status change in Plan details for a year or milestone. Your marital status
            at year end controls that entire tax year: a marriage in December changes that year’s
            filing status. Later scheduled changes apply in date order; the last listed change wins
            if dates match. Death-driven changes take precedence after a death. See{" "}
            <HelpLink to="how-taxes-are-calculated" />.
          </p>
          <Callout kind="boundary">
            <ul>
              <li>
                With <strong>Married Filing Separately</strong>, CoastMath still computes a single
                return containing both partners’ income. It doesn’t split income into two returns or
                compare joint and separate filing.
              </li>
              <li>An unmarried couple is taxed as one filer with the combined income.</li>
              <li>
                A filing status change does not add or remove partner-owned accounts or income. Set
                their own timing separately.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
    {
      id: "check-the-setup",
      title: "Check the setup",
      body: (
        <>
          <p>The Overview lists a household-mismatch warning when the plan is inconsistent:</p>
          <ul>
            <li>
              an account or income stream belongs to a partner, but the plan has no partner profile;
            </li>
            <li>
              the filing status is <strong>Married Filing Jointly</strong>, but the plan has no
              partner profile.
            </li>
          </ul>
          <p>
            Removing a partner doesn’t move their accounts or income. Reassign them first under{" "}
            <UIPath steps={["Accounts", "Owner"]} /> and{" "}
            <UIPath steps={["Income streams", "Income recipient"]} />.
          </p>
          <p>
            For what happens when a partner dies, and how survivor benefits are handled, see{" "}
            <HelpLink to="death-of-a-partner" /> and <HelpLink to="survivor-social-security" />.
          </p>
        </>
      ),
    },
  ],
};

export default article;

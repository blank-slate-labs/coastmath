import type { Article } from "../help_types";
import { Callout, DataTable, Figure, HelpLink, Ledger, Symptoms, UIPath } from "../help_kit";
import { Timeline } from "../help_charts";

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath models a death as happening at a partner’s life expectancy. What follows depends
        on the projection horizon. By default the projection ends with you, and only a partner who
        dies before you is modeled. With the household horizon it runs until the longer-lived
        partner’s life expectancy, whichever of you dies first.
      </p>
      <p>
        In both, the year of death keeps the plan’s filing status and later years use the one you
        choose for the survivor. The deceased partner’s income stops, their accounts become the
        survivor’s, and their taxable accounts can get a basis step-up.
      </p>
    </>
  ),
  sections: [
    {
      id: "two-horizons",
      title: "The two projection horizons",
      body: (
        <>
          <DataTable
            caption="How each horizon handles a death"
            columns={[
              { key: "topic", label: "" },
              { key: "primary", label: "At your longevity age" },
              { key: "household", label: "At the last survivor’s longevity age" },
            ]}
            rows={[
              {
                topic: "Last projected year",
                primary: "The year before you reach your life expectancy",
                household: "The year the longer-lived partner reaches theirs",
              },
              {
                topic: "If you die first",
                primary: "The projection ends; your partner’s later years aren’t shown",
                household: "The projection continues for your partner",
              },
              {
                topic: "Partner’s modeled death",
                primary: "Their birth month, in the year they reach their life expectancy",
                household: "December 31 of the year they reach it",
              },
              {
                topic: "Their income stops",
                primary: "At the end of the month before their birth month",
                household: "At the end of that year",
              },
              {
                topic: "Their accounts pass to the survivor",
                primary: "January of the death year",
                household: "January after the death year",
              },
              {
                topic: "Joint accounts",
                primary: "Stay joint",
                household: "Become the survivor’s",
              },
              {
                topic: "Filing status after death",
                primary: "Any of the four options",
                household: "Single or Head of household",
              },
              {
                topic: "Survivor Social Security",
                primary: "Not available",
                household: "Optional",
              },
            ]}
          />
          <p>
            The household horizon needs the partner’s birth year and life expectancy; without a life
            expectancy the projection won’t run. If you both reach your life expectancies in the
            same year, no one is treated as a survivor and the projection ends that year.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Partner and estate", "Plan ends"]} />. Your partner’s life expectancy
              is <strong>Partner life expectancy (age)</strong> in the same section; yours is{" "}
              <strong>Longevity age</strong> in <UIPath steps={["Plan details"]} />.
            </p>
          </Callout>
          <Figure
            title="Household horizon: Alex (born 1956, life expectancy 77) and Sam (born 1968, life expectancy 92)"
            caption="Alex’s accounts become Sam’s in January 2034, before that year’s growth and withdrawals."
          >
            <Timeline
              label="Alex is modeled through 2033; Sam through 2060; joint returns through 2033 and single returns from 2034"
              unit="year"
              from={2026}
              to={2061}
              spans={[
                { from: 2026, to: 2034, label: "Alex", color: "blue", row: 0 },
                { from: 2026, to: 2061, label: "Sam", color: "blue", row: 1 },
                { from: 2026, to: 2034, label: "Joint return", color: "gray", row: 2 },
                { from: 2034, to: 2061, label: "Single return", color: "gray", row: 2 },
              ]}
              events={[{ at: 2034, label: "Accounts pass to Sam" }]}
            />
          </Figure>
        </>
      ),
    },
    {
      id: "filing-status",
      title: "Filing status after a death",
      body: (
        <>
          <p>
            The year of death keeps the plan’s filing status, so a married couple files one last
            joint return, with both partners’ ages counting toward the standard deduction. From the
            next year, CoastMath uses <strong>Filing status after partner’s death</strong>, which
            defaults to Single. The brackets, standard deduction and Social Security taxation
            thresholds follow that status; see <HelpLink to="federal-brackets-and-deductions" />.
          </p>
          <p>
            With the default horizon you can also choose{" "}
            <strong>Married filing jointly (remarried)</strong> or{" "}
            <strong>Married filing separately</strong> for the later years. No new partner is added;
            the option only changes the tax tables.
          </p>
          <Callout kind="boundary">
            <p>
              Qualifying surviving spouse status, which lets a widow or widower with a dependent
              child use joint rates for two more years, isn’t modeled. Head of household is
              available if a qualifying person lives with you; CoastMath doesn’t check that.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "accounts-and-basis",
      title: "Accounts, ages and cost basis",
      body: (
        <>
          <p>
            Each account the deceased partner owned alone becomes the survivor’s. Balances and Roth
            contribution and conversion records, including the five-year clocks, carry over
            unchanged. From then on:
          </p>
          <ul>
            <li>
              Required minimum distributions and the age-59½ penalty test use the survivor’s age, as
              if the survivor had treated the account as their own. See{" "}
              <HelpLink to="required-minimum-distributions" />.
            </li>
            <li>
              With the household horizon, the deceased partner’s 401(k) accounts keep their balances
              and distribution rules but receive no new employee or employer contributions.
            </li>
            <li>
              With{" "}
              <strong>Step up cost basis on partner-owned taxable accounts at their death</strong>{" "}
              checked (the default), the cost basis of the deceased partner’s taxable brokerage and
              cryptocurrency accounts resets to the balance at the transfer. Pre-tax and Roth
              accounts have no basis step-up.
            </li>
          </ul>
          <Ledger
            title="Example: step-up when Alex’s brokerage account passes to Sam"
            rows={[
              { label: "Balance at the transfer", value: 300000 },
              { label: "Alex’s cost basis", value: 120000 },
              { op: "→", label: "Sam’s cost basis after the step-up", value: 300000 },
              { op: "=", label: "Gain removed by the step-up", value: 180000 },
            ]}
            note="A joint brokerage account worth $100,000 with $60,000 of basis passes to Sam with its $60,000 basis unchanged."
          />
          <Callout kind="boundary">
            <p>
              Joint accounts keep their basis. The half step-up for property a married couple held
              jointly, and the full step-up for community property, aren’t modeled because CoastMath
              doesn’t know each partner’s share.
            </p>
          </Callout>
          <Callout
            kind="boundary"
            title="Not supported: an inherited account held by the first to die"
          >
            <p>
              With the household horizon, a plan in which the first partner to die still holds an
              inherited account with a balance won’t run: the rules for a successor beneficiary
              aren’t modeled. See <HelpLink to="inherited-accounts" />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "income-and-spending",
      title: "Income, spending and benefits",
      body: (
        <>
          <p>
            Every income stream whose <strong>Income recipient</strong> is the deceased partner
            stops at the time shown in the table above. That includes their Social Security; a
            survivor benefit replaces it only if you turn it on (see{" "}
            <HelpLink to="survivor-social-security" />
            ). The survivor’s own streams continue.
          </p>
          <p>
            Per-person health costs stop at the deceased partner’s modeled death. Other expenses
            don’t change on their own: household spending continues at the amounts you entered.
          </p>
          <Callout kind="entry">
            <p>
              To model lower spending or a survivor pension after a death, end or start the item
              with a date milestone set to the January after the death year. Age milestones follow
              your age, not your partner’s. See <HelpLink to="milestones" />.
            </p>
          </Callout>
          <p>
            Estate tax and what heirs receive are calculated once, at the end of the projection, not
            at the first death; see <HelpLink to="estate-tax-and-net-estate" />.
          </p>
        </>
      ),
    },
    {
      id: "not-modeled",
      title: "What isn’t modeled",
      body: (
        <>
          <Callout kind="boundary">
            <ul>
              <li>
                An actual date of death, or the chance of either partner dying earlier or later:
                life expectancy is a fixed planning age.
              </li>
              <li>
                Life insurance proceeds, pension survivor options and changes in spending, unless
                you enter them as income or expenses.
              </li>
              <li>Remarriage, other than choosing a married filing status after the death.</li>
              <li>With the default horizon, anything after your own death.</li>
            </ul>
          </Callout>
        </>
      ),
    },
    {
      id: "reading-the-results",
      title: "Reading the results",
      body: (
        <>
          <Symptoms
            rows={[
              {
                symptom: "The projection ends while your partner is still alive.",
                check: "Plan ends.",
                next: "Choose At the last survivor’s longevity age to continue for the survivor.",
              },
              {
                symptom: "Tax rises the year after a death even though income fell.",
                check: "Filing status after partner’s death.",
                next: "Single brackets and deduction apply from the second year; this is expected.",
              },
              {
                symptom: "Spending is unchanged after the death.",
                check: "Expenses tied to a milestone.",
                next: "Add a date milestone for the January after the death year and adjust the expenses.",
              },
              {
                symptom: "The survivor has no Social Security from the deceased partner.",
                check: "Survivor Social Security policy.",
                next: "It is off by default; see the survivor article for the requirements.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};

export default article;

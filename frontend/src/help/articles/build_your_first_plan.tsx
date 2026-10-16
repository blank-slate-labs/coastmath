import type { Article } from "../help_types";
import { Callout, HelpLink, KeyFigures, Steps, UIPath, hostedPart } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        A first projection needs four essentials: <strong>Plan details</strong>,{" "}
        <strong>Accounts</strong>, <strong>Income streams</strong> and <strong>Expenses</strong>.
        Everything else is optional and can wait until it applies to you. CoastMath recalculates the
        projection after each saved change.
      </p>
      {hostedPart("build-your-first-plan.sign-in", null)}
    </>
  ),
  sections: [
    {
      id: "create-the-plan",
      title: "Create the plan",
      body: (
        <>
          <Steps>
            {hostedPart(
              "build-your-first-plan.first-plan",
              <li>With no plans yet, the sidebar shows the new plan form.</li>,
            )}
            <li>
              {hostedPart("build-your-first-plan.start-empty", <>Enter a </>)}
              <strong>Plan name</strong>, your <strong>Birth year</strong>,{" "}
              <strong>Filing status</strong> and <strong>State</strong>. For a couple, check{" "}
              <strong>Planning with a partner</strong> and enter <strong>Partner name</strong> and{" "}
              <strong>Partner birth year</strong>; the filing status switches to{" "}
              <strong>Married Filing Jointly</strong> unless you picked one. Choose{" "}
              <strong>Create plan</strong>.
            </li>
            <li>
              Answer the <strong>Goals</strong> you know, then choose <strong>Save goals</strong>,
              or choose <strong>Skip</strong>. Every answer is optional.
            </li>
            {hostedPart(
              "build-your-first-plan.later-plans",
              <li>
                Later plans start from <strong>New plan</strong> above the section list.
              </li>,
            )}
          </Steps>
        </>
      ),
    },
    {
      id: "goals",
      title: "What each goal creates",
      body: (
        <>
          <p>
            Each answer becomes an ordinary plan item you can edit later. Saving again updates these
            items instead of adding more.
          </p>
          <ul>
            <li>
              <strong>Stop working</strong>: <strong>At an age</strong> sets the{" "}
              <strong>Retirement</strong> milestone to <strong>Retirement age</strong>.{" "}
              <strong>When I can afford to</strong> triggers it when liquid net worth reaches 25× a
              year of spending. <strong>I’ve already stopped working</strong> sets it to your
              current age and asks for <strong>Social Security received ($/mo)</strong> and{" "}
              <strong>Pension or other retirement income ($/yr)</strong>, saved as income streams.
            </li>
            <li>
              With a partner, <strong>Partner retirement age</strong> sets the{" "}
              <strong>Partner retirement</strong> milestone.{" "}
              <strong>My partner has already stopped working</strong> sets it to the partner’s
              current age and asks for their benefits.
            </li>
            <li>
              <strong>Retirement spending</strong> becomes an expense from{" "}
              <strong>Retirement</strong> in today’s dollars.{" "}
              <strong>Monthly spending today ($/mo)</strong> becomes{" "}
              <strong>Living expenses</strong>, essential and rising with plan inflation; with
              retirement spending set, it ends at Retirement.
            </li>
            <li>
              Under <strong>Travel, giving and heirs</strong>: travel becomes an expense from{" "}
              <strong>Retirement</strong> in today’s dollars, stopping at{" "}
              <strong>Travel until age</strong>; charitable giving becomes a direct gift in nominal
              dollars; <strong>Leave to heirs</strong>, in today’s dollars, becomes the Monte Carlo
              final net worth target.
            </li>
            <li>
              Under <strong>Account balances</strong>, each amount adds an account:{" "}
              <strong>Cash</strong>, <strong>Brokerage</strong>, <strong>401(k)</strong>,{" "}
              <strong>Traditional IRA</strong>, <strong>Roth IRA</strong> and <strong>HSA</strong>.
              With a partner, Cash and Brokerage are joint and each retirement account is asked per
              person.
            </li>
            <li>
              <strong>Leftover income goes to</strong> adds an <strong>Income allocation</strong>{" "}
              rule sending remaining surplus to Brokerage or Cash, adding an empty account if
              needed.
            </li>
          </ul>
          <Callout kind="entry">
            <p>A blank balance adds no account; 0 adds an empty one.</p>
          </Callout>
          <p>
            After <strong>Save goals</strong>, <strong>Add Income</strong> opens for your salary,
            unless you’ve already stopped working or the plan has one.
          </p>
          <p>
            If an item isn’t saved, the form keeps your answers and names it;{" "}
            <strong>Save goals</strong> retries only what failed. If{" "}
            <strong>Income allocation</strong> changed since the plan opened, the leftover choice
            isn’t saved; set it there.
          </p>
        </>
      ),
    },
    {
      id: "fill-in-the-essentials",
      title: "Fill in the essentials",
      body: (
        <>
          <p>
            The sidebar groups sections into Essentials, Optional and Assumptions. Essentials shows
            how many of the four are set, and marks an empty one <strong>Needs input</strong>.
          </p>
          <Steps>
            <li>
              <strong>Plan details.</strong> Set <strong>Plan type</strong> (Now starts today; Fixed
              date keeps a date you pick); change <strong>Filing status</strong> and{" "}
              <strong>State</strong> here. These fields save as you leave them. See{" "}
              <HelpLink to="first-plan-year" />.
            </li>
            <li>
              <strong>Accounts.</strong> Add any account Goals didn’t cover, with its{" "}
              <strong>Account Type</strong>, <strong>Balance</strong> on the start date and{" "}
              <strong>Owner</strong>. For a taxable brokerage account, enter cost basis; left blank,
              it equals the balance, meaning no unrealized gain. See{" "}
              <HelpLink to="opening-balances-and-cost-basis" />.
            </li>
            <li>
              <strong>Income streams.</strong> Add pay, pensions and Social Security in today’s
              dollars. New pay ends at its recipient’s <strong>Retirement</strong> or{" "}
              <strong>Partner retirement</strong> milestone; Social Security is estimated from the
              pay already entered. See <HelpLink to="wages-and-raises" />.
            </li>
            <li>
              <strong>Expenses.</strong> Enter spending as a monthly or annual amount in today’s
              dollars. By default it rises with plan inflation for the life of the plan; with
              retirement spending set, end current spending at <strong>Retirement</strong>. See{" "}
              <HelpLink to="expenses" />.
            </li>
          </Steps>
          <Callout kind="consequence">
            <p>
              Each plan has its own accounts. An older plan whose section reads{" "}
              <strong>Household accounts</strong> shares them: a balance edit or deletion there
              changes every such plan.
            </p>
          </Callout>
          <Callout kind="entry">
            <p>
              “Today’s dollars” means dollars of the plan’s first calendar year. See{" "}
              <HelpLink to="todays-and-future-dollars" />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "what-a-new-plan-assumes",
      title: "What a new plan assumes",
      body: (
        <>
          <p>Until you change them, a new plan uses these settings:</p>
          <KeyFigures
            items={[
              {
                label: "Stock price growth",
                value: 0.07,
                format: "pct",
                detail: "A year, before dividends",
              },
              { label: "Inflation", value: 0.03, format: "pct", detail: "A year" },
              {
                label: "Bond return",
                value: 0.04,
                format: "pct",
                detail: "With a 0% bond allocation",
              },
              { label: "Planning horizon", value: "Age 95", detail: "Plan holder" },
              {
                label: "Retirement milestone",
                value: "Age 65",
                detail: "Only if the plan starts before it",
              },
            ]}
          />
          <ul>
            <li>
              The plan type is Now. Unless you chose otherwise when creating the plan, the filing
              status is Single and no state tax applies.
            </li>
            <li>
              Each account joins the <strong>Drawdown order</strong> by type, which decides where
              shortfalls are funded from; see <HelpLink to="withdrawal-order" />.
            </li>
            <li>
              With no <strong>Income allocation</strong> rules, surplus cash goes to a default
              account and the Overview lists a note naming it; see <HelpLink to="savings-rules" />.
            </li>
            <li>
              The first year runs from today to December 31 and is partial. Income and taxes from
              earlier this year are estimated pro rata until you enter them under{" "}
              <UIPath steps={["Plan details", "Earlier this tax year"]} />; the Overview shows a
              notice until you do.
            </li>
          </ul>
          <Callout kind="where">
            <p>
              Change growth and inflation under <UIPath steps={["Assumptions"]} /> in the sidebar;
              see <HelpLink to="market-and-inflation-assumptions" />. Set the planning horizon and
              birth month as <strong>Longevity age</strong> and <strong>Birth month</strong> in{" "}
              <UIPath steps={["Plan details"]} />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "optional-sections",
      title: "Optional sections",
      body: (
        <>
          <p>
            Optional sections in use stay listed; the rest are collapsed under a{" "}
            <strong>Show … more</strong> row. The ones that most often change a first projection:
          </p>
          <ul>
            <li>
              <strong>Milestones</strong> such as retirement, which start and stop income and
              expenses; see <HelpLink to="milestones" />.
            </li>
            <li>
              <strong>Income allocation</strong>, which directs surplus into accounts and sets
              contributions; see <HelpLink to="contributions-and-employer-match" />.
            </li>
            <li>
              <strong>Property and debt</strong>, for a home or mortgage; see{" "}
              <HelpLink to="homes-and-real-assets" />.
            </li>
            <li>
              <strong>Partner and estate</strong>, to plan for a couple; see{" "}
              <HelpLink to="household-and-partner" />.
            </li>
            <li>
              <strong>Health coverage</strong>, for Marketplace and Medicare costs; see{" "}
              <HelpLink to="marketplace-health-coverage" />.
            </li>
          </ul>
        </>
      ),
    },
    {
      id: "check-the-result",
      title: "Check the first projection",
      body: (
        <>
          <p>
            The header shows the save status (“Saving…”, then “Saved” with the time) and the
            projection’s span of years and ages. A warning pill appears when spending goes unfunded
            or net worth turns negative. The Overview’s year panel steps through each year’s
            balances, income, taxes and spending.
          </p>
          <p>
            For how each year is computed, see <HelpLink to="how-a-plan-year-is-calculated" />. If a
            change doesn’t appear, see <HelpLink to="saves-and-refresh" />.
          </p>
        </>
      ),
    },
  ],
};
export default article;

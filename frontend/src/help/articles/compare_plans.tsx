import type { Article } from "../help_types";
import { Callout, DataTable, HelpLink, Steps, UIPath, hostedPart } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        To test a change, duplicate the plan, change the copy, and compare the copy’s forecast with
        the original’s on the overview chart. The copy gets its own accounts, income, spending,
        milestones, assumptions and every other plan setting.
      </p>
      <p>
        To test a change that should keep up with your main plan, make a scenario instead: a linked
        plan that receives every change you save to the Main plan, except the values you changed in
        the scenario.
      </p>
      <p>
        For a quick what-if without a copy, keep the current forecast as a baseline, edit the plan,
        and compare, then change it back.
      </p>
    </>
  ),
  sections: [
    {
      id: "copy-a-plan",
      title: "Copy a plan",
      body: (
        <>
          <Steps>
            <li>
              Open the plan you want to copy in the plan builder’s <strong>Active plan</strong>{" "}
              list.
            </li>
            <li>
              Choose <strong>Duplicate</strong>, then <strong>Duplicate plan</strong>.
            </li>
            <li>
              The copy opens as the active plan, named after the original with “(copy)” added.
            </li>
            <li>Change the one input you want to test.</li>
          </Steps>
          <Callout kind="where">
            {hostedPart(
              "compare-plans.duplicate",
              <p>
                <UIPath steps={["Active plan", "Duplicate"]} /> at the top of the plan builder.
              </p>,
            )}
          </Callout>
        </>
      ),
    },
    {
      id: "what-copies",
      title: "What the copy shares and what it owns",
      body: (
        <>
          <DataTable
            caption="After duplicating"
            columns={[
              { key: "item", label: "Item" },
              { key: "scope", label: "In the copy" },
            ]}
            rows={[
              {
                item: "Plan details, partner, filing status, state and life expectancy",
                scope: "Copied; edits affect one plan",
              },
              {
                item: "Income, expenses, milestones and income allocation",
                scope: "Copied; edits affect one plan",
              },
              {
                item: "Drawdown order, assumptions, property, debts, charitable giving and residences",
                scope: "Copied; edits affect one plan",
              },
              {
                item: "Tax, health coverage, flexible-spending and estate settings, and notes",
                scope: "Copied; edits affect one plan",
              },
              {
                item: "Accounts: balances, types, owners, cost basis and account investment settings",
                scope: "Copied; edits affect one plan. Household accounts stay shared",
              },
            ]}
          />
          <p>
            References inside the plan point to the copy’s own records. For example, an expense that
            ends at the copy’s retirement milestone moves when you move that milestone, and the
            original plan is unchanged.
          </p>
          <Callout kind="boundary">
            <p>
              Copies of an older plan whose Accounts section reads{" "}
              <strong>Household accounts</strong> share those accounts: a balance, cost basis or
              account investment setting changed in either plan changes both forecasts. For those,
              test a return difference with the plan-wide <UIPath steps={["Assumptions"]} />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "scenarios",
      title: "Scenarios follow their Main plan",
      body: (
        <>
          <Steps>
            <li>Open the plan you want to keep as the Main plan.</li>
            <li>
              Choose <strong>New scenario</strong>, name it, then choose{" "}
              <strong>Create scenario</strong>.
            </li>
            <li>
              The scenario opens as the active plan and is listed under its Main plan in{" "}
              <strong>Active plan</strong>.
            </li>
            <li>Change the values you want to test in the scenario.</li>
          </Steps>
          <DataTable
            caption="When you save a change to the Main plan"
            columns={[
              { key: "item", label: "In the scenario" },
              { key: "result", label: "Result" },
            ]}
            rows={[
              {
                item: "A value you haven’t changed in the scenario",
                result: "Updated to the Main plan’s value",
              },
              { item: "A value changed in this scenario", result: "Kept" },
              { item: "An item added to the Main plan", result: "Added to the scenario" },
              { item: "An item you removed from the scenario", result: "Stays removed" },
              {
                item: "An item you added to the scenario",
                result: "Kept; it exists only in the scenario",
              },
              {
                item: "Income allocation rules, drawdown order and residences",
                result:
                  "Follow the Main plan as a whole list until you change that list in the scenario",
              },
            ]}
          />
          <p>
            Saving a change to a scenario never changes its Main plan. A scenario is otherwise an
            ordinary plan: its forecast, comparisons{hostedPart("compare-plans.sharing", "")} and
            exports work the same way.
          </p>
          <Callout kind="where">
            <p>
              While a scenario is open, a bar above the forecast reads <strong>Scenario of</strong>{" "}
              and the Main plan’s name with the number of changes. <strong>View changes</strong>{" "}
              lists them by section, with the Main plan’s value next to the scenario’s. In the plan
              builder, rows are marked <strong>Changed in scenario</strong> or{" "}
              <strong>Only in this scenario</strong>
              {hostedPart("compare-plans.scenario-tier", ".")}
            </p>
          </Callout>
          <h3>Go back to the Main plan’s values</h3>
          <p>
            In <UIPath steps={["View changes"]} />, <strong>Use Main’s value</strong> resets one
            value and <strong>Use Main’s values</strong> resets a whole item; it then follows the
            Main plan again. <strong>Restore</strong> brings back an item you removed, with the Main
            plan’s current values. <strong>Use Main’s rules</strong> replaces the scenario’s income
            allocation rules with the Main plan’s. If the bar says some changes weren’t applied, it
            lists why; fix the cause, then choose <strong>Sync now</strong>.
          </p>
          <Callout kind="boundary">
            <p>
              One level only: a scenario can’t have scenarios. <strong>New scenario</strong> on a
              scenario creates another scenario of the same Main plan, and{" "}
              <strong>Duplicate</strong> on a scenario makes an independent copy. Older plans whose
              Accounts section reads <strong>Household accounts</strong> don’t offer scenarios. An
              archived scenario isn’t updated; after restoring it, choose <strong>Sync now</strong>.
            </p>
          </Callout>
          <Callout kind="consequence">
            <p>
              <strong>Make independent</strong> keeps the scenario’s current values and stops it
              receiving the Main plan’s changes; it can’t be linked again. Deleting a Main plan
              makes each of its scenarios an independent plan with its current values.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "compare-two-plans",
      title: "Compare two saved plans",
      body: (
        <>
          <Steps>
            <li>Open the plan you changed.</li>
            <li>
              On the overview chart, choose the other plan in{" "}
              <strong>Compare with another plan…</strong>. In a scenario,{" "}
              <strong>Compare with</strong> the Main plan’s name on the scenario bar does the same.
            </li>
            <li>
              Read the difference on the chart: the other plan is the dashed{" "}
              <strong>Baseline</strong> line, and the shading shows where this plan is ahead or
              behind. Hover a year for both net worths and the difference.
            </li>
            <li>
              Choose <strong>Stop comparing</strong> when you’re done.
            </li>
          </Steps>
          <p>
            Both plans are recalculated when you pick the comparison, with the same start date. The
            comparison covers the years both plans share. In today’s dollars, both lines are
            converted with the open plan’s inflation, so a different inflation assumption in the
            other plan doesn’t skew the display.
          </p>
          <p>
            The same comparison appears in <UIPath steps={["Tax tools", "Annual tax breakdown"]} />{" "}
            as the total tax change across shared years. It is the difference between the two whole
            plans, not the tax effect of one change alone.
          </p>
        </>
      ),
    },
    {
      id: "baseline-without-a-copy",
      title: "Compare against a kept forecast",
      body: (
        <>
          <p>
            <strong>Keep forecast for comparison</strong> saves the current forecast as the
            baseline. Edit the plan, and the chart compares the new forecast with the kept one.{" "}
            <strong>Update comparison forecast</strong>
            replaces the baseline with the current forecast.
          </p>
          <Callout kind="consequence">
            <p>
              Your edits are saved to the plan; only the forecast is kept. To go back, undo each
              change yourself. The kept forecast disappears when you reload the page or switch
              plans.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "beyond-net-worth",
      title: "Comparing risk and other results",
      body: (
        <>
          <p>
            The overlay compares steady-return net worth only. To compare risk, run chance of
            success on each plan in turn, with the same trial count and seed, so both plans face the
            same market sequences. See <HelpLink to="chance-of-success" />. Replay the same
            historical period in each plan with the <HelpLink to="historical-stress-test" />.
          </p>
        </>
      ),
    },
  ],
};
export default article;

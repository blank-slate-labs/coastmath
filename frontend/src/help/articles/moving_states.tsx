import type { Article } from "../help_types";
import { Callout, HelpLink, Ledger, Pair, Steps, UIPath } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        To model a move, add a residency change to your plan. It names a state, and optionally a
        locality, with a start and an optional end. CoastMath taxes each year as a full-year
        resident of one state: the state that applies after any move during that year. The one
        exception is a move between California and a state without an income tax. In that case,
        California taxes only the wages earned while you lived there.
      </p>
    </>
  ),
  sections: [
    {
      id: "add-a-move",
      title: "Add a move",
      body: (
        <>
          <Steps>
            <li>
              In <UIPath steps={["Plan details"]} />, set <strong>State</strong> and{" "}
              <strong>Local income tax</strong> to where you live now. This is the starting
              residence.
            </li>
            <li>
              Under <strong>Residency timeline</strong>, choose{" "}
              <strong>+ Add residency change</strong> and pick the new <strong>State</strong>.
            </li>
            <li>
              Set <strong>Start</strong>: <strong>At milestone</strong> ties the move to an event
              such as retirement, and <strong>In year</strong> fixes a calendar year.
            </li>
            <li>
              Leave <strong>End</strong> as <strong>Indefinite</strong> for a permanent move. For a
              stay that ends, set an end milestone or year.
            </li>
            <li>
              Choose the new residence’s <strong>Local income tax</strong>, or leave it at None.
            </li>
            <li>
              Choose <strong>Save residency changes</strong>. Unlike the rest of Plan details, the
              timeline doesn’t save automatically.
            </li>
          </Steps>
          <Callout kind="entry" title="Each row carries its own locality">
            <p>
              A residency change with no locality has no local tax, even if the starting residence
              has one. Changing a row’s state clears its catalog locality.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "which-state-applies",
      title: "Which state applies in each year",
      body: (
        <>
          <ul>
            <li>
              <strong>In year</strong> starts on January 1 of that year. An <strong>In year</strong>{" "}
              end includes all of that year.
            </li>
            <li>
              A start milestone applies for the whole year it occurs in. An end milestone stops the
              row for the whole year it occurs in.
            </li>
            <li>When rows overlap, the one higher in the list wins.</li>
            <li>
              When no row applies, the starting state from Plan details applies. A return home
              therefore needs only an end on the away row.
            </li>
          </ul>
          <Pair
            left={{
              title: "Move from New York to Florida in July 2026",
              body: (
                <p>
                  New York income tax for 2026 is $0. Florida applies to the whole year, including
                  wages from January to June.
                </p>
              ),
            }}
            right={{
              title: "Stay in New York all of 2026",
              body: (
                <p>
                  New York income tax is $6,039.75 on the same $120,000 salary for a single filer.
                </p>
              ),
            }}
          />
          <Callout kind="boundary">
            <p>
              Apart from the California case below, part-year residency isn’t modeled. Income isn’t
              split between the two states in a move year, and neither is a local tax. The move year
              is taxed entirely by the destination. To keep the departure year with the old state,
              start the new row <strong>In year</strong> the year after. The truth lies between the
              two results.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "california-part-year",
      title: "Moving into or out of California",
      body: (
        <>
          <p>
            When a year includes California and one of Alaska, Florida, Nevada, New Hampshire, South
            Dakota, Tennessee, Texas or Wyoming, California tax is prorated. CoastMath computes the
            year’s tax on all income at California rates. It then keeps California’s share: the
            wages earned while you lived in California, taken month by month from the move’s month.
            Other income, such as pensions, withdrawals and gains, goes with the state that applies
            to the year.
          </p>
          <Ledger
            title="Example: single filer, Texas to California on July 1, 2026, $120,000 salary"
            rows={[
              {
                label: "California tax on the full year’s income",
                value: 7067.98,
                format: "usd_cents",
              },
              {
                op: "×",
                label: "Share of wages earned in California",
                value: 0.5,
                format: "pct",
                detail: "July to December",
              },
              {
                op: "=",
                label: "California income tax for 2026",
                value: 3533.99,
                format: "usd_cents",
              },
            ]}
            note="No exemption credits claimed. Moving from California to Texas on the same date gives the same result."
          />
          <p>
            The proration applies only to W-2 wages. It isn’t used when the year also has any of
            these: pre-tax contributions such as 401(k) deferrals or deductible IRA contributions,
            self-employment income, an HSA, head of household status, California dependents, tax
            history entered for the first year, or capital losses. In those cases the whole year
            stays with one state, as described above, and{" "}
            <UIPath steps={["Overview", "Model assumptions and limitations"]} /> gives the reason. A
            move tied to a milestone without a fixed date, such as reaching financial independence,
            counts from January.
          </p>
        </>
      ),
    },
    {
      id: "what-a-move-changes",
      title: "What a move changes",
      body: (
        <>
          <p>
            A residency change affects state and local income tax only. How each state and locality
            is taxed is in <HelpLink to="state-and-local-income-tax" />. Housing, living costs and
            health coverage stay as entered. A state’s pension and retirement-income exclusion
            follows the state of each year, so moving from New York to Pennsylvania replaces the
            $20,000 New York limit with Pennsylvania’s full exclusion from the year of the move. Tie
            the rest to the same milestone if they change with the move; see{" "}
            <HelpLink to="milestones" /> and <HelpLink to="selling-a-home" />. California SDI and
            Washington payroll premiums follow the work coverage periods you enter, not your
            residence.
          </p>
        </>
      ),
    },
  ],
};
export default article;

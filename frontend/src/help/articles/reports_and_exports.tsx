import type { Article } from "../help_types";
import { Callout, DataTable, HelpLink, Steps, UIPath, hostedPart } from "../help_kit";

const article: Article = {
  intro: (
    <>
      {hostedPart(
        "reports-and-exports.intro",
        <p>
          The Exports tab holds a year-by-year table of your projection, with CSV and JSON downloads
          of that table and a printable report you can save as a PDF.
        </p>,
      )}
      <p>
        Everything here is a copy of results. None of it contains your plan’s inputs, and none of it
        can be loaded back into CoastMath.
      </p>
    </>
  ),
  sections: [
    {
      id: "annual-report",
      title: "Read the annual report",
      body: (
        <>
          <Steps>
            <li>
              Open <UIPath steps={["Exports"]} />.
            </li>
            <li>
              Choose a view: <em>Summary</em>, <em>Balances</em>, <em>Cash flow</em>, <em>Taxes</em>
              , <em>Full detail</em>, or <em>Custom</em> to pick columns yourself.
            </li>
            <li>
              Set <em>Dollars</em> to <em>Future $</em> or today’s dollars of the plan’s start year.
              The same setting drives the Overview charts.
            </li>
            <li>
              Open <em>Definitions for this view</em> for what each column includes.
            </li>
          </Steps>
          <p>
            Each row is one year, with balances at December 31. The table rounds to whole dollars.
            When the plan starts after January 1, the first year covers only the months from the
            start date.
          </p>
          <p>
            Two columns overlap by design. <em>Income</em> already includes taxable withdrawals, so
            don’t add <em>Withdrawals</em> to it. <em>Withdrawals</em> includes required minimum
            distributions and early-withdrawal series payments, which <em>Mandatory withdrawals</em>{" "}
            lists again on its own. For how the figures relate within a year, see{" "}
            <HelpLink to="cash-flow-view" />.
          </p>
        </>
      ),
    },
    {
      id: "downloads",
      title: "Download CSV or JSON",
      body: (
        <>
          {hostedPart(
            "reports-and-exports.downloads",
            <p>
              <em>Download CSV</em> and <em>Download JSON</em> sit beside the currency setting. Both
              wait while the projection is updating.
            </p>,
          )}
          <DataTable
            caption="What each download contains"
            columns={[
              { key: "file", label: "File" },
              { key: "contents", label: "Contents" },
            ]}
            rows={[
              {
                file: "CSV",
                contents:
                  "One row per year with every report column, whichever view is showing, plus the currency basis and base year on each row. Amounts keep full precision.",
              },
              {
                file: "JSON",
                contents:
                  "The same rows, with the plan name, currency basis, base year, first and last year, whether spending stays funded, the failure year if any, and the projection’s modeling notes.",
              },
            ]}
            note="Amounts are in the currency chosen when you download. Percent columns are percentages, not fractions."
          />
        </>
      ),
    },
    {
      id: "printable-report",
      title: "Print the report or save it as a PDF",
      body: (
        <>
          <Steps>
            {hostedPart(
              "reports-and-exports.open-printable",
              <li>
                On <UIPath steps={["Exports"]} />, under <em>Printable report</em>, choose{" "}
                <em>Open printable report</em>.
              </li>,
            )}
            <li>
              Check the report: key results, household and assumptions, the net worth and income and
              taxes charts, the annual table, plan notes, and caveats to review.
            </li>
            <li>
              Choose <em>Print or save as PDF</em>, then <em>Save as PDF</em> in your browser’s
              print dialog. <em>Back to the app</em> returns to the planner.
            </li>
          </Steps>
          <p>
            The report reflects the projection when you open it. After changing the plan, open it
            again.
          </p>
        </>
      ),
    },
    {
      id: "results-not-a-backup",
      title: "Downloads are results, not a backup",
      body: (
        <>
          <p>
            A CSV, JSON or PDF records what the projection showed. It doesn’t hold your accounts,
            income, expenses, rules or assumptions, and CoastMath can’t rebuild a plan from it.
          </p>
          <Callout kind="consequence">
            {hostedPart(
              "reports-and-exports.deletion",
              <p>If you delete a plan or your account, no download can restore it.</p>,
            )}
          </Callout>
        </>
      ),
    },
    ...hostedPart("reports-and-exports.share", []),
  ],
};

export default article;

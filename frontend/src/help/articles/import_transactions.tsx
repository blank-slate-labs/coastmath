import type { Article } from "../help_types";
import { Callout, DataTable, HelpLink, Steps, UIPath } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath imports bank and card statements as CSV, OFX or QFX files into imported accounts.
        Months of spending and take-home pay come from those transactions, and a month counts only
        when your statements cover every day of it.
      </p>
      <p>
        An import never changes the file, other accounts or your plans’ inputs, except connected
        spending that reads the account.
      </p>
    </>
  ),
  sections: [
    {
      id: "formats",
      title: "Files you can import",
      body: (
        <>
          <DataTable
            caption="Accepted files"
            columns={[
              { key: "format", label: "Format" },
              { key: "reads", label: "What CoastMath reads" },
              { key: "period", label: "Statement period" },
            ]}
            rows={[
              {
                format: "CSV",
                reads:
                  "Columns you confirm: date, description, amount (one signed column, money out and money in columns, or an amount with a debit/credit column), and optionally merchant, category, currency and status",
                period: "You confirm it",
              },
              {
                format: "OFX or QFX",
                reads:
                  "Bank and credit card statements, one account section at a time; investment statements are skipped",
                period: "From the file",
              },
            ]}
            note="Files up to 10 MB and 50,000 transactions. Rows without a readable date or amount, and zero amounts, are skipped and counted."
          />
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan setup", "Transactions", "Import"]} />. Import in the web
              planner.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "import-a-statement",
      title: "Import a statement",
      body: (
        <>
          <Steps>
            <li>
              Choose <strong>Statement file</strong>. CoastMath reads the file and shows sample rows
              split into <strong>Out</strong> and <strong>In</strong>.
            </li>
            <li>
              For a CSV, check each column’s role. If purchases show under In, change{" "}
              <strong>Money in is</strong>. If the dates read either way, choose the order under{" "}
              <strong>Dates</strong>.
            </li>
            <li>Set the statement period; see below.</li>
            <li>
              Choose the <strong>Account</strong>: an imported account, or{" "}
              <strong>New account</strong> with a name and type. Credit cards and checking count
              toward spending unless you change it in <strong>Accounts</strong>.
            </li>
            <li>
              Map each <strong>Bank category</strong> to a CoastMath category.
            </li>
            <li>
              Choose <strong>Import</strong>. The counts show how many transactions were imported
              and how many were already there.
            </li>
          </Steps>
          <p>
            A file with several accounts imports one account at a time; choose it under{" "}
            <strong>Account in file</strong>. An OFX or QFX account imported before is chosen for
            you.
          </p>
        </>
      ),
    },
    {
      id: "statement-period",
      title: "The statement period",
      body: (
        <>
          <p>
            The period is the span of days the file covers completely. It must include every
            transaction in the file, and it can extend to the first and last day of the file’s
            months, never past today. <strong>Dates in file</strong> uses the first and last
            transaction; <strong>Whole months</strong> uses the widest allowed span.
          </p>
          <Callout kind="entry">
            <p>
              Choose <strong>Whole months</strong> only when the statement covers those days, even
              ones without transactions. Claiming days a download left out makes those months look
              cheaper than they were.
            </p>
          </Callout>
          <p>
            Periods of every import into an account add up. Months with a gap between two statements
            stay incomplete and can’t drive a spending comparison. OFX and QFX files carry their own
            period.
          </p>
        </>
      ),
    },
    {
      id: "duplicates-and-corrections",
      title: "Overlaps, duplicates and corrections",
      body: (
        <>
          <ul>
            <li>
              Statements that overlap are fine: a transaction already in the account is matched, not
              added twice. CSV rows match on date, amount and description; OFX rows on the bank’s
              transaction ID.
            </li>
            <li>
              The same file can’t be imported into the same account twice. Revert the first import
              to import it again.
            </li>
            <li>
              Identical rows inside one CSV, such as two equal purchases on a day, are both kept.
            </li>
            <li>
              A pending CSV row that later posts with a different amount is replaced when a newer
              statement covering that day no longer lists it.
            </li>
            <li>Correction records in an OFX file remove or replace the transactions they name.</li>
            <li>
              Changing a CSV’s description columns or sign between imports stops its rows matching
              earlier ones.
            </li>
          </ul>
        </>
      ),
    },
    {
      id: "categories",
      title: "Bank categories",
      body: (
        <>
          <p>
            CoastMath suggests a category for each bank category it recognizes. A mapping you change
            is saved as a rule for that account, so the next statement uses it; edit or delete it
            under <strong>Rules</strong>. Categories you set on single transactions take precedence.
            See <HelpLink to="expenses" /> for how spending enters a plan.
          </p>
        </>
      ),
    },
    {
      id: "revert-an-import",
      title: "Revert an import",
      body: (
        <>
          <p>
            Under <strong>Imports</strong>, <strong>Revert</strong> removes the transactions that
            import added and its statement period. Transactions dated inside another import’s period
            on the same account stay with that import. Reverting the import that created an account
            removes the account too when nothing else is stored there.
          </p>
          <Callout kind="consequence">
            <p>
              Reverting can’t be undone. Categories, exclusions and one-time marks on the removed
              transactions are lost, and rows that the import’s corrections or pending updates
              removed don’t come back. Import the file again to restore its transactions.
            </p>
          </Callout>
        </>
      ),
    },
  ],
};

export default article;

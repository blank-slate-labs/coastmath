import type { Article } from "../help_types";
import { Callout, DataTable, HelpLink, Ledger, UIPath } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        Compare months projects your plan as if one month’s spending, or the average of several
        months, were your normal spending from now on. Each choice runs the full projection beside
        your plan as it stands, so you can see what June’s spending versus July’s does to your
        financial independence age, your plan’s funding and your final net worth.
      </p>
      <p>
        Nothing changes until you apply a result. Applying saves the chosen spending to the plan;
        income stays as entered.
      </p>
    </>
  ),
  sections: [
    {
      id: "choosing-months",
      title: "Which months you can choose",
      body: (
        <>
          <p>
            A month is available only when every account behind it covers every day of it. A partial
            month would look cheaper than it was, so it stays greyed out, and hovering or focusing
            it says why:
          </p>
          <DataTable
            caption="Why a month is unavailable"
            columns={[
              { key: "reason", label: "Shown as" },
              { key: "meaning", label: "Meaning" },
            ]}
            rows={[
              { reason: "Month in progress", meaning: "The month hasn’t ended yet." },
              {
                reason: "Still settling",
                meaning:
                  "A synced account was last read within six days of the month’s end, so late card postings may be missing.",
              },
              {
                reason: "Not fully covered",
                meaning: "An account’s history or imported statements don’t span the whole month.",
              },
              {
                reason: "Waiting for history",
                meaning: "An account has no transaction history yet.",
              },
            ]}
          />
          <p>
            The accounts are the ones your plan’s spending from transactions reads, or, when that is
            off, every account that counts toward spending. Only transactions in the plan’s currency
            count.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Compare months"]} />. Pick up to six months to compare each on its
              own, or choose <em>Average them</em> to combine up to twelve into one result.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "what-a-month-projects",
      title: "What a month becomes in the plan",
      body: (
        <>
          <p>
            A month’s essential and discretionary spending each become an annual amount: twelve
            times the month, or twelve times the average of the chosen months. Refunds reduce a
            category, but a month with more refunds than purchases counts as zero, never negative.
          </p>
          <Ledger
            title="Two months averaged"
            rows={[
              { label: "June essential spending", value: 3400 },
              { op: "+", label: "July essential spending", value: 4200 },
              { op: "=", label: "Average month", value: 3800 },
              { op: "=", label: "Annual essential spending, 12 × the average", value: 45600 },
            ]}
          />
          <p>
            Transfers between your accounts, debt payments, saving and investing, and taxes never
            count as spending, because the plan already models them. Transactions you mark one-time
            show in the month but are left out of the projection.
          </p>
        </>
      ),
    },
    {
      id: "replaced-and-kept",
      title: "What is replaced and what is kept",
      body: (
        <>
          <p>
            The month replaces your living expenses. Each one is scaled so that this year’s
            essential and discretionary totals equal the month’s; a mixed expense is split by its
            discretionary share. Names, end dates, inflation and flexible spending settings stay as
            they are.
          </p>
          <DataTable
            caption="Expenses a month replaces"
            columns={[
              { key: "kind", label: "Expense" },
              { key: "treatment", label: "In the comparison" },
            ]}
            rows={[
              { kind: "Ordinary living expenses", treatment: "Scaled to the month" },
              { kind: "Payroll deductions", treatment: "Kept as entered" },
              { kind: "Qualified education", treatment: "Kept as entered" },
              { kind: "Expenses that repeat every few years", treatment: "Kept as entered" },
              {
                kind: "Expenses paid from a specific account or tied to an income",
                treatment: "Kept as entered",
              },
              {
                kind: "Spending from transactions (when on)",
                treatment: "Only these two expenses change",
              },
            ]}
          />
          <p>
            Expenses that start later, such as retirement spending, scale by the same ratio unless
            you set <em>Later phases</em> to <em>As planned</em>. If the plan has no discretionary
            spending today, the month’s discretionary amount is added as a new inflation-linked
            expense.
          </p>
        </>
      ),
    },
    {
      id: "take-home",
      title: "Take-home pay is an approximation",
      body: (
        <>
          <p>
            With <em>Take-home</em> set to <em>Scale to month</em>, the comparison scales your wages
            and self-employment income so this year’s projected take-home pay matches the month’s
            deposits, refining the scale a few times because tax is progressive. Pay that would need
            less than a tenth or more than ten times today’s income isn’t scaled, and the result
            says so.
          </p>
          <p>
            Deposits are after tax and payroll deductions, and a month can include a bonus or miss a
            paycheck, so treat this as a what-if. Applying a month never changes your income.
          </p>
        </>
      ),
    },
    {
      id: "applying",
      title: "Applying a month",
      body: (
        <>
          <p>
            When the plan’s spending comes from transactions, applying switches it from recent
            months to the chosen months. The two connected expenses then stay at those months’
            amounts until you switch back with <em>Use recent months</em>. If a chosen month later
            stops being complete, for example because you revert an import, the expenses keep their
            last amounts and the plan shows an error.
          </p>
          <p>
            Otherwise, applying saves the scaled amounts to your living expenses, exactly as
            previewed. If the plan changed after the preview, nothing is saved: the preview
            refreshes so you can review it and apply again.
          </p>
          <p>
            Read the net-worth lines in today’s dollars to compare months without inflation. See{" "}
            <HelpLink to="todays-and-future-dollars" /> and <HelpLink to="expenses" />.
          </p>
        </>
      ),
    },
  ],
};

export default article;

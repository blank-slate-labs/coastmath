import type { Article } from "../help_types";
import {
  Callout,
  DataTable,
  Figure,
  Formula,
  HelpLink,
  Ledger,
  Op,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";
import { Timeline } from "../help_charts";

const article: Article = {
  intro: (
    <>
      <p>
        A withdrawal from a traditional IRA, 401(k), 403(b) or 401(a) made before the owner reaches
        59½ costs a 10% additional tax on top of income tax. A 457(b), traditional or Roth, is
        treated as a government employer’s plan and never carries it. CoastMath charges it on every
        such withdrawal except payments from an active 72(t) series and withdrawals from inherited
        accounts. It grosses up the withdrawal so the money left after that tax still covers the
        shortfall.
      </p>
      <p>
        Roth withdrawals come out in the legal order: regular contributions first, then conversions
        from the oldest year, then earnings. Only the conversions and earnings can cost anything,
        and only until the relevant five-year clocks and 59½ are met.
      </p>
    </>
  ),
  sections: [
    {
      id: "traditional-accounts",
      title: "Traditional accounts before 59½",
      body: (
        <>
          <Formula
            result="Additional tax"
            note="CoastMath assumes withdrawals are spread evenly over the year, so only the share of the year before 59½ is charged."
          >
            <V>Withdrawal</V>
            <Op>×</Op>
            <V>10%</V>
            <Op>×</Op>
            <V>share of the year before 59½</V>
          </Formula>
          <Ledger
            title="Example: a 57-year-old needs $20,000 from a traditional IRA (2026, single)"
            rows={[
              {
                label: "Traditional IRA withdrawal",
                value: 22987.5,
                format: "usd_cents",
                detail: "Grossed up for the additional tax, then for the income tax it creates",
              },
              { op: "−", label: "Additional tax (10%)", value: 2298.75, format: "usd_cents" },
              {
                op: "−",
                label: "Income tax",
                value: 688.75,
                format: "usd_cents",
                detail: "($22,987.50 − $16,100 standard deduction) × 10%",
              },
              { op: "=", label: "Left to spend", value: 20000, format: "usd_cents" },
            ]}
          />
          <p>
            You reach 59½ at the start of the month six months after your birth month. Without a{" "}
            <UIPath steps={["Plan details", "Birth month"]} />, the whole year you turn 59 counts as
            before 59½ and the year you turn 60 counts as after. With a birth month, the charge is
            split between those two years:
          </p>
          <DataTable
            caption="Additional-tax rate on traditional withdrawals, by birth month"
            columns={[
              { key: "month", label: "Birth month" },
              { key: "y59", label: "Year you turn 59", format: "pct", digits: 2 },
              { key: "y60", label: "Year you turn 60", format: "pct", digits: 2 },
            ]}
            rows={[
              { month: "Not entered", y59: 0.1, y60: 0 },
              { month: "January", y59: 0.05, y60: 0 },
              { month: "February", y59: 0.058333, y60: 0 },
              { month: "March", y59: 0.066667, y60: 0 },
              { month: "April", y59: 0.075, y60: 0 },
              { month: "May", y59: 0.083333, y60: 0 },
              { month: "June", y59: 0.091667, y60: 0 },
              { month: "July", y59: 0.1, y60: 0 },
              { month: "August", y59: 0.1, y60: 0.008333 },
              { month: "September", y59: 0.1, y60: 0.016667 },
              { month: "October", y59: 0.1, y60: 0.025 },
              { month: "November", y59: 0.1, y60: 0.033333 },
              { month: "December", y59: 0.1, y60: 0.041667 },
            ]}
            note="Each rate is 10% × the months before 59½ ÷ 12. The owner’s age decides, so a partner’s account follows the partner’s birth year and month."
          />
          <p>
            HSA money spent on anything other than the year’s modeled medical costs works the same
            way with a 20% additional tax that ends at 65.
          </p>
        </>
      ),
    },
    {
      id: "exceptions",
      title: "Which exceptions apply",
      body: (
        <>
          <DataTable
            caption="Exceptions to the 10% additional tax"
            columns={[
              { key: "rule", label: "Exception" },
              { key: "applied", label: "In CoastMath" },
            ]}
            rows={[
              { rule: "Owner has reached 59½", applied: "Applied, prorated by month as above" },
              {
                rule: "Substantially equal periodic payments (72(t))",
                applied: "Applied to the series account’s scheduled payments",
              },
              {
                rule: "Inherited accounts",
                applied:
                  "Applied: withdrawals from an inherited IRA or 401(k) carry no additional tax",
              },
              {
                rule: "Leaving an employer in or after the year you turn 55",
                applied:
                  "Applied to that employer’s 401(k), 403(b) or 401(a) plan when you enter the year you left; never to IRAs or other employers’ plans",
              },
              {
                rule: "Leaving an employer in or after the year you turn 50 (public safety workers)",
                applied: "Not modeled",
              },
              {
                rule: "Disability, terminal illness, medical costs above 7.5% of income, first home, education, birth or adoption, emergency, disaster and similar exceptions",
                applied: "Not modeled",
              },
            ]}
          />
          <Callout kind="boundary">
            <p>
              The age-55 exception is off until you say you left the employer. A traditional 401(k)
              withdrawal at 55 to 59 is charged the additional tax unless the account has a
              separation year. It still counts as income. Your drawdown order decides whether the
              401(k) or an IRA is used first.
            </p>
          </Callout>
          <p>
            To use the exception, open the 401(k), 403(b) or 401(a) account and fill in{" "}
            <strong>Year you left this plan’s employer</strong> under{" "}
            <strong>Distribution rules</strong>. CoastMath treats that as leaving on January 1 of
            the year. The additional tax is waived on that plan’s withdrawals from the first year in
            which the owner is 55 by the end of the calendar year and the separation has happened. A
            year earlier than that, or a blank year, keeps the charge. It follows the account
            owner’s age, so a partner’s plan uses the partner’s birth year. Withdrawals stay in the
            same preview and in the projection. Leaving blank is a choice you make; CoastMath does
            not assume you separated.
          </p>
        </>
      ),
    },
    {
      id: "roth-ordering",
      title: "The order Roth money comes out",
      body: (
        <>
          <p>
            All of one person’s own Roth IRAs are treated as one pool for the year. Withdrawals
            take, in order:
          </p>
          <ol>
            <li>
              <strong>Regular contributions.</strong> Never taxed, never charged the additional tax.
            </li>
            <li>
              <strong>Conversions, oldest year first</strong>, and within a year the previously
              taxed part before any nontaxable part. No income tax. Before 59½, the taxed part of a
              conversion less than five years old is charged 10%.
            </li>
            <li>
              <strong>Earnings.</strong> Untaxed once the withdrawal is qualified. Otherwise they
              are ordinary income, plus 10% before 59½.
            </li>
          </ol>
          <p>
            A withdrawal is qualified from the fifth calendar year after your first Roth
            contribution or conversion, once you are 59½ for most of the year. A conversion made in
            2023 stops being charged in 2028. An inherited Roth needs only the five years.
          </p>
          <Ledger
            title="Example: a 52-year-old needs $80,000 from a Roth IRA (2026)"
            rows={[
              { label: "Regular contributions", value: 40000, detail: "Untaxed" },
              {
                op: "+",
                label: "2023 conversion, all previously taxed",
                value: 30000,
                detail: "Less than five years old: 10% additional tax",
              },
              {
                op: "+",
                label: "Earnings",
                value: 14444.44,
                format: "usd_cents",
                detail: "Not qualified: income, plus 10% additional tax",
              },
              { op: "=", label: "Roth withdrawal", value: 84444.44, format: "usd_cents" },
              {
                op: "−",
                label: "Additional tax: 10% × ($30,000 + $14,444.44)",
                value: 4444.44,
                format: "usd_cents",
              },
              {
                op: "−",
                label: "Income tax on the earnings",
                value: 0,
                detail: "Below the $16,100 standard deduction",
              },
              { op: "=", label: "Left to spend", value: 80000 },
            ]}
            note="First Roth contribution in 2015. The rest of the account, $15,555.56, is earnings."
          />
          <Figure
            title="The clocks behind the example"
            caption="The five-year clock from 2015 is met, but earnings stay unqualified until the owner is 59½ for most of a year. With no birth month entered, that is the year they turn 60."
            table={{
              columns: [
                { key: "period", label: "Period" },
                { key: "from", label: "From", format: "year" },
                { key: "to", label: "Until", format: "year" },
              ],
              rows: [
                { period: "Five-year clock from the first contribution", from: 2015, to: 2020 },
                { period: "2023 conversion charged before 59½", from: 2023, to: 2028 },
                { period: "Before 59½ (born 1974)", from: 2015, to: 2034 },
              ],
            }}
          >
            <Timeline
              label="Roth five-year clocks and age 59½ for an owner born in 1974"
              from={2015}
              to={2036}
              unit="year"
              spans={[
                { from: 2015, to: 2020, label: "Five-year clock", color: "gray", row: 0 },
                { from: 2023, to: 2028, label: "2023 conversion charged", color: "orange", row: 1 },
                { from: 2015, to: 2034, label: "Before 59½", color: "orange", row: 2 },
              ]}
              events={[
                { at: 2026, label: "Withdrawal" },
                { at: 2034, label: "Earnings qualified" },
              ]}
            />
          </Figure>
          <p>
            A Roth 401(k) is its own pool with its own five-year clock. Until it is qualified, each
            withdrawal is part contributions and part earnings in proportion to the account’s
            balance, instead of contributions first.
          </p>
        </>
      ),
    },
    {
      id: "roth-history",
      title: "Entering Roth history",
      body: (
        <>
          <Callout kind="entry">
            <p>
              Without Roth history, CoastMath treats the whole existing balance as earnings and
              starts the five-year clock in the plan’s first year. Enter undistributed regular
              contributions, the first contribution year and each past conversion’s remaining
              principal. Conversions and contributions made during the projection are tracked for
              you.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              <UIPath
                steps={[
                  "Accounts",
                  "Retirement account tax history",
                  "Enter Roth contribution and conversion history",
                ]}
              />
              . Your Roth IRAs share one contribution total, so enter each dollar once.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "where-it-shows-up",
      title: "Where the charge shows up",
      body: (
        <>
          <p>
            The additional tax is part of the year’s taxes.{" "}
            <UIPath steps={["Tax tools", "Annual tax breakdown"]} /> lists it as Early withdrawal
            penalty, and the year details on Overview show Early withdrawal penalties. Where each
            dollar came from is covered in <HelpLink to="withdrawal-order" />.
          </p>
          <Symptoms
            rows={[
              {
                symptom: "Roth withdrawals are taxed after 59½",
                check: "Whether the account has Roth history entered",
                next: "Enter contributions and the first contribution year; blank history counts the balance as earnings with a new five-year clock",
              },
              {
                symptom: "A penalty appears in the year you turn 59 or 60",
                check: "Birth month (imported plans) and the table above",
                next: "The charge covers only the months before 59½",
              },
              {
                symptom: "A 401(k) is penalized after you left the job at 55",
                check: "Drawdown order and whether the account has a separation year",
                next: "Enter the year you left that employer on the 401(k) account. IRAs and other employers’ plans never qualify; reorder accounts or model a 72(t) series",
              },
              {
                symptom: "A penalty appears while a 72(t) series is running",
                check: "Which account the penalty came from",
                next: "Only the series account is exempt; other traditional accounts are still charged",
              },
            ]}
          />
        </>
      ),
    },
  ],
};

export default article;

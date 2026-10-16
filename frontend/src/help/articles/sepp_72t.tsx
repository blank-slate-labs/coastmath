import type { Article } from "../help_types";
import {
  Callout,
  DataTable,
  Figure,
  Formula,
  Frac,
  HelpLink,
  Ledger,
  Op,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";
import { LineChart } from "../help_charts";

const ages = [50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60];
const amortization = [
  30156.12, 30156.12, 30156.12, 30156.12, 30156.12, 30156.12, 30156.12, 30156.12, 30156.12,
  15078.06, 0,
];
const rmdMethod = [
  13812.15, 13773.03, 13773.03, 13731.79, 13689.54, 13646.22, 13646.22, 13554.63, 13507.73, 6729.74,
  0,
];

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath models one series of substantially equal periodic payments from one traditional
        IRA or traditional 401(k). Each year of the series, the scheduled payment comes out of that
        account before spending is funded. It is ordinary income, and it carries no 10% additional
        tax.
      </p>
      <p>
        While the series runs, the account is closed to every other withdrawal, so the projection
        never modifies the series. The series runs until the later of five years after it starts or
        the owner reaching 59½.
      </p>
    </>
  ),
  sections: [
    {
      id: "settings",
      title: "What you enter",
      body: (
        <>
          <Callout kind="where">
            <p>
              <UIPath steps={["Tax tools", "Early withdrawals"]} />. Turn on Enabled, choose the
              Source account, the Method, the Start age and the Interest rate (%), then Save SEPP
              settings. The panel previews each method’s first-year payment and an illustrative
              schedule.
            </p>
          </Callout>
          <DataTable
            caption="SEPP settings"
            columns={[
              { key: "field", label: "Setting" },
              { key: "rule", label: "How it’s used" },
            ]}
            rows={[
              {
                field: "Source account",
                rule: "A traditional IRA or traditional 401(k). A partner’s account runs on the partner’s age.",
              },
              {
                field: "Method",
                rule: "Fixed amortization or the required-minimum-distribution method. Fixed annuitization isn’t offered.",
              },
              {
                field: "Start age",
                rule: "A whole age from 18 to 59. Payments start in the owner’s birth month that year, or January if no birth month is on file.",
              },
              {
                field: "Custom yearly payment ($; optional)",
                rule: "Blank uses the method above. An amount replaces the method’s payment; it keeps the exemption only if it matches what fixed amortization pays (see below).",
              },
              {
                field: "Interest rate (%)",
                rule: "Used by fixed amortization, from 0% to 15%. Above 5% the panel shows the highest rate allowed for your first payment month: 120% of the federal mid-term rate for the two months before it, when that is higher than 5%.",
              },
            ]}
          />
          <Callout kind="entry">
            <p>
              A 401(k) series is allowed only after you have separated from that employer’s service.
              CoastMath doesn’t check this; choosing a 401(k) is your statement that it applies.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-the-payment-is-set",
      title: "How each method sets the payment",
      body: (
        <>
          <p>
            Both methods use the owner’s life expectancy from the IRS Single Life Table: fixed
            amortization at the age reached in the first year of the series, the
            required-minimum-distribution method at the age reached in each payment year.
          </p>
          <Formula
            result="Fixed amortization payment"
            note="Computed once, in the first year of the series, and repeated unchanged every year."
          >
            <V>Balance</V>
            <Op>×</Op>
            <Frac
              num={<V>rate</V>}
              den={
                <>
                  <V>1 − (1 + rate)</V>
                  <sup>−life expectancy</sup>
                </>
              }
            />
          </Formula>
          <Formula
            result="Required-minimum-distribution payment"
            note="Recalculated every year, so it moves with the balance and the owner’s age."
          >
            <V>Balance</V>
            <Op>÷</Op>
            <V>Single life expectancy at this year’s age</V>
          </Formula>
          <Ledger
            title="Example: $500,000 traditional IRA, series starting at 50, 5% rate"
            rows={[
              { label: "Balance", value: 500000 },
              { label: "Single life expectancy at 50", value: 36.2, format: "num", digits: 1 },
              {
                label: "Fixed amortization payment",
                value: 30156.12,
                format: "usd_cents",
                detail: "$500,000 × 0.05 ÷ (1 − 1.05^−36.2)",
              },
              {
                label: "Required-minimum-distribution payment, first year",
                value: 13812.15,
                format: "usd_cents",
                detail: "$500,000 ÷ 36.2",
              },
            ]}
          />
          <p>
            The projection computes the payment from the account’s balance at the end of the year
            before the series starts, before that year’s growth. In a series that starts in the
            plan’s first year this is today’s balance, so the panel’s preview matches the
            projection. The required-minimum-distribution method uses each prior year-end balance.
          </p>
        </>
      ),
    },
    {
      id: "custom-amount",
      title: "Entering your own yearly payment",
      body: (
        <>
          <p>
            Only the amounts that come from an approved method qualify for the exemption from the
            additional tax. A <strong>Custom yearly payment</strong> is checked against the fixed
            amortization payment for the same balance, age and rate. If it matches within a dollar,
            the series keeps the exemption. If not, the payment is still taken every year as income,
            but it is treated as an ordinary early withdrawal and the 10% additional tax applies.
            The preview says which case you are in and shows the approved payment.
          </p>
          <ul>
            <li>
              A custom amount can be validated only for fixed amortization, at a rate no higher than
              the greater of 5% and 120% of the federal mid-term rate for either of the two months
              before the first payment. CoastMath includes the IRS monthly rates from January 2024;
              for a first payment whose two prior months are not included, it validates rates up to
              5% only. The required-minimum-distribution method changes every year, so a fixed
              custom amount never matches it.
            </li>
            <li>
              The check is made once, in the first year, from the balance the payment is based on.
              The same payment is then repeated every year.
            </li>
            <li>
              If the account cannot pay the series in some year, CoastMath warns that this would
              modify the series. A modification can end the exemption and add a retroactive charge,
              which is not modeled.
            </li>
          </ul>
          <Callout kind="boundary">
            <p>
              CoastMath cannot confirm that your plan meets the IRS requirements. If you rely on a
              series, confirm the payment with a tax professional.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-long-it-runs",
      title: "How long the series runs",
      body: (
        <>
          <p>
            Payments are treated as monthly installments from the start month through the month
            before the later of the fifth anniversary and 59½. A first or final calendar year that
            is only partly inside that span pays only its share.
          </p>
          <Figure
            title="Annual payments from a $500,000 IRA, series starting at 50, no growth assumed"
            caption="No birth month on file, so the series starts in January at 50 and its last payment month is June of the year the owner turns 59. With growth assumed, the required-minimum-distribution payment rises with the balance instead of drifting down."
            table={{
              columns: [
                { key: "age", label: "Age", format: "age" },
                { key: "amort", label: "Fixed amortization", format: "usd" },
                { key: "rmd", label: "Required-minimum-distribution method", format: "usd" },
              ],
              rows: ages.map((age, i) => ({ age, amort: amortization[i], rmd: rmdMethod[i] })),
            }}
          >
            <LineChart
              label="SEPP payment by age for two methods"
              xFormat="age"
              step
              series={[
                {
                  id: "amort",
                  label: "Fixed amortization",
                  color: "blue",
                  points: ages.map((age, i) => [age, amortization[i]] as [number, number]),
                },
                {
                  id: "rmd",
                  label: "Required-minimum-distribution method",
                  color: "gray",
                  points: ages.map((age, i) => [age, rmdMethod[i]] as [number, number]),
                },
              ]}
            />
          </Figure>
          <DataTable
            caption="When a series ends"
            columns={[
              { key: "start", label: "Start age" },
              { key: "end", label: "Required through" },
              { key: "why", label: "Why" },
            ]}
            rows={[
              {
                start: "50",
                end: "The month before 59½",
                why: "59½ comes after the fifth anniversary",
              },
              {
                start: "56",
                end: "The month before 61",
                why: "The fifth anniversary comes after 59½",
              },
            ]}
          />
          <p>
            After the series ends, the account returns to the drawdown order and has no further
            additional tax, since the owner is past 59½. The series also stops if the account runs
            out or the owner dies.
          </p>
        </>
      ),
    },
    {
      id: "how-it-limits-the-account",
      title: "How the series limits the account",
      body: (
        <>
          <p>
            During any calendar year that contains a series payment, the account is skipped when a
            shortfall is funded and when it is chosen to pay a specific expense. Other accounts
            cover those needs, in the order described in <HelpLink to="withdrawal-order" />.
          </p>
          <Callout kind="consequence">
            <p>
              The account stays closed for the whole year in which the series ends, even after the
              last payment month. If the other accounts can’t cover that year, the projection
              records an unfunded shortfall and fails there, although the series account still has
              money.
            </p>
          </Callout>
          <Callout kind="boundary">
            <ul>
              <li>
                Modifying a series and the retroactive tax that follows. CoastMath never takes extra
                from the account, so the charge never arises.
              </li>
              <li>
                The one-time switch from fixed amortization to the required-minimum-distribution
                method, and fixed annuitization.
              </li>
              <li>
                Rules that move money into or out of the account. Roth conversion and transfer rules
                that name it still run during the series; in practice those would modify it.
              </li>
              <li>More than one series, or a series on part of an account.</li>
            </ul>
          </Callout>
        </>
      ),
    },
    {
      id: "where-it-shows-up",
      title: "Where the payments show up",
      body: (
        <>
          <p>
            Each payment appears as income named SEPP 72(t) in the year’s cash flow and is taxed as
            ordinary income. Traditional withdrawals from other accounts before 59½ are still
            charged the additional tax; see <HelpLink to="early-withdrawals" />.
          </p>
          <Symptoms
            rows={[
              {
                symptom: "The projected payment differs from the preview",
                check: "Whether your plan assumes growth in the start year",
                next: "The projection uses the start-year balance; the preview uses today’s",
              },
              {
                symptom: "A shortfall or failure in the year the series ends",
                check: "Other accounts in the drawdown order that year",
                next: "The series account is closed all of that year; it reopens the next January",
              },
              {
                symptom: "The final payment is smaller",
                check: "Birth month and start age",
                next: "Only the months before the end of the series are paid",
              },
            ]}
          />
        </>
      ),
    },
  ],
};

export default article;

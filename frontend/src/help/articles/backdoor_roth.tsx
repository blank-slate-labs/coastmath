import type { Article } from "../help_types";
import { Callout, Formula, Frac, HelpLink, KeyFigures, Ledger, Op, UIPath, V } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        Turning on Backdoor Roth for a surplus rule that funds a Roth IRA models a nondeductible
        traditional IRA contribution converted to the Roth IRA straight away. The Roth income limit
        no longer applies; the annual IRA limit and the earned-income requirement still do.
      </p>
      <p>
        If the owner holds pre-tax money in their own traditional IRAs, part of each contribution is
        taxable under the pro-rata rule. CoastMath adds that part to the year’s ordinary income and
        starts a five-year clock on it, as it would for any conversion.
      </p>
    </>
  ),
  sections: [
    {
      id: "set-it-up",
      title: "Set it up",
      body: (
        <>
          <Callout kind="where">
            <p>
              <UIPath steps={["Income allocation", "After spending", "Add allocation"]} />: choose a
              Roth IRA as the Destination account, then check Backdoor Roth.
            </p>
          </Callout>
          <p>
            The rule is funded from the year’s surplus, after spending, in its place in the rule
            list, like any other savings rule (see <HelpLink to="savings-rules" />
            ). Each year it contributes what the rule asks for, limited by the surplus left, the
            rule’s Annual maximum and the owner’s remaining IRA limit. The contribution goes
            straight to the Roth IRA; no balance passes through a traditional IRA in the plan.
          </p>
          <p>
            The option applies only to a Roth IRA destination. Without it, a Roth IRA rule is
            limited by the income phase-out, as described in{" "}
            <HelpLink to="contributions-and-employer-match" />.
          </p>
        </>
      ),
    },
    {
      id: "limits",
      title: "Which limits still apply",
      body: (
        <>
          <KeyFigures
            caption="2026 IRA limits"
            items={[
              {
                label: "IRA contribution limit",
                value: 7500,
                detail: "Shared by the owner’s traditional and Roth IRA contributions",
              },
              { label: "Additional amount at 50 or older", value: 1100 },
              {
                label: "Roth phase-out, single or head of household",
                value: "$153,000–$168,000",
                detail: "Bypassed by the backdoor",
              },
              {
                label: "Roth phase-out, married filing jointly",
                value: "$242,000–$252,000",
                detail: "Bypassed by the backdoor",
              },
            ]}
          />
          <p>
            Contributions can’t exceed the owner’s earned income for the year; a couple filing
            jointly can use their combined earned income. CoastMath raises the limits with inflation
            in later years. Other contributions to the same owner’s IRAs earlier in the list use up
            the limit first.
          </p>
        </>
      ),
    },
    {
      id: "pro-rata-rule",
      title: "How the taxable share is calculated",
      body: (
        <>
          <Formula result="Taxable share">
            <V>Contribution</V>
            <Op>×</Op>
            <Frac
              num={<V>Pre-tax traditional IRA balance</V>}
              den={<V>Pre-tax traditional IRA balance + contribution</V>}
            />
          </Formula>
          <p>
            The pre-tax balance is the total in the owner’s own traditional IRAs when the
            contribution is made. A partner’s IRAs, inherited IRAs and 401(k)s don’t count. With no
            pre-tax IRA money the whole contribution converts tax-free.
          </p>
          <Ledger
            title="Example: $7,500 backdoor contribution with a $67,500 rollover IRA"
            rows={[
              { label: "Contribution", value: 7500 },
              {
                op: "×",
                label: "Pre-tax share: $67,500 ÷ $75,000",
                value: 0.9,
                format: "pct",
                digits: 0,
              },
              { op: "=", label: "Taxable share, added to ordinary income", value: 6750 },
              { op: "×", label: "Marginal federal rate", value: 0.32, format: "pct", digits: 0 },
              { op: "=", label: "Added federal income tax", value: 2160 },
            ]}
            note="Single filer with a $250,000 salary in 2026; the tax is the difference between runs with and without the rollover IRA."
          />
          <p>
            The taxable share is included in the year’s income and tax. It’s taxed like conversion
            income, never charged the early-withdrawal penalty, and settled with the rest of the
            year’s tax. The projection also shows a warning whenever a backdoor contribution was
            partly taxable.
          </p>
          <Callout kind="boundary">
            <ul>
              <li>
                The pre-tax balance is taken at the point in the year the contribution is made. The
                tax return uses the year-end IRA balance plus that year’s distributions and
                conversions, so the result can differ when the balance changes during the year.
              </li>
              <li>
                The after-tax money left in the traditional IRA ($6,750 in the example) isn’t
                tracked, so it’s taxed again when it’s withdrawn or converted later. Projected
                lifetime tax is overstated by that amount times the later rate.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
    {
      id: "five-year-clock",
      title: "The five-year clock",
      body: (
        <>
          <p>
            Each backdoor contribution is recorded in the Roth IRA as a conversion for its year,
            split into the taxable share and the tax-free share. Withdrawing the taxable share
            within five years and before 59½ costs the 10% additional tax; the tax-free share can
            come out without it. Roth IRA money comes out regular contributions first, then
            conversions oldest first, then earnings. See <HelpLink to="roth-conversions" /> and{" "}
            <HelpLink to="early-withdrawals" />.
          </p>
        </>
      ),
    },
    {
      id: "mega-backdoor",
      title: "Mega backdoor Roth (401(k))",
      body: (
        <>
          <Callout kind="where">
            <p>
              <UIPath
                steps={[
                  "Income allocation",
                  "Payroll contributions and account transfers",
                  "Add payroll or transfer rule",
                ]}
              />
              : choose Mega backdoor Roth as the Priority type, a Roth 401(k) as the Destination
              account and the owner’s W-2 wages as the Source income.
            </p>
          </Callout>
          <p>
            The rule models after-tax 401(k) contributions converted in the plan to the Roth 401(k)
            at once. They come out of taxed pay: no deduction and no change to payroll taxes. With
            no earnings between contribution and conversion, nothing is taxed; the dollars are
            recorded in the Roth 401(k) as a tax-free in-plan rollover. Each year it contributes the
            remaining room, limited by the rule’s Annual maximum and the pay earlier rules left.
          </p>
          <Formula result="Room">
            <V>Employee plus employer limit</V>
            <Op>−</Op>
            <V>Employee deferrals, without catch-up</V>
            <Op>−</Op>
            <V>Employer contributions</V>
          </Formula>
          <p>
            The limit is $72,000 in 2026, never more than the owner’s pay, and counts all of the
            owner’s 401(k)s from W-2 jobs. A solo 401(k) funded from self-employment has its own
            limit. Rules run in list order, so put this rule below the deferral and employer rules
            it should leave room for; a rule below it finds the room already used. See{" "}
            <HelpLink to="contributions-and-employer-match" />.
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
                Whether the employer’s plan accepts after-tax contributions or in-plan conversions.
                Set an Annual maximum for a plan cap.
              </li>
              <li>After-tax 401(k) contributions made earlier this tax year.</li>
              <li>
                After-tax money already sitting in a traditional IRA; every other conversion is
                treated as fully pre-tax.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
  ],
};

export default article;

import type { Article } from "../help_types";
import { Callout, Formula, HelpLink, KeyFigures, Ledger, Op, Pair, UIPath, V } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath charges the employee share of Social Security and Medicare tax on wages and both
        shares on self-employment earnings. It adds the 0.9% Additional Medicare Tax once household
        earnings pass your filing status’s threshold. Each person has their own Social Security wage
        base, shared between their jobs and their business. Every year it also works out the
        alternative minimum tax and adds any amount by which it exceeds your regular federal tax.
      </p>
      <p>
        Payroll tax is part of total taxes. It is listed as <strong>Payroll tax</strong> in{" "}
        <UIPath steps={["Tax tools", "Annual tax breakdown"]} />, and any minimum tax is inside{" "}
        <strong>Federal ordinary tax (including any AMT adjustment)</strong>.
      </p>
    </>
  ),
  sections: [
    {
      id: "social-security-and-medicare-tax",
      title: "Social Security and Medicare tax on wages",
      body: (
        <>
          <KeyFigures
            caption="2026 payroll tax, employee share"
            items={[
              {
                label: "Social Security",
                value: "6.2%",
                detail: "On each person’s wages up to $184,500",
              },
              { label: "Medicare", value: "1.45%", detail: "On all wages" },
              {
                label: "Additional Medicare Tax",
                value: "0.9%",
                detail:
                  "Above $200,000 single or head of household, $250,000 joint, $125,000 separate",
              },
            ]}
          />
          <p>
            Wages here are gross pay. Pre-tax 401(k) deferrals lower income tax but not payroll tax.
            HSA contributions made through a cafeteria plan lower both (see <HelpLink to="hsa" />
            ). Employer contributions are not wages. The employer’s matching share of payroll tax
            isn’t part of your taxes.
          </p>
          <p>
            The Social Security base applies to each person across all of their wages, so a second
            job doesn’t add a second base. The Additional Medicare Tax threshold applies to the
            whole return. On a joint return it uses both spouses’ earnings together, even when
            neither alone passes $200,000.
          </p>
          <Pair
            left={{
              title: "Single, $230,000 of wages",
              body: (
                <Ledger
                  title="2026 payroll tax"
                  rows={[
                    { label: "Social Security, 6.2% × $184,500", value: 11439 },
                    { op: "+", label: "Medicare, 1.45% × $230,000", value: 3335 },
                    { op: "+", label: "Additional, 0.9% × $30,000", value: 270 },
                    { op: "=", label: "Payroll tax", value: 15044 },
                  ]}
                />
              ),
            }}
            right={{
              title: "Joint, $180,000 and $120,000 of wages",
              body: (
                <Ledger
                  title="2026 payroll tax"
                  rows={[
                    { label: "Social Security, 6.2% × $300,000", value: 18600 },
                    { op: "+", label: "Medicare, 1.45% × $300,000", value: 4350 },
                    { op: "+", label: "Additional, 0.9% × $50,000", value: 450 },
                    { op: "=", label: "Payroll tax", value: 23400 },
                  ]}
                />
              ),
            }}
          />
          <p>
            In later years the wage base grows with your plan’s inflation assumption. The Additional
            Medicare Tax thresholds are fixed in the law and stay put.
          </p>
        </>
      ),
    },
    {
      id: "self-employment-tax",
      title: "Self-employment tax",
      body: (
        <>
          <p>
            Self-employment income is entered as net business profit. CoastMath applies the ordinary
            method: 92.35% of profit is self-employment earnings, and nothing is due if earnings are
            under $400. Earnings pay 12.4% for Social Security, up to whatever of the wage base that
            person’s wages haven’t used, and 2.9% for Medicare with no limit. Self-employment
            earnings count toward the Additional Medicare Tax threshold along with wages.
          </p>
          <Formula result="Self-employment tax">
            <V>12.4% × min(Earnings, Wage base − Wages)</V>
            <Op>+</Op>
            <V>2.9% × Earnings</V>
          </Formula>
          <p>
            Half of the Social Security and Medicare portions is deducted in arriving at adjusted
            gross income. The Additional Medicare Tax is not part of that deduction.
          </p>
          <Ledger
            title="Example: single, $100,000 of net business profit, 2026"
            rows={[
              { label: "Net profit", value: 100000 },
              { op: "×", label: "Earnings share", value: 0.9235, format: "pct", digits: 2 },
              { op: "=", label: "Self-employment earnings", value: 92350 },
              { op: "→", label: "Social Security, 12.4%", value: 11451.4, format: "usd_cents" },
              { op: "+", label: "Medicare, 2.9%", value: 2678.15, format: "usd_cents" },
              { op: "=", label: "Self-employment tax", value: 14129.55, format: "usd_cents" },
              { op: "→", label: "Deductible half", value: 7064.78, format: "usd_cents" },
            ]}
          />
          <Ledger
            title="Example: single, $150,000 of wages and $60,000 of business profit, 2026"
            rows={[
              { label: "Self-employment earnings, 92.35% × $60,000", value: 55410 },
              { label: "Wage base left after wages", value: 34500, detail: "$184,500 − $150,000" },
              { op: "→", label: "Social Security, 12.4% × $34,500", value: 4278 },
              { op: "+", label: "Medicare, 2.9% × $55,410", value: 1606.89, format: "usd_cents" },
              {
                op: "+",
                label: "Additional Medicare, 0.9% × $5,410",
                value: 48.69,
                format: "usd_cents",
                detail: "Wages and earnings together pass $200,000",
              },
            ]}
            note="Wages also owe $9,300 of Social Security tax and $2,175 of Medicare tax; the year’s payroll tax is $17,408.58."
          />
          <p>
            Business expenses, retirement plans and the qualified business income deduction are
            covered in <HelpLink to="self-employment-income" />.
          </p>
          <Callout kind="boundary">
            <p>
              The optional methods for low earnings, church employee income and farm rules are not
              modeled.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "alternative-minimum-tax",
      title: "Alternative minimum tax",
      body: (
        <>
          <p>
            CoastMath recomputes each year’s income under the minimum tax rules. Starting from
            regular taxable income, it adds back deductions the minimum tax disallows: the standard
            deduction, or capped state and local taxes if you itemize, plus the senior deduction.
            Mortgage interest and charitable gifts stay deducted. An exemption comes off, which
            phases out by 50 cents for each dollar above the start. The rest is taxed at 26%, then
            28%. Qualified dividends and long-term gains keep their 0, 15 and 20 percent rates. If
            the result exceeds your regular income tax plus capital gains tax, the difference is
            added to federal tax.
          </p>
          <KeyFigures
            caption="2026 alternative minimum tax"
            items={[
              {
                label: "Exemption",
                value: "$90,100",
                detail: "$140,200 joint, $70,100 married filing separately",
              },
              {
                label: "Exemption phase-out starts",
                value: "$500,000",
                detail: "Single or separate; $1,000,000 joint",
              },
              {
                label: "28% rate starts",
                value: "$244,500",
                detail: "$122,250 married filing separately",
              },
            ]}
          />
          <p>
            These amounts grow with your plan’s inflation assumption in later years. A year with a
            large gain can trigger it: the gain lifts minimum tax income past the phase-out start
            and removes most of the exemption.
          </p>
          <Ledger
            title="Example: single, $216,100 of ordinary income and a $400,000 long-term gain, 2026"
            rows={[
              {
                label: "Regular taxable income",
                value: 600000,
                detail: "$200,000 ordinary after the standard deduction, plus the gain",
              },
              { op: "+", label: "Standard deduction added back", value: 16100 },
              { op: "=", label: "Minimum tax income", value: 616100 },
              {
                op: "−",
                label: "Exemption after phase-out",
                value: 32050,
                detail: "$90,100 − 50% × ($616,100 − $500,000)",
              },
              { op: "=", label: "Minimum tax base", value: 584050 },
              { op: "→", label: "26% on the $184,050 that isn’t gain", value: 47853 },
              { op: "+", label: "Gain at capital gains rates", value: 62725 },
              { op: "=", label: "Tentative minimum tax", value: 110578 },
              {
                op: "−",
                label: "Regular income tax and capital gains tax",
                value: 103323,
                detail: "$40,598 + $62,725",
              },
              { op: "=", label: "Minimum tax added", value: 7255 },
            ]}
          />
          <Callout kind="boundary">
            <p>
              Incentive stock options, private activity bond interest, depreciation adjustments and
              the minimum tax credit in later years are not modeled.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "where-to-check",
      title: "Where to check",
      body: (
        <>
          <Callout kind="where">
            <p>
              <UIPath steps={["Tax tools", "Annual tax breakdown"]} /> lists{" "}
              <strong>Payroll tax</strong> and{" "}
              <strong>Federal ordinary tax (including any AMT adjustment)</strong> for the selected
              year. Wages and business income are set in <UIPath steps={["Income streams"]} />; see{" "}
              <HelpLink to="wages-and-raises" /> and <HelpLink to="payroll-deductions" />.
            </p>
          </Callout>
          <p>
            For how these taxes fit into the full return, see{" "}
            <HelpLink to="how-taxes-are-calculated" />.
          </p>
        </>
      ),
    },
  ],
};
export default article;

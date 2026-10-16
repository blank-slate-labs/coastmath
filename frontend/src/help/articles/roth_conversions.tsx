import type { Article } from "../help_types";
import {
  Callout,
  Figure,
  Formula,
  HelpLink,
  Ledger,
  Op,
  Symptoms,
  UIPath,
  V,
  hostedPart,
} from "../help_kit";
import { BracketBar } from "../help_charts";

/* 2026 single-filer federal brackets up to 24% (the chart's range). */
const singleBrackets = [
  { rate: 0.1, upTo: 12400 },
  { rate: 0.12, upTo: 50400 },
  { rate: 0.22, upTo: 105700 },
  { rate: 0.24, upTo: 201775 },
];

const article: Article = {
  intro: (
    <>
      <p>
        A Roth conversion rule moves money from a traditional IRA or 401(k) to a Roth IRA or Roth
        401(k) owned by the same person, every year the rule is active. CoastMath converts either up
        to a fixed annual cap or just enough to fill a federal tax bracket, optionally held below an
        income cap. It runs after the year’s required distributions and before the year’s surplus is
        saved or its shortfall funded.
      </p>
      <p>
        The converted amount is ordinary income for the year. The tax isn’t taken from the
        conversion: it’s part of the year’s tax bill, paid from that year’s cash flow and, if that
        isn’t enough, by your withdrawal order.
      </p>
    </>
  ),
  sections: [
    {
      id: "set-up-a-conversion",
      title: "Set up a conversion rule",
      body: (
        <>
          <p>
            Every rule has a traditional source and a Roth destination for the same owner. There are
            three ways to create one:
          </p>
          <ul>
            <li>
              <strong>A fixed annual cap.</strong>{" "}
              <UIPath steps={["Tax tools", "Conversion scenarios"]} /> under Manual Roth
              conversions: choose the Traditional source and Roth destination and enter the Annual
              conversion cap. The rule runs every year until the source is empty.
            </li>
            <li>
              <strong>Fill a bracket.</strong>{" "}
              <UIPath steps={["Tax tools", "Strategy comparisons"]} />: compare bracket targets,
              then Apply one. The applied rule keeps the Convert from and Convert until milestones
              and the MAGI cap you chose (see{" "}
              <a href="#compare-strategies">Compare strategies before applying one</a>).
            </li>
            <li>
              <strong>From the allocation list.</strong>{" "}
              <UIPath
                steps={["Income allocation", "Payroll contributions and account transfers"]}
              />
              , with the priority type Roth conversion. Its Annual maximum works like the cap above.
            </li>
          </ul>
          <Callout kind="entry">
            <p>
              A Roth conversion rule in Income allocation with a blank Annual maximum converts the
              entire source balance in its first year. The cap is in future dollars: the same amount
              every year, not raised with inflation.
            </p>
          </Callout>
          <p>
            Conversion rules run in list order. When several are active in one year, a later rule
            gets only the bracket and income room the earlier ones left.
            {hostedPart("roth-conversions.iphone", "")}
          </p>
        </>
      ),
    },
    {
      id: "how-the-amount-is-set",
      title: "How the amount is calculated",
      body: (
        <>
          <p>
            A fixed rule converts its cap, or the whole remaining balance if that’s smaller. A
            fill-to-bracket rule converts the room left below the top of the chosen bracket:
          </p>
          <Formula result="Fill-to-bracket conversion">
            <V>Top of the chosen bracket</V>
            <Op>−</Op>
            <V>Taxable ordinary income before the conversion</V>
          </Formula>
          <p>
            Taxable ordinary income is the year’s income after deductions, not counting long-term
            gains and qualified dividends. Bracket tops are the federal brackets for your filing
            status, indexed as described in <HelpLink to="federal-brackets-and-deductions" />. Plans
            using flat tax rates have no brackets to fill, so these rules convert nothing.
          </p>
          <p>
            An income cap then limits either kind of rule: the cap, raised each year by the plan’s
            inflation rate because you enter it in today’s dollars, less the year’s modified
            adjusted gross income before the conversion.
          </p>
          <Ledger
            title="Example: fill to the top of the 22% bracket, single filer at 62"
            rows={[
              { label: "Pension", value: 40000 },
              { op: "−", label: "Standard deduction", value: 16100 },
              { op: "=", label: "Taxable ordinary income before the conversion", value: 23900 },
              { label: "Top of the 22% bracket", value: 105700 },
              { op: "−", label: "Taxable ordinary income before the conversion", value: 23900 },
              { op: "=", label: "Roth conversion", value: 81800 },
              { label: "Federal income tax with the conversion", value: 17966 },
              { op: "−", label: "Federal income tax without it", value: 2620 },
              { op: "=", label: "Federal tax on the conversion", value: 15346 },
            ]}
            note="2026 figures. With an income cap of $100,000 the same year converts $60,000: the cap less the $40,000 of income before the conversion."
          />
          <Figure
            title="Where the conversion lands in the 2026 brackets"
            caption="The conversion fills the 22% bracket exactly; nothing reaches 24%."
          >
            <BracketBar
              label="Pension income after the deduction fills the 10% and part of the 12% bracket; the $81,800 conversion fills the rest of 12% and all of 22%"
              brackets={singleBrackets}
              segments={[
                { label: "Pension after the deduction", amount: 23900, color: "blue" },
                { label: "Roth conversion", amount: 81800, color: "cyan" },
              ]}
              max={130000}
            />
          </Figure>
          <Callout kind="boundary">
            <p>
              The room is measured before the year’s withdrawals. Withdrawals from traditional
              accounts later in the year, including any taken to pay the conversion’s tax, and gains
              realized by selling investments can push the final income above the bracket top or the
              income cap.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "plan-tax-target",
      title: "Use the plan tax target",
      body: (
        <>
          <p>
            A conversion or gain harvest rule can take its room from the plan’s tax target instead
            of its own bracket and income cap. Check <strong>Use plan tax target</strong> on the
            rule. The rule then converts, or harvests, as much as keeps the year’s final income
            within the target and every ceiling you checked with it: the net investment income tax
            threshold, the first Medicare IRMAA tier (using the ranges projected for the premium
            year two years later) or a share of the poverty line in Marketplace coverage years. Its
            annual maximum still applies.
          </p>
          <p>
            With a 12% bracket target and no gains or dividends, a rule using the plan target
            converts exactly what a fill-to-12% rule converts. Bracket targets count capital gains
            and qualified dividends in taxable income, so in a year with gains it converts less,
            leaving the gains within the bracket.
          </p>
          <p>
            Rules using the target share one room with each other and with withdrawals that fill the
            target (see <HelpLink to="withdrawal-order#fill-a-tax-target" />
            ). Gain harvests use it first, then the first withdrawal pass, then conversions in list
            order.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "Tax target"]} /> sets the target. The checkbox is on
              each rule under Manual Roth conversions in{" "}
              <UIPath steps={["Tax tools", "Conversion scenarios"]} />. Without a target, a rule set
              to use it converts nothing.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-the-tax-is-paid",
      title: "How the tax is paid",
      body: (
        <>
          <p>
            The whole amount converted is taxable. The conversion itself is never charged the
            early-withdrawal penalty, at any age. Its tax is part of the year’s federal and state
            tax, settled like any other tax (see <HelpLink to="tax-payments-and-settlement" />
            ): from the year’s income first, then by your withdrawal order. If that order reaches a
            traditional account, the extra withdrawal is taxed too.
          </p>
          <p>
            In the example above the tax came from a brokerage account. The sale realized a small
            gain, which the higher income moved from the 0% to the 15% capital-gains rate, so total
            tax rose by $15,541, not only the $15,346 of federal tax on the conversion.
          </p>
          <p>
            Conversion income counts in adjusted gross income, so it can also raise the taxable
            share of Social Security, the Medicare premiums charged two years later, and Marketplace
            premiums through a smaller credit. See <HelpLink to="medicare-and-irmaa" /> and{" "}
            <HelpLink to="marketplace-health-coverage" />.
          </p>
        </>
      ),
    },
    {
      id: "five-year-clock",
      title: "The five-year clock on converted money",
      body: (
        <>
          <p>
            Each year’s conversions start their own five-year clock on January 1 of that year.
            Withdrawing converted money before its clock runs out, and before 59½, costs the 10%
            additional tax on the part that was taxable when converted. The money itself isn’t taxed
            again.
          </p>
          <p>
            Roth IRA withdrawals come out in a fixed order across all of the owner’s Roth IRAs:
            regular contributions first, then conversions oldest year first, then earnings. So
            converted money is reached only after contributions are used up. Roth 401(k) withdrawals
            follow a different, proportional rule; both are covered in{" "}
            <HelpLink to="early-withdrawals" />.
          </p>
          <Callout kind="entry">
            <p>
              Conversions made before the plan starts need to be entered on the Roth account under
              “Enter Roth contribution and conversion history”, with each conversion’s tax year and
              its remaining taxable and nontaxable principal. Without them, CoastMath doesn’t know
              those dollars are protected from tax and when their clocks end.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "compare-strategies",
      title: "Compare strategies before applying one",
      body: (
        <>
          <p>
            Strategy comparisons tests fill-to-bracket rules against your plan without changing it.
            You choose the Pre-tax source, the Roth destination, when to convert (Convert from,
            default Start of plan; Convert until, default Funds are exhausted), an optional MAGI cap
            in today’s dollars, the objective, and the bracket ceilings to test from 10% to 32%.
          </p>
          <p>
            CoastMath runs the full projection once with no new conversions and once for each
            ceiling. For each it reports the objective and its difference from the baseline, the
            total converted and over how many years, lifetime taxes, health coverage costs, net
            estate, the years with a Medicare surcharge, and the years that lost a premium tax
            credit. The best result is only the best of the ceilings you tested, and a strategy that
            makes the plan run short is marked. Nothing changes until you Apply one.
          </p>
          <Callout kind="boundary">
            <p>
              The net estate and end net worth objectives count pre-tax balances after income tax at
              the heirs’ income tax rate in Partner and estate, or 24% when it is zero, without the
              estate tax deduction. The Net estate column is not reduced. Health coverage effects
              appear only when health coverage is modeled in the plan.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "advanced-search",
      title: "Search a wider set of strategies",
      body: (
        <>
          <p>
            Open <strong>Advanced search</strong> under{" "}
            <UIPath steps={["Tax tools", "Strategy comparisons"]} /> to try more than bracket
            ceilings. You choose which bracket rates to test as the plan tax target, which actions
            to pair with them (Roth conversions, capital gain harvesting, blending withdrawals up to
            the target), any of three alternative withdrawal orders (cash and taxable accounts
            first, pre-tax accounts first, Roth before pre-tax), up to four timing windows, and one
            objective. Each side of a window is a milestone, a calendar year or your age, and a year
            or age end is included: a window from 2030 through 2035 stops at the start of 2036.
            Besides the objectives in the comparison, you can rank by lifetime effective tax rate,
            total Marketplace premium credits, total required distributions or total Medicare
            surcharges. Each objective says whether higher or lower is better.
          </p>
          <p>
            The search runs in stages and every candidate is a full projection of your plan. It
            first tries each bracket rate you picked with all your chosen actions on, which ranks the
            rates. Combinations with the other choices follow: simpler ones at the best rate and its
            neighbours, then simpler ones at the other rates, then the rest. Identical candidates are
            simulated once. The simulation budget, from 2 to 128, is a hard limit: when the
            combinations outnumber it, the search says how many it skipped and the rest are left
            unsimulated.
          </p>
          <p>
            Results are ranked by the objective, with a plan that runs short ranked last. The best
            result is only the best of the combinations that were simulated: a different rate, order
            or window you didn’t include could do better, so treat it as a lead, not an optimum. A
            withdrawal order preset regroups your saved order by account type and keeps your saved
            order within each group.
          </p>
          <Callout kind="where">
            <p>
              Nothing changes until you choose <em>Review</em> on a result and then{" "}
              <em>Apply to plan</em>. The review lists each rule, tax target, blending setting and
              withdrawal order it will write. Allocation rules are saved against the revision the
              search used. If the plan changed in another session since then, nothing is applied:
              your review stays open and you choose <em>Review latest saved plan</em> to reload the
              current plan and decide again. If one step of a multi-step apply fails, the review
              says which steps saved and which didn’t, and a retry writes only the remainder.
            </p>
          </Callout>
          <Callout kind="boundary">
            <p>
              Applying a result replaces the plan’s tax target, which then applies to every rule
              that uses it. Applying a result with a year or age window first adds a milestone for
              each year or age bound (or reuses a saved milestone with the same date or age), then
              the rules that use it. As in the comparison, the room for each conversion is measured
              before the year’s withdrawals. The effective rate objective is lifetime taxes over
              lifetime income, with each year weighted by its income and taxable Roth conversions
              counted as income, so converting more raises the denominator as well as the taxes.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "limits-and-surprises",
      title: "What isn’t modeled and common surprises",
      body: (
        <>
          <Callout kind="boundary">
            <ul>
              <li>
                After-tax (nondeductible) money in a traditional IRA: every conversion is treated as
                fully pre-tax. Backdoor contributions are the exception; see{" "}
                <HelpLink to="backdoor-roth" />.
              </li>
              <li>Whether your employer’s plan allows in-plan conversions.</li>
              <li>
                Converting a required distribution: the year’s required distribution always comes
                out first.
              </li>
            </ul>
          </Callout>
          <Symptoms
            rows={[
              {
                symptom: "Income ends the year above the bracket you filled.",
                check: "Withdrawals from traditional accounts or realized gains that year.",
                next: "Expected: the room is measured before withdrawals. A lower bracket target or a cap leaves a margin.",
              },
              {
                symptom: "The whole traditional balance converts in one year.",
                check: "A Roth conversion rule in Income allocation with a blank Annual maximum.",
                next: "Enter an annual maximum, or use a fill-to-bracket rule.",
              },
              {
                symptom: "A fill-to-bracket rule converts nothing in some years.",
                check:
                  "Income before the conversion already above the bracket top or the income cap, the rule’s milestones, or an empty source.",
                next: "Check the year on the Tax tools tab; a later rule in the list may also find no room left.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};

export default article;

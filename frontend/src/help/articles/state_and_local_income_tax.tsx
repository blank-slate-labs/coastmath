import type { Article } from "../help_types";
import {
  Callout,
  DataTable,
  Figure,
  Formula,
  HelpLink,
  KeyFigures,
  Ledger,
  Op,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";
import { BracketBar } from "../help_charts";

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath adds a resident state income tax and, if you pick one, a local income tax to each
        year’s federal calculation. State tax starts from federal adjusted gross income, including
        long-term gains and qualified dividends. CoastMath subtracts the state’s standard deduction
        and applies the state’s 2026 brackets, with changes already written into state law for later
        years. Local tax applies the selected locality’s rate to the base that locality taxes.
      </p>
      <p>
        The state layer is a simplified model of each state’s return. It applies each state’s
        treatment of Social Security, the retirement-income exclusions below, Washington’s capital
        gains tax and the recovery of retirement contributions a state already taxed. Other state
        subtractions, exemptions and credits aren’t applied, apart from California’s.
      </p>
    </>
  ),
  sections: [
    {
      id: "what-you-enter",
      title: "What you enter",
      body: (
        <>
          <p>
            <strong>State</strong> is where you live at the plan’s start.{" "}
            <strong>Local income tax</strong> lists the catalog localities for that state, plus{" "}
            <strong>Custom rates</strong>. A later move goes in the residency timeline, and each
            residence carries its own locality. See <HelpLink to="moving-states" />.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "State"]} /> and{" "}
              <UIPath steps={["Plan details", "Local income tax"]} />.
            </p>
          </Callout>
          <Callout kind="entry" title="A locality belongs to one state">
            <p>
              Changing the state clears a catalog locality, but custom rates stay. A residency
              change with no locality has no local tax, even if the starting residence has one.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-state-tax-is-calculated",
      title: "How state tax is calculated",
      body: (
        <>
          <Formula result="State taxable income">
            <V>Federal AGI, including gains and qualified dividends</V>
            <Op>−</Op>
            <V>State standard deduction</V>
          </Formula>
          <p>
            The state’s brackets apply to that amount. Capital gains are ordinary income for the
            state, except that Wisconsin, Arkansas, North Dakota, South Carolina and Vermont exclude
            part of a long-term gain and Montana and Hawaii tax it at lower rates. On a joint
            return, CoastMath uses the state’s published joint schedule where it has one (New
            Jersey, Maryland, Maine, New York, Minnesota, Wisconsin, New Mexico, North Dakota and
            Vermont), the same schedule as single filers where every filer shares one (DC,
            Massachusetts, Ohio, Virginia, Rhode Island, South Carolina and West Virginia), and
            doubles the single-filer thresholds and deduction elsewhere. Heads of household use
            their state’s own schedule where CoastMath has one. Actual joint and head-of-household
            schedules in other states can differ. Maryland adds 2% of your net capital gain when
            federal AGI is over $350,000, whatever your filing status; that threshold doesn’t grow
            with inflation. Built-in thresholds and deductions stay at their 2026 values for 2026,
            then grow each year with your inflation assumption. An amount a law sets for a later
            year applies as written in that year, then grows the same way; see{" "}
            <a href="#enacted-changes">Changes already in law</a>.
          </p>
          <p>
            Pennsylvania taxes the money you put into a traditional 401(k), 403(b), 457(b) or IRA,
            so CoastMath adds those contributions back to Pennsylvania income. HSA contributions
            stay excluded, as they are federally. New Jersey taxes traditional IRA contributions,
            403(b) and 457(b) deferrals and employer money paid into a 403(b) in the year they’re
            made, but not 401(k) deferrals. Massachusetts taxes traditional IRA contributions only.
            Those taxed contributions are tracked for each account and come back tax free when you
            withdraw while living in the same state; see{" "}
            <a href="#taxed-contributions">Contributions your state already taxed</a>.
          </p>
          <DataTable
            caption="How each state is represented"
            columns={[
              { key: "structure", label: "Structure" },
              { key: "states", label: "Jurisdictions" },
            ]}
            rows={[
              {
                structure: "No broad income tax",
                states:
                  "Alaska, Florida, Nevada, New Hampshire, South Dakota, Tennessee, Texas, Washington (through 2027), Wyoming",
              },
              {
                structure: "One flat rate",
                states:
                  "Arizona, Colorado, Georgia, Illinois, Indiana, Iowa, Kentucky, Louisiana, Michigan, North Carolina, Pennsylvania, Utah",
              },
              {
                structure: "Graduated brackets",
                states: "All other states and the District of Columbia",
              },
              {
                structure: "No standard deduction applied",
                states:
                  "Connecticut, Illinois, Indiana, Massachusetts, Michigan, New Jersey, Ohio, Pennsylvania, Utah, West Virginia",
              },
            ]}
            note="Where a state hadn’t published its 2026 tables, the most recent published table is used."
          />
          <Ledger
            title="Example: single filer in New York City, 2026"
            rows={[
              { label: "Wages", value: 90000 },
              { op: "+", label: "Long-term capital gains", value: 10000 },
              { op: "−", label: "New York standard deduction", value: 8000 },
              { op: "=", label: "New York taxable income", value: 92000 },
              { op: "→", label: "New York income tax", value: 4859.75, format: "usd_cents" },
              {
                op: "→",
                label: "New York City tax before credits",
                value: 3441.09,
                format: "usd_cents",
              },
              {
                op: "−",
                label: "City school tax credit, rate reduction",
                value: 202.92,
                format: "usd_cents",
              },
              {
                op: "−",
                label: "City school tax credit, fixed amount",
                value: 63,
                format: "usd_cents",
              },
              { op: "=", label: "New York City income tax", value: 3175.17, format: "usd_cents" },
            ]}
            note="No pre-tax payroll deductions. The city tax uses the state taxable income from the fourth row."
          />
          <Figure
            title="New York taxable income across the 2026 single brackets"
            caption="The gains are taxed at the same 5.9% rate as the wages below them."
            table={{
              columns: [
                { key: "layer", label: "Layer" },
                { key: "amount", label: "Amount", format: "usd" },
              ],
              rows: [
                { layer: "Wages after the standard deduction", amount: 82000 },
                { layer: "Long-term capital gains", amount: 10000 },
              ],
            }}
          >
            <BracketBar
              label="New York taxable income of $92,000: $82,000 of wages after the deduction, then $10,000 of gains, reaching the 5.9% bracket"
              brackets={[
                { rate: 0.039, upTo: 8500 },
                { rate: 0.044, upTo: 11700 },
                { rate: 0.0515, upTo: 13900 },
                { rate: 0.054, upTo: 80650 },
                { rate: 0.059, upTo: 215400 },
                { rate: 0.0685, upTo: null },
              ]}
              segments={[
                { label: "Wages after deduction", amount: 82000, color: "blue" },
                { label: "Long-term gains", amount: 10000, color: "cyan" },
              ]}
              max={120000}
            />
          </Figure>
        </>
      ),
    },
    {
      id: "enacted-changes",
      title: "Changes already in law",
      body: (
        <>
          <p>
            Where a state has already enacted a dated change for 2027 or later, CoastMath applies it
            from that year: each year uses the latest change in effect, and a change replaces only
            the rates or amounts it sets. Cuts that happen only if a future revenue test is met
            aren’t applied until they’re certified.
          </p>
          <DataTable
            caption="Enacted changes CoastMath applies"
            columns={[
              { key: "state", label: "State" },
              { key: "year", label: "From" },
              { key: "change", label: "Change" },
            ]}
            rows={[
              {
                state: "Georgia",
                year: "2027",
                change:
                  "Retirement-income exclusion at 65 or older rises from $65,000 to $70,000 per person",
              },
              {
                state: "Hawaii",
                year: "2027–2031",
                change:
                  "Wider brackets in 2027 and 2029; standard deduction $9,000 (2028), $10,000 (2030), $12,000 (2031) for single filers, doubled for joint returns",
              },
              { state: "Indiana", year: "2027", change: "Rate 2.95% to 2.9%" },
              {
                state: "Mississippi",
                year: "2027–2030",
                change: "Rate above $10,000: 3.75%, 3.5%, 3.25%, then 3%",
              },
              {
                state: "Montana",
                year: "2027",
                change:
                  "Lower rate up to $65,000 single ($130,000 joint); top rate 5.65% to 5.4%; capital gain bands move with it",
              },
              { state: "Nebraska", year: "2027", change: "Top rate 4.55% to 3.99%" },
              {
                state: "New York",
                year: "2027, 2033",
                change:
                  "Lower five rates cut 0.1 point in 2027; the 9.65%, 10.3% and 10.9% rates end after 2032, with 8.82% above $1,077,550 single ($2,155,350 joint)",
              },
              {
                state: "Virginia",
                year: "2027–2030",
                change:
                  "Standard deduction $9,200 (2027), $9,300 (2028–2029), then $3,000 from 2030; doubled for joint returns",
              },
              {
                state: "Washington",
                year: "2028",
                change: "9.9% income tax above $1,000,000 per person or married couple; see below",
              },
            ]}
          />
          <Ledger
            title="Example: single filer in Nebraska, $100,000 taxable"
            rows={[
              { label: "2026 tax at 2.46%, 3.51% and 4.55%", value: 4256.84, format: "usd_cents" },
              { label: "2027 tax with the 3.99% top rate", value: 3831.91, format: "usd_cents" },
              { op: "=", label: "Difference", value: 424.93, format: "usd_cents" },
            ]}
            note="Both years at 2026 thresholds, with no inflation."
          />
          <Callout kind="boundary" title="Not applied until certified">
            <ul>
              <li>
                North Carolina: 0.5-point cuts (3.49% for 2027) when a year’s revenue beats its
                trigger.
              </li>
              <li>
                Georgia: yearly 0.125-point rate cuts to 3.99% and higher standard and dependent
                deductions, each delayed in any year the state’s revenue and reserve tests fail.
              </li>
              <li>
                Mississippi after 2030, South Carolina, Oklahoma, Missouri and Michigan: further
                cuts that depend on revenue growth.
              </li>
              <li>Kentucky: each further cut needs both revenue tests and a new law.</li>
              <li>
                Colorado: temporary rate reductions that depend on each year’s refund surplus.
              </li>
            </ul>
          </Callout>
          <Callout kind="entry" title="Your own state brackets win">
            <p>
              A scheduled change with state brackets, or custom state brackets, replaces the
              built-in law for the years it covers, including these changes.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "california",
      title: "What California adds",
      body: (
        <>
          <p>California is the one state that CoastMath models beyond its brackets:</p>
          <ul>
            <li>
              The taxable part of Social Security is subtracted, since California doesn’t tax
              benefits.
            </li>
            <li>
              HSA contributions, both yours and your employer’s, are added back to California
              income, since California doesn’t recognize HSAs.
            </li>
            <li>
              Personal and senior exemption credits apply to the people you mark as eligible.
              Dependent credits apply for each year you enter a count. The credits phase out at high
              federal AGI.
            </li>
            <li>Head of household uses California’s own schedule and deduction.</li>
            <li>
              2026 uses the 2025 tables, as California directs for 2026 estimated tax. Later years
              are inflation projections.
            </li>
          </ul>
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "Health savings & work coverage"]} /> holds{" "}
              <strong>California personal exemption</strong> and{" "}
              <strong>California dependents</strong>. While eligibility is Unknown, no exemption
              credit is taken and a note appears.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "state-deduction-rules",
      title: "State deduction rules",
      body: (
        <>
          <p>
            Turn on <strong>Use state deduction rules where supported</strong> to replace the
            standard deduction estimate with the state’s own rules: the choice between its standard
            and itemized deductions, its personal and dependent exemptions after any income
            phase-out, and any deduction for federal income tax. The rules use the state’s own
            deduction categories, not your federal itemized total after the federal cap. States
            without supported rules keep the standard deduction estimate, and the results list a
            note saying so.
          </p>
          <p>
            Supported states are Alabama, Arizona, Arkansas, Connecticut, Delaware, the District of
            Columbia, Georgia, Hawaii, Illinois, Indiana, Kansas, Kentucky, Maine, Maryland,
            Massachusetts, Michigan, Minnesota, Mississippi, Missouri, Nebraska, New Jersey, New
            Mexico, New York, North Carolina, Oklahoma, Oregon, Rhode Island, Utah, Virginia, West
            Virginia and Wisconsin, using each state’s latest published forms or statute.
          </p>
          <p>
            Some states let you itemize only when you itemize on your federal return, and the
            District of Columbia, Georgia, New Mexico, Oklahoma and Virginia require the same choice
            as your federal return. Maine and Minnesota shrink the standard and itemized deductions
            as income rises, and Maine, Minnesota and New Mexico reduce their exemptions as income
            rises. Some states give a credit in place of an exemption, such as Utah’s taxpayer
            credit and the personal credits of Arkansas, Delaware, Kentucky and Nebraska; credits
            reduce the state tax but never below zero. Connecticut also adds its rate phase-out and
            recapture amounts and takes its personal tax credit, a share of that tax. Wisconsin’s
            itemized deduction is a credit against its tax, never a deduction. Kentucky allows one
            standard deduction on a joint return.
          </p>
          <p>
            A deduction for federal income tax uses the same year’s projected federal income tax
            after credits, excluding payroll tax and the net investment income tax. Your federal
            itemized deduction for state tax then uses the lower state tax, and CoastMath
            recalculates both until they agree to within a dollar. California’s exemption credits
            and Ohio’s exemptions keep their existing rules.
          </p>
          <p>
            Amounts the state indexes are projected with your inflation assumption after their
            published year. Changes already in law are applied in their year: Hawaii’s and
            Virginia’s later standard deductions, and Illinois’ exemption, which its law sets only
            through 2028.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Plan details", "Tax adjustments and scheduled changes"]} />. A
              scheduled change can turn the rules on or off from a later year.
            </p>
          </Callout>
          <Callout kind="boundary">
            <p>
              Dependents are counted from children’s birth years (under 19 at year end); rules tied
              to the federal child tax credit count children under 17. Students and other dependents
              aren’t identified. Blindness and disability amounts, part-year residence and the other
              state credits aren’t modeled. Custom state brackets keep the standard deduction
              estimate.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "social-security",
      title: "Social Security",
      body: (
        <>
          <p>
            Each state’s rule starts from the taxable part of your benefits on the federal return
            and subtracts some or all of it before state tax. Nothing is entered. Most income-tax
            states subtract all of it; eight states still tax benefits in 2026.
          </p>
          <DataTable
            caption="States that tax Social Security in 2026"
            columns={[
              { key: "state", label: "State" },
              { key: "rule", label: "Rule (2026)" },
            ]}
            rows={[
              {
                state: "Colorado",
                rule: "Subtracted in full from 65 (or from 55 below an income limit), otherwise within the pension exclusion. Part of the retirement-income rule below.",
              },
              {
                state: "Connecticut",
                rule: "Fully subtracted below $75,000 federal AGI ($100,000 joint or head of household). Above that, at most 25% of benefits stays taxable.",
              },
              {
                state: "Minnesota",
                rule: "Fully subtracted up to $110,780 AGI joint, $86,410 single or head of household, $55,390 separate; 10% less for each $4,000 above ($2,000 separate). A smaller alternate subtraction applies when it’s larger.",
              },
              { state: "Montana", rule: "Taxed as on the federal return." },
              {
                state: "New Mexico",
                rule: "Fully subtracted up to $100,000 federal AGI single, $150,000 joint or head of household, $75,000 separate; nothing above.",
              },
              {
                state: "Rhode Island",
                rule: "Subtracted for a person at full retirement age (67 in the model) when federal AGI is at most $107,000, or $133,750 joint.",
              },
              {
                state: "Utah",
                rule: "A credit at the state rate, reduced by 2.5 cents per dollar of income above $54,000 single, $90,000 joint or head of household, $45,000 separate. Modeled as the equivalent subtraction.",
              },
              {
                state: "Vermont",
                rule: "Fully subtracted up to $55,000 federal AGI ($70,000 joint), phasing out over the next $10,000.",
              },
            ]}
            note="West Virginia’s phase-in is complete for 2026, and Kansas, Missouri and Nebraska exempt benefits fully. Minnesota’s and Rhode Island’s thresholds grow with inflation; the others stay fixed."
          />
          <p>
            Maryland and Maine subtract all taxable benefits and still lower each person’s pension
            exclusion by their Social Security. Custom state brackets keep taxing benefits as
            federal AGI does, except in California.
          </p>
          <p>
            <UIPath steps={["Tax tools", "Annual tax breakdown"]} /> shows the amount as{" "}
            <strong>State Social Security subtraction</strong>, and the annual report’s Taxes view
            has a column for it.
          </p>
        </>
      ),
    },
    {
      id: "retirement-income",
      title: "Pension and retirement-income exclusions",
      body: (
        <>
          <p>
            In 23 states, part or all of each person’s pension and retirement-account income is
            subtracted before state tax. Nothing is entered: the rule follows the state, each
            person’s age at the end of the year and the income’s type. Pensions and annuities come
            from the income type you choose; IRA and workplace-plan amounts are that person’s
            taxable withdrawals, required distributions and SEPP payments.
          </p>
          <DataTable
            caption="Retirement-income exclusions by state"
            columns={[
              { key: "state", label: "State" },
              { key: "rule", label: "Rule (2026)" },
            ]}
            rows={[
              {
                state: "Illinois, Mississippi, Pennsylvania",
                rule: "Pensions and retirement-account withdrawals fully excluded. Mississippi and Pennsylvania require 59½ for account withdrawals; Illinois also excludes Roth conversions.",
              },
              {
                state: "Iowa",
                rule: "All retirement income, including Roth conversions, from age 55.",
              },
              {
                state: "Michigan",
                rule: "Up to $67,610, or $135,220 on a joint return. Account withdrawals from 59½; 457(b) plans don’t qualify.",
              },
              { state: "Georgia", rule: "$35,000 per person at 62–64, $65,000 from 65." },
              {
                state: "New York",
                rule: "$20,000 per person from 59½. Annuities bought with your own money don’t qualify.",
              },
              {
                state: "New Jersey",
                rule: "From 62: up to $75,000 single or $100,000 joint when income is $100,000 or less, then a share of the income up to $150,000.",
              },
              {
                state: "Colorado",
                rule: "$20,000 per person at 55–64, $24,000 from 65, less the person’s taxable Social Security, which is also subtracted.",
              },
              {
                state: "Kentucky, Oklahoma",
                rule: "$31,110 (Kentucky, Roth conversions included) or $10,000 per person, at any age.",
              },
              {
                state: "Connecticut",
                rule: "Pensions, annuities and IRAs fully excluded below $75,000 federal AGI ($100,000 joint), phasing out by $100,000 ($150,000).",
              },
              {
                state: "Maryland, Maine",
                rule: "$41,200 per person from 65 (Maryland, no IRAs) or $49,824 (Maine), less the person’s Social Security. Maine phases out above $125,000 AGI ($250,000 joint).",
              },
              {
                state: "Delaware",
                rule: "$12,500 per person from 60; $2,000 of pension under 60.",
              },
              {
                state: "Louisiana, Wisconsin, Rhode Island",
                rule: "$12,000 from 65; $24,000 from 67; $50,000 of pensions and workplace plans (not IRAs) from 67 below an income limit.",
              },
              {
                state: "Alabama, Arkansas, Missouri, South Carolina",
                rule: "Smaller exclusions: Alabama pensions in full plus $6,000 from 65; $6,000 in Arkansas and Missouri (Missouri phases out above $25,000 or $32,000 joint); South Carolina $3,000, $10,000 from 65, plus its age-65 deduction.",
              },
              {
                state: "Virginia",
                rule: "A $12,000 age deduction per person from 65 against any income, reduced dollar for dollar above $50,000 ($75,000 married) of AGI less Social Security.",
              },
            ]}
          />
          <p>
            The state for the year applies to all of that year’s income. After a move, the new
            state’s rule applies from the year it takes effect; see <HelpLink to="moving-states" />.
            Dollar limits that the state indexes grow with the plan’s inflation; the others stay
            fixed.
          </p>
          <Callout kind="boundary">
            <ul>
              <li>
                Government and military pension rules, which the income types can’t identify.
                Pensions are treated as private ones.
              </li>
              <li>
                Georgia’s and Delaware’s inclusion of interest, dividends, gains and rent in
                retirement income, and credits such as Ohio’s and Utah’s.
              </li>
              <li>Roth conversions, except in Illinois, Iowa and Kentucky.</li>
              <li>
                The year someone reaches 59½ counts from the next birthday; income from the start of
                the plan year to that date isn’t split out.
              </li>
            </ul>
          </Callout>
          <p>
            <UIPath steps={["Tax tools", "Annual tax breakdown"]} /> shows the amount as{" "}
            <strong>State retirement-income exclusion</strong>, and the annual report’s Taxes view
            has a column for it.
          </p>
        </>
      ),
    },
    {
      id: "taxed-contributions",
      title: "Contributions your state already taxed",
      body: (
        <>
          <p>
            Pennsylvania, New Jersey and Massachusetts tax some retirement contributions when
            they’re made (see above). CoastMath keeps that taxed amount for each account, together
            with the state that taxed it, and excludes it from that account’s withdrawals, required
            distributions and SEPP payments while you live in that state.
          </p>
          <DataTable
            caption="How taxed contributions come back"
            columns={[
              { key: "state", label: "State" },
              { key: "method", label: "Method" },
            ]}
            rows={[
              {
                state: "Pennsylvania, Massachusetts",
                method: "Withdrawals are tax free until the taxed contributions are used up.",
              },
              {
                state: "New Jersey",
                method:
                  "Each withdrawal is tax free in proportion to the taxed contributions left, divided by the account’s value plus the year’s withdrawals.",
              },
            ]}
          />
          <p>
            A withdrawal that the state’s retirement-income exclusion already covers isn’t excluded
            twice, though it still uses up the taxed contributions. Pennsylvania withdrawals from
            59½ are exempt anyway, so the recovery matters mostly for earlier withdrawals.
          </p>
          <Callout kind="entry" title="Contributions taxed before the plan starts">
            <p>
              Enter them on the traditional account as{" "}
              <strong>Contributions your state already taxed (optional)</strong>. They’re treated as
              taxed by the state you live in when the plan starts. Leave it blank if none.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              <UIPath
                steps={["Accounts", "Edit", "Contributions your state already taxed (optional)"]}
              />
              .
            </p>
          </Callout>
          <Callout kind="boundary">
            <ul>
              <li>Taxable Roth conversions don’t recover taxed contributions.</li>
              <li>
                New Jersey 403(b) and 457 payments use the IRA proportion instead of the pension
                rules’ three-year or general rule.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
    {
      id: "washington-capital-gains",
      title: "Washington capital gains tax",
      body: (
        <>
          <p>
            Washington residents owe a separate tax on long-term capital gains. CoastMath adds it to
            state tax. It applies to gains from selling taxable investments, including gains you
            choose to harvest. Gains on property sales are excluded, and retirement accounts don’t
            realize gains.
          </p>
          <KeyFigures
            caption="Washington capital gains tax"
            items={[
              {
                label: "Standard deduction",
                value: 278000,
                format: "usd",
                detail:
                  "One per person or per married couple; the latest published amount, grown with inflation after 2026",
              },
              {
                label: "Rate",
                value: 0.07,
                format: "pct",
                digits: 0,
                detail: "Gains above the deduction",
              },
              {
                label: "Additional rate",
                value: 0.029,
                format: "pct",
                digits: 1,
                detail: "Gains above $1,000,000 after the deduction",
              },
            ]}
          />
          <p>
            It’s counted toward your federal itemized deduction for state and local taxes with the
            rest of state tax. <UIPath steps={["Tax tools", "Annual tax breakdown"]} /> shows it as{" "}
            <strong>Washington capital gains tax</strong>.
          </p>
          <Callout kind="boundary">
            <p>
              The charitable deduction and the family-owned small business deduction aren’t modeled.
            </p>
          </Callout>
          <h3>Washington income tax from 2028</h3>
          <p>
            From 2028 Washington taxes income above a $1,000,000 standard deduction at 9.9%. The
            deduction is one per person or per married couple; CoastMath gives each spouse half on
            separate returns and grows it with inflation after 2028. The base is federal AGI with
            long-term gains limited to those the capital gains tax covers, so property sale gains
            stay out. The capital gains tax paid on gains the income tax also reaches is credited
            against it, up to the income tax on those gains.
          </p>
          <Callout kind="boundary">
            <p>
              The income tax’s charitable deduction, pass-through entity election and credits for
              tax paid to other states aren’t modeled.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "local-income-tax",
      title: "Local income tax",
      body: (
        <>
          <p>
            The catalog covers taxes that residents owe because of where they live, at 2026 rates.
            Each locality taxes one of the bases below. Rates set to change on a known schedule
            follow that schedule.
          </p>
          <DataTable
            caption="Localities in the catalog"
            columns={[
              { key: "state", label: "State" },
              { key: "places", label: "Localities" },
              { key: "base", label: "Taxed on" },
            ]}
            rows={[
              { state: "Indiana", places: "All 92 counties", base: "State taxable income" },
              {
                state: "Maryland",
                places: "All 23 counties and Baltimore City",
                base: "State taxable income",
              },
              {
                state: "New York",
                places: "New York City",
                base: "State taxable income, with the city school tax credits",
              },
              { state: "New York", places: "Yonkers", base: "A surcharge on state income tax" },
              {
                state: "Oregon",
                places:
                  "Portland; Multnomah County inside or outside Metro; Metro district in Clackamas or Washington County",
                base: "State taxable income above each tax’s threshold; Portland adds its flat arts tax",
              },
              {
                state: "Michigan",
                places: "24 cities, including Detroit and Grand Rapids",
                base: "Federal AGI less taxable Social Security, pensions, annuities and retirement-account withdrawals, after per-person exemptions",
              },
              {
                state: "Ohio",
                places: "10 cities, including Columbus, Cleveland and Cincinnati",
                base: "Earned income: wages including 401(k) deferrals, plus self-employment profit",
              },
              {
                state: "Pennsylvania",
                places: "Philadelphia and 11 other cities",
                base: "Earned income; Philadelphia also taxes dividends, investment income and nonemployer annuities",
              },
              {
                state: "Missouri",
                places: "Kansas City, St. Louis",
                base: "Wages after pre-tax deductions, plus self-employment profit",
              },
              {
                state: "Delaware",
                places: "Wilmington",
                base: "Gross wages, plus self-employment profit",
              },
            ]}
          />
          <p>
            For a locality outside the catalog, choose <strong>Custom rates</strong>. You can
            combine an <strong>Earned income rate</strong>, a{" "}
            <strong>State taxable income rate</strong> and a <strong>State tax surcharge</strong>.
            Any combination can be used, for example a city rate plus an Ohio school district rate.
            When you live in Indiana or Maryland, or in Pennsylvania with earned income, and haven’t
            chosen a locality, a note reminds you that local tax is missing.
          </p>
          <Callout kind="entry" title="Locality notes appear with the results">
            <p>
              Several localities list what they leave out, such as Ohio school district taxes or
              credits for tax paid to a work city. These notes appear under{" "}
              <UIPath steps={["Overview", "Model assumptions and limitations"]} />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "state-payroll-programs",
      title: "California SDI and Washington payroll premiums",
      body: (
        <>
          <p>
            Employee payroll programs are added only for the people and years you list as covered.
            They appear as named expenses, not as income tax. California SDI and Washington Paid
            Leave count toward your federal itemized state and local tax deduction. Washington Cares
            doesn’t.
          </p>
          <KeyFigures
            caption="2026 employee rates"
            items={[
              {
                label: "California SDI",
                value: 0.013,
                format: "pct",
                digits: 1,
                detail: "All wages",
              },
              {
                label: "Washington Paid Leave",
                value: 0.0113,
                format: "pct",
                digits: 2,
                detail: "Employees pay 71.43%, on wages up to $184,500",
              },
              {
                label: "Washington Cares",
                value: 0.0058,
                format: "pct",
                digits: 2,
                detail: "All wages",
              },
            ]}
          />
          <p>After 2026 the rates stay fixed, and the Paid Leave wage cap grows with inflation.</p>
          <Callout kind="where">
            <p>
              <UIPath
                steps={[
                  "Plan details",
                  "Health savings & work coverage",
                  "Add work coverage period",
                ]}
              />
              . Leave it empty if you don’t know. Covered wages are those in the selected work
              state.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "what-isnt-modeled",
      title: "What isn’t modeled",
      body: (
        <>
          <Callout kind="boundary">
            <ul>
              <li>
                Personal and dependent exemptions, state credits, state itemized deductions and
                income-based deduction phase-outs, except California’s exemption credits, Ohio’s
                exemptions, credits you enter and states with supported deduction rules.
              </li>
              <li>
                State capital gains preferences beyond the states whose brackets already include
                them, and the gains Maryland exempts from its 2% (such as a home sold for under $1.5
                million).
              </li>
              <li>
                Taxes owed because of where you work: nonresident city wage taxes, occupational and
                head taxes, and credits for tax paid to another state or city.
              </li>
              <li>Custom state brackets. The planner uses its built-in tables.</li>
            </ul>
          </Callout>
          <p>
            Local taxes on a state base inherit these gaps and the state’s subtractions. New York
            City tax, for instance, is figured on state taxable income without Social Security or
            the excluded $20,000 of pension.
          </p>
        </>
      ),
    },
    {
      id: "where-results-show",
      title: "Where the result shows up",
      body: (
        <>
          <p>
            <UIPath steps={["Tax tools", "Annual tax breakdown"]} /> lists{" "}
            <strong>State tax</strong> and <strong>Local tax</strong> for the year you pick. Both
            are in the year’s total tax and are settled with it; see{" "}
            <HelpLink to="tax-payments-and-settlement" />. The same year’s state and local tax is
            also counted toward your federal itemized deduction for state and local taxes, up to the
            cap. See <HelpLink to="itemized-deductions" />.
          </p>
          <Symptoms
            rows={[
              {
                symptom: "State tax on Social Security",
                check: "Your state and federal AGI",
                next: "Eight states tax benefits, most above an income limit; see the Social Security table.",
              },
              {
                symptom: "Pennsylvania tax on an early IRA withdrawal",
                check: "Contributions your state already taxed",
                next: "Enter contributions taxed before the plan starts; later ones are tracked automatically.",
              },
              {
                symptom: "State tax on a pension in a state with an exclusion",
                check: "Each person’s age and the income’s type",
                next: "Exclusions start at the state’s age and cover only the listed types; nonqualified annuities often don’t qualify.",
              },
              {
                symptom: "No county or city tax in Indiana, Maryland or Pennsylvania",
                check: "Local income tax for that residence",
                next: "Pick the locality, or enter custom rates.",
              },
              {
                symptom: "Local tax disappears after a move",
                check: "The residency change’s own locality",
                next: "Set a locality on that row; it doesn’t inherit the starting one.",
              },
              {
                symptom: "California tax higher than expected",
                check: "California personal exemption eligibility",
                next: "Mark who is eligible; Unknown takes no credit.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

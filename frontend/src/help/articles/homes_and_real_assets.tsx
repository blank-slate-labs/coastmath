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
  UIPath,
  V,
} from "../help_kit";
import { LineChart } from "../help_charts";

const years = [2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034, 2035];
const byRate = [10500, 10920, 11357, 11811, 12284, 12775, 13286, 13817, 14370, 14945];
const byAmount = [10500, 10815, 11139, 11474, 11818, 12172, 12538, 12914, 13301, 13700];

const article: Article = {
  intro: (
    <>
      <p>
        CoastMath carries each home, vehicle or other property at a value that grows at the fixed
        annual rate you enter. Every year you own it, CoastMath charges its property tax,
        maintenance and insurance as spending, whether or not a loan is attached. Its value counts
        toward net worth, but it never funds spending unless the property is sold. A property can be
        one you own today or one you plan to buy, and a rental property also earns rent and is
        depreciated for tax.
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
            Each property has a current value, an annual appreciation rate, its carrying costs, and
            optional sale settings. The sale settings are explained in{" "}
            <HelpLink to="selling-a-home" />.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Property and debt", "Add property or vehicle"]} />. To edit an
              existing property, use its <strong>Edit</strong> button in the same list.
            </p>
          </Callout>
          <Callout kind="entry">
            <p>
              <strong>Annual property tax ($)</strong> and <strong>Annual maintenance ($)</strong>{" "}
              are in today’s dollars, and CoastMath raises them with inflation each year.{" "}
              <strong>Property tax (% of value)</strong> and{" "}
              <strong>Maintenance (% of value)</strong> are charged on the property’s value instead.
              If you fill in a rate, it replaces the matching dollar amount.{" "}
              <strong>Insurance (% of value)</strong> is entered only as a rate, and it is added on
              top of the other two costs.
            </p>
          </Callout>
          <Callout kind="entry">
            <p>
              The appreciation rate is a nominal annual rate. Enter a negative rate for something
              that loses value, such as −15% for a car. <strong>Current value ($)</strong> must be
              greater than zero.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "planned-purchase",
      title: "Buying a property later",
      body: (
        <>
          <p>
            Turn on <strong>Planned purchase</strong> to buy the property at the start of a future
            month. Until then it has no value, costs, rent or loan. At the purchase, CoastMath pays
            the down payment and closing costs, or the full price and closing costs when there’s no
            loan, and starts a loan for the rest.
          </p>
          <Callout kind="entry">
            <p>
              <strong>Purchase price in today’s dollars ($)</strong> grows at the property’s
              appreciation rate until the purchase month. A $400,000 price with 4% appreciation
              costs $432,640 two years later. A dollar down payment and{" "}
              <strong>Closing costs ($)</strong> grow in step with the price. Closing costs are
              added to the tax basis.
            </p>
          </Callout>
          <ul>
            <li>
              <strong>Loan rate (%, blank for no loan)</strong> and{" "}
              <strong>Loan term (months)</strong> create a fixed-payment loan linked to the
              property. Its payments start in the purchase month, and a sale pays it off like any
              linked loan (see <HelpLink to="mortgages-and-loans" />
              ).
            </li>
            <li>
              <strong>Pay from</strong> chooses the account that pays the cash due. If that account
              runs short, the rest is unfunded spending rather than a withdrawal from another
              account. With <strong>Withdrawal order</strong>, the cash due is paid like any other
              expense: from the year’s income first, then from your withdrawal order.
            </li>
          </ul>
          <p>
            In the cash-flow view the payment appears as “<em>name</em> purchase”. A purchase date
            before the plan starts means you already own the property, and no purchase is modeled.
          </p>
        </>
      ),
    },
    {
      id: "appreciation",
      title: "How value grows",
      body: (
        <>
          <Formula result="Value at year end">
            <V>Value at year start</V>
            <Op>×</Op>
            <V>(1 + appreciation rate)</V>
          </Formula>
          <p>
            Growth compounds once a year. If a year is only partly owned (a plan that starts partway
            through the year, or a sale year), the rate is compounded over that fraction of the
            year. For example, half a year at 4% grows the value by about 1.98%. The rate never
            changes: every Success odds trial and every historical stress test uses the rate you
            entered, not market returns.
          </p>
        </>
      ),
    },
    {
      id: "carrying-costs",
      title: "How carrying costs are charged",
      body: (
        <>
          <Formula
            result="Carrying cost for the year"
            note="A rate uses the value at the start of the year, before that year’s appreciation. A dollar amount is your entry grown by inflation since the plan started."
          >
            <V>Property tax</V>
            <Op>+</Op>
            <V>Maintenance</V>
            <Op>+</Op>
            <V>Insurance</V>
          </Formula>
          <Ledger
            title="Example: $500,000 home appreciating 4% a year, costs entered as rates"
            rows={[
              { label: "Value at the start of the first year", value: 500000 },
              {
                op: "×",
                label: "Property tax 1.1% + maintenance 1% + insurance 0.4%",
                value: 0.025,
                format: "pct",
              },
              { op: "=", label: "First-year carrying cost", value: 12500 },
              {
                label: "Value at the start of the second year",
                value: 520000,
                detail: "$500,000 × 1.04",
              },
              { op: "×", label: "Same rates", value: 0.025, format: "pct" },
              { op: "=", label: "Second-year carrying cost", value: 13000 },
            ]}
          />
          <p>
            Choose rates or dollar amounts according to how you expect the cost to grow. A rate
            follows the property’s value, and a dollar amount follows inflation. With appreciation
            above inflation, rate-based costs pull ahead over time.
          </p>
          <Figure
            title="Annual property tax and maintenance on a $500,000 home: rates vs dollar amounts"
            caption="Both start at $10,500: rates of 1.1% and 1%, or amounts of $5,500 and $5,000. The home appreciates 4% a year and inflation is 3%. No insurance is included."
            table={{
              columns: [
                { key: "year", label: "Year" },
                { key: "rate", label: "Entered as rates", format: "usd" },
                { key: "amount", label: "Entered as dollar amounts", format: "usd" },
              ],
              rows: years.map((year, i) => ({ year, rate: byRate[i], amount: byAmount[i] })),
            }}
          >
            <LineChart
              label="Carrying costs by year: rate-based costs grow 4% a year with value, dollar amounts grow 3% a year with inflation"
              step
              series={[
                {
                  id: "rate",
                  label: "Entered as rates",
                  color: "magenta",
                  points: years.map((year, i) => [year, byRate[i]]),
                },
                {
                  id: "amount",
                  label: "Entered as dollar amounts",
                  color: "gray",
                  points: years.map((year, i) => [year, byAmount[i]]),
                },
              ]}
            />
          </Figure>
          <p>
            Carrying costs are charged every year the property is owned, including years before and
            after a loan is paid off. In a sale year, they’re charged only through the month before
            the sale. They’re essential spending, paid from that year’s income first and then from
            withdrawals in your withdrawal order. In the cash-flow view, each property has one line:
            “<em>name</em> (property tax & upkeep)”.
          </p>
          <p>
            The property tax you enter counts toward the state and local tax deduction if you
            itemize (see <HelpLink to="itemized-deductions" />
            ). Maintenance and insurance aren’t deductible. On a rental property, all three are
            rental expenses instead (see below).
          </p>
        </>
      ),
    },
    {
      id: "rental-property",
      title: "Rental property",
      body: (
        <>
          <p>
            Set <strong>Sale tax treatment</strong> to <strong>Rental property</strong> to enter
            rent and depreciation. Rent after vacancy is income each year the property is owned, and
            it reaches your accounts as cash. The amount taxed is the net rental income: rent minus
            operating expenses, the property’s tax, upkeep and insurance, interest on loans linked
            to it, and depreciation. It is ordinary income and investment income for the net
            investment income tax, but not self-employment income.
          </p>
          <Callout kind="entry">
            <p>
              <strong>Annual rent ($, today’s dollars)</strong> grows with inflation unless you
              enter <strong>Rent growth (%/yr, blank for inflation)</strong>.{" "}
              <strong>Operating expenses</strong> can be dollars a year, which grow with inflation,
              or a percent of collected rent. Don’t enter the property tax, upkeep or insurance here
              as well.
            </p>
          </Callout>
          <Ledger
            title="Example: a duplex owned at the plan start, first year"
            rows={[
              { label: "Annual rent", value: 36000 },
              { op: "−", label: "Vacancy at 5%", value: 1800 },
              { op: "=", label: "Rent collected", value: 34200 },
              { op: "−", label: "Operating expenses at 10% of rent collected", value: 3420 },
              { op: "−", label: "Property tax", value: 4000 },
              {
                op: "−",
                label: "Depreciation",
                value: 8182,
                detail: "$300,000 basis × 75% building ÷ 27.5 years",
              },
              { op: "=", label: "Net rental income taxed", value: 18598 },
            ]}
          />
          <h3>Depreciation</h3>
          <p>
            The building is depreciated in equal amounts over 27.5 years for residential property or
            39 years for nonresidential property. Land isn’t depreciated, so enter either{" "}
            <strong>Land value (% of cost)</strong> or <strong>Building basis ($)</strong>. Without
            either one, depreciation is left out and the projection shows a warning. In the year you
            buy, depreciation starts in the middle of the purchase month; in the year you sell, it
            stops in the middle of the sale month. For a property you already own, enter{" "}
            <strong>Depreciation already taken ($)</strong>: the schedule stops when the total
            reaches the building basis, and the adjusted tax basis you enter should already be
            reduced by it.
          </p>
          <h3>Rental losses</h3>
          <p>
            A net rental loss is a passive loss. With <strong>I actively participate</strong>{" "}
            checked, up to $25,000 of it a year offsets other income. That allowance shrinks by half
            of your income above $100,000, measured before rental income or losses and Social
            Security. Losses above the allowance carry forward. They offset later rental income, and
            all of a property’s carried losses become deductible in the year it is sold.
          </p>
          <KeyFigures
            caption="Rental loss allowance (not adjusted for inflation)"
            items={[
              { label: "Maximum allowance", value: 25000 },
              { label: "Phase-out starts", value: 100000 },
              { label: "Fully phased out", value: 150000 },
              {
                label: "Married filing separately, lived apart all year",
                value: 12500,
                detail: "Phase-out from $50,000; no allowance if you lived together",
              },
            ]}
          />
          <Ledger
            title="Example: rental loss with $120,000 of wages, married filing jointly"
            rows={[
              { label: "Rent collected", value: 10000 },
              { op: "−", label: "Expenses and property tax", value: 23000 },
              { op: "−", label: "Depreciation", value: 8727 },
              { op: "=", label: "Net rental loss", value: -21727 },
              { label: "Allowance: $25,000 − 50% × ($120,000 − $100,000)", value: 15000 },
              { op: "→", label: "Loss deducted this year", value: 15000 },
              { op: "→", label: "Loss carried forward", value: 6727 },
            ]}
          />
          <Callout kind="entry">
            <p>
              Losses carried forward from before the plan go in{" "}
              <strong>Suspended passive losses carried in ($)</strong>. Check{" "}
              <strong>Operated as a trade or business (qualified business income)</strong> only if
              the rental qualifies for the qualified business income deduction; its net rental
              income is then added to that deduction’s base.
            </p>
          </Callout>
          <Callout kind="where">
            <p>
              The tax view lists the year’s rental income in AGI, depreciation and losses carried
              forward. The cash-flow view shows rent as income and operating expenses as “
              <em>name</em> (rental expenses)”.
            </p>
          </Callout>
          <h3>Part rental, part personal use</h3>
          <p>
            A property can be partly rented and partly yours, such as a duplex you live in half of.
            Enter <strong>Rented share of the property (%)</strong>; blank means fully rented. For
            your main home, check <strong>Part of the home is rented out</strong> under{" "}
            <strong>Primary residence</strong> to show the rental fields. Each year, CoastMath
            treats the rented share as a rental: that share of the rent, operating expenses,
            property tax, upkeep, insurance, loan interest and depreciation goes into net rental
            income, and the passive loss rules apply to it. Your share of the property tax stays an
            itemized deduction, and so does your share of mortgage interest on a main home. The
            property still pays all of its costs in cash.
          </p>
          <Callout kind="entry">
            <p>
              Enter <strong>Annual rent</strong> and dollar <strong>Operating expenses</strong> as
              if the whole property were rented; CoastMath scales them by the rented share. To
              change the share over time, such as renting the whole home after you move out, add a
              year under <strong>Rented share by year (optional)</strong>. Each change applies from
              its year until the next one.
            </p>
          </Callout>
          <Ledger
            title="Example: a $400,000 duplex, half rented, first year"
            rows={[
              { label: "Rent if fully rented", value: 40000 },
              { op: "×", label: "Rented share", value: 0.5, format: "pct" },
              { op: "=", label: "Rent collected", value: 20000 },
              { op: "−", label: "Half of $4,000 operating expenses", value: 2000 },
              { op: "−", label: "Half of $8,000 property tax", value: 4000 },
              {
                op: "−",
                label: "Half of the depreciation",
                value: 5455,
                detail: "$400,000 × 75% building ÷ 27.5 years × 50%",
              },
              { op: "=", label: "Net rental income taxed", value: 8545 },
              { op: "→", label: "Property tax left for itemizing", value: 4000 },
            ]}
          />
          <p>
            When the property is sold, the gain up to the depreciation taken is always taxed, even
            on a main home. The rest of the gain is split by the average rented share over the years
            you owned it. On a main home, the home-sale exclusion covers your share when you pass
            the ownership and use test, and years before 2009 count as your own use. The rented
            share’s gain is taxed. A loss is deductible only for the rented share.
          </p>
          <Ledger
            title="Example: a main home owned since 2016, a quarter rented, sold in 2026"
            rows={[
              {
                label: "Gain on the sale",
                value: 250000,
                detail: "$700,000 sale price − $450,000 adjusted basis",
              },
              { op: "−", label: "Depreciation taken, always taxed", value: 30000 },
              { op: "=", label: "Gain to split", value: 220000 },
              { op: "×", label: "Your share (not rented)", value: 0.75, format: "pct" },
              { op: "=", label: "Gain excluded", value: 165000 },
              { op: "→", label: "Gain taxed, including the $30,000", value: 85000 },
            ]}
          />
        </>
      ),
    },
    {
      id: "net-worth",
      title: "How property counts in net worth",
      body: (
        <>
          <p>
            Net worth includes each property at its projected value. Any loan against it is
            subtracted as a separate debt (see <HelpLink to="mortgages-and-loans" />
            ). Property value isn’t available for spending: shortfalls are covered only from
            accounts. The one exception is a property set to be sold automatically when accounts run
            out. <HelpLink to="overview-and-net-worth" /> shows where property appears in the
            results.
          </p>
          <p>
            Measures of liquid wealth leave property out. These include{" "}
            <HelpLink to="financial-independence-estimate" /> and any financial independence
            milestone set to “Liquid accounts minus debt”. Only a milestone set to “Total net worth
            incl. property” counts it.
          </p>
        </>
      ),
    },
    {
      id: "tax-treatment",
      title: "Tax treatment when a property is sold",
      body: (
        <>
          <p>
            Appreciation isn’t taxed while you hold a property. Tax applies only in the year of a
            sale, according to how the property is classified:
          </p>
          <DataTable
            caption="Sale tax treatment by classification"
            columns={[
              { key: "kind", label: "Classification" },
              { key: "gain", label: "Gain" },
              { key: "loss", label: "Loss" },
            ]}
            rows={[
              {
                kind: "Primary residence",
                gain: "Taxed as a long-term capital gain after the home-sale exclusion",
                loss: "Not deductible",
              },
              {
                kind: "Personal use (home, vehicle or other property)",
                gain: "Taxed as a long-term capital gain",
                loss: "Not deductible",
              },
              {
                kind: "Investment capital asset",
                gain: "Taxed as a long-term capital gain",
                loss: "Deductible under the capital-loss rules",
              },
              {
                kind: "Rental property",
                gain: "Gain up to the depreciation taken taxed at no more than 25%; the rest as a long-term capital gain",
                loss: "Deductible against ordinary income",
              },
              {
                kind: "Needs review",
                gain: "Taxed as a long-term capital gain",
                loss: "Not deductible until you choose a classification",
              },
            ]}
            note="A property marked Primary residence is treated as personal use unless part of it is rented out."
          />
          <p>
            A property that is still classified as <strong>Needs review</strong> and has a sale year
            or automatic sale set adds a warning to the projection. <HelpLink to="selling-a-home" />{" "}
            covers how the gain is measured and when the exclusion applies.{" "}
            <HelpLink to="capital-gains-and-dividends" /> covers the rates.
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
                <strong>Rental details.</strong> Short-term rental rules, real estate professional
                status, cost segregation, like-kind exchanges and passive income from other
                activities aren’t modeled.
              </li>
              <li>
                <strong>Mixed use.</strong> The rented share is always a separate rental activity.
                The limit that caps rental deductions at rental income for a home you also use, such
                as a vacation home, isn’t applied. When you move out of a home and rent it all, the
                years after you move out still count as rented years in the sale split, and the
                reduced exclusions for a move caused by work, health or unforeseen events aren’t
                modeled.
              </li>
              <li>
                <strong>Improvements and other costs.</strong> Renovations, HOA dues and
                fixed-dollar insurance aren’t property fields. Enter them as expenses. To reduce the
                taxable gain, add capital improvements to the adjusted tax basis.
              </li>
              <li>
                <strong>Variable appreciation.</strong> There are no housing-market scenarios. A
                property appreciates at its one fixed rate in every projection.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
  ],
};
export default article;

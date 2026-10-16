import type { Article } from "../help_types";
import { Callout, HelpLink, Steps, UIPath } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        An international plan is for people who live outside the US. Choose{" "}
        <strong>Other (custom rules)</strong> as the tax country and describe that country’s tax for
        residents; it replaces US tax in every year you live there. A plan can also move between the
        US and another country. Each year is then taxed entirely under one country’s rules.
      </p>
      <p>
        Each plan uses one currency. You enter every amount in it, and CoastMath shows results in
        it. Nothing is converted between currencies.
      </p>
    </>
  ),
  sections: [
    {
      id: "set-the-country",
      title: "Set the tax country and currency",
      body: (
        <>
          <Steps>
            <li>
              In <UIPath steps={["Plan details"]} />, choose <strong>Tax country</strong>:{" "}
              <strong>United States</strong> or <strong>Other (custom rules)</strong>. This is where
              you live at the plan’s start.
            </li>
            <li>
              Review the confirmation. It lists the settings that stop applying, then choose{" "}
              <strong>Switch to</strong> the new country. You can also switch the currency in the
              same step.
            </li>
            <li>
              Check <strong>Currency</strong>. Changing it only changes how amounts are shown.
            </li>
          </Steps>
          <p>
            When you leave the US, these settings stop applying in the years you live abroad:
            federal, state and local income tax; payroll tax and Social Security benefit taxation;
            Marketplace coverage, Medicare and IRMAA; US tax targets, Roth conversions and 72(t)
            payments; and US estate tax and estimated payments. They stay saved and apply again in
            any US year.
          </p>
          <Callout kind="where">
            <p>
              When no year of the plan is a US year, the planner hides these settings. When the plan
              moves between the US and another country, they stay visible with a note that they
              apply only in US years. The plan’s starting state appears only for plans that start in
              the US.
            </p>
            <p>
              The same applies to the US estate exemptions in <strong>Partner and estate</strong>{" "}
              and to Roth conversion and gain-harvesting rules in{" "}
              <UIPath steps={["Income allocation"]} />. A plan with no US year can’t save a rule
              that fills a federal bracket; remove it or add a US residency period.
            </p>
          </Callout>
          <Callout kind="boundary">
            <p>
              A plan saved with a country that is no longer offered doesn’t run until you switch it
              to United States or Other (custom rules).
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "custom-rules",
      title: "Custom tax rules",
      body: (
        <>
          <p>
            With <strong>Other (custom rules)</strong>, <strong>Custom tax rules</strong> in{" "}
            <UIPath steps={["Plan details"]} /> defines the country’s tax:
          </p>
          <ul>
            <li>whether each person is taxed separately or the couple together</li>
            <li>
              a tax-free allowance and national income tax brackets, which grow with plan inflation
              unless you turn indexing off
            </li>
            <li>
              how capital gains are taxed: as income with a share included, at a flat rate, or not
              at all
            </li>
            <li>
              whether dividends and interest are ordinary income, taxed like gains (dividends only)
              or at a flat rate
            </li>
            <li>
              an optional yearly wealth tax on net worth, with or without property, per person or
              per household
            </li>
            <li>an optional transaction tax on purchases, sales or both in taxable accounts</li>
          </ul>
          <p>
            Choose <strong>Save tax rules</strong> to save them. If the server rejects a rule, its
            message appears above the button and your entries stay in the form.
          </p>
          <Callout kind="boundary">
            <p>CoastMath evaluates custom rules exactly as entered and doesn’t check them.</p>
          </Callout>
        </>
      ),
    },
    {
      id: "which-country-applies",
      title: "Which country taxes each year",
      body: (
        <>
          <p>
            To model a move, add a row under <strong>Residency timeline</strong> in{" "}
            <UIPath steps={["Plan details"]} /> and choose its <strong>Country</strong>. A US row
            keeps its state and locality. <strong>Same as plan</strong> uses the plan’s own tax
            country. See <HelpLink to="moving-states" /> for how start and end milestones and years
            work.
          </p>
          <p>
            Each year is assessed entirely under the rules of the country where you live for most of
            the year. When two countries have the same number of months, the later residence wins.
          </p>
          <Callout kind="boundary">
            <p>
              Split-year treatment isn’t modeled. Income earned before a mid-year move is taxed by
              the country that applies to the whole year. Departure and exit taxes aren’t modeled.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "currency",
      title: "Currency",
      body: (
        <>
          <p>
            The plan’s currency sets the symbol and number format in charts, the ledger, reports and
            exports. It doesn’t change any calculation. Enter balances, income, expenses and tax
            amounts in that currency.
          </p>
          <Callout kind="entry" title="Use one currency for everything">
            <p>
              CoastMath doesn’t convert between currencies or model exchange rates. Convert any
              amount held in another currency yourself, at the rate you want to assume.
            </p>
          </Callout>
          <p>
            In a plan in any other currency than US dollars, the chart and report labels say{" "}
            <strong>Today’s money</strong> and <strong>Future (nominal)</strong> where a US-dollar
            plan says today’s and future dollars.
          </p>
        </>
      ),
    },
    {
      id: "accounts-and-income",
      title: "Accounts and income",
      body: (
        <>
          <p>
            Plans abroad use checking, savings, taxable brokerage and other accounts. When no year
            of the plan is a US year, US retirement accounts, HSAs and 529 plans are hidden. An
            account already saved with one of those types keeps it.
          </p>
          <Callout kind="entry">
            <p>
              Other countries’ state pensions are ordinary income streams. Add them as{" "}
              <strong>Other</strong> income in <UIPath steps={["Income streams"]} />. US Social
              Security you receive while living abroad stays a <strong>US Social Security</strong>{" "}
              income stream, taxed by your country of residence.
            </p>
          </Callout>
          <Callout kind="boundary">
            <p>
              A US retirement account held while you live abroad keeps its US distribution rules,
              such as required minimum distributions and the early-withdrawal penalty. The country
              you live in taxes its withdrawals as income. US withholding on payments to
              nonresidents isn’t modeled.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "approximations",
      title: "Approximations and what isn’t modeled",
      body: (
        <>
          <p>These simplifications apply in every year taxed by another country:</p>
          <ul>
            <li>
              <strong>Shared investment income</strong> (interest, dividends, realized gains, rent
              and cancelled debt from household assets) is split between partners by their cash and
              taxable balances at the start of the year. Joint balances count half to each partner.
            </li>
            <li>
              <strong>US pre-tax payroll deductions don’t reduce income abroad.</strong>
            </li>
            <li>
              <strong>Year-to-date entries and US carryovers are ignored.</strong> Year-to-date
              income, withholding and opening US tax payments don’t apply. US capital loss
              carryforwards and passive-loss rules don’t apply, and a net capital loss isn’t carried
              to a later year.
            </li>
            <li>
              <strong>Wealth tax uses balances at the start of the year.</strong>
            </li>
            <li>
              <strong>No US health costs.</strong> Marketplace premiums, Medicare and IRMAA aren’t
              charged in a country year. Enter health costs abroad as expenses.
            </li>
            <li>
              <strong>Transfers are trades.</strong> A transfer rule counts as a sale from its
              source and a purchase in its destination. If your rules tax trades in taxable
              accounts, both sides are taxed.
            </li>
            <li>
              <strong>Market history is from the US.</strong> Historical stress tests and historical
              Monte Carlo methods use US returns and inflation in every plan.
            </li>
          </ul>
          <Callout kind="boundary">
            <p>
              International plans model residents only. US taxation of citizens abroad, foreign
              earned income and foreign tax credits, tax treaties, currency exchange and departure
              taxes aren’t modeled.
            </p>
          </Callout>
        </>
      ),
    },
  ],
};

export default article;

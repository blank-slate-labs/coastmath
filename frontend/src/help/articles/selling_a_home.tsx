import type { Article } from "../help_types";
import {
  Callout,
  Formula,
  HelpLink,
  KeyFigures,
  Ledger,
  Op,
  Steps,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        A property sells at the start of the month you choose, at its projected value on that date.
        CoastMath subtracts your selling costs, pays off any loan linked to the property, deposits
        the remainder into the account you pick, and taxes the gain in the same year. For a primary
        residence that passes the ownership and use test, the gain is taxed only above the $250,000
        or $500,000 home-sale exclusion. A property can also be sold automatically when your
        accounts can no longer cover spending.
      </p>
    </>
  ),
  sections: [
    {
      id: "sale-timing",
      title: "When the sale happens",
      body: (
        <>
          <Callout kind="where">
            <p>
              <UIPath steps={["Property and debt", "Edit"]} />, then fill in{" "}
              <strong>Planned sale year (optional)</strong>, <strong>Sale month</strong> and{" "}
              <strong>Liquidation target account</strong>. The target account can be a checking,
              savings or taxable brokerage account.
            </p>
          </Callout>
          <p>
            The sale takes place at the start of the sale month. Everything tied to the property
            runs until then and stops at the sale:
          </p>
          <ul>
            <li>
              <strong>Appreciation</strong> compounds for the months owned. A June sale grows the
              value for five months of the sale year.
            </li>
            <li>
              <strong>Carrying costs</strong> (property tax, maintenance and insurance) are charged
              for the months owned.
            </li>
            <li>
              <strong>Payments on a linked loan</strong> are made for the months before the sale.
            </li>
          </ul>
          <p>In later years the property is gone, and so are its costs.</p>
        </>
      ),
    },
    {
      id: "proceeds",
      title: "Where the money goes",
      body: (
        <>
          <Formula result="Deposited proceeds">
            <V>Sale price</V>
            <Op>−</Op>
            <V>Selling costs</V>
            <Op>−</Op>
            <V>Remaining balance of loans linked to the property</V>
          </Formula>
          <p>
            The sale price is the property’s full projected value.{" "}
            <strong>Selling costs (% of sale price)</strong> covers commissions and other costs of
            selling; it reduces both the cash you receive and the taxable gain. Loans with this
            property as their <strong>Linked real asset</strong> are paid off first, and the rest
            goes to the target account. If the price is less than a linked loan’s balance, the whole
            price goes to that loan. The unpaid balance stays as debt, and the loan’s regular
            payments pay it off starting the next year. Loans that aren’t linked to the property are
            unaffected by the sale.
          </p>
          <p>
            Apart from selling costs, the sale itself doesn’t change net worth: the property’s value
            becomes cash, and the loan disappears. Net worth falls by the selling costs and the tax
            on the gain.
          </p>
        </>
      ),
    },
    {
      id: "tax-on-the-sale",
      title: "How the sale is taxed",
      body: (
        <>
          <Formula
            result="Gain"
            note="For a primary residence, the exclusion is subtracted and the result can’t go below zero. For a rental, depreciation taken during the plan also reduces the basis."
          >
            <V>Sale price</V>
            <Op>−</Op>
            <V>Selling costs</V>
            <Op>−</Op>
            <V>Adjusted tax basis</V>
          </Formula>
          <KeyFigures
            caption="Home-sale exclusion for a property marked Primary residence"
            items={[
              { label: "Married filing jointly in the sale year", value: 500000 },
              { label: "Any other filing status", value: 250000 },
            ]}
          />
          <Ledger
            title="Example: primary residence sold in July, married filing jointly, no selling costs"
            rows={[
              { label: "Value when the plan starts", value: 900000 },
              {
                op: "→",
                label: "Sale price, three and a half years later at 3% a year",
                value: 998097,
                detail: "$900,000 × 1.03 compounded over 3.5 years",
              },
              {
                op: "−",
                label: "Adjusted tax basis",
                value: 350000,
                detail: "Purchase price plus capital improvements",
              },
              { op: "=", label: "Gain", value: 648097 },
              { op: "−", label: "Home-sale exclusion", value: 500000 },
              { op: "=", label: "Taxable long-term capital gain", value: 148097 },
              {
                label: "Linked mortgage balance at the sale",
                value: 232011,
                detail: "$250,000 at 5.5% over 25 years; payments made through June",
              },
              {
                op: "=",
                label: "Deposited to the target account",
                value: 766086,
                detail: "$998,097 − $232,011",
              },
            ]}
            note="A single filer selling the same home would have a taxable gain of $398,097."
          />
          <h3>Ownership and use test</h3>
          <p>
            The exclusion applies only if you owned the home and lived in it as your main home for
            at least two of the five years before the sale. Enter{" "}
            <strong>Owned since (year)</strong> and month and, if you moved in later,{" "}
            <strong>Main home since (year)</strong> and month; CoastMath assumes you kept owning and
            living in it until the sale. A home bought with a planned purchase uses its purchase
            date. If the test isn’t met, the whole gain is taxed and the projection says so. With no
            dates, CoastMath assumes the test is met and shows a warning.
          </p>
          <h3>Rental property</h3>
          <p>
            A rental doesn’t get the exclusion, except for the personal share of a main home that is
            partly rented (see <HelpLink to="homes-and-real-assets#rental-property" />
            ). The part of its gain equal to the depreciation taken, before and during the plan, is
            taxed at your ordinary rate but no more than 25%. The rest is a long-term capital gain.
            A loss on a rental is deductible against ordinary income, and any rental losses carried
            forward on that property are deducted in the sale year (see{" "}
            <HelpLink to="homes-and-real-assets#rental-property" />
            ).
          </p>
          <Ledger
            title="Example: rental duplex sold in January after five years"
            rows={[
              { label: "Sale price", value: 400000 },
              { op: "−", label: "Selling costs at 6%", value: 24000 },
              {
                op: "−",
                label: "Adjusted tax basis after depreciation",
                value: 258750,
                detail: "$300,000 − $41,250 of depreciation",
              },
              { op: "=", label: "Gain", value: 117250 },
              { op: "→", label: "Taxed at no more than 25% (depreciation taken)", value: 41250 },
              { op: "→", label: "Taxed as a long-term capital gain", value: 76000 },
            ]}
          />
          <p>
            The taxable gain is taxed as a long-term capital gain. It is added to that year’s
            adjusted gross income and taxed with the rest of that year’s income. For rates and the
            effect on other income, see <HelpLink to="capital-gains-and-dividends" />. For
            properties that aren’t a primary residence, see{" "}
            <HelpLink to="homes-and-real-assets#tax-treatment" />: personal-use gains are taxed, and
            personal-use losses aren’t deductible.
          </p>
          <Callout kind="entry">
            <p>
              If you leave <strong>Adjusted tax basis ($)</strong> blank, CoastMath uses the
              property’s value when the plan starts, so only appreciation during the plan is taxed.
              For a home you’ve owned for years, this understates the gain. The projection shows a
              warning until you enter a basis.
            </p>
          </Callout>
          <Callout kind="boundary">
            <p>
              CoastMath assumes that you haven’t excluded a gain on another home in the previous two
              years. These aren’t modeled:
            </p>
            <ul>
              <li>
                Partial exclusions for a move caused by work, health or other unforeseen
                circumstances
              </li>
              <li>
                Periods of nonqualified use for a home with no rented share. For a partly rented
                home, the exclusion covers only your share of the gain, based on the average rented
                share since 2009.
              </li>
              <li>
                Surviving-spouse rule: an unmarried surviving spouse can keep the $500,000 exclusion
                for a sale within two years of the spouse’s death. CoastMath uses the filing status
                of the sale year.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
    {
      id: "automatic-sale",
      title: "Automatic sales when accounts run out",
      body: (
        <>
          <p>
            With <strong>Auto-liquidate on depletion</strong> turned on, a property is sold in any
            year where the accounts in your withdrawal order can’t cover a shortfall. If more than
            one property qualifies, CoastMath sells properties that aren’t your primary residence
            first, then the primary residence, in the order they’re listed. It sells one whole
            property at a time and stops once the shortfall is covered.
          </p>
          <p>
            An automatic sale uses the property’s value after that year’s full appreciation. The
            year’s carrying costs and loan payments have already been charged by then. Linked loans
            are paid off and the gain is taxed as in a planned sale. The remaining proceeds go to
            the target account, which covers the shortfall first and keeps whatever is left. If a
            sale covers the shortfall, that year doesn’t count as a failure.
          </p>
          <p>
            For how shortfalls reach this point, see <HelpLink to="withdrawal-order" />.
          </p>
        </>
      ),
    },
    {
      id: "moving",
      title: "Model a move",
      body: (
        <>
          <p>
            CoastMath has no single move event. You build a move from a sale, a milestone and
            expenses. Start with a date milestone for the move, set to the month of the sale (see{" "}
            <HelpLink to="milestones" />
            ).
          </p>
          <h3>Sell and rent</h3>
          <Steps>
            <li>Set the home’s sale year and month to the move date.</li>
            <li>
              Add rent as an expense with the move milestone as its <strong>Start Milestone</strong>
              .
            </li>
            <li>
              If you entered costs of the old home as separate expenses (for example, HOA dues or
              utilities), set their <strong>End Milestone</strong> to the move. Don’t end the
              property’s own carrying costs or the linked mortgage: both stop automatically at the
              sale.
            </li>
          </Steps>
          <h3>Sell and buy</h3>
          <Steps>
            <li>Set the old home’s sale as above.</li>
            <li>
              Add the new home as a property with <strong>Planned purchase</strong> on, in the same
              month. Enter its price, closing costs and loan (see{" "}
              <HelpLink to="homes-and-real-assets#planned-purchase" />
              ), and its carrying costs.
            </li>
            <li>
              Mark the new home as Primary residence too, so its own later sale can use the
              exclusion. The old home keeps its flag for its sale.
            </li>
          </Steps>
          <h3>Keep the old home and rent it out</h3>
          <p>
            A property is either a primary residence or a rental for the whole plan, so converting a
            home to a rental isn’t modeled. To approximate it, leave the sale year blank and add the
            rent as an income stream starting at the move milestone. If you move to another state,
            also see <HelpLink to="moving-states" />.
          </p>
        </>
      ),
    },
    {
      id: "common-surprises",
      title: "Common surprises",
      body: (
        <>
          <Symptoms
            rows={[
              {
                symptom: "Net worth doesn’t rise in the sale year.",
                check: "Compare the property value and cash balances before and after the sale.",
                next: "This is expected: a sale converts property into cash. Only the tax on the gain reduces net worth.",
              },
              {
                symptom: "The tax in the sale year is higher than expected.",
                check:
                  "Is Adjusted tax basis ($) blank or low? Is the property marked Primary residence?",
                next: "Enter your actual basis, including improvements. Mark your main home as Primary residence.",
              },
              {
                symptom: "Only $250,000 of the gain is excluded.",
                check: "The filing status in the sale year, for example after a partner’s death.",
                next: "See the surviving-spouse limit above.",
              },
              {
                symptom: "No exclusion on the sale of your home.",
                check:
                  "Are the Owned since or Main home since dates less than two years before the sale?",
                next: "The ownership and use test isn’t met; partial exclusions aren’t modeled.",
              },
              {
                symptom: "The mortgage continues after the home is sold.",
                check:
                  "Is the loan’s Linked real asset set to this property? Was the price lower than the balance?",
                next: "Link the loan to the property. Any unpaid balance stays as debt.",
              },
              {
                symptom: "A property sells in a year you didn’t choose.",
                check: "Is Auto-liquidate on depletion on?",
                next: "This is an automatic sale to cover a shortfall. See the section above.",
              },
            ]}
          />
        </>
      ),
    },
  ],
};
export default article;

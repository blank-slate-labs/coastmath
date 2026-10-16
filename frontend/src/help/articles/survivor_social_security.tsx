import type { Article } from "../help_types";
import {
  Callout,
  DataTable,
  Figure,
  Formula,
  HelpLink,
  Ledger,
  Op,
  Steps,
  Symptoms,
  UIPath,
  V,
} from "../help_kit";
import { LineChart } from "../help_charts";

/* Engine run: Alex (born January 1956) claimed $42,000 at 70; Sam (born September 1968) claims
   $18,000 at 62; Alex's modeled death is the end of 2033; Sam's survivor FRA is September 2035;
   0% inflation. See the sources record. */
const years = [2029, 2030, 2031, 2032, 2033, 2034, 2035, 2036, 2037];
const household = [42000, 48000, 60000, 60000, 60000, 18000, 26000, 42000, 42000];
const samOwn = [0, 6000, 18000, 18000, 18000, 18000, 18000, 18000, 18000];
const topUp = [0, 0, 0, 0, 0, 0, 8000, 24000, 24000];

const article: Article = {
  intro: (
    <>
      <p>
        Survivor benefits are off unless you turn them on. With the survivor option on, after the
        first partner’s modeled death CoastMath pays the survivor the larger of their own benefit
        and the deceased partner’s benefit, never both. It does this by adding a top-up equal to the
        difference, starting in the month the survivor reaches full retirement age for survivor
        benefits.
      </p>
      <p>
        When both partners’ streams use PIA basis, the same option calculates the survivor benefit
        from both primary insurance amounts instead, which also covers early claims and deaths
        before claiming; see <a href="#pia-basis">Survivor benefits from both PIAs</a>. With the
        option off, the deceased partner’s benefit simply stops and the survivor keeps only their
        own. Spousal benefits while both partners are alive are calculated only for PIA-basis
        couples; see <HelpLink to="social-security#pia-basis" />.
      </p>
    </>
  ),
  sections: [
    {
      id: "turn-it-on",
      title: "What it requires",
      body: (
        <>
          <p>
            The option works only on the household horizon, where the projection continues after the
            first death; see <HelpLink to="death-of-a-partner#two-horizons" />. It also needs facts
            CoastMath can’t infer, so the setting asks you to confirm them.
          </p>
          <Steps>
            <li>
              Under <strong>Partner and estate</strong>, set <strong>Plan ends</strong> to{" "}
              <strong>At the last survivor’s longevity age</strong>.
            </li>
            <li>
              Enter <strong>Partner birth year</strong>, <strong>Partner birth month</strong> and{" "}
              <strong>Partner life expectancy (age)</strong>. Your own birth month must also be on
              file.
            </li>
            <li>
              Set <strong>Survivor Social Security policy</strong> to{" "}
              <strong>Claimed benefit top-up at survivor full retirement age</strong>.
            </li>
            <li>
              Check <strong>Survivor eligibility is confirmed, including remarriage rules</strong>{" "}
              and write the basis for that in <strong>Survivor eligibility note</strong>, for
              example the date of the benefit statement you relied on.
            </li>
            <li>Save. The next projection applies the top-up.</li>
          </Steps>
          <p>
            Each partner’s benefit must be its own Social Security stream with the right{" "}
            <strong>Income recipient</strong>. With Benefit amount basis, the partner who dies first
            needs exactly one active stream that:
          </p>
          <ul>
            <li>
              starts at or after that partner’s full retirement age, from a claiming age or a
              milestone set by an age or a date;
            </li>
            <li>
              starts no later than the year of their modeled death, so it is already being paid;
            </li>
            <li>has no end milestone.</li>
          </ul>
          <p>
            The survivor may have one stream of their own or none. If the plan doesn’t meet these
            conditions, the projection doesn’t run rather than guess; see{" "}
            <a href="#projection-errors">Projection errors</a>.
          </p>
          <Callout kind="where">
            <p>
              <UIPath steps={["Partner and estate", "Survivor Social Security policy"]} />. Your own
              birth month is in <UIPath steps={["Plan details", "Birth month"]} />.
            </p>
          </Callout>
        </>
      ),
    },
    {
      id: "how-the-top-up-works",
      title: "How the top-up is calculated",
      body: (
        <>
          <p>
            The deceased partner’s stream stops paying the January after their death year. From the
            later of that January and the survivor’s full-retirement-age month, CoastMath adds a
            line called <strong>Social Security survivor top-up</strong> through the end of the
            survivor’s own life-expectancy year.
          </p>
          <Formula
            result="Survivor top-up for the year"
            note="Both amounts are the full-year rates for the year. The deceased partner’s benefit keeps the claiming amount and cost-of-living growth it had while they were alive."
          >
            <V>Deceased partner’s benefit</V>
            <Op>×</Op>
            <V>eligible share of the year</V>
            <Op>−</Op>
            <V>survivor’s own benefit</V>
            <Op>×</Op>
            <V>share of the year both are paid</V>
          </Formula>
          <p>
            The top-up is never negative. If the survivor’s own benefit is larger, nothing is added.
            Months when the survivor is eligible but hasn’t yet claimed their own benefit receive
            the full deceased benefit. The top-up is taxed like any other Social Security benefit.
          </p>
          <p>
            Full retirement age for survivor benefits uses its own schedule, two birth years behind
            the retirement schedule: 66 for survivors born 1945–1956, rising two months per birth
            year to 67 for those born in 1962 or later.
          </p>
        </>
      ),
    },
    {
      id: "pia-basis",
      title: "Survivor benefits from both PIAs",
      body: (
        <>
          <p>
            When both partners have one active Social Security stream with{" "}
            <strong>Benefit basis</strong> set to <strong>PIA</strong> and the survivor option is
            on, CoastMath works out the survivor benefit from the deceased partner’s primary
            insurance amount (PIA). Mixing a PIA-basis stream with a Benefit amount stream stops the
            projection.
          </p>
          <ul>
            <li>
              <strong>Deceased claimed at or after full retirement age</strong>: the survivor amount
              is the deceased’s benefit, including any delayed credits.
            </li>
            <li>
              <strong>Deceased claimed early</strong>: the survivor amount is the PIA, limited to
              the larger of the deceased’s reduced benefit and 82.5% of the PIA.
            </li>
            <li>
              <strong>Deceased died before claiming</strong>: the PIA, plus delayed credits earned
              through the month before death if they were past full retirement age.
            </li>
          </ul>
          <p>
            The survivor benefit starts at the later of the January after the death year and the
            survivor’s own claim month. If that is before the survivor’s full retirement age for
            survivor benefits, it is reduced in equal monthly steps to 71.5% at 60; the early-claim
            limit above applies after this reduction. The survivor’s expected benefit percentage
            applies. The survivor receives the larger of their own benefit and the survivor benefit,
            as the same <strong>Social Security survivor top-up</strong> line, and any spousal
            benefit stops at the death.
          </p>
          <Ledger
            title="Example: PIAs of $2,000 (born January 1950, claimed at 62) and $800 (born July 1952, claimed at 67); first death at the end of 2026"
            rows={[
              {
                label: "Deceased’s reduced benefit: 75% of $2,000",
                value: 1500,
                detail: "48 months before full retirement age of 66",
              },
              { label: "Limit: larger of $1,500 and 82.5% of $2,000", value: 1650 },
              {
                op: "−",
                label: "Survivor’s own benefit: $800 × 108%",
                value: 864,
                detail: "Delayed credits for claiming at 67",
              },
              { op: "=", label: "Monthly top-up from January 2027", value: 786 },
              { op: "×", label: "Months", value: 12, format: "num" },
              {
                op: "=",
                label: "Survivor top-up in 2027",
                value: 9432,
                detail: "With 0% inflation",
              },
            ]}
            note="In 2026 the survivor also received a $2,400 spousal benefit (half of $2,000 less $800, at full retirement age); it stops in 2027."
          />
        </>
      ),
    },
    {
      id: "worked-example",
      title: "Worked example",
      body: (
        <>
          <p>
            Alex, born January 1956, claimed $42,000 a year at 70 in 2026. Sam, born September 1968,
            claims $18,000 a year at 62, from September 2030. Alex’s life expectancy is 77, so the
            modeled death is the end of 2033. Sam’s full retirement age for survivor benefits is 67,
            reached in September 2035. Inflation is set to 0% to keep the arithmetic visible.
          </p>
          <Figure
            title="Household Social Security by year, survivor top-up on"
            caption="In 2034 Sam receives only their own benefit: the top-up waits for Sam’s survivor full retirement age."
            table={{
              columns: [
                { key: "year", label: "Year" },
                { key: "household", label: "Household total", format: "usd" },
                { key: "own", label: "Sam’s own benefit", format: "usd" },
                { key: "topup", label: "Survivor top-up", format: "usd" },
              ],
              rows: years.map((year, i) => ({
                year: String(year),
                household: household[i],
                own: samOwn[i],
                topup: topUp[i],
              })),
            }}
          >
            <LineChart
              label="Household Social Security falls from $60,000 to $18,000 after Alex’s death, then rises to $42,000 once Sam reaches survivor full retirement age"
              step
              series={[
                {
                  id: "household",
                  label: "Household total",
                  color: "blue",
                  area: true,
                  points: years.map((year, i) => [year, household[i]] as [number, number]),
                },
                {
                  id: "own",
                  label: "Sam’s own benefit",
                  color: "gray",
                  points: years.map((year, i) => [year, samOwn[i]] as [number, number]),
                },
              ]}
              markers={[
                { x: 2034, label: "Alex’s benefit stops" },
                { x: 2035, label: "Survivor top-up starts" },
              ]}
            />
          </Figure>
          <Ledger
            title="2035: the year Sam reaches survivor full retirement age"
            rows={[
              {
                label: "Alex’s benefit, September–December",
                value: 14000,
                detail: "$42,000 × 4 ÷ 12",
              },
              {
                op: "−",
                label: "Sam’s own benefit, same months",
                value: 6000,
                detail: "$18,000 × 4 ÷ 12",
              },
              { op: "=", label: "Survivor top-up", value: 8000 },
              { op: "+", label: "Sam’s own benefit, full year", value: 18000 },
              { op: "=", label: "Social Security for 2035", value: 26000 },
            ]}
            note="From 2036 the top-up is $24,000 a year and the total is $42,000, Alex’s benefit."
          />
          <p>With the survivor option off, the same plan pays Sam $18,000 a year from 2034 on.</p>
        </>
      ),
    },
    {
      id: "former-spouse",
      title: "Benefits from a former spouse",
      body: (
        <>
          <p>
            A PIA-basis benefit can carry one former spouse’s record. CoastMath then adds a
            divorced-spouse benefit while your former spouse is alive and a surviving divorced
            spouse benefit after their death. Your former spouse isn’t part of the household: only
            their PIA, birth date, claiming age and death year are used.
          </p>
          <DataTable
            caption="When each benefit is paid"
            columns={[
              { key: "rule", label: "Requirement" },
              { key: "divorced", label: "Divorced spouse" },
              { key: "survivor", label: "Surviving divorced spouse" },
            ]}
            rows={[
              {
                rule: "Marriage length",
                divorced: "10 years or more",
                survivor: "10 years or more",
              },
              {
                rule: "Your age",
                divorced: "62 or older, and you have claimed your own benefit",
                survivor: "60 or older, from the January after their death year",
              },
              {
                rule: "Your former spouse",
                divorced:
                  "Alive and 62 or older, and either claimed or divorced from you for 2 years",
                survivor: "Deceased",
              },
              {
                rule: "Your current marriage",
                divorced: "You must be unmarried",
                survivor:
                  "A marriage that began at 60 or later doesn’t matter; an earlier one bars the benefit while it lasts",
              },
              {
                rule: "Amount",
                divorced:
                  "Half their PIA minus your PIA, reduced if you start before full retirement age",
                survivor:
                  "Their PIA with delayed credits, or the reduced-benefit limit if they claimed early, reduced for your age, minus your own benefit",
              },
            ]}
          />
          <Ledger
            title="Example: your PIA is $1,000 and your former spouse’s is $3,000"
            rows={[
              { label: "Half your former spouse’s PIA", value: 1500 },
              { op: "−", label: "Your PIA", value: 1000 },
              { op: "=", label: "Monthly excess", value: 500 },
              {
                op: "×",
                label: "Claiming at full retirement age",
                value: 1,
                format: "num",
                digits: 2,
              },
              {
                op: "=",
                label: "Divorced-spouse benefit a year",
                value: 6000,
                detail: "Claiming at 62 instead: 65% of the excess, $3,900",
              },
            ]}
            note="Before cost-of-living adjustments. Your own benefit, $12,000 a year at full retirement age, is paid as well."
          />
          <p>
            You’re treated as married in the years your filing status is married and your partner in
            the plan is alive. A filing status change to single, or your partner’s modeled death,
            makes you eligible again. If you married your current spouse before the plan starts,
            enter the year it began so the survivor rule can tell whether you remarried at 60 or
            later; when it’s blank, CoastMath assumes it was earlier.
          </p>
          <p>
            Only one auxiliary benefit is paid each month. When a spousal benefit from your current
            partner or a survivor top-up overlaps a divorced-spouse or surviving divorced spouse
            amount, CoastMath pays the larger, not both. When your partner’s earnings withhold their
            spousal benefit to you, the comparison uses what is still payable, so a divorced-spouse
            or surviving divorced spouse amount can be paid in full instead. Divorced-spouse amounts
            are counted with your own benefit in the earnings test before full retirement age. At
            full retirement age, a spousal or divorced-spouse benefit that started early is
            refigured without the months it was fully withheld, so less of the early reduction
            applies from then on.
          </p>
          <Callout kind="where">
            <p>
              In the income form, choose <UIPath steps={["Social Security", "PIA"]} />, then check{" "}
              <strong>Include a former spouse’s record</strong> under <strong>Former spouse</strong>
              . Survivor benefits start with your own claim unless you set{" "}
              <strong>Start survivor benefits at age</strong>.
            </p>
          </Callout>
          <Callout kind="boundary">
            <p>
              One former spouse per benefit. The family maximum, benefits based on a disability, and
              a divorce or death in a particular month aren’t modeled: a former spouse’s death falls
              at the end of its year, and a divorce without a month counts from December.
            </p>
          </Callout>
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
                With Benefit amount basis: reduced survivor benefits before survivor full retirement
                age, a deceased partner who claimed early (rejected) and one who hadn’t claimed yet.
                PIA basis on both streams covers these.
              </li>
              <li>
                Claiming the survivor benefit separately from your own claiming age: with PIA basis
                it starts no earlier than your own claim. Switching strategies, such as taking the
                survivor benefit first and your own later, and child or parent survivor benefits.
              </li>
              <li>
                The one-time death payment and remarriage. Eligibility is whatever you confirm;
                CoastMath can’t verify it.
              </li>
              <li>
                Deaths in a particular month: both partners are alive through the end of their
                modeled death year.
              </li>
            </ul>
          </Callout>
        </>
      ),
    },
    {
      id: "projection-errors",
      title: "Projection errors",
      body: (
        <>
          <p>
            When the option is on but the plan doesn’t fit it, the projection fails with a general
            error. Check these in order:
          </p>
          <Symptoms
            rows={[
              {
                symptom: "The projection fails after you turn the option on.",
                check: "The first-to-die partner’s claiming age against their full retirement age.",
                next: "Only claims at or after full retirement age are supported; otherwise turn the option off.",
              },
              {
                symptom: "It still fails.",
                check:
                  "Whether that partner’s stream starts after their modeled death year, or has an end milestone.",
                next: "Start the claim by the death year and remove the end milestone, or turn the option off.",
              },
              {
                symptom: "It still fails.",
                check:
                  "More than one active Social Security stream for one person, or a stream assigned to Partner without a partner in the plan.",
                next: "Keep one stream per person with the right Income recipient.",
              },
              {
                symptom: "No top-up appears after the death.",
                check:
                  "The survivor’s birth year and month, and whether their own benefit is larger.",
                next: "The top-up starts at survivor full retirement age and is zero when the own benefit is higher.",
              },
            ]}
          />
          <p>
            For how the claimed amounts and their growth are set, see{" "}
            <HelpLink to="social-security" />.
          </p>
        </>
      ),
    },
  ],
};

export default article;

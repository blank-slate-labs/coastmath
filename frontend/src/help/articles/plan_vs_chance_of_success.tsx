import type { Article } from "../help_types";
import { HelpLink, Pair, Symptoms, UIPath } from "../help_kit";
import { ExampleFan } from "../figures/chance_of_success";

const article: Article = {
  intro: (
    <>
      <p>
        The overview projection applies your assumed rates every year, so it shows one smooth path.
        The Success odds tab runs the same plan through many market histories and counts how many
        trials run out. A plan can be funded in the projection and still fail in a large share of
        trials. A projection that runs out can also succeed in many trials.
      </p>
      <p>
        Neither result is wrong. They answer different questions: what happens if markets match your
        assumptions every year, and how often the plan survives when they don’t.
      </p>
    </>
  ),
  sections: [
    {
      id: "sequence-of-returns",
      title: "Bad years early are what break a funded projection",
      body: (
        <>
          <p>
            The most common cause. In the projection every year earns the same return. In a trial, a
            run of losses while you’re withdrawing forces sales at low prices, and the money sold
            never recovers. A trial with the same long-run average return as your assumption can
            still run out if its bad years come first.
          </p>
          <Pair
            left={{
              title: "$40,000 of spending",
              body: (
                <p>
                  The projection is funded through the plan’s end with $771,797 left.{" "}
                  <strong>69.3%</strong> of trials succeed.
                </p>
              ),
            }}
            right={{
              title: "$45,000 of spending",
              body: (
                <p>
                  The projection runs out in its final year. <strong>58.3%</strong> of trials still
                  succeed.
                </p>
              ),
            }}
          />
          <p>
            Both use the same example plan: $1,000,000 in a brokerage account at 60, 40% bonds, plan
            default rates, 1,000 trials. A thin margin at the end of the projection usually means a
            success rate near half, in either direction.
          </p>
          <ExampleFan
            title="$40,000 of spending: the projection against the spread of trials"
            caption="The projection stays inside the middle of the spread, but the 10th percentile runs out at 84."
          />
        </>
      ),
    },
    {
      id: "median-is-not-the-projection",
      title: "The median trial isn’t the projection",
      body: (
        <>
          <p>
            The median line is the middle value of all trials in each year, not a trial of its own.
            It can end well above or below the projection. In the example it ends at $1,368,356
            against the projection’s $771,797, yet 30.7% of trials run out. Judge risk by the
            success rate and the lower percentiles, not by where the median ends. See{" "}
            <HelpLink to="chance-of-success#reading-percentiles" />.
          </p>
        </>
      ),
    },
    {
      id: "settings-that-change-the-rate",
      title: "Settings that change the rate",
      body: (
        <>
          <ul>
            <li>
              <strong>Calibration off.</strong> Trials then use unadjusted history, which returned
              more than the 7% default. The example rises from 69.3% to 90.7%.
            </li>
            <li>
              <strong>Failure definition.</strong> Both tests fail a trial in any year spending goes
              unpaid. The default also fails it when cash and investments reach zero. The net-worth
              test instead fails it when debts exceed everything owned, which can happen while
              spending is still paid.
            </li>
            <li>
              <strong>Targets.</strong> A final net worth target or counting flexible-spending cuts
              affects only the target success rate, not the funding success rate.
            </li>
            <li>
              <strong>Trials and seed.</strong> The same seed repeats the same result. More trials
              move it by about a point: the example is 69.3% at 1,000 trials and 68.5% at 5,000.
            </li>
          </ul>
          <p>
            Settings are in <UIPath steps={["Success odds", "Run settings and success criteria"]} />
            .
          </p>
        </>
      ),
    },
    {
      id: "symptoms",
      title: "Symptoms and checks",
      body: (
        <>
          <Symptoms
            rows={[
              {
                symptom: "The projection is funded, but the success rate is low.",
                check:
                  "How much is left at the end of the projection, and when the lower percentiles cross zero.",
                next: (
                  <>
                    Expected when the margin is thin or withdrawals start early. See{" "}
                    <HelpLink to="chance-of-success#how-success-is-counted" />.
                  </>
                ),
              },
              {
                symptom: "The projection runs out, but many trials succeed.",
                check:
                  "The year the projection runs out. Late shortfalls leave roughly half the trials funded.",
                next: <>Look at the failure analysis’s average age at failure.</>,
              },
              {
                symptom: "The success rate is much higher than expected.",
                check: "Whether calibration is off.",
                next: <>Turn calibration on to center trials on your assumptions.</>,
              },
              {
                symptom: "One account barely varies across trials.",
                check: "Whether the account has its own fixed stock growth or dividend yield.",
                next: (
                  <>
                    Clear those fields to let it follow sampled returns. See{" "}
                    <HelpLink to="market-and-inflation-assumptions#account-overrides" />.
                  </>
                ),
              },
              {
                symptom: "The median ends far from the projection.",
                check: "The median is ranked year by year across trials.",
                next: <>Compare success rates and the 10th percentile instead.</>,
              },
              {
                symptom: "Rerunning gives exactly the same result.",
                check: "The random seed. It defaults to 42.",
                next: <>Clear the seed for an independent run.</>,
              },
            ]}
          />
          <p>
            To see how one bad historical period plays out year by year, replay it in the{" "}
            <HelpLink to="historical-stress-test" />.
          </p>
        </>
      ),
    },
  ],
};
export default article;

import type {
  Account,
  CashFlowPriorityCreate,
  EmployerMatch,
  EmployerMatchTier,
} from "@/types/plan";
import {
  ROTH_EMPLOYER_PLAN_TYPES,
  ROTH_PLAN_COUNTERPART,
  employerPlanFamily,
} from "@/domain/account_types";
import { moneyLabel } from "@/utils/format";
import MoneyInput from "./money_input";

type Edit = (update: Partial<CashFlowPriorityCreate>) => void;

/** A common starting formula: dollar for dollar on the first 6% of pay. */
export const DEFAULT_EMPLOYER_MATCH: EmployerMatch = {
  tiers: [{ match_percent: 100, up_to_percent_of_pay: 6 }],
  cap_amount: null,
  nonelective_percent: 0,
  true_up: true,
  roth: false,
};

const numberOr = (value: string, fallback: number) => (value === "" ? fallback : Number(value));

/** Employer contribution controls for an income_percent payroll rule: a fixed percent of pay or a matching formula. */
export function EmployerMatchFields({
  rule,
  target,
  edit,
}: {
  rule: CashFlowPriorityCreate;
  target?: Account;
  edit: Edit;
}) {
  const match = rule.employer_match ?? null;
  const family = employerPlanFamily(target?.account_type);
  const rothAllowed =
    !!target &&
    (ROTH_EMPLOYER_PLAN_TYPES.has(target.account_type) ||
      !!ROTH_PLAN_COUNTERPART[target.account_type]);
  const setMatch = (update: Partial<EmployerMatch>) =>
    edit({ employer_match: { ...(match ?? DEFAULT_EMPLOYER_MATCH), ...update } });
  const setTier = (index: number, update: Partial<EmployerMatchTier>) =>
    setMatch({
      tiers: (match?.tiers ?? []).map((tier, j) => (j === index ? { ...tier, ...update } : tier)),
    });
  return (
    <>
      <label>
        Employer contribution
        <select
          value={match ? "formula" : "percent"}
          onChange={(e) =>
            edit(
              e.target.value === "formula"
                ? { employer_match: DEFAULT_EMPLOYER_MATCH, employer_match_rate: 0 }
                : { employer_match: null },
            )
          }
        >
          <option value="percent">Fixed percent of pay</option>
          <option value="formula">Matching formula</option>
        </select>
      </label>
      {!match && (
        <label>
          Employer contribution (% of income)
          <input
            type="number"
            required
            min={0}
            max={100}
            step="0.01"
            value={rule.employer_match_rate ?? 0}
            onChange={(e) => edit({ employer_match_rate: Number(e.target.value) })}
          />
        </label>
      )}
      {match && (
        <fieldset className="allocation-fields" aria-label="Matching formula">
          <p className="allocation-help">
            Each tier matches a share of what the employee defers on the next slice of pay, in
            order. A fixed percent of pay is paid even with no deferral; a matching formula pays
            only on deferrals.
          </p>
          {match.tiers.map((tier, j) => (
            <div key={j} className="allocation-actions">
              <label>
                Match (%)
                <input
                  type="number"
                  required
                  min={0}
                  max={500}
                  step="0.01"
                  value={tier.match_percent}
                  onChange={(e) => setTier(j, { match_percent: numberOr(e.target.value, 0) })}
                />
              </label>
              <label>
                of the next (% of pay)
                <input
                  type="number"
                  required
                  min={0.01}
                  max={100}
                  step="0.01"
                  value={tier.up_to_percent_of_pay}
                  onChange={(e) =>
                    setTier(j, { up_to_percent_of_pay: numberOr(e.target.value, 0) })
                  }
                />
              </label>
              <button
                type="button"
                aria-label={`Remove match tier ${j + 1}`}
                onClick={() => setMatch({ tiers: match.tiers.filter((_, k) => k !== j) })}
              >
                Remove tier
              </button>
            </div>
          ))}
          {match.tiers.length < 10 && (
            <button
              type="button"
              onClick={() =>
                setMatch({
                  tiers: [...match.tiers, { match_percent: 50, up_to_percent_of_pay: 2 }],
                })
              }
            >
              Add match tier
            </button>
          )}
          <label>
            Nonelective contribution (% of pay)
            <input
              type="number"
              min={0}
              max={100}
              step="0.01"
              value={match.nonelective_percent ?? 0}
              onChange={(e) => setMatch({ nonelective_percent: numberOr(e.target.value, 0) })}
            />
          </label>
          <label>
            {moneyLabel("Annual employer cap ($, today’s dollars; optional)")}
            <MoneyInput
              min={0}
              step="0.01"
              value={match.cap_amount ?? ""}
              onValueChange={(amount) =>
                setMatch({ cap_amount: amount === "" ? null : Number(amount) })
              }
            />
          </label>
          <label className="allocation-check">
            <input
              type="checkbox"
              checked={match.true_up ?? true}
              onChange={(e) => setMatch({ true_up: e.target.checked })}
            />{" "}
            True up the match at year end
          </label>
          <p className="allocation-help">
            {(match.true_up ?? true)
              ? "The match uses the whole year’s deferrals."
              : "Matched each pay period: if deferrals reach the annual limit early, later paychecks get no match."}
          </p>
          {rothAllowed && (
            <label className="allocation-check">
              <input
                type="checkbox"
                checked={match.roth ?? false}
                onChange={(e) => setMatch({ roth: e.target.checked })}
              />{" "}
              Roth employer contributions
            </label>
          )}
          {match.roth && (
            <p className="allocation-help">
              Paid into the owner’s Roth {family} and taxed as income in the year contributed (not
              payroll tax). Requires a Roth {family} account for this person.
            </p>
          )}
        </fieldset>
      )}
    </>
  );
}

/** Plan limit override for contribution and payroll rules: never above the IRS limit. */
export function ContributionLimitFields({
  rule,
  edit,
}: {
  rule: CashFlowPriorityCreate;
  edit: Edit;
}) {
  const custom = rule.limit_mode === "custom";
  return (
    <>
      <label>
        Contribution limit
        <select
          value={custom ? "custom" : "irs"}
          onChange={(e) =>
            edit(
              e.target.value === "custom"
                ? { limit_mode: "custom", custom_annual_limit: rule.custom_annual_limit ?? 0 }
                : { limit_mode: "irs", custom_annual_limit: null },
            )
          }
        >
          <option value="irs">IRS limit</option>
          <option value="custom">Lower plan limit</option>
        </select>
      </label>
      {custom && (
        <>
          <label>
            {moneyLabel("Plan annual limit ($, today’s dollars)")}
            <MoneyInput
              required
              min={0}
              step="0.01"
              value={rule.custom_annual_limit ?? ""}
              onValueChange={(amount) =>
                edit({ custom_annual_limit: amount === "" ? null : Number(amount) })
              }
            />
          </label>
          <p className="allocation-help">
            Caps the year’s contributions to this account, indexed like IRS limits. The IRS limit
            still applies when it is lower.
          </p>
        </>
      )}
    </>
  );
}

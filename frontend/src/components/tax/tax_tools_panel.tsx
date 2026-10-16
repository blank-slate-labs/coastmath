import { useRef, useState } from "react";
import { usePlanStore } from "@/stores/plan_store";
import ComparisonControls from "../comparison_controls";
import { RothConversionPlanner } from "./roth_conversion_planner";
import { DeductionComparison } from "./deduction_comparison";
import { SEPPCalculator } from "./sepp_calculator";
import CashReserveControl from "./cash_reserve_control";
import { HealthcarePanel } from "./healthcare_panel";
import { TaxStrategyOptimizer } from "./tax_strategy_optimizer";
import { TaxSuggestions } from "./tax_suggestions";
import { compactCurrency, signedCompactCurrency } from "@/utils/format";
import { countryName, isIntlYear, usCoverage } from "@/domain/intl_plan";
import { ownerLabel } from "@/domain/person_labels";
import UsOnlyNote from "@/components/intl/us_only_note";
import type { YearSnapshot } from "@/types/plan";
import { EMPTY_PLAN_TEXT, isEmptyProjection } from "@/utils/plan_inputs";

const TASKS = [
  ["annual", "Annual tax breakdown"],
  ["conversions", "Conversion scenarios"],
  ["strategies", "Strategy comparisons"],
  ["healthcare", "Health coverage"],
  ["early", "Early withdrawals"],
] as const;

/** A year taxed under another country's rules: its totals and each line, as the engine reported them. */
function intlRows(snapshot: YearSnapshot): [string, string][] {
  const totals: [string, number | undefined][] = [
    ["National income tax", snapshot.national_income_tax],
    ["Regional income tax", snapshot.regional_income_tax],
    ["Social contributions", snapshot.social_contributions],
    ["Wealth tax", snapshot.wealth_tax],
    ["Transaction tax", snapshot.transaction_tax],
    ["Benefit recovery tax", snapshot.benefit_recovery_tax],
  ];
  return [
    ["Tax rules", countryName(snapshot.tax_country)],
    ...totals
      .filter(([, value]) => (value ?? 0) !== 0)
      .map(([label, value]): [string, string] => [label, compactCurrency(value ?? 0)]),
    ...(snapshot.intl_tax_lines ?? [])
      .filter((line) => line.amount !== 0)
      .map((line): [string, string] => [
        `${line.label}${line.person === "self" || line.person === "spouse" ? ` (${ownerLabel(line.person)})` : ""}`,
        compactCurrency(line.amount),
      ]),
  ];
}

export default function TaxToolsPanel({
  onEditAccounts,
  onEditHealth,
}: {
  onEditAccounts?: () => void;
  onEditHealth?: () => void;
}) {
  const { plan, simulation: current, baselineSimulation, isSimulating } = usePlanStore();
  const [task, setTask] = useState("annual");
  const [year, setYear] = useState<number | null>(null);
  // A save clears the projection until it reruns. Keep showing this plan's last one meanwhile, so the
  // tools stay mounted and keep their drafts, comparison results and confirmations.
  const last = useRef<{ planId: string; simulation: NonNullable<typeof current> } | null>(null);
  if (plan && current) last.current = { planId: plan.id, simulation: current };
  const simulation =
    current ??
    (isSimulating && last.current?.planId === plan?.id ? last.current?.simulation : null);
  if (!plan || !simulation?.yearly_snapshots.length)
    return <p role="status">{isSimulating ? "Updating projection…" : "No projection yet."}</p>;
  if (isEmptyProjection(simulation)) return <p role="status">{EMPTY_PLAN_TEXT}</p>;
  const snapshots = simulation.yearly_snapshots;
  const snapshot = snapshots.find((s) => s.year === year) ?? snapshots[0];
  const coverage = usCoverage(plan);
  // With no US year, the US tools give way to the annual breakdown and the cash reserve.
  const tasks: readonly (readonly [string, string])[] =
    coverage === "non_us"
      ? [
          ["annual", "Annual tax breakdown"],
          ["early", "Cash reserve"],
        ]
      : TASKS;
  const intlYear = isIntlYear(snapshot.tax_country);
  const flat = plan.tax_settings?.mode === "flat";
  // Federal brackets and deductions describe US years only.
  const usBrackets = !flat && !intlYear;
  const estimated = (plan.tax_settings?.estimated_payments?.strategy ?? "off") !== "off";
  const estimatedRows = estimated
    ? [
        [
          "Estimated tax payments",
          compactCurrency(snapshot.cash_flow?.estimated_tax_payments ?? 0),
        ],
        [
          "Required annual payment",
          compactCurrency(snapshot.cash_flow?.required_annual_payment ?? 0),
        ],
        ["Underpayment penalty", compactCurrency(snapshot.cash_flow?.underpayment_penalty ?? 0)],
      ]
    : [];
  const baselineByYear = new Map(baselineSimulation?.yearly_snapshots.map((s) => [s.year, s]));
  const shared = snapshots.filter((s) => baselineByYear.has(s.year));
  const taxDifference = shared.reduce(
    (sum, s) => sum + s.taxes - baselineByYear.get(s.year)!.taxes,
    0,
  );
  return (
    <div style={{ display: "grid", gap: 20 }}>
      <nav aria-label="Tax tasks" className="seg-control task-tabs">
        {tasks.map(([key, label]) => (
          <button
            type="button"
            className={`seg-option${task === key ? " active" : ""}`}
            aria-pressed={task === key}
            key={key}
            onClick={() => setTask(key)}
          >
            {label}
          </button>
        ))}
      </nav>
      {task !== "annual" && (
        <UsOnlyNote
          coverage={coverage}
          what="Roth conversion, strategy, health coverage and 72(t) tools model US rules and"
        />
      )}
      {task !== "annual" && onEditAccounts && (
        <button type="button" className="btn-secondary" onClick={onEditAccounts}>
          Review household accounts
        </button>
      )}
      <div hidden={task !== "annual"}>
        <section className="card">
          <h2>Tax tools</h2>
          <ComparisonControls />
          <p style={{ color: "var(--text-secondary)" }}>
            {intlYear
              ? `${countryName(snapshot.tax_country)} tax rules this year: US bracket and deduction analysis does not apply. `
              : flat
                ? "Flat tax mode: bracket and deduction analysis unavailable. "
                : ""}
            {coverage === "us" ? "Nominal dollars." : "Nominal amounts."}
          </p>
          {isSimulating && <p role="status">Recalculating tax results…</p>}
          {!!shared.length && (
            <p>
              Tax change versus baseline across shared years {shared[0].year}–
              {shared[shared.length - 1].year}:{" "}
              <strong>{signedCompactCurrency(taxDifference)}</strong>. This is the difference
              between the complete scenarios, not an isolated conversion estimate.
            </p>
          )}
          <label data-sample-view>
            Tax year
            <select value={snapshot.year} onChange={(e) => setYear(Number(e.target.value))}>
              {snapshots.map((s) => (
                <option key={s.year} value={s.year}>
                  {s.year} · age {s.age}
                </option>
              ))}
            </select>
          </label>
          <dl style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10 }}>
            {(intlYear
              ? [
                  [
                    "Calendar-year gross income",
                    compactCurrency(snapshot.calendar_year_gross_income ?? snapshot.gross_income),
                  ],
                  ["Full-year taxes", compactCurrency(snapshot.taxes)],
                  ...intlRows(snapshot),
                  [
                    "Early withdrawal penalty",
                    compactCurrency(snapshot.early_withdrawal_penalty ?? 0),
                  ],
                  ["Tax balance carried", compactCurrency(snapshot.tax_balance ?? 0)],
                  ["Effective rate", `${(snapshot.effective_rate * 100).toFixed(1)}%`],
                  ["Marginal rate", `${(snapshot.marginal_rate * 100).toFixed(1)}%`],
                ]
              : [
                  [
                    "Calendar-year gross income",
                    compactCurrency(snapshot.calendar_year_gross_income ?? snapshot.gross_income),
                  ],
                  ["Full-year taxes", compactCurrency(snapshot.taxes)],
                  [
                    "Federal ordinary tax (including any AMT adjustment)",
                    compactCurrency(snapshot.federal_tax),
                  ],
                  ["Capital gains tax", compactCurrency(snapshot.capital_gains_tax)],
                  ["State tax", compactCurrency(snapshot.state_tax)],
                  ...(snapshot.state_retirement_exclusion
                    ? [
                        [
                          "State retirement-income exclusion (reduces state taxable income)",
                          compactCurrency(snapshot.state_retirement_exclusion),
                        ],
                      ]
                    : []),
                  ...(snapshot.state_social_security_subtraction
                    ? [
                        [
                          "State Social Security subtraction (reduces state taxable income)",
                          compactCurrency(snapshot.state_social_security_subtraction),
                        ],
                      ]
                    : []),
                  ...(snapshot.state_capital_gains_excise
                    ? [
                        [
                          "Washington capital gains tax (included in state tax)",
                          compactCurrency(snapshot.state_capital_gains_excise),
                        ],
                      ]
                    : []),
                  ...(snapshot.rental_income || snapshot.rental_taxable_income
                    ? [
                        [
                          "Rental income in AGI (after expenses, depreciation and passive loss limits)",
                          compactCurrency(snapshot.rental_taxable_income ?? 0),
                        ],
                      ]
                    : []),
                  ...(snapshot.rental_depreciation
                    ? [["Rental depreciation", compactCurrency(snapshot.rental_depreciation)]]
                    : []),
                  ...(snapshot.suspended_passive_losses
                    ? [
                        [
                          "Suspended rental losses carried forward",
                          compactCurrency(snapshot.suspended_passive_losses),
                        ],
                      ]
                    : []),
                  ...(snapshot.unrecaptured_section_1250_gain
                    ? [
                        [
                          "Depreciation recapture gain (taxed at up to 25%)",
                          compactCurrency(snapshot.unrecaptured_section_1250_gain),
                        ],
                      ]
                    : []),
                  ["Local tax", compactCurrency(snapshot.local_tax ?? 0)],
                  ["Payroll tax", compactCurrency(snapshot.fica_tax)],
                  ["Net investment income tax", compactCurrency(snapshot.niit_tax ?? 0)],
                  [
                    "Early withdrawal penalty",
                    compactCurrency(snapshot.early_withdrawal_penalty ?? 0),
                  ],
                  ...estimatedRows,
                  ["Tax balance carried", compactCurrency(snapshot.tax_balance ?? 0)],
                  ["Effective rate", `${(snapshot.effective_rate * 100).toFixed(1)}%`],
                  ["Marginal rate", `${(snapshot.marginal_rate * 100).toFixed(1)}%`],
                ]
            ).map(([label, value]) => (
              <div key={label} style={{ display: "contents" }}>
                <dt>{label}</dt>
                <dd style={{ margin: 0, textAlign: "right" }}>{value}</dd>
              </div>
            ))}
          </dl>
          <p className="allocation-help">
            Effective rate uses calendar-year gross income. Tax balance carried is a timing balance,
            not extra tax.
          </p>
          {estimated && (
            <p className="allocation-help">
              Estimated payments and the required annual payment cover federal tax only. The
              underpayment penalty is an annual estimate and is included in full-year taxes.
            </p>
          )}
          {(snapshot.early_withdrawal_penalty ?? 0) > 0 && (
            <p>
              Early withdrawal penalty applied.{" "}
              <a
                href="https://www.irs.gov/retirement-plans/plan-participant-employee/retirement-topics-exceptions-to-tax-on-early-distributions"
                target="_blank"
                rel="noreferrer"
              >
                IRS exceptions
              </a>{" "}
              other than age 59½, a 72(t) series, an inherited account and the age-55 separation
              rule are not modeled.
            </p>
          )}
          {usBrackets && (
            <p>
              Deduction used:{" "}
              <strong>
                {snapshot.deduction_used} · {compactCurrency(snapshot.deduction_amount)}
              </strong>
              . Standard deduction available: {compactCurrency(snapshot.standard_deduction)}.
            </p>
          )}
          {usBrackets && (
            <details>
              <summary>Deduction and marginal-rate history</summary>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", fontSize: 13 }}>
                  <thead>
                    <tr>
                      <th>Year</th>
                      <th>Marginal rate</th>
                      <th>Deduction used</th>
                      <th>Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshots.map((s) => (
                      <tr key={s.year}>
                        <td>{s.year}</td>
                        <td>{(s.marginal_rate * 100).toFixed(1)}%</td>
                        <td>{s.deduction_used}</td>
                        <td>{compactCurrency(s.deduction_amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </section>
        {!flat && coverage !== "non_us" && (
          <section className="card">
            <DeductionComparison snapshots={snapshots} />
          </section>
        )}
      </div>
      {coverage !== "non_us" && (
        <>
          <section className="card" hidden={task !== "conversions"}>
            <RothConversionPlanner key={plan.id} snapshots={snapshots} />
          </section>
          <section className="card" hidden={task !== "strategies"}>
            <TaxSuggestions key={`suggestions-${plan.id}`} />
          </section>
          {!flat && (
            <section className="card" hidden={task !== "strategies"}>
              <TaxStrategyOptimizer key={`strategy-${plan.id}`} />
            </section>
          )}
          {flat && task === "strategies" && <p>Requires bracket-based taxes.</p>}
          <section className="card" hidden={task !== "healthcare"}>
            <HealthcarePanel
              snapshots={snapshots}
              configured={!!plan.healthcare_settings?.enabled}
              onEdit={onEditHealth}
            />
          </section>
          <section className="card" hidden={task !== "early"}>
            <SEPPCalculator key={`sepp-${plan.id}`} snapshots={snapshots} />
          </section>
        </>
      )}
      <section className="card" hidden={task !== "early"}>
        <CashReserveControl key={`reserve-${plan.id}`} />
      </section>
    </div>
  );
}

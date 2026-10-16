import { useState, useEffect, useMemo, useRef, useCallback } from "react";

import { usePlanStore } from "@/stores/plan_store";
import * as api from "@/api/client";
import { useStorage } from "@/storage/context";
import type { YearSnapshot, Account, SEPPMethod, SEPPPreviewResponse } from "@/types/plan";
import { fullCurrency, moneyLabel, pct } from "@/utils/format";
import MoneyInput from "@/components/money_input";
import {
  EMPLOYER_PLAN_TYPES,
  SEPP_ELIGIBLE_TYPES,
  employerPlanFamily,
} from "@/domain/account_types";
import { helpTextStyle } from "../form_styles";

const METHODS: { value: SEPPMethod; label: string; help: string }[] = [
  {
    value: "fixed_amortization",
    label: "Fixed amortization",
    help: "Balance amortized over IRS Single Life expectancy at the chosen rate.",
  },
  {
    value: "rmd_method",
    label: "Required-minimum-distribution method",
    help: "Balance divided by the Single Life factor each year; the payment changes with the balance.",
  },
];

const warningStyle: React.CSSProperties = {
  padding: "8px 10px",
  background: "var(--color-danger-light, rgba(220, 38, 38, 0.08))",
  borderRadius: "var(--radius-md, 6px)",
  fontSize: 13,
  color: "var(--color-danger)",
};

interface SEPPCalculatorProps {
  snapshots: YearSnapshot[];
}

/**
 * SEPP 72(t) planner. Amounts come from the backend preview endpoint, which
 * runs the same functions as the projection engine, so what is shown here is
 * what the simulation withdraws.
 */
export const SEPPCalculator = ({ snapshots }: SEPPCalculatorProps) => {
  const plan = usePlanStore((s) => s.plan);
  const updatePlan = usePlanStore((s) => s.updatePlan);

  const [accounts, setAccounts] = useState<Account[]>([]);
  const [enabled, setEnabled] = useState(plan?.sepp_settings?.enabled ?? false);
  const [sourceAccountId, setSourceAccountId] = useState(
    plan?.sepp_settings?.source_account_id ?? "",
  );
  const [method, setMethod] = useState<SEPPMethod>(
    plan?.sepp_settings?.method ?? "fixed_amortization",
  );
  const [startAge, setStartAge] = useState(
    plan?.sepp_settings ? String(plan.sepp_settings.start_age) : "50",
  );
  const [interestRate, setInterestRate] = useState(
    plan?.sepp_settings ? String(plan.sepp_settings.interest_rate * 100) : "5",
  );
  const [customAmount, setCustomAmount] = useState(
    plan?.sepp_settings?.annual_amount != null ? String(plan.sepp_settings.annual_amount) : "",
  );
  const [preview, setPreview] = useState<SEPPPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  // Edited since the last save; switching tabs or reloading asks first.
  const [dirty, setDirty] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const { adapter } = useStorage();
  const accountLoad = useRef(0);
  const loadAccounts = useCallback(async () => {
    const request = ++accountLoad.current;
    setAccounts([]);
    try {
      const items = await adapter.listAccounts(plan?.id);
      if (accountLoad.current === request) setAccounts(items);
    } catch {
      /* accounts may not be loaded yet */
    }
  }, [adapter, plan?.id]);
  useEffect(() => {
    void loadAccounts();
    return () => {
      accountLoad.current += 1;
    };
  }, [loadAccounts]);

  const eligibleAccounts = useMemo(
    () => accounts.filter((a) => SEPP_ELIGIBLE_TYPES.has(a.account_type)),
    [accounts],
  );
  const sourceAccount = accounts.find((a) => a.id === sourceAccountId);
  const sourceBalance = sourceAccount?.balance ?? snapshots[0]?.accounts?.[sourceAccountId] ?? 0;

  const parsedStartAge = Number(startAge);
  const parsedRate = Number(interestRate) / 100;
  // A series follows the IRA owner's age, as the projection does.
  const ownerIsPartner = sourceAccount?.owner === "spouse" && plan?.spouse?.birth_year != null;
  const ownerBirthYear = ownerIsPartner
    ? (plan?.spouse?.birth_year ?? null)
    : (plan?.birth_year ?? null);
  const ownerBirthMonth = ownerIsPartner
    ? (plan?.spouse?.birth_month ?? null)
    : (plan?.birth_month ?? null);
  const currentAge =
    ownerBirthYear == null ? 0 : (snapshots[0]?.year ?? new Date().getFullYear()) - ownerBirthYear;
  const ageInvalid =
    startAge.trim() === "" ||
    !Number.isInteger(parsedStartAge) ||
    parsedStartAge < 18 ||
    parsedStartAge >= 59.5;
  const rateInvalid =
    interestRate.trim() === "" ||
    !Number.isFinite(parsedRate) ||
    parsedRate < 0 ||
    parsedRate > 0.15;
  const rateAboveSafeHarbor = !rateInvalid && parsedRate > 0.05;
  const parsedCustom = customAmount.trim() === "" ? null : Number(customAmount);
  const customInvalid =
    parsedCustom != null && !(Number.isFinite(parsedCustom) && parsedCustom > 0);
  const startInPast = !ageInvalid && parsedStartAge < currentAge;

  useEffect(() => {
    if (!enabled || !sourceAccountId || ageInvalid || rateInvalid || sourceBalance <= 0) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    const handle = setTimeout(() => {
      setPreviewError(null);
      api
        .previewSepp({
          balance: sourceBalance,
          start_age: parsedStartAge,
          interest_rate: parsedRate,
          birth_year: ownerBirthYear,
          birth_month: ownerBirthMonth,
          ...(parsedCustom != null && !customInvalid ? { annual_amount: parsedCustom } : {}),
        })
        .then((result) => {
          if (!cancelled) setPreview(result);
        })
        .catch(() => {
          if (!cancelled) {
            setPreview(null);
            setPreviewError("Could not calculate SEPP amounts. Check the inputs and try again.");
          }
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [
    enabled,
    sourceAccountId,
    sourceBalance,
    parsedStartAge,
    parsedRate,
    ageInvalid,
    rateInvalid,
    ownerBirthYear,
    ownerBirthMonth,
    parsedCustom,
    customInvalid,
  ]);

  if (!plan) return null;

  const selectedPreview = preview?.methods.find((m) => m.method === method) ?? null;
  const canSave = !enabled || (!!sourceAccountId && !ageInvalid && !rateInvalid && !customInvalid);

  async function handleSave() {
    if (!plan || !canSave) return;
    setSaving(true);
    setSaved(false);
    setSaveError(null);
    try {
      await updatePlan(plan.id, {
        sepp_settings: enabled
          ? {
              enabled: true,
              source_account_id: sourceAccountId,
              method,
              start_age: parsedStartAge,
              interest_rate: parsedRate,
              ...(parsedCustom != null || plan.sepp_settings?.annual_amount != null
                ? { annual_amount: parsedCustom }
                : {}),
            }
          : plan.sepp_settings
            ? { ...plan.sepp_settings, enabled: false }
            : null,
      });
      setSaved(true);
      setDirty(false);
    } catch {
      setSaveError("Could not save SEPP settings. Your edits are retained; try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{ display: "grid", gap: 12 }}
      data-sample-editor
      data-unsaved-changes={dirty || undefined}
      data-save-pending={saving || undefined}
      onChange={() => setDirty(true)}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <h3 style={{ margin: 0 }}>Early retirement withdrawals · SEPP 72(t)</h3>
        <label
          style={{ fontSize: 13, cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}
        >
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => {
              setEnabled(e.target.checked);
              setSaved(false);
            }}
          />
          Enabled
        </label>
      </div>
      <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
        SEPP payments continue for five years or until 59½, whichever is later. Fixed annuitization
        is unavailable.
      </p>

      {!enabled && (
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-tertiary)" }}>
          The source account is excluded from other withdrawals during the payment series.
        </p>
      )}

      {enabled && (
        <fieldset
          disabled={saving}
          style={{ border: 0, padding: 0, minWidth: 0, display: "grid", gap: 10 }}
        >
          <label>
            Source account
            <select
              value={sourceAccountId}
              onChange={(e) => {
                setSourceAccountId(e.target.value);
                setSaved(false);
              }}
            >
              <option value="">— Choose a traditional IRA or 401(k) —</option>
              {eligibleAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} · {fullCurrency(a.balance)}
                </option>
              ))}
            </select>
            {eligibleAccounts.length === 0 && (
              <span style={helpTextStyle}>
                No traditional IRA, 401(k), 403(b) or 401(a) accounts found. Add one in Accounts
                first. A 457(b) needs no series: it has no 10% early-withdrawal tax.
              </span>
            )}
            {EMPLOYER_PLAN_TYPES.has(sourceAccount?.account_type ?? "") && (
              <span style={helpTextStyle}>
                A {employerPlanFamily(sourceAccount?.account_type)} series requires separation from
                that employer's service.
              </span>
            )}
            {ownerIsPartner && (
              <span style={helpTextStyle}>Ages are your partner's, who owns this account.</span>
            )}
          </label>

          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend style={{ fontSize: 13, marginBottom: 4 }}>Method</legend>
            {METHODS.map((m) => (
              <label
                key={m.value}
                style={{
                  display: "flex",
                  gap: 8,
                  alignItems: "flex-start",
                  marginBottom: 6,
                  cursor: "pointer",
                }}
              >
                <input
                  type="radio"
                  name="sepp-method"
                  value={m.value}
                  checked={method === m.value}
                  onChange={() => {
                    setMethod(m.value);
                    setSaved(false);
                  }}
                />
                <span>
                  <strong style={{ fontSize: 13 }}>{m.label}</strong>
                  <br />
                  <span style={helpTextStyle}>{m.help}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
              gap: 12,
            }}
          >
            <label>
              Start age
              <input
                type="number"
                min={18}
                max={59}
                step={1}
                value={startAge}
                onChange={(e) => {
                  setStartAge(e.target.value);
                  setSaved(false);
                }}
              />
            </label>
            <label>
              Interest rate (%)
              <input
                type="number"
                min={0}
                max={15}
                step={0.1}
                value={interestRate}
                onChange={(e) => {
                  setInterestRate(e.target.value);
                  setSaved(false);
                }}
              />
            </label>
          </div>
          <span style={helpTextStyle}>
            The rate may not exceed the greater of 5% or 120% of the federal mid-term rate for
            either of the two months before the first payment (IRS Notice 2022-6).
          </span>

          <label>
            {moneyLabel("Custom yearly payment ($; optional)")}
            <MoneyInput
              min={0.01}
              step={0.01}
              value={customAmount}
              onValueChange={(value) => {
                setCustomAmount(value);
                setSaved(false);
              }}
              aria-invalid={customInvalid || undefined}
            />
            <span style={helpTextStyle}>
              Only an IRS-approved method keeps the exemption from the 10% tax. An amount that
              differs from the fixed-amortization payment is projected as an ordinary early
              withdrawal and carries the penalty.
            </span>
          </label>
          {customInvalid && (
            <div role="alert" style={warningStyle}>
              The custom payment must be more than zero, or blank to use the method above.
            </div>
          )}
          {ageInvalid && (
            <div role="alert" style={warningStyle}>
              Start age must be a whole age from 18 to 59; a series cannot begin at 59½ or later.
            </div>
          )}
          {rateInvalid && (
            <div role="alert" style={warningStyle}>
              Interest rate must be between 0% and 15%.
            </div>
          )}
          {rateAboveSafeHarbor &&
            (preview?.rate_ceiling == null ? (
              <div role="alert" style={warningStyle}>
                Rates above 5% require 120% of the federal mid-term rate to be higher.
              </div>
            ) : parsedRate > preview.rate_ceiling + 1e-12 ? (
              <div role="alert" style={warningStyle}>
                This rate is above the {pct(preview.rate_ceiling, 2)} allowed for a series starting
                then.
              </div>
            ) : (
              <div role="status" style={helpTextStyle}>
                Allowed: 120% of the federal mid-term rate before the first payment is{" "}
                {pct(preview.rate_ceiling, 2)}.
              </div>
            ))}
          {startInPast && (
            <div role="alert" style={warningStyle}>
              Start age {parsedStartAge} is before {ownerIsPartner ? "your partner's" : "your"}{" "}
              current age {currentAge}; the series would begin immediately.
            </div>
          )}
          {sourceAccountId && sourceBalance <= 0 && (
            <div role="alert" style={warningStyle}>
              The selected account has no balance.
            </div>
          )}
          {previewError && (
            <div role="alert" style={warningStyle}>
              {previewError}
            </div>
          )}

          {preview && (
            <div style={{ display: "grid", gap: 10 }}>
              <p style={{ margin: 0, fontSize: 13 }}>
                Payments run from age {parsedStartAge} through the year containing age{" "}
                <strong>{preview.end_age}</strong> ({preview.payment_years} annual payments). Single
                Life factor at start: <strong>{preview.single_life_divisor.toFixed(1)}</strong>.
              </p>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", fontSize: 13 }} aria-label="SEPP method comparison">
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left" }}>Method</th>
                      <th style={{ textAlign: "right" }}>First-year payment</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.methods.map((m) => (
                      <tr key={m.method} style={{ fontWeight: m.method === method ? 600 : 400 }}>
                        <td>{METHODS.find((x) => x.value === m.method)?.label ?? m.method}</td>
                        <td style={{ textAlign: "right" }}>{fullCurrency(m.first_year_amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {preview.custom && (
                <div
                  role={preview.custom.qualifies ? "status" : "alert"}
                  style={preview.custom.qualifies ? helpTextStyle : warningStyle}
                >
                  {preview.custom.message} Approved fixed-amortization payment at this rate:{" "}
                  {fullCurrency(preview.custom.approved_amount)}.
                </div>
              )}
              {selectedPreview && (
                <details>
                  <summary style={{ cursor: "pointer", fontSize: 13 }}>
                    Illustrative schedule for{" "}
                    {METHODS.find((x) => x.value === method)?.label.toLowerCase()}
                  </summary>
                  <p style={helpTextStyle}>
                    Assumes the balance earns the interest rate above. The projection uses the
                    plan's actual return assumptions and stops if the account is exhausted.
                  </p>
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", fontSize: 13 }}>
                      <thead>
                        <tr>
                          <th>Year</th>
                          <th>Age</th>
                          <th style={{ textAlign: "right" }}>Payment</th>
                          <th style={{ textAlign: "right" }}>Remaining</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedPreview.schedule.map((row) => (
                          <tr key={row.age}>
                            <td>{row.year ?? "—"}</td>
                            <td>{row.age}</td>
                            <td style={{ textAlign: "right" }}>{fullCurrency(row.withdrawal)}</td>
                            <td style={{ textAlign: "right" }}>{fullCurrency(row.remaining)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}
              <details>
                <summary style={{ cursor: "pointer", fontSize: 13 }}>
                  Rules and limitations applied
                </summary>
                <ul
                  style={{
                    margin: "6px 0 0",
                    paddingLeft: 18,
                    fontSize: 12,
                    color: "var(--text-secondary)",
                  }}
                >
                  {preview.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                  <li>
                    Ages are the plan holder's; a partner-owned account is not separately aged.
                  </li>
                </ul>
              </details>
            </div>
          )}
        </fieldset>
      )}

      {saveError && (
        <div role="alert" style={warningStyle}>
          {saveError}
        </div>
      )}
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <button type="button" onClick={() => void handleSave()} disabled={!canSave || saving}>
          {saving ? "Saving…" : "Save SEPP settings"}
        </button>
        {saved && (
          <span role="status" style={{ fontSize: 13 }}>
            SEPP settings saved.
          </span>
        )}
      </div>
    </div>
  );
};

export default SEPPCalculator;

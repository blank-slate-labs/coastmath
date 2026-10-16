import { useState } from "react";

import { extensions } from "@/extensions";
import { GoalsIntakeForm, type SetupNext } from "@/components/goals_intake_form";
import { usePlanStore } from "@/stores/plan_store";
import { InlineValidity } from "@/components/inline_validity";
import {
  EARLIEST_BIRTH_YEAR,
  addBtnStyle,
  filingStatuses,
  formGridStyle,
  sectionStyle,
  usStates,
} from "@/pages/plan_setup_shared";
import type { FilingStatus, PlanData } from "@/types/plan";

/**
 * `next` is what setup asks for after the goals; the caller opens it. `clientId`
 * puts the plan in that client's workspace instead of the default one.
 */
export function CreatePlanForm({
  onCreate,
  onGoals,
  clientId,
}: {
  onCreate: (next?: SetupNext) => void;
  onGoals?: (plan: PlanData) => void;
  clientId?: string;
}) {
  const [mode, setMode] = useState("empty");
  const [created, setCreated] = useState<PlanData | null>(null);
  const imports = extensions.planner?.imports ?? [];
  // The new plan asks for goals before it opens; it exists by then, so the import choices go.
  if (created) return <GoalsIntakeForm plan={created} onDone={onCreate} />;
  const empty = (
    <EmptyPlanForm
      clientId={clientId}
      onCreate={onCreate}
      onCreated={(plan) => {
        setCreated(plan);
        onGoals?.(plan);
      }}
    />
  );
  // Imports always create the plan in the default workspace, so a client's plan starts empty.
  if (!imports.length || clientId) return empty;
  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 20 }}>
        <button
          type="button"
          className="btn-secondary"
          aria-pressed={mode === "empty"}
          onClick={() => setMode("empty")}
        >
          Start empty
        </button>
        {imports.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            className="btn-secondary"
            aria-pressed={mode === key}
            onClick={() => setMode(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {imports.map(({ key, Form }) => (
        <div key={key} hidden={mode !== key}>
          <Form onCreate={onCreate} />
        </div>
      ))}
      {mode === "empty" && empty}
    </div>
  );
}

// A salary needs a retirement milestone to end at; new plans start with one.
const DEFAULT_RETIREMENT_AGE = 65;
// The state select's "None" choice, which saves no state. The placeholder's value is
// empty, so a required select refuses it.
const NO_STATE = "__none";

function EmptyPlanForm({
  onCreate,
  onCreated,
  clientId,
}: {
  onCreate: (next?: SetupNext) => void;
  onCreated: (plan: PlanData) => void;
  clientId?: string;
}) {
  const createPlan = usePlanStore((s) => s.createPlan);
  const [name, setName] = useState("My Plan");
  // Birth year and state are asked, never assumed: a forgotten state would silently zero state tax.
  const [birthYear, setBirthYear] = useState("");
  const [filingStatus, setFilingStatus] = useState<FilingStatus>("single");
  // A partner defaults the return to joint until a status is picked by hand.
  const [filingPicked, setFilingPicked] = useState(false);
  const [stateCode, setStateCode] = useState<string | null>(null);
  const [partner, setPartner] = useState(false);
  const [partnerName, setPartnerName] = useState("");
  const [partnerBirthYear, setPartnerBirthYear] = useState("");
  const [saving, setSaving] = useState(false);
  const error = usePlanStore((s) => s.error);
  const incomplete = !name.trim() || (partner && !partnerBirthYear.trim());

  function togglePartner(on: boolean) {
    setPartner(on);
    if (!filingPicked) setFilingStatus(on ? "married_filing_jointly" : "single");
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (saving || incomplete) return;
    setSaving(true);
    await createPlan({
      name: name.trim(),
      birth_year: Number(birthYear),
      filing_status: filingStatus,
      ...(stateCode ? { state_code: stateCode } : {}),
      ...(partner
        ? {
            spouse: { name: partnerName.trim() || "Partner", birth_year: Number(partnerBirthYear) },
          }
        : {}),
      retirement_milestone_age: DEFAULT_RETIREMENT_AGE,
      ...(clientId ? { client_id: clientId } : {}),
    });
    setSaving(false);
    const { error: createError, plan } = usePlanStore.getState();
    if (createError) return;
    if (plan) onCreated(plan);
    else onCreate();
  }

  return (
    <InlineValidity>
      <form onSubmit={handleSubmit} style={sectionStyle}>
        <div style={formGridStyle}>
          <label>
            Plan name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={255}
            />
          </label>
          <label>
            Birth year
            <input
              type="number"
              min={EARLIEST_BIRTH_YEAR}
              max={new Date().getFullYear()}
              value={birthYear}
              onChange={(e) => setBirthYear(e.target.value)}
              required
            />
          </label>
          <label>
            Filing status
            <select
              value={filingStatus}
              onChange={(e) => {
                setFilingPicked(true);
                setFilingStatus(e.target.value as FilingStatus);
              }}
            >
              {filingStatuses.map((status) => (
                <option key={status.value} value={status.value}>
                  {status.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            State
            <select
              value={stateCode === null ? "" : stateCode || NO_STATE}
              required
              onChange={(e) =>
                setStateCode(e.target.value === NO_STATE ? "" : e.target.value || null)
              }
            >
              <option value="" disabled>
                Choose a state
              </option>
              {usStates.map((state) => (
                <option key={state.value || NO_STATE} value={state.value || NO_STATE}>
                  {state.label}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={partner}
              onChange={(e) => togglePartner(e.target.checked)}
            />
            Planning with a partner
          </label>
          {partner && (
            <>
              <label>
                Partner name
                <input
                  value={partnerName}
                  onChange={(e) => setPartnerName(e.target.value)}
                  placeholder="Partner"
                  maxLength={255}
                />
              </label>
              <label>
                Partner birth year
                <input
                  type="number"
                  min={EARLIEST_BIRTH_YEAR}
                  max={new Date().getFullYear()}
                  value={partnerBirthYear}
                  onChange={(e) => setPartnerBirthYear(e.target.value)}
                  required
                />
              </label>
            </>
          )}
          {error && <p role="alert">{error}</p>}
          <button
            type="submit"
            disabled={saving || incomplete}
            style={{ ...addBtnStyle, minHeight: 42 }}
          >
            {saving ? "Creating…" : "Create plan"}
          </button>
        </div>
      </form>
    </InlineValidity>
  );
}

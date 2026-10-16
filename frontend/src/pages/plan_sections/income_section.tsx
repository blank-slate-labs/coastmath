import { useEffect, useState } from "react";

import { FormModal } from "@/components/form_modal";
import IncomeForm from "@/components/income_form";
import { useSetupFlow } from "@/stores/setup_flow_store";
import { usCoverage } from "@/domain/intl_plan";
import { PARTNER_LABEL } from "@/domain/person_labels";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import { formatIncomePerPeriod } from "@/utils/amount_frequency";
import { useFailedSaveGuard } from "@/components/use_failed_save_guard";
import { confirmDelete } from "@/components/confirm_dialog";
import SaveErrorNotice from "@/components/save_error_notice";
import { ScenarioBadge } from "@/components/scenario/scenario_badge";
import {
  CollapsibleSection,
  EmptyState,
  actionBtnStyle,
  addBtnStyle,
  deleteBtnStyle,
} from "@/pages/plan_setup_shared";
import {
  actionGroupStyle,
  compactCurrency,
  itemDetailStyle,
  itemNameStyle,
  itemStackStyle,
  listItemStyle,
} from "@/pages/plan_sections/shared";
import type { Income, IncomeCreate } from "@/types/plan";

/** Compare saved income fields in their semantic default representation. */
function comparableIncomeField(key: string, value: unknown): unknown {
  if (key === "frequency") return value ?? "recurring";
  if (key === "recurrence_years") return value ?? null;
  if (key === "growth_schedule") {
    const rows = (value as Income["growth_schedule"]) ?? [];
    return rows.length === 0
      ? null
      : JSON.stringify(
          rows.map((row) => [
            row.start_year,
            row.end_year ?? null,
            row.kind,
            row.value,
            row.dollars ?? null,
          ]),
        );
  }
  if (key === "ex_spouse") {
    const record = value as Income["ex_spouse"];
    if (record == null) return null;
    return JSON.stringify([
      record.pia_monthly,
      record.birth_year,
      record.birth_month ?? 1,
      record.marriage_years ?? null,
      record.marriage_lasted_10_years ?? false,
      record.divorce_year,
      record.divorce_month ?? null,
      record.claim_age ?? null,
      record.death_year ?? null,
      record.current_marriage_year ?? null,
      record.survivor_claim_age ?? null,
    ]);
  }
  if (key !== "pension_formula") return value;
  if (value == null) return null;
  const formula = value as NonNullable<Income["pension_formula"]>;
  return JSON.stringify({
    kind: formula.kind,
    ...(formula.kind === "flat"
      ? { flat_annual_amount: formula.flat_annual_amount }
      : {
          linked_income_id: formula.linked_income_id,
          benefit_percent_per_year: formula.benefit_percent_per_year ?? 0,
          years_of_service_before_plan: formula.years_of_service_before_plan ?? 0,
          ...(formula.kind === "final_average"
            ? { final_average_years: formula.final_average_years ?? 3 }
            : {}),
        }),
    cola_percent: formula.cola_percent ?? null,
  });
}

export function IncomeSection() {
  const plan = usePlanStore((s) => s.plan);
  const outcomes = usePlanStore((s) => s.simulation?.metadata.milestone_outcomes ?? null);
  const addIncome = usePlanStore((s) => s.addIncome);
  const updateIncome = usePlanStore((s) => s.updateIncome);
  const deleteIncome = usePlanStore((s) => s.deleteIncome);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Income | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const saveKey = editing
    ? `put /plans/${plan?.id}/incomes/${editing.id}`
    : `post /plans/${plan?.id}/incomes`;
  const closeForm = useFailedSaveGuard(saveKey, saving, saveError, () => {
    setShowForm(false);
    setEditing(null);
    setSaveError(null);
  });

  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // New-plan setup hands over here once: the salary comes after the goals.
  const takeAddIncome = useSetupFlow((s) => s.takeAddIncome);
  useEffect(() => {
    if (plan?.id && takeAddIncome(plan.id)) setShowForm(true);
  }, [plan?.id, takeAddIncome]);

  if (!plan) return null;
  const currentPlan = plan;

  async function handleDelete(id: string) {
    if (
      !(await confirmDelete(
        currentPlan.income_streams.find((income) => income.id === id)?.name ?? "this income",
      ))
    )
      return;
    setDeleting(true);
    setDeleteError(null);
    const deleted = await deleteIncome(currentPlan.id, id);
    if (deleted === false)
      setDeleteError(usePlanStore.getState().error ?? "Could not delete income. Try again.");
    setDeleting(false);
  }

  async function handleSubmit(data: IncomeCreate) {
    setSaving(true);
    setSaveError(null);
    let saved = true;
    if (editing) {
      // Compare with the record captured when this form opened. Sending the
      // entire stale form would overwrite another tab's unrelated saved edit.
      const changes = Object.fromEntries(
        Object.entries(data).filter(
          ([key, value]) =>
            comparableIncomeField(key, value) !==
            comparableIncomeField(key, editing[key as keyof Income]),
        ),
      ) as Partial<IncomeCreate>;
      if (Object.keys(changes).length > 0) {
        saved = await updateIncome(currentPlan.id, editing.id, changes);
      }
    } else {
      saved = await addIncome(currentPlan.id, data);
    }
    setSaving(false);
    if (saved === false) {
      setSaveError(
        useSaveStore.getState().failures[saveKey]?.message ??
          usePlanStore.getState().error ??
          "Could not save income. Your edits are retained; retry when ready.",
      );
      return;
    }
    useSaveStore.getState().discardRejected(saveKey);
    setShowForm(false);
    setEditing(null);
  }

  return (
    <CollapsibleSection
      title="Income streams"
      count={currentPlan.income_streams.length}
      defaultOpen={false}
      action={
        !showForm && !editing ? (
          <button
            className="btn-ghost plan-add-btn"
            style={addBtnStyle}
            onClick={() => setShowForm(true)}
          >
            <span style={{ fontSize: "15px", lineHeight: 1 }}>+</span> Add income
          </button>
        ) : undefined
      }
    >
      {deleteError && <p role="alert">{deleteError}</p>}
      {currentPlan.income_streams.length === 0 && !showForm && !editing && (
        <EmptyState message="No income streams configured yet." />
      )}

      {currentPlan.income_streams.map((income) => (
        <div key={income.id} className="plan-list-item" style={listItemStyle}>
          <span style={itemStackStyle}>
            <span style={itemNameStyle}>
              {income.name}
              {income.is_active === false && (
                <>
                  {" "}
                  <span className="pill">Excluded</span>
                </>
              )}
              <ScenarioBadge rowId={income.id} />
            </span>
            <span style={itemDetailStyle}>
              {income.is_social_security &&
              income.ss_benefit_basis === "pia" &&
              income.pia_monthly != null
                ? `PIA ${compactCurrency.format(income.pia_monthly)}/mo${income.claiming_age != null ? ` at ${income.claiming_age}` : ""}`
                : formatIncomePerPeriod(income, compactCurrency.format)}
              {income.is_social_security
                ? income.growth_rate != null && income.growth_rate !== 0
                  ? ` (${income.growth_rate}% growth)`
                  : " (inflation COLA)"
                : income.growth_rate != null && ` (${income.growth_rate}% growth)`}
              {income.growth_cap != null &&
                ` · cap ${compactCurrency.format(income.growth_cap)}${income.growth_cap_inflation_linked ? " real" : ""}`}
              {income.withholding_percent != null &&
                income.withholding_percent > 0 &&
                ` · ${income.withholding_percent}% withheld`}
              {income.is_self_employed && " · self-employed"}
              {income.owner === "spouse" && ` · ${PARTNER_LABEL}`}
            </span>
          </span>
          <span style={actionGroupStyle}>
            <button
              className="plan-action-btn"
              style={actionBtnStyle}
              onClick={() => setEditing(income)}
              data-sample-view
            >
              Edit
            </button>
            <button
              className="plan-delete-btn"
              style={deleteBtnStyle}
              disabled={deleting}
              onClick={() => void handleDelete(income.id)}
            >
              Delete
            </button>
          </span>
        </div>
      ))}

      <FormModal
        open={showForm || editing !== null}
        onClose={closeForm}
        title={editing ? "Edit Income" : "Add Income"}
      >
        <SaveErrorNotice message={saveError} />
        <fieldset
          disabled={saving}
          data-save-pending={saving || undefined}
          style={{ border: 0, padding: 0, minWidth: 0 }}
        >
          <IncomeForm
            initial={editing ?? undefined}
            milestones={currentPlan.milestones}
            incomes={currentPlan.income_streams}
            birthYear={currentPlan.birth_year}
            spouseBirthYear={currentPlan.spouse?.birth_year ?? null}
            outcomes={outcomes}
            hasPartner={!!currentPlan.spouse}
            planType={currentPlan.plan_type}
            usCoverage={usCoverage(currentPlan)}
            onSubmit={handleSubmit}
            onCancel={closeForm}
          />
        </fieldset>
        {saving && <p>Saving…</p>}
      </FormModal>
    </CollapsibleSection>
  );
}

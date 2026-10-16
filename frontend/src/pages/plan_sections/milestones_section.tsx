import { useState } from "react";

import { FormModal } from "@/components/form_modal";
import MilestoneForm, { isPartnerRetirement } from "@/components/milestone_form";
import { MilestoneLinks } from "@/components/milestone_links";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import { useFiEstimateHidden, useFiEstimateStore } from "@/stores/fi_estimate_store";
import {
  FI_ESTIMATE_LABEL,
  FI_ESTIMATE_PRESET,
  FI_MULTIPLE,
  financialIndependence,
  ownFiMilestone,
} from "@/utils/financial_independence";
import { usePlanAccounts } from "@/utils/use_plan_accounts";
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
import type { Milestone, MilestoneCreate } from "@/types/plan";

/** `birthYearGap` is the partner's birth year minus the primary person's, when both are known. */
function describeMilestoneTrigger(
  m: Milestone,
  all: Milestone[],
  birthYearGap: number | null,
): string {
  switch (m.trigger_type) {
    case "age":
      // A Partner retirement fires on the primary person's age; show the partner's.
      if (birthYearGap != null && isPartnerRetirement(m))
        return `partner's age ${m.trigger_value! - birthYearGap}`;
      return `age ${m.trigger_value ?? "?"}`;
    case "date":
      return `on ${m.trigger_date ?? "?"}`;
    case "net_worth":
      return `net worth ≥ ${m.trigger_value != null ? compactCurrency.format(m.trigger_value) : "?"}`;
    case "expense_multiple":
      return `${m.expense_multiple ?? m.trigger_value ?? "?"}× expenses (${m.metric === "net_worth" ? "total net worth" : "liquid"})`;
    case "conditions":
      return `${m.conditions?.combinator === "any" ? "Any" : "All"} of ${m.conditions?.items.length ?? 0} conditions`;
    case "relative": {
      const ref = all.find((x) => x.id === m.relative_to_id)?.name ?? "missing milestone";
      const offset = m.offset_years ?? 0;
      return `${offset === 0 ? "same year as" : `${Math.abs(offset)} yr${Math.abs(offset) === 1 ? "" : "s"} ${offset > 0 ? "after" : "before"}`} ${ref}`;
    }
    default:
      return m.trigger_type;
  }
}

export function MilestonesSection() {
  const plan = usePlanStore((s) => s.plan);
  const simulation = usePlanStore((s) => s.simulation);
  const addMilestone = usePlanStore((s) => s.addMilestone);
  const updateMilestone = usePlanStore((s) => s.updateMilestone);
  const deleteMilestone = usePlanStore((s) => s.deleteMilestone);
  const fiEstimateHidden = useFiEstimateHidden(plan?.id);
  const setFiEstimateHidden = useFiEstimateStore((s) => s.setHidden);

  const { adapter } = useStorage();
  const { accounts } = usePlanAccounts(adapter, plan?.id);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Milestone | null>(null);
  const [preset, setPreset] = useState<MilestoneCreate | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const saveKey = editing
    ? `put /plans/${plan?.id}/milestones/${editing.id}`
    : `post /plans/${plan?.id}/milestones`;
  const closeForm = useFailedSaveGuard(saveKey, saving, saveError, () => {
    setShowForm(false);
    setEditing(null);
    setPreset(null);
    setSaveError(null);
  });
  if (!plan) return null;
  const currentPlan = plan;
  // The CoastMath FI estimate is listed as a built-in milestone until the user
  // removes it or creates their own FI milestone, which replaces it.
  const hasOwnFi = ownFiMilestone(currentPlan) !== null;
  const showEstimate = !hasOwnFi && !fiEstimateHidden;
  const estimate = showEstimate ? financialIndependence(simulation) : null;
  const estimateYear = estimate?.snapshot?.year ?? null;

  async function handleSubmit(data: MilestoneCreate) {
    setSaving(true);
    setSaveError(null);
    usePlanStore.setState({ error: null });
    if (editing) await updateMilestone(currentPlan.id, editing.id, data);
    else await addMilestone(currentPlan.id, data);
    const failure = usePlanStore.getState().error;
    setSaving(false);
    if (failure) {
      setSaveError(failure);
      return;
    }
    setShowForm(false);
    setEditing(null);
    setPreset(null);
  }

  return (
    <CollapsibleSection
      title="Milestones"
      count={currentPlan.milestones.length + (showEstimate ? 1 : 0)}
      defaultOpen={false}
      action={
        !showForm && !editing && !preset ? (
          <button
            className="btn-ghost plan-add-btn"
            style={addBtnStyle}
            onClick={() => setShowForm(true)}
          >
            <span style={{ fontSize: "15px", lineHeight: 1 }}>+</span> Add milestone
          </button>
        ) : undefined
      }
    >
      {currentPlan.milestones.length === 0 && !showEstimate && !showForm && !editing && !preset && (
        <EmptyState message="No milestones yet." />
      )}

      {showEstimate && (
        <div
          className="plan-list-item"
          style={listItemStyle}
          data-testid="fi-estimate-milestone"
          title="Calculated by CoastMath. Edit to make it your own milestone; remove to hide it for this plan."
        >
          <span style={itemStackStyle}>
            <span style={itemNameStyle}>{FI_ESTIMATE_LABEL}</span>
            <span style={itemDetailStyle}>
              {`${estimate?.multiple ?? FI_MULTIPLE}× expenses (liquid)`}
              {simulation?.metadata.fi_estimate &&
                (estimateYear == null
                  ? " · not reached in projection"
                  : ` · reached ${estimateYear}`)}
              {" · automatic"}
            </span>
          </span>
          <span style={actionGroupStyle}>
            <button
              className="plan-action-btn"
              style={actionBtnStyle}
              onClick={() => setPreset(FI_ESTIMATE_PRESET)}
              data-sample-view
            >
              Edit
            </button>
            <button
              className="plan-delete-btn"
              style={deleteBtnStyle}
              onClick={() => setFiEstimateHidden(currentPlan.id, true)}
            >
              Remove
            </button>
          </span>
        </div>
      )}

      {currentPlan.milestones.map((milestone) => (
        <div
          key={milestone.id}
          className="plan-list-item"
          style={milestone.is_active === false ? { ...listItemStyle, opacity: 0.6 } : listItemStyle}
        >
          <span style={itemStackStyle}>
            <span style={itemNameStyle}>
              {milestone.name}
              {milestone.is_active === false && " (inactive)"}
              <ScenarioBadge rowId={milestone.id} />
            </span>
            <span style={itemDetailStyle}>
              {describeMilestoneTrigger(
                milestone,
                currentPlan.milestones,
                currentPlan.spouse?.birth_year != null
                  ? currentPlan.spouse.birth_year - currentPlan.birth_year
                  : null,
              )}
              {(() => {
                if (milestone.is_active === false) return " · switched off, never fires";
                const outcome = simulation?.metadata.milestone_outcomes?.find(
                  (o) => o.id === milestone.id,
                );
                if (!outcome) return null;
                if (outcome.missed_year != null) return ` · missed deadline ${outcome.missed_year}`;
                if (outcome.year == null) return " · not reached in projection";
                const startYear = simulation?.metadata.start_year ?? outcome.year;
                return outcome.year < startYear
                  ? ` · reached ${outcome.year}, before the plan starts in ${startYear}; already in effect`
                  : ` · reached ${outcome.year}`;
              })()}
            </span>
          </span>
          <span style={actionGroupStyle}>
            <button
              className="plan-action-btn"
              style={actionBtnStyle}
              onClick={() => setEditing(milestone)}
              data-sample-view
            >
              Edit
            </button>
            <button
              className="plan-delete-btn"
              style={deleteBtnStyle}
              onClick={() =>
                void confirmDelete(milestone.name).then((confirmed) => {
                  if (confirmed) void deleteMilestone(currentPlan.id, milestone.id);
                })
              }
            >
              Delete
            </button>
          </span>
        </div>
      ))}

      {!hasOwnFi && fiEstimateHidden && (
        <button
          type="button"
          className="btn-ghost"
          style={addBtnStyle}
          onClick={() => setFiEstimateHidden(currentPlan.id, false)}
        >
          Restore the CoastMath financial independence estimate
        </button>
      )}

      <FormModal
        open={showForm || editing !== null || preset !== null}
        onClose={closeForm}
        title={
          editing
            ? "Edit Milestone"
            : preset
              ? "Make the FI estimate your milestone"
              : "Add Milestone"
        }
      >
        <SaveErrorNotice message={saveError} />
        <fieldset
          disabled={saving}
          data-save-pending={saving || undefined}
          style={{ border: 0, padding: 0, minWidth: 0 }}
        >
          <MilestoneForm
            accounts={accounts}
            milestones={currentPlan.milestones}
            birthYear={currentPlan.birth_year}
            spouseBirthYear={currentPlan.spouse?.birth_year ?? null}
            initial={editing ?? undefined}
            preset={preset ?? undefined}
            onSubmit={handleSubmit}
            onCancel={closeForm}
          >
            {editing && <MilestoneLinks plan={currentPlan} milestoneId={editing.id} />}
          </MilestoneForm>
        </fieldset>
        {saving && <p>Saving…</p>}
      </FormModal>
    </CollapsibleSection>
  );
}

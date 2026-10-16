import { useEffect, useRef, useState } from "react";

import ExpenseForm from "@/components/expense_form";
import { FormModal } from "@/components/form_modal";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import { formatPerPeriod } from "@/utils/amount_frequency";
import { flexibleLabel } from "@/utils/discretionary_share";
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
import type { Expense, ExpenseCreate } from "@/types/plan";

export function ExpenseSection() {
  const plan = usePlanStore((s) => s.plan);
  const outcomes = usePlanStore((s) => s.simulation?.metadata.milestone_outcomes ?? null);
  const addExpense = usePlanStore((s) => s.addExpense);
  const updateExpense = usePlanStore((s) => s.updateExpense);
  const deleteExpense = usePlanStore((s) => s.deleteExpense);
  const { adapter } = useStorage();
  const { accounts } = usePlanAccounts(adapter, plan?.id);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Expense | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState<ExpenseCreate | null>(null);
  const [review, setReview] = useState<Expense | null>(null);
  const reviewPanel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (review) reviewPanel.current?.focus();
  }, [review]);
  const [formVersion, setFormVersion] = useState(0);
  const saveKey = editing
    ? `put /plans/${plan?.id}/expenses/${editing.id}`
    : `post /plans/${plan?.id}/expenses`;
  const closeForm = useFailedSaveGuard(saveKey, saving, saveError, () => {
    setShowForm(false);
    setEditing(null);
    setSaveError(null);
    setReview(null);
    setSubmitted(null);
  });

  if (!plan) return null;
  const currentPlan = plan;

  async function handleSubmit(data: ExpenseCreate, reviewed?: Expense) {
    setSaving(true);
    setSaveError(null);
    setSubmitted(data);
    setReview(null);
    let saved = true;
    if (editing) {
      // Use the opening snapshot, as IncomeSection does, to preserve edits
      // another tab saved to fields this form did not change.
      const changes = Object.fromEntries(
        Object.entries(data).filter(([key, value]) => value !== editing[key as keyof Expense]),
      ) as Partial<ExpenseCreate>;
      if (Object.keys(changes).length > 0) {
        const baseline = reviewed ?? editing;
        const expected_values = Object.fromEntries(
          Object.keys(changes).map((key) => [key, baseline[key as keyof Expense] ?? null]),
        );
        saved = await updateExpense(currentPlan.id, editing.id, { ...changes, expected_values });
      }
    } else {
      saved = await addExpense(currentPlan.id, data);
    }
    setSaving(false);
    if (saved === false) {
      setSaveError(
        useSaveStore.getState().failures[saveKey]?.message ??
          usePlanStore.getState().error ??
          "Could not save expense. Your edits are retained; retry when ready.",
      );
      return;
    }
    useSaveStore.getState().discardRejected(saveKey);
    setShowForm(false);
    setEditing(null);
    setSubmitted(null);
  }

  async function reviewSaved(data: ExpenseCreate) {
    if (!editing || saving) return;
    setSubmitted(data);
    setSaving(true);
    try {
      const latest = (await adapter.listExpenses(currentPlan.id)).find(
        (item) => item.id === editing.id,
      );
      if (!latest) {
        setSaveError(
          `Expense “${editing.name}” in “${currentPlan.name}” is no longer available. Your draft is retained. Close this editor only when you are ready to discard it.`,
        );
      } else {
        setReview(latest);
      }
    } catch {
      setSaveError(
        `Could not check saved values for expense “${editing.name}” in “${currentPlan.name}”. Your draft is retained; check your connection and choose Review latest saved values again.`,
      );
    } finally {
      setSaving(false);
    }
  }

  function reviewValue(key: string, value: unknown): string {
    if (value == null) return "Not set";
    if (key.endsWith("_id"))
      return (
        [...currentPlan.milestones, ...currentPlan.income_streams, ...accounts].find(
          (item) => item.id === value,
        )?.name ?? "Unavailable linked item"
      );
    if (typeof value === "boolean") return value ? "Yes" : "No";
    return String(value);
  }

  return (
    <CollapsibleSection
      title="Expenses"
      count={currentPlan.expenses.length}
      defaultOpen={false}
      action={
        !showForm && !editing ? (
          <button
            className="btn-ghost plan-add-btn"
            style={addBtnStyle}
            onClick={() => setShowForm(true)}
          >
            <span style={{ fontSize: "15px", lineHeight: 1 }}>+</span> Add expense
          </button>
        ) : undefined
      }
    >
      {currentPlan.expenses.length === 0 && !showForm && !editing && (
        <EmptyState message="No expenses yet." />
      )}

      {currentPlan.expenses.map((expense) => (
        <div key={expense.id} className="plan-list-item" style={listItemStyle}>
          <span style={{ ...itemStackStyle, gap: 8 }}>
            <span style={itemNameStyle}>
              {expense.name}
              <ScenarioBadge rowId={expense.id} />
            </span>
            <span style={itemDetailStyle}>
              {/* A repeating charge is one yearly amount every few years, so it stays annual. */}
              {expense.recurrence_years != null
                ? `${compactCurrency.format(expense.annual_amount)} every ${expense.recurrence_years} yr${expense.recurrence_years === 1 ? "" : "s"}`
                : formatPerPeriod(
                    expense.annual_amount,
                    expense.amount_frequency,
                    compactCurrency.format,
                  )}
              {expense.growth_rate != null
                ? ` (${expense.growth_rate}% growth${expense.growth_cap != null ? `, cap ${compactCurrency.format(expense.growth_cap)}${expense.growth_cap_inflation_linked ? " real" : ""}` : ""})`
                : expense.inflation_linked
                  ? " (inflation-linked)"
                  : " (fixed)"}
              {expense.recurrence_years != null && expense.recurrence_growth_rate
                ? ` · ${expense.recurrence_growth_rate > 0 ? "+" : ""}${expense.recurrence_growth_rate}% each time`
                : ""}
              {expense.is_payroll_deduction && " (payroll)"}
              {expense.specific_funding_source_id &&
                ` · from ${accounts.find((a) => a.id === expense.specific_funding_source_id)?.name ?? "specific account"}`}
            </span>
            {expense.category && (
              <span
                style={{
                  width: "fit-content",
                  display: "inline-flex",
                  alignItems: "center",
                  padding: "2px 8px",
                  borderRadius: 999,
                  border: "none",
                  background:
                    expense.category === "discretionary"
                      ? "var(--color-warning-light)"
                      : "var(--gray-100)",
                  color:
                    expense.category === "discretionary"
                      ? "var(--color-warning)"
                      : "var(--gray-500)",
                  fontSize: "11px",
                  fontWeight: 500,
                }}
              >
                {flexibleLabel(expense.discretionary_percent) ?? expense.category}
              </span>
            )}
          </span>
          <span style={actionGroupStyle}>
            <button
              className="plan-action-btn"
              style={actionBtnStyle}
              onClick={() => setEditing(expense)}
              data-sample-view
            >
              Edit
            </button>
            <button
              className="plan-delete-btn"
              style={deleteBtnStyle}
              onClick={() =>
                void confirmDelete(expense.name).then((confirmed) => {
                  if (confirmed) void deleteExpense(currentPlan.id, expense.id);
                })
              }
            >
              Delete
            </button>
          </span>
        </div>
      ))}

      <FormModal
        open={showForm || editing !== null}
        onClose={closeForm}
        title={editing ? "Edit Expense" : "Add Expense"}
      >
        <SaveErrorNotice message={saveError} />
        {review && submitted && editing && (
          <section
            ref={reviewPanel}
            tabIndex={-1}
            aria-label="Review expense changes"
            style={{ overflowWrap: "anywhere" }}
          >
            <p>
              Latest saved expense: “{review.name}” in “{currentPlan.name}”. Compare the fields you
              changed before submitting your draft again, then choose which values to keep.
            </p>
            <dl>
              {Object.entries(submitted)
                .filter(([key, value]) => value !== editing[key as keyof Expense])
                .map(([key, value]) => (
                  <div key={key}>
                    <dt>{key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}</dt>
                    <dd>Saved: {reviewValue(key, review[key as keyof Expense])}</dd>
                    <dd>Your draft: {reviewValue(key, value)}</dd>
                  </div>
                ))}
            </dl>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
              <button
                type="button"
                disabled={saving}
                onClick={() => handleSubmit(submitted, review)}
              >
                Save my reviewed changes
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={() => {
                  usePlanStore.setState((s) =>
                    s.plan?.id === currentPlan.id
                      ? {
                          plan: {
                            ...s.plan,
                            expenses: s.plan.expenses.map((item) =>
                              item.id === review.id ? review : item,
                            ),
                          },
                        }
                      : s,
                  );
                  void usePlanStore.getState().runSimulation(currentPlan.id);
                  setEditing(review);
                  setReview(null);
                  setSubmitted(null);
                  setSaveError(null);
                  setFormVersion((v) => v + 1);
                  useSaveStore.getState().discardRejected(saveKey);
                }}
              >
                Use saved version
              </button>
              <button type="button" disabled={saving} onClick={() => setReview(null)}>
                Back to my draft
              </button>
            </div>
          </section>
        )}
        <fieldset
          disabled={saving || review !== null}
          data-save-pending={saving || undefined}
          style={{ border: 0, padding: 0, minWidth: 0 }}
        >
          <ExpenseForm
            key={formVersion}
            onReview={saveError && editing ? reviewSaved : undefined}
            accounts={accounts}
            incomeStreams={currentPlan.income_streams}
            initial={editing ?? undefined}
            existingNames={currentPlan.expenses.map((expense) => expense.name)}
            milestones={currentPlan.milestones}
            birthYear={currentPlan.birth_year}
            outcomes={outcomes}
            onSubmit={handleSubmit}
            onCancel={closeForm}
          />
        </fieldset>
        {saving && <p>Saving…</p>}
      </FormModal>
    </CollapsibleSection>
  );
}

import { useState, useCallback } from "react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { usePlanStore } from "@/stores/plan_store";
import type { DrawdownEntry, DrawdownEntryCreate, Account } from "@/types/plan";

// ── Sortable item ─────────────────────────────────────────────────

interface SortableItemProps {
  entry: DrawdownEntry;
  rank: number;
  accountName: string;
  onDelete: (id: string) => void;
}

function SortableDrawdownItem({ entry, rank, accountName, onDelete }: SortableItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: entry.id });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "8px 12px",
    marginBottom: "4px",
    borderRadius: "6px",
    border: "1px solid var(--surface-border)",
    background: isDragging ? "var(--surface-sunken)" : "var(--surface-card)",
    opacity: isDragging ? 0.8 : 1,
    cursor: "default",
  };

  return (
    <div ref={setNodeRef} style={style}>
      <button
        type="button"
        ref={setActivatorNodeRef}
        {...attributes}
        {...listeners}
        style={{
          background: "none",
          border: "none",
          padding: "0 4px",
          cursor: "grab",
          fontSize: "16px",
          lineHeight: 1,
          userSelect: "none",
          color: "var(--text-tertiary)",
        }}
        aria-label={`Reorder ${accountName}`}
      >
        &#x2261;
      </button>

      <span
        style={{
          fontWeight: 600,
          minWidth: "24px",
          color: "var(--text-secondary)",
          fontSize: "13px",
        }}
      >
        {rank}
      </span>

      <span style={{ flex: 1, fontSize: "14px" }}>{accountName}</span>

      <button
        type="button"
        onClick={() => onDelete(entry.id)}
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          color: "var(--text-tertiary)",
          fontSize: "16px",
          padding: "0 4px",
          lineHeight: 1,
        }}
        aria-label={`Remove ${accountName}`}
      >
        &times;
      </button>
    </div>
  );
}

// ── Main editor ───────────────────────────────────────────────────

interface DrawdownEditorProps {
  planId: string;
  entries: DrawdownEntry[];
  accounts: Account[];
}

export default function DrawdownEditor({ planId, entries, accounts }: DrawdownEditorProps) {
  const updateDrawdownOrder = usePlanStore((s) => s.updateDrawdownOrder);
  const [selectedAccountId, setSelectedAccountId] = useState("");

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const accountMap = new Map(accounts.map((a) => [a.id, a.name]));

  const usedAccountIds = new Set(entries.map((e) => e.source_account_id).filter(Boolean));
  const availableAccounts = accounts.filter((a) => !usedAccountIds.has(a.id));

  const saveOrder = useCallback(
    (reordered: DrawdownEntry[]) => {
      const payload: DrawdownEntryCreate[] = reordered.map((e, i) => ({
        rank: i + 1,
        source_account_id: e.source_account_id,
      }));
      updateDrawdownOrder(planId, payload);
    },
    [planId, updateDrawdownOrder],
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const oldIndex = entries.findIndex((e) => e.id === active.id);
      const newIndex = entries.findIndex((e) => e.id === over.id);
      if (oldIndex === -1 || newIndex === -1) return;

      const reordered = arrayMove(entries, oldIndex, newIndex);
      saveOrder(reordered);
    },
    [entries, saveOrder],
  );

  const handleAdd = useCallback(() => {
    if (!selectedAccountId) return;

    const newEntry: DrawdownEntryCreate = {
      rank: entries.length + 1,
      source_account_id: selectedAccountId,
    };

    const payload: DrawdownEntryCreate[] = [
      ...entries.map((e, i) => ({
        rank: i + 1,
        source_account_id: e.source_account_id,
      })),
      newEntry,
    ];

    updateDrawdownOrder(planId, payload);
    setSelectedAccountId("");
  }, [selectedAccountId, entries, planId, updateDrawdownOrder]);

  const handleDelete = useCallback(
    (id: string) => {
      const remaining = entries.filter((e) => e.id !== id);
      saveOrder(remaining);
    },
    [entries, saveOrder],
  );

  return (
    <div>
      {entries.length === 0 && (
        <p
          style={{
            color: "var(--text-tertiary)",
            fontSize: "14px",
            margin: "0 0 12px",
          }}
        >
          No drawdown accounts configured. Add one below.
        </p>
      )}

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={entries.map((e) => e.id)} strategy={verticalListSortingStrategy}>
          {entries.map((entry, i) => (
            <SortableDrawdownItem
              key={entry.id}
              entry={entry}
              rank={i + 1}
              accountName={
                entry.source_account_id
                  ? (accountMap.get(entry.source_account_id) ?? "Unknown Account")
                  : "Unassigned"
              }
              onDelete={handleDelete}
            />
          ))}
        </SortableContext>
      </DndContext>

      {availableAccounts.length > 0 && (
        <div
          style={{
            display: "flex",
            gap: "8px",
            marginTop: "8px",
            alignItems: "center",
          }}
        >
          <select
            value={selectedAccountId}
            onChange={(e) => setSelectedAccountId(e.target.value)}
            style={{
              flex: 1,
              padding: "6px 8px",
              borderRadius: "4px",
              border: "1px solid var(--surface-border-strong)",
              fontSize: "14px",
            }}
          >
            <option value="">Select account...</option>
            {availableAccounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={handleAdd}
            disabled={!selectedAccountId}
            style={{
              padding: "6px 12px",
              borderRadius: "4px",
              border: "1px solid var(--surface-border-strong)",
              background: selectedAccountId ? "var(--brand-primary)" : "var(--surface-sunken)",
              color: selectedAccountId ? "var(--text-inverse)" : "var(--text-tertiary)",
              fontSize: "14px",
              cursor: selectedAccountId ? "pointer" : "default",
              whiteSpace: "nowrap",
            }}
          >
            Add Account
          </button>
        </div>
      )}
    </div>
  );
}

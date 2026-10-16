import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { PlanCreate } from "@/types/plan";

/** A form's contribution to its sheet's one Save: `build` throws an Error naming the first invalid input. */
export interface SaveGroupPart {
  build: () => Partial<PlanCreate>;
  dirty: boolean;
  /** The draft as built is now saved. */
  markSaved: () => void;
}

type Register = (id: string, part: SaveGroupPart | null) => void;
const SaveGroupContext = createContext<Register | null>(null);

/**
 * Joins a SaveGroup when rendered inside one. Returns whether it did: the form then
 * renders without its own form element, Save button and status line.
 */
export function useSaveGroupPart(id: string, part: SaveGroupPart): boolean {
  const register = useContext(SaveGroupContext);
  // Every render: `build` reads the latest draft.
  useEffect(() => {
    register?.(id, part);
  });
  useEffect(() => () => register?.(id, null), [register, id]);
  return register !== null;
}

/**
 * One form and one Save button for a sheet whose settings come from several
 * forms; the edited parts are saved together in one plan update.
 */
export function SaveGroup({
  label,
  onSave,
  children,
}: {
  label: string;
  onSave: (data: Partial<PlanCreate>) => Promise<void>;
  children: ReactNode;
}) {
  const parts = useRef(new Map<string, SaveGroupPart>());
  const [dirty, setDirty] = useState<ReadonlySet<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const register = useCallback<Register>((id, part) => {
    if (part) parts.current.set(id, part);
    else parts.current.delete(id);
    const isDirty = !!part?.dirty;
    setDirty((previous) => {
      if (previous.has(id) === isDirty) return previous;
      const next = new Set(previous);
      if (isDirty) next.add(id);
      else next.delete(id);
      return next;
    });
    if (isDirty) setSaved(false);
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    let data: Partial<PlanCreate> = {};
    const edited = [...dirty];
    try {
      for (const id of edited) data = { ...data, ...parts.current.get(id)?.build() };
    } catch (err) {
      setError((err as Error).message);
      return;
    }
    setSaving(true);
    try {
      await onSave(data);
      for (const id of edited) parts.current.get(id)?.markSaved();
      setSaved(true);
    } catch {
      setError("Could not save. Your edits are retained; try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      data-unsaved-changes={dirty.size > 0 || undefined}
      data-save-pending={saving || undefined}
      style={{ display: "grid", gap: 12 }}
    >
      <fieldset
        disabled={saving}
        style={{ border: 0, padding: 0, margin: 0, minWidth: 0, display: "grid", gap: 12 }}
      >
        <SaveGroupContext.Provider value={register}>{children}</SaveGroupContext.Provider>
        {error && (
          <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13 }}>
            {error}
          </div>
        )}
        <button type="submit" disabled={dirty.size === 0} style={{ justifySelf: "start" }}>
          {saving ? "Saving…" : label}
        </button>
      </fieldset>
      {saved && dirty.size === 0 && (
        <p role="status" style={{ margin: 0, fontSize: 13 }}>
          Saved.
        </p>
      )}
    </form>
  );
}

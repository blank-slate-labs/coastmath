import { create } from "zustand";

export interface SaveFailure {
  message: string;
  /** Only a definite rejection can be acknowledged by discarding a draft. */
  rejected: boolean;
}

interface SaveState {
  pending: number;
  failed: string[];
  lastSavedAt: number | null;
  /** The request key of the save confirmed at `lastSavedAt`. */
  lastSavedKey: string | null;
  failures: Record<string, SaveFailure>;
  latest: Record<string, number>;
  /** The one live region that announces save status: the page header, or the open editor's footer. */
  announcer: "header" | "sheet";
  begin: (key: string) => number;
  finish: (key: string, success: boolean, attempt: number, failure?: SaveFailure) => void;
  discardRejected: (key: string) => void;
  /** The user discarded this draft after being told to check saved values: drop its message, whatever the outcome. */
  acknowledge: (key: string) => void;
  /** Drafts were closed: a rejected save left nothing unsaved. Unconfirmed saves stay listed. */
  discardAllRejected: () => void;
  setAnnouncer: (announcer: "header" | "sheet") => void;
}

// Only persisted inputs count as saves; POST simulation/preview requests do not.
export function saveRequestKey(method?: string, url?: string): string | null {
  if (!["post", "put", "patch", "delete"].includes(method?.toLowerCase() ?? "")) return null;
  const path = url?.split("?")[0] ?? "";
  const persisted =
    /^\/(accounts|progress-points)(\/[^/]+)?$/.test(path) ||
    path === "/plans" ||
    /^\/plans\/[^/]+\/duplicate$/.test(path) ||
    (/^\/plans\/[^/]+$/.test(path) &&
      !["/plans/sepp-preview", "/plans/ss-estimate"].includes(path)) ||
    /^\/plans\/[^/]+\/(accounts|milestones|incomes|expenses|priorities|drawdown-order|assumptions|charities|real-assets|liabilities|tax-jurisdictions)(\/[^/]+)?$/.test(
      path,
    );
  return persisted ? `${method!.toLowerCase()} ${path}` : null;
}

let nextAttempt = 0;
export const useSaveStore = create<SaveState>()((set) => ({
  pending: 0,
  failed: [],
  lastSavedAt: null,
  lastSavedKey: null,
  failures: {},
  latest: {},
  announcer: "header",
  begin: (key) => {
    const attempt = ++nextAttempt;
    set((s) => ({ pending: s.pending + 1, latest: { ...s.latest, [key]: attempt } }));
    return attempt;
  },
  finish: (key, success, attempt, failure) =>
    set((s) => {
      const pending = Math.max(0, s.pending - 1);
      if (s.latest[key] !== attempt) return { pending };
      const failures = { ...s.failures };
      if (success) delete failures[key];
      else
        failures[key] = failure ?? {
          message: "A save could not be confirmed. Check the saved item before retrying.",
          rejected: false,
        };
      return {
        pending,
        failures,
        failed: success
          ? s.failed.filter((item) => item !== key)
          : [...new Set([...s.failed, key])],
        lastSavedAt: success ? Date.now() : s.lastSavedAt,
        lastSavedKey: success ? key : s.lastSavedKey,
      };
    }),
  discardRejected: (key) =>
    set((s) => {
      if (!s.failures[key]?.rejected) return s;
      const failures = { ...s.failures };
      delete failures[key];
      return { failures, failed: s.failed.filter((item) => item !== key) };
    }),
  acknowledge: (key) =>
    set((s) => {
      if (!s.failures[key]) return s;
      const failures = { ...s.failures };
      delete failures[key];
      return { failures, failed: s.failed.filter((item) => item !== key) };
    }),
  discardAllRejected: () =>
    set((s) => {
      const rejected = s.failed.filter((key) => s.failures[key]?.rejected);
      if (!rejected.length) return s;
      const failures = { ...s.failures };
      for (const key of rejected) delete failures[key];
      return { failures, failed: s.failed.filter((key) => !rejected.includes(key)) };
    }),
  setAnnouncer: (announcer) => set({ announcer }),
}));

export function failedSaveText(state: Pick<SaveState, "failed" | "failures">): string {
  return state.failed
    .map(
      (key) =>
        state.failures[key]?.message ??
        "A save could not be confirmed. Open the affected item and check saved values before retrying.",
    )
    .join(" ");
}

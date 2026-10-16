import { api } from "./client";

/** Optional LLM category suggestions (backend `app/routers/ledger_suggestions.py`). */
export interface SuggestionRun {
  status: "suggested" | "nothing_pending" | "failed";
  suggested: number;
  sent: number;
  message: string | null;
  finished_at: string | null;
}
/** `pending` is null when the deployment offers no suggestions. */
export interface SuggestionStatus {
  offered: boolean;
  running: boolean;
  pending: number | null;
  last_run: SuggestionRun | null;
}

const path = "/ledger/suggestions";
export const ledgerSuggestions = {
  status: (): Promise<SuggestionStatus> => api.get(`${path}/status`).then((r) => r.data),
  run: (): Promise<SuggestionStatus> => api.post(`${path}/run`).then((r) => r.data),
};

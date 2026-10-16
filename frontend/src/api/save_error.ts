import type { PlanData } from "@/types/plan";
import type { SaveFailure } from "@/stores/save_store";
import { extensions } from "@/extensions";

const labels: Record<string, string> = {
  incomes: "income",
  expenses: "expense",
  accounts: "account",
  milestones: "milestone",
  priorities: "income allocation",
  assumptions: "assumption",
  "drawdown-order": "drawdown order",
  "real-assets": "property",
  liabilities: "debt",
  charities: "charity",
  "tax-jurisdictions": "tax settings",
  "progress-points": "progress entry",
};

export function saveAction(
  method: string | undefined,
  url: string | undefined,
  data: unknown,
  plan: PlanData | null,
): string {
  const parts = (url ?? "").split("?")[0].split("/").filter(Boolean);
  const planScoped = parts[0] === "plans" && parts.length > 1;
  const samePlan = planScoped && parts[1] === plan?.id;
  const resource = planScoped ? parts[2] : parts[0];
  const id = planScoped ? parts[3] : parts[1];
  const items = samePlan
    ? resource === "incomes"
      ? plan.income_streams
      : resource === "expenses"
        ? plan.expenses
        : resource === "milestones"
          ? plan.milestones
          : resource === "liabilities"
            ? plan.liabilities
            : resource === "real-assets"
              ? plan.real_assets
              : []
    : [];
  const savedName = items?.find((item) => item.id === id)?.name;
  const draftName =
    data && typeof data === "object" && "name" in data && typeof data.name === "string"
      ? data.name
      : undefined;
  const name = savedName ?? draftName;
  const verb = method === "delete" ? "Delete" : method === "post" ? "Create" : "Save";
  return `${verb} ${labels[resource] ?? "plan"}${name ? ` “${name.slice(0, 80)}${name.length > 80 ? "…" : ""}”` : ""}${samePlan ? ` in “${plan.name}”` : ""}`;
}

// Error envelopes are text, never markup. Suppress technical diagnostics and
// URLs even if a proxy or unexpected server supplies them in a message field.
function safeText(value: unknown): string | null {
  if (
    typeof value !== "string" ||
    value.length > 600 ||
    /https?:|\/api\/|traceback|stack trace|sql|select .+ from|token|password|cookie|<[^>]+>/i.test(
      value,
    )
  )
    return null;
  return value.replace(/[\r\n\t]/g, " ");
}

const BOUNDS: [RegExp, (limit: string) => string][] = [
  [/^Input should be greater than or equal to (-?[\d.e+]+)$/, (limit) => `Enter ${limit} or more`],
  [/^Input should be less than or equal to (-?[\d.e+]+)$/, (limit) => `Enter ${limit} or less`],
  [/^Input should be greater than (-?[\d.e+]+)$/, (limit) => `Enter more than ${limit}`],
  [/^Input should be less than (-?[\d.e+]+)$/, (limit) => `Enter less than ${limit}`],
];

/** Validation wording a person can act on, without the validator's phrasing. */
function readableReason(reason: string): string {
  const text = reason.replace(/^Value error, /, "");
  for (const [pattern, phrase] of BOUNDS) {
    const match = pattern.exec(text);
    // Years and small limits read without grouping ("1900"); amounts with it.
    const limit = Number(match?.[1]);
    if (match)
      return phrase(
        limit.toLocaleString("en-US", {
          maximumFractionDigits: 4,
          useGrouping: Math.abs(limit) >= 10_000,
        }),
      );
  }
  return text;
}

/**
 * Whether a failed request was a 409 conflict (for example a stale allocation revision).
 * Reads the client's save error (`status`) and a raw Axios error (`response.status`).
 */
export function isSaveConflict(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const { status, response } = error as {
    status?: unknown;
    response?: { status?: unknown } | null;
  };
  return status === 409 || response?.status === 409;
}

export function saveFailure(
  error: {
    response?: {
      status?: number;
      data?: { error?: { code?: unknown; message?: unknown; details?: unknown } };
    };
    code?: string;
  },
  action: string,
): SaveFailure {
  const status = error.response?.status;
  const refusal = extensions.api?.refusal?.(error);
  if (refusal) return { message: `${action} was not saved. ${refusal.message}`, rejected: true };
  const envelope = error.response?.data?.error;
  const details = Array.isArray(envelope?.details)
    ? envelope.details
        .flatMap((detail) => {
          const field = safeText(detail?.field);
          // A revision check is the server's bookkeeping; the message says what changed.
          if (field === "expected_revision") return [];
          const reason = safeText(detail?.reason);
          if (!field || !/^[a-z_]+$/.test(field) || !reason) return [];
          // A reason that is the whole message already reads as a sentence.
          if (reason === envelope?.message) return [reason];
          const label = field.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
          return [`${label}: ${readableReason(reason)}`];
        })
        .join(". ")
    : "";
  const message = safeText(envelope?.message);
  let explanation: string;
  const rejected = [400, 401, 403, 404, 409, 422, 429].includes(status ?? 0);
  // The notice beside the editor says the draft is kept; these lines say only what happened and what to do.
  if (status === 422 || status === 400)
    explanation = `was not saved. ${(details || (message !== "Validation failed" ? message : null) || "Some input was rejected; the server did not identify a field").replace(/[.]$/, "")}.`;
  else if (status === 401)
    explanation =
      "was not saved because your session expired. Open CoastMath in a new tab to renew it, then retry.";
  else if (status === 403)
    explanation = "was not saved: this session does not have permission for this plan.";
  else if (status === 404)
    explanation = "was not saved because the item or plan is no longer available.";
  else if (status === 409)
    explanation = `was not saved because it conflicts with saved data. ${details ? `${details}. ` : ""}${message ?? "Review the latest saved values before retrying."}`;
  else if (status === 429)
    explanation =
      "was not saved because too many requests were received. Wait a moment, then retry.";
  else if (typeof navigator !== "undefined" && navigator.onLine === false)
    explanation = "could not be confirmed while offline. Check saved values before retrying.";
  else if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT")
    explanation =
      "could not be confirmed before the request timed out. Check saved values before retrying.";
  else if (status && status >= 500)
    explanation = "could not be confirmed: the server failed. Check saved values before retrying.";
  else
    explanation =
      "could not be confirmed: the connection was interrupted. Check saved values before retrying.";
  return { message: `${action} ${explanation}`, rejected };
}

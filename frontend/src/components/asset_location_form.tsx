import { useRef, useState } from "react";
import type { AccountBucket, AssetLocation, PlanData, TaxSettings } from "@/types/plan";
import type { PendingSave } from "./assumptions_panel";
import { DEFAULT_TAX_SETTINGS } from "@/domain/tax_settings_defaults";

const BUCKETS: { value: AccountBucket; label: string }[] = [
  { value: "tax_deferred", label: "Pre-tax: traditional IRAs and workplace plans" },
  { value: "tax_free", label: "Roth and 529" },
  { value: "taxable", label: "Taxable brokerage and other" },
];
const DEFAULT_ORDER: AccountBucket[] = ["tax_deferred", "tax_free", "taxable"];
const isBucket = (entry: string): entry is AccountBucket => BUCKETS.some((b) => b.value === entry);

/** The buckets in their saved order, then any the saved order leaves out. */
export function bucketOrder(saved: string[] | undefined): AccountBucket[] {
  const listed = (saved ?? []).filter(isBucket);
  return [...listed, ...DEFAULT_ORDER.filter((b) => !listed.includes(b))];
}

/**
 * Reorders only the bucket entries. Account ids saved through the API keep
 * their positions, so this form never drops them.
 */
export function mergeOrder(saved: string[] | undefined, buckets: AccountBucket[]): string[] {
  const queue = [...buckets];
  const merged = (saved ?? []).map((entry) => (isBucket(entry) ? queue.shift()! : entry));
  return [...merged, ...queue];
}

/**
 * Household bond target and asset location (tax_settings.asset_location). It saves with
 * the Assumptions sheet's one Save button: an edit hands the sheet a pending save.
 */
export default function AssetLocationForm({
  plan,
  onSave,
  onPending,
}: {
  plan: PlanData;
  onSave: (settings: TaxSettings) => Promise<void>;
  onPending: (pending: PendingSave | null) => void;
}) {
  const saved = plan.tax_settings?.asset_location ?? null;
  const [household, setHousehold] = useState(saved?.bond_allocation_mode === "household");
  const [order, setOrder] = useState(() => bucketOrder(saved?.bond_location_order));
  const [error, setError] = useState("");
  const latest = useRef({ household, order });
  latest.current = { household, order };

  function edited(next: { household?: boolean; order?: AccountBucket[] }) {
    if (next.household !== undefined) setHousehold(next.household);
    if (next.order) setOrder(next.order);
    setError("");
    onPending({
      check: () => true,
      save: async () => {
        const { household, order } = latest.current;
        const location: AssetLocation | null =
          household || saved
            ? {
                bond_allocation_mode: household ? "household" : "per_account",
                bond_location_order: mergeOrder(saved?.bond_location_order, order),
                excluded_account_ids: saved?.excluded_account_ids ?? [],
              }
            : null;
        try {
          await onSave({ ...DEFAULT_TAX_SETTINGS, ...plan.tax_settings, asset_location: location });
          return true;
        } catch {
          setError("Could not save the bond location. Your choices are kept; try again.");
          return false;
        }
      },
    });
  }

  function move(index: number, step: -1 | 1) {
    const next = [...order];
    [next[index], next[index + step]] = [next[index + step], next[index]];
    edited({ order: next });
  }

  return (
    <details
      id="asset-location"
      style={{ borderTop: "1px solid var(--surface-border)", padding: "12px 0" }}
    >
      <summary style={{ cursor: "pointer", fontWeight: 600 }}>
        Bond location · {household ? "Household target" : "Each account"}
      </summary>
      <div style={{ display: "grid", gap: 10, marginTop: 8 }}>
        <label>
          Apply the bond allocation
          <select
            value={household ? "household" : "per_account"}
            onChange={(e) => edited({ household: e.target.value === "household" })}
          >
            <option value="per_account">To each account</option>
            <option value="household">To all investment accounts together</option>
          </select>
        </label>
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
          {household
            ? "Each year the plan's bond share of all pooled balances is held in bonds, filling accounts in this order; the rest is stocks. Accounts with their own bond allocation or glide path keep it and count toward the total. Cash, HSA and crypto accounts are not pooled."
            : "Every account holds the plan's bond share unless it has its own bond allocation or glide path."}
        </p>
        {household && (
          <ol
            style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 6 }}
            aria-label="Bond location order"
          >
            {order.map((bucket, i) => {
              const label = BUCKETS.find((b) => b.value === bucket)?.label ?? bucket;
              return (
                <li key={bucket}>
                  <span style={{ marginRight: 8 }}>{label}</span>
                  <button
                    type="button"
                    disabled={i === 0}
                    onClick={() => move(i, -1)}
                    aria-label={`Move ${label} up`}
                  >
                    Up
                  </button>{" "}
                  <button
                    type="button"
                    disabled={i === order.length - 1}
                    onClick={() => move(i, 1)}
                    aria-label={`Move ${label} down`}
                  >
                    Down
                  </button>
                </li>
              );
            })}
          </ol>
        )}
        {error && (
          <p role="alert" className="field-error">
            {error}
          </p>
        )}
      </div>
    </details>
  );
}

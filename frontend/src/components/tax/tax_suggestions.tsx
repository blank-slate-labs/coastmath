import { useEffect, useRef, useState } from "react";

import * as api from "@/api/client";
import { articlePath } from "@/help/help_catalog";
import { usePlanStore } from "@/stores/plan_store";
import type { TaxSuggestion, TaxSuggestionKey } from "@/types/plan";
import { moneyLabel, ratePct, signedCompactCurrency } from "@/utils/format";

const HELP: Record<TaxSuggestionKey, string> = {
  max_401k: articlePath("contributions-and-employer-match"),
  backdoor_roth: articlePath("backdoor-roth"),
  max_hsa: articlePath("hsa"),
  mega_backdoor: `${articlePath("backdoor-roth")}#mega-backdoor`,
  roth_conversion: articlePath("roth-conversions"),
  gain_harvest: `${articlePath("capital-gains-and-dividends")}#gain-harvesting`,
};

const favorable = (better: boolean) => ({
  color: better ? "var(--chart-green)" : "var(--chart-red)",
});

/** Server-tested rule changes that improve the saved plan. Nothing is applied. */
export function TaxSuggestions() {
  const plan = usePlanStore((s) => s.plan);
  const accountsRevision = usePlanStore((s) => s.accountsRevision);
  const [suggestions, setSuggestions] = useState<TaxSuggestion[] | null>(null);
  const [discountRate, setDiscountRate] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);

  useEffect(() => {
    request.current += 1;
    setSuggestions(null);
    setDiscountRate(null);
    setRunning(false);
    setError(null);
    return () => {
      request.current += 1;
    };
  }, [plan, accountsRevision]);

  if (!plan) return null;
  const planId = plan.id;

  async function run() {
    const current = ++request.current;
    setRunning(true);
    setError(null);
    try {
      const response = await api.suggestTaxStrategies(planId);
      if (request.current === current) {
        setSuggestions(response.suggestions);
        setDiscountRate(response.pre_tax_discount_rate ?? null);
      }
    } catch {
      if (request.current === current) setError("Could not check suggestions. Try again.");
    } finally {
      if (request.current === current) setRunning(false);
    }
  }

  return (
    <section style={{ display: "grid", gap: 10 }} data-sample-editor>
      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
        }}
      >
        <h3 style={{ margin: 0 }}>Suggestions</h3>
        <button
          type="button"
          className="btn-secondary"
          disabled={running}
          onClick={() => void run()}
        >
          {running ? "Simulating…" : "Find suggestions"}
        </button>
      </div>
      {error && (
        <p role="alert" style={{ margin: 0, fontSize: 13, color: "var(--color-danger)" }}>
          {error}
        </p>
      )}
      {suggestions && suggestions.length === 0 && <p style={{ margin: 0 }}>No suggestions.</p>}
      {suggestions && suggestions.length > 0 && (
        <ul
          aria-label="Tax suggestions"
          style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}
        >
          {suggestions.map((s) => (
            <li
              key={s.key}
              style={{
                display: "flex",
                gap: 16,
                flexWrap: "wrap",
                alignItems: "baseline",
                justifyContent: "space-between",
              }}
            >
              <a href={HELP[s.key]} target="_blank" rel="noreferrer">
                {s.title}
              </a>
              <dl style={{ display: "flex", gap: 16, margin: 0, fontSize: 13 }}>
                <div>
                  <dt style={{ color: "var(--text-secondary)" }}>Lifetime taxes</dt>
                  <dd style={{ margin: 0, ...favorable(s.lifetime_tax_change <= 0) }}>
                    {signedCompactCurrency(s.lifetime_tax_change)}
                  </dd>
                </div>
                <div>
                  <dt style={{ color: "var(--text-secondary)" }}>
                    {discountRate == null ? "End net worth" : "End net worth, after tax"}
                  </dt>
                  <dd style={{ margin: 0, ...favorable(s.end_net_worth_change >= 0) }}>
                    {signedCompactCurrency(s.end_net_worth_change)}
                  </dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>
      )}
      {suggestions && suggestions.length > 0 && (
        <p style={{ margin: 0, fontSize: 12, color: "var(--text-secondary)" }}>
          {moneyLabel("Nominal dollars.")}
          {discountRate != null && ` Pre-tax balances net of ${ratePct(discountRate)} income tax.`}
        </p>
      )}
    </section>
  );
}

export default TaxSuggestions;

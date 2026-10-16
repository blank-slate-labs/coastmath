import { useCallback, useEffect, useState } from "react";

import type { StorageAdapter } from "@/storage/adapter";
import type { TaxRegimeCountry, TaxRegimeRegistry } from "@/types/plan";

export type TaxRegimesState =
  | { status: "loading"; countries: null }
  | { status: "ready"; countries: TaxRegimeCountry[] }
  | { status: "error"; countries: null };

const registries = new WeakMap<StorageAdapter, Promise<TaxRegimeCountry[]>>();

/** Accepts `{countries: [...]}` or a bare list. */
export function registryCountries(
  body: TaxRegimeRegistry | TaxRegimeCountry[] | null | undefined,
): TaxRegimeCountry[] {
  const list = Array.isArray(body) ? body : body?.countries;
  if (!Array.isArray(list)) throw new Error("Unexpected tax regime registry");
  return list.map((country) => ({
    ...country,
    regions: country.regions ?? [],
    account_kinds: country.account_kinds ?? [],
    benefit_rules: country.benefit_rules ?? [],
    spec_years: country.spec_years ?? [],
    approximations: country.approximations ?? [],
  }));
}

/**
 * The country registry (GET /tax-regimes), loaded once per adapter. A failed
 * load is retried by `retry` or by the next editor that opens.
 */
export function useTaxRegimes(adapter: StorageAdapter): TaxRegimesState & { retry: () => void } {
  const [state, setState] = useState<TaxRegimesState>({ status: "loading", countries: null });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    let request = registries.get(adapter);
    if (!request) {
      // A thrown TypeError (an adapter without the route) becomes a rejection.
      request = Promise.resolve()
        .then(() => adapter.listTaxRegimes())
        .then(registryCountries);
      registries.set(adapter, request);
      request.catch(() => {
        if (registries.get(adapter) === request) registries.delete(adapter);
      });
    }
    setState({ status: "loading", countries: null });
    request.then(
      (countries) => {
        if (active) setState({ status: "ready", countries });
      },
      () => {
        if (active) setState({ status: "error", countries: null });
      },
    );
    return () => {
      active = false;
    };
  }, [adapter, attempt]);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, retry };
}

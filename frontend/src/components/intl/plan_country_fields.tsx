import { useId, useState } from "react";

import {
  CUSTOM_COUNTRY,
  US_COUNTRY,
  US_ONLY_SETTINGS,
  countryName,
  currencyChoices,
  defaultRegion,
} from "@/domain/intl_plan";
import type { TaxRegimeCountry } from "@/types/plan";
import type { TaxRegimesState } from "./use_tax_regimes";

export interface CountryChange {
  tax_country: string;
  tax_region: string | null;
  /** Present when the currency changes with the country. */
  currency?: string;
}

interface PlanCountryFieldsProps {
  regimes: TaxRegimesState & { retry: () => void };
  country: string;
  region: string | null;
  currency: string;
  onCountryChange: (change: CountryChange) => void;
  onRegionChange: (region: string | null) => void;
  onCurrencyChange: (currency: string) => void;
}

/** US first, then the registry's countries by name, with "Other" last. */
export function countryOptions(
  countries: readonly TaxRegimeCountry[] | null,
  saved: string,
): { code: string; name: string }[] {
  const listed = (countries ?? []).filter((c) => c.code !== US_COUNTRY);
  const named = listed
    .filter((c) => c.code !== CUSTOM_COUNTRY)
    .map((c) => ({ code: c.code, name: c.name }))
    .sort((a, b) => a.name.localeCompare(b.name));
  const custom = listed.find((c) => c.code === CUSTOM_COUNTRY);
  const options = [{ code: US_COUNTRY, name: "United States" }, ...named];
  if (custom)
    options.push({ code: CUSTOM_COUNTRY, name: custom.name || countryName(CUSTOM_COUNTRY) });
  // A saved country stays selectable while the registry loads or if it was withdrawn.
  if (!options.some((o) => o.code === saved))
    options.push({ code: saved, name: countryName(saved, countries) });
  return options;
}

function SwitchExplanation({
  from,
  to,
  countries,
}: {
  from: string;
  to: string;
  countries: readonly TaxRegimeCountry[] | null;
}) {
  const toName = countryName(to, countries);
  const fromName = countryName(from, countries);
  // A saved country the registry no longer offers: nothing of it carries over.
  const withdrawn = !!countries && from !== US_COUNTRY && !countries.some((c) => c.code === from);
  if (withdrawn) {
    return (
      <p>
        {fromName} is no longer supported; its benefits and contribution room are removed.
        {to === US_COUNTRY ? " Check the state on this page." : ""}
      </p>
    );
  }
  if (from === US_COUNTRY) {
    return (
      <>
        <p>
          From the plan&apos;s start,{" "}
          {toName === countryName(CUSTOM_COUNTRY)
            ? "your custom tax rules replace"
            : `${toName}'s tax rules for residents replace`}{" "}
          US tax in the years you live there. These US settings stop applying in those years:
        </p>
        <ul>
          {US_ONLY_SETTINGS.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p>
          They stay saved. Residency changes keep their own countries, and US settings still apply
          to US years.
        </p>
      </>
    );
  }
  if (to === US_COUNTRY) {
    return (
      <p>
        US federal, state and local tax apply again in the years you live in the US. {fromName}
        &apos;s account kinds, benefits and rules stay saved but apply only in years you live there.
        Check the state on this page.
      </p>
    );
  }
  return (
    <p>
      {toName}&apos;s tax rules replace {fromName}&apos;s from the plan&apos;s start. {fromName}
      &apos;s account kinds and benefits stay saved but apply only in years you live there.
    </p>
  );
}

/**
 * Tax country, region and display currency pickers, fed by GET /tax-regimes.
 * Renders label cells for the caller's form grid. A country change waits for
 * confirmation, since it changes which settings apply.
 */
export default function PlanCountryFields({
  regimes,
  country,
  region,
  currency,
  onCountryChange,
  onRegionChange,
  onCurrencyChange,
}: PlanCountryFieldsProps) {
  const [pending, setPending] = useState<string | null>(null);
  const [switchCurrency, setSwitchCurrency] = useState(true);
  const titleId = useId();
  const helpId = useId();
  const countries = regimes.countries;
  const options = countryOptions(countries, country);
  const selected = countries?.find((c) => c.code === country) ?? null;
  const regions = selected?.regions ?? [];
  const pendingCountry = pending ? (countries?.find((c) => c.code === pending) ?? null) : null;
  const pendingCurrency = pending === US_COUNTRY ? "USD" : (pendingCountry?.currency ?? null);
  const offersCurrency = !!pendingCurrency && pendingCurrency !== currency;

  function confirm() {
    if (!pending) return;
    onCountryChange({
      tax_country: pending,
      // A country with regions starts at its default; the picker below changes it.
      tax_region: defaultRegion(pendingCountry),
      ...(offersCurrency && switchCurrency && pendingCurrency ? { currency: pendingCurrency } : {}),
    });
    setPending(null);
  }

  return (
    <>
      <label>
        Tax country
        <select
          aria-label="Tax country"
          aria-describedby={helpId}
          value={pending ?? country}
          disabled={pending !== null}
          onChange={(e) => {
            if (e.target.value === country) return;
            setSwitchCurrency(true);
            setPending(e.target.value);
          }}
        >
          {options.map((o) => (
            <option key={o.code} value={o.code}>
              {o.name}
            </option>
          ))}
        </select>
        <span id={helpId} style={{ display: "block", fontSize: 12 }}>
          {regimes.status === "loading" && <span role="status">Loading countries…</span>}
          {regimes.status === "error" && (
            <span role="status">
              The country list could not load.{" "}
              {country === US_COUNTRY
                ? "The plan stays in the United States."
                : "The saved country is kept."}{" "}
              <button type="button" onClick={regimes.retry}>
                Retry
              </button>
            </span>
          )}
          {regimes.status === "ready" && "Where you live and pay tax at the plan's start."}
        </span>
      </label>

      {selected && selected.approximations.length > 0 && (
        <details style={{ gridColumn: "1 / -1", fontSize: 12 }}>
          <summary>How {selected.name}&apos;s taxes are approximated</summary>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {selected.approximations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </details>
      )}

      {regions.length > 0 && (
        <label>
          Region
          <select value={region ?? ""} onChange={(e) => onRegionChange(e.target.value || null)}>
            {region == null && <option value="">Choose a region</option>}
            {region != null && !regions.some((r) => r.code === region) && (
              <option value={region}>{region}</option>
            )}
            {regions.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
      )}

      <label>
        Currency
        <select
          aria-label="Currency"
          aria-describedby={`${helpId}-currency`}
          value={currency}
          onChange={(e) => onCurrencyChange(e.target.value)}
        >
          {currencyChoices(currency, selected?.currency).map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </select>
        <span id={`${helpId}-currency`} style={{ display: "block", fontSize: 12 }}>
          Display only: enter every amount in this currency. Nothing is converted.
        </span>
      </label>

      {pending !== null && (
        <div
          role="alertdialog"
          aria-labelledby={titleId}
          style={{
            gridColumn: "1 / -1",
            padding: "12px 14px",
            borderRadius: 12,
            background: "var(--gray-100)",
          }}
        >
          <strong id={titleId}>Switch tax country to {countryName(pending, countries)}?</strong>
          <SwitchExplanation from={country} to={pending} countries={countries} />
          {offersCurrency && (
            <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={switchCurrency}
                onChange={(e) => setSwitchCurrency(e.target.checked)}
              />
              Also show amounts in {pendingCurrency} (amounts are not converted)
            </label>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
            <button type="button" className="btn-primary" onClick={confirm}>
              Switch to {countryName(pending, countries)}
            </button>
            <button type="button" onClick={() => setPending(null)}>
              Keep {countryName(country, countries)}
            </button>
          </div>
        </div>
      )}
    </>
  );
}

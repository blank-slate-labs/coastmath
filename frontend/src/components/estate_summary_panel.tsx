import { usePlanStore } from "@/stores/plan_store";
import { compactCurrency, dollarsOr, fullCurrency } from "@/utils/format";

const filingLabel: Record<string, string> = {
  single: "Single",
  married_filing_jointly: "Married filing jointly",
  married_filing_separately: "Married filing separately",
  head_of_household: "Head of household",
};

interface Row {
  label: string;
  value: number;
  tone?: "neutral" | "negative" | "positive" | "muted";
  note?: string;
}

/**
 * The engine-computed estate breakdown at the end of the plan, as a short
 * reconciliation from total assets down to net legacy. Every figure comes from
 * `metadata.net_legacy`; nothing is derived client-side.
 */
export default function EstateSummaryPanel() {
  const plan = usePlanStore((s) => s.plan);
  const simulation = usePlanStore((s) => s.simulation);
  const legacy = simulation?.metadata.net_legacy ?? null;
  const settings = plan?.estate_settings ?? null;

  if (!plan || !simulation) return null;

  if (!legacy) {
    return (
      <div className="card" data-testid="estate-summary">
        <h3 className="chart-title">Estate</h3>
        <p style={{ fontSize: 13, marginTop: 6 }}>
          The estate summary is unavailable for this projection.
        </p>
      </div>
    );
  }

  const debts = legacy.debts ?? legacy.total_liabilities;
  const accrued = legacy.accrued_taxes ?? 0;
  const settlement = legacy.settlement_costs ?? 0;
  const heirTax = legacy.heir_income_tax ?? 0;
  const education = legacy.education_savings_outside_estate ?? 0;
  const bequest = legacy.charitable_bequest ?? 0;
  const sellingCosts = legacy.selling_costs ?? 0;
  const heirGainsTax = legacy.heir_capital_gains_tax ?? 0;
  const rows: Row[] = [
    { label: "Total assets", value: legacy.total_assets, tone: "neutral" },
    { label: "Outstanding debts", value: -debts, tone: debts > 0 ? "negative" : "muted" },
    {
      label: accrued >= 0 ? "Accrued income tax and unfunded bills" : "Income tax refund due",
      value: -accrued,
      tone: accrued > 0 ? "negative" : "muted",
    },
    ...(education > 0
      ? [{ label: "529 accounts (outside the estate)", value: -education, tone: "muted" as const }]
      : []),
    { label: "Gross estate", value: legacy.gross_estate, tone: "neutral" },
    {
      label: "Settlement costs",
      value: -settlement,
      tone: settlement > 0 ? "negative" : "muted",
      note: settlement > 0 ? "Probate and administration" : undefined,
    },
  ];
  if (bequest > 0)
    rows.push({
      label: "Charitable bequest",
      value: -bequest,
      tone: "negative",
      note: "Deducted before estate tax",
    });

  if (legacy.marital_deduction_applied) {
    rows.push({
      label: "Federal estate tax",
      value: 0,
      tone: "muted",
      note: "Deferred: passes to surviving spouse",
    });
  } else {
    rows.push({
      label: legacy.custom_federal_exemption
        ? "Federal exemption (custom)"
        : "Federal exemption (statutory)",
      value: legacy.federal_exemption,
      tone: "muted",
    });
    if (legacy.dsue_amount > 0) {
      rows.push({
        label: "Deceased partner's unused exemption (DSUE)",
        value: legacy.dsue_amount,
        tone: "muted",
      });
    }
    rows.push({
      label: "Federal taxable estate",
      value: legacy.federal_taxable_estate,
      tone: "muted",
    });
    rows.push({
      label: "Federal estate tax",
      value: -legacy.federal_estate_tax,
      tone: legacy.federal_estate_tax > 0 ? "negative" : "muted",
    });
  }

  if (settings?.state_estate_tax_enabled) {
    if (legacy.marital_deduction_applied) {
      rows.push({
        label: "State estate tax",
        value: 0,
        tone: "muted",
        note: "Deferred: passes to surviving spouse",
      });
    } else {
      rows.push({ label: "State exemption", value: legacy.state_exemption, tone: "muted" });
      rows.push({
        label: "State taxable estate",
        value: legacy.state_taxable_estate,
        tone: "muted",
      });
      rows.push({
        label: "State estate tax",
        value: -legacy.state_estate_tax,
        tone: legacy.state_estate_tax > 0 ? "negative" : "muted",
      });
    }
  }

  if (sellingCosts > 0)
    rows.push({ label: "Selling costs on real assets", value: -sellingCosts, tone: "negative" });
  if (education > 0)
    rows.push({
      label: "529 accounts passing to their successor owner",
      value: education,
      tone: "neutral",
    });
  rows.push({
    label: "Net estate",
    value: legacy.net_legacy,
    tone: legacy.net_legacy >= 0 ? "positive" : "negative",
  });
  const pretaxShown = (legacy.pretax_balance ?? 0) > 0 && !legacy.marital_deduction_applied;
  if (pretaxShown) {
    rows.push({
      label: "Pre-tax balances passing to heirs",
      value: legacy.pretax_balance ?? 0,
      tone: "muted",
    });
    if ((legacy.heir_income_tax_deduction_691c ?? 0) > 0) {
      rows.push({
        label: "§691(c) deduction for estate tax on those balances",
        value: legacy.heir_income_tax_deduction_691c ?? 0,
        tone: "muted",
      });
    }
    rows.push({
      label: "Heirs' income tax on inherited pre-tax balances",
      value: -heirTax,
      tone: heirTax > 0 ? "negative" : "muted",
      note: heirTax > 0 ? undefined : "Set a heir income tax rate to estimate",
    });
  }
  if (heirGainsTax > 0) {
    rows.push({
      label: "Heirs' capital gains tax (no step-up)",
      value: -heirGainsTax,
      tone: "negative",
    });
  }
  if (pretaxShown || heirGainsTax > 0) {
    rows.push({
      label: "Net to heirs after their income tax",
      value: legacy.net_to_heirs_after_income_tax ?? legacy.net_legacy,
      tone: "positive",
    });
  }

  const toneColor: Record<NonNullable<Row["tone"]>, string> = {
    neutral: "var(--text-primary)",
    negative: "var(--chart-red)",
    positive: "var(--chart-green)",
    muted: "var(--text-secondary)",
  };

  const settingBits: Array<{ label: string; value: string }> = settings
    ? [
        { label: "Step-up basis", value: settings.step_up_basis_on_death ? "Yes" : "No" },
        ...(plan.spouse
          ? [
              {
                label: "Status after partner's death",
                value:
                  filingLabel[settings.filing_status_after_death] ??
                  settings.filing_status_after_death,
              },
              {
                label: "Portability",
                value: settings.portability_election ? "Elected" : "Not elected",
              },
            ]
          : []),
        {
          label: "Partner",
          value:
            plan.spouse?.birth_year && plan.spouse.life_expectancy
              ? `Born ${plan.spouse.birth_year}, to age ${plan.spouse.life_expectancy}`
              : "None",
        },
      ]
    : [];

  return (
    <div
      className="card"
      data-testid="estate-summary"
      style={{ display: "grid", gap: 16, alignContent: "start" }}
    >
      <div className="legacy-head">
        <div>
          <h3 className="chart-title">Estate</h3>
          <div className="chart-subtitle">
            {legacy.death_year} · {dollarsOr("nominal dollars", "nominal amounts")}
          </div>
        </div>
        <div className="legacy-total">
          <span
            className="legacy-total-value"
            style={{ color: legacy.net_legacy >= 0 ? "var(--chart-green)" : "var(--chart-red)" }}
            title={fullCurrency(legacy.net_legacy)}
          >
            {compactCurrency(legacy.net_legacy)}
          </span>
          <span className="legacy-total-label">
            Net estate · {dollarsOr("future dollars", "future amounts")}
          </span>
        </div>
      </div>

      {legacy.marital_deduction_applied && (
        <p className="legacy-note">
          Marital deduction applied. Tax at the surviving partner’s death is not projected.
        </p>
      )}

      <div className="legacy-rows">
        {rows.map((raw) => {
          const row = { ...raw, value: raw.value === 0 ? 0 : raw.value }; // normalise −0
          const isTotal = row.label === "Net estate" || row.label === "Gross estate";
          return (
            <div key={row.label} className={`stat-row${isTotal ? " is-total" : ""}`}>
              <span className="stat-label">
                {row.label}
                {row.note && <span className="ledger-note">{row.note}</span>}
              </span>
              <span
                className="stat-value"
                title={fullCurrency(row.value)}
                style={{ color: toneColor[row.tone ?? "neutral"] }}
              >
                {row.value < 0 ? "−" : ""}
                {compactCurrency(Math.abs(row.value))}
              </span>
            </div>
          );
        })}
      </div>

      {settingBits.length > 0 && (
        <p className="legacy-settings">
          {settingBits.map((bit, i) => (
            <span key={bit.label}>
              {i > 0 && (
                <span className="legacy-sep" aria-hidden="true">
                  {" "}
                  ·{" "}
                </span>
              )}
              <span className="legacy-setting-label">{bit.label}</span> {bit.value}
            </span>
          ))}
        </p>
      )}

      {legacy.exclusions.length > 0 && (
        <details className="notice-details">
          <summary>What this estimate leaves out</summary>
          <ul>
            {legacy.exclusions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

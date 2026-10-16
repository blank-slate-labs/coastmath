import { RETIREMENT_ACCOUNT_TYPES } from "@/domain/account_types";
import type { AccountCreate, InheritanceSettings, RothSettings } from "@/types/plan";
import { moneyLabel } from "@/utils/format";
import MoneyInput from "./money_input";

type Props = {
  type: string;
  value: Pick<
    AccountCreate,
    "inherited_year" | "beneficiary_type" | "inheritance_settings" | "roth_settings"
  >;
  onChange: (value: Props["value"]) => void;
};

export default function AccountTaxFields({ type, value, onChange }: Props) {
  const retirement = RETIREMENT_ACCOUNT_TYPES.has(type);
  if (!retirement) return null;
  const inherited = value.inheritance_settings ?? {};
  const roth = value.roth_settings;
  const updateInheritance = (patch: Partial<InheritanceSettings>) =>
    onChange({ ...value, inheritance_settings: { ...inherited, ...patch } });
  const updateRoth = (patch: Partial<RothSettings>) =>
    onChange({ ...value, roth_settings: { ...roth!, ...patch } });
  return (
    <fieldset style={{ gridColumn: "1 / -1", display: "grid", gap: 12 }}>
      <legend>Retirement account tax history</legend>
      <label>
        Year original owner died (inherited accounts only)
        <input
          type="number"
          min={1900}
          max={new Date().getFullYear()}
          value={value.inherited_year ?? ""}
          onChange={(e) =>
            onChange({ ...value, inherited_year: e.target.value ? Number(e.target.value) : null })
          }
        />
      </label>
      {value.inherited_year != null && (
        <>
          <label>
            Beneficiary relationship to original owner
            <select
              value={value.beneficiary_type ?? "non_edb"}
              onChange={(e) =>
                onChange({
                  ...value,
                  beneficiary_type: e.target.value as AccountCreate["beneficiary_type"],
                  inheritance_settings: { ...inherited, distribution_method: "automatic" },
                })
              }
            >
              <option value="non_edb">
                Other individual beneficiary (ten-year rule for deaths from 2020)
              </option>
              <option value="spouse">Surviving spouse</option>
              <option value="edb">Other eligible designated beneficiary</option>
            </select>
          </label>
          <small>
            Minor child, disabled or chronically ill person, or someone no more than ten years
            younger.
          </small>
          <label>
            Distribution election
            <select
              value={inherited.distribution_method ?? "automatic"}
              onChange={(e) =>
                updateInheritance({
                  distribution_method: e.target.value as InheritanceSettings["distribution_method"],
                })
              }
            >
              <option value="automatic">Default for this beneficiary</option>
              {((value.beneficiary_type !== "non_edb" && value.beneficiary_type != null) ||
                value.inherited_year < 2020) && (
                <option value="life_expectancy">Life expectancy</option>
              )}
              <option value="ten_year">Ten-year election (when eligible)</option>
              {value.beneficiary_type === "spouse" && (
                <option value="spousal_rollover">
                  Treat as spouse's own account after year of death
                </option>
              )}
            </select>
          </label>
          <label>
            Original owner's birth year
            <input
              type="number"
              min={1850}
              max={2200}
              value={inherited.decedent_birth_year ?? ""}
              onChange={(e) =>
                updateInheritance({
                  decedent_birth_year: e.target.value ? Number(e.target.value) : null,
                })
              }
            />
          </label>
          {!type.startsWith("roth") && (
            <label>
              Death relative to the required beginning date
              <select
                value={
                  inherited.decedent_died_after_rbd == null
                    ? "unknown"
                    : String(inherited.decedent_died_after_rbd)
                }
                onChange={(e) =>
                  updateInheritance({
                    decedent_died_after_rbd:
                      e.target.value === "unknown" ? null : e.target.value === "true",
                  })
                }
              >
                <option value="unknown">Unknown — projection assumes before</option>
                <option value="false">Before</option>
                <option value="true">On or after</option>
              </select>
            </label>
          )}
          {value.beneficiary_type === "edb" && (
            <label>
              <input
                type="checkbox"
                checked={inherited.beneficiary_is_minor_child ?? false}
                onChange={(e) =>
                  updateInheritance({ beneficiary_is_minor_child: e.target.checked })
                }
              />{" "}
              Beneficiary was the original owner's minor child (ten-year deadline begins at 21)
            </label>
          )}
          {!type.startsWith("roth") && (
            <label>
              {moneyLabel("Unpaid original-owner RMD in year of death ($)")}
              <MoneyInput
                min={0}
                step="0.01"
                value={inherited.year_of_death_rmd_remaining ?? 0}
                onValueChange={(amount) =>
                  updateInheritance({ year_of_death_rmd_remaining: Number(amount) })
                }
              />
            </label>
          )}
        </>
      )}
      {type.startsWith("roth") && (
        <>
          <label>
            <input
              type="checkbox"
              checked={roth != null}
              onChange={(e) =>
                onChange({
                  ...value,
                  roth_settings: e.target.checked
                    ? { contribution_basis: 0, first_contribution_year: null, conversions: [] }
                    : null,
                })
              }
            />{" "}
            Enter Roth contribution and conversion history
          </label>
          {!roth && (
            <small>
              Blank basis is treated as zero; blank five-year clock starts at plan start.
            </small>
          )}
          {roth && (
            <>
              <label>
                {moneyLabel("Undistributed regular contributions ($)")}
                <MoneyInput
                  min={0}
                  step="0.01"
                  required
                  value={roth.contribution_basis}
                  onValueChange={(amount) => updateRoth({ contribution_basis: Number(amount) })}
                />
              </label>
              <small>
                Exclude earnings and conversions. Your Roth IRAs share contribution basis; enter
                each dollar once.
              </small>
              <label>
                First Roth contribution tax year
                <input
                  type="number"
                  min={1998}
                  max={2200}
                  value={roth.first_contribution_year ?? ""}
                  onChange={(e) =>
                    updateRoth({
                      first_contribution_year: e.target.value ? Number(e.target.value) : null,
                    })
                  }
                />
              </label>
              <small>
                {type === "roth_ira"
                  ? "Use your earliest Roth IRA year, or the original owner's year for an inherited IRA."
                  : "First year in this designated Roth plan."}
              </small>
              {roth.conversions.map((conversion, index) => (
                <fieldset key={index} style={{ display: "grid", gap: 8 }}>
                  <legend>Conversion {index + 1} — remaining basis</legend>
                  <label>
                    Conversion tax year
                    <input
                      type="number"
                      min={1998}
                      max={2200}
                      required
                      value={conversion.year}
                      onChange={(e) =>
                        updateRoth({
                          conversions: roth.conversions.map((c, i) =>
                            i === index ? { ...c, year: Number(e.target.value) } : c,
                          ),
                        })
                      }
                    />
                  </label>
                  <label>
                    {moneyLabel("Previously taxable conversion principal ($)")}
                    <MoneyInput
                      min={0}
                      step="0.01"
                      required
                      value={conversion.taxable_basis}
                      onValueChange={(amount) =>
                        updateRoth({
                          conversions: roth.conversions.map((c, i) =>
                            i === index ? { ...c, taxable_basis: Number(amount) } : c,
                          ),
                        })
                      }
                    />
                  </label>
                  <label>
                    {moneyLabel("Nontaxable conversion principal ($)")}
                    <MoneyInput
                      min={0}
                      step="0.01"
                      required
                      value={conversion.nontaxable_basis}
                      onValueChange={(amount) =>
                        updateRoth({
                          conversions: roth.conversions.map((c, i) =>
                            i === index ? { ...c, nontaxable_basis: Number(amount) } : c,
                          ),
                        })
                      }
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() =>
                      updateRoth({ conversions: roth.conversions.filter((_, i) => i !== index) })
                    }
                  >
                    Remove conversion {index + 1}
                  </button>
                </fieldset>
              ))}
              <button
                type="button"
                onClick={() =>
                  updateRoth({
                    conversions: [
                      ...roth.conversions,
                      { year: new Date().getFullYear(), taxable_basis: 0, nontaxable_basis: 0 },
                    ],
                  })
                }
              >
                Add past conversion
              </button>
            </>
          )}
        </>
      )}
    </fieldset>
  );
}

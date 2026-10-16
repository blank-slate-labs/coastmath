import { RULE_OF_55_TYPES, TRADITIONAL_RETIREMENT_TYPES } from "@/domain/account_types";
import type { AccountDistributionSettings } from "@/types/plan";

type Props = {
  type: string;
  owner: string;
  inherited: boolean;
  value: AccountDistributionSettings | null;
  onChange: (value: AccountDistributionSettings | null) => void;
};

/** The settings that exist for this account, with empty values dropped; null when nothing is set. */
export function cleanDistributionSettings(
  type: string,
  owner: string,
  inherited: boolean,
  value: AccountDistributionSettings | null,
): AccountDistributionSettings | null {
  const out: AccountDistributionSettings = {};
  if (RULE_OF_55_TYPES.has(type) && !inherited && value?.separation_year != null)
    out.separation_year = value.separation_year;
  if (
    TRADITIONAL_RETIREMENT_TYPES.has(type) &&
    !inherited &&
    (owner === "self" || owner === "spouse") &&
    value?.spouse_sole_beneficiary
  )
    out.spouse_sole_beneficiary = true;
  return Object.keys(out).length ? out : null;
}

export default function AccountDistributionFields({
  type,
  owner,
  inherited,
  value,
  onChange,
}: Props) {
  const workplace = RULE_OF_55_TYPES.has(type) && !inherited;
  const spouseEligible =
    TRADITIONAL_RETIREMENT_TYPES.has(type) &&
    !inherited &&
    (owner === "self" || owner === "spouse");
  if (!workplace && !spouseEligible) return null;
  const settings = value ?? {};
  const update = (patch: Partial<AccountDistributionSettings>) =>
    onChange({ ...settings, ...patch });
  return (
    <fieldset style={{ gridColumn: "1 / -1", display: "grid", gap: 12 }}>
      <legend>Distribution rules</legend>
      {workplace && (
        <>
          <label>
            Year you left this plan's employer (optional)
            <input
              type="number"
              min={1900}
              max={2200}
              value={settings.separation_year ?? ""}
              onChange={(e) =>
                update({ separation_year: e.target.value === "" ? null : Number(e.target.value) })
              }
            />
          </label>
          <small>Applies the rule of 55 to this plan only. Blank if you haven't left.</small>
        </>
      )}
      {spouseEligible && (
        <>
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={settings.spouse_sole_beneficiary ?? false}
              onChange={(e) => update({ spouse_sole_beneficiary: e.target.checked })}
            />
            Spouse is the sole beneficiary of this account
          </label>
          <small>
            When the spouse is more than 10 years younger, required distributions use the IRS Joint
            Life and Last Survivor table instead of the Uniform Lifetime table.
          </small>
        </>
      )}
    </fieldset>
  );
}

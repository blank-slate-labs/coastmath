import { MONTH_NAMES } from "@/domain/months";

interface MonthPickerProps {
  value: number | null;
  onChange: (month: number | null) => void;
  label: string;
  placeholder?: string;
}

const compactSelect: React.CSSProperties = {
  minHeight: 36,
  padding: "6px 28px 6px 10px",
  fontSize: "0.8125rem",
  marginTop: 4,
  width: "100%",
};

export function MonthPicker({ value, onChange, label, placeholder }: MonthPickerProps) {
  return (
    <label>
      {label}
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        style={compactSelect}
      >
        <option value="">{placeholder ?? "— None —"}</option>
        {MONTH_NAMES.map((name, i) => (
          <option key={i + 1} value={i + 1}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
}

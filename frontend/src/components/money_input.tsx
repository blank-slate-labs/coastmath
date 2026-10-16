import { useEffect, useRef, useState, type ChangeEvent, type InputHTMLAttributes } from "react";

type NativeProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "type" | "value" | "defaultValue" | "onChange" | "min" | "max" | "step" | "inputMode"
>;

export interface MoneyInputProps extends NativeProps {
  /** Numeric text ("231000.5") or a number; null or undefined shows blank. */
  value: string | number | null | undefined;
  /** Numeric text without grouping commas; "" while blank or a lone "-" or ".". */
  onValueChange: (value: string) => void;
  min?: number | string;
  max?: number | string;
  /** Caps decimals by the step's: 1 or 1000 whole amounts, "0.01" cents; omitted or "any", no cap. */
  step?: number | string;
}

/** Decimal places a step allows; null when unlimited. */
function decimalsFor(step: number | string | undefined): number | null {
  if (step == null || step === "any") return null;
  const text = String(step);
  const dot = text.indexOf(".");
  return dot === -1 ? 0 : text.length - dot - 1;
}

/** Typed text as numeric text: digits, one point, a leading minus sign. */
export function cleanAmount(text: string, decimals: number | null = null): string {
  const sign = text.trimStart().startsWith("-") ? "-" : "";
  const digits = text.replace(/[^0-9.]/g, "");
  const dot = digits.indexOf(".");
  if (dot === -1) return sign + digits;
  const whole = digits.slice(0, dot);
  const fraction = digits.slice(dot + 1).replace(/\./g, "");
  if (decimals === 0) return sign + whole;
  return `${sign}${whole}.${decimals == null ? fraction : fraction.slice(0, decimals)}`;
}

/** "1234567.5" -> "1,234,567.5"; text that is not plain numeric is returned unchanged. */
export function groupDigits(raw: string): string {
  const match = /^(-?)(\d*)(\.\d*)?$/.exec(raw);
  if (!match) return raw;
  return match[1] + match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (match[3] ?? "");
}

/** What the parent sees for typed text: a partial "-" or "." reads as blank, as in a number input. */
function reported(text: string): string {
  const raw = cleanAmount(text);
  return raw !== "" && Number.isFinite(Number(raw)) ? raw : "";
}

function textOf(value: MoneyInputProps["value"]): string {
  if (value == null) return "";
  if (typeof value === "number") return Number.isFinite(value) ? groupDigits(String(value)) : "";
  return groupDigits(value);
}

/** Whether typed text already shows the value: "12." and "12.50" show 12. */
function shows(text: string, value: MoneyInputProps["value"]): boolean {
  const typed = reported(text);
  const given = value == null ? "" : String(value);
  if (typed === given) return true;
  return typed !== "" && given !== "" && Number(typed) === Number(given);
}

/** Characters before the caret that survive cleaning, used to restore it after regrouping. */
const significantBefore = (text: string, caret: number) =>
  text.slice(0, caret).replace(/[^0-9.-]/g, "").length;

function caretAfter(formatted: string, significant: number): number {
  let seen = 0;
  for (let i = 0; i < formatted.length && seen < significant; i++) {
    if (formatted[i] !== ",") seen++;
    if (seen === significant) return i + 1;
  }
  return significant === 0 ? 0 : formatted.length;
}

/**
 * A money amount field: no spinner, digits grouped with commas as they are
 * typed. The parent keeps plain numeric text, as from a number input.
 */
export default function MoneyInput({
  value,
  onValueChange,
  min,
  max,
  step,
  ...props
}: MoneyInputProps) {
  const ref = useRef<HTMLInputElement>(null);
  const decimals = decimalsFor(step);
  const [text, setText] = useState(() => textOf(value));
  const [shownValue, setShownValue] = useState(value);
  // Follow outside changes, but keep a typed "12." while the value reads 12.
  if (value !== shownValue) {
    setShownValue(value);
    if (!shows(text, value)) setText(textOf(value));
  }

  // A text field ignores min and max, so the form's own validation checks them.
  useEffect(() => {
    const raw = cleanAmount(text);
    const amount = Number(raw);
    let message = "";
    if (raw !== "" && !Number.isFinite(amount)) message = "Enter a number.";
    else if (raw !== "" && min != null && min !== "" && amount < Number(min))
      message = `Enter ${groupDigits(String(min))} or more.`;
    else if (raw !== "" && max != null && max !== "" && amount > Number(max))
      message = `Enter ${groupDigits(String(max))} or less.`;
    ref.current?.setCustomValidity(message);
  }, [text, min, max]);

  function change(event: ChangeEvent<HTMLInputElement>) {
    const input = event.target;
    let typed = input.value;
    let caret = input.selectionStart ?? typed.length;
    // Deleting a grouping comma deletes the digit beside it instead.
    if (typed.length === text.length - 1 && typed.replace(/,/g, "") === text.replace(/,/g, "")) {
      const kind = (event.nativeEvent as InputEvent).inputType;
      if (kind === "deleteContentBackward" && caret > 0) {
        typed = typed.slice(0, caret - 1) + typed.slice(caret);
        caret -= 1;
      } else if (kind === "deleteContentForward")
        typed = typed.slice(0, caret) + typed.slice(caret + 1);
    }
    const formatted = groupDigits(cleanAmount(typed, decimals));
    // Write the field now so React's controlled-value restore keeps the caret.
    if (input.value !== formatted) {
      input.value = formatted;
      if (document.activeElement === input) {
        const position = caretAfter(formatted, significantBefore(typed, caret));
        input.setSelectionRange(position, position);
      }
    }
    setText(formatted);
    onValueChange(reported(formatted));
  }

  return (
    <input
      {...props}
      ref={ref}
      type="text"
      inputMode={decimals === 0 ? "numeric" : "decimal"}
      autoComplete={props.autoComplete ?? "off"}
      value={text}
      onChange={change}
    />
  );
}

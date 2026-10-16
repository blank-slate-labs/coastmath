import { useEffect, useRef, useState, type ReactNode } from "react";

type Field = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

/** The label's own words: help lines nested in the label after the control are not part of the name. */
function labelWords(label: HTMLLabelElement, field: Field): string {
  let words = "";
  for (const node of Array.from(label.childNodes)) {
    if (node === field || (node instanceof Element && node.contains(field))) break;
    words += node.textContent ?? "";
  }
  // A control that leads its label (a checkbox) is named by the label's bare text.
  if (!words.trim())
    words = Array.from(label.childNodes)
      .filter((node) => node.nodeType === Node.TEXT_NODE)
      .map((node) => node.textContent)
      .join("");
  return words.replace(/\s+/g, " ").trim();
}

function fieldName(field: Field): string {
  const label = field.labels?.[0];
  const name =
    (label && labelWords(label, field)) || field.getAttribute("aria-label") || field.name;
  return name ? `${name}: ` : "";
}

const DATE_TYPES = new Set(["date", "month", "week", "datetime-local", "time"]);

function decimalPlaces(step: number): number | null {
  for (let places = 0; places <= 6; places += 1)
    if (Math.abs(step - 10 ** -places) < 1e-12) return places;
  return null;
}

function isMultiple(value: number, step: number): boolean {
  const ratio = value / step;
  return Math.abs(ratio - Math.round(ratio)) < 1e-9;
}

function stepMessage(field: HTMLInputElement): string {
  // A missing or invalid step attribute means the default step of 1.
  const step = Number(field.step) > 0 ? Number(field.step) : 1;
  // The step base is min, else the field's default value, else zero (HTML step rules).
  const base =
    [field.min, field.defaultValue]
      .map((raw) => (raw === "" ? NaN : Number(raw)))
      .find(Number.isFinite) ?? 0;
  const places = decimalPlaces(step);
  if (places !== null && isMultiple(base, step))
    return places === 0
      ? "Enter a whole number."
      : `Use at most ${places} decimal place${places === 1 ? "" : "s"}.`;
  return base === 0 ? `Enter a multiple of ${step}.` : `Use steps of ${step} from ${base}.`;
}

/**
 * The product's own words for a rejected field, from its ValidityState. The browser's
 * validationMessage is its own copy ("Please select an item in the list."); a message the app
 * set with setCustomValidity is kept as written.
 */
export function validityMessage(field: Field): string {
  const v = field.validity;
  const type = field instanceof HTMLInputElement ? field.type : "";
  const dated = DATE_TYPES.has(type);
  if (v.customError) return field.validationMessage;
  if (v.valueMissing) {
    if (field instanceof HTMLSelectElement || type === "radio") return "Choose one.";
    if (type === "checkbox") return "Check this box.";
    if (type === "number") return "Enter a number.";
    if (dated) return type === "time" ? "Enter a time." : "Enter a date.";
    if (type === "email") return "Enter an email address.";
    return "Enter a value.";
  }
  if (v.badInput) return dated ? "Enter a complete date." : "Enter a number.";
  if (v.typeMismatch)
    return type === "email" ? "Enter an email address." : "Enter a full web address.";
  if (v.patternMismatch) return field.getAttribute("title") || "Check the format.";
  if (v.tooLong && "maxLength" in field) return `Use ${field.maxLength} characters or fewer.`;
  if (v.tooShort && "minLength" in field) return `Use ${field.minLength} characters or more.`;
  if (field instanceof HTMLInputElement) {
    if (v.rangeUnderflow) return `Enter ${field.min} or ${dated ? "later" : "more"}.`;
    if (v.rangeOverflow) return `Enter ${field.max} or ${dated ? "earlier" : "less"}.`;
    if (v.stepMismatch && !dated) return stepMessage(field);
  }
  return "Check this value.";
}

/**
 * Replaces the browser's validation bubbles with the app's inline pattern: a field the browser
 * rejects (required, min, max, step) turns red and the first problem is stated in one red line,
 * in the product's words rather than the browser's.
 * Only fields this wrapper marked are cleared again; a form's own aria-invalid stays its own.
 */
export function InlineValidity({ children }: { children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const element = root.current;
    if (!element) return;
    let reported = false;
    // "invalid" does not bubble, so listen in the capture phase.
    const onInvalid = (event: Event) => {
      // Nested wrappers (a form inside a modal): the outermost, which hears the event first, reports it.
      const claimed = event as Event & { inlineValidity?: boolean };
      if (claimed.inlineValidity) return;
      claimed.inlineValidity = true;
      const field = event.target as Field;
      event.preventDefault();
      if (!field.hasAttribute("aria-invalid")) {
        field.setAttribute("aria-invalid", "true");
        field.dataset.nativeInvalid = "true";
      }
      // Every invalid field fires in one pass; the first one is named and focused.
      if (reported) return;
      reported = true;
      queueMicrotask(() => {
        reported = false;
      });
      field.focus();
      setMessage(`${fieldName(field)}${validityMessage(field)}`);
    };
    const onEdit = (event: Event) => {
      const field = event.target as Field;
      if (field.dataset?.nativeInvalid && field.validity?.valid) {
        field.removeAttribute("aria-invalid");
        delete field.dataset.nativeInvalid;
      }
      // The line names the first field still rejected, or goes once none is.
      const next = element.querySelector<Field>("[data-native-invalid]");
      setMessage(next ? `${fieldName(next)}${validityMessage(next)}` : null);
    };
    element.addEventListener("invalid", onInvalid, true);
    element.addEventListener("input", onEdit, true);
    element.addEventListener("change", onEdit, true);
    return () => {
      element.removeEventListener("invalid", onInvalid, true);
      element.removeEventListener("input", onEdit, true);
      element.removeEventListener("change", onEdit, true);
    };
  }, []);

  return (
    <div ref={root}>
      {message && (
        <p role="alert" className="field-error" style={{ margin: "0 0 12px" }}>
          {message}
        </p>
      )}
      {children}
    </div>
  );
}

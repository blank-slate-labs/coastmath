// A small reader for the JSON Schema of a benefit rule's params (a Pydantic
// model's `model_json_schema()`): enough to render one input per property and
// check it before the server validates it again.

export type ParamKind = "number" | "integer" | "boolean" | "string" | "enum";

export interface ParamField {
  key: string;
  label: string;
  kind: ParamKind;
  description: string | null;
  required: boolean;
  options: { value: string; label: string }[];
  /** Enum values keep their JSON type (numbers stay numbers). */
  optionValues: Record<string, string | number | boolean>;
  minimum: number | null;
  maximum: number | null;
  exclusiveMinimum: number | null;
  exclusiveMaximum: number | null;
  default: unknown;
}

type Schema = Record<string, unknown>;

const isSchema = (value: unknown): value is Schema =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const num = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

function resolve(schema: Schema, root: Schema): Schema {
  const ref = schema.$ref;
  if (typeof ref !== "string") return schema;
  const name = ref.split("/").pop() ?? "";
  const defs = (
    isSchema(root.$defs) ? root.$defs : isSchema(root.definitions) ? root.definitions : {}
  ) as Schema;
  const target = defs[name];
  return isSchema(target)
    ? { ...target, ...Object.fromEntries(Object.entries(schema).filter(([k]) => k !== "$ref")) }
    : schema;
}

/** The non-null branch of an Optional[...] (anyOf with a null type). */
function unwrapNullable(schema: Schema, root: Schema): Schema {
  const branches = (
    Array.isArray(schema.anyOf) ? schema.anyOf : Array.isArray(schema.oneOf) ? schema.oneOf : null
  ) as unknown[] | null;
  if (!branches) return resolve(schema, root);
  const real = branches
    .filter(isSchema)
    .map((b) => resolve(b, root))
    .filter((b) => b.type !== "null");
  if (real.length !== 1) return schema;
  const { anyOf: _anyOf, oneOf: _oneOf, ...rest } = schema;
  return { ...real[0], ...rest };
}

const humanize = (key: string): string =>
  key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export function paramFields(schema: Record<string, unknown> | null | undefined): ParamField[] {
  if (!isSchema(schema) || !isSchema(schema.properties)) return [];
  const required = new Set(
    Array.isArray(schema.required)
      ? schema.required.filter((k): k is string => typeof k === "string")
      : [],
  );
  return Object.entries(schema.properties).flatMap(([key, raw]) => {
    if (!isSchema(raw)) return [];
    const prop = unwrapNullable(resolve(raw, schema), schema);
    const values = Array.isArray(prop.enum)
      ? (prop.enum as unknown[]).filter((v): v is string | number | boolean =>
          ["string", "number", "boolean"].includes(typeof v),
        )
      : null;
    let kind: ParamKind;
    if (values?.length) kind = "enum";
    else if (prop.type === "integer") kind = "integer";
    else if (prop.type === "number") kind = "number";
    else if (prop.type === "boolean") kind = "boolean";
    else if (prop.type === "string") kind = "string";
    else return [];
    const optionValues = Object.fromEntries((values ?? []).map((v) => [String(v), v]));
    return [
      {
        key,
        // A referenced enum's title names its type, not this field.
        label:
          typeof raw.title === "string" && raw.title
            ? raw.title
            : typeof raw.$ref !== "string" && typeof prop.title === "string" && prop.title
              ? prop.title
              : humanize(key),
        kind,
        description: typeof prop.description === "string" ? prop.description : null,
        required: required.has(key),
        options: (values ?? []).map((v) => ({
          value: String(v),
          label: typeof v === "string" ? humanize(v) : String(v),
        })),
        optionValues,
        minimum: num(prop.minimum),
        maximum: num(prop.maximum),
        exclusiveMinimum: num(prop.exclusiveMinimum),
        exclusiveMaximum: num(prop.exclusiveMaximum),
        default: prop.default,
      },
    ];
  });
}

/** Editable text (or checkbox state) for a saved or default value. */
export function paramDraft(field: ParamField, value: unknown): string | boolean {
  const v = value === undefined ? field.default : value;
  if (field.kind === "boolean") return v === true;
  return v == null ? "" : String(v);
}

/** The wire params for a draft, or the first error per field. Blank optional fields are left out. */
export function paramValues(
  fields: ParamField[],
  draft: Record<string, string | boolean>,
): { params: Record<string, unknown> } | { errors: Record<string, string> } {
  const params: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const field of fields) {
    const raw = draft[field.key];
    if (field.kind === "boolean") {
      params[field.key] = raw === true;
      continue;
    }
    const text = typeof raw === "string" ? raw.trim() : "";
    if (!text) {
      if (field.required)
        errors[field.key] =
          `${field.kind === "enum" ? "Choose" : "Enter"} ${field.label.toLowerCase()}.`;
      continue;
    }
    if (field.kind === "enum") {
      if (!(text in field.optionValues)) errors[field.key] = `Choose ${field.label.toLowerCase()}.`;
      else params[field.key] = field.optionValues[text];
      continue;
    }
    if (field.kind === "string") {
      params[field.key] = text;
      continue;
    }
    const value = Number(text);
    if (!Number.isFinite(value) || (field.kind === "integer" && !Number.isInteger(value))) {
      errors[field.key] = field.kind === "integer" ? "Enter a whole number." : "Enter a number.";
    } else if (field.minimum != null && value < field.minimum) {
      errors[field.key] = `Enter ${field.minimum} or more.`;
    } else if (field.maximum != null && value > field.maximum) {
      errors[field.key] = `Enter ${field.maximum} or less.`;
    } else if (field.exclusiveMinimum != null && value <= field.exclusiveMinimum) {
      errors[field.key] = `Enter more than ${field.exclusiveMinimum}.`;
    } else if (field.exclusiveMaximum != null && value >= field.exclusiveMaximum) {
      errors[field.key] = `Enter less than ${field.exclusiveMaximum}.`;
    } else {
      params[field.key] = value;
    }
  }
  return Object.keys(errors).length ? { errors } : { params };
}

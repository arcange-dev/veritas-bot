/**
 * Turn the API's error envelope into something a person can read.
 *
 * The server sends `detail` in several shapes, depending on where the error came from:
 *   "Not found"                                  a plain string
 *   { "name": ["A project with this..."] }       field validation errors
 *   { "non_field_errors": ["..."] }              form-level errors
 *   ["..."]                                      a list
 * Reading only the string case (as the first version did) turned every field error into
 * "Request failed (400)".
 */
export type FieldErrors = Record<string, string[]>;

export interface ParsedError {
  message: string;
  fields: FieldErrors;
}

const asStrings = (value: unknown): string[] => {
  if (typeof value === "string") return value.trim() ? [value.trim()] : [];
  if (Array.isArray(value)) return value.flatMap(asStrings);
  if (value && typeof value === "object") return Object.values(value).flatMap(asStrings);
  return [];
};

const label = (field: string): string =>
  field.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function parseErrorDetail(detail: unknown, status: number): ParsedError {
  const fallback = `Request failed (${status})`;
  if (typeof detail === "string") return { message: detail.trim() || fallback, fields: {} };

  if (Array.isArray(detail)) {
    const all = asStrings(detail);
    return { message: all[0] ?? fallback, fields: {} };
  }

  if (detail && typeof detail === "object") {
    const fields: FieldErrors = {};
    const general: string[] = [];
    for (const [key, value] of Object.entries(detail as Record<string, unknown>)) {
      const messages = asStrings(value);
      if (messages.length === 0) continue;
      if (key === "non_field_errors" || key === "detail") general.push(...messages);
      else fields[key] = messages;
    }
    // A form shows each field's message beside its input; the summary is for everything else.
    const firstField = Object.entries(fields)[0];
    const message =
      general[0] ??
      (firstField ? `${label(firstField[0])}: ${firstField[1][0]}` : undefined) ??
      fallback;
    return { message, fields };
  }
  return { message: fallback, fields: {} };
}

/** Project rules shared by the forms, mirrored from the server so errors show early. */

export const NAME_MIN = 2;
export const NAME_MAX = 64;          // the design says "2–64 characters"

export type NameCheck = { ok: true; name: string } | { ok: false; message: string };

/** Collapse whitespace, then check length and that the name yields a usable slug. */
export function checkProjectName(raw: string): NameCheck {
  const name = raw.replace(/\s+/g, " ").trim();
  if (name.length < NAME_MIN) return { ok: false, message: `Use at least ${NAME_MIN} characters.` };
  if (name.length > NAME_MAX) return { ok: false, message: `Use ${NAME_MAX} characters or fewer.` };
  // The project address is derived from the name using ASCII letters and digits only. A name
  // without any (for example "!!!" or an all-Cyrillic one) produces no address, and the server
  // would reject it, so say so here instead of after submitting.
  if (previewSlug(name) === "") {
    return { ok: false, message: "Include at least one letter (A to Z) or number so the project can have an address." };
  }
  return { ok: true, name };
}

/**
 * Mirror of Django's `slugify` (allow_unicode=False), which the server uses to build a project's
 * address: NFKD-fold to ASCII, lowercase, drop everything except word characters, spaces and
 * hyphens, then collapse runs of spaces/hyphens into one hyphen and trim them. Underscores are
 * KEPT, and a name with no ASCII letters or digits (for example a Cyrillic one) yields "".
 */
export function previewSlug(name: string): string {
  return name
    .normalize("NFKD").replace(/[^\x00-\x7f]/g, "")
    .replace(/[^\w\s-]/g, "").trim().toLowerCase()
    .replace(/[-\s]+/g, "-")
    .replace(/^[-_]+|[-_]+$/g, "")
    .slice(0, 80);
}

/**
 * Deleting is permanent, so the button stays disabled until the exact name is typed.
 * Comparison ignores surrounding whitespace but is otherwise exact and case-sensitive.
 */
export function deleteConfirmed(typed: string, projectName: string): boolean {
  return projectName.length > 0 && typed.trim() === projectName;
}

/** The draft is only worth saving once the user has typed something. */
export function isPristine(form: { name: string; description: string }): boolean {
  return form.name.trim() === "" && form.description.trim() === "";
}

export interface FormValues {
  name: string;
  description: string;
  default_branch: string;
  execution_preference: "local" | "cloud";
}

/** Only the fields that changed, so a PATCH never overwrites something it did not touch. */
export function changedFields(original: FormValues, current: FormValues): Partial<FormValues> {
  const out: Partial<FormValues> = {};
  (Object.keys(current) as (keyof FormValues)[]).forEach((k) => {
    if (current[k] !== original[k]) (out as Record<string, unknown>)[k] = current[k];
  });
  return out;
}

/** A branch name git would accept, in the simple cases the form can offer. */
export function checkBranch(raw: string): { ok: boolean; message?: string } {
  const b = raw.trim();
  if (!b) return { ok: false, message: "Branch is required." };
  if (b.length > 120) return { ok: false, message: "Branch name is too long." };
  if (/\s|\.\.|[~^:?*[\\]|\/\/|^\/|\/$|\.lock$|@\{/.test(b)) return { ok: false, message: "That is not a valid branch name." };
  return { ok: true };
}

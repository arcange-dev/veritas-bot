/**
 * Who may do what, mirrored from the server so the UI hides what would be refused.
 * The server remains the authority: this only avoids showing buttons that always 403.
 */
import type { Organization, Role } from "./schemas";

const RANK: Record<Role, number> = { viewer: 0, member: 1, admin: 2, owner: 3 };

export const atLeast = (role: Role | undefined, needed: Role): boolean =>
  role !== undefined && RANK[role] >= RANK[needed];

export const canWrite = (role?: Role) => atLeast(role, "member");
export const canAdminister = (role?: Role) => atLeast(role, "admin");

/**
 * Pick the active workspace. A stored id wins only if the user still belongs to it
 * (membership can be revoked), otherwise fall back to the first, otherwise none.
 */
export function chooseOrg(orgs: Organization[], storedId: string | null): Organization | null {
  if (orgs.length === 0) return null;
  return orgs.find((o) => o.id === storedId) ?? orgs[0] ?? null;
}

/**
 * What the app should show before any workspace screen: a pure decision so every
 * branch is testable without rendering.
 *
 *  unconfigured  Supabase env vars missing (nobody can sign in)
 *  checking      still finding out if there is a session / loading /me
 *  signed_out    no session -> /login
 *  error         /me failed for a reason other than "not signed in"
 *  no_workspace  signed in, but belongs to no workspace yet -> create one
 *  ready         has an active workspace
 */
import { ApiError } from "@/lib/api";
import { chooseOrg } from "./access";
import type { Me, Organization } from "./schemas";

export type GateState =
  | { kind: "unconfigured" }
  | { kind: "checking" }
  | { kind: "signed_out" }
  | { kind: "error"; message: string; retryable: boolean }
  | { kind: "no_workspace"; me: Me }
  | { kind: "ready"; me: Me; org: Organization };

export interface GateInput {
  configured: boolean;
  signedIn: boolean | null; // null = not known yet
  me: Me | undefined;
  meLoading: boolean;
  meError: unknown;
  storedOrgId: string | null;
}

export function decideGate(i: GateInput): GateState {
  if (!i.configured) return { kind: "unconfigured" };
  if (i.signedIn === null) return { kind: "checking" };
  if (!i.signedIn) return { kind: "signed_out" };

  if (i.meError) {
    if (i.meError instanceof ApiError && i.meError.status === 401) return { kind: "signed_out" };
    const message =
      i.meError instanceof ApiError ? i.meError.message : "Could not load your account.";
    // 5xx and network failures are worth retrying; a 4xx other than 401 is not.
    const retryable =
      !(i.meError instanceof ApiError) || i.meError.status === 0 || i.meError.status >= 500;
    return { kind: "error", message, retryable };
  }
  if (i.meLoading || !i.me) return { kind: "checking" };

  const org = chooseOrg(i.me.organizations, i.storedOrgId);
  if (!org) return { kind: "no_workspace", me: i.me };
  return { kind: "ready", me: i.me, org };
}

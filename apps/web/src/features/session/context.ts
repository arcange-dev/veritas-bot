import { createContext, useContext } from "react";
import type { Me, Organization, Role } from "./schemas";

export interface SessionValue {
  me: Me;
  org: Organization;
  role: Role;
  setOrg: (orgId: string) => void;
}

export const SessionContext = createContext<SessionValue | null>(null);

/** Only valid under SessionGate's "ready" state; throws loudly if misused. */
export function useActiveSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useActiveSession must be used inside a ready SessionGate");
  return value;
}

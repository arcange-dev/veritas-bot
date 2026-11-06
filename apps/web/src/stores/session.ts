import { create } from "zustand";

const KEY = "veritas.org";

interface SessionState {
  /** The active workspace id. Always validated against /me by SessionGate before use. */
  orgId: string | null;
  email: string | null;
  setOrg: (orgId: string) => void;
  setEmail: (email: string | null) => void;
}

/** A remembered preference only: membership is checked server-side on every call. */
export const useSession = create<SessionState>((set) => ({
  orgId: localStorage.getItem(KEY) ?? localStorage.getItem("superagent.org") ?? null,
  email: null,
  setOrg: (orgId) => {
    localStorage.setItem(KEY, orgId);
    set({ orgId });
  },
  setEmail: (email) => set({ email }),
}));

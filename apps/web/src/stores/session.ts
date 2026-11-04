import { create } from "zustand";

interface SessionState {
  orgId: string | null;
  email: string | null;
  setOrg: (orgId: string) => void;
  setEmail: (email: string | null) => void;
}

/** Minimal session slice: the org whose data the UI is showing. */
export const useSession = create<SessionState>((set) => ({
  orgId: localStorage.getItem("superagent.org") ?? null,
  email: null,
  setOrg: (orgId) => {
    localStorage.setItem("superagent.org", orgId);
    set({ orgId });
  },
  setEmail: (email) => set({ email }),
}));

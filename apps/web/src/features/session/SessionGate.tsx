/**
 * Everything behind sign-in lives under this. It answers, in order: is Supabase
 * configured, is there a session, can we load /me, does the user have a workspace.
 * Only when all four are yes does it render the app, with the workspace selected.
 */
import { useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Logo } from "@/components/brand/Logo";
import { ApiError } from "@/lib/api";
import { getAccessToken, onAuthChange } from "@/lib/auth";
import { isConfigured } from "@/lib/env";
import { useSession } from "@/stores/session";
import { sessionApi } from "./api";
import { decideGate } from "./gate";
import { SessionContext, type SessionValue } from "./context";

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="glass-backdrop flex min-h-full items-center justify-center p-6">
      <div className="glass w-full max-w-sm rounded-lg p-6">
        <Logo size={22} className="mb-4" />
        {children}
      </div>
    </div>
  );
}

function CreateWorkspace({ onCreated }: { onCreated: (orgId: string) => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: (n: string) => sessionApi.createOrganization(n),
    onSuccess: (me) => {
      qc.setQueryData(["me"], me);
      const newest = me.organizations[me.organizations.length - 1];
      if (newest) onCreated(newest.id);
    },
  });
  const trimmed = name.trim();
  const message = create.error instanceof ApiError ? create.error.message : null;
  return (
    <Centered>
      <h1 className="text-[16px] font-semibold text-primary">Create your workspace</h1>
      <p className="mt-1 text-[12.5px] text-muted">
        A workspace holds your projects, agents and team. You can invite people later.
      </p>
      <form
        className="mt-5 flex flex-col gap-3"
        onSubmit={(e) => { e.preventDefault(); if (trimmed.length >= 2) create.mutate(trimmed); }}
      >
        <label htmlFor="workspace-name" className="panel-label">Workspace name</label>
        <input
          id="workspace-name" value={name} onChange={(e) => setName(e.target.value)}
          maxLength={120} autoFocus placeholder="Orbit Commerce"
          className="h-9 rounded-sm border border-subtle bg-base px-2 text-[12.5px] text-primary"
        />
        {message && <p role="alert" className="text-[12px] text-danger">{message}</p>}
        <button type="submit" disabled={trimmed.length < 2 || create.isPending}
                className="btn-liquid h-9 text-[12.5px] font-medium">
          {create.isPending ? "Creating…" : "Create workspace"}
        </button>
      </form>
    </Centered>
  );
}

export function SessionGate({ children, retryDelay }: { children: ReactNode; retryDelay?: number }) {
  const location = useLocation();
  const storedOrgId = useSession((s) => s.orgId);
  const setOrg = useSession((s) => s.setOrg);
  const [signedIn, setSignedIn] = useState<boolean | null>(isConfigured ? null : false);
  const qc = useQueryClient();

  useEffect(() => {
    if (!isConfigured) return;
    let alive = true;
    void getAccessToken().then((t) => { if (alive) setSignedIn(Boolean(t)); });
    const off = onAuthChange((s) => { setSignedIn(s); qc.clear(); });
    return () => { alive = false; off(); };
  }, [qc]);

  const me = useQuery({
    queryKey: ["me"],
    queryFn: sessionApi.me,
    enabled: signedIn === true,
    retry: (count, err) => !(err instanceof ApiError && err.status < 500 && err.status !== 0) && count < 2,
    ...(retryDelay !== undefined ? { retryDelay } : {}),
  });

  const state = decideGate({
    configured: isConfigured, signedIn, me: me.data, meLoading: me.isLoading,
    meError: me.error, storedOrgId,
  });

  // Keep the stored preference in step with what the server says is valid.
  useEffect(() => {
    if (state.kind === "ready" && state.org.id !== storedOrgId) setOrg(state.org.id);
  }, [state, storedOrgId, setOrg]);

  switch (state.kind) {
    case "unconfigured":
      return location.pathname === "/login" ? <>{children}</> : <Navigate to="/login" replace />;
    case "signed_out":
      return location.pathname === "/login" ? <>{children}</> : <Navigate to="/login" replace />;
    case "checking":
      return <Centered><p role="status" className="text-[12.5px] text-muted">Loading your account…</p></Centered>;
    case "error":
      return (
        <Centered>
          <p role="alert" className="text-[12.5px] text-danger">{state.message}</p>
          {state.retryable && (
            <button type="button" onClick={() => void me.refetch()}
                    className="btn-glass mt-3 h-8 px-3 text-[12.5px]">Try again</button>
          )}
        </Centered>
      );
    case "no_workspace":
      return <CreateWorkspace onCreated={setOrg} />;
    case "ready": {
      const value: SessionValue = { me: state.me, org: state.org, role: state.org.role, setOrg };
      // A signed-in user on /login has nothing to do there.
      if (location.pathname === "/login") return <Navigate to="/dashboard" replace />;
      return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
    }
  }
}

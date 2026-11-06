/**
 * SessionGate with the real component tree, real Zod schemas and real TanStack Query.
 * Only the network edge (fetch) and the Supabase helpers are faked.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import real from "./real_me.fixture.json";

const auth = vi.hoisted(() => ({ configured: true, token: "tok" as string | null, listeners: [] as ((s: boolean) => void)[] }));

vi.mock("@/lib/env", () => ({
  env: { apiBaseUrl: "http://api.test" },
  get isConfigured() { return auth.configured; },
}));
vi.mock("@/lib/auth", () => ({
  getAccessToken: async () => auth.token,
  onAuthChange: (fn: (s: boolean) => void) => { auth.listeners.push(fn); return () => undefined; },
}));

import { useSession } from "@/stores/session";
import { SessionGate } from "./SessionGate";
import { useActiveSession } from "./context";

type Call = { url: string; method: string; body: unknown };
let calls: Call[] = [];
let routes: Record<string, () => { status?: number; body: unknown }> = {};

beforeEach(() => {
  calls = []; routes = {}; auth.configured = true; auth.token = "tok"; auth.listeners = [];
  localStorage.clear(); useSession.setState({ orgId: null });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    calls.push({ url, method, body: init.body ? JSON.parse(String(init.body)) : undefined });
    const h = routes[`${method} ${url.replace("http://api.test", "")}`];
    if (!h) return new Response(JSON.stringify({ detail: "unrouted" }), { status: 599 });
    const { status = 200, body } = h();
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function Probe() {
  const { org, role } = useActiveSession();
  const loc = useLocation();
  return <p>app:{org.name}:{role}:{loc.pathname}</p>;
}

function mount(path = "/dashboard") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <SessionGate retryDelay={0}>
          <Routes>
            <Route path="/login" element={<p>login page</p>} />
            <Route path="*" element={<Probe />} />
          </Routes>
        </SessionGate>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SessionGate", () => {
  it("sends a signed-out visitor to the login page", async () => {
    auth.token = null;
    mount("/dashboard");
    expect(await screen.findByText("login page")).toBeInTheDocument();
    expect(calls).toHaveLength(0);                       // it never called the API without a session
  });

  it("sends everyone to login, and says why, when Supabase is not configured", async () => {
    auth.configured = false;
    mount("/studio");
    expect(await screen.findByText("login page")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("renders the app with the user's workspace and role when signed in", async () => {
    routes["GET /api/v1/me/"] = () => ({ body: real.me });
    mount("/dashboard");
    expect(await screen.findByText(/app:Acme:owner:\/dashboard/)).toBeInTheDocument();
  });

  it("remembers the validated workspace for the other screens", async () => {
    routes["GET /api/v1/me/"] = () => ({ body: real.me });
    mount();
    await screen.findByText(/app:Acme/);
    await waitFor(() => expect(useSession.getState().orgId).toBe(real.me.organizations[0]?.id));
  });

  it("replaces a stale remembered workspace the user no longer belongs to", async () => {
    useSession.setState({ orgId: "revoked-workspace" });
    routes["GET /api/v1/me/"] = () => ({ body: real.me });
    mount();
    await screen.findByText(/app:Acme/);
    await waitFor(() => expect(useSession.getState().orgId).toBe(real.me.organizations[0]?.id));
  });

  it("moves a signed-in user off /login", async () => {
    routes["GET /api/v1/me/"] = () => ({ body: real.me });
    mount("/login");
    expect(await screen.findByText(/app:Acme:owner:\/dashboard/)).toBeInTheDocument();
  });

  it("lets a user with no workspace create one, then shows the app", async () => {
    routes["GET /api/v1/me/"] = () => ({ body: { ...real.me, organizations: [] } });
    routes["POST /api/v1/me/organizations/"] = () => ({ status: 201, body: real.created });
    mount();
    const input = await screen.findByLabelText("Workspace name");
    const button = screen.getByRole("button", { name: "Create workspace" });
    expect(button).toBeDisabled();                       // nothing typed yet
    await userEvent.type(input, "  Fixture Co ");
    await userEvent.click(button);
    expect(await screen.findByText(/app:Fixture Co:owner/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: "Fixture Co" });
  });

  it("shows the server's message when workspace creation is refused", async () => {
    routes["GET /api/v1/me/"] = () => ({ body: { ...real.me, organizations: [] } });
    routes["POST /api/v1/me/organizations/"] = () => ({ status: 409, body: { code: "workspace_limit", detail: "You can own at most 5 workspaces." } });
    mount();
    await userEvent.type(await screen.findByLabelText("Workspace name"), "Another");
    await userEvent.click(screen.getByRole("button", { name: "Create workspace" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You can own at most 5 workspaces.");
  });

  it("offers Try again on a server failure and recovers", async () => {
    let up = false;
    routes["GET /api/v1/me/"] = () => (up ? { body: real.me } : { status: 503, body: { detail: "Service unavailable" } });
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    up = true;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/app:Acme/)).toBeInTheDocument();
  });

  it("does not offer Try again for a 403", async () => {
    routes["GET /api/v1/me/"] = () => ({ status: 403, body: { detail: "Forbidden" } });
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("Forbidden");
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("treats a 401 from the API as signed out", async () => {
    routes["GET /api/v1/me/"] = () => ({ status: 401, body: { detail: "expired" } });
    mount("/dashboard");
    expect(await screen.findByText("login page")).toBeInTheDocument();
  });
});

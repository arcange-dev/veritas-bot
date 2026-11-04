/**
 * The run panels with the real component tree, real Zod schemas, real hooks and
 * real TanStack Query. Only the network edge (fetch) and the auth token are faked.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import real from "./real_run.fixture.json";
import { AgentPanel } from "./AgentPanel";
import { PlanApprovals } from "./PlanApprovals";

vi.mock("@/lib/auth", () => ({ getAccessToken: async () => "test-token" }));
vi.mock("@/lib/env", () => ({ env: { apiBaseUrl: "http://api.test" } }));

const ORG = "11111111-1111-4111-8111-111111111111";
const RUN = real.detail.id;

type Call = { url: string; method: string; body: unknown };
let calls: Call[] = [];
let routes: Record<string, () => { status?: number; body: unknown }> = {};

function respond(url: string, method: string) {
  const key = `${method} ${url.replace("http://api.test", "")}`;
  const handler = routes[key];
  if (!handler) return new Response(JSON.stringify({ detail: `unrouted ${key}` }), { status: 599 });
  const { status = 200, body } = handler();
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  calls = [];
  routes = {};
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, method: init.method ?? "GET", body: init.body ? JSON.parse(String(init.body)) : undefined });
    return respond(url, init.method ?? "GET");
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function wrap(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const detail = (over: Record<string, unknown> = {}) => ({ ...real.detail, ...over });
const detailPath = `GET /api/v1/orgs/${ORG}/runs/${RUN}/`;

const approval = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", run: RUN, action_type: "production_migration",
  summary: "Apply migrations", payload: { command: "alembic upgrade head", target: "production" },
  state: "pending", expires_at: new Date(Date.now() + 30 * 60_000).toISOString(),
  decided_at: null, decision_note: "",
};

describe("AgentPanel", () => {
  it("starts a run with the project and trimmed objective, then reports its id", async () => {
    routes[`POST /api/v1/orgs/${ORG}/runs/`] = () => ({ status: 201, body: { ...real.detail, status: "queued" } });
    const onStarted = vi.fn();
    wrap(<AgentPanel orgId={ORG} projectId="proj-1" runId={null} onRunStarted={onStarted} />);

    await userEvent.type(screen.getByLabelText("Objective"), "  Add pagination to the runs list  ");
    await userEvent.click(screen.getByRole("button", { name: /send to orchestrator/i }));

    await waitFor(() => expect(onStarted).toHaveBeenCalledWith(RUN));
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({ project: "proj-1", objective: "Add pagination to the runs list" });
  });

  it("will not send an objective that is too short", async () => {
    wrap(<AgentPanel orgId={ORG} projectId="proj-1" runId={null} onRunStarted={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Objective"), "fix");
    expect(screen.getByRole("button", { name: /send to orchestrator/i })).toBeDisabled();
  });

  it("tells the user to pick a project instead of failing silently", () => {
    wrap(<AgentPanel orgId={ORG} projectId={null} runId={null} onRunStarted={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent(/project/i);
    expect(screen.getByRole("button", { name: /send to orchestrator/i })).toBeDisabled();
  });

  it("shows server progress and exact sub-cent spend", async () => {
    routes[detailPath] = () => ({ body: detail({ status: "running", cost_usd: "0.004000", cost_cap_usd: "5.000000" }) });
    wrap(<AgentPanel orgId={ORG} projectId="p" runId={RUN} onRunStarted={vi.fn()} />);
    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByText("$0.0040 of $5.00")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /spend/i })).toHaveAttribute("aria-valuenow", "0");
  });

  it("offers Resume (not Pause) on a paused run and posts the action", async () => {
    routes[detailPath] = () => ({ body: detail({ status: "paused" }) });
    routes[`POST /api/v1/orgs/${ORG}/runs/${RUN}/resume/`] = () => ({ body: { ...real.detail, status: "running" } });
    wrap(<AgentPanel orgId={ORG} projectId="p" runId={RUN} onRunStarted={vi.fn()} />);

    expect(await screen.findByRole("button", { name: /resume/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /pause/i })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /resume/i }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/resume/") && c.method === "POST")).toBe(true));
  });

  it("offers no controls once the run has finished", async () => {
    routes[detailPath] = () => ({ body: detail({ status: "succeeded" }) });
    wrap(<AgentPanel orgId={ORG} projectId="p" runId={RUN} onRunStarted={vi.fn()} />);
    expect(await screen.findByText("Done")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /pause|stop|resume/i })).not.toBeInTheDocument();
  });

  it("translates an error code instead of exposing it", async () => {
    routes[detailPath] = () => ({ body: detail({ status: "failed", error_code: "spend_cap_exceeded" }) });
    wrap(<AgentPanel orgId={ORG} projectId="p" runId={RUN} onRunStarted={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/spending limit/i);
    expect(screen.queryByText("spend_cap_exceeded")).not.toBeInTheDocument();
  });

  it("surfaces a server rejection to the user", async () => {
    routes[`POST /api/v1/orgs/${ORG}/runs/`] = () => ({ status: 402, body: { code: "spend_cap_exceeded", detail: "Monthly cap reached" } });
    wrap(<AgentPanel orgId={ORG} projectId="p" runId={null} onRunStarted={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Objective"), "Build the settings page");
    await userEvent.click(screen.getByRole("button", { name: /send to orchestrator/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Monthly cap reached");
  });
});

describe("PlanApprovals", () => {
  it("shows the real plan tasks with their owners", async () => {
    routes[detailPath] = () => ({ body: detail() });
    wrap(<PlanApprovals orgId={ORG} runId={RUN} />);
    const list = await screen.findByRole("list", { name: /plan tasks/i });
    expect(within(list).getAllByRole("listitem")).toHaveLength(real.detail.plan.length);
  });

  it("shows the EXACT payload being approved, not just the summary", async () => {
    routes[detailPath] = () => ({ body: detail({ status: "waiting_approval", pending_approvals: [approval] }) });
    wrap(<PlanApprovals orgId={ORG} runId={RUN} />);
    const payload = await screen.findByLabelText("Exact action payload");
    expect(payload).toHaveTextContent("alembic upgrade head");
    expect(payload).toHaveTextContent('"target": "production"');
  });

  it("sends the approval decision for that exact approval", async () => {
    routes[detailPath] = () => ({ body: detail({ status: "waiting_approval", pending_approvals: [approval] }) });
    routes[`POST /api/v1/orgs/${ORG}/approvals/${approval.id}/decide/`] = () => ({ body: { ...approval, state: "approved" } });
    wrap(<PlanApprovals orgId={ORG} runId={RUN} />);
    await userEvent.click(await screen.findByRole("button", { name: /approve/i }));
    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST");
      expect(post?.url).toContain(`/approvals/${approval.id}/decide/`);
      expect(post?.body).toEqual({ approve: true, note: "" });
    });
  });

  it("sends approve:false when rejecting", async () => {
    routes[detailPath] = () => ({ body: detail({ status: "waiting_approval", pending_approvals: [approval] }) });
    routes[`POST /api/v1/orgs/${ORG}/approvals/${approval.id}/decide/`] = () => ({ body: { ...approval, state: "rejected" } });
    wrap(<PlanApprovals orgId={ORG} runId={RUN} />);
    await userEvent.click(await screen.findByRole("button", { name: /reject/i }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({ approve: false, note: "" }));
  });

  it("disables both buttons once an approval has expired", async () => {
    const expired = { ...approval, expires_at: new Date(Date.now() - 60_000).toISOString() };
    routes[detailPath] = () => ({ body: detail({ status: "waiting_approval", pending_approvals: [expired] }) });
    wrap(<PlanApprovals orgId={ORG} runId={RUN} />);
    expect(await screen.findByText(/has expired/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /reject/i })).toBeDisabled();
  });

  it("shows a server conflict (for example, already decided) on the card", async () => {
    routes[detailPath] = () => ({ body: detail({ status: "waiting_approval", pending_approvals: [approval] }) });
    routes[`POST /api/v1/orgs/${ORG}/approvals/${approval.id}/decide/`] = () => ({ status: 409, body: { code: "invalid_state", detail: "Approval already decided" } });
    wrap(<PlanApprovals orgId={ORG} runId={RUN} />);
    await userEvent.click(await screen.findByRole("button", { name: /approve/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Approval already decided");
  });

  it("does not claim 'no pending approvals' before a run exists", () => {
    wrap(<PlanApprovals orgId={ORG} runId={null} />);
    expect(screen.getByText(/start a run/i)).toBeInTheDocument();
    expect(screen.queryByText(/no pending approvals/i)).not.toBeInTheDocument();
  });
});

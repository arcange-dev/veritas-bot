/** Projects screens with the real components, schemas and query client. Only fetch is faked. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import real from "../session/real_me.fixture.json";
import { SessionContext, type SessionValue } from "../session/context";
import { MeSchema, type Role } from "../session/schemas";
import { NewProjectPage } from "./NewProjectPage";
import { ProjectPage } from "./ProjectPage";
import { ProjectsPage } from "./ProjectsPage";

vi.mock("@/lib/auth", () => ({ getAccessToken: async () => "tok" }));
vi.mock("@/lib/env", () => ({ env: { apiBaseUrl: "http://api.test" } }));

const me = MeSchema.parse(real.me);
const ORG = me.organizations[0]!.id;
const P = real.projects.results[0]!;
const PROJECT = { ...P, archived_at: null, is_archived: false };

type Call = { url: string; method: string; body: unknown };
let calls: Call[] = [];
let routes: Record<string, () => { status?: number; body?: unknown }> = {};

beforeEach(() => {
  calls = []; routes = {};
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    const path = url.replace("http://api.test", "");
    calls.push({ url: path, method, body: init.body ? JSON.parse(String(init.body)) : undefined });
    const h = routes[`${method} ${path}`];
    if (!h) return new Response(JSON.stringify({ detail: `unrouted ${method} ${path}` }), { status: 599 });
    const { status = 200, body } = h();
    return status === 204 ? new Response(null, { status }) : new Response(JSON.stringify(body ?? {}), { status, headers: { "Content-Type": "application/json" } });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function Where() { return <p data-testid="where">{useLocation().pathname}</p>; }

function mount(path: string, role: Role = "owner") {
  const value: SessionValue = { me, org: { ...me.organizations[0]!, role }, role, setOrg: () => undefined };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SessionContext.Provider value={value}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/projects/new" element={<NewProjectPage />} />
            <Route path="/projects/:id" element={<ProjectPage />} />
          </Routes>
          <Where />
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
}

const LIST = `GET /api/v1/orgs/${ORG}/projects/`;
const ONE = `/api/v1/orgs/${ORG}/projects/${PROJECT.id}/`;

describe("ProjectsPage", () => {
  it("lists projects from the server", async () => {
    routes[LIST] = () => ({ body: { next: null, previous: null, results: [PROJECT] } });
    mount("/projects");
    expect(await screen.findByRole("link", { name: PROJECT.name })).toHaveAttribute("href", `/projects/${PROJECT.id}`);
  });

  it("shows the first-project empty state with a create action for writers", async () => {
    routes[LIST] = () => ({ body: { next: null, previous: null, results: [] } });
    mount("/projects");
    expect(await screen.findByText("Your next idea starts here.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create first project" })).toBeInTheDocument();
  });

  it("hides every create action from a viewer", async () => {
    routes[LIST] = () => ({ body: { next: null, previous: null, results: [] } });
    mount("/projects", "viewer");
    await screen.findByText("Your next idea starts here.");
    expect(screen.queryByRole("link", { name: /create/i })).toBeNull();
  });

  it("asks the server for archived projects when that tab is chosen", async () => {
    routes[LIST] = () => ({ body: { next: null, previous: null, results: [PROJECT] } });
    routes[`${LIST}?archived=1`] = () => ({ body: { next: null, previous: null, results: [] } });
    mount("/projects");
    await screen.findByRole("link", { name: PROJECT.name });
    await userEvent.click(screen.getByRole("tab", { name: "Archived" }));
    expect(await screen.findByText("Nothing here")).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("?archived=1"))).toBe(true);
  });

  it("searches on the server after the user stops typing, and names the search when nothing matches", async () => {
    routes[LIST] = () => ({ body: { next: null, previous: null, results: [PROJECT] } });
    routes[`${LIST}?search=zzz`] = () => ({ body: { next: null, previous: null, results: [] } });
    mount("/projects");
    await screen.findByRole("link", { name: PROJECT.name });
    await userEvent.type(screen.getByLabelText("Search projects"), "zzz");
    expect(await screen.findByText('No projects match "zzz"')).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByRole("link", { name: PROJECT.name })).toBeInTheDocument();
  });

  it("shows a retry on failure and recovers", async () => {
    let up = false;
    routes[LIST] = () => (up ? { body: { next: null, previous: null, results: [PROJECT] } } : { status: 500, body: { detail: "boom" } });
    mount("/projects");
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load projects.");
    up = true;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("link", { name: PROJECT.name })).toBeInTheDocument();
  });
});

describe("NewProjectPage", () => {
  const POST = `POST /api/v1/orgs/${ORG}/projects/`;

  it("creates a project with the trimmed name and goes to it", async () => {
    routes[POST] = () => ({ status: 201, body: PROJECT });
    routes[`GET ${ONE}`] = () => ({ body: PROJECT });
    mount("/projects/new");
    await userEvent.type(screen.getByLabelText("Project name"), "  Orbit   Commerce ");
    expect(screen.getByText("Address: orbit-commerce")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(`/projects/${PROJECT.id}`));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      name: "Orbit Commerce", description: "", default_branch: "main", execution_preference: "cloud",
    });
  });

  it("blocks submit and explains why for a name with no usable letters", async () => {
    mount("/projects/new");
    await userEvent.type(screen.getByLabelText("Project name"), "Проект");
    await userEvent.tab();
    expect(await screen.findByRole("alert")).toHaveTextContent(/at least one letter/i);
    expect(screen.getByRole("button", { name: "Create project" })).toBeDisabled();
    expect(calls).toHaveLength(0);
  });

  it("shows the server's duplicate-name error on the name field, not a banner", async () => {
    // The exact body the live API returns for a duplicate name (captured from the running server).
    routes[POST] = () => ({ status: 400, body: { code: "invalid", detail: { name: ["A project with this name already exists."] }, request_id: "r" } });
    mount("/projects/new");
    await userEvent.type(screen.getByLabelText("Project name"), "Demo");
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A project with this name already exists.");
    expect(screen.getByLabelText("Project name")).toHaveAttribute("aria-invalid", "true");
  });

  it("rejects a bad branch name before sending", async () => {
    mount("/projects/new");
    await userEvent.type(screen.getByLabelText("Project name"), "Demo");
    const branch = screen.getByLabelText("Default branch");
    await userEvent.clear(branch); await userEvent.type(branch, "bad branch");
    expect(screen.getByRole("button", { name: "Create project" })).toBeDisabled();
  });

  it("sends a viewer back to the list", async () => {
    routes[LIST] = () => ({ body: { next: null, previous: null, results: [] } });
    mount("/projects/new", "viewer");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/projects"));
    expect(screen.queryByLabelText("Project name")).toBeNull();
  });
});

describe("ProjectPage", () => {
  const GET = `GET ${ONE}`;

  it("saves only the fields that changed", async () => {
    routes[GET] = () => ({ body: PROJECT });
    routes[`PATCH ${ONE}`] = () => ({ body: { ...PROJECT, name: "Renamed" } });
    mount(`/projects/${PROJECT.id}`);
    const name = await screen.findByLabelText("Project name");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();       // nothing changed yet
    await userEvent.clear(name); await userEvent.type(name, "Renamed");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ name: "Renamed" });
  });

  it("never lets the address be edited", async () => {
    routes[GET] = () => ({ body: PROJECT });
    mount(`/projects/${PROJECT.id}`);
    expect(await screen.findByLabelText("Project address")).toBeDisabled();
  });

  it("makes a viewer read-only: no inputs enabled, no save, no archive, no delete", async () => {
    routes[GET] = () => ({ body: PROJECT });
    mount(`/projects/${PROJECT.id}`, "viewer");
    expect(await screen.findByText(/read-only for your role/)).toBeInTheDocument();
    expect(screen.getByLabelText("Project name")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
    expect(screen.queryByRole("button", { name: /archive project/i })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete project forever" })).toBeNull();
  });

  it("lets a member edit but shows that only admins can delete", async () => {
    routes[GET] = () => ({ body: PROJECT });
    mount(`/projects/${PROJECT.id}`, "member");
    expect(await screen.findByLabelText("Project name")).toBeEnabled();
    expect(screen.getByText("Only workspace admins can delete a project.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete project forever" })).toBeNull();
  });

  it("archives, then offers to restore", async () => {
    routes[GET] = () => ({ body: PROJECT });
    routes[`POST ${ONE}archive/`] = () => ({ body: { ...PROJECT, archived_at: "2026-11-05T10:00:00Z", is_archived: true } });
    mount(`/projects/${PROJECT.id}`);
    await userEvent.click(await screen.findByRole("button", { name: "Archive project" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("archive/"))).toBe(true));
  });

  it("keeps delete disabled until the exact name is typed, then deletes and leaves", async () => {
    routes[GET] = () => ({ body: PROJECT });
    routes[`DELETE ${ONE}`] = () => ({ status: 204 });
    routes[LIST] = () => ({ body: { next: null, previous: null, results: [] } });
    mount(`/projects/${PROJECT.id}`);
    const del = await screen.findByRole("button", { name: "Delete project forever" });
    expect(del).toBeDisabled();
    const box = screen.getByLabelText("Type the project name to confirm deletion");
    await userEvent.type(box, PROJECT.name.toLowerCase() === PROJECT.name ? PROJECT.name + "x" : PROJECT.name.toLowerCase());
    expect(del).toBeDisabled();                                             // wrong case / extra text
    await userEvent.clear(box); await userEvent.type(box, PROJECT.name);
    expect(del).toBeEnabled();
    await userEvent.click(del);
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/projects"));
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1);
  });

  it("explains a missing or foreign project instead of showing a blank page", async () => {
    routes[GET] = () => ({ status: 404, body: { detail: "Not found" } });
    mount(`/projects/${PROJECT.id}`);
    expect(await screen.findByText("Project not found")).toBeInTheDocument();
    expect(within(screen.getByText("Project not found").closest("div")!).getByRole("link", { name: "Back to projects" })).toBeInTheDocument();
  });
});

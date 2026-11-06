import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import real from "./real_me.fixture.json";
import { AppHeader } from "./AppHeader";
import { SessionContext, type SessionValue } from "./context";
import { MeSchema } from "./schemas";

const signOut = vi.hoisted(() => vi.fn(async () => undefined));
vi.mock("@/lib/auth", () => ({ signOut }));

afterEach(() => { cleanup(); signOut.mockClear(); });

const me = MeSchema.parse(real.me);
const two = MeSchema.parse({
  ...real.me,
  organizations: [
    { id: "o1", name: "Acme", slug: "acme", plan: "free", role: "owner" },
    { id: "o2", name: "Globex", slug: "globex", plan: "free", role: "viewer" },
  ],
});

function mount(value: SessionValue | null) {
  const client = new QueryClient();
  const spy = vi.spyOn(client, "clear");
  render(
    <QueryClientProvider client={client}>
      <SessionContext.Provider value={value}>
        <MemoryRouter><AppHeader /></MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
  return { spy };
}

const value = (m = me, orgIndex = 0, setOrg = vi.fn()): SessionValue => ({
  me: m, org: m.organizations[orgIndex]!, role: m.organizations[orgIndex]!.role, setOrg,
});

describe("AppHeader", () => {
  it("shows only the brand when signed out: no navigation, no account menu", () => {
    mount(null);
    expect(screen.getByText("Veritas Bot")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("button", { name: "Account menu" })).toBeNull();
  });

  it("shows navigation to every main area when signed in", () => {
    mount(value());
    const nav = screen.getByRole("navigation", { name: "Primary" });
    for (const label of ["Dashboard", "Projects", "Studio", "Providers"]) {
      expect(nav).toHaveTextContent(label);
    }
  });

  it("shows the workspace name as plain text when there is only one", () => {
    mount(value());
    expect(screen.getByText(me.organizations[0]!.name)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("offers a workspace switcher with several, and switching clears cached data", async () => {
    const setOrg = vi.fn();
    const { spy } = mount(value(two, 0, setOrg));
    const select = screen.getByRole("combobox");
    expect(select).toHaveValue("o1");
    await userEvent.selectOptions(select, "o2");
    expect(setOrg).toHaveBeenCalledWith("o2");
    expect(spy).toHaveBeenCalled();        // another workspace's projects must not linger on screen
  });

  it("shows who you are and your role, and signs out", async () => {
    mount(value(two, 1));
    await userEvent.click(screen.getByRole("button", { name: "Account menu" }));
    const menu = screen.getByRole("menu");
    expect(menu).toHaveTextContent(me.profile.email);
    expect(menu).toHaveTextContent(/viewer in Globex/i);
    await userEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it("does not show a made-up status label", () => {
    mount(value());
    expect(screen.queryByText("local")).toBeNull();
  });
});

import { describe, expect, it } from "vitest";
import real from "./real_me.fixture.json";
import { atLeast, canAdminister, canWrite, chooseOrg } from "./access";
import { DashboardSummarySchema, MeSchema } from "./schemas";

describe("session schemas against REAL backend responses", () => {
  it("parses /me/", () => {
    const me = MeSchema.parse(real.me);
    expect(me.organizations[0]?.role).toBe("owner");
  });
  it("parses the response of creating a workspace", () => {
    expect(MeSchema.parse(real.created).organizations).toHaveLength(1);
  });
  it("parses an empty dashboard summary", () => {
    DashboardSummarySchema.parse(real.summary);
  });
  it("parses a dashboard summary that has a run in it", () => {
    const parsed = DashboardSummarySchema.parse(real.summary_full);
    expect(parsed.recent_runs[0]?.status).toBe("queued");
    expect(typeof parsed.spend_this_month_usd).toBe("string");
  });
  it("rejects spend sent as a number", () => {
    expect(() => DashboardSummarySchema.parse({ ...real.summary, spend_this_month_usd: 0.3 })).toThrow();
  });
  it("rejects an unknown role", () => {
    const bad = { ...real.me, organizations: [{ ...real.me.organizations[0], role: "superuser" }] };
    expect(() => MeSchema.parse(bad)).toThrow();
  });
});

describe("role helpers", () => {
  it("orders roles", () => {
    expect(atLeast("owner", "admin")).toBe(true);
    expect(atLeast("member", "admin")).toBe(false);
    expect(atLeast(undefined, "viewer")).toBe(false);
  });
  it("viewers cannot write; admins can administer", () => {
    expect(canWrite("viewer")).toBe(false);
    expect(canWrite("member")).toBe(true);
    expect(canAdminister("member")).toBe(false);
    expect(canAdminister("admin")).toBe(true);
  });
});

describe("chooseOrg", () => {
  const orgs = MeSchema.parse({
    ...real.me,
    organizations: [
      { id: "a", name: "A", slug: "a", plan: "free", role: "owner" },
      { id: "b", name: "B", slug: "b", plan: "free", role: "viewer" },
    ],
  }).organizations;
  it("keeps the stored workspace while the user still belongs to it", () => {
    expect(chooseOrg(orgs, "b")?.id).toBe("b");
  });
  it("falls back to the first when the stored id was revoked or is stale", () => {
    expect(chooseOrg(orgs, "gone")?.id).toBe("a");
    expect(chooseOrg(orgs, null)?.id).toBe("a");
  });
  it("returns null when there are no workspaces", () => {
    expect(chooseOrg([], "a")).toBeNull();
  });
});

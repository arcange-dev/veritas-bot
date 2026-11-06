import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import { decideGate, type GateInput } from "./gate";
import real from "./real_me.fixture.json";
import { MeSchema } from "./schemas";

const me = MeSchema.parse(real.me);
const base: GateInput = {
  configured: true, signedIn: true, me, meLoading: false, meError: undefined, storedOrgId: null,
};
const decide = (over: Partial<GateInput>) => decideGate({ ...base, ...over });

describe("decideGate", () => {
  it("says unconfigured before anything else, since nobody can sign in", () => {
    expect(decide({ configured: false, signedIn: true }).kind).toBe("unconfigured");
  });
  it("waits while it does not yet know whether there is a session", () => {
    expect(decide({ signedIn: null }).kind).toBe("checking");
  });
  it("sends a signed-out visitor to login", () => {
    expect(decide({ signedIn: false, me: undefined }).kind).toBe("signed_out");
  });
  it("treats a 401 from the API as signed out, even though a session exists", () => {
    const s = decide({ me: undefined, meError: new ApiError(401, "unauthenticated", "x") });
    expect(s.kind).toBe("signed_out");
  });
  it("waits while /me is loading", () => {
    expect(decide({ me: undefined, meLoading: true }).kind).toBe("checking");
  });
  it("marks a server failure retryable", () => {
    const s = decide({ me: undefined, meError: new ApiError(503, "x", "down") });
    expect(s).toMatchObject({ kind: "error", retryable: true, message: "down" });
  });
  it("marks a network failure retryable", () => {
    const s = decide({ me: undefined, meError: new ApiError(0, "network_error", "offline") });
    expect(s).toMatchObject({ kind: "error", retryable: true });
  });
  it("does not offer retry for a 403", () => {
    const s = decide({ me: undefined, meError: new ApiError(403, "forbidden", "no") });
    expect(s).toMatchObject({ kind: "error", retryable: false });
  });
  it("gives an unknown error a generic message, never the raw object", () => {
    const s = decide({ me: undefined, meError: { weird: true } });
    expect(s).toMatchObject({ kind: "error", message: "Could not load your account." });
  });
  it("asks a user with no workspace to create one", () => {
    const s = decide({ me: { ...me, organizations: [] } });
    expect(s.kind).toBe("no_workspace");
  });
  it("is ready with the first workspace by default", () => {
    const s = decide({});
    expect(s.kind).toBe("ready");
    if (s.kind === "ready") expect(s.org.id).toBe(me.organizations[0]?.id);
  });
  it("ignores a stored workspace the user no longer belongs to", () => {
    const s = decide({ storedOrgId: "revoked-or-stale" });
    if (s.kind === "ready") expect(s.org.id).toBe(me.organizations[0]?.id);
    else throw new Error("expected ready");
  });
});

import { describe, expect, it } from "vitest";
import { changedFields, checkBranch, checkProjectName, deleteConfirmed, isPristine, previewSlug } from "./rules";

describe("checkProjectName", () => {
  it("trims and collapses whitespace", () => {
    expect(checkProjectName("  Orbit    Commerce ")).toEqual({ ok: true, name: "Orbit Commerce" });
  });
  it.each(["", " ", "a"])("rejects %j as too short", (v) => {
    expect(checkProjectName(v)).toMatchObject({ ok: false });
  });
  it("rejects over 64 characters but accepts exactly 64", () => {
    expect(checkProjectName("a".repeat(65)).ok).toBe(false);
    expect(checkProjectName("a".repeat(64)).ok).toBe(true);
  });
  it("rejects a name with no letters or numbers, matching the server", () => {
    expect(checkProjectName("!!!???")).toMatchObject({ ok: false });
  });
  it("rejects a name that cannot produce an address, as the server does", () => {
    expect(checkProjectName("Проект Альфа")).toMatchObject({ ok: false });
    expect(checkProjectName("项目")).toMatchObject({ ok: false });
  });
  it("accepts a non-latin name that also contains latin letters or digits", () => {
    expect(checkProjectName("Проект Alpha").ok).toBe(true);
    expect(checkProjectName("Проект 2").ok).toBe(true);
  });
});

describe("previewSlug", () => {
  it.each([
    ["Orbit Commerce", "orbit-commerce"],
    ["  Hello,   World!! ", "hello-world"],
    ["Café Münch", "cafe-munch"],
    ["a_b-c", "a_b-c"],
    ["a  b", "a-b"],
    ["--x--", "x"],
    ["A.B.C", "abc"],
    ["C++ Lab", "c-lab"],
    ["Проект Альфа", ""],
    ["!!!", ""],
  ])("%s -> %s", (n, s) => expect(previewSlug(n)).toBe(s));
});

describe("deleteConfirmed", () => {
  it("needs the exact name", () => {
    expect(deleteConfirmed("Orbit Commerce", "Orbit Commerce")).toBe(true);
    expect(deleteConfirmed("  Orbit Commerce  ", "Orbit Commerce")).toBe(true);
  });
  it("is case-sensitive and rejects partial matches", () => {
    expect(deleteConfirmed("orbit commerce", "Orbit Commerce")).toBe(false);
    expect(deleteConfirmed("Orbit", "Orbit Commerce")).toBe(false);
    expect(deleteConfirmed("", "Orbit Commerce")).toBe(false);
  });
  it("never confirms against an empty project name", () => {
    expect(deleteConfirmed("", "")).toBe(false);
  });
});

describe("changedFields", () => {
  const base = { name: "A", description: "d", default_branch: "main", execution_preference: "cloud" as const };
  it("returns only what changed", () => {
    expect(changedFields(base, { ...base, name: "B" })).toEqual({ name: "B" });
    expect(changedFields(base, base)).toEqual({});
  });
});

describe("isPristine", () => {
  it("is true until something is typed", () => {
    expect(isPristine({ name: " ", description: "" })).toBe(true);
    expect(isPristine({ name: "x", description: "" })).toBe(false);
  });
});

describe("checkBranch", () => {
  it.each(["main", "feature/checkout", "release-1.2", "fix/stock-lock"])("accepts %s", (b) => {
    expect(checkBranch(b).ok).toBe(true);
  });
  it.each(["", " ", "a b", "a..b", "/lead", "trail/", "x.lock", "a//b", "a~b", "a:b", "a?b"])("rejects %j", (b) => {
    expect(checkBranch(b).ok).toBe(false);
  });
});

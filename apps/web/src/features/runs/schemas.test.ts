import { describe, expect, it } from "vitest";
import real from "./real_run.fixture.json";
import { RunDetailSchema, RunSchema, TERMINAL } from "./schemas";

describe("run schemas against a REAL backend response", () => {
  it("parses the run detail the Django API actually returned", () => {
    const parsed = RunDetailSchema.parse(real.detail);
    expect(parsed.status).toBe("succeeded");
    expect(parsed.plan.length).toBeGreaterThan(0);
    expect(parsed.steps.length).toBeGreaterThan(0);
  });

  it("parses every run in the real list response", () => {
    expect(real.list.results.length).toBeGreaterThan(0);
    for (const item of real.list.results) RunSchema.parse(item);
  });

  it("keeps money as an exact decimal string, not a float", () => {
    const parsed = RunDetailSchema.parse(real.detail);
    expect(typeof parsed.cost_usd).toBe("string");
    expect(parsed.cost_usd).toBe(real.detail.cost_usd);
  });

  it("rejects a numeric cost, which would lose precision", () => {
    expect(() => RunSchema.parse({ ...real.detail, cost_usd: 0.004 })).toThrow();
  });

  it("rejects a status the backend never sends", () => {
    expect(() => RunSchema.parse({ ...real.detail, status: "exploded" })).toThrow();
  });

  it("treats exactly the four finished states as terminal", () => {
    expect([...TERMINAL].sort()).toEqual(["cancelled", "failed", "needs_review", "succeeded"]);
  });
});

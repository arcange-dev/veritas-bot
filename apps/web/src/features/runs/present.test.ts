import { describe, expect, it } from "vitest";
import {
  availableControls, blockedBy, errorMessage, expiresIn, formatUsd,
  planProgress, spendPercent, toMicros,
} from "./present";
import type { PlanTask } from "./schemas";

const task = (id: string, state: string, depends_on: string[] = []): PlanTask => ({
  id, title: id, agent: "backend", state, depends_on, write_scope: [],
});

describe("money", () => {
  it("converts decimal strings to micro-dollars exactly", () => {
    expect(toMicros("0.004000")).toBe(4000);
    expect(toMicros("5.000000")).toBe(5_000_000);
    expect(toMicros("0.1")).toBe(100_000);
    expect(toMicros("-1.5")).toBe(-1_500_000);
  });

  it("is exact where floating point is not", () => {
    // 0.1 + 0.2 !== 0.3 in floats. In micro-dollars it is exact.
    expect(toMicros("0.1") + toMicros("0.2")).toBe(toMicros("0.3"));
  });

  it("shows sub-cent spend instead of rounding it to $0.00", () => {
    expect(formatUsd("0.004000")).toBe("$0.0040");
    expect(formatUsd("0.000000")).toBe("$0.00");
    expect(formatUsd("5.000000")).toBe("$5.00");
    expect(formatUsd("0.072000")).toBe("$0.07");
  });

  it("computes spend percent, clamped, with no divide by zero", () => {
    expect(spendPercent("2.5", "5")).toBe(50);
    expect(spendPercent("9", "5")).toBe(100);
    expect(spendPercent("0", "5")).toBe(0);
    expect(spendPercent("1", "0")).toBe(100);
  });
});

describe("controls", () => {
  it("offers nothing on a finished run", () => {
    for (const s of ["succeeded", "failed", "cancelled", "needs_review"] as const)
      expect(availableControls(s)).toEqual([]);
  });
  it("offers resume, not pause, on a paused run", () => {
    expect(availableControls("paused")).toEqual(["resume", "cancel"]);
  });
  it("only allows cancel while queued", () => {
    expect(availableControls("queued")).toEqual(["cancel"]);
  });
  it("offers pause and cancel while running", () => {
    expect(availableControls("running")).toEqual(["pause", "cancel"]);
  });
});

describe("errors", () => {
  it("translates known codes", () => {
    expect(errorMessage("spend_cap_exceeded")).toMatch(/spending limit/);
  });
  it("never shows an unknown code raw", () => {
    expect(errorMessage("zz_internal_xyz")).toBe("The run stopped unexpectedly.");
    expect(errorMessage("zz_internal_xyz")).not.toMatch(/zz_internal/);
  });
  it("returns null when there is no error", () => {
    expect(errorMessage("")).toBeNull();
  });
});

describe("plan", () => {
  const plan = [task("a", "done"), task("b", "running", ["a"]), task("c", "pending", ["a", "b"]), task("d", "failed")];
  it("counts progress", () => {
    expect(planProgress(plan)).toEqual({ total: 4, done: 1, failed: 1, running: 1 });
  });
  it("lists only unfinished dependencies", () => {
    expect(blockedBy(plan[2]!, plan)).toEqual(["b"]);
    expect(blockedBy(plan[1]!, plan)).toEqual([]);
  });
  it("treats an empty plan as zero progress, not complete", () => {
    expect(planProgress([])).toEqual({ total: 0, done: 0, failed: 0, running: 0 });
  });
});

describe("approval expiry", () => {
  const now = new Date("2026-11-03T10:00:00Z");
  it("formats minutes and hours", () => {
    expect(expiresIn("2026-11-03T10:30:00Z", now)).toBe("30 min");
    expect(expiresIn("2026-11-03T12:15:00Z", now)).toBe("2 h 15 min");
  });
  it("returns null once expired or invalid", () => {
    expect(expiresIn("2026-11-03T09:59:00Z", now)).toBeNull();
    expect(expiresIn("not a date", now)).toBeNull();
  });
});

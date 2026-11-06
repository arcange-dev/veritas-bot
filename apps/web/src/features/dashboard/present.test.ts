import { describe, expect, it } from "vitest";
import { capUsedPercent, greetingName, statusCount, timeAgo } from "./present";

const now = new Date("2026-11-05T12:00:00Z");

describe("timeAgo", () => {
  it.each([
    ["2026-11-05T11:59:50Z", "just now"],
    ["2026-11-05T12:00:30Z", "just now"],       // server clock slightly ahead
    ["2026-11-05T11:55:00Z", "5 min ago"],
    ["2026-11-05T09:00:00Z", "3 h ago"],
    ["2026-11-02T12:00:00Z", "3 d ago"],
  ])("%s -> %s", (iso, expected) => expect(timeAgo(iso, now)).toBe(expected));
  it("returns an empty string for garbage rather than 'NaN min ago'", () => {
    expect(timeAgo("not a date", now)).toBe("");
  });
  it("uses a calendar date for old items", () => {
    expect(timeAgo("2026-01-02T12:00:00Z", now)).toMatch(/2026/);
  });
});

describe("capUsedPercent", () => {
  it("computes the share exactly from decimal strings", () => {
    expect(capUsedPercent("12.5", "50")).toBe(25);
    expect(capUsedPercent("0.3", "0.6")).toBe(50);
  });
  it("clamps at 100", () => expect(capUsedPercent("80", "50")).toBe(100));
  it("is unknown (null), not 100%, when there is no cap", () => {
    expect(capUsedPercent("5", null)).toBeNull();
    expect(capUsedPercent("5", "0")).toBeNull();
    expect(capUsedPercent("5", undefined)).toBeNull();
  });
});

describe("statusCount", () => {
  it("sums only the requested statuses and treats missing as zero", () => {
    expect(statusCount({ running: 2, queued: 1, failed: 5 }, "running", "queued", "paused")).toBe(3);
    expect(statusCount({}, "running")).toBe(0);
  });
});

describe("greetingName", () => {
  it("prefers the first word of the display name", () => expect(greetingName("Ada Lovelace", "x@y.io")).toBe("Ada"));
  it("falls back to the email local part", () => expect(greetingName("  ", "ada.l@y.io")).toBe("ada.l"));
  it("never invents a name", () => expect(greetingName("", "")).toBe(""));
});

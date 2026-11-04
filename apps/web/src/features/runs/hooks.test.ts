import { describe, expect, it } from "vitest";
import { POLL_ACTIVE_MS, POLL_WAITING_MS, pollInterval } from "./hooks";

describe("pollInterval", () => {
  it.each(["succeeded", "failed", "cancelled", "needs_review"] as const)(
    "stops polling once the run is %s",
    (status) => expect(pollInterval(status)).toBe(false),
  );

  it.each(["queued", "running"] as const)("polls quickly while %s", (status) =>
    expect(pollInterval(status)).toBe(POLL_ACTIVE_MS),
  );

  it.each(["waiting_approval", "paused"] as const)("polls slowly while %s", (status) =>
    expect(pollInterval(status)).toBe(POLL_WAITING_MS),
  );

  it("keeps polling before the first response arrives", () => {
    expect(pollInterval(undefined)).toBe(POLL_ACTIVE_MS);
  });
});

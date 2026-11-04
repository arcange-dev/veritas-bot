import { describe, expect, it } from "vitest";
import { LIMITS, useLayout } from "@/stores/layout";

describe("studio layout store", () => {
  it("clamps a dragged panel to its limits", () => {
    useLayout.getState().setSize("left", 10_000);
    expect(useLayout.getState().left).toBe(LIMITS.left.max);
    useLayout.getState().setSize("left", 1);
    expect(useLayout.getState().left).toBe(LIMITS.left.min);
  });

  it("resets every panel", () => {
    useLayout.getState().setSize("right", 500);
    useLayout.getState().reset();
    expect(useLayout.getState().right).toBe(LIMITS.right.default);
  });

  it("toggles a panel without losing its size", () => {
    useLayout.getState().setSize("bottom", 300);
    useLayout.getState().toggle("bottom");
    expect(useLayout.getState().collapsed.bottom).toBe(true);
    expect(useLayout.getState().bottom).toBe(300);
  });
});

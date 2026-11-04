import { describe, expect, it } from "vitest";

import { emptyBuffer, firstMissing, ingest, ingestAll } from "./streamBuffer";
import type { TermFrame } from "./TerminalHost";

const frame = (seq: number, data = `line ${seq}\n`): TermFrame => ({
  stream: "stdout",
  seq,
  data,
});

describe("terminal stream buffer", () => {
  it("keeps frames in seq order and advances the cursor", () => {
    const state = ingestAll(emptyBuffer, [frame(2), frame(1), frame(3)]);
    expect(state.frames.map((f) => f.seq)).toEqual([1, 2, 3]);
    expect(state.cursor).toBe(3);
    expect(state.gap).toBe(false);
  });

  it("drops duplicates from a reconnect instead of double-printing", () => {
    const first = ingestAll(emptyBuffer, [frame(1), frame(2)]);
    const again = ingestAll(first, [frame(2), frame(3)]);
    expect(again.frames.map((f) => f.seq)).toEqual([1, 2, 3]);
  });

  it("records a gap when a sequence number is skipped", () => {
    const state = ingestAll(emptyBuffer, [frame(1), frame(4)]);
    expect(state.gap).toBe(true);
    expect(firstMissing(state)).not.toBeNull();
  });

  it("ignores frames with a non-numeric seq", () => {
    const state = ingest(emptyBuffer, { stream: "stdout", seq: NaN, data: "x" });
    expect(state).toBe(emptyBuffer);
  });
});

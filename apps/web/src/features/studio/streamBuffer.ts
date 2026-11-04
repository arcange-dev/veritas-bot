/**
 * Ordering rules for the terminal stream.
 *
 * Frames arrive over a socket, so they can be duplicated on reconnect, arrive
 * out of order after a replay, or skip ahead if the buffered backlog was
 * trimmed. Swallowing any of those silently would make a failing build look
 * clean, so gaps are reported rather than hidden.
 */
import type { TermFrame } from "./TerminalHost";

export interface BufferState {
  frames: TermFrame[];
  /** Highest seq consumed so far, or -1 before the first frame. */
  cursor: number;
  /** True when a seq was skipped: the transcript is known to be incomplete. */
  gap: boolean;
}

export const emptyBuffer: BufferState = { frames: [], cursor: -1, gap: false };

const MAX_FRAMES = 5000;

export function ingest(state: BufferState, incoming: TermFrame): BufferState {
  if (!Number.isFinite(incoming.seq) || incoming.seq <= state.cursor) {
    return state; // duplicate or stale replay
  }

  // The very first frame is never a gap, whatever its sequence number:
  // streams may legitimately start at any offset.
  const gap = state.gap || (state.cursor >= 0 && incoming.seq > state.cursor + 1);
  const frames = [...state.frames, incoming].slice(-MAX_FRAMES);

  return { frames, cursor: incoming.seq, gap };
}

export function ingestAll(state: BufferState, batch: TermFrame[]): BufferState {
  return [...batch]
    .sort((a, b) => a.seq - b.seq)
    .reduce<BufferState>((acc, frame) => ingest(acc, frame), state);
}

/** First sequence number missing from the transcript, or null when contiguous. */
export function firstMissing(state: BufferState): number | null {
  const first = state.frames.at(0);
  if (!first) return null;
  for (let i = 1; i < state.frames.length; i += 1) {
    const previous = state.frames[i - 1];
    const current = state.frames[i];
    if (previous && current && current.seq !== previous.seq + 1) {
      return previous.seq + 1;
    }
  }
  return null;
}

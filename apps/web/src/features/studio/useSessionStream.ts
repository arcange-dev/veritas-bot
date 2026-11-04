/**
 * Live terminal stream for one execution session.
 *
 * Reconnects with capped backoff and re-uses the buffer's dedupe rules, so a
 * flaky connection shows a duplicate-free transcript rather than a mangled one.
 */
import { useEffect, useRef, useState } from "react";

import { env } from "@/lib/env";
import { type BufferState, emptyBuffer, ingest } from "./streamBuffer";
import type { TermFrame } from "./TerminalHost";

const MAX_BACKOFF_MS = 10_000;

export interface StreamState {
  buffer: BufferState;
  live: boolean;
  error: string | null;
}

export function useSessionStream(sessionId: string | null, token: string | null): StreamState {
  const [state, setState] = useState<StreamState>({ buffer: emptyBuffer, live: false, error: null });
  const attemptRef = useRef(0);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!sessionId || !token) return;

    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (disposed) return;
      const url = `${env.wsBaseUrl}/ws/sessions/${sessionId}/?token=${encodeURIComponent(token)}`;
      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => {
        attemptRef.current = 0;
        setState((prev) => ({ ...prev, live: true, error: null }));
      };

      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(String(event.data)) as Partial<TermFrame>;
          if (payload.seq === undefined || payload.seq === null) return;
          const frame: TermFrame = {
            stream: payload.stream ?? "stdout",
            seq: Number(payload.seq),
            data: String(payload.data ?? ""),
          };
          setState((prev) => ({ ...prev, buffer: ingest(prev.buffer, frame) }));
        } catch {
          // A malformed frame must not kill the terminal.
        }
      };

      socket.onclose = (event) => {
        setState((prev) => ({ ...prev, live: false }));
        if (disposed || event.code === 4401 || event.code === 4403) return;
        const delay = Math.min(MAX_BACKOFF_MS, 500 * 2 ** attemptRef.current);
        attemptRef.current += 1;
        timer = setTimeout(connect, delay);
      };

      socket.onerror = () => {
        setState((prev) => ({ ...prev, error: "stream connection failed" }));
      };
    };

    connect();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [sessionId, token]);

  return state;
}

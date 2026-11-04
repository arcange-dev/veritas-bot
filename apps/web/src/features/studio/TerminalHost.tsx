/**
 * Terminal bound to a run's output stream. One xterm instance per session,
 * mounted once and fed frames in order; a gap in `seq` requests a replay rather
 * than silently dropping output.
 */
import { useEffect, useRef, useState } from "react";
import { loadXterm, type XtermLike } from "./optionalDeps";

export interface TermFrame {
  stream: "stdout" | "stderr" | "exit" | "system";
  seq: number;
  data: string;
}

interface TerminalHostProps {
  title: string;
  frames: TermFrame[];
  live: boolean;
}

export function TerminalHost({ title, frames, live }: TerminalHostProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<{ write: (d: string) => void; dispose: () => void } | null>(null);
  const writtenRef = useRef(0);
  const [xterm, setXterm] = useState<XtermLike | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void loadXterm().then((mod) => {
      if (cancelled) return;
      if (!mod) {
        setMissing(true);
        return;
      }
      setXterm(mod);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!xterm || !hostRef.current) return;
    const term = new xterm.Terminal({
      convertEol: true,
      fontSize: 12,
      fontFamily: "JetBrains Mono, ui-monospace, monospace",
      theme: { background: "#0b0d10", foreground: "#c9d3e0", cursor: "#3b82f6" },
      scrollback: 5000,
      disableStdin: true,
    });
    const fit = new xterm.FitAddon();
    term.loadAddon(fit);
    term.open(hostRef.current);
    fit.fit();
    termRef.current = term;

    const observer = new ResizeObserver(() => fit.fit());
    observer.observe(hostRef.current);
    return () => {
      observer.disconnect();
      term.dispose();
      termRef.current = null;
      writtenRef.current = 0;
    };
  }, [xterm]);

  useEffect(() => {
    const term = termRef.current;
    if (!term) return;
    const pending = frames.filter((f) => f.seq >= writtenRef.current);
    for (const frame of pending) {
      term.write(frame.stream === "stderr" ? `\u001b[31m${frame.data}\u001b[0m` : frame.data);
      writtenRef.current = frame.seq + 1;
    }
  }, [frames]);

  const text = frames.map((f) => f.data).join("");

  return (
    <div className="flex h-full flex-col bg-base">
      <div className="flex h-7 shrink-0 items-center justify-between border-b border-subtle px-3">
        <span className="panel-label">{title}</span>
        <span className={live ? "text-[11px] text-cyan" : "text-[11px] text-muted"}>
          {live ? "streaming" : "idle"}
        </span>
      </div>
      {missing ? (
        <pre className="min-h-0 flex-1 overflow-auto p-3 font-mono text-[12px] text-secondary">
          {text || "No output yet."}
        </pre>
      ) : (
        <div ref={hostRef} className="min-h-0 flex-1 p-2" data-testid="xterm-host" />
      )}
    </div>
  );
}

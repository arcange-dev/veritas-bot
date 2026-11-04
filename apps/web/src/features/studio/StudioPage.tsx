/**
 * The Developer Studio shell. Five regions, all resizable, all with their own
 * scroll and error boundary so one crashed panel cannot blank the workspace.
 */
import { useCallback, useMemo, useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileCode2, FolderTree, GitBranch } from "lucide-react";
import { api, type Project } from "@/lib/api";
import { cn } from "@/lib/cn";
import { EmptyState, Panel, StatusChip } from "@/components/ui/Panel";
import { Splitter } from "@/components/ui/Splitter";
import { useLayout } from "@/stores/layout";
import { useSearchParams } from "react-router-dom";

import { useSession } from "@/stores/session";
import { getAccessToken } from "@/lib/auth";
import { EditorHost } from "./EditorHost";
import { TerminalHost, type TermFrame } from "./TerminalHost";
import { AgentPanel } from "@/features/runs/AgentPanel";
import { PlanApprovals } from "@/features/runs/PlanApprovals";
import { useSessionStream } from "./useSessionStream";
import { StudioToolbar } from "./StudioToolbar";

const SAMPLE_FILES = ["README.md", "apps/api/config/settings/base.py", "apps/web/src/main.tsx"];

const LANGUAGE_BY_EXT: Record<string, string> = {
  ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
  py: "python", md: "markdown", json: "json", css: "css", sql: "sql", yml: "yaml",
};

const languageFor = (path: string): string =>
  LANGUAGE_BY_EXT[path.split(".").pop() ?? ""] ?? "plaintext";

export function StudioPage() {
  const orgId = useSession((s) => s.orgId);
  const { left, right, bottom, collapsed } = useLayout();
  const [activeFile, setActiveFile] = useState<string | null>(SAMPLE_FILES[0] ?? null);
  const [buffer, setBuffer] = useState("# Veritas Bot\n\nOpen a file to begin editing.\n");
  // Terminal output is a live session stream. `?session=<id>` attaches the
  // panel to that session; with no session the panel shows the boot line
  // instead of inventing progress we cannot prove.
  const [search, setSearch] = useSearchParams();
  const sessionId = search.get("session");
  const runId = search.get("run");
  const setRunId = useCallback(
    (id: string) =>
      setSearch((prev) => {
        const next = new URLSearchParams(prev);
        next.set("run", id);
        return next;
      }),
    [setSearch],
  );
  const [token, setToken] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    void getAccessToken()
      .then((value) => {
        if (!cancelled) setToken(value);
      })
      .catch(() => setToken(null));
    return () => {
      cancelled = true;
    };
  }, []);
  const stream = useSessionStream(sessionId, token);
  const frames: TermFrame[] =
    stream.buffer.frames.length > 0
      ? stream.buffer.frames
      : [{ stream: "system", seq: 0, data: "$ superagent studio ready\n" }];

  const projects = useQuery({
    queryKey: ["projects", orgId],
    queryFn: () => api.projects(orgId as string),
    enabled: Boolean(orgId),
  });

  const project: Project | null = projects.data?.results[0] ?? null;


  const content = useMemo(() => buffer, [buffer]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-base">
      <StudioToolbar
        project={project}
        target={project?.execution_preference ?? "cloud"}
        model="no model selected"
      />

      <div className="flex min-h-0 flex-1">
        {!collapsed.left && (
          <>
            <aside style={{ width: left }} className="flex min-h-0 shrink-0 flex-col border-r border-subtle">
              <Panel
                label="Files"
                actions={<FolderTree className="size-3.5 text-muted" aria-hidden />}
                className="min-h-0 flex-1 border-b border-subtle"
              >
                <ul className="py-1" role="tree" aria-label="Project files">
                  {SAMPLE_FILES.map((file) => (
                    <li key={file} role="treeitem" aria-selected={activeFile === file}>
                      <button
                        type="button"
                        onClick={() => setActiveFile(file)}
                        className={cn(
                          "flex w-full items-center gap-1.5 px-3 py-1 text-left text-[12.5px] transition-colors duration-[var(--dur-fast)]",
                          activeFile === file
                            ? "bg-accent/10 text-primary"
                            : "text-secondary hover:bg-overlay hover:text-primary",
                        )}
                      >
                        <FileCode2 className="size-3.5 shrink-0 text-muted" aria-hidden />
                        <span className="truncate">{file}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </Panel>
              <Panel label="Agents" className="min-h-0 flex-1 border-b border-subtle">
                <ul className="py-1 text-[12.5px] text-secondary">
                  {["orchestrator", "architect", "backend", "frontend", "qa"].map((agent) => (
                    <li key={agent} className="flex items-center justify-between px-3 py-1">
                      <span>{agent}</span>
                      <StatusChip tone="muted">idle</StatusChip>
                    </li>
                  ))}
                </ul>
              </Panel>
              <Panel label="Git" className="h-24 shrink-0">
                <p className="flex items-center gap-1.5 px-3 py-2 text-[12px] text-muted">
                  <GitBranch className="size-3.5" aria-hidden /> working tree clean
                </p>
              </Panel>
            </aside>
            <Splitter panel="left" label="Resize file panel" />
          </>
        )}

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex h-8 shrink-0 items-center border-b border-subtle bg-raised/40 px-3">
            <span className="font-mono text-[11.5px] text-secondary">
              {activeFile ?? "no file open"}
            </span>
          </div>
          <div className="min-h-0 flex-1">
            {activeFile ? (
              <EditorHost
                path={activeFile}
                value={content}
                language={languageFor(activeFile)}
                readOnly={false}
                onChange={setBuffer}
              />
            ) : (
              <EmptyState
                title="No file open"
                body="Choose a file from the explorer to view and edit it. Agent edits appear here in real time."
              />
            )}
          </div>

          {!collapsed.bottom && (
            <>
              <Splitter panel="bottom" orientation="horizontal" side="after" label="Resize terminal panel" />
              <div style={{ height: bottom }} className="shrink-0">
                <TerminalHost title="Terminal — run output" frames={frames} live={stream.live} />
              </div>
            </>
          )}
        </main>

        {!collapsed.right && (
          <>
            <Splitter panel="right" label="Resize assistant panel" side="after" />
            <aside style={{ width: right }} className="flex min-h-0 shrink-0 flex-col border-l border-subtle">
              <AgentPanel
                orgId={orgId}
                projectId={project?.id ?? null}
                runId={runId}
                onRunStarted={setRunId}
              />
              <PlanApprovals orgId={orgId} runId={runId} />
            </aside>
          </>
        )}
      </div>
    </div>
  );
}

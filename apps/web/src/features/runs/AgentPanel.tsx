/**
 * The Veritas Bot panel: describe an objective, start a run, watch it, control it.
 * Everything shown comes from the server; nothing is simulated.
 */
import { useState } from "react";
import { Pause, Play, Square } from "lucide-react";
import { Panel, StatusChip } from "@/components/ui/Panel";
import { ApiError } from "@/lib/api";
import { useRun, useRunControl, useStartRun } from "./hooks";
import {
  availableControls, errorMessage, formatUsd, planProgress, spendPercent, statusLabel, statusTone,
} from "./present";

const MIN_OBJECTIVE = 10;

interface AgentPanelProps {
  orgId: string | null;
  projectId: string | null;
  runId: string | null;
  onRunStarted: (runId: string) => void;
}

const CONTROL_ICON = { pause: Pause, resume: Play, cancel: Square } as const;
const CONTROL_LABEL = { pause: "Pause", resume: "Resume", cancel: "Stop" } as const;

export function AgentPanel({ orgId, projectId, runId, onRunStarted }: AgentPanelProps) {
  const [objective, setObjective] = useState("");
  const start = useStartRun(orgId);
  const run = useRun(orgId, runId);
  const control = useRunControl(orgId, runId);

  const trimmed = objective.trim();
  const canSend = Boolean(orgId && projectId) && trimmed.length >= MIN_OBJECTIVE && !start.isPending;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSend || !projectId) return;
    start.mutate(
      { project: projectId, objective: trimmed },
      {
        onSuccess: (created) => {
          setObjective("");
          onRunStarted(created.id);
        },
      },
    );
  };

  const data = run.data;
  const problem = data ? errorMessage(data.error_code) : null;
  const progress = data ? planProgress(data.plan) : null;
  const controls = data ? availableControls(data.status) : [];
  const failure =
    start.error instanceof ApiError ? start.error.message
    : control.error instanceof ApiError ? control.error.message
    : run.error instanceof ApiError ? run.error.message
    : null;

  return (
    <Panel
      label="Veritas Bot"
      className="min-h-0 flex-1 border-b border-subtle"
      actions={data ? <StatusChip tone={statusTone(data.status)}>{statusLabel(data.status)}</StatusChip> : null}
    >
      <div className="flex h-full flex-col gap-3 p-3">
        <div className="min-h-0 flex-1 space-y-3 overflow-auto text-[12.5px] leading-relaxed">
          {!data && (
            <>
              <p className="text-primary">What should I build?</p>
              <p className="text-muted">
                Describe the change in plain language. I will plan it, show the plan, and wait for
                your approval before anything destructive.
              </p>
              {!projectId && (
                <p role="status" className="text-warn">Create or select a project before starting.</p>
              )}
            </>
          )}

          {data && (
            <>
              <p className="text-primary">{data.objective}</p>

              {progress && progress.total > 0 && (
                <div>
                  <div className="mb-1 flex justify-between text-[11.5px] text-muted">
                    <span>{progress.done} of {progress.total} tasks done</span>
                    {progress.failed > 0 && <span className="text-danger">{progress.failed} failed</span>}
                  </div>
                  <div className="h-1 overflow-hidden rounded-sm bg-overlay" role="progressbar"
                       aria-valuemin={0} aria-valuemax={progress.total} aria-valuenow={progress.done}
                       aria-label="Plan progress">
                    <div className="h-full bg-accent transition-[width] duration-[var(--dur-fast)]"
                         style={{ width: `${(progress.done / progress.total) * 100}%` }} />
                  </div>
                </div>
              )}

              <div>
                <div className="mb-1 flex justify-between text-[11.5px] text-muted">
                  <span>Spend</span>
                  <span>{formatUsd(data.cost_usd)} of {formatUsd(data.cost_cap_usd)}</span>
                </div>
                <div className="h-1 overflow-hidden rounded-sm bg-overlay" role="progressbar"
                     aria-valuemin={0} aria-valuemax={100}
                     aria-valuenow={spendPercent(data.cost_usd, data.cost_cap_usd)}
                     aria-label="Spend against limit">
                  <div className={spendPercent(data.cost_usd, data.cost_cap_usd) >= 80 ? "h-full bg-warn" : "h-full bg-cyan"}
                       style={{ width: `${spendPercent(data.cost_usd, data.cost_cap_usd)}%` }} />
                </div>
              </div>

              {problem && <p role="alert" className="text-danger">{problem}</p>}
              {data.status === "needs_review" && !problem && (
                <p className="text-warn">
                  The run stopped with unfinished work. Review the plan to see what did not complete.
                </p>
              )}

              {controls.length > 0 && (
                <div className="flex gap-2">
                  {controls.map((action) => {
                    const Icon = CONTROL_ICON[action];
                    return (
                      <button key={action} type="button" disabled={control.isPending}
                              onClick={() => control.mutate(action)}
                              className="inline-flex h-7 items-center gap-1.5 rounded-sm border border-subtle px-2 text-[12px] text-secondary transition-colors duration-[var(--dur-fast)] hover:bg-overlay hover:text-primary disabled:opacity-50">
                        <Icon className="size-3" aria-hidden /> {CONTROL_LABEL[action]}
                      </button>
                    );
                  })}
                </div>
              )}
            </>
          )}

          {failure && <p role="alert" className="text-danger">{failure}</p>}
        </div>

        <form className="flex flex-col gap-2" onSubmit={submit}>
          <label htmlFor="objective" className="sr-only">Objective</label>
          <textarea
            id="objective" rows={3} value={objective}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="Add pagination to the runs list"
            className="resize-none rounded-sm border border-subtle bg-base p-2 text-[12.5px] text-primary placeholder:text-muted"
          />
          <button type="submit" disabled={!canSend}
                  className="h-8 rounded-sm bg-accent text-[12.5px] font-medium text-white transition-colors duration-[var(--dur-fast)] hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-50">
            {start.isPending ? "Starting…" : data ? "Start a new run" : "Send to orchestrator"}
          </button>
        </form>
      </div>
    </Panel>
  );
}

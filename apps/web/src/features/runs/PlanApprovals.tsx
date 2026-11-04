/**
 * Plan and approvals. The approval card always shows the exact payload that will
 * run, not only a summary: the server binds the decision to a hash of that
 * payload, so what the user reads must be what they are approving.
 */
import { useState } from "react";
import { Check, ShieldQuestion, X } from "lucide-react";
import { Panel, StatusChip } from "@/components/ui/Panel";
import { ApiError } from "@/lib/api";
import { useDecideApproval, useRun } from "./hooks";
import { blockedBy, expiresIn } from "./present";
import type { Approval, PlanTask } from "./schemas";

const TASK_TONE = { done: "ok", failed: "danger", running: "live", pending: "muted" } as const;

function TaskRow({ task, plan }: { task: PlanTask; plan: PlanTask[] }) {
  const waiting = blockedBy(task, plan);
  const tone = TASK_TONE[task.state as keyof typeof TASK_TONE] ?? "muted";
  return (
    <li className="flex items-start justify-between gap-2 border-b border-subtle px-3 py-2 last:border-b-0">
      <div className="min-w-0">
        <p className="truncate text-[12.5px] text-primary">{task.title}</p>
        <p className="truncate text-[11.5px] text-muted">
          {task.agent}
          {task.write_scope.length > 0 && ` · writes ${task.write_scope.join(", ")}`}
          {task.state === "pending" && waiting.length > 0 && ` · waiting on ${waiting.join(", ")}`}
        </p>
      </div>
      <StatusChip tone={tone}>{task.state}</StatusChip>
    </li>
  );
}

function ApprovalCard({
  approval, busy, error, onDecide,
}: {
  approval: Approval;
  busy: boolean;
  error: string | null;
  onDecide: (approve: boolean) => void;
}) {
  const remaining = expiresIn(approval.expires_at);
  return (
    <li className="space-y-2 border-b border-subtle px-3 py-3 last:border-b-0">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[12.5px] font-medium text-primary">{approval.summary}</p>
        <StatusChip tone="warn">{approval.action_type.replaceAll("_", " ")}</StatusChip>
      </div>

      <p className="text-[11px] uppercase tracking-wide text-muted">Exactly what will run</p>
      <pre className="max-h-32 overflow-auto rounded-sm border border-subtle bg-base p-2 font-mono text-[11.5px] leading-snug text-secondary"
           tabIndex={0} aria-label="Exact action payload">
        {JSON.stringify(approval.payload, null, 2)}
      </pre>

      {remaining ? (
        <p className="text-[11.5px] text-muted">Expires in {remaining}</p>
      ) : (
        <p role="status" className="text-[11.5px] text-danger">This request has expired.</p>
      )}
      {error && <p role="alert" className="text-[11.5px] text-danger">{error}</p>}

      <div className="flex gap-2">
        <button type="button" disabled={busy || !remaining} onClick={() => onDecide(true)}
                className="inline-flex h-7 items-center gap-1.5 rounded-sm bg-accent px-2.5 text-[12px] font-medium text-white hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-50">
          <Check className="size-3" aria-hidden /> Approve
        </button>
        <button type="button" disabled={busy || !remaining} onClick={() => onDecide(false)}
                className="inline-flex h-7 items-center gap-1.5 rounded-sm border border-subtle px-2.5 text-[12px] text-secondary hover:bg-overlay disabled:cursor-not-allowed disabled:opacity-50">
          <X className="size-3" aria-hidden /> Reject
        </button>
      </div>
    </li>
  );
}

export function PlanApprovals({ orgId, runId }: { orgId: string | null; runId: string | null }) {
  const run = useRun(orgId, runId);
  const decide = useDecideApproval(orgId, runId);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const approvals = run.data?.pending_approvals ?? [];
  const plan = run.data?.plan ?? [];
  const decideError = decide.error instanceof ApiError ? decide.error.message : null;

  return (
    <Panel
      label="Plan & approvals"
      className="h-56 shrink-0"
      actions={approvals.length > 0 ? <StatusChip tone="warn">{approvals.length} pending</StatusChip> : null}
    >
      {!runId && (
        <p className="flex items-center gap-1.5 px-3 py-2 text-[12px] text-muted">
          <ShieldQuestion className="size-3.5" aria-hidden /> Start a run to see its plan.
        </p>
      )}
      {runId && run.isLoading && <p className="px-3 py-2 text-[12px] text-muted">Loading…</p>}
      {runId && run.isError && (
        <p role="alert" className="px-3 py-2 text-[12px] text-danger">Could not load this run.</p>
      )}

      {approvals.length > 0 && (
        <ul aria-label="Pending approvals">
          {approvals.map((a) => (
            <ApprovalCard key={a.id} approval={a}
              busy={decide.isPending && pendingId === a.id}
              error={pendingId === a.id ? decideError : null}
              onDecide={(approve) => { setPendingId(a.id); decide.mutate({ approvalId: a.id, approve }); }} />
          ))}
        </ul>
      )}

      {run.data && plan.length === 0 && approvals.length === 0 && (
        <p className="px-3 py-2 text-[12px] text-muted">
          {run.data.status === "queued" || run.data.status === "running"
            ? "Planning…" : "This run produced no plan."}
        </p>
      )}
      {plan.length > 0 && (
        <ul aria-label="Plan tasks">
          {plan.map((task) => <TaskRow key={task.id} task={task} plan={plan} />)}
        </ul>
      )}
    </Panel>
  );
}

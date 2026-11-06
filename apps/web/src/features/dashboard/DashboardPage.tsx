/**
 * Main dashboard. Every number comes from the server; a figure the backend cannot
 * compute (build success rate, execution minutes) is simply not shown rather than
 * invented. Each section fails on its own, as in the design's state sheet
 * ("Usage is temporarily unavailable" / "Retry usage"), so one bad call does not
 * blank the page.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { EmptyState, Panel, StatusChip } from "@/components/ui/Panel";
import { api } from "@/lib/api";
import { formatUsd } from "@/features/runs/present";
import { statusLabel, statusTone } from "@/features/runs/present";
import { RunStatusSchema } from "@/features/runs/schemas";
import { sessionApi } from "@/features/session/api";
import { canWrite } from "@/features/session/access";
import { useActiveSession } from "@/features/session/context";
import { greetingName, statusCount, timeAgo } from "./present";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="glass rounded-md p-4">
      <p className="panel-label">{label}</p>
      <p className="mt-2 text-[26px] font-semibold leading-none text-primary">{value}</p>
      {hint && <p className="mt-2 text-[11.5px] text-muted">{hint}</p>}
    </div>
  );
}

function SectionError({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between gap-3 p-4 text-[12.5px]">
      <span className="text-danger">{what} is temporarily unavailable.</span>
      <button type="button" onClick={onRetry} className="btn-glass h-7 px-2.5 text-[12px]">Retry</button>
    </div>
  );
}

export function DashboardPage() {
  const { me, org, role } = useActiveSession();
  const summary = useQuery({ queryKey: ["summary", org.id], queryFn: () => sessionApi.summary(org.id) });
  const projects = useQuery({ queryKey: ["projects", org.id], queryFn: () => api.projects(org.id) });

  const name = greetingName(me.profile.display_name, me.profile.email);
  const s = summary.data;
  const projectList = projects.data?.results ?? [];
  const projectNames = new Map(projectList.map((p) => [p.id, p.name]));

  return (
    <div className="glass-backdrop h-full overflow-auto">
      <div className="mx-auto max-w-6xl space-y-5 p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="panel-label">{org.name} / Overview</p>
            <h1 className="mt-1 text-[20px] font-semibold text-primary">
              {name ? `Welcome back, ${name}.` : "Welcome back."}
            </h1>
            <p className="text-[12.5px] text-muted">Here is what needs your attention today.</p>
          </div>
          {canWrite(role) ? (
            <Link to="/projects/new" className="btn-liquid inline-flex h-9 items-center px-4 text-[12.5px] font-medium">
              New project
            </Link>
          ) : (
            <p className="text-[12px] text-muted">Your role can view this workspace but not change it.</p>
          )}
        </div>

        {summary.isError ? (
          <div className="glass rounded-md"><SectionError what="Workspace figures" onRetry={() => void summary.refetch()} /></div>
        ) : (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-busy={summary.isLoading}>
            <Stat label="Projects" value={s ? String(s.project_count) : "…"} />
            <Stat label="Running agents" value={s ? String(s.active_runs) : "…"}
                  hint={s ? `${statusCount(s.runs_by_status, "waiting_approval")} waiting for approval` : undefined} />
            <Stat label="Pending approvals" value={s ? String(s.pending_approvals) : "…"} />
            <Stat label="Spend this month" value={s ? formatUsd(s.spend_this_month_usd) : "…"}
                  hint={s ? "Calendar month, UTC" : undefined} />
          </div>
        )}

        <div className="grid gap-5 lg:grid-cols-2">
          <Panel label="Recent projects" className="glass rounded-md"
                 actions={<Link to="/projects" className="text-[11.5px] text-accent-soft hover:underline">View all</Link>}>
            {projects.isError ? (
              <SectionError what="Projects" onRetry={() => void projects.refetch()} />
            ) : projects.isLoading ? (
              <p className="p-4 text-[12.5px] text-muted">Loading…</p>
            ) : projectList.length === 0 ? (
              <EmptyState title="Your next idea starts here."
                          body="Create a project to connect a repository and give your agents a workspace."
                          action={canWrite(role) ? (
                            <Link to="/projects/new" className="btn-liquid mt-2 inline-flex h-8 items-center px-3 text-[12.5px]">
                              Create first project
                            </Link>) : undefined} />
            ) : (
              <ul className="divide-y divide-subtle">
                {projectList.slice(0, 6).map((p) => (
                  <li key={p.id} className="flex items-center gap-3 px-4 py-3">
                    <div className="min-w-0 flex-1">
                      <Link to={`/projects/${p.id}`} className="truncate text-[13px] text-primary hover:underline">{p.name}</Link>
                      <p className="font-mono text-[11.5px] text-muted">{p.slug} · {p.default_branch}</p>
                    </div>
                    <StatusChip tone="muted">{p.execution_preference}</StatusChip>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel label="Recent runs" className="glass rounded-md">
            {summary.isError ? (
              <SectionError what="Runs" onRetry={() => void summary.refetch()} />
            ) : !s ? (
              <p className="p-4 text-[12.5px] text-muted">Loading…</p>
            ) : s.recent_runs.length === 0 ? (
              <EmptyState title="No runs yet" body="Describe what you want built in the Studio and your agents will plan it here." />
            ) : (
              <ul className="divide-y divide-subtle">
                {s.recent_runs.map((r) => {
                  const parsed = RunStatusSchema.safeParse(r.status);
                  return (
                    <li key={r.id} className="flex items-center gap-3 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <Link to={`/studio?run=${r.id}`} className="block truncate text-[13px] text-primary hover:underline">
                          {r.objective}
                        </Link>
                        <p className="text-[11.5px] text-muted">
                          {projectNames.get(r.project_id) ?? "Project"} · {timeAgo(r.created_at)} · {formatUsd(r.cost_usd)}
                        </p>
                      </div>
                      {parsed.success
                        ? <StatusChip tone={statusTone(parsed.data)}>{statusLabel(parsed.data)}</StatusChip>
                        : <StatusChip tone="muted">{r.status}</StatusChip>}
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

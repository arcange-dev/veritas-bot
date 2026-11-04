import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useSession } from "@/stores/session";
import { EmptyState, Panel, StatusChip } from "@/components/ui/Panel";

export function DashboardPage() {
  const orgId = useSession((s) => s.orgId);
  const projects = useQuery({
    queryKey: ["projects", orgId],
    queryFn: () => api.projects(orgId as string),
    enabled: Boolean(orgId),
  });

  if (!orgId) {
    return (
      <EmptyState
        title="No organization selected"
        body="Set an organization id to load your projects. In production this comes from your membership list after sign-in."
      />
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-[18px] font-semibold text-primary">Projects</h1>
          <p className="text-[12.5px] text-muted">Repositories your agents can work in.</p>
        </div>
        <Link to="/studio" className="rounded-sm bg-accent px-3 py-2 text-[12.5px] font-medium text-white hover:bg-accent-soft">
          Open studio
        </Link>
      </div>

      <Panel label="All projects" className="rounded-md border border-subtle">
        {projects.isLoading ? (
          <p className="p-4 text-[12.5px] text-muted">Loading…</p>
        ) : projects.data && projects.data.results.length > 0 ? (
          <ul className="divide-y divide-subtle">
            {projects.data.results.map((project) => (
              <li key={project.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] text-primary">{project.name}</p>
                  <p className="font-mono text-[11.5px] text-muted">
                    {project.slug} · {project.default_branch}
                  </p>
                </div>
                <StatusChip tone="muted">{project.execution_preference}</StatusChip>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No projects yet" body="Create a project to connect a repository and give your agents a workspace." />
        )}
      </Panel>
    </div>
  );
}

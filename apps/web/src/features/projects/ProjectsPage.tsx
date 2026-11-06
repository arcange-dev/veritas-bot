/** Projects library (Figma 09): search, active / archived views, honest empty and error states. */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState, Panel, StatusChip } from "@/components/ui/Panel";
import { canWrite } from "@/features/session/access";
import { useActiveSession } from "@/features/session/context";
import { timeAgo } from "@/features/dashboard/present";
import type { ArchiveFilter } from "./api";
import { useProjects } from "./hooks";

const TABS: { id: ArchiveFilter; label: string }[] = [
  { id: "active", label: "Active" },
  { id: "archived", label: "Archived" },
  { id: "all", label: "All projects" },
];

/** Wait for the user to stop typing, so each keystroke is not a request. */
function useDebounced(value: string, ms = 250): string {
  const [out, setOut] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setOut(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return out;
}

export function ProjectsPage() {
  const { org, role } = useActiveSession();
  const [tab, setTab] = useState<ArchiveFilter>("active");
  const [search, setSearch] = useState("");
  const debounced = useDebounced(search.trim());
  const query = useProjects(org.id, tab, debounced);
  const items = query.data?.results ?? [];
  const filtering = debounced !== "" || tab !== "active";

  return (
    <div className="glass-backdrop h-full overflow-auto">
      <div className="mx-auto max-w-6xl space-y-4 p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="panel-label">{org.name} / Projects</p>
            <h1 className="mt-1 text-[20px] font-semibold text-primary">Projects</h1>
            <p className="text-[12.5px] text-muted">Everything you are building, in one workspace.</p>
          </div>
          {canWrite(role) && (
            <Link to="/projects/new" className="btn-liquid inline-flex h-9 items-center px-4 text-[12.5px] font-medium">
              Create project
            </Link>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div role="tablist" aria-label="Project view" className="glass flex rounded-sm p-0.5">
            {TABS.map((t) => (
              <button key={t.id} role="tab" type="button" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
                      className={`h-7 rounded-sm px-3 text-[12px] ${tab === t.id ? "bg-overlay text-primary" : "text-secondary hover:text-primary"}`}>
                {t.label}
              </button>
            ))}
          </div>
          <label htmlFor="project-search" className="sr-only">Search projects</label>
          <input id="project-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)}
                 placeholder="Search projects…"
                 className="h-8 min-w-[16rem] flex-1 rounded-sm border border-subtle bg-base px-2.5 text-[12.5px] text-primary" />
        </div>

        <Panel label={query.data ? `${items.length} shown` : "Projects"} className="glass rounded-md">
          {query.isError ? (
            <div role="alert" className="flex items-center justify-between gap-3 p-4 text-[12.5px]">
              <span className="text-danger">Could not load projects.</span>
              <button type="button" onClick={() => void query.refetch()} className="btn-glass h-7 px-2.5 text-[12px]">Retry</button>
            </div>
          ) : query.isLoading ? (
            <p className="p-4 text-[12.5px] text-muted" role="status">Loading projects…</p>
          ) : items.length === 0 ? (
            filtering ? (
              <EmptyState title={debounced ? `No projects match "${debounced}"` : "Nothing here"}
                          body={tab === "archived" ? "You have no archived projects." : "Try a different search or view."}
                          action={<button type="button" className="btn-glass h-8 px-3 text-[12.5px]"
                                          onClick={() => { setSearch(""); setTab("active"); }}>Clear filters</button>} />
            ) : (
              <EmptyState title="Your next idea starts here."
                          body="Create a project to give your agents a workspace."
                          action={canWrite(role) ? <Link to="/projects/new" className="btn-liquid mt-2 inline-flex h-8 items-center px-3 text-[12.5px]">Create first project</Link> : undefined} />
            )
          ) : (
            <ul className="divide-y divide-subtle">
              {items.map((p) => (
                <li key={p.id} className="flex items-center gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <Link to={`/projects/${p.id}`} className="truncate text-[13px] font-medium text-primary hover:underline">{p.name}</Link>
                    <p className="truncate text-[12px] text-muted">{p.description || "No description"}</p>
                    <p className="font-mono text-[11.5px] text-muted">{p.slug} · {p.default_branch} · created {timeAgo(p.created_at)}</p>
                  </div>
                  {p.is_archived && <StatusChip tone="warn">Archived</StatusChip>}
                  <StatusChip tone="muted">{p.execution_preference === "local" ? "Local" : "Cloud"}</StatusChip>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

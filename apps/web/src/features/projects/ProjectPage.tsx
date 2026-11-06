/** Project overview and settings (Figma 12 + 13). Destructive actions are gated by role and by typing the name. */
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { EmptyState, Panel, StatusChip } from "@/components/ui/Panel";
import { ApiError } from "@/lib/api";
import { canAdminister, canWrite } from "@/features/session/access";
import { useActiveSession } from "@/features/session/context";
import { useArchiveProject, useDeleteProject, useProject, useUpdateProject } from "./hooks";
import { changedFields, checkBranch, checkProjectName, deleteConfirmed, type FormValues } from "./rules";

const input = "h-9 w-full rounded-sm border border-subtle bg-base px-2.5 text-[12.5px] text-primary disabled:opacity-60";

export function ProjectPage() {
  const { id = "" } = useParams();
  const { org, role } = useActiveSession();
  const navigate = useNavigate();
  const query = useProject(org.id, id);
  const update = useUpdateProject(org.id, id);
  const archive = useArchiveProject(org.id, id);
  const remove = useDeleteProject(org.id, id);
  const project = query.data;

  const [form, setForm] = useState<FormValues | null>(null);
  const [typed, setTyped] = useState("");
  const [saved, setSaved] = useState(false);

  // Fill the form once the project arrives (and again if it is replaced by a fresh server copy).
  useEffect(() => {
    if (project) setForm({ name: project.name, description: project.description, default_branch: project.default_branch, execution_preference: project.execution_preference });
  }, [project]);

  if (query.isLoading) return <p role="status" className="p-6 text-[12.5px] text-muted">Loading project…</p>;
  if (query.isError || !project || !form) {
    const notFound = query.error instanceof ApiError && query.error.status === 404;
    return (
      <EmptyState title={notFound ? "Project not found" : "Could not load this project"}
                  body={notFound ? "It may have been deleted, or it belongs to another workspace." : "Check your connection and try again."}
                  action={<Link to="/projects" className="btn-glass inline-flex h-8 items-center px-3 text-[12.5px]">Back to projects</Link>} />
    );
  }

  const original: FormValues = { name: project.name, description: project.description, default_branch: project.default_branch, execution_preference: project.execution_preference };
  const diff = changedFields(original, form);
  const dirty = Object.keys(diff).length > 0;
  const nameCheck = checkProjectName(form.name);
  const branchCheck = checkBranch(form.default_branch);
  const writable = canWrite(role);
  const admin = canAdminister(role);
  const saveError = update.error instanceof ApiError ? update.error.message : null;
  const set = <K extends keyof FormValues>(k: K, v: FormValues[K]) => { setForm({ ...form, [k]: v }); setSaved(false); update.reset(); };

  return (
    <div className="glass-backdrop h-full overflow-auto">
      <div className="mx-auto max-w-3xl space-y-5 p-6">
        <div>
          <p className="panel-label"><Link to="/projects" className="hover:underline">Projects</Link> / {project.name}</p>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            <h1 className="text-[20px] font-semibold text-primary">{project.name}</h1>
            {project.is_archived && <StatusChip tone="warn">Archived</StatusChip>}
            <StatusChip tone="muted">{project.execution_preference === "local" ? "Local runner" : "Cloud sandbox"}</StatusChip>
          </div>
          <p className="mt-1 font-mono text-[11.5px] text-muted">{project.slug} · {project.default_branch}</p>
          {!writable && <p className="mt-2 text-[12.5px] text-warn">Project access is read-only for your role.</p>}
        </div>

        <Panel label="General" className="glass rounded-md">
          <form className="space-y-4 p-4" onSubmit={(e) => {
            e.preventDefault();
            if (!dirty || !nameCheck.ok || !branchCheck.ok) return;
            update.mutate(diff, { onSuccess: () => setSaved(true) });
          }}>
            <div>
              <label htmlFor="s-name" className="panel-label">Project name</label>
              <input id="s-name" className={`${input} mt-1.5`} value={form.name} disabled={!writable} maxLength={80}
                     onChange={(e) => set("name", e.target.value)} aria-invalid={!nameCheck.ok} />
              {!nameCheck.ok && <p role="alert" className="mt-1 text-[11.5px] text-danger">{nameCheck.message}</p>}
            </div>
            <div>
              <label htmlFor="s-slug" className="panel-label">Project address</label>
              <input id="s-slug" className={`${input} mt-1.5 font-mono`} value={project.slug} readOnly disabled />
              <p className="mt-1 text-[11.5px] text-muted">The address never changes when you rename a project, so existing links keep working.</p>
            </div>
            <div>
              <label htmlFor="s-desc" className="panel-label">Description</label>
              <textarea id="s-desc" rows={3} className={`${input} mt-1.5 h-auto resize-none py-2`} value={form.description}
                        disabled={!writable} maxLength={500} onChange={(e) => set("description", e.target.value)} />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="s-branch" className="panel-label">Default branch</label>
                <input id="s-branch" className={`${input} mt-1.5 font-mono`} value={form.default_branch} disabled={!writable}
                       onChange={(e) => set("default_branch", e.target.value)} aria-invalid={!branchCheck.ok} />
                {!branchCheck.ok && <p role="alert" className="mt-1 text-[11.5px] text-danger">{branchCheck.message}</p>}
              </div>
              <div>
                <label htmlFor="s-target" className="panel-label">Runs on</label>
                <select id="s-target" className={`${input} mt-1.5`} value={form.execution_preference} disabled={!writable}
                        onChange={(e) => set("execution_preference", e.target.value as "local" | "cloud")}>
                  <option value="cloud">Cloud sandbox</option>
                  <option value="local">Local runner</option>
                </select>
              </div>
            </div>
            {saveError && <p role="alert" className="text-[12.5px] text-danger">{saveError}</p>}
            {saved && !dirty && <p role="status" className="text-[12.5px] text-ok">Project settings saved</p>}
            {writable && (
              <div className="flex justify-end">
                <button type="submit" disabled={!dirty || !nameCheck.ok || !branchCheck.ok || update.isPending} className="btn-liquid h-9 px-4 text-[12.5px] font-medium">
                  {update.isPending ? "Saving…" : "Save changes"}
                </button>
              </div>
            )}
          </form>
        </Panel>

        {writable && (
          <Panel label="Archive" className="glass rounded-md">
            <div className="flex flex-wrap items-center justify-between gap-3 p-4">
              <p className="max-w-[48ch] text-[12.5px] text-secondary">
                {project.is_archived
                  ? "This project is archived and hidden from the main list. Restore it to work on it again."
                  : "Archiving hides the project from the main list. Nothing is deleted and you can restore it any time."}
              </p>
              <button type="button" disabled={archive.isPending} onClick={() => archive.mutate(!project.is_archived)} className="btn-glass h-8 px-3 text-[12.5px]">
                {archive.isPending ? "Working…" : project.is_archived ? "Restore project" : "Archive project"}
              </button>
            </div>
            {archive.error instanceof ApiError && <p role="alert" className="px-4 pb-3 text-[12.5px] text-danger">{archive.error.message}</p>}
          </Panel>
        )}

        <Panel label="Danger zone" className="rounded-md border border-danger/40 bg-raised/60">
          {admin ? (
            <div className="space-y-3 p-4">
              <p className="text-[12.5px] text-secondary">
                Deleting a project permanently removes it and its runs. This cannot be undone. Type <strong className="text-primary">{project.name}</strong> to confirm.
              </p>
              <label htmlFor="confirm-delete" className="sr-only">Type the project name to confirm deletion</label>
              <input id="confirm-delete" className={input} value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={project.name} autoComplete="off" />
              {remove.error instanceof ApiError && <p role="alert" className="text-[12.5px] text-danger">{remove.error.message}</p>}
              <button type="button" disabled={!deleteConfirmed(typed, project.name) || remove.isPending}
                      onClick={() => remove.mutate(undefined, { onSuccess: () => navigate("/projects", { replace: true }) })}
                      className="h-9 rounded-sm bg-danger px-4 text-[12.5px] font-medium text-white disabled:cursor-not-allowed disabled:opacity-40">
                {remove.isPending ? "Deleting…" : "Delete project forever"}
              </button>
            </div>
          ) : (
            <p className="p-4 text-[12.5px] text-muted">Only workspace admins can delete a project.</p>
          )}
        </Panel>
      </div>
    </div>
  );
}

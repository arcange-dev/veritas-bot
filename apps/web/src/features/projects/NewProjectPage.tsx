/** New project (Figma 10). Only fields the API stores are offered; nothing is faked. */
import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "@/lib/api";
import { canWrite } from "@/features/session/access";
import { useActiveSession } from "@/features/session/context";
import { useCreateProject } from "./hooks";
import { checkBranch, checkProjectName, previewSlug } from "./rules";

const input = "h-9 w-full rounded-sm border border-subtle bg-base px-2.5 text-[12.5px] text-primary";

export function NewProjectPage() {
  const { org, role } = useActiveSession();
  const navigate = useNavigate();
  const create = useCreateProject(org.id);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [branch, setBranch] = useState("main");
  const [target, setTarget] = useState<"local" | "cloud">("cloud");
  const [touched, setTouched] = useState(false);

  if (!canWrite(role)) return <Navigate to="/projects" replace />;

  const nameCheck = checkProjectName(name);
  const branchCheck = checkBranch(branch);
  const slug = previewSlug(name);
  // The server reports a duplicate on the name field; show it there, not as a generic banner.
  const apiError = create.error instanceof ApiError ? create.error : null;
  const serverFieldError = apiError?.fields.name?.[0] ?? null;
  const serverOther = create.error && !serverFieldError ? (apiError ? apiError.message : "Could not create the project.") : null;
  const nameError = touched && !nameCheck.ok ? nameCheck.message : serverFieldError;
  const canSubmit = nameCheck.ok && branchCheck.ok && !create.isPending;

  return (
    <div className="glass-backdrop h-full overflow-auto">
      <div className="mx-auto max-w-xl space-y-4 p-6">
        <div>
          <p className="panel-label">{org.name} / Projects / New</p>
          <h1 className="mt-1 text-[20px] font-semibold text-primary">Create project</h1>
        </div>
        <form
          className="glass space-y-4 rounded-md p-5"
          onSubmit={(e) => {
            e.preventDefault();
            setTouched(true);
            if (!nameCheck.ok || !branchCheck.ok) return;
            create.mutate(
              { name: nameCheck.name, description: description.trim(), default_branch: branch.trim(), execution_preference: target },
              { onSuccess: (p) => navigate(`/projects/${p.id}`) },
            );
          }}
        >
          <div>
            <label htmlFor="pname" className="panel-label">Project name</label>
            <input id="pname" className={`${input} mt-1.5`} value={name} autoFocus maxLength={80}
                   onChange={(e) => { setName(e.target.value); create.reset(); }} onBlur={() => setTouched(true)}
                   aria-invalid={Boolean(nameError)} aria-describedby="pname-help" placeholder="Orbit Commerce" />
            <p id="pname-help" className={`mt-1 text-[11.5px] ${nameError ? "text-danger" : "text-muted"}`}
               role={nameError ? "alert" : undefined}>
              {nameError ?? (slug ? `Address: ${slug}` : "2 to 64 characters. Used to build the project address.")}
            </p>
          </div>
          <div>
            <label htmlFor="pdesc" className="panel-label">Description <span className="normal-case text-muted">(optional)</span></label>
            <textarea id="pdesc" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500}
                      className={`${input} mt-1.5 h-auto resize-none py-2`} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="pbranch" className="panel-label">Default branch</label>
              <input id="pbranch" className={`${input} mt-1.5 font-mono`} value={branch} onChange={(e) => setBranch(e.target.value)}
                     aria-invalid={!branchCheck.ok} />
              {!branchCheck.ok && <p role="alert" className="mt-1 text-[11.5px] text-danger">{branchCheck.message}</p>}
            </div>
            <fieldset>
              <legend className="panel-label">Runs on</legend>
              <div className="mt-1.5 flex gap-2">
                {(["cloud", "local"] as const).map((t) => (
                  <label key={t} className={`glass flex h-9 flex-1 cursor-pointer items-center justify-center rounded-sm text-[12.5px] ${target === t ? "text-primary ring-1 ring-[var(--accent)]" : "text-secondary"}`}>
                    <input type="radio" name="target" className="sr-only" checked={target === t} onChange={() => setTarget(t)} />
                    {t === "cloud" ? "Cloud sandbox" : "Local runner"}
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
          {serverOther && <p role="alert" className="text-[12.5px] text-danger">{serverOther}</p>}
          <div className="flex items-center justify-end gap-2 pt-1">
            <Link to="/projects" className="btn-glass inline-flex h-9 items-center px-4 text-[12.5px]">Cancel</Link>
            <button type="submit" disabled={!canSubmit} className="btn-liquid h-9 px-4 text-[12.5px] font-medium">
              {create.isPending ? "Creating…" : "Create project"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

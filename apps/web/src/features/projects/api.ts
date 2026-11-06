import { z } from "zod";
import { ProjectSchema, apiFetch } from "@/lib/api";

/** The API now also returns the archive state; widen the shared schema locally. */
export const ProjectDetailSchema = ProjectSchema.extend({
  archived_at: z.string().nullable(),
  is_archived: z.boolean(),
  description: z.string(),
});
export type ProjectDetail = z.infer<typeof ProjectDetailSchema>;

const Page = z.object({
  next: z.string().nullable(),
  previous: z.string().nullable(),
  results: z.array(ProjectDetailSchema),
});

const base = (orgId: string) => `/api/v1/orgs/${orgId}/projects/`;
export type ArchiveFilter = "active" | "archived" | "all";

export interface ProjectInput {
  name: string;
  description?: string;
  default_branch?: string;
  execution_preference?: "local" | "cloud";
}

export const projectsApi = {
  list: (orgId: string, opts: { archived?: ArchiveFilter; search?: string; cursor?: string } = {}) => {
    const q = new URLSearchParams();
    if (opts.archived === "archived") q.set("archived", "1");
    if (opts.archived === "all") q.set("archived", "all");
    if (opts.search) q.set("search", opts.search);
    const qs = q.toString();
    return apiFetch(opts.cursor ?? `${base(orgId)}${qs ? `?${qs}` : ""}`, Page);
  },
  get: (orgId: string, id: string) => apiFetch(`${base(orgId)}${id}/`, ProjectDetailSchema),
  create: (orgId: string, body: ProjectInput) =>
    apiFetch(base(orgId), ProjectDetailSchema, { method: "POST", json: body }),
  update: (orgId: string, id: string, body: Partial<ProjectInput>) =>
    apiFetch(`${base(orgId)}${id}/`, ProjectDetailSchema, { method: "PATCH", json: body }),
  archive: (orgId: string, id: string) =>
    apiFetch(`${base(orgId)}${id}/archive/`, ProjectDetailSchema, { method: "POST", json: {} }),
  unarchive: (orgId: string, id: string) =>
    apiFetch(`${base(orgId)}${id}/unarchive/`, ProjectDetailSchema, { method: "POST", json: {} }),
  remove: async (orgId: string, id: string): Promise<void> => {
    await apiFetch(`${base(orgId)}${id}/`, z.unknown(), { method: "DELETE" });
  },
};

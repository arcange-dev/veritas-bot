import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { projectsApi, type ArchiveFilter, type ProjectInput } from "./api";

export const projectKeys = {
  all: (orgId: string) => ["projects", orgId] as const,
  list: (orgId: string, archived: ArchiveFilter, search: string) => ["projects", orgId, "list", archived, search] as const,
  one: (orgId: string, id: string) => ["projects", orgId, "one", id] as const,
};

export function useProjects(orgId: string, archived: ArchiveFilter, search: string) {
  return useQuery({
    queryKey: projectKeys.list(orgId, archived, search),
    queryFn: () => projectsApi.list(orgId, { archived, search: search || undefined }),
  });
}

export function useProject(orgId: string, id: string) {
  return useQuery({ queryKey: projectKeys.one(orgId, id), queryFn: () => projectsApi.get(orgId, id) });
}

function useInvalidate(orgId: string) {
  const qc = useQueryClient();
  return () => Promise.all([
    qc.invalidateQueries({ queryKey: projectKeys.all(orgId) }),
    qc.invalidateQueries({ queryKey: ["summary", orgId] }),
  ]);
}

export function useCreateProject(orgId: string) {
  const invalidate = useInvalidate(orgId);
  return useMutation({ mutationFn: (b: ProjectInput) => projectsApi.create(orgId, b), onSuccess: invalidate });
}

export function useUpdateProject(orgId: string, id: string) {
  const invalidate = useInvalidate(orgId);
  return useMutation({
    mutationFn: (b: Partial<ProjectInput>) => projectsApi.update(orgId, id, b),
    onSuccess: invalidate,
  });
}

export function useArchiveProject(orgId: string, id: string) {
  const invalidate = useInvalidate(orgId);
  return useMutation({
    mutationFn: (archive: boolean) => (archive ? projectsApi.archive(orgId, id) : projectsApi.unarchive(orgId, id)),
    onSuccess: invalidate,
  });
}

export function useDeleteProject(orgId: string, id: string) {
  const qc = useQueryClient();
  const invalidate = useInvalidate(orgId);
  return useMutation({
    mutationFn: () => projectsApi.remove(orgId, id),
    onSuccess: async () => {
      // Forget the deleted project first. Refetching it (as invalidate would) asks the server
      // for an id that no longer exists while its page is still on screen, and gets a 404.
      qc.removeQueries({ queryKey: projectKeys.one(orgId, id) });
      await invalidate();
    },
  });
}

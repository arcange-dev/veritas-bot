import { apiFetch } from "@/lib/api";
import { DashboardSummarySchema, MeSchema } from "./schemas";

export const sessionApi = {
  me: () => apiFetch("/api/v1/me/", MeSchema),
  createOrganization: (name: string) =>
    apiFetch("/api/v1/me/organizations/", MeSchema, { method: "POST", json: { name } }),
  summary: (orgId: string) =>
    apiFetch(`/api/v1/orgs/${orgId}/dashboard/summary/`, DashboardSummarySchema),
};

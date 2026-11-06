/** Wire schemas for the signed-in person and their workspaces. */
import { z } from "zod";

export const ROLES = ["owner", "admin", "member", "viewer"] as const;
export const RoleSchema = z.enum(ROLES);
export type Role = z.infer<typeof RoleSchema>;

export const OrganizationSchema = z.object({
  id: z.string(),
  name: z.string(),
  slug: z.string(),
  plan: z.string(),
  role: RoleSchema,
});
export type Organization = z.infer<typeof OrganizationSchema>;

export const MeSchema = z.object({
  profile: z.object({
    id: z.string(),
    email: z.string(),
    display_name: z.string(),
    avatar_url: z.string(),
    is_platform_admin: z.boolean(),
    onboarded: z.boolean(),
  }),
  organizations: z.array(OrganizationSchema),
});
export type Me = z.infer<typeof MeSchema>;

const Money = z.string().regex(/^-?\d+(\.\d+)?$/, "expected a decimal string");

export const RecentRunSchema = z.object({
  id: z.string(),
  objective: z.string(),
  status: z.string(),
  cost_usd: Money,
  project_id: z.string(),
  created_at: z.string(),
});

export const DashboardSummarySchema = z.object({
  project_count: z.number(),
  active_runs: z.number(),
  pending_approvals: z.number(),
  runs_by_status: z.record(z.number()),
  spend_this_month_usd: Money,
  month_started_at: z.string(),
  recent_runs: z.array(RecentRunSchema),
});
export type DashboardSummary = z.infer<typeof DashboardSummarySchema>;

/**
 * Wire schemas for runs and approvals.
 *
 * Money arrives as a decimal STRING from DRF ("0.072000"), never a JS number:
 * binary floats cannot represent most decimal amounts exactly, and a spend cap
 * is exactly where that matters. Values stay strings until display.
 */
import { z } from "zod";

export const RUN_STATUSES = [
  "queued",
  "running",
  "paused",
  "waiting_approval",
  "succeeded",
  "failed",
  "cancelled",
  "needs_review",
] as const;
export const RunStatusSchema = z.enum(RUN_STATUSES);
export type RunStatus = z.infer<typeof RunStatusSchema>;

export const TERMINAL: ReadonlySet<RunStatus> = new Set<RunStatus>([
  "succeeded",
  "failed",
  "cancelled",
  "needs_review",
]);

const Money = z.string().regex(/^-?\d+(\.\d+)?$/, "expected a decimal string");

export const PlanTaskSchema = z.object({
  id: z.string(),
  title: z.string(),
  agent: z.string(),
  state: z.string(),
  depends_on: z.array(z.string()).default([]),
  write_scope: z.array(z.string()).default([]),
});
export type PlanTask = z.infer<typeof PlanTaskSchema>;

export const StepSchema = z.object({
  id: z.string(),
  sequence: z.number(),
  agent_kind: z.string(),
  title: z.string(),
  status: z.string(),
  error: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
});
export type Step = z.infer<typeof StepSchema>;

export const ApprovalSchema = z.object({
  id: z.string(),
  run: z.string(),
  action_type: z.string(),
  summary: z.string(),
  payload: z.record(z.unknown()),
  state: z.enum(["pending", "approved", "rejected", "expired"]),
  expires_at: z.string(),
  decided_at: z.string().nullable(),
  decision_note: z.string(),
});
export type Approval = z.infer<typeof ApprovalSchema>;

export const RunSchema = z.object({
  id: z.string(),
  project: z.string(),
  objective: z.string(),
  status: RunStatusSchema,
  execution_target: z.string(),
  plan: z.array(PlanTaskSchema),
  cost_usd: Money,
  cost_cap_usd: Money,
  iterations: z.number(),
  error_code: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  created_at: z.string(),
});
export type Run = z.infer<typeof RunSchema>;

export const RunDetailSchema = RunSchema.extend({
  steps: z.array(StepSchema),
  pending_approvals: z.array(ApprovalSchema),
});
export type RunDetail = z.infer<typeof RunDetailSchema>;

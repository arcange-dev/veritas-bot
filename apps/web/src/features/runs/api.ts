/** Run and approval calls. Thin wrappers: contracts live in ./schemas. */
import { z } from "zod";
import { apiFetch } from "@/lib/api";
import {
  ApprovalSchema,
  RunDetailSchema,
  RunSchema,
  type Approval,
  type Run,
  type RunDetail,
} from "./schemas";

const CursorPage = <T extends z.ZodTypeAny>(item: T) =>
  z.object({
    next: z.string().nullable(),
    previous: z.string().nullable(),
    results: z.array(item),
  });

const base = (orgId: string) => `/api/v1/orgs/${orgId}`;

export interface StartRunInput {
  project: string;
  objective: string;
  execution_target?: "cloud" | "local";
  cost_cap_usd?: string;
}

export const runsApi = {
  list: (orgId: string) => apiFetch(`${base(orgId)}/runs/`, CursorPage(RunSchema)),

  detail: (orgId: string, runId: string): Promise<RunDetail> =>
    apiFetch(`${base(orgId)}/runs/${runId}/`, RunDetailSchema),

  start: (orgId: string, input: StartRunInput): Promise<Run> =>
    apiFetch(`${base(orgId)}/runs/`, RunSchema, { method: "POST", json: input }),

  control: (orgId: string, runId: string, action: "cancel" | "pause" | "resume"): Promise<Run> =>
    apiFetch(`${base(orgId)}/runs/${runId}/${action}/`, RunSchema, { method: "POST", json: {} }),

  approvals: (orgId: string, runId: string) =>
    apiFetch(`${base(orgId)}/approvals/?run=${encodeURIComponent(runId)}`, CursorPage(ApprovalSchema)),

  decide: (orgId: string, approvalId: string, approve: boolean, note = ""): Promise<Approval> =>
    apiFetch(`${base(orgId)}/approvals/${approvalId}/decide/`, ApprovalSchema, {
      method: "POST",
      json: { approve, note },
    }),
};

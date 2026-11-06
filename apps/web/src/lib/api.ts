/**
 * Every network call goes through here: one place attaches the Supabase JWT,
 * one place normalises the error envelope, one place parses the contract.
 */
import { z } from "zod";
import { parseErrorDetail, type FieldErrors } from "./errors";
import { env } from "./env";
import { getAccessToken } from "./auth";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId?: string,
    /** Per-field validation messages, when the server sent them (HTTP 400). */
    readonly fields: FieldErrors = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Init = Omit<RequestInit, "body"> & { json?: unknown; body?: BodyInit };

export async function apiFetch<T>(
  path: string,
  schema: z.ZodType<T, z.ZodTypeDef, unknown>,
  init: Init = {},
): Promise<T> {
  const { json, headers, ...rest } = init;
  const token = await getAccessToken();

  let response: Response;
  try {
    response = await fetch(`${env.apiBaseUrl}${path}`, {
      ...rest,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      ...(json !== undefined ? { body: JSON.stringify(json) } : {}),
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the API. Check your connection.");
  }

  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      code?: string;
      detail?: unknown;
      request_id?: string;
    };
    const parsed = parseErrorDetail(payload.detail, response.status);
    throw new ApiError(
      response.status,
      payload.code ?? "error",
      parsed.message,
      payload.request_id,
      parsed.fields,
    );
  }

  const body = response.status === 204 ? {} : await response.json();
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    // A contract violation is a bug, not a user error: surface it loudly.
    throw new ApiError(
      response.status,
      "contract_mismatch",
      `Unexpected response shape from ${path}`,
      response.headers.get("X-Request-Id") ?? undefined,
    );
  }
  return parsed.data;
}

// --- contracts ------------------------------------------------------------
export const ProjectSchema = z.object({
  id: z.string(),
  name: z.string(),
  slug: z.string(),
  description: z.string(),
  default_branch: z.string(),
  execution_preference: z.enum(["local", "cloud"]),
  created_at: z.string(),
});
export type Project = z.infer<typeof ProjectSchema>;

export const CredentialSchema = z.object({
  id: z.string(),
  provider: z.string(),
  label: z.string(),
  base_url: z.string(),
  status: z.enum(["unverified", "valid", "invalid", "revoked"]),
  last4: z.string(),
  last_validated_at: z.string().nullable().optional(),
  created_at: z.string(),
});
export type Credential = z.infer<typeof CredentialSchema>;

export const PageSchema = <T extends z.ZodTypeAny>(item: T) =>
  z.object({ results: z.array(item), next: z.string().nullable().optional() });

export const ProbeResultSchema = z.object({
  ok: z.boolean(),
  status: z.string(),
  error_code: z.string(),
  detail: z.string(),
  model_count: z.number(),
});
export type ProbeResult = z.infer<typeof ProbeResultSchema>;

export const api = {
  projects: (orgId: string) =>
    apiFetch(`/api/v1/orgs/${orgId}/projects/`, PageSchema(ProjectSchema)),

  createProject: (orgId: string, body: { name: string; execution_preference: string }) =>
    apiFetch(`/api/v1/orgs/${orgId}/projects/`, ProjectSchema, { method: "POST", json: body }),

  credentials: (orgId: string) =>
    apiFetch(`/api/v1/orgs/${orgId}/credentials/`, PageSchema(CredentialSchema)),

  createCredential: (
    orgId: string,
    body: { provider: string; label: string; api_key: string; base_url?: string },
  ) =>
    apiFetch(`/api/v1/orgs/${orgId}/credentials/`, CredentialSchema, {
      method: "POST",
      json: body,
    }),

  testCredential: (orgId: string, id: string) =>
    apiFetch(`/api/v1/orgs/${orgId}/credentials/${id}/test/`, ProbeResultSchema, {
      method: "POST",
    }),
};

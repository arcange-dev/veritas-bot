---
name: react-typescript-engineering
description: Implementation standards for the React 18 + TypeScript + Vite frontend - state ownership, data fetching with TanStack Query, Zustand boundaries, WebSocket stream handling, error boundaries, and typing the API layer. Use when writing components, hooks, stores, or API clients in apps/web.
---

# React + TypeScript Engineering

## When to use
Any component, hook, store, route, or API client work in `apps/web`.

## State ownership (decide once, keep it)
| Kind | Tool | Example |
|---|---|---|
| Server data | TanStack Query | projects, credentials list, run history |
| Streamed run events | Query cache + `setQueryData` | agent step updates |
| Ephemeral UI | Zustand | panel sizes, active tab, command palette open |
| Form state | React Hook Form + Zod | provider credential form |
| URL state | React Router search params | selected file, selected run |

Never copy server data into Zustand. Never store a token in Zustand or localStorage;
the Supabase session owns it.

## Typed API client

```ts
// src/lib/api.ts
import { z } from "zod";

const BASE = import.meta.env.VITE_API_BASE_URL;

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string,
              public requestId?: string) { super(message); }
}

export async function apiFetch<T>(
  path: string,
  schema: z.ZodType<T>,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const { json, headers, ...rest } = init;
  const token = await getAccessToken();           // from supabase session
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.code ?? "unknown",
      body.detail ?? res.statusText, body.request_id);
  }
  return schema.parse(await res.json());
}
```
Every response is parsed by a Zod schema from `packages/contracts`. `z.parse` failure is a
bug in the contract, not something to swallow.

## Query conventions
```ts
export const useProjects = (orgId: string) =>
  useQuery({
    queryKey: ["projects", orgId],
    queryFn: () => apiFetch(`/api/v1/orgs/${orgId}/projects/`, ProjectList),
    staleTime: 30_000,
  });
```
- Keys are arrays starting with the resource name, then scope ids, then filters.
- Mutations invalidate the narrowest key that changed.
- Optimistic updates only for toggle-like actions, always with rollback in `onError`.

## Streaming
Use one `RunStream` per open run, subscribing to `/ws/runs/<run_id>/`. Reduce events into
the query cache; do not keep an event array in component state beyond a bounded ring
buffer (last 500 entries). Always handle `onclose` with exponential backoff capped at 15s
and show a "reconnecting" chip.

## Component rules
- Presentational components take primitives, not query hooks. Container passes data.
- One exported component per file, named the same as the file.
- `useEffect` is for external synchronisation only. Derived values are computed inline.
- Error boundaries at route level; a crashed panel must not blank the studio: wrap each
  studio region in its own boundary with a reset action.
- No `any`. For genuinely unknown shapes use `unknown` plus a narrowing guard.

## Checklist
- [ ] `npm run typecheck` clean, no `@ts-expect-error` added.
- [ ] Loading/empty/error states implemented.
- [ ] Query keys follow convention and invalidation is correct.
- [ ] No secret ever read from `import.meta.env`.
- [ ] Component test covers the empty and error branches.

# Architecture

SuperAgent is a modular monorepo with four executable surfaces and one hard rule: the
process that serves HTTP never executes user code.

## Context map

```
                    ┌──────────────┐
   browser  ───────▶│  apps/web    │  React SPA, Vercel
                    └──────┬───────┘
                           │ HTTPS + WSS, Supabase JWT
                    ┌──────▼───────┐        ┌───────────────┐
                    │  apps/api    │◀──────▶│  Supabase     │
                    │  Django+DRF  │        │  Auth+Postgres│
                    └──┬────┬───┬──┘        └───────────────┘
                       │    │   │
             ┌─────────▼┐ ┌─▼───┴────┐ ┌──────────────┐
             │  Redis   │ │  Celery  │ │ Daytona      │
             │ queues   │ │ workers  │ │ cloud sandbox│
             └────┬─────┘ └──────────┘ └──────────────┘
                  │ outbound WSS only
           ┌──────▼─────────┐
           │ apps/local-    │  runs on the user's machine
           │ runner         │  no inbound port
           └────────────────┘
```

Invariant: the arrow from `apps/api` to a sandbox or runner carries a command, never a
credential and never an execution. `subprocess` inside a request path is a defect.

## Bounded contexts

| Context | Django app | Owns | Must not |
|---|---|---|---|
| Identity | `identity` | Profiles, organizations, memberships, invitations, JWT verification | Know about projects or AI |
| Providers (BYOK) | `providers` | Credential storage and encryption, capability catalogue, validation probes, model resolution | Stream chat or own conversations |
| Projects | `projects` | Projects, repositories, index, deployments | Execute code |
| Orchestration | `orchestration` | Graph state, runs, steps, approvals, agents | Touch a filesystem directly |
| Tools | `tools` | Tool registry, argument schemas, dispatch, audit | Decide product permissions |
| Execution | `execution` | `ExecutionBackend` adapters, sessions, devices, sandboxes | Contain business rules |
| Billing | `billing` | Usage records, cost estimation, spend caps | Call providers |
| Audit | `audit` | Append-only audit log, notifications | Be written to by the model |

Dependency direction: `orchestration → tools → execution`; `providers` is consumed by
`orchestration` but never imports it; `identity` and `audit` are leaves. A cycle is a defect.

## Request path

1. `SupabaseJWTAuthentication` verifies the token (HS256 secret, or RS256/ES256 against the
   cached JWKS, refetched once on an unknown `kid`, then fail closed).
2. The token's `sub` maps to an `identity.Profile`, created on first sight.
3. `IsOrgMember` resolves the membership from the URL `org_id` (or `X-Org-Id`), attaches
   `request.org`, and returns 404 when the caller is not a member, so ids stay unenumerable.
4. The view delegates to a service; the queryset is scoped with `core.tenancy.for_org`.
5. `core.errors.exception_handler` renders `{code, detail, request_id}` and never leaks
   internals.

## BYOK credential lifecycle

```
POST /credentials {provider, api_key, base_url}
  → encrypt_secret()            Fernet/MultiFernet, key id recorded on the row
  → ProviderCredential(secret_encrypted, key_id, last4)
  → response contains last4 only; api_key is popped before save

POST /credentials/{id}/test
  → decrypt_secret()            the only decrypting caller in the codebase
  → probes.probe(provider, key) cheapest authenticated call, 8 s timeout
  → status valid|invalid, last_error_code persisted

rotation: prepend a new key to BYOK_ENCRYPTION_KEYS → deploy → reencrypt task → drop old
```

## Orchestration

```
orchestrator ──plan──▶ plan ──▶ orchestrator ──dispatch──▶ specialists (parallel batch)
     │                                            │
     └── state: RunState (JSON only)              └── write-scope disjointness enforced
                    │
                    └── checkpoint per node, resume by thread_id = run_id
```

Routing is pure and unit-tested (`orchestration/routing.py`): plan validation rejects
duplicate ids, unknown dependencies, self-dependencies and cycles; `select_parallel_batch`
returns a greedy, deterministic, non-overlapping set; `next_action` chooses
approval / re-plan / dispatch / finish and refuses to run past the iteration limit.

## Execution boundary

`ExecutionBackend` is the only contract. Three implementations exist: `FakeBackend` (tested),
`DaytonaBackend` (unverified) and `LocalRunnerBackend` (stub). Adding a provider means adding
an adapter and registering it, never branching on a provider name in a view or node.

Every command passes `ToolRegistry.dispatch`, which validates the Pydantic argument schema,
checks the agent allowlist, requires an approval record for destructive tools, enforces a
timeout, caps output at 200 KB and writes a `ToolInvocation` audit row with hashed, redacted
arguments.

## Data model

26 domain tables across nine apps: identity (4), providers (2), projects (4), orchestration
(6), tools (1), execution (4), billing (1), audit (2), plus core primitives. UUID primary
keys, `organization` foreign key on every tenant table, explicit constraint and index names,
`CheckConstraint` for enum-like fields instead of Postgres enums.

## Open architectural gaps
1. RLS policies are not written (SEC-001). Tenancy is Django-only today.
2. The runner WebSocket consumer and pairing endpoints are not implemented.
3. `AUTH_USER_MODEL` mismatch (ADR-004).

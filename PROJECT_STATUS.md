# Project status

As of 2026-10-30. Verified means a command was run and its output inspected.

## Verified working

| Area | Evidence |
|---|---|
| Backend suite | `pytest` → **69 passed** (sqlite test settings) |
| Django integrity | `manage.py check` clean; `makemigrations --check` → no drift |
| Schema | 24 domain tables (33 including Django's) created from 8 migrations on a fresh database |
| Frontend types | `tsc --noEmit` → 0 errors |
| Frontend tests | `vitest` → **7 passed** |
| Frontend build | `vite build` → 1693 modules, ~321 kB app chunk |
| Local runner | `pytest` → **51 passed** |
| Claude environment | validator → 15 skills, 11 subagents |
| Secret scan | 0 key-shaped strings in the repo |

**Runner relay (closed this session).** A Django call now reaches a real device:
`RunnerRelay` creates a per-request reply channel, the consumer forwards the frame,
the device answers, and the caller gets the result. Proven by `tests/test_runner_relay.py`
driving the actual `RunnerConsumer` over `WebsocketCommunicator`: round trip,
refusal propagation, offline fast-fail (<1s, not the 30s timeout), disconnect
waking in-flight callers, and output frames reaching a session subscriber.

**Pairing (closed this session).** `POST /api/v1/orgs/{id}/runners/pairing-codes/`
(admin) → `POST /api/v1/runners/claim/` (public, throttled 20/hour, 5 attempts,
10-minute TTL, single use, hashed at rest) → device row + device-bound token.
Unknown, used and expired codes return an identical message so the endpoint
cannot confirm a code ever existed. Revocation kills live tokens (tested).

**Frontend streaming.** `useSessionStream` + `streamBuffer` attach the xterm panel
to `?session=<id>`, dedupe reconnects, and flag sequence gaps instead of hiding a
truncated transcript.

## Definition of done

| # | Requirement | State |
|---|---|---|
| 1 | Register + authenticate | Partial: JWT verification implemented, not exercised against a live Supabase project |
| 2 | Create a project | Yes: API + tests |
| 3 | Connect a provider via BYOK | Yes: API + tests |
| 4 | Key encrypted at rest | Yes: MultiFernet, rotation, tamper detection |
| 5 | Connection testable | Coded; live probe unverified (no provider key) |
| 6 | Models selectable | Partial: registry + capability checks, no discovery UI |
| 7 | Chat with main agent | No |
| 8 | Structured plan | Partial: `routing.py` validated by tests, graph not run |
| 9 | Specialists complete tasks | No |
| 10 | Agents touch real files | Yes at the adapter layer, not driven by a graph yet |
| 11 | Runner connects securely | Yes: pairing + handshake + token tests |
| 12 | Local code executes | Yes at protocol level (relay tests); not with a real machine here |
| 13 | Cloud workspaces | No: Daytona unverified |
| 14 | Cloud code executes | No |
| 15 | Terminal streams to frontend | Yes: consumer → group → hook → xterm |
| 16 | Monaco view/edit | Partial: host + optional loader, package not installed |
| 17 | Tests execute | Runner-side only |
| 18 | Errors detected and corrected | No |
| 19 | GitHub PRs | No |
| 20 | Deployment needs authorisation | Design only |
| 21 | Usage and cost visible | Partial: exact Decimal cost maths + caps, no UI |
| 22 | Tenant isolation | Yes for HTTP and the terminal socket |
| 23 | Stop tasks and clean up | Partial: `stop` relayed, no scheduler |
| 24 | Admin audit without plaintext keys | Partial: audit log + redaction, no admin UI |

## Not started

Phase 3 orchestration endpoints (`/runs`), Phase 6 Daytona, Phase 7 GitHub and the
Monaco bundle, Phase 8 admin UI, Playwright E2E, CI runs,
any deployment.

## Known gaps

- **SEC-001 (mitigated, not closed):** RLS is written and tested on real Postgres 16 as an unprivileged role, but never against Supabase. Celery run execution binds its tenant (tested); Channels consumers and management commands do not yet. Isolation now has two walls (the ORM scoping layer and
  database RLS), but the second has only been exercised on a throwaway local Postgres.
- `AUTH_USER_MODEL` is still `auth.User` while DRF authenticates a `Profile`.
  Consistent and tested, but worth unifying.
- Studio toolbar actions (Build/Run/Test) call no endpoint yet; the code says so.
- Monaco and xterm are optional imports. The fallback path is what built here.


## Update 2026-11-01

| Check | Result |
|---|---|
| Backend, real PostgreSQL 16 | **217 passed** |
| Backend, SQLite | 176 passed, 41 skipped (Postgres-only RLS tests) |
| LangGraph engine | executed for real; 4 defects found and fixed (see TESTING_REPORT) |
| Run lifecycle API | create / start / pause / resume / cancel / approve / reject |
| JWT verification | 20 tests through the real authenticator, mutation-checked |
| Row-level security | 24 policy tests + 3 HTTP tests as unprivileged role |

Still not done: Studio screens for chat/plans/approvals, Daytona, GitHub App, real Monaco bundle,
Playwright E2E, CI runs, any deployment, any real Supabase or real provider call.


## Update 2026-11-03: Studio run and approval UI

| Check | Result |
|---|---|
| Backend, real PostgreSQL 16 | **224 passed** |
| Backend, SQLite | 177 passed, 47 skipped (Postgres-only RLS and worker tests) |
| Frontend | **53 passed** across 6 files; `tsc` clean; production build succeeds |
| Migration drift | none |

**New and working (tested):**
- Run API client and TanStack Query hooks (`apps/web/src/features/runs/`). The wire schemas were validated against a
  *real* backend response captured from the Django API, not a hand-written fixture.
- `AgentPanel`: start a run, live progress, spend against cap, pause / resume / stop, translated error messages.
- `PlanApprovals`: plan tasks with owners and dependencies, approve / reject, and the approval card shows the
  **exact payload** being approved (the server binds the decision to a hash of it).
- Polling stops once a run reaches a terminal state; slows while waiting on a human.

**Bugs found and fixed while building it:**
- `apiFetch` typed `schema` as `ZodType<T>`, which rejects any schema using `.default()`. Fixed at the shared signature.
- My first `schemas.ts` write was truncated to 0 bytes by a dropped connection and went unnoticed until re-checked.
- Money is parsed as a decimal *string*; `z.number()` would have rejected every real response.

**Removed dishonest UI:** the Studio had a fake `onAction` that slept 400 ms and logged to the console, a hardcoded
"no pending approvals" line, and a Git badge that always read "clean". The toolbar buttons Build, Run, Test and
Preview are now **disabled with the reason**, because no endpoint exposes command execution to the browser yet.

**Still not done / not verified:**
- Build / Run / Test / Preview do nothing (no execution endpoint). Git status is not connected.
- The component tests mock `fetch`. **No browser has loaded this UI against the live API** (no Playwright run yet).
- Nothing has run against real Supabase or a real model provider. The graph has only run with a scripted model.
- Daytona adapter, GitHub App, real Monaco bundle, CI, and any deployment remain unbuilt.
- The throwaway local Postgres is destroyed when the sandbox restarts; it must be recreated before the Postgres suite runs.

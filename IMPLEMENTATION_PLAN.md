# Implementation plan

Nine phases. A phase is done only when its tests run and its report is written.
Current position: **Phase 1 partially complete, Phase 2 and 4 foundations landed early.**

## Phase 1 — Repository, auth, database foundation
Status: **mostly done.**
- [x] Monorepo, Claude Code environment (15 skills, 11 subagents, rules, hooks, validator)
- [x] Django project, settings per environment, health check, error envelope, redaction
- [x] Supabase JWT verification (HS256 tested, JWKS untested)
- [x] Models for every domain in the brief (26 tables), migrations applied
- [x] Frontend shell: tokens, router, dashboard, providers page, studio layout
- [ ] RLS policies (SEC-001)
- [ ] Sign-in flow exercised against a live Supabase project

## Phase 2 — BYOK, catalogue, streaming chat
Status: **storage and validation done, streaming not started.**
- [x] Credential encryption, rotation, `last4`-only exposure
- [x] Validation probes for 13 provider shapes
- [x] Capability registry model, cost fields, capability gate
- [x] Model resolution with recorded fallback reason
- [ ] Catalogue refresh task per provider
- [ ] LiteLLM adapter layer and streaming responses
- [ ] Chat UI wired to a real stream

## Phase 3 — LangGraph orchestration
Status: **logic done, graph execution unverified.**
- [x] Typed state with reducers, JSON-only
- [x] Plan validation, parallel batch selection, next-action routing (13 tests)
- [x] Graph topology compiled when `langgraph` is installed
- [ ] Postgres checkpointer wired to `thread_id = run_id`
- [ ] Specialist prompts and tool subsets per agent
- [ ] Approval interrupt/resume round trip

## Phase 4 — Tool registry and approvals
Status: **done for the registry; approval lifecycle partial.**
- [x] Registry with allowlist, schema validation, destructive gate, audit, redaction
- [x] Argument hashing and payload-hash approval model
- [ ] Approval API endpoints and UI
- [ ] Approval replay protection test against the live graph

## Phase 5 — Local runner
Status: **runner done and tested; server side missing.**
- [x] Package, CLI (`pair`/`allow`/`run`/`doctor`), config with 0600 perms
- [x] Path authorisation, command policy, process supervision, env scrubbing (51 tests)
- [x] Outbound WebSocket client with backoff and hello frame
- [ ] `POST /api/v1/runners/pairing/` and `/claim/`
- [ ] Channels consumer at `ws/runner/`
- [ ] End-to-end: pair a real machine, run `pytest`, stream output to the UI

## Phase 6 — Daytona cloud execution
Status: **adapter written, entirely unverified.**
- [ ] Verify lifecycle against a real account
- [ ] Log streaming transport
- [ ] Orphan reconciliation job
- [ ] Preview URL signing and gateway
- [ ] Cost model and idle reaper

## Phase 7 — Developer Studio, Monaco, xterm, GitHub
Status: **layout and hosts done; integrations missing.**
- [x] Five-region resizable layout, accessible splitters, persisted sizes (3 tests)
- [x] Editor and terminal hosts with graceful fallback when packages absent
- [ ] Install Monaco/xterm and verify the real editor path
- [ ] File tree from a real repository index
- [ ] GitHub App token exchange, webhooks, branch/commit/PR flows

## Phase 8 — Organisations, admin, usage
- [ ] Membership and invitation UI
- [ ] Usage dashboard from `billing_usage`
- [ ] Platform admin: audit view and system health, never plaintext credentials
- [ ] Notifications delivery

## Phase 9 — Hardening, QA, deployment
- [ ] Close SEC-001/002/003/007
- [ ] CI executing all suites on every push
- [ ] Playwright happy path
- [ ] Staging deploy, backup and restore rehearsal
- [ ] Final verified delivery report

## Sequencing rule
Do not start Phase 6 before Phase 5 has an end-to-end run, and do not start Phase 8 before
RLS exists. Both shortcuts create rework that costs more than the ordering does.

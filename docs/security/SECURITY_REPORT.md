# Security report

Date: 2026-10-30. Scope: the code in this repository as committed. No production environment
exists yet, so nothing here reflects a deployed posture.

## Findings

| ID | Severity | Area | Finding | Status |
|---|---|---|---|---|
| SEC-001 | **Medium** (was High) | Tenancy | **Mitigated, not closed.** RLS is enabled and forced on all 24 tenant tables, verified on real PostgreSQL 16 as an unprivileged role (24 policy tests, plus HTTP tests that sabotage the ORM filter). Remaining: (1) nothing has run against a real Supabase project, where the connecting role and pooler (transaction mode) behaviour are unverified; (2) the database trusts `app.current_org`, so `core/rls.py` is now a critical trust boundary; (3) Channels consumers and management commands do not yet bind a tenant and would see zero rows as `sa_app` (Celery run execution does, and is tested). | **Mitigated** |
| SEC-002 | **High** | Execution | `execution/local.py` and `daytona.py::stream_logs` raise `NotImplementedError`. A caller that does not handle it will fail the run, but there is no compile-time guarantee that no code path treats a stub as working. | **Open** (by design, must be closed before Phase 5/6) |
| SEC-003 | Medium | Auth | Supabase RS256/JWKS verification has never been exercised against a live project. Key rotation and `kid`-miss refetch are implemented but untested. | **Open** |
| SEC-004 | Medium | GitHub | Webhook HMAC verification is specified in the skill and sketched in the architecture, but no handler exists. When it is written, verification must happen on the raw body before parsing. | **Open** (not yet implemented) |
| SEC-005 | Medium | Runner | The server-side pairing claim endpoint does not exist, so a device token can only be minted in tests. `PairingCode` stores a hash and tracks attempts, but there is no rate limit enforced yet. | **Open** |
| SEC-006 | Low | Auth | `AUTH_USER_MODEL` is `auth.User` while `request.user` is `identity.Profile` (ADR-004). Confusing, not currently exploitable. | Accepted debt |
| SEC-007 | Low | CSP | No Content-Security-Policy header is set by Django or the frontend host. Required before production, and it needs to accommodate Monaco's worker blobs when Monaco is enabled. | **Open** |

## Controls that are implemented and tested

- **Credential encryption.** Fernet/MultiFernet, key id per row, rotation verified by test,
  tampered ciphertext rejected without leaking material. Ciphertext never appears in a
  `__repr__` or an API response (tests assert both).
- **Credential exposure.** `api_key` is write-only on the serializer and popped before save;
  `last4` is the only fragment serialized. A response-body redaction middleware scrubs
  key-shaped strings as a second wall and logs loudly if it ever fires.
- **Tenancy.** `for_org()` refuses `None` rather than returning unscoped rows. Cross-tenant
  reads return 404, not 403, so ids are not enumerable. Tested for projects and credentials.
- **Tool authorisation.** Tools come from the server-side registry; the model cannot widen its
  own allowlist. Destructive tools require an approval record. Every dispatch, including
  denials, writes a `ToolInvocation` row with a hashed, redacted argument preview.
- **Prompt injection.** Repository content is treated as data. File content cannot grant a
  permission because permission checks never read model output.
- **Runner isolation.** Outbound-only; path resolution rejects traversal, absolute escapes and
  symlinks; child env is an allowlist with forbidden keys that cannot be re-added; process
  groups are killed on timeout and on stop. 51 tests.
- **Cost abuse.** Run and organisation caps are checked before dispatch with Decimal maths;
  `SpendCapExceeded` is a typed error.
- **Log hygiene.** A logging filter applies redaction to every record including Celery and the
  ASGI access log.

## Explicitly not done
- No penetration test, no dependency audit in CI (`pip-audit`, `npm audit`, `bandit` are in
  `requirements.txt` and the CI shape, never executed here).
- No CSP, no rate-limit tuning under load, no lockout policy for the pairing endpoint.
- No SSRF guard module yet. The provider `base_url` field is validated for scheme only. A full
  guard (resolve, reject private ranges and metadata IPs, re-resolve after redirect) is
  required before custom `base_url` values are allowed in production.
- No secrets manager. Keys come from environment variables, which is acceptable for Render and
  not for a larger deployment.

## Release gate
Do not call this production-ready while SEC-001, SEC-002, SEC-003 and SEC-007 are open. Each
needs either a fix with a test that proves it, or a written, dated acceptance by the owner.

## Addendum - 0.2.0 (relay and pairing)

Reviewed and enforced this session:

- **The runner chooses nothing.** The server creates the reply channel; the
  device is never told a channel name and cannot address another caller or tenant.
- **Pairing codes are the only unauthenticated write.** Hashed at rest, single use,
  10-minute TTL, 5 attempts, 20 claims/hour/IP, and identical failure text for
  unknown/used/expired so the endpoint cannot confirm a code existed.
- **Tokens are device-bound** (`sub = device_id`, `aud = runner`), 15 minutes,
  and revocation invalidates live tokens immediately (tested).
- **Presence is a cache TTL**, so a killed runner cannot appear available.
- **The terminal socket checks tenancy**, not just authentication: a valid token
  for another organisation is refused (4403).
- **Approval ids cannot escalate.** The runner re-applies its own policy; an
  approval satisfies ASK-level commands only and never a DENY. A compromised
  platform cannot weaponise a user's machine.
- **Disconnect wakes in-flight callers** rather than leaving a task hung, and the
  queue is capped at 512 frames so a slow device cannot exhaust server memory.

Still open:

- **SEC-001 (medium, mitigated):** RLS is enabled, forced and tested on real PostgreSQL 16 as an unprivileged role, including Celery run execution. Not yet verified against Supabase; Channels consumers and management commands do not yet bind a tenant.
- **SEC-002 (medium):** `AUTH_USER_MODEL` is `auth.User` while DRF authenticates
  `Profile`. Consistent, but two identity concepts should not coexist long-term.
- **SEC-003 (medium):** runner token uses HS256; EdDSA is wired but unexercised.
- **SEC-004 (low):** the pairing claim endpoint is throttled per IP only; per-org
  limits would blunt distributed attempts.


## Row-level security addendum (2026-11-01)

**What exists.** Migrations `core/0001..0003` enable and FORCE RLS on every tenant table (24), using a
fail-closed helper `app_current_org()` that returns NULL when unset. Child tables inherit through an
`EXISTS` on their parent. `identity_profile` is visible to its owner and to members of the current org.
`identity_membership` additionally allows a person to read their own rows, which the authorisation check
needs before a tenant is bound. `providers_model` is a shared catalogue and is intentionally not scoped.

**How it is bound.** `core/rls.py` sets `app.current_org` / `app.current_profile` with
`set_config(..., true)` (transaction-local) only after verifying active membership. `TenantBoundMixin`
opens that transaction in DRF `initial()` for every org-scoped viewset; `tests/test_tenant_routes.py`
fails CI if a new org-scoped route lacks the mixin.

**Defects found while building it (all fixed, all covered by tests).**
1. Membership lookup ran before any identity was bound, so under a real role every user got 404.
2. `select_related` joined tables that RLS hides until the tenant is bound, dropping the row.
3. Rolling back on every 4xx and then running cleanup SQL raised `TransactionManagementError`.
Every one of these was invisible when connected as a superuser, which bypasses RLS. **Any future RLS test
must connect as `sa_app`; a green run as `postgres` proves nothing.**

**Not covered / residual risk.**
- Production must connect as a non-superuser without BYPASSRLS. Supabase's default `postgres` role
  has BYPASSRLS; a dedicated role is required. Unverified against a real project.
- Supabase's pooler in *transaction* mode is compatible with transaction-local settings; session mode
  with `SET` (not used here) would not be. Unverified.
- Celery run execution now binds its tenant (`core.rls.ambient_tenant` + short `bound()` transactions; 6 tests
  as `sa_app`, including revoked-member and cross-tenant refusal). **Channels consumers and management
  commands still do not bind a tenant** and would see zero rows as `sa_app`.
- A running worker verifies membership once at start. A member revoked mid-run keeps the run going until
  it ends; it is not re-checked per query. Accepted trade-off, bounded by the run's cost cap and timeout.
- Raw SQL anywhere can call `set_config` and re-point the tenant; the tool registry does not expose raw
  SQL to models, but this is a convention, not an enforced barrier.

### Worker defects found (2026-11-01)
1. **Deadlock.** Wrapping a whole run in one tenant transaction held row locks that parallel task threads
   then blocked on, hanging the worker (pg_stat_activity: one `idle in transaction`, one waiting on
   `transactionid`). Fixed by a thread-local ambient identity and short per-operation transactions.
2. **False-green RLS test.** `SET ROLE` affects one connection; `close_old_connections()` and worker threads
   reconnected as the superuser, so the first worker-under-RLS test passed while bypassing RLS entirely.
   The test now sets the connection USER and asserts every connection, including threads, is unprivileged.
3. **Hidden lazy queries.** `run.organization` is a query; under RLS it returns nothing outside a bound
   transaction. Replaced with explicit `*_id` filters and bound loads.

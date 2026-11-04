# Architecture decision records

## ADR-001: Supabase Auth as the only identity provider

Date: 2026-10-30. Status: accepted.

**Context.** The product needs multi-tenant identity, and the brief mandates Supabase Auth
with PostgreSQL.
**Decision.** Supabase owns credentials and sessions. Django verifies its JWTs and stores a
`Profile` row per Supabase user. No password column, no second session store.
**Alternatives.** Django's own auth (rejected: two credential systems, the exact conflict the
brief forbids).
**Consequences.** Every API request costs a token verification (cached JWKS). Token revocation
is Supabase's responsibility; we fail closed on verification errors.

## ADR-002: Django migrations only, RLS as a second wall

Date: 2026-10-30. Status: accepted (RLS portion **not yet implemented**).

**Context.** Supabase clients and future services could reach Postgres directly.
**Decision.** All schema changes go through Django migrations. RLS mirrors the Django
permission model for defence in depth; it does not replace permission classes.
**Consequences.** Two places to keep in sync, hence a rule that a tenant table and its policy
ship in the same migration. Current state: policies missing, tracked as SEC-001.

## ADR-003: MultiFernet envelope encryption for BYOK keys

Date: 2026-10-30. Status: accepted.

**Context.** Users store third-party API keys. A database leak must not expose them.
**Decision.** `cryptography.fernet.MultiFernet`, keys supplied as `kid:base64key` from the
environment, newest first, `key_id` recorded per row. Decryption confined to
`providers/crypto.py`.
**Alternatives.** KMS per-row wrapping (better, requires cloud infra and a cost decision),
plain `Fernet` (no rotation path).
**Consequences.** Rotation is a deploy plus a re-encrypt task. A lost key means credentials
must be re-entered, not recovered. This is the correct failure mode.

## ADR-004: `request.user` is a Profile — known inconsistency

Date: 2026-10-30. Status: accepted, with debt.

**Context.** Django expects `AUTH_USER_MODEL` to be a user model. We never use Django's auth
user, but DRF's `IsAuthenticated` and `AnonymousUser` machinery still need the auth app.
**Decision.** Leave `AUTH_USER_MODEL = auth.User`, authenticate to `identity.Profile`, and
make `core.permissions` tolerant of both shapes.
**Consequences.** Confusing for a new engineer, and a future source of bugs if something
assumes `request.user.pk` is a Django user. The clean fix is a custom user model, which needs
a migration plan across every FK. Tracked as debt, not as done.

## ADR-005: Approvals bind to a payload hash

Date: 2026-10-30. Status: accepted.

**Context.** "Approve the pull request" must not become "approve whatever runs next".
**Decision.** `ApprovalRequest` stores the action payload, its SHA-256, an expiry and the
decider. At execution the hash is recomputed; a mismatch fails the resume.
**Consequences.** Editing an approved action requires a new approval. That is the point.

## ADR-006: Local runner is outbound-only with a local deny-list

Date: 2026-10-30. Status: accepted.

**Context.** The runner has the user's real machine. Assume the platform can be compromised.
**Decision.** No inbound port. User-approved workspace roots stored locally. A local command
policy that deny-wins and cannot be overridden or disabled by the server. An allowlisted child
environment that strips the runner's own tokens.
**Consequences.** Some legitimate commands need an approval id, and some are simply refused.
Debugging "why did my command not run" now involves reading `verdict.reason`.

## ADR-007: Optional Monaco/xterm with a functional fallback

Date: 2026-10-30. Status: accepted.

**Context.** Monaco is ~1 MB and not needed for the app to boot or for CI to pass.
**Decision.** Declare both as optional dependencies, load them with a runtime dynamic import,
and degrade to a textarea and a `<pre>` when absent. Failures are visible in the UI.
**Consequences.** The studio is never a dead panel. Enabling the full editor requires
`npm i monaco-editor @xterm/xterm @xterm/addon-fit`, which was not done here.

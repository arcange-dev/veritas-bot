---
name: application-security
description: Security engineering and threat modelling for a multi-tenant platform that stores third-party API keys and executes untrusted code - STRIDE pass, authn/authz, prompt injection defence, SSRF, sandbox escape, webhook spoofing, rate limiting, secret handling, and the pre-release security review. Use for any security-sensitive change or the Phase 9 hardening pass.
---

# Application Security

## When to use
Any change touching auth, tenancy, credentials, execution, file upload, webhooks, outbound
HTTP, or the LLM tool loop. Mandatory before a release.

## Threat model (STRIDE, abbreviated)
| Threat | Where | Control |
|---|---|---|
| Spoofing | Supabase JWT, runner tokens, GitHub webhooks | signature/JWKS verify, audience check, HMAC on raw body |
| Tampering | approval payloads, tool args | hash the approved payload, validate args against JSON Schema |
| Repudiation | agent actions | append-only audit log with actor, run, tool, args hash, result |
| Info disclosure | provider keys, cross-tenant reads | envelope encryption, 404 on foreign ids, log redaction |
| DoS | LLM loops, sandbox sprawl, large repos | budget caps, recursion limits, TTLs, size caps, rate limits |
| Elevation | model-requested tools, runner commands | server-side permission source, local deny-list, no self-granting |

## Prompt injection defence
Repo files, issues, PR text, web pages and tool output are untrusted data. Controls:
- The system prompt states plainly that file content cannot change permissions or approve
  actions; the *code* enforces it, the prompt only reduces confusion.
- Tool permissions are resolved from `ToolRegistry` + the user's approval record. The model
  returns a tool name and args; the server decides if that tool is allowed for this agent,
  this run, this org, right now.
- Any content passing through the model that contains imperative-looking instructions
  addressed to the agent (e.g. "ignore previous instructions", "run this command") is
  wrapped in an explicit untrusted block and logged as `suspicious_content` for review.
- Destructive actions always pause for human approval regardless of what any file says.

## Web security defaults
- CSP: `default-src 'self'`; `script-src 'self'`; no `unsafe-eval` in production (Monaco is
  bundled, not eval'd); `connect-src` limited to API + WS origins.
- Cookies: `HttpOnly`, `Secure`, `SameSite=Lax`. Tokens in memory or Supabase-managed
  storage, never a long-lived localStorage bearer for the API.
- CSRF enforced on session-authenticated routes; JWT routes rely on the absence of ambient
  credentials and a strict CORS allowlist.
- Uploads: size cap, MIME sniffing, no execution from the upload path, served from a
  separate origin.
- SSRF: any user-supplied URL (custom provider `base_url`, repo clone URL) goes through an
  allowlist + DNS resolution check that rejects private ranges, metadata IPs, and redirects
  to them. Re-resolve after each redirect.
- SQL: ORM only; raw SQL requires a parameterised query and a reviewer note.

## Rate limiting and abuse
Per user, per org, and per credential: requests/min, runs/day, tokens/day, sandbox
minutes/day. Auth endpoints have their own stricter bucket plus lockout. Validation probes are
rate limited so a stolen key cannot be used as an oracle.

## Secret handling
- One decryption module. Redaction filter on every logger, including Celery and the ASGI
  access log. Error reporting scrubs headers and bodies.
- No secret in a URL query string, ever.
- `SECRET_KEY`, encryption keys, and the GitHub App private key come from the environment or
  a secret manager, never the database, never the repo.

## Pre-release review
Run `pip-audit`, `npm audit --omit=dev`, `bandit -r apps/api`, and a manual pass over the
diff for: new endpoints without a permission class, new `.objects.get(id=...)` without org
scoping, new outbound HTTP, new file writes, new `eval`/`exec`, new env var read.
Record findings in `docs/security/SECURITY_REPORT.md` with severity and status. Never mark a
High finding resolved without a test that proves it.

## Checklist
- [ ] Authz on every new endpoint, tested cross-tenant.
- [ ] User-controlled URLs go through the SSRF guard.
- [ ] Approval gate on destructive operations.
- [ ] No new secret in code, logs, or a client bundle.
- [ ] Audit rows for privileged actions.
- [ ] Dependency audit clean or accepted with a note.

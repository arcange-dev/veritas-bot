---
name: cloud-sandbox-execution
description: Daytona cloud sandbox adapter engineering - workspace lifecycle, image selection, non-root execution, quotas and TTL, preview URLs, egress policy, artifact retrieval, and cleanup guarantees behind a provider-neutral ExecutionBackend. Use when working in apps/api/execution/daytona or adding a new cloud execution provider.
---

# Cloud Sandbox Execution

## When to use
Changes to `apps/api/execution/daytona/**`, sandbox lifecycle, preview gateway, or when
evaluating a new cloud execution provider (E2B, Modal, Fly Machines).

## Non-negotiables
- The Django host never executes user code. No `subprocess`, no `os.system`, no `exec` in
  `apps/api` outside test helpers and management commands that operate on our own tooling.
- Ordinary Docker containers are **not** a sufficient multi-tenant boundary. Isolation comes
  from the provider's VM/microVM boundary, not from a namespace.
- Every sandbox is created with a TTL, a CPU/memory ceiling, a disk cap, and a hard
  wall-clock limit. There is no "unlimited" sandbox.
- Egress is deny-by-default except an allowlist (package registries, the user's git host,
  the model provider endpoints the org actually uses). Block metadata endpoints
  (169.254.169.254) and RFC1918 explicitly.

## Lifecycle
```
provision -> clone -> install -> run -> [stream] -> snapshot artifacts -> destroy
```
Each transition writes `CloudSandbox(status, provider, external_id, region,
created_at, expires_at, last_activity_at, cost_accrual)`.

```python
# execution/daytona/backend.py
class DaytonaBackend(ExecutionBackend):
    def create_session(self, spec: SessionSpec) -> SessionHandle:
        ws = self.client.workspace.create(
            image=spec.image,                     # pinned digest, never :latest
            resources=Resources(cpu=spec.cpu, memory_gb=spec.memory_gb,
                                disk_gb=spec.disk_gb),
            ttl_minutes=spec.ttl_minutes,
            env=self._scoped_env(spec),           # no platform secrets, no user API keys
            user="agent",                         # non-root
        )
        return SessionHandle(id=ws.id, provider="daytona", region=spec.region)
```
`_scoped_env` injects only short-lived repo-scoped git tokens and project env vars the user
explicitly marked as safe for sandboxes. Model credentials are never injected: if the graph
needs to call a model while a sandbox is open, the call goes back through the API, never
through the sandbox.

## Git inside the sandbox
Use a GitHub App installation token scoped to the single repository, 60-minute expiry,
`contents:write` only on a working branch. Never the user's personal token, never an org-wide
installation token.

## Preview URLs
Sandbox-exposed ports are proxied through our own gateway with:
- a signed, expiring URL bound to the run and the requesting user session,
- `X-Frame-Options` set deliberately (allow only our own origin),
- no direct sandbox hostname exposure to the browser,
- rate limiting per run per minute,
- a kill switch that invalidates all previews when the sandbox is stopped.

## Cost and cleanup
- Idle detection: no command and no preview hit for 10 minutes -> pause/destroy.
- A Celery beat sweep every 5 minutes destroys sandboxes past `expires_at` and reconciles
  `CloudSandbox` rows against the provider API. Orphans (provider-side but not in our DB)
  are destroyed and recorded in the audit log.
- `stop` is idempotent and must succeed even if the provider already destroyed the sandbox.

## Testing
Integration tests run against a real Daytona account, gated by `DAYTONA_API_KEY` and
`DAYTONA_TEST=1`. They assert: non-root user, TTL enforced, egress blocked to a canary
host, path escape rejected, cleanup leaves zero sandboxes. A local fake backend
(`execution/fake.py`) implements the same protocol for CI without credentials.

## Checklist
- [ ] New provider implements the full `ExecutionBackend` protocol and the conformance test.
- [ ] Image pinned by digest; non-root user; no privileged mode.
- [ ] TTL, quota, and idle reaper present.
- [ ] No platform or user model secrets in sandbox env.
- [ ] Preview URL signed and expiring; invalidated on stop.
- [ ] Orphan reconciliation in place.

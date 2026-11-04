---
name: deployment-and-devops
description: CI/CD and hosting for the platform - GitHub Actions pipeline shape, Render services and health checks, Vercel frontend config, Supabase environment separation, migration gating, rollback, and observability. Use when changing CI, infrastructure, environment config, or a release procedure.
---

# Deployment and DevOps

## When to use
Editing `.github/workflows`, `infrastructure/**`, Render/Vercel config, environment
matrices, or running a release.

## Environments
| Env | Frontend | API | DB | Purpose |
|---|---|---|---|---|
| local | Vite dev | runserver | docker postgres | development |
| preview | Vercel preview | Render PR service (optional) | Supabase branch | per-PR review |
| staging | Vercel | Render | separate Supabase project | migration rehearsal |
| production | Vercel | Render | dedicated Supabase project | live |

Separate Supabase projects, separate secrets, separate GitHub App installations. Nothing is
shared between staging and production except code.

## Pipeline
```yaml
# .github/workflows/ci.yml (shape, not a copy-paste template)
jobs:
  api:
    services: { postgres: { image: postgres:16, env: {...} }, redis: {...} }
    steps: [checkout, setup-python, pip-install, ruff, mypy, manage.py check,
            makemigrations --check --dry-run, migrate, pytest --cov, bandit, pip-audit]
  web:
    steps: [checkout, setup-node, npm ci, typecheck, vitest run, build, playwright]
  runner:
    steps: [checkout, setup-python, pip-install -e ., pytest]
```
`makemigrations --check --dry-run` in CI is mandatory: a model change without a migration
fails the build. Migrations run as a separate release step, never inside a web container
start command that could run 3 times concurrently.

## Render services
- `api-web`: gunicorn/uvicorn workers, `preDeployCommand: python manage.py migrate`,
  health check `/healthz` (checks DB + Redis, 2s timeout, returns 503 on failure).
- `api-worker`: `celery -A config worker -Q agents,execution,default`, concurrency tuned to
  memory, `--max-tasks-per-child=50` to bound leaks.
- `api-beat`: single instance only.
- Auto-deploy from `main` after CI passes; no deploy from a branch.

## Frontend on Vercel
- `VITE_API_BASE_URL` per environment; no secret in any `VITE_*` variable.
- SPA rewrites to `index.html`, immutable caching for hashed assets, no caching for
  `index.html`.
- Build fails if `typecheck` fails.

## Rollback
1. Revert the deploy (Render rollback / Vercel instant rollback).
2. Migrations: forward-only by default. If a bad migration shipped, ship a corrective
   migration; do not edit history. Data-destructive changes always have a documented
   rollback plan before merge.
3. Feature flags for anything risky so rollback is a flag flip, not a redeploy.

## Observability
- Structured JSON logs with `request_id`, `org_id`, `run_id`, `step_id`; secrets redacted.
- Sentry for exceptions on web/worker/frontend, with `beforeSend` scrubbing.
- Metrics that matter: run success rate, p50/p95 step latency, provider error rate per
  provider, sandbox provisioning failures, queue depth, spend per org vs cap.
- Alerts: error rate > 2% for 5 min, queue depth > 500, provider 401 spike (credential
  problem), sandbox orphan count > 0 after the reaper.

## Checklist
- [ ] CI green including migration check and both test suites.
- [ ] Health check returns real dependency status.
- [ ] New env var added to `.env.example`, Render, Vercel, and the docs table.
- [ ] Migration gated as a pre-deploy step.
- [ ] Rollback path written for anything destructive.
- [ ] No secret in a build-time variable.

# Deployment

Nothing below has been executed. There is no Render service, no Vercel project and no
Supabase project attached to this repository. This is the plan the code was written for.

## Environments

| Env | Frontend | API | Database | Purpose |
|---|---|---|---|---|
| local | Vite dev server | `runserver` | docker postgres | development |
| preview | Vercel preview | optional per-PR Render service | Supabase branch | review |
| staging | Vercel | Render | separate Supabase project | migration rehearsal |
| production | Vercel | Render | dedicated Supabase project | live |

Separate Supabase projects, separate secrets, separate GitHub App installations. Nothing is
shared between staging and production except code.

## Required configuration

Every variable below must exist in Render and Vercel before the first deploy. Full list with
descriptions in `.env.example`.

| Variable | Service | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | Render | 64 random chars, unique per environment |
| `DATABASE_URL` | Render | pooled connection string |
| `DATABASE_DIRECT_URL` | Render pre-deploy | direct connection, migrations only |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | Render + Vercel | anon key is public |
| `SUPABASE_SERVICE_ROLE_KEY` | Render only | never a `VITE_*` variable |
| `SUPABASE_JWT_SECRET` or `SUPABASE_JWKS_URL` | Render | one of the two |
| `BYOK_ENCRYPTION_KEYS`, `BYOK_ACTIVE_KEY_ID` | Render | losing this makes credentials unrecoverable |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Render | three logical DBs |
| `GITHUB_APP_*` | Render | private key mounted as a file, not a variable |
| `DAYTONA_API_KEY`, `DAYTONA_ENABLED` | Render | leave disabled until verified |
| `VITE_API_BASE_URL`, `VITE_WS_BASE_URL`, `VITE_SUPABASE_*` | Vercel | public values only |

## Render services

```
api-web     gunicorn config.wsgi --workers 3 --timeout 60
            preDeployCommand: python manage.py migrate    (single execution)
            healthCheckPath: /healthz

api-worker  celery -A config worker -Q agents,execution,default
            --concurrency 4 --max-tasks-per-child 50

api-beat    celery -A config beat        (exactly one instance)
```

`/healthz` queries the database and pings Redis, and returns 503 when the database is down.

## Frontend on Vercel

- Build command `npm run build` (runs `tsc -b` first, so a type error fails the deploy).
- SPA rewrite to `index.html`; immutable caching for hashed assets, no cache for `index.html`.
- No secret in any `VITE_*` variable.

## First deploy sequence

```bash
# 1. Supabase: create project, copy URL + keys, run nothing else by hand.
# 2. Generate the encryption key once and store it in the password manager.
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 3. Render: create the three services, set env vars, let the pre-deploy migrate run.
# 4. Vercel: import the repo with apps/web as the root directory.
# 5. Verify
curl -s https://api.example.com/healthz
```

## Rollback

1. Roll back the service (Render rollback / Vercel instant rollback).
2. Migrations are forward-only. A bad migration gets a corrective migration; history is never
   edited. Anything destructive must have a written rollback note in the PR before merge.
3. Feature flags for risky behaviour so rollback is a flag flip.

## Alerts to configure

Run failure rate over 2% for 5 minutes; queue depth over 500; a provider 401 spike (credential
problem, not an outage); sandbox orphans remaining after the reaper; spend per organisation
approaching its cap.

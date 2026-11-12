# Deploy on Fly.io + Neon

Four small services on Fly, Postgres on Neon. Total: **four Fly apps** (`veritas-api`,
`veritas-worker`, `veritas-redis`, `veritas-web`) and **one Neon project**.

```
browser ──► veritas-web   (nginx, static SPA)
              │
              ▼
           veritas-api    (daphne, ASGI: HTTP + WebSockets)
              ├──► Neon Postgres  (DATABASE_URL, sslmode=require)
              ├──► veritas-redis  (private network only: broker + channel layer)
              └──► veritas-worker (celery, same image, no public IP)
```

Read the whole page before starting. Steps 2 and 5 are the two that are easy to skip
and expensive to get wrong.

---

## 0. Prerequisites

- `flyctl` installed and `fly auth login`
- A Neon account
- A payment card on the Fly account (Fly has no permanent free tier; see §8)

```bash
brew install flyctl        # or: curl -L https://fly.io/install.sh | sh
fly auth signup            # or: fly auth login
```

---

## 1. Postgres on Neon

1. Create a project. Choose the region closest to your Fly region (`jnb` → AWS
   `af-south-1` if offered, else `eu-central-1`).
2. From **Connection Details**, copy **two** strings, both with `sslmode=require`:

   - **Direct** (no `-pooler` in the host) → used for migrations and as the app
     connection. Prefer direct: the Row-Level Security layer sets a
     transaction-scoped caller identity with `set_config(..., is_local => true)`,
     and direct connections keep that unambiguous.
   - **Pooled** (`-pooler` host) → optional, only if you later need many more
     connections.

3. Replace the user in both strings once step 2 below creates the restricted role.

Neon's free plan suspends an idle database after a few minutes. The first request
after that is slow (a second or two) while it wakes. That is normal, not an outage.

---

## 2. Create the unprivileged database role (do not skip)

The app must **not** connect as the database owner. An owner or superuser bypasses
Row-Level Security, which is what keeps one customer's data invisible to another.
The API, the worker and the security rules all assume the restricted role.

```bash
cd apps/api
export MIGRATE_DATABASE_URL='<Neon DIRECT url with the OWNER user>'
export APP_DB_PASSWORD='<a long random password you choose and save>'
python deploy/bootstrap_db_roles.py
```

It prints `OK: role veritas_app ready (not superuser, no BYPASSRLS)`. Keep the
password: it goes into `DATABASE_URL` in step 5.

Expected pitfalls:
- The owner user on Neon is `neondb_owner`, not `postgres`.
- The role is created in the database you point at. Confirm `veritas` (or your
  chosen database name) is in the URL path.

---

## 3. Redis (private, no public IP)

```bash
fly apps create veritas-redis
fly volumes create redis_data --app veritas-redis --region jnb --size 1
fly deploy --config fly.redis.toml
```

Because `fly.redis.toml` has no `[http_service]`, Fly gives this app no public IP.
It is reachable only at `veritas-redis.internal:6379` from your other apps.

---

## 4. The API

```bash
fly apps create veritas-api
fly deploy --config fly.api.toml
```

Do not expect a healthy first boot yet: without secrets it cannot start. That is
step 5. The first deploy still needs to happen so the app exists for `fly secrets`.

---

## 5. Secrets

Every value below is required unless marked optional. Set them on **both** the API
and the worker (the worker connects to the same database and broker).

Generate the Django key and the credential-encryption key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"          # DJANGO_SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # BYOK key
```

Back up the BYOK key. If it is lost, every AI provider key users have stored becomes
permanently unreadable.

```bash
COMMON="
DJANGO_SECRET_KEY=<from above>
DJANGO_ALLOWED_HOSTS=veritas-api.fly.dev
CORS_ALLOWED_ORIGINS=https://veritas-web.fly.dev
DATABASE_URL=postgresql://veritas_app:<password>@<direct-host>/<db>?sslmode=require
REDIS_URL=redis://veritas-redis.internal:6379/0
CELERY_BROKER_URL=redis://veritas-redis.internal:6379/1
CELERY_RESULT_BACKEND=redis://veritas-redis.internal:6379/2
BYOK_ENCRYPTION_KEYS=k1:<fernet-key>
BYOK_ACTIVE_KEY_ID=k1
LOCAL_RUNNER_WS_URL=wss://veritas-api.fly.dev
"

# Repeat for both apps:
echo "$COMMON" | fly secrets import --app veritas-api
echo "$COMMON" | fly secrets import --app veritas-worker
```

Then the login values (`SUPABASE_URL`, `SUPABASE_ANON_KEY`,
`SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `SUPABASE_JWKS_URL`), or the
equivalent for whichever login provider you switch to.

Optional, only if you want the GitHub integration: `GITHUB_APP_ID`,
`GITHUB_APP_SLUG`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_WEBHOOK_SECRET`. Without
them the connect-a-repository button reports "not configured" and nothing breaks.

---

## 6. Deploy API, worker, web

Order matters: the API's release command runs migrations, so it must go first.

```bash
fly deploy --config fly.api.toml        # runs migrate + collectstatic on release
fly apps create veritas-worker
fly deploy --config fly.worker.toml
```

The web app needs the deployed API URL compiled into the bundle. Edit the
`[build.args]` block in `fly.web.toml` if your app names differ, then:

```bash
fly apps create veritas-web
fly deploy --config fly.web.toml
```

`VITE_*` values are baked in at **build** time. Changing them means redeploying the
web app, not restarting it.

---

## 7. Verify

```bash
curl -s https://veritas-api.fly.dev/healthz
```

- Expected: `{"status": "ok", "checks": {"database": "ok", "redis": "ok"}}`
- `redis: error:*` → the API cannot reach `veritas-redis.internal`; check both apps
  are in the same region and the Redis app is running.
- `database: error:*` → usually a bad password, a missing `sslmode=require`, or
  step 2 not done against the same database.

Then in the browser at `https://veritas-web.fly.dev`:
1. Sign in — this is the step that proves the login provider works.
2. Create a workspace (this exercises the first-login path and the new RLS policy).
3. Create a project, then rename and archive it.
4. Refresh on a deep link (`/projects/...`) — a 404 here means the nginx fallback
   is missing.

Check the worker is actually consuming jobs:

```bash
fly logs --app veritas-worker
```

---

## 8. Cost

Fly has no permanent free tier. Community docs describe an allowance of roughly
three 256MB shared-CPU machines and 3GB of volume; a payment card is still required.
This guide asks for 512MB on the API (daphne plus Django is tight at 256MB) and
256MB each for worker, Redis and web, plus a 1GB volume. Expect roughly **$5–15 a
month** depending on traffic and region — that is an estimate, not a quote. Check
Fly's live pricing before committing.

Ways to trim it: run the worker at `--concurrency=1`, drop the web app and host the
SPA on a free static host (it is just files; point `VITE_API_BASE_URL` at the API),
or shrink the Redis volume.

---

## 9. Known gaps

- **Login.** The code only speaks Supabase. If Supabase is unreachable for you,
  swap the provider first (§ in `docs/` or ask); everything else here is unaffected.
- **The images have not been built here.** There is no Docker daemon in the
  environment this was written in, so expect to fix something small on the first
  `fly deploy`. The paths, ports, entry points and dependencies were checked
  against the repo, and the Vite build-argument mechanism was verified by building
  the SPA and inspecting the compiled bundle.
- **Most screens are unbuilt.** See `PROJECT_STATUS.md` before inviting users.
- **No agent has run against a real AI provider yet.** The Studio run/build
  controls are disabled, so the worker's queue will stay empty until that lands.

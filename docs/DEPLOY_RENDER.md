# Deploying Veritas Bot on Render

`render.yaml` (repo root) validates against Render's official blueprint schema. It has **not** been applied to a
Render account, because none is connected here. Expect to adjust names (service URLs are derived from the names).

## What you need before starting
1. A GitHub repository containing this project (push it first).
2. A **Supabase project** (free tier is fine). Nobody can sign in without one.
   - Project Settings > API: copy **Project URL**, **anon key**, **service_role key**.
   - Project Settings > API > JWT Settings: copy the **JWT secret**.
   - JWKS URL is `<Project URL>/auth/v1/.well-known/jwks.json`.
3. Two generated secrets (run locally):
   - `python3 -c "import secrets;print(secrets.token_urlsafe(32))"` -> the app DB password (24+ chars, letters/digits/`_`/`-` only).
   - `python3 -c "from cryptography.fernet import Fernet;print('k1:'+Fernet.generate_key().decode())"` -> `BYOK_ENCRYPTION_KEYS`.
     **Back this up.** Losing it makes every stored provider API key unrecoverable.

## Steps
1. Render dashboard > **New > Blueprint** > select the repo. Render reads `render.yaml`.
2. When prompted for the `sync: false` values, enter the Supabase values and `BYOK_ENCRYPTION_KEYS`.
   Leave `DATABASE_URL` blank for now (step 4).
3. Let the first deploy run. The `pre-deploy` step migrates using the **owner** URL (`MIGRATE_DATABASE_URL`).
   The API will not be fully usable yet: it has no runtime database URL.
4. **Create the unprivileged database role (required for tenant isolation).** In the `veritas-api` service open
   **Shell** and run:
   ```
   APP_DB_PASSWORD='<the password you generated>' python deploy/bootstrap_db_roles.py
   ```
   It must print `OK: role veritas_app ready (not superuser, no BYPASSRLS)`. Then set `DATABASE_URL` on **both**
   `veritas-api` and `veritas-worker` to:
   `postgresql://veritas_app:<password>@<internal host>:5432/veritas`
   (the host and database name are the same as in `MIGRATE_DATABASE_URL`; only user and password change).
5. Redeploy both services. Check `https://<api>/healthz` returns `database: ok`.
6. In Supabase > Authentication > URL Configuration, set **Site URL** to the `veritas-web` URL and add it to
   the redirect allow-list. Without this, email links (verification, password reset) point to the wrong place.

## Why step 4 matters
Row-level security is the second wall behind the application's own tenant checks. A database **owner or superuser
bypasses it**, so if the app ran on the owner URL, one forgotten filter would leak data across organizations
and nothing would warn you. The bootstrap script creates a role that cannot bypass RLS and refuses to
report success if it can.

## Re-running after new migrations
New tables created by later migrations inherit grants through default privileges. Re-run the bootstrap
script anyway after a deploy that adds tables; it is idempotent and also reports any table that lacks RLS.

## Known limits (be aware before testing)
- Cloud sandboxes (Daytona) and GitHub App installation are **not connected**; those screens show an honest
  "not connected" state. Local runners work once paired.
- Email is not configured. Team invitations show a copyable link instead of sending mail. Supabase sends
  its own auth emails.
- Render plan IDs in `render.yaml` are schema-valid, but confirm current pricing in the dashboard.
- WebSockets (runner relay, session streams) run on the ASGI web service via daphne.
- The free Supabase tier and the Render `starter` plans are for testing, not production load.

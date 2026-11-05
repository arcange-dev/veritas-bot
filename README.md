# Veritas Bot — AI Developer Studio

Your AI engineering team. One intelligent workspace.

A multi-tenant platform where users bring their own AI credentials (BYOK), connect
repositories, and delegate the software development lifecycle to specialist agents that
execute code in a secure local runner or an isolated cloud sandbox.

## Repository layout

```
apps/web            React 18 + TypeScript + Vite SPA (Developer Studio, settings, dashboards)
apps/api            Django 5 + DRF (auth, tenancy, BYOK, orchestration, tools, execution)
apps/local-runner   Standalone Python agent installed on a user machine (outbound only)
packages/contracts  Shared API contract types, generated from the Pydantic models
packages/shared     Framework-free helpers used by web and runner
infrastructure      Docker, GitHub Actions   (Render blueprint: render.yaml at the repo root)
docs                Architecture, API, security, deployment
.claude             Engineering environment: 15 skills, 11 subagents, rules, hooks
```

## Run it locally

```bash
cp .env.example .env                     # fill in DATABASE_URL, SUPABASE_*, BYOK_ENCRYPTION_KEYS

# Backend
cd apps/api
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# Frontend (second terminal)
cd apps/web
npm ci
npm run dev            # http://localhost:5173

# Local runner (third terminal, on the machine that will execute code)
cd apps/local-runner
pip install -e ".[dev]"
superagent-runner pair --api-url http://localhost:8000
superagent-runner allow ~/code/my-project
superagent-runner run
```

Generate the credential encryption key once:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Verify

```bash
cd apps/api          && pytest -q                                   # 290 on PostgreSQL, 240 on SQLite (+50 skipped: Postgres-only)
cd apps/web          && npm run typecheck && npm run test && npm run build
cd apps/local-runner && pytest -q
python tooling/validate_claude_env.py                               # skills + subagents + hooks
```

## Deploying

`render.yaml` is a Render blueprint that passes Render's official schema. It has **not** been applied to a
Render account. Read [`docs/DEPLOY_RENDER.md`](docs/DEPLOY_RENDER.md) first: it has a required step that creates
an unprivileged database role, without which row-level security would be bypassed.

## Status: what works and what does not

Read `PROJECT_STATUS.md` for the detailed, evidence-based version. In short:

**Built and tested**
- Multi-tenant backend: Supabase JWT auth, organizations and roles, row-level security enforced twice
  (ORM scoping plus PostgreSQL policies, tested as an unprivileged role).
- BYOK provider credentials (encrypted), run orchestration, approvals, spend caps with exact decimal accounting.
- GitHub webhook receiver (HMAC verified, replay-protected), deployments read API, notifications, audit log,
  dashboard summary, project archive.
- Frontend: login, dashboard shell, providers, Studio with the agent panel and plan/approvals panel.
- Veritas Bot branding from the Figma file: logo, favicons, design tokens, fonts, optional glass styling.

**Not built / not verified**
- Most of the 47 Figma screens. Only login, dashboard, providers and Studio exist. Public site, onboarding,
  projects pages, agents, team management, usage dashboard, admin and others are not written yet.
- No agent has run against a real AI provider; the orchestration graph has only run with a scripted model.
- No command-execution endpoint, so Studio Build/Run/Test/Preview are disabled. Daytona cloud sandboxes
  and the GitHub App installation flow are not connected.
- Nothing has been deployed, and the UI has not been loaded in a browser against the live API.
- The internal package, command and environment names still say `superagent` (for example
  `superagent-runner`); only user-visible text was renamed.

## License

Apache License 2.0 (see `LICENSE`).

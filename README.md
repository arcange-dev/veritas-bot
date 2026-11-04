# SuperAgent — AI Developer Studio

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
infrastructure      Docker, Render, GitHub Actions
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
cd apps/api          && pytest -q                                   # 52 tests
cd apps/web          && npm run typecheck && npm run test && npm run build
cd apps/local-runner && pytest -q                                   # 51 tests
python tooling/validate_claude_env.py                               # skills + subagents + hooks
```

## Status

Read `PROJECT_STATUS.md` before trusting any part of this repository. It separates what has
been executed and observed from what has only been written.

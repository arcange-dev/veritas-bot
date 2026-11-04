# Veritas Bot: parallel build contract

Read this fully before writing code. Every worker follows it so the pieces merge cleanly.

## Product and brand
- Product name is **Veritas Bot** (never "SuperAgent" in anything a user sees).
- Design source of truth: Figma file `TbcwVUFr3hprG6RKdBZS4i`, already exported:
  - Screens (PNG): `/app/conversations/6ae45d427996c393b5b08033/figma_assets/pages/`
  - Index: `.../figma_assets/manifest.json` (page, name, id, file)
  - Exact text/labels per page: `.../figma_assets/spec/page_NN.txt`
  - You CANNOT view images. Use the `spec/page_NN.txt` text (exact copy, labels, states) and the
    design rules below. Do not invent copy that contradicts the spec.
- Rules from the Figma: flat surfaces, 1px hairline borders, 6px radius controls, Inter + JetBrains
  Mono, dense engineering layout, no decorative glow. **The owner then asked for glass on top**, so
  use the existing opt-in classes (`glass`, `glass-strong`, `btn-liquid`, `btn-glass`,
  `glass-backdrop`) for primary surfaces and primary buttons. Do not write new blur/gradient CSS.
- Tokens are in `apps/web/src/styles/tokens.css`. Use Tailwind token classes already defined in
  `apps/web/src/styles/app.css` (`bg-base`, `bg-raised`, `bg-overlay`, `border-subtle`,
  `text-primary`, `text-secondary`, `text-muted`, `text-ok`, `text-warn`, `text-danger`, accent).
  Never hardcode hex colours.
- Logo: `import { Logo, LogoMark } from "@/components/brand/Logo"`.
- Reuse `Panel`, `EmptyState`, `StatusChip` from `@/components/ui/Panel`.

## Hard rules (do not break)
1. **Only touch files inside your assigned directories.** Do NOT edit: `apps/web/src/App.tsx`,
   `apps/api/config/urls.py`, `apps/api/config/settings/*`, `apps/web/src/lib/api.ts`,
   `apps/web/src/styles/*`, `apps/web/package.json`, any other worker's directory, or any existing
   migration. If you need a shared change, describe it in your final report under "SHARED CHANGES
   NEEDED" and the coordinator will apply it.
2. Do not run `makemigrations` into shared apps unless your brief says you own that app. If you add
   a model, put it in your own new Django app and generate only that app's migration.
3. **Backend tenancy is mandatory.** Every org-scoped viewset must:
   - inherit `core.rls.TenantBoundMixin` FIRST, then DRF mixins/viewsets,
   - use `permission_classes = [IsOrgMember]` for reads and `IsOrgWriter` for writes
     (`from core.permissions import ...`), admin-only actions use `IsOrgAdmin`,
   - scope querysets with `core.tenancy.for_org(qs, request.org)`,
   - NEVER access `obj.organization` / `run.project` style relations lazily outside a request; use
     `*_id` fields (Row-Level Security hides unbound rows).
   `tests/test_tenant_routes.py` will FAIL the build if an org-scoped route lacks the mixin.
4. Secrets (API keys, tokens) are never returned by any serializer and never logged.
5. Errors: raise `core.errors.DomainError` subclasses or DRF exceptions. Never return stack traces.
6. Money is a decimal STRING on the wire. Never a JS number.
7. Frontend data layer: wire schemas in Zod, calls via `apiFetch` from `@/lib/api`, server state via
   TanStack Query, pure display logic in its own file with unit tests.
8. Every screen needs: loading state, empty state, error state, and keyboard/aria basics. The Figma
   "Associated State Sheet" frames list the exact states and copy; follow them.
9. **Do not fake it.** No hardcoded data presented as real, no buttons that do nothing. If a feature
   needs something that does not exist (a real GitHub App, Daytona, Supabase), build the UI and API
   against the real contract, show an honest "not connected" state, and list it in your report.

## Verify before you report (mandatory)
Backend (run from `apps/api`, `export DJANGO_SETTINGS_MODULE=config.settings.test`):
- `python3 -m pytest -p no:warnings -q` must pass (SQLite default). Your new tests are required:
  happy path, validation errors, **cross-tenant access returns 404**, viewer role cannot write.
- `python3 manage.py check` clean; `python3 manage.py makemigrations --check --dry-run` shows no
  drift for your app.
Frontend (from `apps/web`):
- `npx tsc --noEmit` clean, `npx vitest run` passes, `npx vite build` succeeds.
- Write tests for your data layer, display logic and the main interactions (React Testing Library;
  `@testing-library/user-event` is installed; fake only `fetch`).
Report only what you actually ran, with the real counts. If something fails, say so.

## Final report format
1. Files created/changed (paths).
2. Backend: endpoints (method + path), new models/migrations.
3. Frontend: routes (path -> component), which Figma frames each covers.
4. Test counts (backend + frontend) and commands run.
5. SHARED CHANGES NEEDED: exact lines for `urls.py` router registrations, `App.tsx` routes, nav items.
6. Honest gaps: anything not built or not verified.

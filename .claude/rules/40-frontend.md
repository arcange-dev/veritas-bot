# Rule: frontend

- TypeScript strict. No `any` in `apps/web/src` without a comment justifying it.
- Server state lives in TanStack Query; UI state in Zustand. Do not duplicate
  server data into a Zustand store.
- Every fetch goes through `src/lib/api.ts`, which attaches the Supabase JWT and
  normalises errors. No ad-hoc `fetch` in components.
- Every interactive control is keyboard reachable and has a visible focus ring.
- No API key, token, or secret is ever read from `import.meta.env` except
  `VITE_API_BASE_URL` / `VITE_WS_BASE_URL`.
- Loading, empty, and error states are required for every data view.
- The Developer Studio panels stack vertically below 1024px.

# @superagent/contracts

Single source of truth for API shapes between `apps/api` and `apps/web`.

Today the wire schemas live in two places that must agree:
- Pydantic models in `apps/api/tools/schemas.py` (tool arguments)
- Zod schemas in `apps/web/src/lib/api.ts` (HTTP responses)

Plan: generate JSON Schema from the DRF serializers via `drf-spectacular`, commit it here, and
derive both the TypeScript types and the Zod schemas from it in CI so drift fails the build.
Until that exists, a serializer change without a matching Zod change is caught only by
`apiFetch` rejecting an unexpected shape at runtime, which is a bug report rather than a test.

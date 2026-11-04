# Testing report

Run 2026-10-30 in the build sandbox. Every number below is copied from command
output, not estimated.

## Backend: 69 passed

```
cd apps/api && DJANGO_SETTINGS_MODULE=config.settings.test pytest
69 passed in 0.92s
```

Coverage by intent:

- `test_crypto` - encrypt/decrypt round trip, tamper rejection, key rotation,
  no plaintext in `repr`.
- `test_tenancy` - cross-tenant reads 404 for projects and credentials; scoped
  lists exclude other organisations.
- `test_tool_registry` - unlisted tool denied, destructive tool requires an
  approval row, path escape refused, denials audited.
- `test_routing` - plan validation (cycles, duplicate ids, unknown deps),
  parallel batches never overlap write scopes, next-action selection.
- `test_costs` - Decimal exactness, cap enforcement raises before dispatch.
- `test_runner_tokens` - device binding, audience, TTL, revocation.
- `test_api_credentials` - create encrypts, response never contains the key,
  `last4` only, cross-tenant 404.
- `test_pairing` (new) - mint, claim, single use, expiry, fingerprint length,
  non-admin refused, tenant scoping, revocation kills live tokens.
- `test_runner_relay` (new) - real consumer over `WebsocketCommunicator`:
  round trip, refusal propagation, offline fast-fail, disconnect wake-up,
  output → session group, adapter frame mapping, base64 file wire format.

## Frontend: 7 passed, build green

```
tsc --noEmit           -> 0 errors
vitest run             -> 7 passed (2 files)
vite build             -> 1693 modules transformed
```

`streamBuffer` tests caught a real defect: the first frame of any stream was
flagged as a gap because the cursor starts at -1. Fixed, not worked around.

## Local runner: 51 passed

Path authorisation (traversal, absolute escape, symlink), command policy
matrix (allow/ask/deny), process timeout kill and group teardown, output caps,
environment scrubbing of the runner's own token.

## Not covered

No Playwright/E2E (nothing deployed), no live Supabase JWKS, no live provider
probe, no Daytona, no GitHub, no CI execution. These are listed as gaps rather
than implied by a green suite.


## Defects found by execution, 2026-11-01

| # | Defect | Found by | Impact if shipped |
|---|---|---|---|
| 1 | Empty plan counted as complete (`all([])` is True) | first real graph run | run "succeeded" having done nothing |
| 2 | A re-plan reset DONE tasks to pending | graph trace | finished work repeated, spend repeated |
| 3 | Exhausted budget reported as success | graph trace | false success |
| 4 | Parallel steps collided on `(run, sequence)` | lifecycle test | task silently failed |
| 5 | **Lost cost updates under concurrency** | `test_cost_concurrency.py` | **run recorded $0.012 of $0.072 real spend (83% lost); spend caps could be exceeded about 6x** |
| 6 | Logged-in `Profile` had no `is_authenticated` | API test | DRF would reject every real Supabase user |
| 7 | Anonymous callers got 404 instead of 401 | API test | expired sessions looked like missing pages |
| 8 | Membership check ran before any RLS identity existed | first test as `sa_app` | every user 404 under a real DB role |
| 9 | Whole-run transaction deadlocked parallel tasks | worker test + pg_stat_activity | worker hang |

**Defect 5 predates this session and was present in release 0.2.0.** Mutation check: restoring the
read-add-write update makes the test fail on both SQLite and PostgreSQL.

Counts at the end of this session: **224 passed on real PostgreSQL 16**, 177 passed + 47 skipped on SQLite.
Concurrency and RLS suites repeated 8 times on PostgreSQL: 8/8 pass.


## Frontend verification, 2026-11-03

53 tests across schemas, polling, display logic and component behaviour (React Testing Library, real Zod schemas,
real TanStack Query; only `fetch` and the auth token are faked).

Mutation checks, each restored byte for byte afterwards:
- Showing only the approval summary instead of the exact payload -> fails the payload test.
- Making Reject send `approve: true` -> fails the reject test.
- Rounding sub-cent spend to `$0.00` -> fails two tests.

**Limit of this evidence:** these are component tests with a mocked network. They prove the components call the
right endpoints with the right bodies and render the right states. They do not prove the page works in a browser
against the running API.

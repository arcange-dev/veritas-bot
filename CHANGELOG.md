# Changelog

## 0.2.0 - 2026-10-30

### Added
- Runner relay: `RunnerRelay` with per-request reply channels, presence with a
  45s TTL, offline fast-fail, and timeout handling (`execution/relay.py`).
- `RunnerConsumer`: joins the device group, records `hello` metadata, maps
  request ids to server-created reply channels, publishes output to
  `session.<id>`, and wakes in-flight callers on disconnect.
- `TerminalConsumer`: browser terminal with tenant authorisation against session
  ownership, not just a valid token.
- Device pairing: mint/claim/revoke with hashed, single-use, attempt-limited,
  10-minute codes and constant failure messages.
- `LocalRunnerBackend` fully implemented over the relay: exec, fs read/write/list
  (base64), `stream_logs` via the session group, idempotent `stop`.
- Frontend: `useSessionStream` + `streamBuffer` (dedupe, gap detection) wired
  into the studio terminal via `?session=<id>`.
- `docs/api/RUNNER_PROTOCOL.md`.
- 17 backend tests, 4 frontend tests.

### Fixed
- Stream buffer flagged the first frame as a gap (cursor sentinel off by one).
- `useEffect` missing from the Studio React import.

### Changed
- Test settings use `InMemoryChannelLayer`; `daphne` added to requirements.

## 0.1.0 - 2026-10-30

Initial foundation: monorepo, Claude Code environment (15 skills, 11 subagents,
hooks), Django backend with 23 models, BYOK with MultiFernet, tool registry,
execution adapter interface, Vite/React studio shell, local runner package.

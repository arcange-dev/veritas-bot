# Runner wire protocol (v1)

The runner opens one outbound WebSocket to `/ws/runner/?device=<uuid>&token=<jwt>`.
The platform never dials a device, never exposes an inbound port, and never tells
the runner where to publish: the consumer owns all routing.

## Handshake

1. Runner POSTs a pairing code to `/api/v1/runners/claim/` (the only
   unauthenticated write in the API).
2. Platform returns `device_id` plus a 15-minute HS256 token bound to that device
   (`sub = device_id`, `aud = runner`).
3. Runner connects and sends `hello` with version, os, arch and its approved
   workspace roots. The platform records them and marks the device online.

Presence is a 45-second cache key refreshed by `pong`. A hard-killed runner
disappears on its own.

## Frames

| type | direction | purpose |
|---|---|---|
| `hello` | runner → server | identity + approved roots |
| `exec` | server → runner | `argv`, `cwd`, `timeout_seconds`, `approval_id` |
| `fs.read` / `fs.write` / `fs.list` | server → runner | file operations, content base64 |
| `stop` | server → runner | kill a session's process group |
| `output` | runner → server | live stdout/stderr, published to `session.<id>` |
| `result` | runner → server | terminal frame for one request `id` |
| `ping` / `pong` | either | heartbeat / presence refresh |

Every frame carries `v` and `id`. Request and response share the `id`; the
consumer maps it to a server-created reply channel that the runner never sees.

## Who enforces what

The runner re-applies its own command policy on every `exec`, including DENY for
privilege escalation, pipe-to-shell, force pushes, and credential directories.
An `approval_id` from the platform satisfies an ASK-level command *only*; it can
never unlock a DENY. This is deliberate: a compromised platform cannot turn a
user's laptop into a botnet.

## Failure modes

| condition | platform behaviour |
|---|---|
| device offline | `DeviceOffline` immediately, no timeout wait |
| no `result` in time | `DeviceTimeout` |
| `result.ok = false` | `RunnerRefused` with the runner's reason |
| socket drops mid-request | in-flight callers are woken with `runner disconnected` |
| >512 in-flight frames | new callers rejected, not queued silently |

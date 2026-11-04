---
name: secure-local-runner
description: The Python local runner that executes code on a user's own machine - outbound-only WebSocket, device pairing codes, scoped short-lived tokens, workspace path allowlisting, command policy, process supervision, and terminal streaming. Use when working in apps/local-runner or its server-side counterpart.
---

# Secure Local Runner

## When to use
Any change to device pairing, the runner WebSocket protocol, filesystem access, process
control, or the server endpoints that drive them.

## Threat model
The runner has the user's real filesystem and real credentials. Assume:
- The platform could be compromised and send malicious commands.
- Repo content could contain prompt-injected instructions.
- The network between runner and server is untrusted.

Therefore: outbound-only connection, no inbound listening socket, explicit workspace
allowlist chosen by the user in a native dialog, short-lived scoped tokens, and a local
deny-list that the server cannot override.

## Pairing flow
1. User clicks "Connect device" in the web app -> `POST /api/v1/runners/pairing/` returns a
   6-digit code and `expires_at` (10 min), plus a single-use `pairing_id`.
2. Runner prompts for the code, calls `POST /api/v1/runners/pairing/claim/` with code +
   device fingerprint (hostname hash, OS, arch) -> receives a `device_id` and a
   device-bound refresh token.
3. Runner opens `wss://api/ws/runner/?device=<id>` with `Authorization: Bearer <access>`
   where access tokens are 15-minute, audience `runner`, and scoped to that device.
4. Server records `LocalRunnerDevice(status, last_seen, runner_version, os, arch)`.

```python
# apps/api/execution/local/tokens.py
def mint_runner_token(device: LocalRunnerDevice) -> str:
    return jwt.encode({
        "sub": str(device.id),
        "aud": "runner",
        "org": str(device.organization_id),
        "scope": ["exec", "fs", "git", "stream"],
        "exp": now() + timedelta(minutes=15),
        "jti": uuid4().hex,
    }, settings.RUNNER_JWT_KEY, algorithm="EdDSA")
```
Tokens are device-bound and revoked on unpair, on 3 auth failures, or on a version below
the minimum supported.

## Path authorisation
```python
class Workspace:
    def resolve(self, candidate: str) -> Path:
        root = Path(self.root).resolve()
        target = (root / candidate).resolve() if not os.path.isabs(candidate) \
                 else Path(candidate).resolve()
        if target != root and root not in target.parents:
            raise PathOutsideWorkspace(candidate)      # reject before any I/O
        if target.is_symlink() or any(p.is_symlink() for p in target.parents):
            raise SymlinkRefused(candidate)
        return target
```
Workspace roots are registered locally by the user and stored in the runner's own config
file. The server cannot add a root; it can only read the list.

## Command policy (enforced locally)
- Deny: privilege escalation, disk formatting, recursive deletion outside the workspace,
  package managers run with elevated rights, piping remote content into a shell, writes to
  `~/.ssh`, `~/.aws`, `~/.config/gh`, and browser profile paths.
- Require approval: installs, long-running servers, git operations that rewrite history.
- Always: timeout (default 120s, max from env), output cap 200 KB, `cwd` inside workspace,
  scrub env down to an allowlist (`PATH`, `HOME`, `LANG`, project-provided vars), never
  inherit the runner's own tokens into the child process.

## Process supervision
Track every spawned process in a registry keyed by `session_id`. On disconnect, keep
servers alive but stream nothing; on `stop`, terminate the process group, wait 5s, then
force. On runner shutdown, terminate all children. Never leave an orphan dev server.

## Terminal streaming
Frames: `{type: "stdout"|"stderr"|"exit"|"pong", session, seq, data}`. `seq` is monotonic so
the client can detect gaps and request a replay from the ring buffer (last 2 MB per
session, in memory only). Heartbeat every 20s; server drops the socket after 45s of
silence and the runner reconnects with jittered backoff.

## Update path
Runner checks a signed manifest on start, reports its version on connect, and the server
refuses devices below `MIN_RUNNER_VERSION`. Auto-update is opt-in; the default shows an
instruction with the exact command for the user's OS.

## Checklist
- [ ] No inbound port opened by the runner.
- [ ] Path resolution rejects `..`, absolute escapes, and symlinks.
- [ ] Token audience `runner`, <= 15 min, revocable.
- [ ] Child env scrubbed; runner tokens never inherited.
- [ ] Timeout + output cap + process-group cleanup tested.
- [ ] Pairing code single-use, expiring, rate limited (5 attempts/hour/device).

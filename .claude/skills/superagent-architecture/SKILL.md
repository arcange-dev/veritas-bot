---
name: superagent-architecture
description: System-level design rules for the SuperAgent platform - bounded contexts, service boundaries, data flow between web, api, local-runner and cloud sandboxes, and how to decide where new code belongs. Use when adding a service, a cross-cutting concern, a new bounded context, or when a change would cross module boundaries.
---

# SuperAgent Architecture

## When to use
Adding a backend module, a new execution provider, a background job, or any change that
touches more than one app in the monorepo. Also when reviewing whether a proposed
feature belongs in `apps/api`, `apps/web`, `apps/local-runner` or a new service.

## Bounded contexts

| Context | Owns | Must not |
|---|---|---|
| `identity` | Profiles, orgs, memberships, invitations, Supabase JWT verification | Know about projects or AI |
| `providers` (BYOK) | Credential storage/encryption, model catalogue, capability registry, validation | Stream chat or own conversations |
| `projects` | Projects, repositories, files metadata, GitHub links | Execute code |
| `orchestration` | LangGraph graphs, runs, steps, checkpoints, approvals | Touch the filesystem directly |
| `tools` | Tool registry, schemas, permission checks, dispatch, audit | Decide product permissions |
| `execution` | `ExecutionBackend` adapters (local runner, Daytona), sessions, streaming | Contain business rules |
| `billing` | Usage records, spend caps, cost estimation | Call providers |

Rules of the dependency graph: `orchestration -> tools -> execution`. `providers` is
consumed by `orchestration` for model access but never imports `orchestration`.
`identity` and `billing` are leaves. A cycle in this graph is an architectural defect.

## Where does new code go?

1. Is it about who may do something? -> `core/tenancy.py` + a permission class.
2. Is it about talking to a model provider? -> `providers/`.
3. Is it about deciding what to do next? -> `orchestration/` (agent logic, graph edges).
4. Is it about performing an action on a machine? -> `tools/` (schema + permission) and
   `execution/` (adapter method).
5. Is it about long-running side effects? -> a Celery task that calls the same service
   function the view calls. Never duplicate the logic in the task.

## Cross-cutting rules

- Every service boundary crossing goes through a Python function with typed Pydantic
  input/output, not a dict. Contracts are exported to `packages/contracts`.
- Synchronous request paths stay under ~300 ms of own work; anything model-bound or
  shell-bound is queued and streamed over WebSocket.
- State that must survive a restart lives in Postgres. Redis holds queues, presence and
  ephemeral stream buffers only.
- Idempotency: every Celery task that can be retried takes an idempotency key (usually
  `step_id`) and checks for existing side effects before acting.

## Adding a new execution provider

```python
# apps/api/execution/base.py defines the contract
class ExecutionBackend(Protocol):
    def create_session(self, spec: SessionSpec) -> SessionHandle: ...
    def exec(self, handle: SessionHandle, cmd: Command) -> CommandResult: ...
    def write_file(self, handle: SessionHandle, path: str, content: bytes) -> None: ...
    def read_file(self, handle: SessionHandle, path: str) -> bytes: ...
    def stream_logs(self, handle: SessionHandle) -> Iterator[LogChunk]: ...
    def stop(self, handle: SessionHandle) -> None: ...
```
Register it in `execution/registry.py` behind a settings flag. Do not branch on provider
name in views or graph nodes.

## Review checklist
- [ ] No new import cycle (`python -c "import config"` plus `pydeps` or `import-linter`).
- [ ] New module has an `__init__.py` exporting only its public surface.
- [ ] Contract change mirrored in `packages/contracts`.
- [ ] Long work queued, not inline.
- [ ] ADR added to `docs/DECISIONS.md` if a boundary moved.

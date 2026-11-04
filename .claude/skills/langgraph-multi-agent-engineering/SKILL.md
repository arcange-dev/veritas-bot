---
name: langgraph-multi-agent-engineering
description: Building the user-facing agent engine with LangGraph - typed graph state, supervisor routing to specialist agents, parallel fan-out with reducers, Postgres checkpointing, retries and resumability, human-in-the-loop approvals, and hard limits against runaway loops. Use when adding an agent, a node, an edge, or a run lifecycle behaviour.
---

# LangGraph Multi-Agent Engineering

## When to use
Any change to `apps/api/orchestration/graphs/**`, agent prompts, routing, or run state.

## Graph state (single source of truth)

```python
# orchestration/state.py
from typing import Annotated, Literal, TypedDict
from operator import add

def merge_plan(left: list[Task], right: list[Task]) -> list[Task]:
    by_id = {t.id: t for t in left}
    by_id.update({t.id: t for t in right})
    return list(by_id.values())

class RunState(TypedDict, total=False):
    run_id: str
    organization_id: str
    objective: str
    repository_summary: str
    plan: Annotated[list[Task], merge_plan]
    active_task_id: str | None
    messages: Annotated[list[Message], add]
    artifacts: dict[str, str]
    approvals: Annotated[list[Approval], add]
    findings: Annotated[list[Finding], add]
    budget: Budget                # tokens, usd_remaining, wall_clock_remaining
    iteration: int
    needs_human: bool
    next: str
```

Rules: state is JSON-serialisable (no ORM objects, no bytes); every list written by more
than one node has a reducer; anything large (file contents, diffs) lives in a blob store
and state carries a reference.

## Topology

```
          ┌──────────────┐
objective→│ orchestrator │──plan──┐
          └──────┬───────┘        │
                 │ route          ▼
      ┌──────────┼──────────┬─────────────┐
      ▼          ▼          ▼             ▼
  analyst   architect   engineer(s)      qa        (parallel where independent)
      └──────────┴──────────┴─────────────┘
                 ▼
            reviewer ──► orchestrator (re-plan / finish)
                 │
                 ▼ (destructive or gated action)
              approval ── interrupt ──► resume
```

- `orchestrator` owns the plan and the routing decision. It does not edit files.
- Specialists: `analyst`, `architect`, `frontend`, `backend`, `database`, `integration`,
  `qa`, `security`, `devops`. Each has one system prompt, one tool subset, one definition
  of done.
- Parallelism only for tasks whose `depends_on` are all `done` and whose `write_scope`
  sets are disjoint. Two agents may not hold the same file scope concurrently.

## Checkpointing and resume
Use `PostgresSaver` keyed by `thread_id = run_id`. Every node boundary commits state, so a
worker crash resumes at the last completed node. `interrupt()` is used only for approval
gates; on resume, re-validate that the approved action still matches the pending one
(hash the action payload into the approval row).

## Loop and cost guards
- `recursion_limit` set from config, default 60.
- `iteration` increments per orchestrator pass; over `max_iterations` (default 12) the run
  ends `needs_review` with a plan diff, not a silent stop.
- Budget is decremented by real usage records, not estimates. On exhaustion, checkpoint and
  emit `budget_exhausted`.

## Retries
Retry only transient failures (network, 429, 5xx, sandbox timeout). Never retry a
non-idempotent tool (PR creation, push) without an existence check first. Max 3 attempts
with jitter, then mark the step `failed` with a structured error and let the orchestrator
decide whether to re-plan.

## Human in the loop
Approval request rows carry: action type, a human-readable summary, the exact payload, a
payload hash, an expiry, and the requesting step. Approving sets `approved_by`,
`approved_at`; the graph resumes with the approval id and recomputes the hash before
executing. Any mismatch fails the resume.

## Testing agents without burning tokens
Fake the model with a scripted responder that returns canned tool calls, and assert on
graph transitions and state diffs. Have at least one opt-in integration test against a real
provider, gated by an env var, that runs a single cheap task.

## Checklist
- [ ] New node returns a partial state dict, never mutates input.
- [ ] New list field has a reducer.
- [ ] Failure path handled: raise a typed error and let the router decide.
- [ ] Step/tool rows written for observability.
- [ ] Graph test asserts the happy path and one failure path.

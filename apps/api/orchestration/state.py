"""Typed graph state. JSON-serialisable only: no ORM objects, no bytes.

Large artefacts (file contents, diffs) live in object storage; state carries a
reference. Every list mutated by more than one node has a reducer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from operator import add
from typing import Annotated, Any, TypedDict


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class Task:
    id: str
    title: str
    agent: str
    state: TaskState = TaskState.PENDING
    depends_on: list[str] = field(default_factory=list)
    write_scope: list[str] = field(default_factory=list)
    result_ref: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "agent": self.agent,
            "state": self.state.value, "depends_on": self.depends_on,
            "write_scope": self.write_scope, "result_ref": self.result_ref,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Task":
        return cls(
            id=raw["id"], title=raw.get("title", ""), agent=raw.get("agent", ""),
            state=TaskState(raw.get("state", "pending")),
            depends_on=list(raw.get("depends_on", [])),
            write_scope=list(raw.get("write_scope", [])),
            result_ref=raw.get("result_ref", ""),
        )


@dataclass
class Budget:
    tokens_remaining: int = 200_000
    usd_remaining: Decimal = Decimal("5.00")
    wall_clock_seconds: int = 3_600

    def to_dict(self) -> dict:
        return {
            "tokens_remaining": self.tokens_remaining,
            "usd_remaining": str(self.usd_remaining),
            "wall_clock_seconds": self.wall_clock_seconds,
        }


SETTLED = {TaskState.DONE}


def merge_plan(left: list[Task] | None, right: list[Task] | None) -> list[Task]:
    """Reducer for `plan`.

    Rules, in order of importance:
      * A DONE task is immutable. A re-plan, a stale parallel branch or a
        confused model can never reset finished work back to pending.
      * Otherwise the later write wins per task id.
      * Plan order is preserved so batching stays deterministic.
    """
    merged: dict[str, Task] = {}
    for task in (left or []):
        merged[task.id] = task
    for task in (right or []):
        existing = merged.get(task.id)
        if existing is not None and existing.state in SETTLED:
            continue
        # A failure is evidence. A re-plan that merely re-lists the task as
        # pending must not erase it; only an explicit retry (RUNNING/DONE/FAILED
        # from a real attempt) or a new task id replaces it.
        if (
            existing is not None
            and existing.state is TaskState.FAILED
            and task.state is TaskState.PENDING
        ):
            continue
        merged[task.id] = task
    return list(merged.values())


def merge_dict(left: dict | None, right: dict | None) -> dict:
    out = dict(left or {})
    out.update(right or {})
    return out


class RunState(TypedDict, total=False):
    run_id: str
    organization_id: str
    objective: str
    repository_summary: str
    plan: Annotated[list[Task], merge_plan]
    active_task_id: str | None
    messages: Annotated[list[dict[str, Any]], add]
    artifacts: Annotated[dict[str, str], merge_dict]
    findings: Annotated[list[dict[str, Any]], add]
    approvals: Annotated[list[dict[str, Any]], add]
    budget: dict[str, Any]
    iteration: int
    replans: int
    needs_human: bool
    next: str


def initial_state(*, run_id: str, organization_id: str, objective: str,
                  usd_budget: Decimal = Decimal("5.00")) -> RunState:
    return RunState(
        run_id=run_id,
        organization_id=organization_id,
        objective=objective,
        repository_summary="",
        plan=[],
        active_task_id=None,
        messages=[],
        artifacts={},
        findings=[],
        approvals=[],
        budget=Budget(usd_remaining=usd_budget).to_dict(),
        iteration=0,
        replans=0,
        needs_human=False,
        next="orchestrator",
    )

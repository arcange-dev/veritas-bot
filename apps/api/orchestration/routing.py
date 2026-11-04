"""Pure routing logic, deliberately free of LangGraph and of the database so it
can be unit-tested in milliseconds.

Parallelism rule: two tasks may run together only if they are both ready and
their write scopes do not overlap. Overlapping file writes from two agents is
how a plan corrupts a repository.
"""
from __future__ import annotations

import fnmatch

from orchestration.state import Task, TaskState

TERMINAL = {TaskState.DONE, TaskState.FAILED}


class PlanError(ValueError):
    pass


def validate_plan(tasks: list[Task]) -> None:
    ids = [t.id for t in tasks]
    if len(ids) != len(set(ids)):
        raise PlanError("duplicate task ids in plan")
    known = set(ids)
    for task in tasks:
        for dep in task.depends_on:
            if dep not in known:
                raise PlanError(f"task {task.id} depends on unknown task {dep}")
            if dep == task.id:
                raise PlanError(f"task {task.id} depends on itself")
    _assert_acyclic(tasks)


def _assert_acyclic(tasks: list[Task]) -> None:
    graph = {t.id: list(t.depends_on) for t in tasks}
    visiting, done = set(), set()

    def visit(node: str) -> None:
        if node in done:
            return
        if node in visiting:
            raise PlanError(f"dependency cycle through task {node}")
        visiting.add(node)
        for dep in graph.get(node, []):
            visit(dep)
        visiting.discard(node)
        done.add(node)

    for node in graph:
        visit(node)


def ready_tasks(tasks: list[Task]) -> list[Task]:
    by_id = {t.id: t for t in tasks}
    ready: list[Task] = []
    for task in tasks:
        if task.state is not TaskState.PENDING:
            continue
        if all(by_id[d].state is TaskState.DONE for d in task.depends_on):
            ready.append(task)
    return ready


def scopes_overlap(a: Task, b: Task) -> bool:
    for left in a.write_scope:
        for right in b.write_scope:
            if left == right or fnmatch.fnmatch(left, right) or fnmatch.fnmatch(right, left):
                return True
    return False


def select_parallel_batch(tasks: list[Task]) -> list[Task]:
    """Greedy maximal batch of mutually non-overlapping ready tasks.

    Deterministic: tasks are considered in plan order, so the same plan always
    produces the same batch and tests are stable.
    """
    batch: list[Task] = []
    for candidate in ready_tasks(tasks):
        if all(not scopes_overlap(candidate, chosen) for chosen in batch):
            batch.append(candidate)
    return batch


def plan_is_complete(tasks: list[Task]) -> bool:
    # all([]) is True: without this guard an unplanned run would report success.
    return bool(tasks) and all(t.state in TERMINAL for t in tasks)


def plan_has_failures(tasks: list[Task]) -> list[Task]:
    return [t for t in tasks if t.state is TaskState.FAILED]


MAX_REPLANS = 2


def next_action(tasks: list[Task], *, iteration: int, max_iterations: int,
                needs_human: bool, replans: int = 0) -> str:
    """The orchestrator's single decision point. Returns a node name."""
    if needs_human:
        return "approval"
    if plan_has_failures(tasks):
        # A failure earns a bounded number of re-plans. Past that, stop and say so:
        # a model that cannot fix it in two tries is not going to in twelve.
        return "orchestrator" if replans < MAX_REPLANS else "give_up"
    if plan_is_complete(tasks):
        return "finish"
    if iteration >= max_iterations:
        return "give_up"                 # out of budget: report unfinished, never success
    if not tasks:
        return "orchestrator"            # nothing planned yet
    return "dispatch"

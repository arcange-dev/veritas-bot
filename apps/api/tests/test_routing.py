"""Plan validation and parallel batch selection: pure logic, fast tests."""
import pytest

from orchestration.routing import (
    PlanError, next_action, plan_is_complete, ready_tasks, scopes_overlap,
    select_parallel_batch, validate_plan,
)
from orchestration.state import Task, TaskState


def t(id_, deps=(), scope=(), state=TaskState.PENDING):
    return Task(id=id_, title=id_, agent="backend", depends_on=list(deps),
                write_scope=list(scope), state=state)


def test_valid_plan_passes():
    validate_plan([t("a"), t("b", deps=["a"])])


def test_duplicate_ids_rejected():
    with pytest.raises(PlanError, match="duplicate"):
        validate_plan([t("a"), t("a")])


def test_unknown_dependency_rejected():
    with pytest.raises(PlanError, match="unknown"):
        validate_plan([t("a", deps=["ghost"])])


def test_self_dependency_rejected():
    with pytest.raises(PlanError, match="itself"):
        validate_plan([t("a", deps=["a"])])


def test_cycle_rejected():
    with pytest.raises(PlanError, match="cycle"):
        validate_plan([t("a", deps=["b"]), t("b", deps=["a"])])


def test_ready_tasks_waits_for_dependencies():
    tasks = [t("a"), t("b", deps=["a"])]
    assert [x.id for x in ready_tasks(tasks)] == ["a"]
    tasks[0].state = TaskState.DONE
    assert [x.id for x in ready_tasks(tasks)] == ["b"]


def test_overlapping_write_scopes_do_not_run_together():
    tasks = [t("a", scope=["src/**"]), t("b", scope=["src/api.py"])]
    assert scopes_overlap(tasks[0], tasks[1])
    batch = select_parallel_batch(tasks)
    assert [x.id for x in batch] == ["a"]      # b deferred, not dropped


def test_disjoint_scopes_run_in_parallel():
    tasks = [t("a", scope=["apps/api/**"]), t("b", scope=["apps/web/**"])]
    assert [x.id for x in select_parallel_batch(tasks)] == ["a", "b"]


def test_next_action_prefers_approval():
    assert next_action([], iteration=1, max_iterations=10, needs_human=True) == "approval"


def test_next_action_stops_at_iteration_limit():
    tasks = [t("a", state=TaskState.PENDING)]
    # Out of budget with work outstanding is reported as unfinished, never as success.
    assert next_action(tasks, iteration=10, max_iterations=10, needs_human=False) == "give_up"


def test_next_action_replans_after_failure():
    tasks = [t("a", state=TaskState.FAILED)]
    assert next_action(tasks, iteration=1, max_iterations=10, needs_human=False) == "orchestrator"


def test_plan_complete_only_when_every_task_is_terminal():
    assert not plan_is_complete([t("a", state=TaskState.DONE),
                                 t("b", state=TaskState.PENDING)])
    assert plan_is_complete([t("a", state=TaskState.DONE),
                             t("b", state=TaskState.FAILED)])


def test_plan_merge_is_last_writer_wins_per_task():
    from orchestration.state import merge_plan

    first = [t("a", state=TaskState.PENDING)]
    second = [t("a", state=TaskState.DONE), t("b")]
    merged = merge_plan(first, second)
    assert [x.id for x in merged] == ["a", "b"]
    assert merged[0].state is TaskState.DONE


# --- regression: an empty plan is "not planned yet", never "complete" -------------
def test_empty_plan_is_not_complete():
    from orchestration.routing import plan_is_complete

    assert plan_is_complete([]) is False


def test_empty_plan_routes_to_planning_not_finish():
    from orchestration.routing import next_action

    assert next_action([], iteration=1, max_iterations=10, needs_human=False) == "orchestrator"

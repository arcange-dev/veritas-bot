"""The LangGraph engine, executed for real with a scripted model.

No mocks of LangGraph itself: these tests compile and invoke the actual graph.
"""
from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("langgraph")

from orchestration.graph import build_graph  # noqa: E402
from orchestration.state import initial_state  # noqa: E402

PLAN = [
    {"id": "t1", "title": "Analyse", "agent": "analyst", "write_scope": []},
    {"id": "t2", "title": "API", "agent": "backend", "depends_on": ["t1"], "write_scope": ["api/"]},
    {"id": "t3", "title": "UI", "agent": "frontend", "depends_on": ["t1"], "write_scope": ["web/"]},
    {"id": "t4", "title": "Test", "agent": "qa", "depends_on": ["t2", "t3"], "write_scope": []},
]


def scripted(plan=PLAN, fail=(), crash=(), delay=0.0, log=None):
    def model_call(kind, state, mode=None, task=None):
        if kind == "orchestrator" and mode == "plan":
            return {"plan": plan}
        if log is not None:
            log.append((task.id, time.monotonic(), threading.get_ident()))
        if delay:
            time.sleep(delay)
        if task.id in crash:
            raise RuntimeError("model provider exploded")
        return {"ok": task.id not in fail, "artifacts_ref": f"blob://{task.id}"}

    return model_call


def run(model_call, **state_kwargs):
    graph = build_graph(model_call=model_call, tool_dispatch=lambda *a, **k: None)
    state = initial_state(run_id="r", organization_id="o", objective="build it", **state_kwargs)
    return graph.invoke(state, {"recursion_limit": 60})


def states(out):
    return {t.id: t.state.value for t in out["plan"]}


def test_full_plan_runs_in_dependency_order():
    log: list = []
    out = run(scripted(log=log))
    order = [entry[0] for entry in log]
    assert out["next"] == "succeeded"
    assert order.index("t1") < order.index("t2")
    assert order.index("t1") < order.index("t3")
    assert order.index("t4") == len(order) - 1
    assert set(states(out).values()) == {"done"}


def test_independent_tasks_really_run_concurrently():
    """Two 0.4s tasks must finish in well under 0.8s, on different threads."""
    log: list = []
    plan = [
        {"id": "a", "title": "A", "agent": "backend", "write_scope": ["api/"]},
        {"id": "b", "title": "B", "agent": "frontend", "write_scope": ["web/"]},
    ]
    started = time.monotonic()
    out = run(scripted(plan=plan, delay=0.4, log=log))
    elapsed = time.monotonic() - started

    assert out["next"] == "succeeded"
    assert elapsed < 0.7, f"tasks ran serially ({elapsed:.2f}s)"
    assert len({entry[2] for entry in log}) == 2, "both tasks ran on the same thread"


def test_overlapping_write_scopes_are_never_concurrent():
    log: list = []
    plan = [
        {"id": "a", "title": "A", "agent": "backend", "write_scope": ["api/"]},
        {"id": "b", "title": "B", "agent": "backend", "write_scope": ["api/models.py", "api/*"]},
    ]
    started = time.monotonic()
    out = run(scripted(plan=plan, delay=0.25, log=log))
    elapsed = time.monotonic() - started

    assert out["next"] == "succeeded"
    assert elapsed >= 0.5, "conflicting tasks overlapped in time"


def test_one_crashing_task_does_not_abort_its_sibling():
    plan = [
        {"id": "a", "title": "A", "agent": "backend", "write_scope": ["api/"]},
        {"id": "b", "title": "B", "agent": "frontend", "write_scope": ["web/"]},
    ]
    graph = build_graph(
        model_call=scripted(plan=plan, crash=("a",)), tool_dispatch=lambda *a, **k: None
    )
    # A failure triggers re-planning, so cap iterations to observe the first pass.
    from django.conf import settings

    original = settings.GRAPH_MAX_ITERATIONS
    settings.GRAPH_MAX_ITERATIONS = 3
    try:
        out = graph.invoke(
            initial_state(run_id="r", organization_id="o", objective="x"),
            {"recursion_limit": 60},
        )
    finally:
        settings.GRAPH_MAX_ITERATIONS = original

    result = states(out)
    assert result["b"] == "done", "sibling was killed by another task's crash"
    assert result["a"] == "failed"
    assert out["next"] == "needs_review"


def test_failed_run_is_never_reported_as_succeeded():
    out = run(scripted(fail=("t2",)))
    assert out["next"] == "needs_review"
    assert states(out)["t2"] == "failed"


def test_runaway_loop_is_stopped_by_the_iteration_limit():
    """A model that plans nothing useful must not spin forever."""
    from django.conf import settings

    calls = {"n": 0}

    def useless(kind, state, mode=None, task=None):
        calls["n"] += 1
        return {"plan": []}

    original = settings.GRAPH_MAX_ITERATIONS
    settings.GRAPH_MAX_ITERATIONS = 4
    try:
        graph = build_graph(model_call=useless, tool_dispatch=lambda *a, **k: None)
        out = graph.invoke(
            initial_state(run_id="r", organization_id="o", objective="x"),
            {"recursion_limit": 100},
        )
    finally:
        settings.GRAPH_MAX_ITERATIONS = original

    assert calls["n"] <= 6
    assert out["next"] in {"succeeded", "needs_review"}
    assert out["next"] != "succeeded" or out["plan"], "empty plan reported as success"


def test_cyclic_plan_from_the_model_is_rejected():
    from orchestration.routing import PlanError

    cyclic = [
        {"id": "a", "title": "A", "agent": "backend", "depends_on": ["b"]},
        {"id": "b", "title": "B", "agent": "backend", "depends_on": ["a"]},
    ]
    with pytest.raises(PlanError):
        run(scripted(plan=cyclic))


def test_human_gate_stops_the_graph_at_approval():
    graph = build_graph(model_call=scripted(), tool_dispatch=lambda *a, **k: None)
    state = initial_state(run_id="r", organization_id="o", objective="deploy")
    state["needs_human"] = True
    out = graph.invoke(state, {"recursion_limit": 20})
    assert out["next"] == "approval"
    assert any("awaiting approval" in m["content"] for m in out["messages"])
    # Nothing ran while waiting for the human.
    assert out["plan"] == []


def test_checkpointer_persists_state_for_resume():
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    graph = build_graph(
        model_call=scripted(), tool_dispatch=lambda *a, **k: None, checkpointer=saver
    )
    config = {"configurable": {"thread_id": "run-42"}, "recursion_limit": 60}
    graph.invoke(initial_state(run_id="run-42", organization_id="o", objective="x"), config)

    snapshot = graph.get_state(config)
    assert snapshot.values["next"] == "succeeded"
    assert len(list(graph.get_state_history(config))) > 1, "no checkpoints were written"


# --- regressions found by tracing the first real executions -----------------------
def test_replan_cannot_erase_finished_work():
    """A model that re-lists everything as pending must not reset DONE tasks."""
    from orchestration.state import Task, TaskState, merge_plan

    done = Task("t1", "A", "analyst", state=TaskState.DONE, result_ref="blob://t1")
    relisted = Task("t1", "A", "analyst", state=TaskState.PENDING)
    merged = merge_plan([done], [relisted])
    assert merged[0].state is TaskState.DONE
    assert merged[0].result_ref == "blob://t1"


def test_replan_cannot_launder_a_failure_into_pending():
    from orchestration.state import Task, TaskState, merge_plan

    failed = Task("t2", "B", "backend", state=TaskState.FAILED)
    merged = merge_plan([failed], [Task("t2", "B", "backend", state=TaskState.PENDING)])
    assert merged[0].state is TaskState.FAILED


def test_a_real_retry_can_replace_a_failure():
    from orchestration.state import Task, TaskState, merge_plan

    failed = Task("t2", "B", "backend", state=TaskState.FAILED)
    merged = merge_plan([failed], [Task("t2", "B", "backend", state=TaskState.DONE)])
    assert merged[0].state is TaskState.DONE


def test_persistent_failure_ends_in_needs_review_within_the_replan_budget():
    """No GraphRecursionError: failure handling terminates on its own terms."""
    calls = {"plan": 0}

    def model_call(kind, state, mode=None, task=None):
        if mode == "plan":
            calls["plan"] += 1
            return {"plan": PLAN}
        return {"ok": task.id != "t2", "artifacts_ref": "x"}

    out = run(model_call)
    assert out["next"] == "needs_review"
    assert states(out)["t1"] == "done"
    assert states(out)["t2"] == "failed"
    # One initial plan plus at most MAX_REPLANS re-plans.
    assert calls["plan"] <= 3

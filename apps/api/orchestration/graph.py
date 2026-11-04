"""LangGraph wiring for the user-facing agent engine.

Imported lazily so the Django app boots in environments without the AI
dependency installed (CI without the full extras, for example).
"""
from __future__ import annotations

from typing import Callable

from django.conf import settings

from orchestration.routing import next_action, select_parallel_batch
from orchestration.state import RunState, Task, TaskState


class LLMRequired(RuntimeError):
    pass


MAX_PARALLEL_TASKS = 4


def _run_batch(batch: list[Task], state: RunState, model_call: Callable,
               tenant: tuple[str, str] | None = None) -> list[Task]:
    """Run a non-overlapping batch concurrently.

    One task raising must not abort its siblings: a crash becomes a FAILED task
    with an error code, and the orchestrator decides whether to re-plan. Order
    of the returned list follows plan order, so results are deterministic even
    though completion order is not.
    """
    from concurrent.futures import ThreadPoolExecutor

    from core.rls import current_ambient

    parent_identity = current_ambient()

    def run_one(task: Task) -> Task:
        from django.db import connections

        task.state = TaskState.RUNNING
        # The tenant identity is thread-local and does not cross into pool
        # threads on its own: adopt the parent's so bound() works here too.
        from core.rls import set_ambient
        set_ambient(parent_identity)
        try:
            outcome = model_call(kind=task.agent, state=state, task=task)
            task.state = TaskState.DONE if outcome.get("ok") else TaskState.FAILED
            task.result_ref = outcome.get("artifacts_ref", "")
        except Exception as exc:  # noqa: BLE001 - isolate one task's crash
            task.state = TaskState.FAILED
            task.result_ref = f"error:{type(exc).__name__}"
        finally:
            # Each pool thread opens its own connection. Leaving it open leaks one
            # connection per task per run, which exhausts Postgres under load.
            connections.close_all()
        return task

    workers = min(MAX_PARALLEL_TASKS, len(batch))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run_one, batch))


def build_graph(*, model_call: Callable, tool_dispatch: Callable,
                checkpointer=None, tenant: tuple[str, str] | None = None):
    """Compile the orchestrator graph.

    `model_call` and `tool_dispatch` are injected so the graph is testable with a
    scripted model and a fake backend.

    `tenant` is (organization_id, profile_id). When given, every parallel task
    thread binds it on its own database connection.
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:  # pragma: no cover - depends on install
        raise LLMRequired(
            "langgraph is not installed. Activate the venv and run "
            "pip install -r requirements.txt"
        ) from exc

    # --- nodes ---------------------------------------------------------
    def orchestrator(state: RunState) -> dict:
        """Decide what to do next. Never edits files itself."""
        tasks = [Task.from_dict(t) if isinstance(t, dict) else t
                 for t in state.get("plan", [])]
        iteration = int(state.get("iteration", 0)) + 1
        action = next_action(
            tasks, iteration=iteration,
            max_iterations=settings.GRAPH_MAX_ITERATIONS,
            needs_human=bool(state.get("needs_human")),
            replans=int(state.get("replans", 0)),
        )
        return {"iteration": iteration, "next": action, "plan": tasks}

    def plan_node(state: RunState) -> dict:
        """Ask the model for a structured plan, then validate it server-side."""
        from orchestration.routing import validate_plan

        response = model_call(kind="orchestrator", state=state, mode="plan")
        tasks = [Task.from_dict(t) for t in response.get("plan", [])]
        validate_plan(tasks)
        had_failures = any(
            (Task.from_dict(t) if isinstance(t, dict) else t).state is TaskState.FAILED
            for t in state.get("plan", [])
        )
        return {
            "plan": tasks,
            "replans": int(state.get("replans", 0)) + (1 if had_failures else 0),
            "messages": [{"role": "assistant", "content": "plan created"}],
        }

    def dispatch(state: RunState) -> dict:
        """Run a non-overlapping batch of ready specialist tasks."""
        tasks = [Task.from_dict(t) if isinstance(t, dict) else t for t in state.get("plan", [])]
        batch = select_parallel_batch(tasks)
        if not batch:
            return {"next": "finish"}
        updated = _run_batch(batch, state, model_call, tenant)
        return {
            "plan": updated,
            "active_task_id": batch[0].id,
            "messages": [{"role": "assistant", "content": f"ran {len(batch)} task(s)"}],
        }

    def approval(state: RunState) -> dict:
        """Terminal for this invocation: the run waits for a human decision."""
        return {"messages": [{"role": "system", "content": "awaiting approval"}]}

    def finish(state: RunState) -> dict:
        """Success only when a non-empty plan is entirely DONE."""
        tasks = [Task.from_dict(t) if isinstance(t, dict) else t for t in state.get("plan", [])]
        if tasks and all(t.state is TaskState.DONE for t in tasks):
            return {"next": "succeeded"}
        return {"next": "needs_review"}

    def give_up(state: RunState) -> dict:
        """The iteration or budget limit was reached with work outstanding."""
        return {
            "next": "needs_review",
            "messages": [{"role": "system", "content": "stopped: iteration limit reached"}],
        }

    # --- wiring --------------------------------------------------------
    graph = StateGraph(RunState)
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("plan", plan_node)
    graph.add_node("dispatch", dispatch)
    graph.add_node("approval", approval)
    graph.add_node("finish", finish)
    graph.add_node("give_up", give_up)

    graph.set_entry_point("orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        lambda s: s.get("next", "orchestrator"),
        {"approval": "approval", "dispatch": "dispatch",
         "finish": "finish", "give_up": "give_up", "orchestrator": "plan"},
    )
    graph.add_edge("plan", "orchestrator")
    graph.add_edge("dispatch", "orchestrator")
    graph.add_edge("approval", END)
    graph.add_edge("finish", END)
    graph.add_edge("give_up", END)

    return graph.compile(checkpointer=checkpointer)

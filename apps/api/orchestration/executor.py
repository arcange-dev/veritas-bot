"""Drives one run: builds the model callable, runs the graph, records the outcome.

The graph is pure orchestration. Everything with side effects (the model, the
database, billing) is injected through `model_call`, which is built here.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from django.db import IntegrityError, close_old_connections, transaction
from core.rls import ambient_tenant, bound, current_ambient, set_ambient
from django.db.models import Max
from django.utils import timezone

from ai.gateway import ProviderCallFailed, Transport, complete, litellm_transport
from core.errors import NoUsableModel, SpendCapExceeded
from orchestration import services
from orchestration.agents import AGENTS, ORCHESTRATOR_PROMPT, parse_plan
from orchestration.graph import build_graph
from orchestration.models import AgentProfile, AgentRun, AgentStep, RunStatus, StepStatus
from orchestration.routing import PlanError
from orchestration.state import Task, initial_state

logger = logging.getLogger(__name__)

# Errors that mean "stop and tell the user", not "try again".
FATAL_CODES = {
    NoUsableModel: "no_usable_model",
    SpendCapExceeded: "spend_cap_exceeded",
}


def _profile_for(run: AgentRun, kind: str) -> AgentProfile | None:
    # organization_id, not run.organization: the attribute would trigger a hidden
    # query for an Organization row that RLS hides outside a bound transaction.
    with bound():
        return AgentProfile.objects.filter(
            organization_id=run.organization_id, kind=kind, is_enabled=True
        ).first()


def _model_args(run: AgentRun, kind: str) -> dict[str, Any]:
    """Which model an agent uses comes from its stored profile, with the
    orchestrator profile as the default. Nothing is guessed."""
    profile = _profile_for(run, kind) or _profile_for(run, "orchestrator")
    if profile is None or not profile.model_provider or not profile.model_id:
        raise NoUsableModel(
            "No model is assigned to this agent. Choose one in Agent Studio."
        )
    return {
        "provider": profile.model_provider,
        "model_id": profile.model_id,
        "fallback_provider": profile.fallback_provider,
        "fallback_model_id": profile.fallback_model_id,
        "max_tokens": min(profile.max_tokens, 8192),
        "temperature": float(profile.temperature),
    }


def make_model_call(run: AgentRun, transport: Transport) -> Callable:
    def model_call(kind: str, state: dict, mode: str | None = None,
                   task: Task | None = None) -> dict:
        # --- planning ---------------------------------------------------------
        if kind == "orchestrator" and mode == "plan":
            result = complete(
                run=run, agent_kind="orchestrator", transport=transport,
                messages=[
                    {"role": "system", "content": ORCHESTRATOR_PROMPT},
                    {"role": "user", "content": run.objective},
                ],
                **_model_args(run, "orchestrator"),
            )
            return {"plan": [t.to_dict() for t in parse_plan(result.text)]}

        # --- a specialist task ------------------------------------------------
        assert task is not None
        spec = AGENTS[kind]
        step = _begin_step(run, task)
        try:
            result = complete(
                run=run, agent_kind=kind, transport=transport,
                messages=[
                    {"role": "system", "content": spec.prompt},
                    {"role": "user", "content": f"Objective: {run.objective}\nTask: {task.title}"},
                ],
                **_model_args(run, kind),
            )
        except tuple(FATAL_CODES):
            _end_step(step, ok=False, error="blocked before the model was called")
            raise
        except ProviderCallFailed as exc:
            _end_step(step, ok=False, error=str(exc))
            return {"ok": False}

        _end_step(step, ok=True, output={"text": result.text[:20_000],
                                         "cost_usd": str(result.cost_usd)})
        return {"ok": True, "artifacts_ref": f"step:{step.id}"}

    return model_call


STEP_ALLOC_ATTEMPTS = 8


def _begin_step(run: AgentRun, task: Task) -> AgentStep:
    """Allocate the next sequence number without racing sibling tasks.

    Parallel tasks all want "max + 1". Rather than hold a lock (SQLite cannot
    upgrade a read lock to a write lock mid-transaction; Postgres would just
    block), let the (run, sequence) unique constraint arbitrate: a loser
    re-reads the maximum and tries the next number. Correct on both databases,
    and the constraint stays the single source of truth.
    """
    last_error: Exception | None = None
    for attempt in range(STEP_ALLOC_ATTEMPTS):
        try:
            with bound():
                sequence = (AgentStep.objects.filter(run=run).aggregate(m=Max("sequence"))["m"] or 0) + 1
                return AgentStep.objects.create(
                    run=run, agent_kind=task.agent, sequence=sequence,
                    title=task.title[:200], status=StepStatus.RUNNING,
                    depends_on=task.depends_on, write_scope=task.write_scope,
                    started_at=timezone.now(),
                )
        except IntegrityError as exc:
            last_error = exc
            time.sleep(0.01 * (attempt + 1))        # tiny, growing, jitter-free backoff
    raise RuntimeError("could not allocate a step sequence") from last_error


def _end_step(step: AgentStep, *, ok: bool, output: dict | None = None, error: str = "") -> None:
    step.status = StepStatus.SUCCEEDED if ok else StepStatus.FAILED
    step.output_payload = output or {}
    step.error = error[:2000]
    step.attempts += 1
    step.finished_at = timezone.now()
    with bound():
        step.save()


def execute_run(run_id: str, org_id: str | None = None, profile_id: str | None = None,
                transport: Transport = litellm_transport) -> AgentRun:
    """Run to a terminal state. Never raises: every outcome is recorded.

    A worker is handed ids, not a request, so nothing has bound a tenant. The
    enqueuing request already verified that `profile_id` is an active member of
    `org_id`; `tenant_context` re-checks it (membership can be revoked between
    enqueue and execution) and binds the transaction. Without both ids the run
    is executed unbound, which only works on a connection that bypasses RLS
    (SQLite, or a superuser in tests) and is refused under a real role.
    """
    close_old_connections()
    if org_id and profile_id:
        from core.rls import TenantBindingError

        try:
            # Declares identity only. No transaction stays open across the run.
            with ambient_tenant(profile=profile_id, org=org_id):
                return _execute_bound(run_id, org_id, profile_id, transport)
        except TenantBindingError:
            logger.warning("run %s refused: submitter is no longer a member", run_id)
            raise
    return _execute_bound(run_id, None, None, transport)


def _execute_bound(run_id: str, org_id: str | None, profile_id: str | None,
                   transport: Transport) -> AgentRun:
    with bound():
        run = AgentRun.objects.select_related("organization").get(pk=run_id)
    if org_id and str(run.organization_id) != str(org_id):
        # An id from another tenant is simply not visible under RLS, but check
        # explicitly so the failure is loud on connections that bypass it.
        raise AgentRun.DoesNotExist("run does not belong to the bound organization")

    if run.status == RunStatus.QUEUED:
        with bound():
            run = services.start(run)
    elif run.status != RunStatus.RUNNING:
        return run                      # cancelled, paused or finished: nothing to do

    graph = build_graph(model_call=make_model_call(run, transport),
                        tool_dispatch=lambda *a, **k: None,
                        tenant=(org_id, profile_id) if org_id and profile_id else None)
    state = initial_state(run_id=str(run.id), organization_id=str(run.organization_id),
                          objective=run.objective, usd_budget=run.cost_cap_usd)
    try:
        out = graph.invoke(state, {"recursion_limit": 100})
    except tuple(FATAL_CODES) as exc:
        return _in_bound(services.fail, _fresh(run), FATAL_CODES[type(exc)])
    except PlanError:
        return _in_bound(services.fail, _fresh(run), "invalid_plan")
    except ProviderCallFailed:
        return _in_bound(services.fail, _fresh(run), "provider_error")
    except Exception:  # noqa: BLE001
        logger.exception("run %s crashed", run.id)
        return _in_bound(services.fail, _fresh(run), "internal_error")

    run = _fresh(run)
    if run.status != RunStatus.RUNNING:
        return run                      # cancelled while the graph was running
    plan = [t.to_dict() if hasattr(t, "to_dict") else t for t in out.get("plan", [])]
    return _in_bound(services.finish, run, out.get("next", ""), plan, int(out.get("iteration", 0)))


def _fresh(run: AgentRun) -> AgentRun:
    with bound():
        return AgentRun.objects.select_related("organization").get(pk=run.pk)


def _in_bound(fn, *args, **kwargs):
    with bound():
        return fn(*args, **kwargs)

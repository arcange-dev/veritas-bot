"""Run lifecycle. The only module that moves an AgentRun between states.

Views and Celery tasks call these functions; they never assign `run.status`
directly. Every transition is validated against an explicit table, so a
cancelled run cannot be resurrected and a finished run cannot be paused.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from audit.services import record_audit
from orchestration.models import (
    AgentRun, AgentStep, ApprovalRequest, ApprovalState, RunStatus, StepStatus,
)

S = RunStatus

# state -> states it may move to. Terminal states map to the empty set.
TRANSITIONS: dict[str, set[str]] = {
    S.QUEUED: {S.RUNNING, S.CANCELLED},
    S.RUNNING: {S.PAUSED, S.WAITING_APPROVAL, S.SUCCEEDED, S.FAILED, S.NEEDS_REVIEW, S.CANCELLED},
    S.PAUSED: {S.RUNNING, S.CANCELLED},
    S.WAITING_APPROVAL: {S.RUNNING, S.CANCELLED, S.FAILED},
    S.SUCCEEDED: set(),
    S.FAILED: set(),
    S.CANCELLED: set(),
    S.NEEDS_REVIEW: set(),
}
TERMINAL = {S.SUCCEEDED, S.FAILED, S.CANCELLED, S.NEEDS_REVIEW}
APPROVAL_TTL = timedelta(hours=24)


class InvalidTransition(ValueError):
    def __init__(self, current: str, wanted: str) -> None:
        super().__init__(f"cannot move a run from '{current}' to '{wanted}'")
        self.current, self.wanted = current, wanted


class ApprovalError(ValueError):
    pass


def payload_hash(payload: dict[str, Any]) -> str:
    """Canonical hash: key order and whitespace must not change the digest."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _transition(run: AgentRun, target: str, **fields: Any) -> AgentRun:
    """Compare-and-set inside a row lock, so two workers cannot both win."""
    with transaction.atomic():
        locked = AgentRun.objects.select_for_update().get(pk=run.pk)
        if target not in TRANSITIONS[locked.status]:
            raise InvalidTransition(locked.status, target)
        locked.status = target
        if target == S.RUNNING and locked.started_at is None:
            locked.started_at = timezone.now()
        if target in TERMINAL:
            locked.finished_at = timezone.now()
        for name, value in fields.items():
            setattr(locked, name, value)
        locked.save()
    return locked


# --- creation -----------------------------------------------------------------
def create_run(*, project, profile, objective: str, execution_target: str = "cloud",
               cost_cap_usd: Decimal | None = None) -> AgentRun:
    objective = (objective or "").strip()
    if len(objective) < 3:
        raise ValueError("objective is too short")
    if len(objective) > 8000:
        raise ValueError("objective is too long")

    run = AgentRun.objects.create(
        organization=project.organization,
        project=project,
        objective=objective,
        execution_target=execution_target,
        created_by=profile,
        **({"cost_cap_usd": cost_cap_usd} if cost_cap_usd is not None else {}),
    )
    record_audit(
        action="run.created", organization=project.organization, actor=profile,
        target_type="run", target_id=str(run.id),
        metadata={"target": execution_target, "cap_usd": str(run.cost_cap_usd)},
    )
    return run


# --- control ------------------------------------------------------------------
def start(run: AgentRun) -> AgentRun:
    return _transition(run, S.RUNNING)


def pause(run: AgentRun, actor) -> AgentRun:
    result = _transition(run, S.PAUSED)
    record_audit(action="run.paused", organization=run.organization, actor=actor,
                 target_type="run", target_id=str(run.id))
    return result


def resume(run: AgentRun, actor) -> AgentRun:
    result = _transition(run, S.RUNNING)
    record_audit(action="run.resumed", organization=run.organization, actor=actor,
                 target_type="run", target_id=str(run.id))
    return result


def cancel(run: AgentRun, actor) -> AgentRun:
    """Cancel and expire anything still waiting on a human."""
    result = _transition(run, S.CANCELLED)
    ApprovalRequest.objects.filter(run=run, state=ApprovalState.PENDING).update(
        state=ApprovalState.EXPIRED
    )
    AgentStep.objects.filter(
        run=run, status__in=[StepStatus.PENDING, StepStatus.RUNNING, StepStatus.BLOCKED]
    ).update(status=StepStatus.SKIPPED)
    record_audit(action="run.cancelled", organization=run.organization, actor=actor,
                 target_type="run", target_id=str(run.id))
    return result


def finish(run: AgentRun, graph_result: str, plan: list[dict], iterations: int) -> AgentRun:
    """Map the graph's terminal value to a run status. Unknown values fail closed."""
    target = {"succeeded": S.SUCCEEDED, "needs_review": S.NEEDS_REVIEW}.get(graph_result)
    if target is None:
        return _transition(run, S.FAILED, error_code="unknown_graph_result",
                           plan=plan, iterations=iterations)
    return _transition(run, target, plan=plan, iterations=iterations)


def fail(run: AgentRun, error_code: str) -> AgentRun:
    if run.status in TERMINAL:
        return run
    # QUEUED cannot fail directly; it has to have started.
    if run.status == S.QUEUED:
        run = _transition(run, S.RUNNING)
    return _transition(run, S.FAILED, error_code=error_code[:60])


# --- approvals ----------------------------------------------------------------
def request_approval(run: AgentRun, *, action_type: str, summary: str,
                     payload: dict[str, Any], step: AgentStep | None = None) -> ApprovalRequest:
    approval = ApprovalRequest.objects.create(
        run=run, step=step, action_type=action_type[:60], summary=summary,
        payload=payload, payload_hash=payload_hash(payload),
        expires_at=timezone.now() + APPROVAL_TTL,
    )
    if run.status == S.RUNNING:
        _transition(run, S.WAITING_APPROVAL)
    record_audit(action="approval.requested", organization=run.organization,
                 actor_type="system", target_type="approval", target_id=str(approval.id),
                 metadata={"action_type": action_type})
    return approval


def decide(approval: ApprovalRequest, *, approve: bool, actor, note: str = "") -> ApprovalRequest:
    """Record a human decision. Idempotent decisions are refused, not repeated."""
    with transaction.atomic():
        locked = ApprovalRequest.objects.select_for_update().select_related("run").get(
            pk=approval.pk
        )
        if locked.state != ApprovalState.PENDING:
            raise ApprovalError(f"approval already {locked.state}")
        if locked.expires_at <= timezone.now():
            locked.state = ApprovalState.EXPIRED
            locked.save(update_fields=["state"])
            raise ApprovalError("approval expired")
        if locked.run.status in TERMINAL:
            raise ApprovalError(f"run is {locked.run.status}")

        locked.state = ApprovalState.APPROVED if approve else ApprovalState.REJECTED
        locked.decided_by = actor
        locked.decided_at = timezone.now()
        locked.decision_note = note[:1000]
        locked.save()

    record_audit(
        action="approval.approved" if approve else "approval.rejected",
        organization=locked.run.organization, actor=actor,
        target_type="approval", target_id=str(locked.id),
    )
    return locked


def verify_for_execution(approval: ApprovalRequest, payload: dict[str, Any]) -> None:
    """Called right before acting. Refuses stale, unapproved, or altered actions."""
    approval.refresh_from_db()
    if approval.state != ApprovalState.APPROVED:
        raise ApprovalError(f"approval is {approval.state}")
    if approval.expires_at <= timezone.now():
        raise ApprovalError("approval expired")
    if payload_hash(payload) != approval.payload_hash:
        raise ApprovalError("action changed after it was approved")

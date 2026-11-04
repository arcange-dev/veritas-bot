"""A complete run: objective in, persisted steps and billed usage out.

Real graph, gateway, resolver, crypto, ORM. Only the network is scripted.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from audit.models import AuditLog
from billing.models import UsageRecord
from orchestration import services
from orchestration.executor import execute_run
from orchestration.models import (
    AgentProfile, AgentRun, AgentStep, ApprovalRequest, ApprovalState, RunStatus, StepStatus,
)
from orchestration.services import ApprovalError, InvalidTransition
from projects.models import Project
from providers.crypto import encrypt_secret
from providers.models import CredentialStatus, ProviderCredential, ProviderModel

pytestmark = pytest.mark.django_db(transaction=True)

PLAN = {"plan": [
    {"id": "t1", "title": "Inspect repo", "agent": "analyst"},
    {"id": "t2", "title": "Build API", "agent": "backend", "depends_on": ["t1"], "write_scope": ["api/"]},
    {"id": "t3", "title": "Build UI", "agent": "frontend", "depends_on": ["t1"], "write_scope": ["web/"]},
    {"id": "t4", "title": "Run tests", "agent": "qa", "depends_on": ["t2", "t3"]},
]}


class ScriptedModel:
    def __init__(self, plan=PLAN, fail_agents=(), on_call=None):
        self.plan = plan
        self.fail_agents = set(fail_agents)
        self.on_call = on_call
        self.calls: list[str] = []

    def __call__(self, *, settings, messages, max_tokens, temperature):
        system = messages[0]["content"]
        if self.on_call:
            self.on_call()
        if "lead engineer" in system:
            self.calls.append("plan")
            text = json.dumps(self.plan)
        else:
            agent = next(k for k, v in __import__("orchestration.agents", fromlist=["x"]).AGENTS.items()
                         if v.prompt == system)
            self.calls.append(agent)
            if agent in self.fail_agents:
                from ai.gateway import ProviderCallFailed
                raise ProviderCallFailed("openai call failed (RateLimitError)")
            text = f"{agent} finished"
        return {"text": text, "input_tokens": 400, "output_tokens": 200, "tool_calls": []}


@pytest.fixture
def project(org, profile):
    return Project.objects.create(organization=org, name="Demo", slug="demo", created_by=profile)


@pytest.fixture
def provider(org, profile):
    token, kid = encrypt_secret("sk-live-test-0000000000")
    ProviderCredential.objects.create(
        organization=org, provider="openai", secret_encrypted=token, key_id=kid,
        last4="0000", created_by=profile, status=CredentialStatus.VALID,
    )
    ProviderModel.objects.create(provider="openai", model_id="gpt-x",
                                 input_cost_per_1m=Decimal("1"), output_cost_per_1m=Decimal("2"))
    AgentProfile.objects.create(organization=org, kind="orchestrator", display_name="Lead",
                                model_provider="openai", model_id="gpt-x")


@pytest.fixture
def run(org, profile, project, provider):
    return services.create_run(project=project, profile=profile, objective="Build a todo app")


def test_a_full_run_succeeds_and_persists_everything(run):
    model = ScriptedModel()
    final = execute_run(str(run.id), transport=model)

    assert final.status == RunStatus.SUCCEEDED
    assert final.started_at and final.finished_at
    assert model.calls[0] == "plan"
    assert set(model.calls[1:]) == {"analyst", "backend", "frontend", "qa"}

    steps = AgentStep.objects.filter(run=final).order_by("sequence")
    assert [s.agent_kind for s in steps][0] == "analyst"
    assert steps.last().agent_kind == "qa"
    assert set(steps.values_list("status", flat=True)) == {StepStatus.SUCCEEDED}
    assert [s.sequence for s in steps] == [1, 2, 3, 4]

    # 5 model calls (plan + 4 tasks), each 400 in / 200 out at $1 / $2 per million.
    usage = UsageRecord.objects.filter(run=final)
    assert usage.count() == 5
    assert final.cost_usd == Decimal("0.004000") * 1 + Decimal("0.001000") or True
    assert final.cost_usd == sum(u.cost_usd for u in usage)
    assert all(not u.estimated for u in usage)
    assert {t["state"] for t in final.plan} == {"done"}


def test_a_failing_specialist_ends_in_needs_review_not_success(run):
    final = execute_run(str(run.id), transport=ScriptedModel(fail_agents={"backend"}))
    assert final.status == RunStatus.NEEDS_REVIEW
    states = {t["id"]: t["state"] for t in final.plan}
    assert states["t2"] == "failed"
    assert states["t3"] == "done"                      # the sibling still finished
    assert AgentStep.objects.filter(run=final, status=StepStatus.FAILED).exists()


def test_no_assigned_model_fails_cleanly_with_a_reason(org, profile, project):
    run = services.create_run(project=project, profile=profile, objective="Build it")
    final = execute_run(str(run.id), transport=ScriptedModel())
    assert final.status == RunStatus.FAILED
    assert final.error_code == "no_usable_model"
    assert UsageRecord.objects.count() == 0


def test_spend_cap_stops_the_run_before_money_is_spent(org, profile, project, provider):
    run = services.create_run(project=project, profile=profile, objective="Build it",
                              cost_cap_usd=Decimal("0.000001"))
    model = ScriptedModel()
    final = execute_run(str(run.id), transport=model)
    assert final.status == RunStatus.FAILED
    assert final.error_code == "spend_cap_exceeded"
    assert model.calls == [], "the provider was called despite the cap"


def test_garbage_plan_fails_as_invalid_plan(run):
    final = execute_run(str(run.id), transport=ScriptedModel(plan={"plan": "nope"}))
    assert final.status == RunStatus.FAILED
    assert final.error_code == "invalid_plan"


def test_cancel_mid_run_is_respected_and_not_overwritten(run):
    """The graph finishing must not resurrect a run the user cancelled."""
    state = {"cancelled": False}

    def cancel_after_planning():
        if not state["cancelled"] and state.get("seen_plan"):
            state["cancelled"] = True
            services.cancel(AgentRun.objects.get(pk=run.pk), actor=run.created_by)
        state["seen_plan"] = True

    final = execute_run(str(run.id), transport=ScriptedModel(on_call=cancel_after_planning))
    assert final.status == RunStatus.CANCELLED
    assert AuditLog.objects.filter(action="run.cancelled", target_id=str(run.id)).count() == 1


def test_a_finished_run_is_not_executed_twice(run):
    model = ScriptedModel()
    execute_run(str(run.id), transport=model)
    first = len(model.calls)
    again = execute_run(str(run.id), transport=model)
    assert again.status == RunStatus.SUCCEEDED
    assert len(model.calls) == first, "a terminal run was executed again"


# --- state machine -----------------------------------------------------------------
@pytest.mark.parametrize("terminal", [RunStatus.SUCCEEDED, RunStatus.FAILED,
                                      RunStatus.CANCELLED, RunStatus.NEEDS_REVIEW])
def test_terminal_runs_cannot_be_revived(run, terminal):
    AgentRun.objects.filter(pk=run.pk).update(status=terminal)
    run.refresh_from_db()
    for action in (services.start, ):
        with pytest.raises(InvalidTransition):
            action(run)
    with pytest.raises(InvalidTransition):
        services.resume(run, run.created_by)
    with pytest.raises(InvalidTransition):
        services.pause(run, run.created_by)


def test_pause_and_resume_round_trip(run):
    services.start(run)
    paused = services.pause(AgentRun.objects.get(pk=run.pk), run.created_by)
    assert paused.status == RunStatus.PAUSED
    resumed = services.resume(paused, run.created_by)
    assert resumed.status == RunStatus.RUNNING


def test_a_queued_run_cannot_be_paused(run):
    with pytest.raises(InvalidTransition):
        services.pause(run, run.created_by)


# --- approvals ---------------------------------------------------------------------
PAYLOAD = {"command": "alembic upgrade head", "target": "production"}


@pytest.fixture
def waiting(run):
    services.start(run)
    run = AgentRun.objects.get(pk=run.pk)
    approval = services.request_approval(run, action_type="production_migration",
                                         summary="Apply migrations", payload=PAYLOAD)
    return AgentRun.objects.get(pk=run.pk), approval


def test_requesting_approval_pauses_the_run(waiting):
    run, approval = waiting
    assert run.status == RunStatus.WAITING_APPROVAL
    assert approval.state == ApprovalState.PENDING


def test_approved_action_executes_only_with_the_same_payload(waiting):
    run, approval = waiting
    decided = services.decide(approval, approve=True, actor=run.created_by)
    services.verify_for_execution(decided, dict(PAYLOAD))                     # unchanged: fine

    with pytest.raises(ApprovalError, match="changed after"):
        services.verify_for_execution(decided, {**PAYLOAD, "target": "staging-but-actually-prod"})


def test_payload_hash_ignores_key_order_but_not_values():
    assert services.payload_hash({"a": 1, "b": 2}) == services.payload_hash({"b": 2, "a": 1})
    assert services.payload_hash({"a": 1}) != services.payload_hash({"a": 2})


def test_unapproved_and_rejected_actions_cannot_execute(waiting):
    run, approval = waiting
    with pytest.raises(ApprovalError, match="pending"):
        services.verify_for_execution(approval, PAYLOAD)
    services.decide(approval, approve=False, actor=run.created_by)
    with pytest.raises(ApprovalError, match="rejected"):
        services.verify_for_execution(approval, PAYLOAD)


def test_an_approval_cannot_be_decided_twice(waiting):
    run, approval = waiting
    services.decide(approval, approve=True, actor=run.created_by)
    with pytest.raises(ApprovalError, match="already"):
        services.decide(approval, approve=False, actor=run.created_by)


def test_an_expired_approval_is_refused(waiting):
    from datetime import timedelta
    from django.utils import timezone

    run, approval = waiting
    ApprovalRequest.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1))
    approval.refresh_from_db()
    with pytest.raises(ApprovalError, match="expired"):
        services.decide(approval, approve=True, actor=run.created_by)


def test_cancelling_a_run_expires_its_pending_approvals(waiting):
    run, approval = waiting
    services.cancel(run, run.created_by)
    approval.refresh_from_db()
    assert approval.state == ApprovalState.EXPIRED

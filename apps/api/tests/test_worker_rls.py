"""Background execution under row-level security, as the unprivileged role.

The Celery task is handed only a run id. It has no request, so nothing has bound
a tenant. These tests run the real task body against the real graph on a
connection that is NOT a superuser.
"""
from __future__ import annotations

import json
import os
import uuid
from decimal import Decimal

import pytest
from django.db import connection

pytestmark = [
    pytest.mark.skipif(connection.vendor != "postgresql", reason="row-level security requires PostgreSQL"),
    pytest.mark.django_db(transaction=True),
]
APP_ROLE = os.environ.get("TEST_APP_ROLE", "sa_app")

PLAN = {"plan": [
    {"id": "t1", "title": "Inspect", "agent": "analyst"},
    {"id": "t2", "title": "API", "agent": "backend", "depends_on": ["t1"], "write_scope": ["api/"]},
    {"id": "t3", "title": "UI", "agent": "frontend", "depends_on": ["t1"], "write_scope": ["web/"]},
]}


class Scripted:
    def __call__(self, *, settings, messages, max_tokens, temperature):
        from orchestration.agents import AGENTS
        system = messages[0]["content"]
        if "lead engineer" in system:
            text = json.dumps(PLAN)
        else:
            text = next(k for k, v in AGENTS.items() if v.prompt == system) + " done"
        return {"text": text, "input_tokens": 100, "output_tokens": 50, "tool_calls": []}


@pytest.fixture
def seeded():
    from identity.models import Membership, Organization, Profile
    from orchestration import services
    from orchestration.models import AgentProfile
    from projects.models import Project
    from providers.crypto import encrypt_secret
    from providers.models import CredentialStatus, ProviderCredential, ProviderModel

    with connection.cursor() as cur:
        cur.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
        cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
        cur.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")

    profile = Profile.objects.create(supabase_user_id=uuid.uuid4(), email="w@x.io")
    org = Organization.objects.create(name="W", slug="w", created_by=profile)
    Membership.objects.create(organization=org, profile=profile, role="owner")
    project = Project.objects.create(organization=org, name="p", slug="p", created_by=profile)
    token, kid = encrypt_secret("sk-live-test-0000000000")
    ProviderCredential.objects.create(organization=org, provider="openai", secret_encrypted=token,
                                      key_id=kid, last4="0000", created_by=profile,
                                      status=CredentialStatus.VALID)
    ProviderModel.objects.create(provider="openai", model_id="gpt-x",
                                 input_cost_per_1m=Decimal("1"), output_cost_per_1m=Decimal("2"))
    AgentProfile.objects.create(organization=org, kind="orchestrator", display_name="Lead",
                                model_provider="openai", model_id="gpt-x")
    run = services.create_run(project=project, profile=profile, objective="Build it")
    return {"run": run, "org": org, "profile": profile}


@pytest.fixture
def unprivileged():
    """Make EVERY connection Django opens connect as the unprivileged role.

    `SET ROLE` only changes one connection, and execute_run() calls
    close_old_connections() on entry, after which Django reconnects as the
    superuser. Worker threads open their own connections too. Both silently
    bypassed RLS in an earlier version of this test. Changing the connection's
    USER setting is the only way to be sure no connection is privileged.
    """
    from django.db import connections

    settings_dict = connections["default"].settings_dict
    original_user = settings_dict.get("USER")
    connections.close_all()
    settings_dict["USER"] = APP_ROLE
    try:
        yield
    finally:
        connections.close_all()
        settings_dict["USER"] = original_user


def test_every_connection_in_this_test_is_unprivileged(seeded, unprivileged):
    """Guard against the false pass: prove the premise before trusting the rest."""
    import threading
    from django.db import connections

    seen = {}

    def probe(label):
        with connections["default"].cursor() as cur:
            cur.execute("select current_user, (select rolbypassrls from pg_roles where rolname=current_user)")
            seen[label] = cur.fetchone()
        connections.close_all()

    probe("main")
    t = threading.Thread(target=probe, args=("thread",))
    t.start(); t.join()
    assert seen["main"] == (APP_ROLE, False), seen
    assert seen["thread"] == (APP_ROLE, False), seen


def test_an_unbound_connection_cannot_see_the_run(seeded, unprivileged):
    from orchestration.models import AgentRun
    assert AgentRun.objects.filter(pk=seeded["run"].id).count() == 0


def test_a_worker_can_complete_a_run_as_the_unprivileged_role(seeded, unprivileged):
    from orchestration.executor import execute_run
    from orchestration.models import RunStatus

    final = execute_run(str(seeded["run"].id), str(seeded["org"].id),
                        str(seeded["profile"].id), transport=Scripted())
    assert final.status == RunStatus.SUCCEEDED, f"{final.status} / {final.error_code}"


def test_a_member_removed_before_execution_is_refused(seeded, unprivileged):
    """Membership can be revoked between enqueue and execution."""
    from core.rls import TenantBindingError
    from identity.models import Membership
    from orchestration.executor import execute_run
    from orchestration.models import AgentRun, RunStatus

    with connection.cursor() as cur:
        cur.execute("RESET ROLE")
    # Revoke as the platform (superuser), then go back to the unprivileged role.
    from django.db import connections
    connections.close_all()
    settings_dict = connections["default"].settings_dict
    settings_dict["USER"] = "postgres"
    Membership.objects.filter(profile=seeded["profile"]).update(is_active=False)
    connections.close_all()
    settings_dict["USER"] = APP_ROLE

    with pytest.raises(TenantBindingError):
        execute_run(str(seeded["run"].id), str(seeded["org"].id), str(seeded["profile"].id),
                    transport=Scripted())

    connections.close_all()
    settings_dict["USER"] = "postgres"
    assert AgentRun.objects.get(pk=seeded["run"].id).status == RunStatus.QUEUED, \
        "a refused run must not have started"
    connections.close_all()
    settings_dict["USER"] = APP_ROLE


def test_a_worker_cannot_run_another_tenants_run(seeded, unprivileged):
    from core.rls import TenantBindingError
    from django.db import connections
    from identity.models import Membership, Organization, Profile
    from orchestration.executor import execute_run

    settings_dict = connections["default"].settings_dict
    connections.close_all(); settings_dict["USER"] = "postgres"
    outsider = Profile.objects.create(supabase_user_id=uuid.uuid4(), email="o@x.io")
    other = Organization.objects.create(name="O", slug="other", created_by=outsider)
    Membership.objects.create(organization=other, profile=outsider, role="owner")
    connections.close_all(); settings_dict["USER"] = APP_ROLE

    # The outsider is a legitimate member of THEIR org, and names the victim's run id.
    with pytest.raises(Exception) as caught:
        execute_run(str(seeded["run"].id), str(other.id), str(outsider.id), transport=Scripted())
    assert "DoesNotExist" in type(caught.value).__name__ or isinstance(caught.value, TenantBindingError)

    connections.close_all(); settings_dict["USER"] = "postgres"
    from orchestration.models import AgentRun, RunStatus
    assert AgentRun.objects.get(pk=seeded["run"].id).status == RunStatus.QUEUED
    connections.close_all(); settings_dict["USER"] = APP_ROLE


def test_parallel_task_threads_are_bound_not_just_lucky(seeded, unprivileged):
    """Both parallel specialists must have recorded steps, which they can only do
    if their own connections were bound to the tenant."""
    from django.db import connections
    from orchestration.executor import execute_run
    from orchestration.models import AgentStep, RunStatus

    final = execute_run(str(seeded["run"].id), str(seeded["org"].id),
                        str(seeded["profile"].id), transport=Scripted())
    assert final.status == RunStatus.SUCCEEDED

    settings_dict = connections["default"].settings_dict
    connections.close_all(); settings_dict["USER"] = "postgres"
    kinds = set(AgentStep.objects.filter(run_id=seeded["run"].id).values_list("agent_kind", flat=True))
    assert {"backend", "frontend"} <= kinds, f"parallel steps missing: {kinds}"
    connections.close_all(); settings_dict["USER"] = APP_ROLE

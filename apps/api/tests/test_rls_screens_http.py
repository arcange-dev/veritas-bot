"""The new screens' endpoints, over HTTP, with EVERY connection as the unprivileged
role. Tests that run as a superuser cannot show an RLS problem (a superuser bypasses
it), so this is the check that matters for production."""
from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest
from django.db import connection, connections
from rest_framework.test import APIClient

pytestmark = [
    pytest.mark.skipif(connection.vendor != "postgresql", reason="row-level security requires PostgreSQL"),
    pytest.mark.django_db(transaction=True),
]
APP_ROLE = os.environ.get("TEST_APP_ROLE", "sa_app")


@pytest.fixture
def seeded():
    from audit.models import AuditLog, Notification
    from billing.models import UsageRecord
    from identity.models import Membership, Organization, Profile
    from orchestration import services
    from projects.models import Deployment, Project, Repository

    with connection.cursor() as cur:
        cur.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
        cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
        cur.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    out = {}
    for label in ("a", "b"):
        profile = Profile.objects.create(supabase_user_id=uuid.uuid4(), email=f"{label}@x.io")
        org = Organization.objects.create(name=label, slug=f"org-{label}", created_by=profile)
        Membership.objects.create(organization=org, profile=profile, role="owner")
        project = Project.objects.create(organization=org, name=f"proj-{label}", slug=label, created_by=profile)
        run = services.create_run(project=project, profile=profile, objective=f"objective for {label}")
        UsageRecord.objects.create(organization=org, run=run, agent_kind="backend", provider="openai", model_id="m",
                                   input_tokens=1, output_tokens=1, cost_usd=Decimal("0.5"))
        Notification.objects.create(organization=org, profile=profile, kind="k", title=f"note {label}")
        AuditLog.objects.create(organization=org, action=f"evt.{label}", actor_type="user")
        Repository.objects.create(project=project, installation_id=100 + len(out), full_name=f"{label}/repo")
        Deployment.objects.create(project=project, status="succeeded", config={"build_log": ["x"]})
        out[label] = {"profile": profile, "org": org, "project": project}
    return out


@pytest.fixture
def unprivileged(seeded):
    settings_dict = connections["default"].settings_dict
    original = settings_dict.get("USER")
    connections.close_all()
    settings_dict["USER"] = APP_ROLE
    yield
    connections.close_all()
    settings_dict["USER"] = original


def client_for(profile):
    c = APIClient(); c.force_authenticate(user=profile); return c


def rows(resp):
    b = resp.json(); return b["results"] if isinstance(b, dict) and "results" in b else b


def test_this_test_really_runs_unprivileged(seeded, unprivileged):
    with connection.cursor() as cur:
        cur.execute("select current_user, (select rolbypassrls from pg_roles where rolname=current_user)")
        assert cur.fetchone() == (APP_ROLE, False)


@pytest.mark.parametrize("path,check", [
    ("dashboard/summary/", lambda b, label: b["project_count"] == 1 and b["recent_runs"][0]["objective"] == f"objective for {label}"
                                            and b["spend_this_month_usd"] == "0.500000"),
    ("notifications/", lambda b, label: [n["title"] for n in b["results"]] == [f"note {label}"]),
    # create_run also writes a real "run.created" audit row, so assert on what matters:
    # my own event is present and the other tenant's is not.
    ("audit/", lambda b, label: {r["action"] for r in b["results"]} == {f"evt.{label}", "run.created"}),
    ("projects/", lambda b, label: [p["name"] for p in b["results"]] == [f"proj-{label}"]),
    ("deployments/", lambda b, label: len(b["results"]) == 1 and b["results"][0]["project_name"] == f"proj-{label}"),
    ("integrations/github/", lambda b, label: [r["full_name"] for r in b["repositories"]] == [f"{label}/repo"]),
])
def test_each_endpoint_returns_only_my_tenant_as_the_unprivileged_role(seeded, unprivileged, path, check):
    for label in ("a", "b"):
        me = seeded[label]
        r = client_for(me["profile"]).get(f"/api/v1/orgs/{me['org'].id}/{path}")
        assert r.status_code == 200, (path, r.status_code, r.content[:200])
        assert check(r.json(), label), (path, label, r.json())


def test_another_tenants_org_id_is_404_for_every_endpoint(seeded, unprivileged):
    a, b = seeded["a"], seeded["b"]
    c = client_for(a["profile"])
    for path in ("dashboard/summary/", "notifications/", "audit/", "projects/", "deployments/", "integrations/github/"):
        assert c.get(f"/api/v1/orgs/{b['org'].id}/{path}").status_code == 404, path


def test_creating_archiving_and_deleting_work_under_rls(seeded, unprivileged):
    a = seeded["a"]
    c = client_for(a["profile"]); base = f"/api/v1/orgs/{a['org'].id}/projects/"
    pid = c.post(base, {"name": "Fresh"}, format="json").json()["id"]
    assert c.post(f"{base}{pid}/archive/").json()["is_archived"] is True
    assert c.delete(f"{base}{pid}/").status_code == 204
    assert c.post(base, {"name": "Fresh"}, format="json").status_code == 201      # slug free again

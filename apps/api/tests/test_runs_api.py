"""Runs and approvals over HTTP: tenancy, roles, state conflicts, enqueue behaviour."""
from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from identity.models import Membership, MembershipRole, Profile
from orchestration import services
from orchestration.models import AgentRun, ApprovalRequest, RunStatus
from projects.models import Project

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def enqueued(monkeypatch):
    """Capture hand-offs to the worker. The view must enqueue, never execute."""
    class Sent(list):
        identities: list

    sent = Sent()
    sent.identities = []

    def capture(run_id, org_id="", profile_id=""):
        sent.append(run_id)
        sent.identities.append((org_id, profile_id))

    monkeypatch.setattr("orchestration.views.enqueue_run", capture)
    return sent


@pytest.fixture
def project(org, profile):
    return Project.objects.create(organization=org, name="Demo", slug="demo", created_by=profile)


def url(org, suffix=""):
    return f"/api/v1/orgs/{org.id}/runs/{suffix}"


def test_create_run_enqueues_and_returns_immediately(api, org, project, enqueued):
    resp = api.post(url(org), {"project": str(project.id), "objective": "Build a todo app"},
                    format="json")
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["status"] == "running"
    assert enqueued == [body["id"]], "the view must hand the run to the worker exactly once"


def test_the_view_never_executes_the_graph_itself(api, org, project, monkeypatch):
    """A request that ran the agent graph would hold a web worker for minutes."""
    called = []
    monkeypatch.setattr("orchestration.executor.execute_run", lambda *a, **k: called.append(1))
    monkeypatch.setattr("orchestration.views.enqueue_run", lambda run_id: None)
    api.post(url(org), {"project": str(project.id), "objective": "Build a todo app"}, format="json")
    assert called == []


@pytest.mark.parametrize("payload", [
    {"objective": "Build a todo app"},                                      # no project
    {"project": "not-a-uuid", "objective": "Build a todo app"},
    {"objective": "ab"},                                                    # too short
])
def test_invalid_create_payloads_are_rejected(api, org, project, enqueued, payload):
    body = {"project": str(project.id), **payload} if "project" not in payload and "objective" in payload and payload["objective"] == "ab" else payload
    resp = api.post(url(org), body, format="json")
    assert resp.status_code == 400
    assert enqueued == []


def test_cost_cap_is_bounded(api, org, project, enqueued):
    for bad in ("0", "-5", "100000"):
        resp = api.post(url(org), {"project": str(project.id), "objective": "Build it",
                                   "cost_cap_usd": bad}, format="json")
        assert resp.status_code == 400, bad
    ok = api.post(url(org), {"project": str(project.id), "objective": "Build it",
                             "cost_cap_usd": "2.50"}, format="json")
    assert ok.status_code == 201
    assert Decimal(ok.json()["cost_cap_usd"]) == Decimal("2.5")


def test_a_project_from_another_tenant_is_a_404(api, org, other_org, enqueued):
    foreign = Project.objects.create(organization=other_org, name="Secret", slug="secret",
                                     created_by=other_org.created_by)
    resp = api.post(url(org), {"project": str(foreign.id), "objective": "Build it"}, format="json")
    assert resp.status_code == 404
    assert AgentRun.objects.count() == 0
    assert enqueued == []


def test_runs_are_invisible_across_tenants(api, org, other_org):
    foreign_project = Project.objects.create(organization=other_org, name="X", slug="x",
                                             created_by=other_org.created_by)
    foreign = services.create_run(project=foreign_project, profile=other_org.created_by,
                                  objective="Their private objective")
    listing = api.get(url(org)).json()
    items = listing["results"] if isinstance(listing, dict) else listing
    assert items == []
    assert api.get(url(org, f"{foreign.id}/")).status_code == 404
    # Even addressing it through the foreign org id is refused: caller is not a member.
    assert api.get(url(other_org, f"{foreign.id}/")).status_code == 404


def test_viewers_can_read_but_not_start_or_control_runs(org, project, enqueued):
    viewer = Profile.objects.create(supabase_user_id="33333333-3333-4333-8333-333333333333",
                                    email="viewer@example.com")
    Membership.objects.create(organization=org, profile=viewer, role=MembershipRole.VIEWER)
    client = APIClient()
    client.force_authenticate(user=viewer)

    run = services.create_run(project=project, profile=org.created_by, objective="Build it")
    services.start(run)

    assert client.get(url(org)).status_code == 200
    assert client.get(url(org, f"{run.id}/")).status_code == 200
    assert client.post(url(org), {"project": str(project.id), "objective": "Build it"},
                       format="json").status_code == 403
    assert client.post(url(org, f"{run.id}/cancel/")).status_code == 403
    run.refresh_from_db()
    assert run.status == RunStatus.RUNNING
    assert enqueued == []


def test_unauthenticated_requests_are_refused(org):
    assert APIClient().get(url(org)).status_code in (401, 403)


def test_runs_cannot_be_edited_or_deleted_through_the_api(api, org, project):
    run = services.create_run(project=project, profile=org.created_by, objective="Build it")
    for method in ("patch", "put", "delete"):
        resp = getattr(api, method)(url(org, f"{run.id}/"), {"status": "succeeded"}, format="json")
        assert resp.status_code == 405, method
    run.refresh_from_db()
    assert run.status == RunStatus.QUEUED


def test_cancel_then_cancel_again_is_a_clean_409(api, org, project, enqueued):
    created = api.post(url(org), {"project": str(project.id), "objective": "Build it"},
                       format="json").json()
    first = api.post(url(org, f"{created['id']}/cancel/"))
    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    second = api.post(url(org, f"{created['id']}/cancel/"))
    assert second.status_code == 409
    assert second.json()["code"] == "invalid_state"


def test_pause_and_resume_via_api(api, org, project, enqueued):
    created = api.post(url(org), {"project": str(project.id), "objective": "Build it"},
                       format="json").json()
    paused = api.post(url(org, f"{created['id']}/pause/"))
    assert paused.json()["status"] == "paused"
    resumed = api.post(url(org, f"{created['id']}/resume/"))
    assert resumed.json()["status"] == "running"
    assert enqueued.count(created["id"]) == 2, "resume must re-enqueue the run"


def test_detail_includes_steps_and_pending_approvals(api, org, project):
    run = services.create_run(project=project, profile=org.created_by, objective="Build it")
    services.start(run)
    run.refresh_from_db()
    services.request_approval(run, action_type="deploy", summary="Deploy v1", payload={"env": "prod"})
    body = api.get(url(org, f"{run.id}/")).json()
    assert "steps" in body
    assert len(body["pending_approvals"]) == 1
    assert body["pending_approvals"][0]["action_type"] == "deploy"


# --- approvals ---------------------------------------------------------------------
@pytest.fixture
def pending(org, project):
    run = services.create_run(project=project, profile=org.created_by, objective="Build it")
    services.start(run)
    run.refresh_from_db()
    return services.request_approval(run, action_type="deploy", summary="Deploy",
                                     payload={"env": "prod"})


def test_approve_via_api(api, org, pending):
    resp = api.post(f"/api/v1/orgs/{org.id}/approvals/{pending.id}/decide/",
                    {"approve": True, "note": "ship it"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["state"] == "approved"


def test_approval_cannot_be_decided_twice_over_http(api, org, pending):
    path = f"/api/v1/orgs/{org.id}/approvals/{pending.id}/decide/"
    assert api.post(path, {"approve": True}, format="json").status_code == 200
    again = api.post(path, {"approve": False}, format="json")
    assert again.status_code == 409


def test_a_missing_approve_flag_is_not_treated_as_yes(api, org, pending):
    resp = api.post(f"/api/v1/orgs/{org.id}/approvals/{pending.id}/decide/", {}, format="json")
    assert resp.status_code == 400
    pending.refresh_from_db()
    assert pending.state == "pending"


def test_another_tenants_approval_is_a_404(api, org, other_org):
    foreign_project = Project.objects.create(organization=other_org, name="X", slug="x",
                                             created_by=other_org.created_by)
    run = services.create_run(project=foreign_project, profile=other_org.created_by,
                              objective="Their objective")
    services.start(run)
    run.refresh_from_db()
    theirs = services.request_approval(run, action_type="deploy", summary="d", payload={})
    resp = api.post(f"/api/v1/orgs/{org.id}/approvals/{theirs.id}/decide/",
                    {"approve": True}, format="json")
    assert resp.status_code == 404
    theirs.refresh_from_db()
    assert theirs.state == "pending"


def test_viewers_cannot_decide_approvals(org, pending):
    viewer = Profile.objects.create(supabase_user_id="44444444-4444-4444-8444-444444444444",
                                    email="v2@example.com")
    Membership.objects.create(organization=org, profile=viewer, role=MembershipRole.VIEWER)
    client = APIClient()
    client.force_authenticate(user=viewer)
    resp = client.post(f"/api/v1/orgs/{org.id}/approvals/{pending.id}/decide/",
                       {"approve": True}, format="json")
    assert resp.status_code == 403
    pending.refresh_from_db()
    assert pending.state == "pending"

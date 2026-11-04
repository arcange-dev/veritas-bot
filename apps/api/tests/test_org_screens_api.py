"""Notifications, audit log, dashboard summary and the project fixes."""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditLog, Notification
from billing.models import UsageRecord
from identity.models import Membership, Profile
from orchestration import services
from projects.models import Project


def client_with_role(org, role):
    p = Profile.objects.create(supabase_user_id=uuid.uuid4(), email=f"{role}-{uuid.uuid4().hex[:6]}@x.io")
    Membership.objects.create(organization=org, profile=p, role=role)
    c = APIClient(); c.force_authenticate(user=p)
    return c, p


def base(org):
    return f"/api/v1/orgs/{org.id}"


def rows(resp):
    body = resp.json()
    return body["results"] if isinstance(body, dict) and "results" in body else body


# ---------------------------------- notifications ----------------------------------
@pytest.fixture
def notes(org, profile):
    other_c, other_p = client_with_role(org, "member")
    mine = [Notification.objects.create(organization=org, profile=profile, kind="run", title=f"mine {i}") for i in range(3)]
    theirs = Notification.objects.create(organization=org, profile=other_p, kind="run", title="theirs")
    return dict(mine=mine, theirs=theirs, other_client=other_c)


def test_you_only_ever_see_your_own_notifications(api, org, notes):
    r = api.get(f"{base(org)}/notifications/")
    assert sorted(n["title"] for n in rows(r)) == ["mine 0", "mine 1", "mine 2"]
    assert r.json()["unread_count"] == 3


def test_unread_filter_and_mark_one_read(api, org, notes):
    first = notes["mine"][0]
    assert api.post(f"{base(org)}/notifications/{first.id}/read/").status_code == 200
    unread = rows(api.get(f"{base(org)}/notifications/?unread=1"))
    assert len(unread) == 2 and str(first.id) not in {n["id"] for n in unread}


def test_marking_someone_elses_notification_is_a_404_and_changes_nothing(api, org, notes):
    r = api.post(f"{base(org)}/notifications/{notes['theirs'].id}/read/")
    assert r.status_code == 404
    notes["theirs"].refresh_from_db()
    assert notes["theirs"].read_at is None


def test_read_all_touches_only_my_rows_and_is_idempotent(api, org, notes):
    assert api.post(f"{base(org)}/notifications/read-all/").json() == {"marked_read": 3}
    assert api.post(f"{base(org)}/notifications/read-all/").json() == {"marked_read": 0}
    notes["theirs"].refresh_from_db()
    assert notes["theirs"].read_at is None


def test_undo_mark_as_read_only_affects_my_notifications(api, org, notes):
    api.post(f"{base(org)}/notifications/read-all/")
    ids = [str(n.id) for n in notes["mine"]] + [str(notes["theirs"].id)]
    assert api.post(f"{base(org)}/notifications/unread/", {"ids": ids}, format="json").json() == {"marked_unread": 3}


@pytest.mark.parametrize("bad", [None, "x", [1, 2], ["a"] * 201])
def test_undo_validates_its_input(api, org, bad):
    assert api.post(f"{base(org)}/notifications/unread/", {"ids": bad}, format="json").status_code == 400


def test_notifications_do_not_cross_organizations(api, org, other_org):
    outsider = other_org.created_by
    Notification.objects.create(organization=other_org, profile=outsider, kind="x", title="foreign")
    assert rows(api.get(f"{base(org)}/notifications/")) == []
    assert api.get(f"{base(other_org)}/notifications/").status_code == 404


# ------------------------------------ audit log ------------------------------------
def test_audit_log_is_admin_only(api, org):
    AuditLog.objects.create(organization=org, action="project.deleted", actor_type="user", ip_hash="secret-hash")
    assert api.get(f"{base(org)}/audit/").status_code == 200
    for role in ("member", "viewer"):
        c, _ = client_with_role(org, role)
        assert c.get(f"{base(org)}/audit/").status_code == 403, role


def test_audit_log_hides_ip_hash_and_filters_by_action(api, org):
    AuditLog.objects.create(organization=org, action="a.one", actor_type="user", ip_hash="deadbeef")
    AuditLog.objects.create(organization=org, action="b.two", actor_type="user")
    body = rows(api.get(f"{base(org)}/audit/?action=a.one"))
    assert [r["action"] for r in body] == ["a.one"]
    assert "ip_hash" not in body[0] and "deadbeef" not in str(body)


def test_audit_log_is_tenant_scoped(api, org, other_org):
    AuditLog.objects.create(organization=other_org, action="theirs.event", actor_type="user")
    assert rows(api.get(f"{base(org)}/audit/")) == []


# --------------------------------- dashboard summary ---------------------------------
def test_dashboard_summary_counts_are_real_and_money_is_an_exact_string(api, org, profile, other_org):
    project = Project.objects.create(organization=org, name="P", slug="p", created_by=profile)
    run = services.create_run(project=project, profile=profile, objective="Build the thing")
    UsageRecord.objects.create(organization=org, run=run, agent_kind="backend", provider="openai", model_id="m",
                               input_tokens=1, output_tokens=1, cost_usd=Decimal("0.100000"))
    UsageRecord.objects.create(organization=org, run=run, agent_kind="backend", provider="openai", model_id="m",
                               input_tokens=1, output_tokens=1, cost_usd=Decimal("0.200000"))
    # Last month and another tenant must both be excluded.
    old = UsageRecord.objects.create(organization=org, run=run, agent_kind="backend", provider="openai", model_id="m",
                                     input_tokens=1, output_tokens=1, cost_usd=Decimal("99"))
    UsageRecord.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=45))
    body = api.get(f"{base(org)}/dashboard/summary/").json()
    assert body["project_count"] == 1
    assert body["active_runs"] == 1 and body["runs_by_status"] == {"queued": 1}
    assert body["spend_this_month_usd"] == "0.300000"          # 0.1 + 0.2 exactly, no float drift
    assert [r["objective"] for r in body["recent_runs"]] == ["Build the thing"]


def test_dashboard_summary_is_zero_not_error_for_an_empty_org(api, org):
    body = api.get(f"{base(org)}/dashboard/summary/").json()
    assert (body["project_count"], body["active_runs"], body["pending_approvals"]) == (0, 0, 0)
    assert body["spend_this_month_usd"] == "0.000000" and body["recent_runs"] == []


def test_dashboard_summary_does_not_leak_across_tenants(api, org, other_org):
    p = Project.objects.create(organization=other_org, name="Theirs", slug="t", created_by=other_org.created_by)
    services.create_run(project=p, profile=other_org.created_by, objective="Their secret objective")
    body = api.get(f"{base(org)}/dashboard/summary/").json()
    assert body["project_count"] == 0 and body["recent_runs"] == []
    assert api.get(f"{base(other_org)}/dashboard/summary/").status_code == 404


# ---------------------------------- project fixes ----------------------------------
def test_a_duplicate_project_name_is_a_400_field_error_not_a_500(api, org):
    url = f"{base(org)}/projects/"
    assert api.post(url, {"name": "Demo"}, format="json").status_code == 201
    r = api.post(url, {"name": "Demo"}, format="json")
    assert r.status_code == 400 and "already exists" in str(r.json())


def test_the_same_name_is_allowed_in_a_different_organization(api, org, other_org):
    api.post(f"{base(org)}/projects/", {"name": "Demo"}, format="json")
    Project.objects.create(organization=other_org, name="Demo", slug="demo", created_by=other_org.created_by)
    assert api.post(f"{base(org)}/projects/", {"name": "Other"}, format="json").status_code == 201


def test_renaming_a_project_never_changes_its_slug(api, org):
    pid = api.post(f"{base(org)}/projects/", {"name": "Demo"}, format="json").json()["id"]
    r = api.patch(f"{base(org)}/projects/{pid}/", {"name": "Totally Renamed"}, format="json")
    assert r.status_code == 200 and r.json()["slug"] == "demo" and r.json()["name"] == "Totally Renamed"


def test_a_name_with_no_usable_characters_is_rejected(api, org):
    assert api.post(f"{base(org)}/projects/", {"name": "!!!"}, format="json").status_code == 400


def test_archive_hides_from_the_default_list_and_is_reversible(api, org):
    pid = api.post(f"{base(org)}/projects/", {"name": "Old"}, format="json").json()["id"]
    arch = api.post(f"{base(org)}/projects/{pid}/archive/").json()
    assert arch["is_archived"] is True and arch["archived_at"]
    assert rows(api.get(f"{base(org)}/projects/")) == []
    assert [p["id"] for p in rows(api.get(f"{base(org)}/projects/?archived=1"))] == [pid]
    assert api.get(f"{base(org)}/projects/{pid}/").status_code == 200       # still reachable by id
    assert api.post(f"{base(org)}/projects/{pid}/unarchive/").json()["is_archived"] is False
    assert [p["id"] for p in rows(api.get(f"{base(org)}/projects/"))] == [pid]


def test_archiving_twice_is_idempotent_and_audited_once(api, org):
    pid = api.post(f"{base(org)}/projects/", {"name": "Old"}, format="json").json()["id"]
    api.post(f"{base(org)}/projects/{pid}/archive/"); api.post(f"{base(org)}/projects/{pid}/archive/")
    assert AuditLog.objects.filter(action="project.archived").count() == 1


def test_only_admins_can_delete_and_it_is_audited(api, org):
    pid = api.post(f"{base(org)}/projects/", {"name": "Doomed"}, format="json").json()["id"]
    member, _ = client_with_role(org, "member")
    assert member.delete(f"{base(org)}/projects/{pid}/").status_code == 403
    assert Project.objects.filter(pk=pid).exists()
    assert api.delete(f"{base(org)}/projects/{pid}/").status_code == 204
    assert not Project.objects.filter(pk=pid).exists()
    assert AuditLog.objects.filter(action="project.deleted", target_id=pid).count() == 1


def test_viewers_cannot_create_or_archive(api, org):
    pid = api.post(f"{base(org)}/projects/", {"name": "Keep"}, format="json").json()["id"]
    viewer, _ = client_with_role(org, "viewer")
    assert viewer.post(f"{base(org)}/projects/", {"name": "New"}, format="json").status_code == 403
    assert viewer.post(f"{base(org)}/projects/{pid}/archive/").status_code == 403
    assert viewer.get(f"{base(org)}/projects/").status_code == 200


def test_another_orgs_project_is_a_404_for_archive_and_delete(api, org, other_org):
    p = Project.objects.create(organization=other_org, name="Theirs", slug="theirs", created_by=other_org.created_by)
    assert api.post(f"{base(org)}/projects/{p.id}/archive/").status_code == 404
    assert api.delete(f"{base(org)}/projects/{p.id}/").status_code == 404
    assert Project.objects.filter(pk=p.id).exists()

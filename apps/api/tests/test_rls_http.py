"""RLS behind real HTTP requests: the database must protect a view whose ORM
filter has been deliberately sabotaged.

This is the test that proves the second wall exists. If tenant isolation relied
on the ORM filter alone, removing the filter would leak. It must not.
"""
from __future__ import annotations

import os
import uuid

import pytest
from django.db import connection
from rest_framework.test import APIClient

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="row-level security requires PostgreSQL"
)
APP_ROLE = os.environ.get("TEST_APP_ROLE", "sa_app")


@pytest.fixture
def two_orgs(transactional_db):
    from identity.models import Membership, Organization, Profile
    from projects.models import Project

    with connection.cursor() as cur:
        cur.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
        cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
        cur.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    out = {}
    for label in ("a", "b"):
        profile = Profile.objects.create(supabase_user_id=uuid.uuid4(), email=f"{label}@x.io")
        org = Organization.objects.create(name=label, slug=f"org-{label}", created_by=profile)
        Membership.objects.create(organization=org, profile=profile, role="owner")
        Project.objects.create(organization=org, name=f"proj-{label}", slug=label, created_by=profile)
        out[label] = {"profile": profile, "org": org}
    return out


@pytest.fixture
def as_unprivileged():
    with connection.cursor() as cur:
        cur.execute(f"SET ROLE {APP_ROLE}")
    yield
    with connection.cursor() as cur:
        cur.execute("RESET ROLE")


def _names(resp):
    body = resp.json()
    rows = body["results"] if isinstance(body, dict) and "results" in body else body
    return sorted(r["name"] for r in rows)


def test_a_normal_request_returns_only_own_projects(two_orgs, as_unprivileged):
    a = two_orgs["a"]
    client = APIClient()
    client.force_authenticate(user=a["profile"])
    resp = client.get(f"/api/v1/orgs/{a['org'].id}/projects/")
    assert resp.status_code == 200
    assert _names(resp) == ["proj-a"]


def test_database_still_isolates_when_the_orm_filter_is_removed(two_orgs, as_unprivileged, monkeypatch):
    """Sabotage for_org() so the ORM returns EVERY tenant's rows. Only RLS stands."""
    import core.tenancy as tenancy
    import projects.views as pviews

    monkeypatch.setattr(tenancy, "for_org", lambda qs, org: qs)
    monkeypatch.setattr(pviews, "for_org", lambda qs, org: qs, raising=False)

    a = two_orgs["a"]
    client = APIClient()
    client.force_authenticate(user=a["profile"])
    resp = client.get(f"/api/v1/orgs/{a['org'].id}/projects/")
    assert resp.status_code == 200
    assert _names(resp) == ["proj-a"], "RLS failed to stop a query with no tenant filter"


def test_without_the_mixin_the_same_sabotage_would_leak(two_orgs, as_unprivileged, monkeypatch):
    """Control experiment: proves the previous test is meaningful.

    Strip the mixin's binding and sabotage the ORM filter. With neither wall in
    place the request sees nothing (RLS fails closed) rather than everything,
    because no tenant is set at all.
    """
    import core.tenancy as tenancy
    import projects.views as pviews
    from core import rls

    monkeypatch.setattr(tenancy, "for_org", lambda qs, org: qs)
    monkeypatch.setattr(pviews, "for_org", lambda qs, org: qs, raising=False)
    monkeypatch.setattr(rls.TenantBoundMixin, "initial",
                        lambda self, request, *a, **k: super(rls.TenantBoundMixin, self).initial(request, *a, **k))

    a = two_orgs["a"]
    client = APIClient()
    client.force_authenticate(user=a["profile"])
    resp = client.get(f"/api/v1/orgs/{a['org'].id}/projects/")
    names = _names(resp) if resp.status_code == 200 else []
    assert "proj-b" not in names, "another tenant's data leaked with no tenant bound"

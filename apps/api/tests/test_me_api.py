"""GET /me/ and POST /me/organizations/: the first thing the UI calls after sign-in."""
from __future__ import annotations

import os
import uuid

import pytest
from django.db import connection, connections
from rest_framework.test import APIClient

from identity.models import Membership, Organization, Profile

APP_ROLE = os.environ.get("TEST_APP_ROLE", "sa_app")


def client(profile):
    c = APIClient(); c.force_authenticate(user=profile); return c


def new_profile(label="x"):
    return Profile.objects.create(supabase_user_id=uuid.uuid4(), email=f"{label}-{uuid.uuid4().hex[:5]}@x.io")


# ------------------------------- behaviour (any database) -------------------------------
@pytest.mark.django_db
def test_me_returns_profile_and_only_my_organizations(profile, org, other_org):
    body = client(profile).get("/api/v1/me/").json()
    assert body["profile"]["email"] == profile.email and body["profile"]["onboarded"] is False
    assert [o["id"] for o in body["organizations"]] == [str(org.id)]
    assert body["organizations"][0]["role"] == "owner" and body["organizations"][0]["name"] == "Acme"
    assert "Globex" not in str(body)


@pytest.mark.django_db
def test_a_brand_new_user_gets_an_empty_list_not_an_error():
    body = client(new_profile()).get("/api/v1/me/").json()
    assert body["organizations"] == []


@pytest.mark.django_db
def test_inactive_memberships_are_not_listed(profile, org):
    Membership.objects.filter(organization=org, profile=profile).update(is_active=False)
    assert client(profile).get("/api/v1/me/").json()["organizations"] == []


@pytest.mark.django_db
def test_me_requires_authentication():
    assert APIClient().get("/api/v1/me/").status_code == 401
    assert APIClient().post("/api/v1/me/organizations/", {"name": "X Co"}, format="json").status_code == 401


@pytest.mark.django_db
def test_creating_a_workspace_makes_me_the_owner_atomically():
    p = new_profile()
    r = client(p).post("/api/v1/me/organizations/", {"name": "  Orbit   Commerce "}, format="json")
    assert r.status_code == 201
    orgs = r.json()["organizations"]
    assert [(o["name"], o["role"], o["slug"]) for o in orgs] == [("Orbit Commerce", "owner", "orbit-commerce")]
    assert Membership.objects.filter(profile=p, role="owner").count() == 1


@pytest.mark.django_db
def test_two_people_choosing_the_same_name_get_different_addresses():
    a, b = new_profile("a"), new_profile("b")
    sa = client(a).post("/api/v1/me/organizations/", {"name": "Acme Labs"}, format="json").json()["organizations"][0]["slug"]
    sb = client(b).post("/api/v1/me/organizations/", {"name": "Acme Labs"}, format="json").json()["organizations"][0]["slug"]
    assert sa == "acme-labs" and sb != sa and sb.startswith("acme-labs-")
    assert Organization.objects.count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["", " ", "x", "a" * 121, None, 5])
def test_bad_names_are_rejected_and_create_nothing(name):
    p = new_profile()
    assert client(p).post("/api/v1/me/organizations/", {"name": name}, format="json").status_code == 400
    assert Organization.objects.count() == 0


@pytest.mark.django_db
def test_a_name_with_no_letters_still_gets_a_valid_address():
    r = client(new_profile()).post("/api/v1/me/organizations/", {"name": "!!!???"}, format="json")
    assert r.status_code == 201 and r.json()["organizations"][0]["slug"].startswith("workspace")


@pytest.mark.django_db
def test_a_user_cannot_own_unbounded_workspaces():
    p = new_profile()
    c = client(p)
    for i in range(5):
        assert c.post("/api/v1/me/organizations/", {"name": f"Space {i}"}, format="json").status_code == 201
    r = c.post("/api/v1/me/organizations/", {"name": "One too many"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "workspace_limit"
    assert Organization.objects.count() == 5


@pytest.mark.django_db
def test_the_created_workspace_is_immediately_usable(monkeypatch):
    p = new_profile(); c = client(p)
    oid = c.post("/api/v1/me/organizations/", {"name": "Fresh Start"}, format="json").json()["organizations"][0]["id"]
    assert c.get(f"/api/v1/orgs/{oid}/dashboard/summary/").status_code == 200
    assert c.post(f"/api/v1/orgs/{oid}/projects/", {"name": "First"}, format="json").status_code == 201


# --------------------- the real check: as the unprivileged role ---------------------
pg = pytest.mark.skipif(connection.vendor != "postgresql", reason="row-level security requires PostgreSQL")


@pytest.fixture
def unprivileged(transactional_db):
    with connection.cursor() as cur:
        cur.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
        cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
        cur.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    s = connections["default"].settings_dict
    original = s.get("USER"); connections.close_all(); s["USER"] = APP_ROLE
    yield
    connections.close_all(); s["USER"] = original


@pg
def test_rls_me_lists_my_orgs_but_not_anyone_elses(unprivileged):
    connections.close_all(); s = connections["default"].settings_dict; s["USER"] = "postgres"
    a, b = new_profile("a"), new_profile("b")
    oa = Organization.objects.create(name="Alpha", slug="alpha", created_by=a)
    ob = Organization.objects.create(name="Bravo", slug="bravo", created_by=b)
    Membership.objects.create(organization=oa, profile=a, role="admin")
    Membership.objects.create(organization=ob, profile=b, role="owner")
    connections.close_all(); s["USER"] = APP_ROLE

    got_a = client(a).get("/api/v1/me/").json()["organizations"]
    got_b = client(b).get("/api/v1/me/").json()["organizations"]
    assert [(o["name"], o["role"]) for o in got_a] == [("Alpha", "admin")]
    assert [(o["name"], o["role"]) for o in got_b] == [("Bravo", "owner")]


@pg
def test_rls_creating_a_workspace_works_as_the_unprivileged_role(unprivileged):
    connections.close_all(); s = connections["default"].settings_dict; s["USER"] = "postgres"
    p = new_profile(); connections.close_all(); s["USER"] = APP_ROLE
    r = client(p).post("/api/v1/me/organizations/", {"name": "Created Under RLS"}, format="json")
    assert r.status_code == 201, r.content[:300]
    oid = r.json()["organizations"][0]["id"]
    assert client(p).get(f"/api/v1/orgs/{oid}/dashboard/summary/").status_code == 200


@pg
def test_rls_cannot_insert_an_org_for_a_tenant_that_is_not_bound(unprivileged):
    """The org insert policy must still refuse a row whose id is not the bound org."""
    from django.db.utils import DatabaseError
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('app.current_org', %s, false)", [str(uuid.uuid4())])
        with pytest.raises(DatabaseError, match="row-level security"):
            cur.execute("INSERT INTO identity_organization (id, created_at, updated_at, name, slug, plan, "
                        "monthly_spend_cap_usd, max_task_cost_usd, is_active) "
                        "VALUES (%s, now(), now(), 'Evil', 'evil', 'free', 50, 5, true)", [uuid.uuid4()])


@pg
def test_rls_a_stranger_cannot_read_an_organization_that_other_people_belong_to(unprivileged):
    """The policy must tie the membership to THE CALLER. With a policy that only asked
    'does anyone have an active membership here?', every organization with any member
    would be readable by everyone, and the per-user tests above would not notice
    because each person only lists their own."""
    connections.close_all(); s = connections["default"].settings_dict; s["USER"] = "postgres"
    member, stranger = new_profile("member"), new_profile("stranger")
    org = Organization.objects.create(name="Private Co", slug="private-co", created_by=member)
    Membership.objects.create(organization=org, profile=member, role="owner")
    connections.close_all(); s["USER"] = APP_ROLE

    assert client(stranger).get("/api/v1/me/").json()["organizations"] == []
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('app.current_profile', %s, false)", [str(stranger.pk)])
        cur.execute("SELECT count(*) FROM identity_organization")
        assert cur.fetchone()[0] == 0, "a stranger can read an organization they do not belong to"
        cur.execute("SELECT set_config('app.current_profile', %s, false)", [str(member.pk)])
        cur.execute("SELECT count(*) FROM identity_organization")
        assert cur.fetchone()[0] == 1


@pg
def test_rls_org_policy_holds_on_its_own_even_if_the_membership_policy_is_relaxed(unprivileged):
    """Two independent walls. The membership policy hides other people's membership rows, so
    the organization policy's subquery already finds nothing for a stranger. The organization
    policy ALSO ties the membership to the caller, so it stays safe if the membership policy
    is ever loosened (for example to let admins list teammates). This loosens the first wall
    inside the test transaction and proves the second still holds."""
    connections.close_all(); s = connections["default"].settings_dict; s["USER"] = "postgres"
    member, stranger = new_profile("member"), new_profile("stranger")
    org = Organization.objects.create(name="Private Co", slug="private-co", created_by=member)
    Membership.objects.create(organization=org, profile=member, role="owner")
    with connection.cursor() as cur:
        cur.execute("DROP POLICY IF EXISTS membership_self_read ON identity_membership")
        cur.execute("CREATE POLICY membership_self_read ON identity_membership FOR SELECT USING (true)")
    connections.close_all(); s["USER"] = APP_ROLE
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT set_config('app.current_profile', %s, false)", [str(stranger.pk)])
            cur.execute("SELECT count(*) FROM identity_membership")
            assert cur.fetchone()[0] >= 1, "precondition: the first wall really is open"
            cur.execute("SELECT count(*) FROM identity_organization")
            assert cur.fetchone()[0] == 0, "organization policy leaked once the membership policy was relaxed"
    finally:
        connections.close_all(); s["USER"] = "postgres"
        with connection.cursor() as cur:
            cur.execute("DROP POLICY IF EXISTS membership_self_read ON identity_membership")
            cur.execute("CREATE POLICY membership_self_read ON identity_membership FOR SELECT USING "
                        "(profile_id = app_current_profile())")
        connections.close_all(); s["USER"] = APP_ROLE

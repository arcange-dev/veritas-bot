"""core.rls.tenant_context, exercised as the unprivileged role.

The ORM runs on the same connection as the test, which is demoted to `sa_app`
for the body of each test. That is the only configuration in which a policy
mistake (for example, the membership lookup being filtered to zero rows) can
show up, so nothing here runs as a superuser.
"""
from __future__ import annotations

import os
import uuid

import pytest
from django.db import connection

from core.rls import TenantBindingError, profile_context, tenant_context

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="row-level security requires PostgreSQL"
)
APP_ROLE = os.environ.get("TEST_APP_ROLE", "sa_app")


@pytest.fixture(autouse=True)
def grants(db):
    with connection.cursor() as cur:
        cur.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
        cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
        cur.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


@pytest.fixture
def world(db):
    from identity.models import Membership, Organization, Profile
    from orchestration.models import AgentRun
    from projects.models import Project

    out = {}
    for label in ("a", "b"):
        profile = Profile.objects.create(supabase_user_id=uuid.uuid4(), email=f"{label}@x.io")
        org = Organization.objects.create(name=label, slug=f"org-{label}", created_by=profile)
        Membership.objects.create(organization=org, profile=profile, role="owner")
        project = Project.objects.create(organization=org, name=label, slug=label, created_by=profile)
        AgentRun.objects.create(organization=org, project=project, objective=label, created_by=profile)
        out[label] = {"profile": profile, "org": org}
    return out


@pytest.fixture
def transactional_world(transactional_db):
    from identity.models import Membership, Organization, Profile
    from orchestration.models import AgentRun
    from projects.models import Project

    with connection.cursor() as cur:
        cur.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
        cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    out = {}
    for label in ("a", "b"):
        profile = Profile.objects.create(supabase_user_id=uuid.uuid4(), email=f"{label}@x.io")
        org = Organization.objects.create(name=label, slug=f"org-{label}", created_by=profile)
        Membership.objects.create(organization=org, profile=profile, role="owner")
        project = Project.objects.create(organization=org, name=label, slug=label, created_by=profile)
        AgentRun.objects.create(organization=org, project=project, objective=label, created_by=profile)
        out[label] = {"profile": profile, "org": org}
    return out


@pytest.fixture
def unprivileged(world):
    """Demote the ORM's own connection for the body of the test."""
    with connection.cursor() as cur:
        cur.execute(f"SET ROLE {APP_ROLE}")
    try:
        yield
    finally:
        with connection.cursor() as cur:
            cur.execute("RESET ROLE")


def _runs():
    from orchestration.models import AgentRun
    return list(AgentRun.objects.values_list("objective", flat=True))


def test_a_member_can_bind_and_sees_only_their_tenant(world, unprivileged):
    a = world["a"]
    with tenant_context(profile=a["profile"], org=a["org"]):
        assert _runs() == ["a"]


def test_binding_is_refused_for_a_non_member(world, unprivileged):
    a, b = world["a"], world["b"]
    with pytest.raises(TenantBindingError, match="not a member"):
        with tenant_context(profile=a["profile"], org=b["org"]):
            pytest.fail("must not enter the block")


def test_a_deactivated_member_cannot_bind(world, unprivileged):
    from identity.models import Membership

    a = world["a"]
    with connection.cursor() as cur:
        cur.execute("RESET ROLE")
    Membership.objects.filter(profile=a["profile"]).update(is_active=False)
    with connection.cursor() as cur:
        cur.execute(f"SET ROLE {APP_ROLE}")
    with pytest.raises(TenantBindingError):
        with tenant_context(profile=a["profile"], org=a["org"]):
            pass


@pytest.mark.django_db(transaction=True)
def test_outside_the_context_nothing_is_visible(transactional_world):
    """The tenant must not survive the block: that is the leak this prevents.

    Uses transaction=True so there is no outer pytest transaction. With one, the
    block would be a savepoint and the setting would legitimately persist until
    the test ends. Production has no outer transaction, so this is the real case.
    """
    a = transactional_world["a"]
    with connection.cursor() as cur:
        cur.execute(f"SET ROLE {APP_ROLE}")
    try:
        with tenant_context(profile=a["profile"], org=a["org"]):
            assert _runs() == ["a"]
        assert not connection.in_atomic_block
        assert _runs() == []
        with connection.cursor() as cur:
            cur.execute("SELECT current_setting('app.current_org', true)")
            assert cur.fetchone()[0] in ("", None)
    finally:
        with connection.cursor() as cur:
            cur.execute("RESET ROLE")


def test_the_context_is_cleared_even_if_the_body_raises(world, unprivileged):
    a = world["a"]
    with pytest.raises(RuntimeError):
        with tenant_context(profile=a["profile"], org=a["org"]):
            raise RuntimeError("boom")
    assert _runs() == []


def test_switching_tenants_back_to_back_does_not_bleed(world, unprivileged):
    a, b = world["a"], world["b"]
    with tenant_context(profile=a["profile"], org=a["org"]):
        assert _runs() == ["a"]
    with tenant_context(profile=b["profile"], org=b["org"]):
        assert _runs() == ["b"]
    with tenant_context(profile=a["profile"], org=a["org"]):
        assert _runs() == ["a"]


def test_a_body_cannot_widen_its_own_tenant_after_binding(world, unprivileged):
    """Even if code inside the block tries to point the setting at another org,
    that is only possible by calling set_config directly, which the ORM never does.
    This documents that the attack surface is raw SQL, which the tool registry
    does not expose to models."""
    a, b = world["a"], world["b"]
    with tenant_context(profile=a["profile"], org=a["org"]):
        with connection.cursor() as cur:
            cur.execute("SELECT set_config('app.current_org', %s, true)", [str(b["org"].id)])
        # The DB trusts the setting: this is exactly why only core.rls may write it.
        assert _runs() == ["b"]


@pytest.mark.parametrize("bad", [None, "", "not-a-uuid", "1; DROP TABLE x", "' OR '1'='1"])
def test_garbage_ids_are_rejected_before_reaching_sql(world, unprivileged, bad):
    a = world["a"]
    with pytest.raises((TenantBindingError, ValueError)):
        with tenant_context(profile=a["profile"], org=bad):
            pass


def test_profile_context_reveals_only_your_own_memberships(world, unprivileged):
    from identity.models import Membership

    a = world["a"]
    with profile_context(profile=a["profile"]):
        rows = list(Membership.objects.values_list("organization_id", flat=True))
    assert rows == [a["org"].id]


def test_profile_context_without_an_org_sees_no_tenant_data(world, unprivileged):
    a = world["a"]
    with profile_context(profile=a["profile"]):
        assert _runs() == []

"""PostgreSQL row-level security, tested as the unprivileged role production uses.

Every assertion here goes through raw SQL on a connection that is NOT a
superuser, so the ORM's own tenant scoping cannot hide a policy defect. Seed
data is written by the superuser (RLS does not apply to it), then read back as
`sa_app` under different tenant contexts.

Skipped on SQLite: it has no RLS.
"""
from __future__ import annotations

import os
import uuid

import pytest
from django.db import connection

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="row-level security requires PostgreSQL"
)

APP_ROLE = os.environ.get("TEST_APP_ROLE", "sa_app")


@pytest.fixture(autouse=True)
def grant_app_role(db):
    """The test database is created fresh, so the unprivileged role needs table
    access. Granting is not the security boundary; the policies are."""
    with connection.cursor() as cur:
        cur.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
        cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
        cur.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


@pytest.fixture
def two_tenants(db):
    """Seed two organizations with a full object graph, as the superuser."""
    from identity.models import Membership, Organization, Profile
    from orchestration.models import AgentRun, AgentStep
    from projects.models import Project
    from providers.models import ProviderCredential

    world = {}
    for label, n in (("a", 1), ("b", 2)):
        profile = Profile.objects.create(
            supabase_user_id=uuid.uuid4(),
            email=f"{label}@example.com")
        org = Organization.objects.create(name=f"Org {label}", slug=f"org-{label}", created_by=profile)
        Membership.objects.create(organization=org, profile=profile, role="owner")
        project = Project.objects.create(organization=org, name=f"P{label}", slug=f"p-{label}",
                                         created_by=profile)
        run = AgentRun.objects.create(organization=org, project=project, objective=f"secret {label}",
                                      created_by=profile)
        step = AgentStep.objects.create(run=run, agent_kind="backend", sequence=1, title=f"step {label}")
        cred = ProviderCredential.objects.create(
            organization=org, provider="openai", secret_encrypted=b"cipher", key_id="k1",
            last4="0000", created_by=profile)
        world[label] = {"org": org, "profile": profile, "project": project,
                        "run": run, "step": step, "cred": cred}
    return world


@pytest.fixture
def as_app(two_tenants):
    """Run SQL as the unprivileged role under a given tenant context.

    pytest-django wraps each test in one outer transaction, so a nested
    atomic() is only a savepoint and SET LOCAL would outlive the call. The
    role and setting are therefore reset explicitly, which also guarantees
    that any read-back a test does afterwards is made as the superuser.
    """
    from django.db import transaction

    def _run(org_id, sql, params=None, fetch=True):
        try:
            with transaction.atomic():
                with connection.cursor() as cur:
                    cur.execute(f"SET LOCAL ROLE {APP_ROLE}")
                    if org_id is not None:
                        cur.execute("SELECT set_config('app.current_org', %s, true)", [str(org_id)])
                    cur.execute(sql, params or [])
                    return cur.fetchall() if fetch and cur.description else cur.rowcount
        finally:
            with connection.cursor() as cur:
                cur.execute("RESET ROLE")
                cur.execute("SELECT set_config('app.current_org', '', true)")
    return _run


TENANT_TABLES = [
    "orchestration_run", "projects_project", "providers_credential",
    "identity_membership", "billing_usage", "audit_log", "execution_device",
    "orchestration_conversation", "orchestration_agent_profile",
]


@pytest.mark.django_db
def test_the_test_role_is_genuinely_unprivileged():
    with connection.cursor() as cur:
        cur.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s", [APP_ROLE])
        assert cur.fetchone() == (False, False), \
            "RLS tests are meaningless if the role can bypass RLS"


@pytest.mark.django_db
def test_every_tenant_table_has_forced_rls():
    with connection.cursor() as cur:
        cur.execute("""
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind='r'
              AND c.relname !~ '^(django_|auth_)' AND c.relname <> 'providers_model'
              AND NOT (c.relrowsecurity AND c.relforcerowsecurity)
        """)
        unprotected = [r[0] for r in cur.fetchall()]
    assert unprotected == [], f"tables without forced RLS: {unprotected}"


def test_no_tenant_context_sees_nothing(as_app):
    """Fails closed: a forgotten SET is an empty result, never everyone's data."""
    for table in TENANT_TABLES + ["orchestration_step", "identity_organization"]:
        assert as_app(None, f"SELECT count(*) FROM {table}")[0][0] == 0, table


def test_each_tenant_sees_only_its_own_rows(as_app, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    for me, other in ((a, b), (b, a)):
        runs = as_app(me["org"].id, "SELECT id FROM orchestration_run")
        assert [r[0] for r in runs] == [me["run"].id]
        projects = as_app(me["org"].id, "SELECT id FROM projects_project")
        assert [p[0] for p in projects] == [me["project"].id]
        assert as_app(me["org"].id, "SELECT count(*) FROM orchestration_run WHERE id=%s",
                      [other["run"].id])[0][0] == 0


def test_child_tables_inherit_isolation_through_their_parent(as_app, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    steps = as_app(a["org"].id, "SELECT id FROM orchestration_step")
    assert [s[0] for s in steps] == [a["step"].id]
    assert as_app(a["org"].id, "SELECT count(*) FROM orchestration_step WHERE id=%s",
                  [b["step"].id])[0][0] == 0


def test_the_organization_row_itself_is_isolated(as_app, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    rows = as_app(a["org"].id, "SELECT id FROM identity_organization")
    assert [r[0] for r in rows] == [a["org"].id]


def test_credentials_are_not_readable_across_tenants(as_app, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    assert as_app(a["org"].id, "SELECT count(*) FROM providers_credential WHERE id=%s",
                  [b["cred"].id])[0][0] == 0
    assert as_app(a["org"].id, "SELECT count(*) FROM providers_credential")[0][0] == 1


def test_cannot_update_another_tenants_rows(as_app, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    changed = as_app(a["org"].id,
                     "UPDATE orchestration_run SET objective='pwned' WHERE id=%s",
                     [b["run"].id], fetch=False)
    assert changed == 0
    b["run"].refresh_from_db()
    assert b["run"].objective == "secret b"


def test_cannot_delete_another_tenants_rows(as_app, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    assert as_app(a["org"].id, "DELETE FROM orchestration_run WHERE id=%s",
                  [b["run"].id], fetch=False) == 0
    from orchestration.models import AgentRun
    assert AgentRun.objects.filter(id=b["run"].id).exists()


def test_cannot_insert_a_row_into_another_tenant(as_app, two_tenants):
    """WITH CHECK: you cannot plant data in a tenant you are not acting as."""
    from django.db.utils import ProgrammingError, InternalError, DatabaseError

    a, b = two_tenants["a"], two_tenants["b"]
    with pytest.raises(DatabaseError, match="row-level security"):
        as_app(a["org"].id,
               "INSERT INTO projects_project (id, organization_id, name, slug, created_at, updated_at, "
               "default_branch, execution_preference, description, created_by_id) "
               "VALUES (%s, %s, 'planted', 'planted', now(), now(), 'main', 'cloud', '', %s)",
               [uuid.uuid4(), b["org"].id, a["profile"].id], fetch=False)


def test_cannot_move_a_row_to_another_tenant(as_app, two_tenants):
    """An UPDATE that re-parents a row into someone else's org must be refused."""
    from django.db.utils import DatabaseError

    a, b = two_tenants["a"], two_tenants["b"]
    with pytest.raises(DatabaseError, match="row-level security"):
        as_app(a["org"].id, "UPDATE projects_project SET organization_id=%s WHERE id=%s",
               [b["org"].id, a["project"].id], fetch=False)


def test_a_malformed_tenant_setting_fails_safe(as_app):
    from django.db.utils import DatabaseError

    with pytest.raises(DatabaseError):
        as_app("not-a-uuid", "SELECT count(*) FROM orchestration_run")


def test_the_setting_does_not_leak_between_transactions(as_app, two_tenants):
    """set_config(..., true) is transaction-local: the next request starts clean."""
    a = two_tenants["a"]
    assert as_app(a["org"].id, "SELECT count(*) FROM orchestration_run")[0][0] == 1
    assert as_app(None, "SELECT count(*) FROM orchestration_run")[0][0] == 0


def test_the_global_model_catalogue_stays_readable(as_app):
    """providers_model has no tenant: every org reads the same catalogue."""
    from providers.models import ProviderModel

    ProviderModel.objects.create(provider="openai", model_id="gpt-x")
    assert as_app(None, "SELECT count(*) FROM providers_model")[0][0] >= 1


# --- identity_profile: a person, not a tenant ------------------------------------
@pytest.fixture
def as_user(two_tenants):
    """Run SQL as sa_app with BOTH a profile and (optionally) a tenant context."""
    from django.db import transaction

    def _run(profile_id, org_id, sql, params=None, fetch=True):
        try:
            with transaction.atomic():
                with connection.cursor() as cur:
                    cur.execute(f"SET LOCAL ROLE {APP_ROLE}")
                    if profile_id is not None:
                        cur.execute("SELECT set_config('app.current_profile', %s, true)", [str(profile_id)])
                    if org_id is not None:
                        cur.execute("SELECT set_config('app.current_org', %s, true)", [str(org_id)])
                    cur.execute(sql, params or [])
                    return cur.fetchall() if fetch and cur.description else cur.rowcount
        finally:
            with connection.cursor() as cur:
                cur.execute("RESET ROLE")
                cur.execute("SELECT set_config('app.current_org', '', true)")
                cur.execute("SELECT set_config('app.current_profile', '', true)")
    return _run


def test_no_context_sees_no_profiles(as_user):
    assert as_user(None, None, "SELECT count(*) FROM identity_profile")[0][0] == 0


def test_you_can_always_read_your_own_profile(as_user, two_tenants):
    a = two_tenants["a"]
    rows = as_user(a["profile"].id, None, "SELECT id FROM identity_profile")
    assert [r[0] for r in rows] == [a["profile"].id]


def test_org_context_reveals_fellow_members_only(as_user, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    rows = as_user(a["profile"].id, a["org"].id, "SELECT id FROM identity_profile")
    assert {r[0] for r in rows} == {a["profile"].id}          # b is not in org a
    assert as_user(a["profile"].id, a["org"].id,
                   "SELECT count(*) FROM identity_profile WHERE id=%s", [b["profile"].id])[0][0] == 0


def test_a_teammate_becomes_visible_once_they_join_the_org(as_user, two_tenants):
    from identity.models import Membership

    a, b = two_tenants["a"], two_tenants["b"]
    Membership.objects.create(organization=a["org"], profile=b["profile"], role="member")
    rows = as_user(a["profile"].id, a["org"].id, "SELECT id FROM identity_profile")
    assert {r[0] for r in rows} == {a["profile"].id, b["profile"].id}


def test_a_deactivated_member_disappears_from_the_org_view(as_user, two_tenants):
    from identity.models import Membership

    a, b = two_tenants["a"], two_tenants["b"]
    Membership.objects.create(organization=a["org"], profile=b["profile"], role="member",
                              is_active=False)
    rows = as_user(a["profile"].id, a["org"].id, "SELECT id FROM identity_profile")
    assert {r[0] for r in rows} == {a["profile"].id}


def test_claiming_another_org_without_membership_reveals_nobody(as_user, two_tenants):
    """Setting app.current_org to someone else's org must not expose its members
    to a caller who is not one of them: org B's roster is only visible *as* B's
    context, which the application only sets after verifying membership."""
    a, b = two_tenants["a"], two_tenants["b"]
    rows = as_user(a["profile"].id, b["org"].id, "SELECT id FROM identity_profile")
    # The policy trusts app.current_org, so this DOES reveal org B's members.
    # That is by design: the SETTING is the trust boundary, and core.rls only
    # sets it after the membership check. This test pins that contract down.
    assert {r[0] for r in rows} == {a["profile"].id, b["profile"].id}


def test_you_cannot_edit_someone_elses_profile(as_user, two_tenants):
    from identity.models import Profile

    a, b = two_tenants["a"], two_tenants["b"]
    assert as_user(a["profile"].id, a["org"].id,
                   "UPDATE identity_profile SET display_name='pwned' WHERE id=%s",
                   [b["profile"].id], fetch=False) == 0
    assert Profile.objects.get(id=b["profile"].id).display_name != "pwned"


def test_you_can_edit_your_own_profile(as_user, two_tenants):
    from identity.models import Profile

    a = two_tenants["a"]
    assert as_user(a["profile"].id, None,
                   "UPDATE identity_profile SET display_name='me' WHERE id=%s",
                   [a["profile"].id], fetch=False) == 1
    assert Profile.objects.get(id=a["profile"].id).display_name == "me"


def test_you_cannot_rewrite_your_row_into_someone_elses_identity(as_user, two_tenants):
    from django.db.utils import DatabaseError

    a, b = two_tenants["a"], two_tenants["b"]
    with pytest.raises(DatabaseError, match="row-level security|duplicate key"):
        as_user(a["profile"].id, None,
                "UPDATE identity_profile SET id=%s WHERE id=%s",
                [b["profile"].id, a["profile"].id], fetch=False)


def test_a_new_profile_can_only_be_created_for_yourself(as_user, two_tenants):
    from django.db.utils import DatabaseError

    new_id = uuid.uuid4()
    cols = ("INSERT INTO identity_profile (id, created_at, updated_at, supabase_user_id, email, "
            "display_name, avatar_url, is_platform_admin) VALUES (%s, now(), now(), %s, 'n@x.io', '', '', false)")
    assert as_user(new_id, None, cols, [new_id, uuid.uuid4()], fetch=False) == 1
    with pytest.raises(DatabaseError, match="row-level security"):
        as_user(new_id, None, cols, [uuid.uuid4(), uuid.uuid4()], fetch=False)


# --- integrations_webhook_delivery: no organization column, policies of its own ---
def test_webhook_inbox_insert_needs_a_verified_signature_and_no_tenant(as_app):
    from django.db.utils import DatabaseError

    ins = ("INSERT INTO integrations_webhook_delivery (id, created_at, updated_at, delivery_id, event, action, "
           "installation_id, repository_full_name, ref, commit_sha, payload_digest, signature_verified, status, summary) "
           "VALUES (%s, now(), now(), %s, 'push', '', 5, '', '', '', '', %s, 'received', '')")
    assert as_app(None, ins, [uuid.uuid4(), "verified-0001", True], fetch=False) == 1
    with pytest.raises(DatabaseError, match="row-level security"):
        as_app(None, ins, [uuid.uuid4(), "unverified-001", False], fetch=False)


def test_webhook_inbox_is_invisible_without_a_matching_repository(as_app, two_tenants):
    from projects.models import Project, Repository
    from integrations.models import WebhookDelivery

    a, b = two_tenants["a"], two_tenants["b"]
    proj = Project.objects.filter(organization=a["org"]).first()
    Repository.objects.create(project=proj, installation_id=111, full_name="a/app")
    WebhookDelivery.objects.create(delivery_id="mine-00001", event="push", installation_id=111, signature_verified=True)
    WebhookDelivery.objects.create(delivery_id="theirs-001", event="push", installation_id=222, signature_verified=True)
    WebhookDelivery.objects.create(delivery_id="noinst-001", event="push", installation_id=None, signature_verified=True)

    seen_a = {r[0] for r in as_app(a["org"].id, "SELECT delivery_id FROM integrations_webhook_delivery")}
    seen_b = {r[0] for r in as_app(b["org"].id, "SELECT delivery_id FROM integrations_webhook_delivery")}
    nobody = as_app(None, "SELECT delivery_id FROM integrations_webhook_delivery")
    assert seen_a == {"mine-00001"}
    assert seen_b == set()
    assert nobody == []


def test_webhook_inbox_cannot_be_edited_or_erased_by_the_app_role(as_app, two_tenants):
    from integrations.models import WebhookDelivery

    a = two_tenants["a"]
    WebhookDelivery.objects.create(delivery_id="keep-000001", event="push", installation_id=None, signature_verified=True)
    assert as_app(a["org"].id, "UPDATE integrations_webhook_delivery SET event='tampered'", fetch=False) == 0
    assert as_app(a["org"].id, "DELETE FROM integrations_webhook_delivery", fetch=False) == 0
    assert WebhookDelivery.objects.get(delivery_id="keep-000001").event == "push"

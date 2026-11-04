"""PostgreSQL row-level security: the second wall behind the ORM scoping layer.

Why this exists: tenant isolation otherwise rests on every query remembering to
filter by organization. One forgotten `.filter()` is a cross-tenant leak. RLS
makes the database refuse, regardless of what the application code does.

Mechanics
---------
* The application sets `app.current_org` per transaction (see core.rls).
* `app_current_org()` reads it and returns NULL when unset. NULL never equals
  anything, so an unset context sees ZERO rows: it fails closed.
* FORCE ROW LEVEL SECURITY applies the policies to the table owner as well.
  Without it the role that owns the tables would bypass every policy.
* Tables without an organization column reach their tenant through a parent;
  policies use an EXISTS subquery on that chain.
* Superusers and roles with BYPASSRLS ignore RLS entirely. Production must
  connect as a plain role (documented in docs/security/RLS.md).

SQLite has no RLS, so this migration is a no-op there; the ORM layer remains
the only wall on that backend, which is acceptable for local development only.
"""
from django.db import migrations

# table -> SQL predicate that must hold for a row to be visible/writable.
DIRECT = [
    "audit_log", "audit_notification", "billing_usage", "execution_device",
    "execution_pairing_code", "identity_invitation", "identity_membership",
    "orchestration_agent_profile", "orchestration_conversation", "orchestration_run",
    "projects_project", "providers_credential",
]

VIA_PARENT = {
    "orchestration_step": "EXISTS (SELECT 1 FROM orchestration_run p WHERE p.id = run_id)",
    "orchestration_approval": "EXISTS (SELECT 1 FROM orchestration_run p WHERE p.id = run_id)",
    "tools_invocation": "EXISTS (SELECT 1 FROM orchestration_run p WHERE p.id = run_id)",
    "orchestration_message": "EXISTS (SELECT 1 FROM orchestration_conversation p WHERE p.id = conversation_id)",
    "projects_repository": "EXISTS (SELECT 1 FROM projects_project p WHERE p.id = project_id)",
    "projects_deployment": "EXISTS (SELECT 1 FROM projects_project p WHERE p.id = project_id)",
    "projects_repositoryindex": "EXISTS (SELECT 1 FROM projects_repository p WHERE p.id = repository_id)",
    "execution_session": "EXISTS (SELECT 1 FROM orchestration_run p WHERE p.id = run_id)",
    "execution_sandbox": "EXISTS (SELECT 1 FROM execution_session p WHERE p.id = session_id)",
}

HELPER = """
CREATE OR REPLACE FUNCTION app_current_org() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.current_org', true), '')::uuid
$$;
"""


def _forwards(schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    run = schema_editor.execute
    run(HELPER)

    for table in DIRECT:
        run(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        run(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        run(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        run(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (organization_id = app_current_org()) "
            f"WITH CHECK (organization_id = app_current_org())"
        )

    # Child tables: the parent's own policy applies inside the EXISTS subquery,
    # so visibility is inherited transitively down the chain.
    for table, predicate in VIA_PARENT.items():
        run(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        run(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        run(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        run(f"CREATE POLICY tenant_isolation ON {table} USING ({predicate}) WITH CHECK ({predicate})")

    # The tenant row itself: visible only when it is the current tenant.
    run("ALTER TABLE identity_organization ENABLE ROW LEVEL SECURITY")
    run("ALTER TABLE identity_organization FORCE ROW LEVEL SECURITY")
    run("DROP POLICY IF EXISTS tenant_isolation ON identity_organization")
    run("CREATE POLICY tenant_isolation ON identity_organization "
        "USING (id = app_current_org()) WITH CHECK (id = app_current_org())")


def _backwards(schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    run = schema_editor.execute
    for table in [*DIRECT, *VIA_PARENT, "identity_organization"]:
        run(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        run(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        run(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    run("DROP FUNCTION IF EXISTS app_current_org()")


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0001_initial"), ("providers", "0001_initial"),
        ("projects", "0001_initial"), ("orchestration", "0001_initial"),
        ("tools", "0001_initial"), ("execution", "0001_initial"),
        ("billing", "0001_initial"), ("audit", "0001_initial"),
    ]
    operations = [
        migrations.RunPython(
            lambda apps, se: _forwards(se),
            lambda apps, se: _backwards(se),
        )
    ]

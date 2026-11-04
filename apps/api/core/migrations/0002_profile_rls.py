"""Row-level security for identity_profile.

A profile is a person, not a tenant: one user can belong to many organizations,
so there is no organization_id to key on. A row is visible when either:
  * it is the caller's own profile (app.current_profile), or
  * the person is a member of the organization currently in context.

Everything else, including enumeration of other tenants' users, returns nothing.
Writes are limited to your own profile. Creating a profile happens at first
login, before any tenant exists, so INSERT is allowed only for the caller's own
id.
"""
from django.db import migrations

HELPER = """
CREATE OR REPLACE FUNCTION app_current_profile() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.current_profile', true), '')::uuid
$$;
"""

VISIBLE = """(
    id = app_current_profile()
    OR EXISTS (
        SELECT 1 FROM identity_membership m
        WHERE m.profile_id = identity_profile.id
          AND m.organization_id = app_current_org()
          AND m.is_active
    )
)"""


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    run = schema_editor.execute
    run(HELPER)
    run("ALTER TABLE identity_profile ENABLE ROW LEVEL SECURITY")
    run("ALTER TABLE identity_profile FORCE ROW LEVEL SECURITY")
    run("DROP POLICY IF EXISTS profile_select ON identity_profile")
    run("DROP POLICY IF EXISTS profile_write ON identity_profile")
    run(f"CREATE POLICY profile_select ON identity_profile FOR SELECT USING {VISIBLE}")
    # Writes: only your own row. The id is checked on the new row as well, so a
    # user cannot rewrite their row into someone else's identity.
    run("CREATE POLICY profile_write ON identity_profile FOR ALL "
        "USING (id = app_current_profile()) WITH CHECK (id = app_current_profile())")


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    run = schema_editor.execute
    run("DROP POLICY IF EXISTS profile_select ON identity_profile")
    run("DROP POLICY IF EXISTS profile_write ON identity_profile")
    run("ALTER TABLE identity_profile NO FORCE ROW LEVEL SECURITY")
    run("ALTER TABLE identity_profile DISABLE ROW LEVEL SECURITY")
    run("DROP FUNCTION IF EXISTS app_current_profile()")


class Migration(migrations.Migration):
    dependencies = [("core", "0001_row_level_security"), ("identity", "0001_initial")]
    operations = [migrations.RunPython(forwards, backwards)]

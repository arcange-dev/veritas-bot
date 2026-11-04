"""Let a person read their OWN memberships, before any tenant is bound.

core.rls.tenant_context must verify "is this profile an active member of that
org?" BEFORE it sets app.current_org. identity_membership is protected by an
org-scoped policy, so with no org set that check would see zero rows and refuse
every legitimate user.

This adds a SELECT-only policy exposing exactly the rows that describe the
caller themself. It reveals nothing about anyone else, and grants no write.
Policies are permissive and OR together with tenant_isolation.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    run = schema_editor.execute
    run("DROP POLICY IF EXISTS membership_self_read ON identity_membership")
    run("CREATE POLICY membership_self_read ON identity_membership "
        "FOR SELECT USING (profile_id = app_current_profile())")


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP POLICY IF EXISTS membership_self_read ON identity_membership")


class Migration(migrations.Migration):
    dependencies = [("core", "0002_profile_rls")]
    operations = [migrations.RunPython(forwards, backwards)]

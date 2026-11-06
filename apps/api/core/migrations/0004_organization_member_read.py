"""Let a person read the organizations they belong to, before one is chosen.

After sign-in the UI must ask "which workspaces am I in?" before any organization
is bound. identity_organization is protected by `id = app_current_org()`, which
shows nothing until one is chosen, so the question cannot be answered.

Defence in depth: the subquery reads identity_membership, which is itself protected
by membership_self_read (a person sees only their own membership rows). So the explicit
`m.profile_id = app_current_profile()` below is currently redundant: removing it does not
open a leak, because the membership policy already hides other people's rows. It is kept on
purpose so this policy stays correct on its own if the membership policy is ever relaxed
(for example to let admins list teammates). tests/test_me_api.py checks the end result.

This adds a SECOND, SELECT-only policy (policies on a table are OR-ed together):
an organization is readable to a person who has an ACTIVE membership in it. That is
exactly "workspaces I belong to". It does not widen what any tenant can see of
another: a non-member still sees nothing, and there is no write path.
"""
from django.db import migrations

POLICY = "org_member_read"


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    run = schema_editor.execute
    run(f"DROP POLICY IF EXISTS {POLICY} ON identity_organization")
    run(
        f"CREATE POLICY {POLICY} ON identity_organization FOR SELECT USING ("
        "EXISTS (SELECT 1 FROM identity_membership m "
        "WHERE m.organization_id = identity_organization.id "
        "AND m.profile_id = app_current_profile() AND m.is_active))"
    )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f"DROP POLICY IF EXISTS {POLICY} ON identity_organization")


class Migration(migrations.Migration):
    dependencies = [("core", "0003_membership_self_read"), ("identity", "0001_initial")]
    operations = [migrations.RunPython(forwards, backwards)]

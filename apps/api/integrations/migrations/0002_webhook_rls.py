"""Row-level security for the webhook inbox.

WebhookDelivery has no organization column: GitHub's request arrives before any
tenant is known. So the usual `organization_id = app_current_org()` rule does not
apply, and the table gets a policy set of its own:

  INSERT  allowed with no tenant bound (the receiver is unauthenticated), but only
          for rows that record a verified signature. The receiver verifies before
          it writes; this makes the database refuse an unverified row regardless.
  SELECT  only deliveries whose installation_id belongs to a repository the bound
          tenant can already see. Repository is itself RLS-protected through its
          project, so this inherits tenant isolation instead of re-implementing it.
  UPDATE / DELETE  no policy, so the application role cannot do either. A delivery
          log that can be edited is not evidence of anything.

The platform owner role is unaffected (it owns the table and bypasses policies),
which is what migrations and operational clean-up use.
"""
from django.db import migrations

TABLE = "integrations_webhook_delivery"


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    run = schema_editor.execute
    run(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    run(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    for name in ("webhook_insert", "webhook_select"):
        run(f"DROP POLICY IF EXISTS {name} ON {TABLE}")
    run(f"CREATE POLICY webhook_insert ON {TABLE} FOR INSERT WITH CHECK (signature_verified IS TRUE)")
    run(
        f"CREATE POLICY webhook_select ON {TABLE} FOR SELECT USING ("
        f"installation_id IS NOT NULL AND signature_verified IS TRUE AND EXISTS ("
        f"SELECT 1 FROM projects_repository r WHERE r.installation_id = {TABLE}.installation_id))"
    )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    run = schema_editor.execute
    run(f"DROP POLICY IF EXISTS webhook_insert ON {TABLE}")
    run(f"DROP POLICY IF EXISTS webhook_select ON {TABLE}")
    run(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    run(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [("integrations", "0001_initial"), ("core", "0003_membership_self_read"),
                    ("projects", "0001_initial")]
    operations = [migrations.RunPython(forwards, backwards)]

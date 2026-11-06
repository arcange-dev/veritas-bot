"""Let a verified login find or create its own profile.

The problem
-----------
Row-level security on identity_profile only admits a row when `id = app_current_profile()`.
At the first request of a session, authentication has not run yet, so no profile is bound,
and the profile may not even exist. Two things broke:

  * `INSERT` of a new user's profile failed the policy's WITH CHECK (the id is generated at
    insert time, so it could not have been bound beforehand): nobody could ever sign in for
    the first time.
  * the lookup that precedes the insert could not see an existing profile either, so a
    returning user would have been inserted a second time.

The fix
-------
A second pair of policies keyed on `app.auth_subject`, a transaction-local setting that ONLY
the authenticator sets, and only to the `sub` of a token whose signature, audience and expiry
have just been verified. A row is visible/creatable for exactly that subject:

    supabase_user_id = app_auth_subject()

It grants nothing about anyone else, never lists profiles, and is unset (NULL) on every other
request, so the comparison is NULL and matches no row. The existing id-based policies are
untouched and still govern everything after login.
"""
from django.db import migrations

HELPER = """
CREATE OR REPLACE FUNCTION app_auth_subject() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.auth_subject', true), '')::uuid
$$;
"""


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    run = schema_editor.execute
    run(HELPER)
    for name in ("profile_login_select", "profile_login_insert", "profile_login_update"):
        run(f"DROP POLICY IF EXISTS {name} ON identity_profile")
    run("CREATE POLICY profile_login_select ON identity_profile FOR SELECT "
        "USING (supabase_user_id = app_auth_subject())")
    run("CREATE POLICY profile_login_insert ON identity_profile FOR INSERT "
        "WITH CHECK (supabase_user_id = app_auth_subject())")
    # Needed to backfill an empty email on a returning login. Same subject, same row.
    run("CREATE POLICY profile_login_update ON identity_profile FOR UPDATE "
        "USING (supabase_user_id = app_auth_subject()) WITH CHECK (supabase_user_id = app_auth_subject())")


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    run = schema_editor.execute
    for name in ("profile_login_select", "profile_login_insert", "profile_login_update"):
        run(f"DROP POLICY IF EXISTS {name} ON identity_profile")
    run("DROP FUNCTION IF EXISTS app_auth_subject()")


class Migration(migrations.Migration):
    dependencies = [("core", "0004_organization_member_read")]
    operations = [migrations.RunPython(forwards, backwards)]

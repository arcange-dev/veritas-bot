"""Create the unprivileged runtime role that makes row-level security real.

Why this exists
---------------
Migrations must run as the database OWNER (they create tables and policies). The
running app and workers must NOT: an owner or superuser role bypasses RLS, so the
second tenant wall would silently not exist. Render's managed Postgres gives you
only the owner, so this script creates a second role, `veritas_app`, with
NOSUPERUSER NOBYPASSRLS and only the table privileges the app needs.

Run once after the first `migrate`, and again after any migration that adds
tables (it is idempotent). Needs MIGRATE_DATABASE_URL (the owner URL).

Prints the runtime URL to set as DATABASE_URL. The password is read from
APP_DB_PASSWORD so it never appears in a command line or a log.
"""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import quote, urlparse, urlunparse

import psycopg
from psycopg import sql

ROLE = "veritas_app"


def main() -> int:
    owner_url = os.environ.get("MIGRATE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    password = os.environ.get("APP_DB_PASSWORD", "")
    if not owner_url:
        print("MIGRATE_DATABASE_URL is required", file=sys.stderr)
        return 2
    if len(password) < 24:
        print("APP_DB_PASSWORD must be set and at least 24 characters", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", password):
        print("APP_DB_PASSWORD may only contain letters, digits, _ and -", file=sys.stderr)
        return 2

    with psycopg.connect(owner_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user")
        dbname, owner = cur.fetchone()
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [ROLE])
        exists = cur.fetchone() is not None
        role_sql = sql.SQL(
            "{verb} ROLE {role} WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {pw}"
        ).format(verb=sql.SQL("ALTER" if exists else "CREATE"), role=sql.Identifier(ROLE), pw=sql.Literal(password))
        cur.execute(role_sql)
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(dbname), sql.Identifier(ROLE)))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(ROLE)))
        cur.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(ROLE)))
        cur.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(sql.Identifier(ROLE)))
        # Tables created by later migrations (run as the owner) get the same grants.
        cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}").format(sql.Identifier(owner), sql.Identifier(ROLE)))
        cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}").format(sql.Identifier(owner), sql.Identifier(ROLE)))

        # Prove it, rather than assume: the role must not be able to bypass RLS.
        cur.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s", [ROLE])
        is_super, bypass = cur.fetchone()
        if is_super or bypass:
            print(f"FATAL: {ROLE} can bypass row-level security", file=sys.stderr)
            return 1
        cur.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind='r' AND c.relname !~ '^(django_|auth_)' "
            "AND c.relname NOT IN ('providers_model') AND NOT (c.relrowsecurity AND c.relforcerowsecurity)"
        )
        unprotected = cur.fetchone()[0]
        if unprotected:
            print(f"WARNING: {unprotected} tenant table(s) lack forced RLS", file=sys.stderr)

    parsed = urlparse(owner_url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    runtime = urlunparse((parsed.scheme, f"{ROLE}:{quote(password, safe='')}@{host}{port}", parsed.path, "", parsed.query, ""))
    print(f"OK: role {ROLE} ready (not superuser, no BYPASSRLS).")
    print("Set DATABASE_URL on the api and worker services to the runtime URL below,")
    print("and keep MIGRATE_DATABASE_URL (the owner URL) for the pre-deploy migrate step only.")
    if os.environ.get("PRINT_RUNTIME_URL") == "1":
        print(runtime)
    else:
        print("(re-run with PRINT_RUNTIME_URL=1 locally to print it; it contains the password)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

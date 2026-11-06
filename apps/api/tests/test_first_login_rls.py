"""First sign-in under row-level security, as the unprivileged role.

Every earlier test either pre-created the profile or ran as a superuser, so none could see
that a brand-new user could not sign in at all. This is the test that can."""
from __future__ import annotations

import os
import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.db import connection, connections
from rest_framework.test import APIClient

from identity.models import Profile

APP_ROLE = os.environ.get("TEST_APP_ROLE", "sa_app")
SECRET = "test-secret-that-is-comfortably-longer-than-32-bytes"
pytestmark = [
    pytest.mark.skipif(connection.vendor != "postgresql", reason="row-level security requires PostgreSQL"),
    pytest.mark.django_db(transaction=True),
]


@pytest.fixture(autouse=True)
def configured(settings):
    settings.SUPABASE_JWT_SECRET = SECRET
    settings.SUPABASE_JWT_AUDIENCE = "authenticated"


def token(sub=None, email="new@example.com", **extra) -> str:
    now = int(time.time())
    claims = {"sub": str(sub or uuid.uuid4()), "email": email, "aud": "authenticated",
              "role": "authenticated", "iat": now, "exp": now + 600, **extra}
    return jwt.encode(claims, SECRET, algorithm="HS256")


def call(tok, path="/api/v1/me/"):
    c = APIClient()
    return c.get(path, HTTP_AUTHORIZATION=f"Bearer {tok}")


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


def owner_count(sql, params=()):
    s = connections["default"].settings_dict
    mine = s["USER"]; connections.close_all(); s["USER"] = "postgres"
    try:
        with connection.cursor() as cur:
            cur.execute(sql, params); return cur.fetchone()[0]
    finally:
        connections.close_all(); s["USER"] = mine


def test_a_brand_new_user_can_sign_in_for_the_first_time(unprivileged):
    sub = uuid.uuid4()
    r = call(token(sub, "ada@example.com"))
    assert r.status_code == 200, r.content[:300]
    body = r.json()
    assert body["profile"]["email"] == "ada@example.com" and body["organizations"] == []
    assert owner_count("select count(*) from identity_profile where supabase_user_id = %s", [str(sub)]) == 1


def test_signing_in_again_does_not_create_a_second_profile(unprivileged):
    sub = uuid.uuid4()
    for _ in range(3):
        assert call(token(sub)).status_code == 200
    assert owner_count("select count(*) from identity_profile where supabase_user_id = %s", [str(sub)]) == 1


def test_a_returning_user_with_an_empty_email_gets_it_backfilled(unprivileged):
    sub = uuid.uuid4()
    assert call(token(sub, email="")).status_code == 200
    assert call(token(sub, email="later@example.com")).status_code == 200
    assert owner_count("select email from identity_profile where supabase_user_id = %s", [str(sub)]) == "later@example.com"


def test_two_people_get_two_separate_profiles(unprivileged):
    a, b = uuid.uuid4(), uuid.uuid4()
    ra = call(token(a, "a@x.io")).json()["profile"]; rb = call(token(b, "b@x.io")).json()["profile"]
    assert ra["id"] != rb["id"] and ra["email"] == "a@x.io" and rb["email"] == "b@x.io"


def test_a_token_with_a_non_uuid_subject_is_a_401_not_a_500(unprivileged):
    for bad in ("not-a-uuid", "'; drop table identity_profile; --", "1"):
        assert call(token(bad)).status_code == 401, bad
    assert owner_count("select count(*) from identity_profile") == 0


def test_a_forged_or_expired_token_creates_no_profile(unprivileged):
    forged = jwt.encode({"sub": str(uuid.uuid4()), "aud": "authenticated", "exp": int(time.time()) + 600},
                        "the-wrong-secret-the-wrong-secret-0123456789", algorithm="HS256")
    expired = token(exp=int(time.time()) - 5)
    assert call(forged).status_code == 401 and call(expired).status_code == 401
    assert owner_count("select count(*) from identity_profile") == 0


def test_the_login_setting_does_not_outlive_the_request(unprivileged):
    """app.auth_subject is transaction-local: after sign-in, the same connection must see no profile."""
    sub = uuid.uuid4(); assert call(token(sub)).status_code == 200
    with connection.cursor() as cur:
        cur.execute("select current_setting('app.auth_subject', true)")
        assert cur.fetchone()[0] in (None, "")
        cur.execute("select count(*) from identity_profile")
        assert cur.fetchone()[0] == 0            # nothing is visible once the request is over


def test_the_login_policy_never_exposes_someone_elses_profile(unprivileged):
    """Binding my own subject must reveal my row only; it is not a way to list or read others."""
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    call(token(theirs, "theirs@x.io")); call(token(mine, "mine@x.io"))
    with connection.cursor() as cur:
        cur.execute("select set_config('app.auth_subject', %s, false)", [str(mine)])
        cur.execute("select email from identity_profile")
        assert [r[0] for r in cur.fetchall()] == ["mine@x.io"]


def test_the_login_policy_cannot_insert_a_profile_for_a_different_subject(unprivileged):
    from django.db.utils import DatabaseError
    with connection.cursor() as cur:
        cur.execute("select set_config('app.auth_subject', %s, false)", [str(uuid.uuid4())])
        with pytest.raises(DatabaseError, match="row-level security"):
            cur.execute("insert into identity_profile (id, created_at, updated_at, supabase_user_id, email, display_name, "
                        "avatar_url, is_platform_admin) values (%s, now(), now(), %s, 'evil@x.io', '', '', true)",
                        [uuid.uuid4(), uuid.uuid4()])


def test_no_subject_bound_means_no_profile_can_be_inserted_or_read(unprivileged):
    from django.db.utils import DatabaseError
    with connection.cursor() as cur:
        with pytest.raises(DatabaseError, match="row-level security"):
            cur.execute("insert into identity_profile (id, created_at, updated_at, supabase_user_id, email, display_name, "
                        "avatar_url, is_platform_admin) values (%s, now(), now(), %s, 'x@x.io', '', '', false)",
                        [uuid.uuid4(), uuid.uuid4()])

from .base import *  # noqa: F401,F403
import os
import tempfile

DEBUG = False
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {"NAME": f"{tempfile.gettempdir()}/superagent_test.sqlite3"},
        # SQLite allows one writer. Parallel agent tasks queue instead of erroring;
        # PostgreSQL in production has no such limit.
        # IMMEDIATE takes the write lock when a transaction begins, so contending
        # threads queue on the busy timeout instead of failing with "database is
        # locked" when a read lock cannot be upgraded. SQLite-only; Postgres has
        # no such limitation.
        "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
    }
}
# Opt-in real PostgreSQL: TEST_DATABASE_URL=postgres://user@/dbname?host=/socket/dir
# SQLite stays the default because it is fast; anything that depends on database
# behaviour (row-level security, locking, constraints) must also run on Postgres.
_pg_url = os.environ.get("TEST_DATABASE_URL", "")
if _pg_url:
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(_pg_url)}
    DATABASES["default"]["TEST"] = {"NAME": DATABASES["default"]["NAME"] + "_run"}

# Deterministic test keys. Never used outside tests.
BYOK_ENCRYPTION_KEYS = ["k-test-1:ZmDfcTF7_60GrrY167zsiPd67pEvs0UUuCUZ9_C7rJ8="]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
PASSWORD_HASHERS = PASSWORD_HASHERS  # noqa: PLW0127
LOGGING["root"]["level"] = "ERROR"  # noqa: F405

# Tests never need a broker: the in-memory layer implements the same contract.
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

"""Settings shared by every environment. Nothing secret is hardcoded here."""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parents[2]


def env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value or ""


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [p.strip() for p in env(name, default).split(",") if p.strip()]


# --- core ------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-only-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "channels",
    # local apps
    "core",
    "identity",
    "providers",
    "projects",
    "integrations",
    "accounts",
    "orchestration",
    "tools",
    "execution",
    "billing",
    "audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "core.middleware.RequestContextMiddleware",
    "core.middleware.SecretRedactionMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
    ]},
}]

# --- database --------------------------------------------------------------
# Web tier uses the pooled URL; migrations use the direct URL (see docs).
DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=int(env("DB_CONN_MAX_AGE", "0")),
        conn_health_checks=True,
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

# --- cache / celery --------------------------------------------------------
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TIME_LIMIT = 60 * 30
CELERY_WORKER_MAX_TASKS_PER_CHILD = 50
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# --- auth ------------------------------------------------------------------
AUTH_USER_MODEL = "auth.User"          # Django's user is internal only; identity is Supabase
SUPABASE_URL = env("SUPABASE_URL")
SUPABASE_ANON_KEY = env("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = env("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_JWT_SECRET = env("SUPABASE_JWT_SECRET")
SUPABASE_JWKS_URL = env("SUPABASE_JWKS_URL")
SUPABASE_JWT_AUDIENCE = env("SUPABASE_JWT_AUDIENCE", "authenticated")
JWT_JWKS_CACHE_SECONDS = 300

# --- BYOK crypto -----------------------------------------------------------
# Comma separated, newest first. MultiFernet decrypts with any listed key and
# encrypts with the first, which makes rotation a deploy + re-encrypt task.
BYOK_ENCRYPTION_KEYS = env_list("BYOK_ENCRYPTION_KEYS")
BYOK_ACTIVE_KEY_ID = env("BYOK_ACTIVE_KEY_ID", "k1")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["identity.authentication.SupabaseJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.CursorPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.errors.exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["core.throttles.OrgScopedThrottle"],
    "DEFAULT_THROTTLE_RATES": {"org": env("RATE_LIMIT_PER_MINUTE", "120") + "/min"},
}

SPECTACULAR_SETTINGS = {
    "TITLE": "SuperAgent API",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
CORS_ALLOW_CREDENTIALS = True

# --- platform guardrails ---------------------------------------------------
MAX_TASK_COST_USD = env("MAX_TASK_COST_USD", "5.00")
DEFAULT_MONTHLY_SPEND_CAP_USD = env("DEFAULT_MONTHLY_SPEND_CAP_USD", "50.00")
RUNNER_JWT_KEY = env("RUNNER_JWT_KEY", SECRET_KEY)
LOCAL_RUNNER_PAIRING_TTL_SECONDS = int(env("LOCAL_RUNNER_PAIRING_TTL_SECONDS", "600"))
LOCAL_RUNNER_MAX_COMMAND_SECONDS = int(env("LOCAL_RUNNER_MAX_COMMAND_SECONDS", "900"))
MAX_TOOL_OUTPUT_BYTES = 200 * 1024
GRAPH_RECURSION_LIMIT = int(env("GRAPH_RECURSION_LIMIT", "60"))
GRAPH_MAX_ITERATIONS = int(env("GRAPH_MAX_ITERATIONS", "12"))

DAYTONA_ENABLED = env_bool("DAYTONA_ENABLED", False)
DAYTONA_API_KEY = env("DAYTONA_API_KEY")
DAYTONA_API_URL = env("DAYTONA_API_URL", "https://app.daytona.io/api")
DAYTONA_TARGET_REGION = env("DAYTONA_TARGET_REGION", "eu")

GITHUB_APP_ID = env("GITHUB_APP_ID")
GITHUB_APP_PRIVATE_KEY_PATH = env("GITHUB_APP_PRIVATE_KEY_PATH")
GITHUB_APP_WEBHOOK_SECRET = env("GITHUB_APP_WEBHOOK_SECRET")

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": (
                '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s",'
                '"msg":"%(message)s","request_id":"%(request_id)s"}'
            )
        }
    },
    "filters": {"redact": {"()": "core.logging_filters.SecretRedactionFilter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["redact"],
        }
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

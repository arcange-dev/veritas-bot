from .base import *  # noqa: F401,F403
from .base import env, env_bool

DEBUG = False
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CORS_ALLOW_ALL_ORIGINS = False

if env_bool("SENTRY_ENABLED", False):
    import sentry_sdk

    sentry_sdk.init(
        dsn=env("SENTRY_DSN"),
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

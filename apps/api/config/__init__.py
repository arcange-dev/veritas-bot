"""Celery is imported lazily so the app boots in minimal environments.

Production installs requirements.txt, so `celery_app` is always present there.
`manage.py check` and the pure-logic test suite must not require a broker.
"""
try:  # pragma: no cover - import-time guard
    from .celery import app as celery_app

    __all__ = ("celery_app",)
except ImportError:  # pragma: no cover
    celery_app = None
    __all__ = ("celery_app",)

"""Celery application. Tasks pass ids, never ORM objects."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("superagent")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.task_routes = {
    "orchestration.*": {"queue": "agents"},
    "execution.*": {"queue": "execution"},
}

@app.task(bind=True, ignore_result=True)
def healthcheck(self) -> str:
    return "ok"

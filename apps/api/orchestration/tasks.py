"""Celery entry points. Tasks receive ids, never ORM objects or secrets."""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="orchestration.execute_run", acks_late=True, ignore_result=True,
             soft_time_limit=60 * 25)
def execute_run_task(run_id: str, org_id: str = "", profile_id: str = "") -> str:
    """Run the agent graph for one run. Safe to deliver twice.

    `acks_late` means a worker crash re-delivers the message. `execute_run`
    refuses to start a run that is already terminal, so a duplicate delivery is
    a no-op rather than a second bill.
    """
    from orchestration.executor import execute_run

    run = execute_run(run_id, org_id or None, profile_id or None)
    logger.info("run finished", extra={"run_id": run_id, "status": run.status})
    return run.status


def enqueue_run(run_id: str, org_id: str = "", profile_id: str = "") -> None:
    """Hand a run to the worker. Called after the DB transaction commits.

    The org and profile ids are those of the request that was authorised to start
    the run. The worker re-verifies membership before binding them.
    """
    from django.db import transaction

    transaction.on_commit(lambda: execute_run_task.delay(run_id, org_id, profile_id))

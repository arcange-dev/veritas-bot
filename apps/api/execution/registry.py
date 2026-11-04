"""Backend selection. Branching on provider lives here and nowhere else."""
from __future__ import annotations

from django.conf import settings

from .base import ExecutionBackend
from .fake import FakeBackend


def get_backend(name: str) -> ExecutionBackend:
    if name == "fake":
        return FakeBackend()
    if name == "cloud":
        if not settings.DAYTONA_ENABLED:
            raise RuntimeError("Cloud execution is disabled (DAYTONA_ENABLED=false)")
        from .daytona import DaytonaBackend

        return DaytonaBackend()
    if name == "local":
        from .local import LocalRunnerBackend

        return LocalRunnerBackend()
    raise ValueError(f"unknown execution backend: {name}")


def available_backends() -> list[str]:
    names = ["local", "fake"]
    if settings.DAYTONA_ENABLED:
        names.insert(1, "cloud")
    return names

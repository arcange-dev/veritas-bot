"""Daytona adapter.

Shape only: this is written against the documented workspaces API and is marked
UNVERIFIED until a real DAYTONA_API_KEY has exercised it (see
docs/security/SECURITY_REPORT.md and PROJECT_STATUS.md).
"""
from __future__ import annotations

import time
from typing import AsyncIterator

import httpx
from django.conf import settings

from .base import Command, CommandResult, ExecutionBackend, LogChunk, SessionHandle, SessionSpec


class DaytonaBackend(ExecutionBackend):
    name = "cloud"

    def __init__(self) -> None:
        if not settings.DAYTONA_API_KEY:
            raise RuntimeError("DAYTONA_API_KEY is not configured")
        self.client = httpx.Client(
            base_url=settings.DAYTONA_API_URL,
            headers={"Authorization": f"Bearer {settings.DAYTONA_API_KEY}"},
            timeout=30.0,
        )

    def create_session(self, spec: SessionSpec) -> SessionHandle:
        resp = self.client.post("/workspace", json={
            "image": spec.image,                       # pinned digest, never :latest
            "resources": {"cpu": spec.cpu, "memory": spec.memory_gb,
                          "disk": spec.disk_gb},
            "ttlMinutes": spec.ttl_minutes,
            "region": settings.DAYTONA_TARGET_REGION,
            "env": spec.env_allowlist,                 # no platform or model secrets
            "user": "agent",                           # non-root
        })
        resp.raise_for_status()
        body = resp.json()
        return SessionHandle(
            session_id=body["id"],
            provider=self.name,
            workspace="/workspace",
            region=body.get("region", settings.DAYTONA_TARGET_REGION),
        )

    def exec(self, handle: SessionHandle, command: Command) -> CommandResult:
        started = time.monotonic()
        resp = self.client.post(
            f"/workspace/{handle.session_id}/exec",
            json={"argv": command.argv, "cwd": command.cwd,
                  "timeout": command.timeout_seconds},
            timeout=command.timeout_seconds + 10,
        )
        resp.raise_for_status()
        body = resp.json()
        stdout, t1 = self.truncate(body.get("stdout", ""), settings.MAX_TOOL_OUTPUT_BYTES)
        stderr, t2 = self.truncate(body.get("stderr", ""), settings.MAX_TOOL_OUTPUT_BYTES)
        return CommandResult(
            exit_code=int(body.get("exitCode", 1)),
            stdout=stdout, stderr=stderr,
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=t1 or t2,
        )

    def write_file(self, handle, path, content):
        safe = self.safe_join(handle.workspace, path)
        self.client.put(f"/workspace/{handle.session_id}/files",
                        json={"path": safe, "content": content.decode("utf-8", "replace")}
                        ).raise_for_status()

    def read_file(self, handle, path):
        safe = self.safe_join(handle.workspace, path)
        resp = self.client.get(f"/workspace/{handle.session_id}/files",
                               params={"path": safe})
        resp.raise_for_status()
        return resp.content

    def list_dir(self, handle, path):
        safe = self.safe_join(handle.workspace, path)
        resp = self.client.get(f"/workspace/{handle.session_id}/list",
                               params={"path": safe})
        resp.raise_for_status()
        return resp.json().get("entries", [])

    async def stream_logs(self, handle) -> AsyncIterator[LogChunk]:
        raise NotImplementedError(
            "Log streaming uses the Daytona websocket channel; see "
            "docs/architecture/ARCHITECTURE.md#execution"
        )

    def stop(self, handle: SessionHandle) -> None:
        resp = self.client.delete(f"/workspace/{handle.session_id}")
        if resp.status_code not in (200, 202, 204, 404):
            resp.raise_for_status()          # 404 means already gone: idempotent

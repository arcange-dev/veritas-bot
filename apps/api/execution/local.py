"""Local runner adapter: every operation is relayed over the device socket.

The Django process never executes anything here. It enqueues a frame, waits for
the correlated reply, and fails fast when the device is not connected.
"""
from __future__ import annotations

import base64
import uuid
from typing import AsyncIterator

from .base import Command, CommandResult, ExecutionBackend, LogChunk, SessionHandle, SessionSpec
from .relay import DEFAULT_TIMEOUT_SECONDS, RelayError, RunnerRelay


class LocalRunnerBackend(ExecutionBackend):
    name = "local"

    def __init__(self, relay: RunnerRelay | None = None) -> None:
        self.relay = relay or RunnerRelay()

    # --- session ---------------------------------------------------------
    def create_session(self, spec: SessionSpec) -> SessionHandle:
        if not spec.device_id:
            raise ValueError("local sessions require a paired device")
        if not spec.workspace_subpath:
            raise ValueError("local sessions require an approved workspace subpath")
        return SessionHandle(
            session_id=f"local-{uuid.uuid4().hex[:12]}",
            provider=self.name,
            workspace=spec.workspace_subpath,
            device_id=spec.device_id,
        )

    @staticmethod
    def _require_device(handle: SessionHandle) -> str:
        if not handle.device_id:
            raise ValueError("session handle is not bound to a device")
        return handle.device_id

    # --- command ---------------------------------------------------------
    def exec(self, handle: SessionHandle, command: Command) -> CommandResult:
        device_id = self._require_device(handle)
        # The runner applies its own policy again; relaying an approval id grants
        # nothing on its own.
        data = self.relay.request_sync(
            device_id,
            {
                "type": "exec",
                "argv": list(command.argv),
                "cwd": command.cwd or handle.workspace,
                "timeout_seconds": int(command.timeout_seconds),
                "approval_id": command.approval_id,
            },
            # Client-side timeout sits above the runner's so the runner reports
            # the kill rather than the platform giving up first.
            timeout=float(command.timeout_seconds) + 15.0,
        )
        return CommandResult(
            exit_code=int(data.get("exit_code", 1)),
            stdout=str(data.get("stdout", "")),
            stderr=str(data.get("stderr", "")),
            duration_ms=int(data.get("duration_ms", 0)),
            truncated=bool(data.get("truncated", False)),
        )

    # --- filesystem ------------------------------------------------------
    def write_file(self, handle: SessionHandle, path: str, content: bytes) -> None:
        self.relay.request_sync(
            self._require_device(handle),
            {
                "type": "fs.write",
                "path": path,
                "content": base64.b64encode(content).decode("ascii"),
            },
        )

    def read_file(self, handle: SessionHandle, path: str) -> bytes:
        data = self.relay.request_sync(
            self._require_device(handle), {"type": "fs.read", "path": path}
        )
        return base64.b64decode(str(data.get("content", "")))

    def list_dir(self, handle: SessionHandle, path: str) -> list[str]:
        data = self.relay.request_sync(
            self._require_device(handle), {"type": "fs.list", "path": path}
        )
        return [str(entry) for entry in data.get("entries", [])]

    # --- streaming -------------------------------------------------------
    async def stream_logs(self, handle: SessionHandle) -> AsyncIterator[LogChunk]:
        """Live output for this session, published by the runner consumer."""
        from execution.stream import subscribe

        async for payload in subscribe(handle.session_id):
            yield LogChunk(
                stream=payload.get("stream", "stdout"),
                seq=int(payload.get("seq", 0)),
                data=str(payload.get("data", "")),
            )

    # --- lifecycle -------------------------------------------------------
    def stop(self, handle: SessionHandle) -> None:
        """Best effort: a device that is already gone is already stopped."""
        device_id = handle.device_id
        if not device_id:
            return
        try:
            self.relay.request_sync(
                device_id,
                {"type": "stop", "session": handle.session_id},
                timeout=min(DEFAULT_TIMEOUT_SECONDS, 20.0),
            )
        except RelayError:
            return

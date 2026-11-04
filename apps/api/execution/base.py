"""The execution contract. Everything that runs code implements this.

No view, service or graph node may branch on a provider name: they call this
protocol. Adding a provider is adding an adapter, never an `if`.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal


@dataclass(frozen=True)
class SessionSpec:
    run_id: str
    organization_id: str
    repository_url: str = ""
    branch: str = ""
    image: str = "python:3.12-slim@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    cpu: float = 1.0
    memory_gb: float = 2.0
    disk_gb: float = 10.0
    ttl_minutes: int = 60
    workspace_subpath: str = ""
    env_allowlist: dict[str, str] = field(default_factory=dict)
    # Set for local execution: which paired device runs this session.
    device_id: str = ""


@dataclass(frozen=True)
class SessionHandle:
    session_id: str
    provider: str
    workspace: str
    region: str = ""
    # Local sessions carry the device id so every call can be routed back.
    device_id: str = ""


@dataclass(frozen=True)
class Command:
    argv: list[str]
    cwd: str = "."
    timeout_seconds: int = 120
    stdin: str | None = None
    # Set by the caller that already cleared the approval gate.
    approval_id: str | None = None


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool = False


@dataclass(frozen=True)
class LogChunk:
    stream: Literal["stdout", "stderr", "system"]
    seq: int
    data: str


class ExecutionBackend(abc.ABC):
    """Adapter protocol. Implementations must be idempotent on stop()."""

    name: str

    @abc.abstractmethod
    def create_session(self, spec: SessionSpec) -> SessionHandle: ...

    @abc.abstractmethod
    def exec(self, handle: SessionHandle, command: Command) -> CommandResult: ...

    @abc.abstractmethod
    def write_file(self, handle: SessionHandle, path: str, content: bytes) -> None: ...

    @abc.abstractmethod
    def read_file(self, handle: SessionHandle, path: str) -> bytes: ...

    @abc.abstractmethod
    def list_dir(self, handle: SessionHandle, path: str) -> list[str]: ...

    @abc.abstractmethod
    def stream_logs(self, handle: SessionHandle) -> AsyncIterator[LogChunk]: ...

    @abc.abstractmethod
    def stop(self, handle: SessionHandle) -> None: ...

    # --- shared, provider-independent helpers -----------------------------
    @staticmethod
    def safe_join(root: str, candidate: str) -> str:
        """Resolve a path inside the workspace or refuse.

        Blocks `..` traversal, absolute escapes and symlinked parents. Every
        adapter must call this before touching the filesystem.
        """
        import os

        root_abs = os.path.realpath(root)
        target = candidate if os.path.isabs(candidate) else os.path.join(root_abs, candidate)
        target_abs = os.path.realpath(target)
        if target_abs != root_abs and not target_abs.startswith(root_abs + os.sep):
            raise PermissionError(f"path escapes workspace: {candidate}")
        return target_abs

    @staticmethod
    def truncate(text: str, max_bytes: int) -> tuple[str, bool]:
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) <= max_bytes:
            return text, False
        cut = encoded[:max_bytes].decode("utf-8", errors="ignore")
        return cut + "\n... [output truncated]", True

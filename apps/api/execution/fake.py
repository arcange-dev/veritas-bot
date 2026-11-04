"""Deterministic in-memory backend: lets CI test the whole execution path with
no credentials, no network and no container."""
from __future__ import annotations

import shlex
import time
import uuid
from typing import AsyncIterator

from .base import Command, CommandResult, ExecutionBackend, LogChunk, SessionHandle, SessionSpec


class FakeBackend(ExecutionBackend):
    name = "fake"

    def __init__(self) -> None:
        self.files: dict[str, dict[str, bytes]] = {}
        self.commands: list[Command] = []
        self.stopped: set[str] = set()

    def create_session(self, spec: SessionSpec) -> SessionHandle:
        sid = f"fake-{uuid.uuid4().hex[:12]}"
        self.files[sid] = {"README.md": b"# fake workspace\n"}
        return SessionHandle(session_id=sid, provider=self.name, workspace=f"/tmp/{sid}")

    def exec(self, handle: SessionHandle, command: Command) -> CommandResult:
        if handle.session_id in self.stopped:
            raise RuntimeError("session is stopped")
        self.commands.append(command)
        started = time.monotonic()
        argv = command.argv
        fake_fs = self.files[handle.session_id]
        rel = command.cwd if command.cwd != "." else ""
        if argv[:1] == ["echo"]:
            out = " ".join(argv[1:]) + "\n"
            return CommandResult(0, out, "", int((time.monotonic() - started) * 1000))
        if argv[:2] == ["cat", "README.md"]:
            data = fake_fs.get((rel + "/" if rel else "") + "README.md", b"")
            return CommandResult(0, data.decode(), "", 1)
        if argv[:2] == ["pytest"] or argv[:3] == ["npm", "run", "test"]:
            return CommandResult(0, "2 passed\n", "", 5)
        if argv[:1] == ["fail"]:
            return CommandResult(1, "", "simulated failure\n", 3)
        return CommandResult(127, "", f"unknown fake command: {shlex.join(argv)}\n", 1)

    def write_file(self, handle: SessionHandle, path: str, content: bytes) -> None:
        self.safe_join("/workspace", path)          # reuse the traversal guard
        self.files[handle.session_id][path.lstrip("/")] = content

    def read_file(self, handle: SessionHandle, path: str) -> bytes:
        self.safe_join("/workspace", path)
        return self.files[handle.session_id].get(path.lstrip("/"), b"")

    def list_dir(self, handle: SessionHandle, path: str) -> list[str]:
        self.safe_join("/workspace", path)
        prefix = path.strip("/")
        prefix = f"{prefix}/" if prefix else ""
        return sorted({p[len(prefix):].split("/")[0] for p in self.files[handle.session_id]
                       if p.startswith(prefix)})

    async def stream_logs(self, handle: SessionHandle) -> AsyncIterator[LogChunk]:
        for seq, line in enumerate(["$ fake session ready\n"]):
            yield LogChunk(stream="stdout", seq=seq, data=line)

    def stop(self, handle: SessionHandle) -> None:
        self.stopped.add(handle.session_id)          # idempotent by construction

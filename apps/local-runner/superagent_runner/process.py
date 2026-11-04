"""Process supervision.

Every child runs in its own process group and is killed with that group, so a
dev server's worker processes do not outlive the session.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import IO

from .config import RunnerConfig
from .security.paths import Workspace
from .security.policy import Decision, evaluate, scrub_env


@dataclass
class ProcessRecord:
    session_id: str
    pid: int
    argv: list[str]
    started_at: float
    finished_at: float | None = None
    exit_code: int | None = None
    truncated: bool = False
    _chunks: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def append(self, chunk: str, limit: int) -> None:
        with self._lock:
            self._chunks.append(chunk)
            total = sum(len(c) for c in self._chunks)
            while total > limit and len(self._chunks) > 1:
                total -= len(self._chunks.pop(0))
            if total > limit and self._chunks:
                self._chunks = [self._chunks[-1][-limit:]]
                self.truncated = True

    @property
    def output(self) -> str:
        with self._lock:
            return "".join(self._chunks)

    @property
    def duration_ms(self) -> int:
        end = self.finished_at or time.time()
        return int((end - self.started_at) * 1000)


class ProcessManager:
    """Owns every process the runner spawns on behalf of the platform."""

    def __init__(self, config: RunnerConfig) -> None:
        self.config = config
        self._records: dict[str, ProcessRecord] = {}
        self._lock = threading.Lock()

    def run(
        self,
        workspace: Workspace,
        argv: list[str],
        *,
        cwd: str = ".",
        timeout_seconds: int | None = None,
        approval_id: str | None = None,
    ) -> ProcessRecord:
        resolved_cwd = workspace.resolve(cwd)
        verdict = evaluate(argv)
        if verdict.decision is Decision.DENY:
            raise PermissionError(f"command refused locally: {verdict.reason}")
        if verdict.decision is Decision.ASK and not approval_id:
            raise PermissionError(f"approval required: {verdict.reason}")

        timeout = min(
            timeout_seconds or self.config.max_command_seconds,
            self.config.max_command_seconds,
        )

        process = subprocess.Popen(  # noqa: S603 - argv is a validated list, shell=False
            argv,
            cwd=str(resolved_cwd),
            env=scrub_env(dict(os.environ)),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        record = ProcessRecord(
            session_id=f"s-{uuid.uuid4().hex[:12]}",
            pid=process.pid,
            argv=list(argv),
            started_at=time.time(),
        )
        with self._lock:
            self._records[record.session_id] = record

        self._pump(process.stdout, record)

        try:
            record.exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill_group(process.pid)
            record.exit_code = -1
            record.append(f"\n[timed out after {timeout}s]\n", self.config.max_output_bytes)
        finally:
            record.finished_at = time.time()

        return record

    def _pump(self, stream: IO[str] | None, record: ProcessRecord) -> None:
        if stream is None:
            return

        def reader() -> None:
            try:
                for line in stream:
                    record.append(line, self.config.max_output_bytes)
            except (ValueError, OSError):
                return

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        thread.join(timeout=1)

    def stop(self, session_id: str) -> bool:
        with self._lock:
            record = self._records.get(session_id)
        if record is None or record.finished_at is not None:
            return False
        self._kill_group(record.pid)
        return True

    def stop_all(self) -> int:
        return sum(1 for session_id in list(self._records) if self.stop(session_id))

    @staticmethod
    def _kill_group(pid: int) -> None:
        """Terminate the process group, then force it after a grace period."""
        for sig, grace in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 2.0)):
            try:
                os.killpg(os.getpgid(pid), sig)
            except (ProcessLookupError, PermissionError):
                return
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return
                time.sleep(0.05)

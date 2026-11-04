"""Outbound WebSocket client. No inbound listener is ever opened."""
from __future__ import annotations

import asyncio
import json
import logging
import platform
import random
import socket
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import RunnerConfig
from .process import ProcessManager
from .protocol import Hello
from .security.paths import PathRefused, Workspace
from .security.policy import Decision, evaluate

logger = logging.getLogger("superagent_runner")

HEARTBEAT_SECONDS = 20
MAX_BACKOFF_SECONDS = 15


class RunnerClient:
    def __init__(self, config: RunnerConfig) -> None:
        self.config = config
        self.processes = ProcessManager(config)
        self._seq = 0
        self._workspaces: dict[str, Workspace] = {}
        for root in config.workspace_roots:
            try:
                self._workspaces[root] = Workspace(root)
            except PathRefused:
                logger.warning("skipping unusable workspace root: %s", root)

    def _ws_url(self) -> str:
        base = self.config.api_url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base}/ws/runner/?device={self.config.device_id}&token={self.config.device_token}"

    def _workspace_for(self, path: str) -> Workspace:
        target = Path(path).expanduser().resolve() if path else None
        if target is None:
            if len(self._workspaces) == 1:
                return next(iter(self._workspaces.values()))
            raise PathRefused("a workspace path is required when several roots are approved")
        for root, workspace in self._workspaces.items():
            if Path(root) in (target, *target.parents):
                return workspace
        raise PathRefused(f"no approved workspace contains {path}")

    def build_hello(self) -> str:
        return Hello(
            runner_version=__version__,
            os=sys.platform,
            arch=platform.machine(),
            workspace_roots=list(self._workspaces),
        ).model_dump_json()

    async def run_forever(self) -> None:
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("websockets is not installed: pip install websockets") from exc

        attempt = 0
        while True:
            try:
                async with websockets.connect(
                    self._ws_url(), ping_interval=HEARTBEAT_SECONDS, max_size=8 * 1024 * 1024
                ) as socket_:
                    attempt = 0
                    await socket_.send(self.build_hello())
                    logger.info("connected to platform")
                    await self._serve(socket_)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect on any transport error
                attempt += 1
                delay = min(MAX_BACKOFF_SECONDS, 2 ** min(attempt, 4)) + random.uniform(0, 1)
                logger.warning("disconnected (%s); retrying in %.1fs", type(exc).__name__, delay)
                await asyncio.sleep(delay)

    async def _serve(self, socket_: Any) -> None:
        async for raw in socket_:
            message = json.loads(raw)
            kind = message.get("type", "")
            if kind == "exec":
                await self._handle_exec(socket_, message)
            elif kind.startswith("fs."):
                await self._handle_fs(socket_, message)
            elif kind == "stop":
                self.processes.stop(str(message.get("session", "")))
            elif kind == "ping":
                await socket_.send(json.dumps({"v": 1, "type": "pong", "id": message.get("id", "")}))

    async def _handle_exec(self, socket_: Any, message: dict) -> None:
        request_id = str(message.get("id", ""))
        argv = message.get("argv") or []

        verdict = evaluate(argv)
        if verdict.decision is Decision.DENY:
            await self._reply(socket_, request_id, ok=False,
                              error=f"refused by local policy: {verdict.reason}")
            return

        try:
            workspace = self._workspace_for(str(message.get("cwd") or ""))
        except PathRefused as exc:
            await self._reply(socket_, request_id, ok=False, error=str(exc))
            return

        # ASK-level commands need an approval id on the frame. The local policy
        # is enforced regardless of what the platform believes it approved.
        if verdict.decision is Decision.ASK and not message.get("approval_id"):
            await self._reply(socket_, request_id, ok=False,
                              error=f"approval required: {verdict.reason}")
            return

        loop = asyncio.get_running_loop()
        try:
            record = await loop.run_in_executor(
                None,
                lambda: self.processes.run(
                    workspace, argv, cwd=".",
                    timeout_seconds=int(message.get("timeout_seconds", 120)),
                    approval_id=message.get("approval_id"),
                ),
            )
        except PermissionError as exc:
            await self._reply(socket_, request_id, ok=False, error=str(exc))
            return

        await self._reply(socket_, request_id, ok=record.exit_code in (0, None), data={
            "session": record.session_id,
            "exit_code": record.exit_code,
            "stdout": record.output,
            "truncated": record.truncated,
            "duration_ms": record.duration_ms,
        })

    async def _handle_fs(self, socket_: Any, message: dict) -> None:
        request_id = str(message.get("id", ""))
        try:
            workspace = self._workspace_for(str(message.get("path", "")))
            target = workspace.resolve(str(message["path"]))
        except (PathRefused, KeyError) as exc:
            await self._reply(socket_, request_id, ok=False, error=str(exc))
            return

        kind = message.get("type")
        try:
            if kind == "fs.read":
                content = target.read_text(encoding="utf-8", errors="replace")
                await self._reply(socket_, request_id, ok=True, data={"content": content})
            elif kind == "fs.write":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(message.get("content") or ""), encoding="utf-8")
                await self._reply(socket_, request_id, ok=True, data={"path": str(target)})
            elif kind == "fs.list":
                entries = sorted(
                    p.name + ("/" if p.is_dir() else "") for p in target.iterdir()
                )
                await self._reply(socket_, request_id, ok=True, data={"entries": entries})
            else:
                await self._reply(socket_, request_id, ok=False, error="unknown fs frame")
        except OSError as exc:
            await self._reply(socket_, request_id, ok=False,
                              error=f"filesystem error: {exc.strerror}")

    @staticmethod
    async def _reply(socket_: Any, request_id: str, *, ok: bool,
                     data: dict | None = None, error: str = "") -> None:
        await socket_.send(json.dumps({
            "v": 1, "type": "result", "id": request_id, "ok": ok,
            "data": data or {}, "error": error,
        }))

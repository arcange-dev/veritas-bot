"""Wire protocol between runner and platform.

Additive changes only: adding a field is safe, renaming one needs a protocol
version bump. Frames are JSON objects with a `type`; request/response pairs
share an `id`.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PROTOCOL_VERSION = 1


class Frame(BaseModel):
    v: int = PROTOCOL_VERSION
    type: str
    id: str = ""


class Hello(Frame):
    type: Literal["hello"] = "hello"
    runner_version: str
    os: str
    arch: str
    workspace_roots: list[str] = Field(default_factory=list)


class ExecRequest(Frame):
    type: Literal["exec"] = "exec"
    argv: list[str]
    cwd: str = "."
    timeout_seconds: int = 120
    approval_id: str | None = None


class FsRequest(Frame):
    type: Literal["fs.read", "fs.write", "fs.list"]
    path: str
    content: str | None = None


class Response(Frame):
    type: Literal["result"] = "result"
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class Output(Frame):
    type: Literal["output"] = "output"
    session: str
    stream: Literal["stdout", "stderr", "system"]
    seq: int
    data: str


class Ping(Frame):
    type: Literal["ping"] = "ping"

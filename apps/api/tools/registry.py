"""Central, permission-controlled tool dispatch.

The model proposes a tool name plus arguments. This module decides whether that
name is allowed for this agent and this run, validates the arguments, enforces
approvals for destructive tools, applies a timeout and output cap, and writes an
audit row. Model output can never widen its own permissions: `allowed_tools` on
the AgentProfile is server-side data and the approval record is user-created.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from django.conf import settings
from pydantic import BaseModel, ValidationError

from core.errors import ApprovalRequired, DomainError
from execution.base import Command, CommandResult, ExecutionBackend, SessionHandle
from tools.models import ToolInvocation
from tools.schemas import (
    CreatePullRequestArgs,
    EditFileArgs,
    GitBranchArgs,
    GitCommitArgs,
    GitStatusArgs,
    ListDirArgs,
    ReadFileArgs,
    RunCommandArgs,
    RunTestsArgs,
    SearchCodeArgs,
    WriteFileArgs,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    requires: frozenset[str] = frozenset()
    destructive: bool = False
    timeout_key: str = ""


@dataclass
class DispatchContext:
    backend: ExecutionBackend
    handle: SessionHandle
    run_id: str | None = None
    step_id: str | None = None
    allowed_tools: set[str] = field(default_factory=set)
    approval_checked: set[str] = field(default_factory=set)   # tool names pre-approved
    organization_id: str | None = None


class ToolDenied(DomainError):
    code = "tool_denied"
    status_code = 403


REQUIRED_TOOLS: dict[str, ToolSpec] = {
    "read_file": ToolSpec("read_file", "Read a UTF-8 text file from the workspace.",
                          ReadFileArgs),
    "write_file": ToolSpec("write_file", "Create or replace a file in the workspace.",
                           WriteFileArgs),
    "edit_file": ToolSpec("edit_file", "Replace one exact occurrence of text in a file.",
                          EditFileArgs),
    "list_dir": ToolSpec("list_dir", "List a directory in the workspace.", ListDirArgs),
    "search_code": ToolSpec("search_code", "Search the workspace for a pattern.",
                            SearchCodeArgs),
    "run_command": ToolSpec("run_command", "Run a shell command in the workspace.",
                            RunCommandArgs, destructive=True),
    "run_tests": ToolSpec("run_tests", "Run the project test suite.", RunTestsArgs),
    "git_status": ToolSpec("git_status", "Read git status and diff summary.", GitStatusArgs),
    "git_branch": ToolSpec("git_branch", "Create a working branch.", GitBranchArgs),
    "git_commit": ToolSpec("git_commit", "Commit staged changes.", GitCommitArgs),
    "create_pull_request": ToolSpec(
        "create_pull_request", "Open a pull request for a working branch.",
        CreatePullRequestArgs, destructive=True,
    ),
}


def args_digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def redact_args(payload: dict) -> dict:
    """Preview kept in the audit row: keys and lengths, never values of secrets."""
    preview: dict = {}
    for key, value in payload.items():
        if any(t in key.lower() for t in ("key", "token", "secret", "password")):
            preview[key] = f"[redacted len={len(str(value))}]"
        elif isinstance(value, str) and len(value) > 200:
            preview[key] = f"[{len(value)} chars]"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            preview[key] = value
        else:
            preview[key] = f"[{type(value).__name__}]"
    return preview


class ToolRegistry:
    def __init__(self, tools: dict[str, ToolSpec] | None = None) -> None:
        self.tools = tools or dict(REQUIRED_TOOLS)

    def specs_for_prompt(self, allowed: set[str]) -> list[dict]:
        """Only tools this agent may use are ever shown to the model."""
        return [
            {"name": s.name, "description": s.description,
             "parameters": s.args_model.model_json_schema()}
            for name, s in self.tools.items() if name in allowed
        ]

    def dispatch(self, name: str, raw_args: dict, ctx: DispatchContext) -> dict:
        started = time.monotonic()
        spec = self.tools.get(name)
        if spec is None:
            raise ToolDenied(f"unknown tool: {name}")

        if name not in ctx.allowed_tools:
            self._audit(ctx, name, raw_args, allowed=False, reason="not in agent allowlist",
                        duration_ms=0)
            raise ToolDenied(f"agent is not permitted to use {name}")

        try:
            args = spec.args_model.model_validate(raw_args)
        except ValidationError as exc:
            self._audit(ctx, name, raw_args, allowed=False, reason="invalid arguments",
                        duration_ms=0)
            raise DomainError("Tool arguments did not match the schema",
                              code="invalid_tool_args") from exc

        if spec.destructive and name not in ctx.approval_checked:
            self._audit(ctx, name, raw_args, allowed=False, reason="approval required",
                        duration_ms=0)
            raise ApprovalRequired(f"{name} requires explicit approval before it runs")

        try:
            result = self._execute(spec, args, ctx)
        except PermissionError as exc:
            self._audit(ctx, name, raw_args, allowed=False, reason="path refused",
                        duration_ms=int((time.monotonic() - started) * 1000))
            raise DomainError(str(exc), code="path_refused") from exc

        self._audit(
            ctx, name, raw_args, allowed=True,
            exit_code=result.get("exit_code"),
            duration_ms=int((time.monotonic() - started) * 1000),
            output_bytes=len(json.dumps(result, default=str).encode()),
        )
        return result

    # --- handlers ---------------------------------------------------------
    def _execute(self, spec: ToolSpec, args: BaseModel, ctx: DispatchContext) -> dict:
        handler = getattr(self, f"_h_{spec.name}", None)
        if handler is None:
            raise DomainError(f"{spec.name} is declared but not implemented",
                              code="tool_not_implemented")
        return handler(args, ctx)

    def _h_read_file(self, args: ReadFileArgs, ctx: DispatchContext) -> dict:
        data = ctx.backend.read_file(ctx.handle, args.path)
        text, truncated = ctx.backend.truncate(
            data.decode("utf-8", "replace"), settings.MAX_TOOL_OUTPUT_BYTES
        )
        return {"path": args.path, "content": text, "truncated": truncated}

    def _h_write_file(self, args: WriteFileArgs, ctx: DispatchContext) -> dict:
        ctx.backend.write_file(ctx.handle, args.path, args.content.encode())
        return {"path": args.path, "bytes": len(args.content.encode())}

    def _h_edit_file(self, args: EditFileArgs, ctx: DispatchContext) -> dict:
        current = ctx.backend.read_file(ctx.handle, args.path).decode("utf-8", "replace")
        if args.find not in current:
            raise DomainError("text to replace was not found; file left unchanged",
                              code="edit_target_missing")
        ctx.backend.write_file(
            ctx.handle, args.path, current.replace(args.find, args.replace, 1).encode()
        )
        return {"path": args.path, "replacements": 1}

    def _h_list_dir(self, args: ListDirArgs, ctx: DispatchContext) -> dict:
        return {"path": args.path, "entries": ctx.backend.list_dir(ctx.handle, args.path)}

    def _h_search_code(self, args: SearchCodeArgs, ctx: DispatchContext) -> dict:
        result = ctx.backend.exec(ctx.handle, Command(
            argv=["grep", "-rn", "--include", args.glob, args.pattern, "."],
            timeout_seconds=60,
        ))
        return {"exit_code": result.exit_code, "matches": result.stdout[:50_000]}

    def _h_run_command(self, args: RunCommandArgs, ctx: DispatchContext) -> dict:
        timeout = min(args.timeout_seconds, settings.LOCAL_RUNNER_MAX_COMMAND_SECONDS)
        result = ctx.backend.exec(ctx.handle, Command(
            argv=args.argv, cwd=args.cwd, timeout_seconds=timeout
        ))
        return self._result_dict(result)

    def _h_run_tests(self, args: RunTestsArgs, ctx: DispatchContext) -> dict:
        result = ctx.backend.exec(ctx.handle, Command(
            argv=["pytest", "-q"], timeout_seconds=args.timeout_seconds
        ))
        return self._result_dict(result)

    def _h_git_status(self, args: GitStatusArgs, ctx: DispatchContext) -> dict:
        result = ctx.backend.exec(ctx.handle, Command(
            argv=["git", "status", "--short", "--branch"], timeout_seconds=30
        ))
        return self._result_dict(result)

    def _h_git_branch(self, args: GitBranchArgs, ctx: DispatchContext) -> dict:
        result = ctx.backend.exec(ctx.handle, Command(
            argv=["git", "checkout", "-b", args.name], timeout_seconds=30
        ))
        return self._result_dict(result)

    def _h_git_commit(self, args: GitCommitArgs, ctx: DispatchContext) -> dict:
        ctx.backend.exec(ctx.handle, Command(argv=["git", "add", "-A"], timeout_seconds=30))
        msg = f"{args.message}\n\n[superagent run {ctx.run_id}]"
        result = ctx.backend.exec(ctx.handle, Command(
            argv=["git", "commit", "-m", msg], timeout_seconds=60
        ))
        return self._result_dict(result)

    def _h_create_pull_request(self, args: CreatePullRequestArgs, ctx: DispatchContext) -> dict:
        # Deliberately delegated: PR creation goes through the GitHub service with
        # an installation token, not through the sandbox.
        raise DomainError(
            "create_pull_request is handled by projects.github service",
            code="delegated_tool",
        )

    @staticmethod
    def _result_dict(result: CommandResult) -> dict:
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": result.duration_ms,
            "truncated": result.truncated,
        }

    @staticmethod
    def _audit(ctx: DispatchContext, name: str, raw_args: dict, *, allowed: bool,
               reason: str = "", exit_code: int | None = None, duration_ms: int = 0,
               output_bytes: int = 0) -> None:
        try:
            ToolInvocation.objects.create(
                run_id=ctx.run_id, step_id=ctx.step_id, tool_name=name,
                args_hash=args_digest(raw_args), args_preview=redact_args(raw_args),
                allowed=allowed, denied_reason=reason[:120], exit_code=exit_code,
                duration_ms=duration_ms, output_bytes=output_bytes,
            )
        except Exception:
            # Auditing must never break the agent loop, but it must be loud.
            logger.exception("failed to write ToolInvocation audit row for %s", name)

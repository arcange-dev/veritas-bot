"""Specialist agent definitions and the parsing of what they return.

Model output is untrusted. A plan is parsed into a closed schema, capped in
size, and validated structurally before any task is created. A specialist can
never name its own tools or widen its own permissions: those come from the
server-side registry below.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from orchestration.models import AgentKind
from orchestration.routing import PlanError, validate_plan
from orchestration.state import Task

MAX_TASKS = 25
MAX_TITLE = 200
MAX_SCOPE_ENTRIES = 20
VALID_AGENTS = {k.value for k in AgentKind} - {AgentKind.ORCHESTRATOR.value}
_ID = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")


@dataclass(frozen=True)
class AgentSpec:
    kind: str
    title: str
    prompt: str
    tools: frozenset[str]


# Tool grants are server-side policy. They are never read from model output.
READ_ONLY = frozenset({"read_file", "search_code", "list_dir", "git_status", "git_diff"})
EDITOR = READ_ONLY | {"write_file", "edit_file"}
RUNNER = EDITOR | {"run_tests", "run_command", "inspect_logs"}

AGENTS: dict[str, AgentSpec] = {
    "analyst": AgentSpec("analyst", "Project Analyst",
        "Inspect the repository and summarise structure, stack, conventions and risks. "
        "You cannot modify files.", READ_ONLY),
    "architect": AgentSpec("architect", "Software Architect",
        "Design the approach: modules, interfaces, data flow, trade-offs. "
        "You cannot modify files.", READ_ONLY),
    "frontend": AgentSpec("frontend", "Frontend Engineer",
        "Implement user interface changes within your write scope only.", RUNNER),
    "backend": AgentSpec("backend", "Backend Engineer",
        "Implement server-side changes within your write scope only.", RUNNER),
    "database": AgentSpec("database", "Database Engineer",
        "Design schema and migrations. Destructive changes need approval.",
        RUNNER | {"inspect_schema"}),
    "integration": AgentSpec("integration", "Integration Engineer",
        "Connect external APIs safely. Never hard-code credentials.", RUNNER),
    "qa": AgentSpec("qa", "QA Engineer",
        "Write and run tests, report reproducible failures. Do not weaken tests.",
        READ_ONLY | {"write_file", "run_tests", "inspect_logs"}),
    "security": AgentSpec("security", "Security Engineer",
        "Review for vulnerabilities and report findings. You cannot modify files.",
        READ_ONLY | {"inspect_logs"}),
    "devops": AgentSpec("devops", "DevOps Engineer",
        "Prepare build and deployment configuration. Deploying needs approval.",
        EDITOR | {"prepare_deployment"}),
}

ORCHESTRATOR_PROMPT = (
    "You are the lead engineer. Break the objective into the smallest set of tasks that "
    "can be completed safely. Reply with JSON only: "
    '{"plan":[{"id":"t1","title":"...","agent":"<specialist>","depends_on":[],"write_scope":["path/glob"]}]}. '
    "Only delegate when the work can be done in parallel without touching the same files. "
    f"Allowed agents: {', '.join(sorted(VALID_AGENTS))}."
)


def tools_for(agent_kind: str) -> frozenset[str]:
    """Unknown agents get nothing. Fail closed."""
    spec = AGENTS.get(agent_kind)
    return spec.tools if spec else frozenset()


def _extract_json(text: str) -> Any:
    """Accept a bare object or one fenced block. Anything else is rejected."""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    try:
        return json.loads(candidate)
    except (ValueError, TypeError) as exc:
        raise PlanError("model did not return valid JSON") from exc


def _safe_scope(entry: Any) -> str:
    value = str(entry).strip()
    # A write scope is a project-relative glob. Anything that could leave the
    # project is a model trying to widen its own reach.
    if not value or value.startswith(("/", "~")) or ".." in value.split("/") or "\x00" in value:
        raise PlanError(f"unsafe write scope: {value!r}")
    return value[:200]


def parse_plan(text: str) -> list[Task]:
    data = _extract_json(text)
    if not isinstance(data, dict) or not isinstance(data.get("plan"), list):
        raise PlanError("response has no 'plan' list")

    raw_tasks = data["plan"]
    if not raw_tasks:
        raise PlanError("plan is empty")
    if len(raw_tasks) > MAX_TASKS:
        raise PlanError(f"plan has {len(raw_tasks)} tasks; the limit is {MAX_TASKS}")

    tasks: list[Task] = []
    for item in raw_tasks:
        if not isinstance(item, dict):
            raise PlanError("each task must be an object")
        task_id = str(item.get("id", "")).strip()
        agent = str(item.get("agent", "")).strip()
        if not _ID.match(task_id):
            raise PlanError(f"invalid task id: {task_id!r}")
        if agent not in VALID_AGENTS:
            raise PlanError(f"unknown agent: {agent!r}")
        scope = item.get("write_scope", []) or []
        if not isinstance(scope, list) or len(scope) > MAX_SCOPE_ENTRIES:
            raise PlanError("write_scope must be a short list")
        deps = item.get("depends_on", []) or []
        if not isinstance(deps, list):
            raise PlanError("depends_on must be a list")

        tasks.append(Task(
            id=task_id,
            title=str(item.get("title", ""))[:MAX_TITLE],
            agent=agent,
            depends_on=[str(d) for d in deps],
            # Read-only specialists get an empty scope regardless of what they ask for.
            write_scope=[] if "write_file" not in tools_for(agent)
            else [_safe_scope(s) for s in scope],
        ))

    validate_plan(tasks)
    return tasks

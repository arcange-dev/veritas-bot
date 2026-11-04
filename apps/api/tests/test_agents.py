"""Model output is untrusted: plans are parsed into a closed schema."""
from __future__ import annotations

import json

import pytest

from orchestration.agents import AGENTS, MAX_TASKS, VALID_AGENTS, parse_plan, tools_for
from orchestration.routing import PlanError


def plan(*tasks):
    return json.dumps({"plan": list(tasks)})


def task(id="t1", agent="backend", **kw):
    return {"id": id, "title": "do it", "agent": agent, **kw}


def test_valid_plan_parses_into_tasks():
    tasks = parse_plan(plan(task("t1", "analyst"), task("t2", depends_on=["t1"], write_scope=["api/"])))
    assert [t.id for t in tasks] == ["t1", "t2"]
    assert tasks[1].write_scope == ["api/"]


def test_fenced_json_is_accepted():
    wrapped = "Here you go:\n```json\n" + plan(task()) + "\n```"
    assert parse_plan(wrapped)[0].id == "t1"


@pytest.mark.parametrize("bad", ["", "not json", "[1,2]", '{"plan": "x"}', '{"plan": []}', "{}"])
def test_malformed_output_is_rejected(bad):
    with pytest.raises(PlanError):
        parse_plan(bad)


def test_unknown_and_orchestrator_agents_are_rejected():
    with pytest.raises(PlanError):
        parse_plan(plan(task(agent="root")))
    with pytest.raises(PlanError):
        parse_plan(plan(task(agent="orchestrator")))


@pytest.mark.parametrize("scope", ["/etc/passwd", "~/.ssh", "../secrets", "a/../../b"])
def test_a_model_cannot_widen_its_write_scope_outside_the_project(scope):
    with pytest.raises(PlanError, match="unsafe write scope"):
        parse_plan(plan(task(write_scope=[scope])))


def test_read_only_agents_cannot_claim_write_scope():
    tasks = parse_plan(plan(task("t1", "analyst", write_scope=["api/"])))
    assert tasks[0].write_scope == []


def test_oversized_plans_are_rejected():
    many = [task(f"t{i}") for i in range(MAX_TASKS + 1)]
    with pytest.raises(PlanError, match="limit"):
        parse_plan(plan(*many))


def test_cycles_and_dangling_dependencies_are_rejected():
    with pytest.raises(PlanError):
        parse_plan(plan(task("a", depends_on=["b"]), task("b", depends_on=["a"])))
    with pytest.raises(PlanError):
        parse_plan(plan(task("a", depends_on=["ghost"])))


def test_bad_task_ids_are_rejected():
    with pytest.raises(PlanError):
        parse_plan(plan(task("../x")))


def test_the_model_cannot_grant_itself_tools():
    """A 'tools' field in model output is ignored; grants come from the registry."""
    tasks = parse_plan(plan(task("t1", "analyst", tools=["run_command", "write_file"])))
    assert "run_command" not in tools_for(tasks[0].agent)
    assert "write_file" not in tools_for("analyst")


def test_unknown_agent_gets_no_tools():
    assert tools_for("hacker") == frozenset()


def test_read_only_specialists_have_no_mutating_tools():
    mutating = {"write_file", "edit_file", "run_command", "run_tests"}
    for kind in ("analyst", "architect", "security"):
        assert not (tools_for(kind) & mutating), kind


def test_every_specialist_is_defined():
    assert set(AGENTS) == VALID_AGENTS

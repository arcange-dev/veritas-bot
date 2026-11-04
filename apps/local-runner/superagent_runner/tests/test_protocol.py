from __future__ import annotations

import json

from superagent_runner import __version__
from superagent_runner.client import RunnerClient
from superagent_runner.config import RunnerConfig
from superagent_runner.protocol import ExecRequest, Hello, Output, PROTOCOL_VERSION


def test_hello_round_trips():
    hello = Hello(runner_version=__version__, os="linux", arch="x86_64",
                  workspace_roots=["/home/dev/code"])
    payload = json.loads(hello.model_dump_json())
    assert payload["type"] == "hello"
    assert payload["v"] == PROTOCOL_VERSION
    assert payload["workspace_roots"] == ["/home/dev/code"]


def test_exec_request_defaults():
    request = ExecRequest(id="r1", argv=["pytest", "-q"])
    assert request.cwd == "."
    assert request.timeout_seconds == 120


def test_output_frame_shape():
    frame = Output(session="s-1", stream="stdout", seq=3, data="ok\n")
    assert json.loads(frame.model_dump_json())["seq"] == 3


def test_client_builds_a_hello_with_its_workspaces(tmp_path):
    client = RunnerClient(RunnerConfig(workspace_roots=[str(tmp_path)]))
    payload = json.loads(client.build_hello())
    assert payload["workspace_roots"] == [str(tmp_path)]

    client.processes.stop_all()


def test_runner_refuses_a_path_outside_every_root(tmp_path):
    from superagent_runner.security.paths import PathRefused

    client = RunnerClient(RunnerConfig(workspace_roots=[str(tmp_path)]))
    try:
        client._workspace_for("/etc")   # noqa: SLF001 - protocol boundary under test
    except PathRefused as exc:
        assert "no approved workspace" in str(exc)
    else:
        raise AssertionError("expected PathRefused")

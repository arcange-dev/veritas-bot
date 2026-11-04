"""Process supervision: timeouts, refusal, output caps, cleanup."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from superagent_runner.config import RunnerConfig
from superagent_runner.process import ProcessManager
from superagent_runner.security.paths import Workspace


@pytest.fixture
def manager(tmp_path: Path) -> ProcessManager:
    return ProcessManager(RunnerConfig(max_command_seconds=10, max_output_bytes=2048))


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path)


def test_running_a_command_captures_output(manager, workspace):
    record = manager.run(workspace, [sys.executable, "-c", "print('hello from child')"])
    assert record.exit_code == 0
    assert "hello from child" in record.output
    assert record.duration_ms >= 0


def test_non_zero_exit_is_reported(manager, workspace):
    record = manager.run(workspace, [sys.executable, "-c", "raise SystemExit(3)"])
    assert record.exit_code == 3


def test_denied_command_is_refused_before_spawning(manager, workspace):
    with pytest.raises(PermissionError, match="refused locally"):
        manager.run(workspace, ["sudo", "ls"])


def test_ask_level_command_needs_an_approval_id(manager, workspace):
    with pytest.raises(PermissionError, match="approval required"):
        manager.run(workspace, ["git", "commit", "-m", "x"])


def test_timeout_kills_the_child(manager, workspace):
    started = time.monotonic()
    record = manager.run(
        workspace, [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_seconds=1,
    )
    elapsed = time.monotonic() - started
    assert record.exit_code == -1
    assert elapsed < 12
    assert "timed out" in record.output


def test_output_is_capped(manager, workspace):
    record = manager.run(
        workspace,
        [sys.executable, "-c", "print('x' * 20000)"],
    )
    assert len(record.output) <= 4096
    assert record.truncated is True


def test_cwd_outside_workspace_is_refused(manager, workspace):
    with pytest.raises(PermissionError): 
        manager.run(workspace, ["ls"], cwd="../../")

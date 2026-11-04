"""Path authorisation: the runner's most important security boundary."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from superagent_runner.security.paths import PathRefused, Workspace, is_within


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n")
    return Workspace(tmp_path)


def test_relative_path_resolves_inside_root(workspace: Workspace, tmp_path: Path):
    assert workspace.resolve("src/main.py") == (tmp_path / "src" / "main.py").resolve()


def test_absolute_path_inside_root_is_allowed(workspace: Workspace, tmp_path: Path):
    assert workspace.resolve(str(tmp_path / "src")) == (tmp_path / "src").resolve()


def test_parent_traversal_is_refused(workspace: Workspace):
    with pytest.raises(PathRefused, match="escapes"):
        workspace.resolve("../../etc/passwd")


def test_absolute_escape_is_refused(workspace: Workspace):
    with pytest.raises(PathRefused, match="escapes"):
        workspace.resolve("/etc/passwd")


def test_empty_and_null_byte_paths_are_refused(workspace: Workspace):
    with pytest.raises(PathRefused):
        workspace.resolve("")
    with pytest.raises(PathRefused):
        workspace.resolve("src/\x00main.py")


def test_symlink_escape_is_refused(workspace: Workspace, tmp_path: Path):
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret")
    link = tmp_path / "src" / "link.txt"
    os.symlink(outside, link)
    with pytest.raises(PathRefused):
        workspace.resolve("src/link.txt")


def test_symlink_to_inside_is_also_refused_by_default(workspace: Workspace, tmp_path: Path):
    target = tmp_path / "src" / "main.py"
    link = tmp_path / "src" / "alias.py"
    os.symlink(target, link)
    with pytest.raises(PathRefused, match="symlink"):
        workspace.resolve("src/alias.py")

    permissive = Workspace(tmp_path, allow_symlinks=True)
    assert permissive.resolve("src/alias.py") == target.resolve()


def test_root_itself_is_valid(workspace: Workspace, tmp_path: Path):
    assert workspace.resolve(".") == tmp_path.resolve()


def test_relative_returns_workspace_relative_path(workspace: Workspace):
    assert workspace.relative("src/main.py") == "src/main.py"


def test_is_within_helper(tmp_path: Path):
    inside = tmp_path / "a" / "b.txt"
    inside.parent.mkdir()
    inside.write_text("x")
    assert is_within(tmp_path, inside)
    assert not is_within(tmp_path, Path("/tmp"))

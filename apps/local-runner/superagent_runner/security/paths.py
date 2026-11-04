"""Workspace path authorisation.

Every filesystem operation resolves through `Workspace`. If a path escapes an
approved root, or passes through a symlink, it is refused before any I/O.
"""
from __future__ import annotations

import os
from pathlib import Path


class PathRefused(PermissionError):
    """Raised before any filesystem access when a path is not authorised."""


class Workspace:
    def __init__(self, root: str | os.PathLike[str], *, allow_symlinks: bool = False) -> None:
        self.root = Path(root).expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise PathRefused(f"workspace root is not a directory: {self.root}")
        self.allow_symlinks = allow_symlinks

    def resolve(self, candidate: str) -> Path:
        """Return an absolute path inside the root, or raise PathRefused."""
        if not candidate or "\x00" in candidate:
            raise PathRefused("empty or null-byte path")

        target = Path(candidate)
        if not target.is_absolute():
            target = self.root / target

        # Resolve symlinks before comparing, so a link cannot smuggle a path out.
        resolved = target.resolve()

        if resolved != self.root and self.root not in resolved.parents:
            raise PathRefused(f"path escapes the workspace: {candidate}")

        if not self.allow_symlinks and target.is_symlink():
            raise PathRefused(f"symlink refused: {candidate}")

        return resolved

    def relative(self, candidate: str) -> str:
        return str(self.resolve(candidate).relative_to(self.root))


def is_within(root: Path, candidate: Path) -> bool:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    return resolved == resolved_root or resolved_root in resolved.parents

"""Local configuration. Lives in the user's config dir, not in any project."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

APP_NAME = "superagent-runner"


def config_dir() -> Path:
    path = Path(platformdirs.user_config_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


@dataclass
class RunnerConfig:
    api_url: str = "http://localhost:8000"
    device_id: str = ""
    device_token: str = ""
    refresh_token: str = ""
    # Absolute paths the user explicitly approved. The server can read this
    # list but never add to it.
    workspace_roots: list[str] = field(default_factory=list)
    max_command_seconds: int = 900
    max_output_bytes: int = 200 * 1024

    @classmethod
    def load(cls) -> "RunnerConfig":
        path = config_path()
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        path = config_path()
        path.write_text(json.dumps(self.__dict__, indent=2))
        try:
            os.chmod(path, 0o600)          # the device token lives here
        except OSError:
            pass

    def add_root(self, raw_path: str) -> Path:
        resolved = Path(raw_path).expanduser().resolve()
        if not resolved.is_dir():
            raise NotADirectoryError(f"not a directory: {resolved}")
        if any(part == ".ssh" for part in resolved.parts):
            raise PermissionError("refusing to expose an SSH directory")
        if str(resolved) not in self.workspace_roots:
            self.workspace_roots.append(str(resolved))
            self.save()
        return resolved
